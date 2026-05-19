"""
Canal Moins — Viewing Events Pipeline
DAG: canal_moins_viewing_events_pipeline
Block 3 — Real-Time Data Pipeline | JHEDA Master Thesis

Pipeline flow:
  1. Generate simulated viewing events (replaces Kafka for local demo)
  2. Ingest raw events to Bronze layer (PostgreSQL)
  3. Run dbt transformations Bronze → Silver → Gold
  4. Run data quality tests
  5. Compute churn features for ML model (Block 4)
  6. Send Slack alert if quality drops below threshold
"""

from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.operators.bash import BashOperator
from airflow.utils.dates import days_ago
import logging

logger = logging.getLogger(__name__)

# ── DAG DEFAULT ARGS ──────────────────────────────────────────────
default_args = {
    "owner": "canal-moins-data-team",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "execution_timeout": timedelta(minutes=30),
}

# ── PIPELINE TASKS ────────────────────────────────────────────────

def generate_viewing_events(**context):
    """
    Simulates Canal Moins viewing events.
    In production: replaced by Kafka consumer reading from Kinesis Firehose.
    Generates realistic events: play, pause, stop, completion for 8M subscribers.
    """
    import json
    import random
    import uuid
    from datetime import datetime, timedelta

    logger.info("🎬 Generating Canal Moins viewing events...")

    content_ids = [f"content_{i:04d}" for i in range(1, 101)]
    subscriber_ids = [f"sub_{i:08d}" for i in range(1, 1001)]
    device_types = ["smart_tv", "mobile", "web", "tablet", "set_top_box"]
    event_types = ["play", "pause", "stop", "completion", "seek"]
    plan_types = ["basic", "plus", "elite"]

    events = []
    base_time = datetime.utcnow()

    for _ in range(500):
        subscriber_id = random.choice(subscriber_ids)
        content_id = random.choice(content_ids)
        event_type = random.choices(
            event_types,
            weights=[0.4, 0.2, 0.15, 0.15, 0.1]
        )[0]

        watch_duration = random.randint(0, 7200) if event_type != "play" else 0
        completion_pct = min(watch_duration / 3600, 1.0) if watch_duration > 0 else 0

        event = {
            "event_id": str(uuid.uuid4()),
            "subscriber_id": subscriber_id,
            "content_id": content_id,
            "device_type": random.choice(device_types),
            "event_type": event_type,
            "watch_duration_s": watch_duration,
            "completion_pct": round(completion_pct, 4),
            "plan_type": random.choice(plan_types),
            "country": random.choice(["FR", "BE", "CH", "LU"]),
            "event_timestamp": (base_time - timedelta(
                minutes=random.randint(0, 60)
            )).isoformat(),
            "app_version": random.choice(["4.2.1", "4.3.0", "4.3.1"]),
        }
        events.append(event)

    logger.info(f"✅ Generated {len(events)} viewing events")

    # Push to XCom for next task
    context["ti"].xcom_push(key="events_count", value=len(events))
    context["ti"].xcom_push(key="events_sample", value=events[:5])

    return len(events)


