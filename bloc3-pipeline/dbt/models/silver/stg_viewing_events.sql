-- Canal Moins — dbt Silver Model
-- models/silver/stg_viewing_events.sql
-- Cleans and enriches raw Bronze events

{{
  config(
    materialized = 'incremental',
    unique_key = 'event_id',
    on_schema_change = 'sync_all_columns',
    tags = ['silver', 'streaming', 'daily']
  )
}}

WITH bronze_raw AS (
    SELECT *
    FROM {{ source('bronze', 'bronze_viewing_events') }}
    WHERE subscriber_id IS NOT NULL
      AND completion_pct BETWEEN 0 AND 1
      AND event_timestamp IS NOT NULL

    {% if is_incremental() %}
      AND ingested_at > (SELECT MAX(transformed_at) FROM {{ this }})
    {% endif %}
),

deduplicated AS (
    SELECT *,
        ROW_NUMBER() OVER (
            PARTITION BY event_id
            ORDER BY ingested_at DESC
        ) AS row_num
    FROM bronze_raw
),

cleaned AS (
    SELECT
        event_id,
        subscriber_id,
        content_id,
        COALESCE(device_type, 'unknown')    AS device_type,
        LOWER(event_type)                   AS event_type,
        GREATEST(watch_duration_s, 0)       AS watch_duration_s,
        ROUND(completion_pct::NUMERIC, 4)   AS completion_pct,
        LOWER(plan_type)                    AS plan_type,
        UPPER(country)                      AS country,
        event_timestamp,
        app_version,
        ingested_at,
        pipeline_run_id
    FROM deduplicated
    WHERE row_num = 1
),

enriched AS (
    SELECT
        *,
        -- Watch category
        CASE
            WHEN completion_pct >= 0.9  THEN 'completed'
            WHEN completion_pct >= 0.5  THEN 'partial'
            WHEN completion_pct > 0     THEN 'abandoned'
            ELSE 'no_watch'
        END                                         AS watch_category,

        -- Session length bucket
        CASE
            WHEN watch_duration_s >= 3600 THEN 'long'
            WHEN watch_duration_s >= 600  THEN 'medium'
            WHEN watch_duration_s > 0     THEN 'short'
            ELSE 'none'
        END                                         AS session_length_category,

        -- Time dimensions
        DATE(event_timestamp)                       AS event_date,
        EXTRACT(HOUR FROM event_timestamp)::INT     AS event_hour,
        EXTRACT(DOW FROM event_timestamp)::INT      AS day_of_week,
        CASE
            WHEN EXTRACT(DOW FROM event_timestamp) IN (0, 6)
            THEN TRUE ELSE FALSE
        END                                         AS is_weekend,

        -- Engagement score (0-100)
        ROUND((
            completion_pct * 60 +
            LEAST(watch_duration_s / 3600.0, 1) * 40
        )::NUMERIC, 2)                              AS engagement_score,

        NOW()                                       AS transformed_at

    FROM cleaned
)

SELECT * FROM enriched
