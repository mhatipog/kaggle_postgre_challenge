INSERT INTO public.table2 (
    id_column_2,
    integer_column_1,
    integer_column_2,
    text_column_1,
    integer_column_3,
    integer_column_4,
    integer_column_5,
    integer_column_6
)
SELECT
    main_row.id_column_1,
    position_data.position_number,
    ROUND(
        NULLIF(BTRIM(position_data.weight_text), '')::numeric * 1000
    )::integer,
    UPPER(BTRIM(position_data.type_text)),
    NULL::integer,
    NULL::integer,
    NULL::integer,
    CASE
        WHEN NULLIF(BTRIM(position_data.gap_text), '')::numeric > 0
        THEN ROUND(
            NULLIF(BTRIM(position_data.gap_text), '')::numeric * 1000
        )::integer
        ELSE NULL::integer
    END
FROM {{source}} AS source_row
LEFT JOIN LATERAL pg_catalog.jsonb_to_record(
    source_row.raw -> 'values'
) AS extracted (
    integer_column_10 text,
    integer_column_11 text,
    integer_column_12 text,
    integer_column_13 text,
    integer_column_14 text,
    integer_column_15 text,
    integer_column_2 text,
    integer_column_3 text,
    integer_column_4 text,
    integer_column_5 text,
    integer_column_6 text,
    integer_column_7 text,
    integer_column_8 text,
    integer_column_9 text,
    numeric_column_10 text,
    numeric_column_11 text,
    numeric_column_12 text,
    numeric_column_13 text,
    numeric_column_14 text,
    numeric_column_15 text,
    numeric_column_16 text,
    numeric_column_17 text,
    numeric_column_18 text,
    numeric_column_19 text,
    numeric_column_20 text,
    numeric_column_21 text,
    numeric_column_22 text,
    numeric_column_23 text,
    numeric_column_24 text,
    numeric_column_25 text,
    numeric_column_26 text,
    numeric_column_27 text,
    numeric_column_28 text,
    numeric_column_29 text,
    numeric_column_3 text,
    numeric_column_30 text,
    numeric_column_4 text,
    numeric_column_5 text,
    numeric_column_6 text,
    numeric_column_7 text,
    numeric_column_8 text,
    numeric_column_9 text,
    text_column_10 text,
    text_column_11 text,
    text_column_12 text,
    text_column_13 text,
    text_column_14 text,
    text_column_15 text,
    text_column_16 text,
    text_column_17 text,
    text_column_4 text,
    text_column_5 text,
    text_column_6 text,
    text_column_7 text,
    text_column_8 text,
    text_column_9 text
) ON TRUE
CROSS JOIN LATERAL (
    VALUES
        (1::smallint, extracted.integer_column_2, extracted.text_column_4, extracted.numeric_column_3, extracted.numeric_column_4),
        (2::smallint, extracted.integer_column_3, extracted.text_column_5, extracted.numeric_column_5, extracted.numeric_column_6),
        (3::smallint, extracted.integer_column_4, extracted.text_column_6, extracted.numeric_column_7, extracted.numeric_column_8),
        (4::smallint, extracted.integer_column_5, extracted.text_column_7, extracted.numeric_column_9, extracted.numeric_column_10),
        (5::smallint, extracted.integer_column_6, extracted.text_column_8, extracted.numeric_column_11, extracted.numeric_column_12),
        (6::smallint, extracted.integer_column_7, extracted.text_column_9, extracted.numeric_column_13, extracted.numeric_column_14),
        (7::smallint, extracted.integer_column_8, extracted.text_column_10, extracted.numeric_column_15, extracted.numeric_column_16),
        (8::smallint, extracted.integer_column_9, extracted.text_column_11, extracted.numeric_column_17, extracted.numeric_column_18),
        (9::smallint, extracted.integer_column_10, extracted.text_column_12, extracted.numeric_column_19, extracted.numeric_column_20),
        (10::smallint, extracted.integer_column_11, extracted.text_column_13, extracted.numeric_column_21, extracted.numeric_column_22),
        (11::smallint, extracted.integer_column_12, extracted.text_column_14, extracted.numeric_column_23, extracted.numeric_column_24),
        (12::smallint, extracted.integer_column_13, extracted.text_column_15, extracted.numeric_column_25, extracted.numeric_column_26),
        (13::smallint, extracted.integer_column_14, extracted.text_column_16, extracted.numeric_column_27, extracted.numeric_column_28),
        (14::smallint, extracted.integer_column_15, extracted.text_column_17, extracted.numeric_column_29, extracted.numeric_column_30)
) AS position_data(position_number, declared_number_text, type_text, weight_text, gap_text)
JOIN public.table1 AS main_row
  ON main_row.id_column_3 = source_row.raw_id
WHERE NULLIF(BTRIM(position_data.declared_number_text), '')::smallint
        = position_data.position_number
  AND NULLIF(BTRIM(position_data.weight_text), '')::numeric >= 0
  AND UPPER(BTRIM(position_data.type_text)) IN ('X', 'Y', 'Z');
