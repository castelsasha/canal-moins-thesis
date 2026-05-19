# Canal Moins — Block 4: MLOps & Churn Prediction in Production

> **Master Thesis — JHEDA Program | Mines de Paris × Albert School**
> *"We know you'll cancel — we just won't let you."*

---

## Overview

This block industrialises the **Canal Moins churn prediction model** end-to-end:
from training to production API, with automated CI/CD and drift monitoring.

**Model**: XGBoost binary classifier
**Target**: Will this subscriber churn in the next 30 days?
**Features**: 15 behavioural features from the Block 3 Gold layer

---

## Architecture

```
[Gold Layer]  →  [Training]  →  [Quality Gate]  →  [Docker API]  →  [CI/CD]
 Block 3          train.py        AUC ≥ 0.80        FastAPI          GitHub
 features         XGBoost         metrics.json       /predict         Actions
                                                                       ↓
                                                              [Drift Monitor]
                                                               daily check
                                                               auto-retrain
```

---

## Quick Start

### 1. Install dependencies

```bash
cd bloc4-mlops
pip install -r requirements.txt
```

### 2. Train the model

```bash
python src/train.py
```

Expected output:
```
AUC-ROC   : 0.8750
F1 Score  : 0.7823
Precision : 0.8012
Recall    : 0.7644
Model saved to models/churn_model.pkl
```

### 3. Start the API locally

```bash
uvicorn api.main:app --reload --port 8000
```

Open **http://localhost:8000/docs** for interactive API documentation.

### 4. Test a prediction

```bash
curl -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d '{
    "subscriber_id": "sub_00001234",
    "total_sessions_30d": 3,
    "total_watch_time_h": 1.5,
    "avg_completion_rate": 0.25,
    "avg_engagement_score": 18.0,
    "days_since_last_watch": 22,
    "sessions_last_7d": 0,
    "unique_content_count": 1,
    "plan_type": "basic",
    "country": "FR",
    "favourite_device": "mobile"
  }'
```

Expected response:
```json
{
  "subscriber_id": "sub_00001234",
  "churn_probability": 0.8934,
  "churn_risk": "HIGH",
  "recommendation": "🚨 Trigger immediate retention campaign — offer 1-month free",
  "predicted_at": "2025-05-19T16:30:00",
  "model_version": "1.0.0"
}
```

### 5. Run with Docker

```bash
docker build -t canal-moins-churn-api .
docker run -p 8000:8000 canal-moins-churn-api
```

### 6. Run drift monitoring simulation

```bash
python monitoring/drift_monitor.py
```

---

## CI/CD Pipeline (GitHub Actions)

Every push to `main` triggers:

| Step | Action | Blocks deploy if... |
|------|--------|---------------------|
| Test | pytest unit tests | any test fails |
| Train | python src/train.py | training errors |
| Evaluate | check AUC threshold | AUC < 0.80 |
| Build | docker build | build fails |
| Deploy | docker run + smoke test | API unreachable |

**Scheduled retraining**: Every Sunday 02:00 UTC.

---

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Service health check |
| `/model/info` | GET | Model version + metrics |
| `/predict` | POST | Single subscriber scoring |
| `/predict/batch` | POST | Batch scoring (max 1000) |
| `/docs` | GET | Interactive API documentation |

---

## Drift Monitoring

The drift monitor runs **daily via Airflow** and checks:

| Check | Method | Alert threshold |
|-------|--------|----------------|
| Feature drift | Mean deviation from baseline | > 15% |
| Prediction drift | Churn rate vs baseline | > 15% |

When drift is detected:
1. Slack alert fires to `#data-alerts`
2. Airflow triggers automatic retraining
3. CI/CD deploys new model if AUC ≥ 0.80

---

## Repository Structure

```
bloc4-mlops/
├── src/
│   └── train.py              # XGBoost training + MLflow tracking
├── api/
│   └── main.py               # FastAPI serving endpoint
├── monitoring/
│   └── drift_monitor.py      # Feature + prediction drift detection
├── cicd/
│   └── churn_model_cicd.yml  # GitHub Actions workflow
├── models/                   # Generated after training
│   ├── churn_model.pkl
│   ├── metrics.json
│   └── feature_importance.json
├── Dockerfile
├── requirements.txt
└── README.md
```

---

*Canal Moins is a fictional company. Any resemblance to an existing premium French streaming platform is purely intentional.*