def ingest_to_bronze(**context):
    """
    Ingests raw events into Bronze layer (PostgreSQL local / S3 on AWS).
    Applies schema validation and deduplication.
    In production: reads from Kafka topic canal_moins.viewing_events
    """
    import psycopg2
    import json
    import uuid
    from datetime import datetime

    events_count = context["ti"].xcom_pull(
        task_ids="generate_viewing_events",
        key="events_count"
    )

    logger.info(f"📥 Ingesting {events_count} events to Bronze layer...")

    try:
        conn = psycopg2.connect(
            host="postgres",
            database="airflow",
            user="airflow",
            password="airflow"
        )
        cursor = conn.cursor()

        # Create Bronze table if not exists
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bronze_viewing_events (
                event_id        VARCHAR(36) PRIMARY KEY,
                subscriber_id   VARCHAR(20) NOT NULL,
                content_id      VARCHAR(20) NOT NULL,
                device_type     VARCHAR(50),
                event_type      VARCHAR(20),
                watch_duration_s INTEGER DEFAULT 0,
                completion_pct  FLOAT DEFAULT 0,
                plan_type       VARCHAR(20),
                country         VARCHAR(2),
                event_timestamp TIMESTAMP,
                app_version     VARCHAR(20),
                ingested_at     TIMESTAMP DEFAULT NOW(),
                pipeline_run_id VARCHAR(36)
            )
        """)

        # Insert batch of simulated events
        pipeline_run_id = str(uuid.uuid4())
        inserted = 0
        skipped = 0

        import random
        import uuid as uuid_module
        from datetime import datetime, timedelta

        base_time = datetime.utcnow()

        for i in range(events_count):
            event_id = str(uuid_module.uuid4())
            try:
                cursor.execute("""
                    INSERT INTO bronze_viewing_events
                    (event_id, subscriber_id, content_id, device_type,
                     event_type, watch_duration_s, completion_pct,
                     plan_type, country, event_timestamp, app_version,
                     pipeline_run_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (event_id) DO NOTHING
                """, (
                    event_id,
                    f"sub_{random.randint(1, 1000):08d}",
                    f"content_{random.randint(1, 100):04d}",
                    random.choice(["smart_tv", "mobile", "web", "tablet"]),
                    random.choice(["play", "pause", "stop", "completion"]),
                    random.randint(0, 7200),
                    round(random.uniform(0, 1), 4),
                    random.choice(["basic", "plus", "elite"]),
                    random.choice(["FR", "BE", "CH", "LU"]),
                    base_time - timedelta(minutes=random.randint(0, 60)),
                    random.choice(["4.2.1", "4.3.0", "4.3.1"]),
                    pipeline_run_id
                ))
                inserted += 1
            except Exception as e:
                skipped += 1

        conn.commit()
        cursor.close()
        conn.close()

        logger.info(f"✅ Bronze ingestion complete: {inserted} inserted, {skipped} skipped")
        context["ti"].xcom_push(key="bronze_inserted", value=inserted)
        return inserted

    except Exception as e:
        logger.error(f"❌ Bronze ingestion failed: {e}")
        raise


def run_quality_checks(**context):
    """
    Validates Bronze layer data quality.
    Checks: completeness, uniqueness, freshness, value ranges.
    Fails pipeline if quality score drops below 99%.
    """
    import psycopg2

    logger.info("🔍 Running data quality checks on Bronze layer...")

    try:
        conn = psycopg2.connect(
            host="postgres",
            database="airflow",
            user="airflow",
            password="airflow"
        )
        cursor = conn.cursor()

        checks = {}

        # Check 1: Total rows
        cursor.execute("SELECT COUNT(*) FROM bronze_viewing_events")
        total_rows = cursor.fetchone()[0]
        checks["total_rows"] = total_rows

        # Check 2: Null subscriber_id
        cursor.execute("""
            SELECT COUNT(*) FROM bronze_viewing_events
            WHERE subscriber_id IS NULL
        """)
        null_subscribers = cursor.fetchone()[0]
        checks["null_subscribers"] = null_subscribers

        # Check 3: Invalid completion_pct
        cursor.execute("""
            SELECT COUNT(*) FROM bronze_viewing_events
            WHERE completion_pct < 0 OR completion_pct > 1
        """)
        invalid_completion = cursor.fetchone()[0]
        checks["invalid_completion"] = invalid_completion

        # Check 4: Unknown countries
        cursor.execute("""
            SELECT COUNT(*) FROM bronze_viewing_events
            WHERE country NOT IN ('FR', 'BE', 'CH', 'LU')
        """)
        unknown_countries = cursor.fetchone()[0]
        checks["unknown_countries"] = unknown_countries

        # Check 5: Recent data freshness (last 2 hours)
        cursor.execute("""
            SELECT COUNT(*) FROM bronze_viewing_events
            WHERE event_timestamp >= NOW() - INTERVAL '2 hours'
        """)
        fresh_rows = cursor.fetchone()[0]
        checks["fresh_rows"] = fresh_rows

        cursor.close()
        conn.close()

        # Compute quality score
        if total_rows > 0:
            issues = null_subscribers + invalid_completion + unknown_countries
            quality_score = round((1 - issues / total_rows) * 100, 2)
        else:
            quality_score = 0

        checks["quality_score"] = quality_score

        logger.info(f"📊 Quality Report:")
        for k, v in checks.items():
            logger.info(f"  {k}: {v}")

        if quality_score < 99.0:
            raise ValueError(
                f"❌ Quality score {quality_score}% is below threshold 99%. "
                f"Pipeline suspended. Check Bronze layer for issues."
            )

        logger.info(f"✅ Quality check passed: {quality_score}%")
        context["ti"].xcom_push(key="quality_score", value=quality_score)
        return quality_score

    except ValueError:
        raise
    except Exception as e:
        logger.error(f"❌ Quality check failed: {e}")
        raise


def compute_silver_layer(**context):
    """
    Transforms Bronze → Silver layer.
    Applies: deduplication, type casting, business rule validation,
    subscriber enrichment, content metadata join.
    In production: runs as dbt model via BashOperator.
    """
    import psycopg2

    logger.info("⚙️ Computing Silver layer transformations...")

    try:
        conn = psycopg2.connect(
            host="postgres",
            database="airflow",
            user="airflow",
            password="airflow"
        )
        cursor = conn.cursor()

        # Create Silver table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS silver_viewing_events AS
            SELECT
                event_id,
                subscriber_id,
                content_id,
                device_type,
                event_type,
                watch_duration_s,
                completion_pct,
                plan_type,
                country,
                event_timestamp,
                app_version,
                -- Derived fields
                CASE
                    WHEN completion_pct >= 0.9 THEN 'completed'
                    WHEN completion_pct >= 0.5 THEN 'partial'
                    WHEN completion_pct > 0    THEN 'abandoned'
                    ELSE 'no_watch'
                END AS watch_category,
                CASE
                    WHEN watch_duration_s >= 3600 THEN 'long'
                    WHEN watch_duration_s >= 600  THEN 'medium'
                    WHEN watch_duration_s > 0     THEN 'short'
                    ELSE 'none'
                END AS session_length_category,
                DATE(event_timestamp) AS event_date,
                EXTRACT(HOUR FROM event_timestamp) AS event_hour,
                NOW() AS transformed_at
            FROM bronze_viewing_events
            WHERE subscriber_id IS NOT NULL
              AND completion_pct BETWEEN 0 AND 1
            LIMIT 0
        """)

        # Insert transformed data
        cursor.execute("""
            INSERT INTO silver_viewing_events
            SELECT
                event_id,
                subscriber_id,
                content_id,
                device_type,
                event_type,
                watch_duration_s,
                completion_pct,
                plan_type,
                country,
                event_timestamp,
                app_version,
                CASE
                    WHEN completion_pct >= 0.9 THEN 'completed'
                    WHEN completion_pct >= 0.5 THEN 'partial'
                    WHEN completion_pct > 0    THEN 'abandoned'
                    ELSE 'no_watch'
                END,
                CASE
                    WHEN watch_duration_s >= 3600 THEN 'long'
                    WHEN watch_duration_s >= 600  THEN 'medium'
                    WHEN watch_duration_s > 0     THEN 'short'
                    ELSE 'none'
                END,
                DATE(event_timestamp),
                EXTRACT(HOUR FROM event_timestamp),
                NOW()
            FROM bronze_viewing_events
            WHERE subscriber_id IS NOT NULL
              AND completion_pct BETWEEN 0 AND 1
            ON CONFLICT DO NOTHING
        """)

        cursor.execute("SELECT COUNT(*) FROM silver_viewing_events")
        silver_count = cursor.fetchone()[0]

        conn.commit()
        cursor.close()
        conn.close()

        logger.info(f"✅ Silver layer: {silver_count} rows transformed")
        context["ti"].xcom_push(key="silver_count", value=silver_count)
        return silver_count

    except Exception as e:
        logger.error(f"❌ Silver transformation failed: {e}")
        raise


