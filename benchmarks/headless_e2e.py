#!/usr/bin/env python3
"""Headless end-to-end expansion measurement and logical-output verification.

Runs the same PostgresAdminService methods as the GUI expansion worker over
real localhost SSH -> Linux PostgreSQL. The official generator and SQL recipes
remain unchanged. Fingerprinting happens *after* the timed operation.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import resource
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services.postgres_service import PostgresAdminService  # noqa: E402
from benchmarks.compare_sql import SIGNATURES  # noqa: E402

DESTINATIONS = [
    ("01_table3.sql", "public.table3"),
    ("02_table4.sql", "public.table4"),
    ("03_table1.sql", "public.table1"),
    ("04_table5.sql", "public.table5"),
    ("05_table6.sql", "public.table6"),
    ("06_table2.sql", "public.table2"),
]


def fingerprint() -> dict:
    """Surrogate-independent, order-independent dual MD5 sums + row counts."""
    results = {}
    for name, normalized_query in SIGNATURES.items():
        sql = (
            "WITH normalized AS (" + normalized_query + ") "
            "SELECT json_build_object("
            "'rows',COUNT(*),"
            "'hash_a',COALESCE(sum(('x'||substr(md5(payload::text),1,16))"
            "::bit(64)::bigint),0)::text,"
            "'hash_b',COALESCE(sum(('x'||substr(md5(payload::text),17,16))"
            "::bit(64)::bigint),0)::text"
            ")::text FROM normalized;"
        )
        result = subprocess.run(
            ["psql", "-h", "127.0.0.1", "-U", os.environ["PDM_BENCH_PG_USER"],
             "-d", "kaggle_challenge", "-X", "-qAt", "-v", "ON_ERROR_STOP=1"],
            input=sql, text=True, capture_output=True, check=True,
        )
        results[name] = json.loads(result.stdout.strip())
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--out-dir", default="benchmark_comparison")
    parser.add_argument("--inspect-only", action="store_true")
    args = parser.parse_args()
    output_dir = Path(args.out_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    record = {"label": args.label, "database": "kaggle_challenge"}
    if not args.inspect_only:
        svc = PostgresAdminService()
        svc.connect(
            host="127.0.0.1",
            ssh_port=2222,
            ssh_username=os.environ["PDM_BENCH_SSH_USER"],
            ssh_password=os.environ["PDM_BENCH_PASSWORD"],
            postgres_port=5432,
            sql_username=os.environ["PDM_BENCH_PG_USER"],
            sql_password=os.environ["PDM_BENCH_PASSWORD"],
        )
        try:
            destinations = [
                {
                    "table_name": table,
                    "version_title": "reproduction " + args.label,
                    "sql": (ROOT / "SQL files" / filename).read_text(encoding="utf-8"),
                }
                for filename, table in DESTINATIONS
            ]
            report = svc.create_cross_table_expansion_timing_report(
                "kaggle_challenge", "public.raw_data", ["group001"],
                [table for _, table in DESTINATIONS],
            )
            started = time.perf_counter()
            svc.ensure_admin_schema()
            result = svc.execute_cross_table_expansion(
                database_name="kaggle_challenge",
                source_full_table_name="public.raw_data",
                raw_schemas=["group001"],
                destinations=destinations,
                timing_report=report,
                requested_by="CI benchmark",
                workstation_name=socket.gethostname(),
            )
            svc.register_cross_table_expansion_versions(
                expansion_result=result,
                requested_by="CI benchmark",
                workstation_name=socket.gethostname(),
                timing_report=report,
            )
            record["wall_seconds"] = round(time.perf_counter() - started, 5)
            record["measured_processing_total"] = round(sum(
                max(float(item.get("seconds") or 0), 0)
                for item in report.get("items", [])
                if item.get("include_in_total", True)
            ), 5)
            record["source_rows"] = report.get("source_rows")
            record["total_rows_inserted"] = report.get("total_rows_inserted")
            record["stages"] = {}
            for entry in report.get("items", []):
                if entry.get("include_in_total", True):
                    stage = entry.get("stage") or "other"
                    record["stages"][stage] = round(
                        record["stages"].get(stage, 0)
                        + float(entry.get("seconds") or 0), 5
                    )
            record["items"] = report.get("items", [])
        finally:
            svc.close()
    record["signatures"] = fingerprint()
    record["peak_python_rss_kb"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    (output_dir / (args.label + ".json")).write_text(
        json.dumps(record, indent=2, sort_keys=True), encoding="utf-8"
    )
    if record.get("items"):
        # The application's scored metric is distinct from validation wall time.
        # Print the ten largest measured stages to guide controlled profiling.
        stages = sorted(
            (i for i in record["items"] if i.get("include_in_total", True)),
            key=lambda item: float(item.get("seconds") or 0), reverse=True,
        )[:10]
        print("SCORED_STAGE_BREAKDOWN " + json.dumps([
            {"name": item.get("name"), "stage": item.get("stage"),
             "seconds": round(float(item.get("seconds") or 0), 4)}
            for item in stages
        ]), flush=True)
    print(json.dumps({
        "label": args.label,
        "measured_processing_total": record.get("measured_processing_total"),
        "wall_seconds": record.get("wall_seconds"),
        "rows": {name: d["rows"] for name, d in record["signatures"].items()},
        "peak_python_rss_kb": record["peak_python_rss_kb"],
    }, indent=2), flush=True)


if __name__ == "__main__":
    main()
