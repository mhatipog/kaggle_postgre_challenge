"""Safety and SQL compiler tests for optional sparse position materialization."""
import unittest
from pathlib import Path
from unittest.mock import patch

from services.postgres_service import PostgresAdminService
from services.expansion_stage import plan_single_pass_projection
from services.expansion_stage_typed import specialize_typed_fields
from services.expansion_sparse_positions import rewrite_sparse_positions

ROOT = Path(__file__).resolve().parents[1]
RECIPES = [
    ("01_table3.sql", "public.table3"),
    ("02_table4.sql", "public.table4"),
    ("03_table1.sql", "public.table1"),
    ("04_table5.sql", "public.table5"),
    ("05_table6.sql", "public.table6"),
    ("06_table2.sql", "public.table2"),
]


class SparsePositionTests(unittest.TestCase):
    @staticmethod
    def compiled_statement():
        destinations = [
            {
                "table_name": name,
                "version_title": "compiler test",
                "sql": (ROOT / "SQL files" / filename).read_text(),
            }
            for filename, name in RECIPES
        ]
        prepared = PostgresAdminService._prepare_cross_table_expansion(
            "public.raw_data", ["group001"], destinations
        )
        metadata = {
            name: "text" for name in (
                "raw_id", "raw_hash", "raw_schema",
                "raw_ingested_at", "raw_tab", "raw"
            )
        }
        stage = plan_single_pass_projection(prepared, metadata)
        assert stage is not None
        typed = specialize_typed_fields(prepared, stage, prune_unused_meta=True)
        assert typed.get("typed_fields", 0) >= 40
        return typed["rewritten_destinations"][5][0]

    def test_exact_supported_recipe_rewrites(self):
        original = self.compiled_statement()
        rewritten = rewrite_sparse_positions(original)
        self.assertIsNotNone(rewritten, "Supported table2 did not rewrite")
        self.assertIn("unnest(array_remove(ARRAY[", rewritten)
        self.assertEqual(rewritten.count("THEN 1::smallint"), 1)
        self.assertEqual(rewritten.count("ELSE NULL::smallint END"), 14)
        self.assertIn("JOIN public.table1 AS main_row", rewritten)
        self.assertIn("position_data.weight_text >= 0", rewritten)
        self.assertNotIn("    VALUES\n", rewritten)

    def test_unknown_predicate_preserves_original(self):
        original = self.compiled_statement()
        altered = original.replace(
            "position_data.weight_text >= 0",
            "position_data.weight_text > 0"
        )
        self.assertIsNone(rewrite_sparse_positions(altered))
        self.assertIsNone(rewrite_sparse_positions("SELECT 1"))

    def test_unknown_unpivot_mapping_preserves_original(self):
        original = self.compiled_statement()
        self.assertIsNone(rewrite_sparse_positions(
            original.replace(
                'source_row."pgdm_v_numeric_column_3"',
                'source_row."pgdm_v_numeric_column_4"', 1
            )
        ))


if __name__ == "__main__":
    unittest.main()