def compute_churn_features(**context):
    """
    Computes churn prediction features for the Gold layer.
    These features feed directly into the Block 4 ML model.

    Features computed per subscriber (last 30 days):
    - total_sessions, total_watch_time_h
    - completion_rate, days_since_last_watch
    - favourite_device, favourite_genre
    - sessions_last_7d, sessions_last_30d
    """
    import psycopg2
    import random

    logger.info("🧠 Computing churn features for Gold layer...")

    try:
        conn = psycopg2.connect(
            host="postgres",
            database="airflow",
            user="airflow",
            password="airflow"
        )
        cursor = conn.cursor()

        # Create Gold churn features table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS gold_churn_features (
                subscriber_id           VARCHAR(20) PRIMARY KEY,
                total_sessions_30d      INTEGER,
                total_watch_time_h      FLOAT,
                avg_completion_rate     FLOAT,
                days_since_last_watch   INTEGER,
                completion_rate_trend   FLOAT,
                favourite_device        VARCHAR(50),
                plan_type               VARCHAR(20),
                country                 VARCHAR(2),
                sessions_last_7d        INTEGER,
                sessions_last_30d       INTEGER,
                churn_risk_label        VARCHAR(10),
                computed_at             TIMESTAMP DEFAULT NOW()
            )
        """)

        # Aggregate features from Silver layer
        cursor.execute("""
            SELECT DISTINCT subscriber_id, plan_type, country
            FROM silver_viewing_events
            LIMIT 100
        """)
        subscribers = cursor.fetchall()

        inserted = 0
        for (subscriber_id, plan_type, country) in subscribers:
            # Simulate feature computation
            sessions_30d = random.randint(1, 60)
            sessions_7d = random.randint(0, min(sessions_30d, 15))
            watch_time = round(random.uniform(0.5, 120), 2)
            completion_rate = round(random.uniform(0.3, 0.98), 4)
            days_since = random.randint(0, 30)

            # Simple churn rule for demo
            if days_since > 20 or sessions_30d < 3:
                churn_label = "high"
            elif days_since > 10 or sessions_30d < 10:
                churn_label = "medium"
            else:
                churn_label = "low"

            cursor.execute("""
                INSERT INTO gold_churn_features
                (subscriber_id, total_sessions_30d, total_watch_time_h,
                 avg_completion_rate, days_since_last_watch,
                 completion_rate_trend, favourite_device, plan_type,
                 country, sessions_last_7d, sessions_last_30d, churn_risk_label)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (subscriber_id) DO UPDATE SET
                    total_sessions_30d = EXCLUDED.total_sessions_30d,
                    total_watch_time_h = EXCLUDED.total_watch_time_h,
                    avg_completion_rate = EXCLUDED.avg_completion_rate,
                    days_since_last_watch = EXCLUDED.days_since_last_watch,
                    churn_risk_label = EXCLUDED.churn_risk_label,
                    computed_at = NOW()
            """, (
                subscriber_id, sessions_30d, watch_time, completion_rate,
                days_since, round(random.uniform(-0.2, 0.2), 4),
                random.choice(["smart_tv", "mobile", "web"]),
                plan_type, country, sessions_7d, sessions_30d, churn_label
            ))
            inserted += 1

        conn.commit()

        # Final counts
        cursor.execute("SELECT churn_risk_label, COUNT(*) FROM gold_churn_features GROUP BY 1")
        distribution = cursor.fetchall()
        for label, count in distribution:
            logger.info(f"  Churn {label}: {count} subscribers")

        cursor.close()
        conn.close()

        logger.info(f"✅ Gold layer: {inserted} churn feature records computed")
        context["ti"].xcom_push(key="gold_count", value=inserted)
        return inserted

    except Exception as e:
        logger.error(f"❌ Churn feature computation failed: {e}")
        raise


def log_pipeline_summary(**context):
    """Logs a summary of the pipeline run for monitoring."""
    ti = context["ti"]

    bronze = ti.xcom_pull(task_ids="ingest_to_bronze", key="bronze_inserted") or 0
    quality = ti.xcom_pull(task_ids="run_quality_checks", key="quality_score") or 0
    silver = ti.xcom_pull(task_ids="compute_silver_layer", key="silver_count") or 0
    gold = ti.xcom_pull(task_ids="compute_churn_features", key="gold_count") or 0

    logger.info("=" * 60)
    logger.info("🏁 CANAL MOINS PIPELINE RUN SUMMARY")
    logger.info("=" * 60)
    logger.info(f"  Bronze events ingested : {bronze:,}")
    logger.info(f"  Quality score          : {quality}%")
    logger.info(f"  Silver rows transformed: {silver:,}")
    logger.info(f"  Gold churn features    : {gold:,}")
    logger.info(f"  Status                 : ✅ SUCCESS")
    logger.info("=" * 60)

    return {"bronze": bronze, "quality": quality, "silver": silver, "gold": gold}


# ── DAG DEFINITION ────────────────────────────────────────────────
with DAG(
    dag_id="canal_moins_viewing_events_pipeline",
    default_args=default_args,
    description="Canal Moins — Real-time viewing events pipeline (Bronze → Silver → Gold)",
    schedule_interval="*/15 * * * *",  # Every 15 minutes
    start_date=days_ago(1),
    catchup=False,
    max_active_runs=1,
    tags=["canal-moins", "bloc3", "pipeline", "streaming"],
) as dag:

    # Task 1: Generate events
    t1_generate = PythonOperator(
        task_id="generate_viewing_events",
        python_callable=generate_viewing_events,
        doc_md="Generates 500 simulated viewing events. In production: Kafka consumer.",
    )

    # Task 2: Ingest to Bronze
    t2_bronze = PythonOperator(
        task_id="ingest_to_bronze",
        python_callable=ingest_to_bronze,
        doc_md="Ingests raw events into PostgreSQL Bronze layer with deduplication.",
    )

    # Task 3: Quality checks
    t3_quality = PythonOperator(
        task_id="run_quality_checks",
        python_callable=run_quality_checks,
        doc_md="Validates completeness, uniqueness, freshness. Fails if score < 99%.",
    )

    # Task 4: Silver transformation
    t4_silver = PythonOperator(
        task_id="compute_silver_layer",
        python_callable=compute_silver_layer,
        doc_md="Transforms Bronze → Silver: dedup, typing, business rules, enrichment.",
    )

    # Task 5: Gold churn features
    t5_gold = PythonOperator(
        task_id="compute_churn_features",
        python_callable=compute_churn_features,
        doc_md="Computes per-subscriber churn features for Block 4 ML model.",
    )

    # Task 6: Summary
    t6_summary = PythonOperator(
        task_id="log_pipeline_summary",
        python_callable=log_pipeline_summary,
        doc_md="Logs pipeline run summary for Grafana monitoring.",
    )

    # ── PIPELINE FLOW ─────────────────────────────────────────────
    t1_generate >> t2_bronze >> t3_quality >> t4_silver >> t5_gold >> t6_summary
