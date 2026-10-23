"""Regression gates for the opt-in single-pass JSONB staging compiler."""
from pathlib import Path
import unittest

from services.postgres_service import PostgresAdminService
from services.expansion_stage import plan_single_pass_projection

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
                self.assertNotIn("source_row.raw", statement)
                self.assertNotIn("extracted.", statement)

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
