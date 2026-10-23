"""Regression gates for the opt-in single-pass JSONB staging compiler."""
from pathlib import Path
from unittest.mock import patch
import unittest

from services.postgres_service import PostgresAdminService
from services.expansion_stage import plan_single_pass_projection
from services.expansion_stage_typed import specialize_typed_fields

ROOT = Path(__file__).resolve().parents[1]
RECIPES = [
    ("01_table3.sql", "public.table3"),
    ("02_table4.sql", "public.table4"),
    ("03_table1.sql", "public.table1"),
    ("04_table5.sql", "public.table5"),
    ("05_table6.sql", "public.table6"),
    ("06_table2.sql", "public.table2"),
]


class SinglePassSourceTest(unittest.TestCase):
    def make_prepared(self):
        dest = [
            {"table_name": target, "version_title": "unit-test",
             "sql": (ROOT / "SQL files" / filename).read_text()}
            for filename, target in RECIPES
        ]
        return PostgresAdminService._prepare_cross_table_expansion(
            "public.raw_data", ["group001"], dest
        )

    def source_columns(self):
        return {name: "text" for name in (
            "raw_id", "raw_hash", "raw_schema", "raw_ingested_at", "raw_tab", "raw"
        )}

    def test_six_recipes_use_one_source_projection(self):
        plan = plan_single_pass_projection(
            self.make_prepared(), self.source_columns()
        )
        self.assertIsNotNone(plan)
        self.assertEqual(len(plan["rewritten_destinations"]), 6)
        self.assertGreaterEqual(plan["field_count"], 50)
        self.assertIn("jsonb_to_record", plan["stage_sql"])
        self.assertIn("ON COMMIT DROP", plan["stage_sql"])
        for destinations in plan["rewritten_destinations"]:
            for statement in destinations:
                self.assertIn("pg_temp.pgdm_source_stage", statement)
                self.assertNotRegex(statement, r"\bsource_row\.raw\b")
                self.assertNotIn("extracted.", statement)

    def test_stage_statistics_opt_in_only_and_safe_fallback(self):
        prepared = self.make_prepared()
        default = plan_single_pass_projection(prepared, self.source_columns())
        self.assertIn("ANALYZE pg_temp.pgdm_source_stage;", default["stage_sql"])
        with patch.dict("os.environ", {"PDM_EXPANSION_STAGE_STATS": "join-only"}):
            specialized = plan_single_pass_projection(prepared, self.source_columns())
        self.assertIn('"raw_id", "pgdm_v_text_column_1"', specialized["stage_sql"])
        self.assertNotIn("ANALYZE pg_temp.pgdm_source_stage;", specialized["stage_sql"])
        prepared["raw_schemas"] = ["another_scope"]
        with patch.dict("os.environ", {"PDM_EXPANSION_STAGE_STATS": "join-only"}):
            fallback = plan_single_pass_projection(prepared, self.source_columns())
        self.assertIsNone(fallback, "Unexpected source scope must fail safe")

    def test_typed_specialization_preserves_validated_structure(self):
        prepared = self.make_prepared()
        original = plan_single_pass_projection(prepared, self.source_columns())
        typed = specialize_typed_fields(prepared, original)
        self.assertGreaterEqual(typed.get("typed_fields", 0), 40)
        self.assertIn("::numeric AS", typed["stage_sql"])
        self.assertIn("::smallint AS", typed["stage_sql"])
        self.assertNotIn("BTRIM(position_data.weight_text)", typed["rewritten_destinations"][5][0])
        self.assertNotIn("BTRIM(position_data.declared_number_text)", typed["rewritten_destinations"][5][0])
        self.assertIn("pg_temp.pgdm_source_stage", typed["rewritten_destinations"][5][0])

    def test_typed_stage_prunes_unused_metadata_when_requested(self):
        prepared = self.make_prepared()
        stage = plan_single_pass_projection(prepared, self.source_columns())
        with patch.dict("os.environ", {"PDM_EXPANSION_PRUNE_STAGE_META": "1"}):
            typed = specialize_typed_fields(prepared, stage)
        self.assertIn("s.raw_id,", typed["stage_sql"])
        for unused in ("raw_hash", "raw_schema", "raw_ingested_at", "raw_tab"):
            self.assertNotIn(f"    s.{unused},", typed["stage_sql"])
        self.assertIn("WHERE s.raw_schema IN", typed["stage_sql"])

    def test_typed_optimization_falls_back_for_unexpected_expression(self):
        prepared = self.make_prepared()
        plan = plan_single_pass_projection(prepared, self.source_columns())
        plan["rewritten_destinations"][2][0] += (
            ' AND source_row."pgdm_v_integer_column_2" IS NOT NULL'
        )
        self.assertIs(specialize_typed_fields(prepared, plan), plan)

    def test_unknown_source_expression_requires_safe_fallback(self):
        prepared = self.make_prepared()
        prepared["destinations"][0]["statements"][0] += (
            " AND source_row.raw -> 'other' IS NOT NULL"
        )
        self.assertIsNone(
            plan_single_pass_projection(prepared, self.source_columns())
        )

    def test_incomplete_source_metadata_requires_safe_fallback(self):
        self.assertIsNone(
            plan_single_pass_projection(self.make_prepared(), {"raw_schema": "text"})
        )


if __name__ == "__main__":
    unittest.main()
