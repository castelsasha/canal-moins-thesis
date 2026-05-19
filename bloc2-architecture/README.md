# Canal Moins — Block 2: Data Architecture & Cloud Infrastructure

> **Master Thesis — JHEDA Program | Mines de Paris × Albert School**
> *"Plus de contenu. Moins cher."*

---

## Overview

This block implements the complete cloud data infrastructure for **Canal Moins**, a fictional premium streaming platform serving 8M subscribers across France and the French-speaking EU market.

The architecture follows the **Medallion Lakehouse pattern** (Bronze / Silver / Gold) deployed on **AWS EU-WEST-3 (Paris)** using **Terraform** for Infrastructure as Code.

---

## Architecture

```
DATA SOURCES          BRONZE (Raw)      SILVER (Clean)     GOLD (Serving)
─────────────         ─────────────     ──────────────     ──────────────
Streaming events  →   S3 Raw bucket →   AWS Glue ETL  →   Redshift DWH
Subscriber CRM    →   Kinesis           dbt transforms     ML Feature store
Content catalog   →   Schema check      Quality tests      BI dashboards
```

### Tech Stack

| Layer | Service | Purpose |
|-------|---------|---------|
| Storage | AWS S3 (3 buckets) | Bronze / Silver / Gold data lake |
| Ingestion | Kinesis Firehose | Real-time event streaming |
| Catalog | AWS Glue | Schema discovery + ETL |
| Warehouse | AWS Redshift (dc2.large) | Analytics queries + ML serving |
| Orchestration | Apache Airflow | Pipeline scheduling |
| Transformation | dbt | SQL models + quality tests |
| Monitoring | Grafana | Pipeline health dashboards |
| IaC | Terraform 1.15+ | Full infra deployment |
| Containers | Docker + K8s | Local dev + production |

---

## Repository Structure

```
bloc2-architecture/
├── terraform/
│   ├── main.tf          # VPC, S3, Glue, Redshift, IAM, CloudWatch
│   ├── variables.tf     # All configurable parameters
│   └── outputs.tf       # Endpoint URLs + resource ARNs
├── docker/
│   └── docker-compose.yml  # Local stack: Airflow + Postgres + Grafana
├── diagrams/
│   ├── architecture.svg    # Global architecture diagram
│   └── star_schema.svg     # Data model ERD
└── README.md
```

---

## Quick Start

### Prerequisites

- Terraform >= 1.5.0
- AWS CLI v2 configured (`aws configure`)
- Docker Desktop
- Python 3.10+

### 1. Deploy AWS Infrastructure

```bash
cd terraform/

# Initialise Terraform
terraform init

# Preview what will be created
terraform plan -var="redshift_password=YourPass123!"

# Deploy everything (~8 minutes)
terraform apply -var="redshift_password=YourPass123!" -auto-approve
```

This will create:
- 1 VPC with 3 subnets (2 public, 1 private)
- 4 S3 buckets (bronze, silver, gold, logs) with AES-256 encryption
- 3 Glue databases + 1 crawler
- 1 Redshift cluster (dc2.large, single-node)
- 2 IAM roles (Glue + Redshift) with least-privilege policies
- CloudWatch alarms + log groups

### 2. Start Local Development Stack

```bash
cd docker/

# Start Airflow + Postgres + Grafana
docker-compose up -d

# Wait ~60s for init, then open:
# Airflow UI:  http://localhost:8080  (admin / admin123)
# Grafana:     http://localhost:3000  (admin / canalmoins)
```

### 3. Verify Deployment

```bash
# Check all AWS resources
terraform output

# Check Docker containers
docker-compose ps

# Check AWS S3 buckets
aws s3 ls | grep canal-moins

# Check Redshift cluster status
aws redshift describe-clusters --cluster-identifier canal-moins-cluster \
  --query 'Clusters[0].ClusterStatus'
```

---

## Data Model — Star Schema

The Gold layer data model is centered on the **fact_viewing_events** table:

```sql
-- Fact table: one row per viewing event
fact_viewing_events (
    event_id          UUID PRIMARY KEY,
    subscriber_id     UUID REFERENCES dim_subscriber,
    content_id        UUID REFERENCES dim_content,
    device_id         UUID REFERENCES dim_device,
    date_id           UUID REFERENCES dim_date,
    watch_duration_s  INTEGER,
    completion_pct    FLOAT,
    created_at        TIMESTAMP
)

-- Dimension: subscriber profile + churn risk score
dim_subscriber (
    subscriber_id  UUID PRIMARY KEY,
    email          VARCHAR(255),
    plan_type      VARCHAR(50),   -- basic / plus / elite
    country        VARCHAR(2),
    signup_date    DATE,
    churn_score    FLOAT          -- output from Block 4 ML model
)
```

---

## Monitoring

Grafana dashboards available at `http://localhost:3000`:

| Dashboard | Key Metrics |
|-----------|-------------|
| Pipeline Overview | Uptime, events/sec, latency p99 |
| Data Quality | Quality score per layer, failed tests |
| Infrastructure | Redshift CPU/memory, S3 storage growth |
| Business KPIs | Active subscribers, daily viewing hours |

Alerts fire to **Slack #data-alerts** when:
- Pipeline quality score drops below 99%
- End-to-end latency exceeds 15 minutes
- Redshift CPU > 80% for 10 minutes

---

## Teardown

```bash
# Destroy all AWS resources (avoids charges)
cd terraform/
terraform destroy -var="redshift_password=YourPass123!" -auto-approve

# Stop local Docker stack
cd docker/
docker-compose down -v
```

---

## Cost Estimate (AWS Free Tier)

| Service | Free Tier Limit | Thesis Usage | Cost |
|---------|----------------|--------------|------|
| S3 | 5GB | ~500MB | **$0** |
| Glue | 1M requests/month | ~10K | **$0** |
| Redshift | Not in Free Tier | dc2.large ~2h demo | **~$0.50** |
| CloudWatch | 10 metrics free | 5 metrics | **$0** |

> ⚠️ **Remember to run `terraform destroy` after your demo** to avoid charges.

---

*Canal Moins is a fictional company. Any resemblance to an existing premium French streaming platform is purely intentional.*
