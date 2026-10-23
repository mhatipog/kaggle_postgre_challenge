INSERT INTO public.table1 (
    id_column_2,
    text_column_1,
    datetime_column_1,
    text_column_2,
    integer_column_1,
    integer_column_2,
    integer_column_3,
    text_column_3,
    id_column_3,
    id_column_4,
    id_column_5,
    integer_column_4,
    integer_column_5,
    id_column_6,
    integer_column_6,
    integer_column_7
)
SELECT
    NULLIF(BTRIM(extracted.id_column_1), '')::integer,
    NULL::character varying,
    NULLIF(BTRIM(extracted.datetime_column_1), '')::timestamptz
        AT TIME ZONE 'America/Sao_Paulo',
    NULL::character varying,
    GREATEST(
        NULLIF(BTRIM(extracted.integer_column_2), '')::smallint,
        NULLIF(BTRIM(extracted.integer_column_3), '')::smallint,
        NULLIF(BTRIM(extracted.integer_column_4), '')::smallint,
        NULLIF(BTRIM(extracted.integer_column_5), '')::smallint,
        NULLIF(BTRIM(extracted.integer_column_6), '')::smallint,
        NULLIF(BTRIM(extracted.integer_column_7), '')::smallint,
        NULLIF(BTRIM(extracted.integer_column_8), '')::smallint,
        NULLIF(BTRIM(extracted.integer_column_9), '')::smallint,
        NULLIF(BTRIM(extracted.integer_column_10), '')::smallint,
        NULLIF(BTRIM(extracted.integer_column_11), '')::smallint,
        NULLIF(BTRIM(extracted.integer_column_12), '')::smallint,
        NULLIF(BTRIM(extracted.integer_column_13), '')::smallint,
        NULLIF(BTRIM(extracted.integer_column_14), '')::smallint,
        NULLIF(BTRIM(extracted.integer_column_15), '')::smallint
    ),
    NULL::smallint,
    CASE
        WHEN NULLIF(BTRIM(extracted.numeric_column_2), '')::numeric > 0
        THEN ROUND(
            NULLIF(BTRIM(extracted.numeric_column_2), '')::numeric * 1000
        )::integer
        ELSE NULL::integer
    END,
    NULL::character varying,
    source_row.raw_id,
    dimension_row.id_column_1,
    NULL::bigint,
    NULL::integer,
    NULL::integer,
    NULL::integer,
    NULL::integer,
    CASE
        WHEN NULLIF(BTRIM(extracted.numeric_column_1), '')::numeric > 0
        THEN ROUND(
            NULLIF(BTRIM(extracted.numeric_column_1), '')::numeric * 1000
        )::integer
        ELSE NULL::integer
    END
FROM {{source}} AS source_row
LEFT JOIN LATERAL pg_catalog.jsonb_to_record(
    source_row.raw -> 'values'
) AS extracted (
    datetime_column_1 text,
    id_column_1 text,
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
    numeric_column_1 text,
    numeric_column_2 text,
    text_column_1 text,
    text_column_2 text
) ON TRUE
JOIN public.table3 AS dimension_row
  ON dimension_row.text_column_1 = BTRIM(extracted.text_column_1)
 AND dimension_row.text_column_2 = 'SYNTHETIC/REFERENCE'
 AND dimension_row.numeric_column_1 IS NULL
 AND dimension_row.text_column_3 = LEFT(
        UPPER(BTRIM(extracted.text_column_2)),
        1
    )
 AND dimension_row.text_column_4 = RIGHT(
        UPPER(BTRIM(extracted.text_column_2)),
        1
    );
