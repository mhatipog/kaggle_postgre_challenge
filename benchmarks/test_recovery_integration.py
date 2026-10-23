#!/usr/bin/env python3
"""End-to-end crash-gap recovery exercise on the unmodified Kaggle generator.

This CI-only adapter executes the normal DB Manager service commands locally
rather than via SSH. It validates the database SQL and control-database
registration; separate Windows/SSH integration is still required for release.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.postgres_service import PostgresAdminService

ROOT = Path(__file__).resolve().parents[1]
SQL_NAMES = (
    ("01_table3.sql", "public.table3"),
    ("02_table4.sql", "public.table4"),
    ("03_table1.sql", "public.table1"),
    ("04_table5.sql", "public.table5"),
    ("05_table6.sql", "public.table6"),
    ("06_table2.sql", "public.table2"),
)


def service(user: str, password: str) -> PostgresAdminService:
    instance = PostgresAdminService()
    instance.sql_username = user
    instance.sql_password = password
    instance.postgres_port = 5432
    instance.ssh_username = "ci-local-adapter"

    def local_exec(command, stdin_text=None, cancel_event=None,
                   stdin_progress_callback=None, **kwargs):
        env = dict(os.environ)
        env["PGPASSWORD"] = password
        env["PGPORT"] = "5432"
        completed = subprocess.run(
            ["/bin/bash", "-c", command],
            input=stdin_text,
            text=True, capture_output=True, env=env,
            check=False,
        )
        if completed.returncode:
            raise RuntimeError(
                f"Service PostgreSQL command failed: {completed.stderr[:4000]} "
                f"COMMAND: {command[:1000]}"
            )
        if stdin_progress_callback:
            stdin_progress_callback(100, "Local adapter complete")
        return completed.stdout.strip()

    instance.run_remote_command = local_exec
    return instance


def query(svc: PostgresAdminService, db: str, sql: str) -> str:
    # This executes on the same local test PostgreSQL instance as the service.
    return svc.run_remote_command(
        f"psql -h localhost -U {svc.sql_username} -d {db} "
        f"-X -qAt -v ON_ERROR_STOP=1 -c {json.dumps(sql)}"
    ).strip()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--user", required=True)
    parser.add_argument("--database", default="kaggle_challenge")
    args = parser.parse_args()
    password = os.environ["PGPASSWORD"]
    svc = service(args.user, password)
    svc.ensure_admin_schema()
    query(
        svc, args.database,
        "TRUNCATE TABLE public.table2, public.table5, public.table6, "
        "public.table1, public.table4, public.table3 RESTART IDENTITY CASCADE;",
    )
    destinations = [
        {
            "table_name": table_name,
            "version_title": "Recovery integration benchmark",
            "sql": (ROOT / "SQL files" / filename).read_text(encoding="utf-8"),
        }
        for filename, table_name in SQL_NAMES
    ]
    print("Expanding all six destinations into the real PostgreSQL database.", flush=True)
    result = svc.execute_cross_table_expansion(
        database_name=args.database,
        source_full_table_name="public.raw_data",
        raw_schemas=["group001"],
        destinations=destinations,
        requested_by="CI recovery test",
        workstation_name="ci-local",
    )
    job_id = result["expansion_job_id"]
    assert len(job_id) == 32
    before_receipts = svc._get_committed_expansion_receipt(args.database, job_id)
    assert before_receipts is None, "Premature version receipt"
    marker = query(
        svc, args.database,
        "SELECT count(*) FROM pgdm_runtime.expansion_commits "
        f"WHERE job_id = '{job_id}' AND finalized_at IS NULL;",
    )
    assert marker == "1", f"Missing committed recovery marker: {marker}"
    print("Crash simulation: discarding execution result before registering versions.", flush=True)

    reconnected = service(args.user, password)
    repaired = reconnected.recover_pending_cross_table_expansions(args.database)
    assert len(repaired) == 1, f"Expected one recovery: {repaired}"
    assert {v["table_name"] for v in repaired[0]["versions"]} == {
        name for _file, name in SQL_NAMES
    }
    print("Recovered all six version records from durable journal.", flush=True)
    assert reconnected.recover_pending_cross_table_expansions(args.database) == []
    already_registered = reconnected.register_cross_table_expansion_versions(
        result, requested_by="CI recovery test", workstation_name="ci-local"
    )
    assert already_registered == repaired[0]["versions"], "Idempotent receipt lookup changed versions"
    finalized = query(
        reconnected, args.database,
        "SELECT count(*) FROM pgdm_runtime.expansion_commits "
        f"WHERE job_id = '{job_id}' AND finalized_at IS NOT NULL;",
    )
    assert finalized == "1"
    # Simulate the control transaction COMMIT succeeding, but its SSH reply
    # being lost. The next connection must detect the already-written receipt.
    query(
        reconnected, args.database,
        "TRUNCATE TABLE public.table2, public.table5, public.table6, "
        "public.table1, public.table4, public.table3 RESTART IDENTITY CASCADE;",
    )
    second = service(args.user, password)
    result_two = second.execute_cross_table_expansion(
        database_name=args.database,
        source_full_table_name="public.raw_data",
        raw_schemas=["group001"],
        destinations=destinations,
        requested_by="CI recovery test",
        workstation_name="ci-local",
    )
    job_two = result_two["expansion_job_id"]
    original_remote = second.run_remote_command

    def drop_control_reply(command, stdin_text=None, **kwargs):
        response = original_remote(command, stdin_text=stdin_text, **kwargs)
        if (
            "-d postgres_data_manager " in command
            and isinstance(stdin_text, str)
            and "Commit atomic version batch" in stdin_text
        ):
            raise ConnectionError("Simulated SSH response loss after control COMMIT")
        return response

    second.run_remote_command = drop_control_reply
    try:
        second.register_cross_table_expansion_versions(
            result_two, requested_by="CI recovery test", workstation_name="ci-local"
        )
        raise AssertionError("Expected simulated response loss")
    except ConnectionError:
        pass
    third = service(args.user, password)
    recovered_reply_loss = third.recover_pending_cross_table_expansions(args.database)
    assert len(recovered_reply_loss) == 1, recovered_reply_loss
    assert recovered_reply_loss[0]["expansion_job_id"] == job_two
    assert third.recover_pending_cross_table_expansions(args.database) == []
    dep_count = query(
        third, "postgres_data_manager",
        "SELECT count(*) FROM app_control.table_version_dependencies "
        f"WHERE dependency_payload ->> 'expansion_job_id' = '{job_two}';",
    )
    assert dep_count == "6", f"Version duplication after lost reply: {dep_count}"
    print("Recovered lost control COMMIT reply without duplicating versions.", flush=True)

    # A failing SQL step inside the data transaction must rollback everything,
    # including the recovery marker. No partial destination inserts survive.
    query(
        third, args.database,
        "TRUNCATE TABLE public.table2, public.table5, public.table6, "
        "public.table1, public.table4, public.table3 RESTART IDENTITY CASCADE;",
    )
    before_failed_journal = query(
        third, args.database,
        "SELECT count(*) FROM pgdm_runtime.expansion_commits;",
    )
    failing = service(args.user, password)
    real_remote = failing.run_remote_command

    def force_precommit_error(command, stdin_text=None, **kwargs):
        if (
            "-d kaggle_challenge " in command
            and isinstance(stdin_text, str)
            and "INSERT INTO pgdm_runtime.expansion_commits" in stdin_text
        ):
            marker = "INSERT INTO pg_temp.pgdm_expansion_timings VALUES (9000"
            assert marker in stdin_text
            stdin_text = stdin_text.replace(marker, "SELECT 1 / 0;\\n" + marker, 1)
        return real_remote(command, stdin_text=stdin_text, **kwargs)

    failing.run_remote_command = force_precommit_error
    try:
        failing.execute_cross_table_expansion(
            database_name=args.database,
            source_full_table_name="public.raw_data",
            raw_schemas=["group001"],
            destinations=destinations,
            requested_by="CI recovery test",
            workstation_name="ci-local",
        )
        raise AssertionError("Expected injected SQL failure before COMMIT")
    except RuntimeError as exc:
        assert "division by zero" in str(exc).lower(), str(exc)
    after_failed_journal = query(
        third, args.database,
        "SELECT count(*) FROM pgdm_runtime.expansion_commits;",
    )
    assert before_failed_journal == after_failed_journal
    for _filename, table_name in SQL_NAMES:
        assert query(third, args.database, f"SELECT count(*) FROM {table_name};") == "0"
    print("Simulated pre-COMMIT failure rolled back every destination and marker.", flush=True)

    print(json.dumps({
        "recovered_job": job_id,
        "version_count": len(repaired[0]["versions"]),
        "second_recovery": 0,
        "idempotent_registration": True,
        "journal_finalized": True,
        "lost_control_reply_recovered": True,
        "precommit_rollback_consistent": True,
    }, indent=2), flush=True)


if __name__ == "__main__":
    main()
