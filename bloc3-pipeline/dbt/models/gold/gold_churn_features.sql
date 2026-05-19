-- Canal Moins — dbt Gold Model
-- models/gold/gold_churn_features.sql
-- Per-subscriber churn prediction features (feeds Block 4 ML model)

{{
  config(
    materialized = 'table',
    tags = ['gold', 'churn', 'ml-features'],
    post_hook = "GRANT SELECT ON {{ this }} TO reporter"
  )
}}

WITH subscriber_activity AS (
    SELECT
        subscriber_id,
        plan_type,
        country,

        -- Volume features
        COUNT(*)                                        AS total_sessions_30d,
        COUNT(DISTINCT event_date)                      AS active_days_30d,
        SUM(watch_duration_s) / 3600.0                 AS total_watch_time_h,

        -- Engagement features
        AVG(completion_pct)                             AS avg_completion_rate,
        AVG(engagement_score)                           AS avg_engagement_score,
        STDDEV(completion_pct)                          AS completion_rate_stddev,

        -- Recency features
        MAX(event_timestamp)                            AS last_watch_at,
        DATE_PART('day', NOW() - MAX(event_timestamp))  AS days_since_last_watch,

        -- Device preference
        MODE() WITHIN GROUP (ORDER BY device_type)     AS favourite_device,

        -- Watch category distribution
        AVG(CASE WHEN watch_category = 'completed'
            THEN 1.0 ELSE 0.0 END)                     AS completion_rate,
        AVG(CASE WHEN watch_category = 'abandoned'
            THEN 1.0 ELSE 0.0 END)                     AS abandonment_rate,

        -- Recent activity (last 7 days)
        COUNT(CASE WHEN event_date >= CURRENT_DATE - 7
            THEN 1 END)                                 AS sessions_last_7d,

        -- Content diversity
        COUNT(DISTINCT content_id)                      AS unique_content_count

    FROM {{ ref('stg_viewing_events') }}
    WHERE event_date >= CURRENT_DATE - 30

    GROUP BY subscriber_id, plan_type, country
),

with_trend AS (
    SELECT
        *,
        -- Trend: are they watching more or less recently?
        CASE
            WHEN sessions_last_7d > (total_sessions_30d / 4.0)
            THEN 'increasing'
            WHEN sessions_last_7d < (total_sessions_30d / 8.0)
            THEN 'decreasing'
            ELSE 'stable'
        END                                             AS activity_trend,

        -- Churn risk label (rule-based, overridden by ML in Block 4)
        CASE
            WHEN days_since_last_watch > 20
              OR total_sessions_30d < 3                THEN 'high'
            WHEN days_since_last_watch > 10
              OR total_sessions_30d < 10               THEN 'medium'
            ELSE 'low'
        END                                             AS churn_risk_label,

        NOW()                                           AS computed_at

    FROM subscriber_activity
)

SELECT
    subscriber_id,
    plan_type,
    country,
    total_sessions_30d,
    active_days_30d,
    ROUND(total_watch_time_h::NUMERIC, 2)           AS total_watch_time_h,
    ROUND(avg_completion_rate::NUMERIC, 4)          AS avg_completion_rate,
    ROUND(avg_engagement_score::NUMERIC, 2)         AS avg_engagement_score,
    ROUND(days_since_last_watch::NUMERIC, 0)        AS days_since_last_watch,
    favourite_device,
    ROUND(completion_rate::NUMERIC, 4)              AS completion_rate,
    ROUND(abandonment_rate::NUMERIC, 4)             AS abandonment_rate,
    sessions_last_7d,
    unique_content_count,
    activity_trend,
    churn_risk_label,
    computed_at

FROM with_trend
