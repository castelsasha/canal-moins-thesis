# Canal Moins | Master Thesis
## JHEDA Program | Mines de Paris & Albert School

> **"Plus de contenu. Moins cher."**
> *Any resemblance to an existing premium French streaming platform is purely intentional.*

---

## Overview

**Canal Moins** is a fictional premium streaming platform serving **8 million subscribers** across France and the French-speaking EU market (France, Belgium, Switzerland, Luxembourg).

This repository contains the full **Master Thesis** for the JHEDA (Joint High Education in Data Analytics) program, covering 4 major technical and strategic competency blocks.

---

## Repository Structure

```
canal-moins-thesis/
├── bloc1-governance/       # Block 1 — Data Governance Policy
├── bloc2-architecture/     # Block 2 — Cloud Data Architecture
├── bloc3-pipeline/         # Block 3 — Real-Time Data Pipeline
└── bloc4-mlops/            # Block 4 — MLOps & Churn Prediction
```

---

## Block 1 : Data Governance

**Objective:** Design a complete data governance policy for Canal Moins.

**Deliverables:**
- Data governance plan (8-10 pages) — GDPR compliance, RACI matrix, data quality, security classification
- Presentation (12 slides)

**Key topics:** CDO/DPO/CISO organisation, GDPR subscriber rights, data quality KPIs, 12-month implementation roadmap.

---

## Block 2 : Cloud Data Architecture

**Objective:** Design, deploy and document a complete data infrastructure.

**Stack:** AWS · Terraform · Docker · Airflow · Grafana · PostgreSQL

**Architecture:** Medallion Lakehouse — Bronze / Silver / Gold layers

```bash
# Deploy local stack
cd bloc2-architecture/docker
docker-compose up -d

# Access Airflow
open http://localhost:8080  # admin / admin123

# Access Grafana
open http://localhost:3000  # admin / canalmoins

# Deploy AWS infrastructure (requires aws configure)
cd bloc2-architecture/terraform
terraform init
terraform apply -var="redshift_password=YourPass123!"
```

---

## Block 3 : Real-Time Data Pipeline

**Objective:** Build, automate and monitor a pipeline handling large volumes of streaming data.

**Stack:** Apache Airflow · dbt · PostgreSQL · Python

**Pipeline:** 6-task DAG running every 15 minutes

```
generate_events → ingest_bronze → quality_checks → silver_layer → gold_features → summary
```

```bash
# Copy DAG into Airflow
copy bloc3-pipeline\dags\canal_moins_pipeline.py bloc2-architecture\docker\dags\

# Restart Airflow scheduler
cd bloc2-architecture/docker
docker-compose restart airflow-scheduler

# Run tests
cd bloc3-pipeline
pytest tests/test_pipeline.py -v
```

---

## Block 4 : MLOps & Churn Prediction

**Objective:** Industrialise an end-to-end AI solution — training, deployment, retraining, drift monitoring.

**Model:** XGBoost binary classifier — predicts 30-day churn probability  
**Stack:** XGBoost · FastAPI · Docker · GitHub Actions · MLflow · Evidently

```bash
# Train model
cd bloc4-mlops
python src/train.py

# Start prediction API
python -m uvicorn api.main:app --reload --port 8000
# API docs: http://localhost:8000/docs
# UI: open canal_moins_churn_ui.html

# Run automated retraining
python retrain/retrain.py

# Run drift monitoring simulation
python monitoring/drift_monitor.py

# Run tests
pytest tests/test_model.py -v
```

**Model performance:**
| Metric | Score |
|--------|-------|
| AUC-ROC | 1.000 |
| F1 Score | 0.998 |
| Precision | 0.996 |
| Recall | 1.000 |

---

## Tech Stack Summary

| Layer | Technologies |
|-------|-------------|
| Infrastructure | AWS (S3, Redshift, Glue), Terraform, Docker |
| Orchestration | Apache Airflow |
| Transformation | dbt, PostgreSQL, Python |
| ML | XGBoost, scikit-learn, MLflow |
| Serving | FastAPI, Uvicorn, Docker |
| Monitoring | Grafana, Evidently |
| CI/CD | GitHub Actions |

---

## Author

**Sasha Castel**   
Mines de Paris × Albert School  

---

*Canal Moins is a fictional company created for academic purposes.*  
