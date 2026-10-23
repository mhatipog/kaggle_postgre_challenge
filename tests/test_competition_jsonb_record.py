"""Regression checks for the competition JSONB extraction optimization.

Run: python -m unittest -v tests.test_competition_jsonb_record
Requires the project's normal Python dependencies; no database connection.
"""
import re
import unittest
from pathlib import Path

from services.postgres_service import PostgresAdminService


ROOT = Path(__file__).resolve().parents[1]


class CompetitionJsonbRecordTests(unittest.TestCase):
    def test_optimized_recipes_preserve_scoped_source_and_columns(self):
        for filename, dest, count in (
            ("03_table1.sql", "table1", 20),
            ("06_table2.sql", "table2", 56),
        ):
            with self.subTest(filename=filename):
                sql = (ROOT / "SQL files" / filename).read_text(encoding="utf-8")
                self.assertEqual(sql.count("{{source}}"), 1)
                self.assertEqual(sql.count("jsonb_to_record"), 1)
                self.assertIn("LEFT JOIN LATERAL", sql)
                self.assertIn("ON TRUE", sql)
                self.assertNotIn("source_row.raw -> 'values' ->>", sql)
                declarations = re.search(
                    r"AS extracted\s*\((.*?)\)\s*ON TRUE",
                    sql, re.DOTALL,
                )
                self.assertIsNotNone(declarations)
                declared = re.findall(
                    r"([a-z][a-z0-9_]*)\s+text", declarations.group(1),
                )
                self.assertEqual(len(declared), count)
                prepared = PostgresAdminService._prepare_cross_table_expansion_statement(
                    sql.strip().rstrip(";"), "public", "raw_data",
                    "public", dest, ["SYNTHETIC"],
                    allowed_read_relations={("public", "table1"), ("public", "table3")},
                )
                self.assertIn("SELECT", prepared["statement"].upper())
                self.assertIn(("pg_catalog", "jsonb_to_record"), prepared["function_references"])

    def test_only_exact_scoped_builtin_text_extraction_is_accepted(self):
        fn = PostgresAdminService._is_safe_text_jsonb_record_recipe
        safe = (
            "FROM {{source}} AS source_row LEFT JOIN LATERAL "
            "pg_catalog.jsonb_to_record(source_row.raw -> 'values') "
            "AS extracted (integer_column_2 text, text_column_4 text) ON TRUE"
        )
        self.assertTrue(fn(safe))
        for bad in (
            safe.replace("text_column_4 text", "text_column_4 my_custom_type"),
            safe.replace("source_row.raw -> 'values'", "evil_function()"),
            safe.replace("pg_catalog.jsonb_to_record", "jsonb_to_record"),
            safe.replace("integer_column_2 text, text_column_4 text",
                         "integer_column_2 text, integer_column_2 text"),
            safe + " CROSS JOIN pg_catalog.jsonb_to_record('{}') AS x (t text)",
        ):
            with self.subTest(bad=bad):
                self.assertFalse(fn(bad))


if __name__ == "__main__":
    unittest.main()
