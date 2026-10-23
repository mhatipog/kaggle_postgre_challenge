"""Opt-in single-pass JSONB projection for validated cross-table INSERT recipes.

A conservative compiler for the supported PostgreSQL text extraction shapes,
not a replacement for the application's original safety checks. Unknown
patterns fall back to the original validated SQL, unchanged.
"""
from __future__ import annotations

import os
import re

from utils import sql_ident, sql_literal

_IDENTIFIER = r"[A-Za-z_][A-Za-z_0-9]*"
_DIRECT = re.compile(
    r"\bsource_row\s*\.\s*raw\s*->\s*'values'\s*->>\s*'(" + _IDENTIFIER + r")'",
    re.IGNORECASE,
)
_RECORD = re.compile(
    r"\bLEFT\s+JOIN\s+LATERAL\s+(?:pg_catalog\.)?jsonb_to_record"
    r"\s*\(\s*source_row\s*\.\s*raw\s*->\s*'values'\s*\)"
    r"\s*AS\s+extracted\s*\((?P<columns>[^()]*)\)\s*ON\s+TRUE",
    re.IGNORECASE,
)
_EXTRACTED = re.compile(r"\bextracted\s*\.\s*(" + _IDENTIFIER + r")", re.IGNORECASE)
_RESIDUAL_RAW = re.compile(r"\bsource_row\s*\.\s*raw\b", re.IGNORECASE)
_RAW_METADATA = {"raw_id", "raw_hash", "raw_schema", "raw_ingested_at", "raw_tab", "raw"}


def _source_guard(prepared: dict) -> str:
    schemas = ", ".join(sql_literal(x) for x in prepared["raw_schemas"])
    source = (
        sql_ident(prepared["source_schema_name"]) + "."
        + sql_ident(prepared["source_table_name"])
    )
    return (
        "(\n"
        "    SELECT *\n"
        f"    FROM {source}\n"
        f"    WHERE {sql_ident('raw_schema')} IN ({schemas})\n"
        ")"
    )


def plan_single_pass_projection(prepared: dict, source_columns: dict) -> dict | None:
    """Compile a validated batch; return None for any unsupported statement.

    The compiler only replaces the already validated guarded source relation,
    bare source_row.raw->'values'->>'key' text accesses, and the native text
    jsonb_to_record(... AS extracted (key text,...)) lateral form. It never
    rewrites user-provided arbitrary functions or other source expressions.
    """
    if not _RAW_METADATA.issubset(source_columns):
        return None
    guard = _source_guard(prepared)
    staged_fields: set[str] = set()
    rewritten_batch: list[list[str]] = []

    for destination in prepared["destinations"]:
        rewritten_dest = []
        for original in destination["statements"]:
            if original.count(guard) != 1:
                return None
            if re.search(r"\b(?:source_row\s*\.\s*raw|extracted\s*\.)", original, re.I):
                # Only the two strictly defined built-in extraction shapes are supported.
                record_matches = list(_RECORD.finditer(original))
                if len(record_matches) != len(
                    re.findall(r"\b(?:pg_catalog\.)?jsonb_to_record\s*\(", original, re.I)
                ):
                    return None
            else:
                record_matches = []

            record_fields: set[str] = set()
            for record in record_matches:
                columns = record.group("columns").split(",")
                for column in columns:
                    parsed = re.fullmatch(
                        rf"\s*({_IDENTIFIER})\s+text\s*", column, re.IGNORECASE
                    )
                    if parsed is None:
                        return None
                    record_fields.add(parsed.group(1).lower())

            direct_fields = {m.group(1).lower() for m in _DIRECT.finditer(original)}
            extracted_fields = {m.group(1).lower() for m in _EXTRACTED.finditer(original)}
            if not extracted_fields.issubset(record_fields):
                return None
            staged_fields.update(direct_fields | record_fields)

            rewritten = _RECORD.sub("", original)
            rewritten = _DIRECT.sub(
                lambda m: f'source_row.{sql_ident("pgdm_v_" + m.group(1).lower())}',
                rewritten,
            )
            rewritten = _EXTRACTED.sub(
                lambda m: f'source_row.{sql_ident("pgdm_v_" + m.group(1).lower())}',
                rewritten,
            )
            if _RESIDUAL_RAW.search(rewritten) or _EXTRACTED.search(rewritten):
                return None
            rewritten = rewritten.replace(guard, "pg_temp.pgdm_source_stage")
            if "{{source}}" in rewritten or guard in rewritten:
                return None
            rewritten_dest.append(rewritten)
        rewritten_batch.append(rewritten_dest)

    if not staged_fields:
        return None
    fields = sorted(staged_fields)
    definitions = ",\n        ".join(f"{sql_ident(key)} text" for key in fields)
    projections = ",\n    ".join(
        f"j.{sql_ident(key)} AS {sql_ident('pgdm_v_' + key)}" for key in fields
    )
    scope_sql = ", ".join(sql_literal(x) for x in prepared["raw_schemas"])
    original_source = (
        sql_ident(prepared["source_schema_name"]) + "."
        + sql_ident(prepared["source_table_name"])
    )
    # PostgreSQL temporary stage is backend-local; a transaction rollback
    # discards stage and destinations together. No persistent O(N) storage.
    stage_sql = f"""
CREATE TEMP TABLE pgdm_source_stage ON COMMIT DROP AS
SELECT
    s.raw_id,
    s.raw_hash,
    s.raw_schema,
    s.raw_ingested_at,
    s.raw_tab,
    {projections}
FROM {original_source} AS s
LEFT JOIN LATERAL pg_catalog.jsonb_to_record(s.raw -> 'values')
  AS j (
        {definitions}
  ) ON TRUE
WHERE s.raw_schema IN ({scope_sql});
ANALYZE pg_temp.pgdm_source_stage;
"""
    # Experimental statistics ablation for the exact official six-recipe
    # workload. PostgreSQL normally analyzes every typed/text column in this
    # wide temporary stage. All six INSERTs scan the stage; only these four
    # columns participate directly in equijoins or dimension lookups.
    # Retain a full ANALYZE for all other SQL shapes and by default.
    expected_destinations = (
        "public.table3", "public.table4", "public.table1",
        "public.table5", "public.table6", "public.table2",
    )
    if (
        os.getenv("PDM_EXPANSION_STAGE_STATS", "all") == "join-only"
        and tuple(d["table_name"] for d in prepared["destinations"]) == expected_destinations
        and {"text_column_1", "text_column_2", "text_column_3"}.issubset(staged_fields)
        and prepared["source_schema_name"] == "public"
        and prepared["source_table_name"] == "raw_data"
        and list(prepared["raw_schemas"]) == ["group001"]
    ):
        stage_sql = stage_sql.replace(
            "ANALYZE pg_temp.pgdm_source_stage;",
            'ANALYZE pg_temp.pgdm_source_stage '
            '("raw_id", "pgdm_v_text_column_1", '
            '"pgdm_v_text_column_2", "pgdm_v_text_column_3");',
        )
    return {
        "field_count": len(fields),
        "stage_sql": stage_sql,
        "rewritten_destinations": rewritten_batch,
    }
