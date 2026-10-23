#!/usr/bin/env python3
"""Snapshot and verify PostgreSQL constraints/index definitions.

The fast bulk path may defer FK checks *inside* its transaction, but must
restore all constraint definitions and index properties before COMMIT.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess

SQL = """
WITH properties AS (
    SELECT 'constraint' AS kind,
           c.conrelid::regclass::text AS parent,
           c.conname AS name,
           pg_get_constraintdef(c.oid, true) AS definition,
           c.convalidated::text AS valid
    FROM pg_constraint c
    WHERE c.conrelid IN (
        'public.table1'::regclass, 'public.table2'::regclass,
        'public.table3'::regclass, 'public.table4'::regclass,
        'public.table5'::regclass, 'public.table6'::regclass
    )
    UNION ALL
    SELECT 'index', schemaname || '.' || tablename,
           indexname, indexdef, 'true'
    FROM pg_indexes
    WHERE schemaname='public'
      AND tablename IN ('table1','table2','table3','table4','table5','table6')
)
SELECT json_agg(json_build_object(
    'kind',kind,'table',parent,'name',name,'ddl',definition,'valid',valid)
    ORDER BY kind,parent,name)::text FROM properties;
"""

def snapshot():
    r = subprocess.run(
        ["psql", "-X", "-qAt", "-v", "ON_ERROR_STOP=1",
         "-h", "127.0.0.1", "-U", os.environ["PDM_BENCH_PG_USER"],
         "-d", "kaggle_challenge"],
        input=SQL, text=True, capture_output=True, check=True,
    )
    data = json.loads(r.stdout.strip())
    if not data:
        raise AssertionError("Missing constraints / indexes")
    if not any(row["kind"]=="constraint" and "FOREIGN KEY" in row["ddl"] for row in data):
        raise AssertionError("Foreign keys not found in target schema")
    return data

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True, type=Path)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    actual = snapshot()
    if args.verify:
        expected = json.loads(args.file.read_text())
        if actual != expected:
            missing = [x for x in expected if x not in actual]
            extra = [x for x in actual if x not in expected]
            raise AssertionError(f"Schema mismatch: missing={missing}, extra={extra}")
        print(f"PASS: {len(actual)} index and constraint definitions unchanged")
    else:
        args.file.parent.mkdir(parents=True, exist_ok=True)
        args.file.write_text(json.dumps(actual, indent=2)+"\n")
        print(f"Saved {len(actual)} index and constraint definitions")

if __name__=="__main__":
    main()
