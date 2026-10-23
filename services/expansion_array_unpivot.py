"""Experiment: replace fixed 14-way typed VALUES with aligned array UNNEST.

This is NOT enabled by default. The planner must have produced the exact
validated challenge table2 query; any unexpected source mapping, cast or SQL
shape leaves the original statement unchanged.
"""
from __future__ import annotations

import re

_HEADER = re.compile(
    r"CROSS\s+JOIN\s+LATERAL\s*\(\s*VALUES\s*(?P<values>.*?)"
    r"\)\s*AS\s+position_data\s*\(\s*position_number\s*,\s*"
    r"declared_number_text\s*,\s*type_text\s*,\s*weight_text\s*,\s*gap_text\s*\)",
    re.IGNORECASE | re.DOTALL,
)
_VALUE = re.compile(
    r"\(\s*(?P<pos>\d+)::smallint\s*,\s*"
    r'source_row\."pgdm_v_integer_column_(?P<decl>\d+)"\s*,\s*'
    r'source_row\."pgdm_v_text_column_(?P<kind>\d+)"\s*,\s*'
    r'source_row\."pgdm_v_numeric_column_(?P<weight>\d+)"\s*,\s*'
    r'source_row\."pgdm_v_numeric_column_(?P<gap>\d+)"\s*\)',
    re.IGNORECASE,
)

# The integer, weight and gap predicates are retained exactly in the original
# WHERE clause. Reordering or relaxing predicates is deliberately disallowed.
_FILTER = re.compile(
    r"\bWHERE\s+position_data\.declared_number_text\s*=\s*"
    r"position_data\.position_number\s+AND\s+"
    r"position_data\.weight_text\s*>=\s*0\s+AND\s+"
    r"UPPER\s*\(\s*BTRIM\s*\(\s*position_data\.type_text\s*\)\s*\)"
    r"\s+IN\s*\(\s*'X'\s*,\s*'Y'\s*,\s*'Z'\s*\)",
    re.IGNORECASE | re.DOTALL,
)


def rewrite_array_unpivot(statement: str) -> str | None:
    """Create an order-preserving, aligned typed-UNNEST candidate or fail closed."""
    matches = list(_HEADER.finditer(statement))
    if len(matches) != 1 or len(_FILTER.findall(statement)) != 1:
        return None
    match = matches[0]
    fields = list(_VALUE.finditer(match.group("values")))
    if len(fields) != 14:
        return None
    if re.fullmatch(r"[\s,]*", _VALUE.sub("", match.group("values"))) is None:
        return None
    rows = [
        (int(f["pos"]), f["decl"], f["kind"], f["weight"], f["gap"])
        for f in fields
    ]
    expected = [
        (i, str(i + 1), str(i + 3), str(2 * i + 1), str(2 * i + 2))
        for i in range(1, 15)
    ]
    if rows != expected:
        return None

    # One UNNEST of four aligned arrays reduces 14 VALUES tuples and has
    # simple, well-defined WITH ORDINALITY semantics: position_number 1..14.
    def array_column(column_type: str, field_idx: int) -> str:
        category = {
            "smallint": "integer",
            "text": "text",
            "numeric": "numeric",
        }[column_type]
        values = ", ".join(
            f'source_row."pgdm_v_{category}_column_{row[field_idx]}"'
            for row in rows
        )
        return f"ARRAY[{values}]::{column_type}[]"

    replacement = (
        "CROSS JOIN LATERAL (\n"
        "  SELECT u.ordinal_position::smallint AS position_number,\n"
        "         u.declared AS declared_number_text,\n"
        "         u.kind AS type_text,\n"
        "         u.weight AS weight_text,\n"
        "         u.gap AS gap_text\n"
        "  FROM unnest(\n"
        "       " + array_column("smallint", 1) + ",\n"
        "       " + array_column("text", 2) + ",\n"
        "       " + array_column("numeric", 3) + ",\n"
        "       " + array_column("numeric", 4) + "\n"
        "  ) WITH ORDINALITY AS u(declared, kind, weight, gap, ordinal_position)\n"
        ") AS position_data(position_number, declared_number_text, type_text, weight_text, gap_text)"
    )
    return statement[:match.start()] + replacement + statement[match.end():]
