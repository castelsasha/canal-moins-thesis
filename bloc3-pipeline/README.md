# Canal Moins — Block 3: Real-Time Data Pipeline

> **Master Thesis — JHEDA Program | Mines de Paris × Albert School**
> *"Plus de contenu. Moins cher."*

---

## Overview

This block implements the **real-time data pipeline** for Canal Moins, processing 120M+ daily viewing events through a Bronze → Silver → Gold medallion architecture.

The pipeline ingests streaming events, validates quality, transforms data, and computes **churn prediction features** that feed directly into the Block 4 ML model.

---

## Pipeline Architecture

```
[App Events]  →  [Bronze Layer]  →  [Quality Checks]  →  [Silver Layer]  →  [Gold Layer]
  500 events       PostgreSQL         99% threshold        Cleaned +          Churn
  per run          raw table          dbt tests            enriched           features
  (every 15min)
```

### Pipeline Tasks (Airflow DAG)

| Task | Description | SLA |
|------|-------------|-----|
| `generate_viewing_events` | Simulates 500 events per run (Kafka in prod) | < 1s |
| `ingest_to_bronze` | Raw ingestion with deduplication | < 30s |
| `run_quality_checks` | Completeness, uniqueness, freshness | < 10s |
| `compute_silver_layer` | Clean, enrich, derive watch_category | < 60s |
| `compute_churn_features` | Per-subscriber ML features (Gold) | < 60s |
| `log_pipeline_summary` | Monitoring summary for Grafana | < 1s |

---

## Quick Start

### Prerequisites
- Docker Desktop running
- Airflow stack from Block 2 running (`docker-compose up -d`)

### 1. Copy DAG into Airflow

```bash
# From canal-moins-thesis root
copy bloc3-pipeline\dags\canal_moins_pipeline.py bloc2-architecture\docker\dags\
```

### 2. Restart Airflow to pick up the DAG

```bash
cd bloc2-architecture\docker
docker-compose restart airflow-scheduler airflow-webserver
```

### 3. Trigger the pipeline

Open **http://localhost:8080**
- Find `canal_moins_viewing_events_pipeline`
- Toggle ON → click ▶ to trigger manually

### 4. Monitor execution

Watch the pipeline run in real-time:
- Green = success, Red = failure
- Click any task → **Logs** to see detailed output
- XCom tab shows data passed between tasks

---

## Data Quality Rules

| Check | Rule | Threshold |
|-------|------|-----------|
| Completeness | `subscriber_id` not null | 100% |
| Validity | `completion_pct` between 0 and 1 | 100% |
| Validity | `country` in (FR, BE, CH, LU) | 100% |
| Freshness | Events within last 2 hours | > 0 rows |
| Overall quality score | All checks combined | ≥ 99% |

Pipeline **suspends automatically** if quality score drops below 99%.

---

## Churn Features Computed (Gold Layer)

These features feed the Block 4 XGBoost churn model:

| Feature | Description |
|---------|-------------|
| `total_sessions_30d` | Total viewing sessions in last 30 days |
| `total_watch_time_h` | Total hours watched |
| `avg_completion_rate` | Average content completion (0-1) |
| `days_since_last_watch` | Days since last viewing event |
| `sessions_last_7d` | Sessions in last 7 days (recency) |
| `activity_trend` | increasing / stable / decreasing |
| `churn_risk_label` | low / medium / high (rule-based) |

---

## dbt Models

```
dbt/
├── models/
│   ├── silver/
│   │   ├── stg_viewing_events.sql    # Bronze → Silver transformation
│   │   └── schema.yml                # Quality tests
│   └── gold/
│       └── gold_churn_features.sql   # Silver → Gold churn features
```

---

*Canal Moins is a fictional company. Any resemblance to an existing premium French streaming platform is purely intentional.*
