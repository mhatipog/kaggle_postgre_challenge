"""Strict compiler tests for typed array UNNEST without changing source recipes."""
import unittest
from pathlib import Path

from services.postgres_service import PostgresAdminService
from services.expansion_stage import plan_single_pass_projection
from services.expansion_stage_typed import specialize_typed_fields
from services.expansion_array_unpivot import rewrite_array_unpivot

ROOT = Path(__file__).resolve().parents[1]
RECIPES = [
    ("01_table3.sql", "public.table3"),
    ("02_table4.sql", "public.table4"),
    ("03_table1.sql", "public.table1"),
    ("04_table5.sql", "public.table5"),
    ("05_table6.sql", "public.table6"),
    ("06_table2.sql", "public.table2"),
]


class ArrayUnpivotTests(unittest.TestCase):
    @staticmethod
    def compiled():
        destinations = [
            {"table_name": name, "version_title": "unit-test",
             "sql": (ROOT / "SQL files" / path).read_text()}
            for path, name in RECIPES
        ]
        prepared = PostgresAdminService._prepare_cross_table_expansion(
            "public.raw_data", ["group001"], destinations
        )
        source_columns = {
            name: "text" for name in (
                "raw_id", "raw_hash", "raw_schema",
                "raw_ingested_at", "raw_tab", "raw",
            )
        }
        plan = plan_single_pass_projection(prepared, source_columns)
        assert plan is not None
        typed = specialize_typed_fields(prepared, plan, prune_unused_meta=True)
        assert typed.get("typed_fields", 0) >= 40
        return typed["rewritten_destinations"][5][0]

    def test_validated_table2_rewrites(self):
        original = self.compiled()
        rewritten = rewrite_array_unpivot(original)
        self.assertIsNotNone(rewritten)
        self.assertIn("pg_catalog.unnest(", rewritten)
        self.assertIn("WITH ORDINALITY", rewritten)
        self.assertEqual(rewritten.count("::smallint[]"), 1)
        self.assertEqual(rewritten.count("::numeric[]"), 2)
        self.assertEqual(rewritten.count("::text[]"), 1)
        self.assertRegex(rewritten, r"WHERE position_data\.declared_number_text\s*=\s*position_data\.position_number")
        self.assertIn("JOIN public.table1 AS main_row", rewritten)
        self.assertNotIn("    VALUES\n", rewritten)

    def test_unknown_predicates_fall_back(self):
        original = self.compiled()
        self.assertIsNone(rewrite_array_unpivot("SELECT 1"))
        self.assertIsNone(rewrite_array_unpivot(
            original.replace("position_data.weight_text >= 0",
                             "position_data.weight_text > 0")))
        self.assertIsNone(rewrite_array_unpivot(
            original.replace('source_row."pgdm_v_numeric_column_3"',
                             'source_row."pgdm_v_numeric_column_4"', 1)))


if __name__ == "__main__":
    unittest.main()
