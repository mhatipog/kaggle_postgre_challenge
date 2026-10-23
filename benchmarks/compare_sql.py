#!/usr/bin/env python3
"""SQL-only A/B benchmark on an unmodified official Kaggle-generated database.

Requires the challenge generator to have created kaggle_challenge, all six
destination tables empty or reusable, and a PostgreSQL CLI connection.
Exercises PostgreSQL statement execution, not the Windows GUI, SSH
transport, or the DB Manager's control-database version registration.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SQL_NAMES = (
    "01_table3.sql",
    "02_table4.sql",
    "03_table1.sql",
    "04_table5.sql",
    "05_table6.sql",
    "06_table2.sql",
)
SIGNATURES = {
    "table3": "SELECT to_jsonb(t) - 'id_column_1' AS payload FROM public.table3 t",
    "table4": "SELECT to_jsonb(t) AS payload FROM public.table4 t",
    "table1": (
        "SELECT (to_jsonb(t) - 'id_column_1' - 'id_column_4') "
        "|| jsonb_build_object('dimension', to_jsonb(d) - 'id_column_1') AS payload "
        "FROM public.table1 t LEFT JOIN public.table3 d "
        "ON t.id_column_4 = d.id_column_1"
    ),
    "table5": (
        "SELECT (to_jsonb(t) - 'id_column_1' - 'id_column_2') "
        "|| jsonb_build_object('source_raw_id', m.id_column_3) AS payload "
        "FROM public.table5 t JOIN public.table1 m ON t.id_column_2 = m.id_column_1"
    ),
    "table6": (
        "SELECT (to_jsonb(t) - 'id_column_1' - 'id_column_2') "
        "|| jsonb_build_object('source_raw_id', m.id_column_3) AS payload "
        "FROM public.table6 t JOIN public.table1 m ON t.id_column_2 = m.id_column_1"
    ),
    "table2": (
        "SELECT (to_jsonb(t) - 'id_column_1' - 'id_column_2') "
        "|| jsonb_build_object('source_raw_id', m.id_column_3) AS payload "
        "FROM public.table2 t JOIN public.table1 m ON t.id_column_2 = m.id_column_1"
    ),
}


def psql(statement: str, args: argparse.Namespace) -> str:
    command = [
        "psql", "-X", "-qAt", "-v", "ON_ERROR_STOP=1",
        "-h", args.host, "-p", str(args.port),
        "-U", args.user, "-d", args.database,
        "-f", "-",
    ]
    completed = subprocess.run(
        command, input=statement, text=True, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, env=os.environ.copy(), check=False,
    )
    if completed.returncode:
        raise RuntimeError(
            f"PostgreSQL command failed (status {completed.returncode}): "
            + completed.stderr.strip()[:5000]
        )
    return completed.stdout.strip()


def prepare_source(args: argparse.Namespace) -> str:
    values = psql(
        "SELECT DISTINCT raw_schema FROM public.raw_data ORDER BY raw_schema;",
        args,
    ).splitlines()
    if not values or any(not value for value in values):
        raise RuntimeError("Official dataset has no valid raw_schema scope")
    scope = ", ".join("'" + name.replace("'", "''") + "'" for name in values)
    return f"(SELECT * FROM public.raw_data WHERE raw_schema IN ({scope}))"


def fingerprint(table: str, args: argparse.Namespace) -> dict:
    sql = (
        "WITH normalized AS (" + SIGNATURES[table] + ") "
        "SELECT json_build_object("
        "'rows',count(*),"
        "'hash_a',COALESCE(sum(('x' || substr(md5(payload::text),1,16))::bit(64)::bigint),0)::text,"
        "'hash_b',COALESCE(sum(('x' || substr(md5(payload::text),17,16))::bit(64)::bigint),0)::text"
        ")::text FROM normalized;"
    )
    return json.loads(psql(sql, args))


def run_case(mode: str, args: argparse.Namespace, source: str) -> dict:
    psql(
        "TRUNCATE TABLE public.table2, public.table5, public.table6, "
        "public.table1, public.table4, public.table3 RESTART IDENTITY CASCADE;",
        args,
    )
    durations = {}
    total_wall_start = time.perf_counter()
    for filename in SQL_NAMES:
        target = ROOT / "SQL files" / filename
        if mode == "baseline" and filename in {"03_table1.sql", "06_table2.sql"}:
            target = ROOT / "benchmarks" / "original_sql" / filename
        sql = target.read_text(encoding="utf-8").strip().rstrip(";")
        if sql.count("{{source}}") != 1:
            raise RuntimeError(f"Unexpected protected source placeholder in {target}")
        statement = sql.replace("{{source}}", source) + ";"
        output = psql(
            "EXPLAIN (ANALYZE, FORMAT JSON, TIMING OFF) " + statement,
            args,
        )
        data = json.loads(output)
        duration = float(data[0]["Execution Time"]) / 1000.0
        durations[filename] = duration
        print(f"{mode}: {filename} {duration:.3f} s", flush=True)
    wall = time.perf_counter() - total_wall_start
    signatures = {name: fingerprint(name, args) for name in SIGNATURES}
    return {
        "mode": mode,
        "postgres_execution_seconds": round(sum(durations.values()), 6),
        "wall_seconds": round(wall, 6),
        "statements_seconds": durations,
        "signatures": signatures,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5432)
    parser.add_argument("--user", required=True)
    parser.add_argument("--database", default="kaggle_challenge")
    parser.add_argument("--out", type=Path, default=Path("benchmark_results.json"))
    parser.add_argument("--repeats", type=int, default=1)
    args = parser.parse_args()
    if args.repeats not in (1, 2):
        parser.error("repeats must be 1 or 2")
    source = prepare_source(args)
    order = ["baseline", "optimized"]
    if args.repeats == 2:
        order += ["optimized", "baseline"]
    results = []
    reference = None
    for mode in order:
        result = run_case(mode, args, source)
        if reference is None:
            reference = result["signatures"]
        elif reference != result["signatures"]:
            errors = [
                table for table in SIGNATURES
                if reference[table] != result["signatures"][table]
            ]
            raise AssertionError(
                f"Output mismatch against baseline: {errors}. "
                "Do not submit without investigation."
            )
        results.append(result)
    summary = {
        "scope": "PostgreSQL-only EXPLAIN ANALYZE; not official MEASURED PROCESSING TOTAL",
        "source_rows": int(psql("SELECT count(*) FROM public.raw_data;", args)),
        "runs": results,
        "fingerprints_equal": True,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({
        "source_rows": summary["source_rows"],
        "runs": [
            {"mode": r["mode"], "postgres_execution_seconds": r["postgres_execution_seconds"]}
            for r in results
        ],
        "fingerprints_equal": True,
    }, indent=2), flush=True)


if __name__ == "__main__":
    main()
