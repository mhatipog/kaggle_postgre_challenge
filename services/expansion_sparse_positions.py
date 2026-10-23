"""Conservative sparse-position unpivot for the official validated table2 recipe.

The original LATERAL VALUES materializes fourteen candidate position records
per raw row and filters out most of them. This experimental rewrite evaluates
the same predicates first and unnests only matching position numbers. It then
projects their type, weight, and gap using CASE expressions. It is activated
only for exactly recognized, typed, six-destination challenge SQL.
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


def _case(rows: list[tuple[int, str, str, str, str]], idx: int) -> str:
    return (
        "CASE pos.position_number\n"
        + "\n".join(
            '    WHEN %d THEN source_row."pgdm_v_%s_column_%s"'
            % (p, ("text" if idx == 2 else "numeric"), row[idx])
            for row in rows for p in [row[0]]
        )
        + "\n  END"
    )


def rewrite_sparse_positions(statement: str) -> str | None:
    """Return equivalent SQL or None if the exact supported pattern differs."""
    match = _HEADER.search(statement)
    if match is None or len(_HEADER.findall(statement)) != 1:
        return None
    values = match.group("values")
    fields = list(_VALUE.finditer(values))
    if len(fields) != 14:
        return None
    # Reject unrecognized expressions or additions, even if PostgreSQL accepts
    # them. SQL transformations must always fail closed, never guess semantics.
    remainder = _VALUE.sub("", values)
    if re.fullmatch(r"[\s,]*", remainder) is None:
        return None
    rows = []
    for m in fields:
        rows.append((
            int(m["pos"]), m["decl"], m["kind"], m["weight"], m["gap"]
        ))
    expected = [
        (i, str(i + 1), str(i + 3), str(2 * i + 1), str(2 * i + 2))
        for i in range(1, 15)
    ]
    if rows != expected:
        return None

    # The typed compiler must already have eliminated expensive conversions
    # on weight/declared/gap. Enforce this exact WHERE shape or fall back.
    where = re.compile(
        r"\bWHERE\s+position_data\.declared_number_text\s*=\s*"
        r"position_data\.position_number\s+AND\s+"
        r"position_data\.weight_text\s*>=\s*0\s+AND\s+"
        r"UPPER\s*\(\s*BTRIM\s*\(\s*position_data\.type_text\s*\)\s*\)"
        r"\s+IN\s*\(\s*'X'\s*,\s*'Y'\s*,\s*'Z'\s*\)",
        re.I | re.S,
    )
    if len(where.findall(statement)) != 1:
        return None

    checks = []
    for p, declared, kind, weight, _gap in rows:
        checks.append(
            f'CASE WHEN source_row."pgdm_v_integer_column_{decl}" = {p}::smallint\n'
            f'       AND source_row."pgdm_v_numeric_column_{weight}" >= 0\n'
            f'       AND UPPER(BTRIM(source_row."pgdm_v_text_column_{kind}"))'
            f" IN ('X', 'Y', 'Z')\n"
            f"  THEN {p}::smallint ELSE NULL::smallint END"
        )
    position_array = ",\n        ".join(checks)
    kind_case = _case(rows, 2)
    weight_case = _case(rows, 3)
    gap_case = _case(rows, 4)
    sparse = f"""CROSS JOIN LATERAL (
    SELECT
        pos.position_number,
        pos.position_number AS declared_number_text,
        {kind_case} AS type_text,
        {weight_case} AS weight_text,
        {gap_case} AS gap_text
    FROM unnest(array_remove(ARRAY[
        {position_array}
    ]::smallint[], NULL::smallint)) AS pos(position_number)
) AS position_data(position_number, declared_number_text, type_text, weight_text, gap_text)"""
    return statement[:match.start()] + sparse + statement[match.end():]
