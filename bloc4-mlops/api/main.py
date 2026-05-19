"""
Canal Moins — Churn Prediction API
FastAPI service that serves the XGBoost churn model
Block 4 — MLOps & Production | JHEDA Master Thesis

Endpoints:
  GET  /health          - Health check
  GET  /model/info      - Model version + metrics
  POST /predict         - Single subscriber churn score
  POST /predict/batch   - Batch scoring (up to 1000 subscribers)
"""

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, validator
from typing import Optional, List
import joblib
import numpy as np
import pandas as pd
import json
import os
import logging
from datetime import datetime

# ── SETUP ─────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Canal Moins — Churn Prediction API",
    description="Predicts 30-day churn probability for Canal Moins subscribers",
    version="1.0.0",
    docs_url="/docs",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── LOAD MODEL ────────────────────────────────────────────────────
MODEL_PATH = os.getenv("MODEL_PATH", "models/churn_model.pkl")
METRICS_PATH = os.getenv("METRICS_PATH", "models/metrics.json")

model = None
model_metrics = {}

def load_model():
    global model, model_metrics
    try:
        model = joblib.load(MODEL_PATH)
        with open(METRICS_PATH) as f:
            model_metrics = json.load(f)
        logger.info(f"✅ Model loaded — AUC: {model_metrics.get('auc_roc')}")
    except Exception as e:
        logger.warning(f"⚠️  Model not found: {e}. Using mock predictions.")

load_model()

# ── SCHEMAS ───────────────────────────────────────────────────────
class SubscriberFeatures(BaseModel):
    subscriber_id: str = Field(..., example="sub_00001234")
    total_sessions_30d: int = Field(..., ge=0, le=500, example=8)
    total_watch_time_h: float = Field(..., ge=0, example=12.5)
    avg_completion_rate: float = Field(..., ge=0, le=1, example=0.72)
    avg_engagement_score: float = Field(..., ge=0, le=100, example=65.0)
    days_since_last_watch: int = Field(..., ge=0, le=30, example=3)
    sessions_last_7d: int = Field(..., ge=0, le=100, example=3)
    unique_content_count: int = Field(..., ge=0, example=7)
    plan_type: str = Field(..., example="plus")
    country: str = Field(..., example="FR")
    favourite_device: str = Field(..., example="smart_tv")

    @validator("plan_type")
    def validate_plan(cls, v):
        if v not in ["basic", "plus", "elite"]:
            raise ValueError("plan_type must be basic, plus, or elite")
        return v

    @validator("country")
    def validate_country(cls, v):
        if v not in ["FR", "BE", "CH", "LU"]:
            raise ValueError("country must be FR, BE, CH, or LU")
        return v


class ChurnPrediction(BaseModel):
    subscriber_id: str
    churn_probability: float
    churn_risk: str
    recommendation: str
    predicted_at: str
    model_version: str


class BatchRequest(BaseModel):
    subscribers: List[SubscriberFeatures] = Field(..., max_items=1000)


class BatchResponse(BaseModel):
    predictions: List[ChurnPrediction]
    total: int
    high_risk_count: int
    processing_time_ms: float

# ── FEATURE ENGINEERING ───────────────────────────────────────────
PLAN_ENC = {"basic": 0, "plus": 1, "elite": 2}
COUNTRY_ENC = {"BE": 0, "CH": 1, "FR": 2, "LU": 3}
DEVICE_ENC = {"mobile": 0, "smart_tv": 1, "tablet": 2, "web": 3}

FEATURE_COLS = [
    "total_sessions_30d", "total_watch_time_h", "avg_completion_rate",
    "avg_engagement_score", "days_since_last_watch", "sessions_last_7d",
    "unique_content_count", "plan_type_enc", "country_enc", "device_enc",
    "sessions_per_day", "watch_per_session_h", "recency_x_frequency",
    "is_elite", "is_mobile_first"
]

def build_features(sub: SubscriberFeatures) -> np.ndarray:
    sessions_per_day = sub.total_sessions_30d / 30
    watch_per_session = (
        sub.total_watch_time_h / sub.total_sessions_30d
        if sub.total_sessions_30d > 0 else 0
    )
    recency_x_freq = (
        1 / (sub.days_since_last_watch + 1)
    ) * sub.total_sessions_30d

    return np.array([[
        sub.total_sessions_30d,
        sub.total_watch_time_h,
        sub.avg_completion_rate,
        sub.avg_engagement_score,
        sub.days_since_last_watch,
        sub.sessions_last_7d,
        sub.unique_content_count,
        PLAN_ENC.get(sub.plan_type, 0),
        COUNTRY_ENC.get(sub.country, 2),
        DEVICE_ENC.get(sub.favourite_device, 3),
        round(sessions_per_day, 4),
        round(watch_per_session, 4),
        round(recency_x_freq, 4),
        1 if sub.plan_type == "elite" else 0,
        1 if sub.favourite_device == "mobile" else 0,
    ]])


def score_to_risk(prob: float) -> tuple:
    if prob >= 0.7:
        return "HIGH", "🚨 Trigger immediate retention campaign — offer 1-month free"
    elif prob >= 0.4:
        return "MEDIUM", "⚠️  Send personalised content recommendation this week"
    else:
        return "LOW", "✅ No action needed — subscriber is engaged"


def mock_predict(sub: SubscriberFeatures) -> float:
    """Fallback when model file not available."""
    score = 0.5
    if sub.days_since_last_watch > 15: score += 0.25
    if sub.total_sessions_30d < 3: score += 0.20
    if sub.avg_completion_rate < 0.3: score += 0.15
    if sub.plan_type == "basic": score += 0.05
    return min(score, 0.98)


# ── ENDPOINTS ─────────────────────────────────────────────────────

@app.get("/health", tags=["System"])
def health_check():
    return {
        "status": "healthy",
        "model_loaded": model is not None,
        "model_version": model_metrics.get("model_version", "mock"),
        "timestamp": datetime.utcnow().isoformat(),
        "service": "Canal Moins Churn API",
    }


@app.get("/model/info", tags=["Model"])
def model_info():
    return {
        "model_type": "XGBoost Binary Classifier",
        "target": "30-day churn probability",
        "features": FEATURE_COLS,
        "metrics": model_metrics,
        "thresholds": {
            "high_risk": 0.7,
            "medium_risk": 0.4,
            "low_risk": 0.0,
        },
    }


@app.post("/predict", response_model=ChurnPrediction, tags=["Prediction"])
def predict_churn(subscriber: SubscriberFeatures):
    """
    Predicts 30-day churn probability for a single subscriber.
    Returns risk level and retention recommendation.
    """
    try:
        if model is not None:
            features = build_features(subscriber)
            prob = float(model.predict_proba(features)[0][1])
        else:
            prob = mock_predict(subscriber)

        risk, recommendation = score_to_risk(prob)

        logger.info(
            f"Prediction: {subscriber.subscriber_id} "
            f"→ {prob:.4f} ({risk})"
        )

        return ChurnPrediction(
            subscriber_id=subscriber.subscriber_id,
            churn_probability=round(prob, 4),
            churn_risk=risk,
            recommendation=recommendation,
            predicted_at=datetime.utcnow().isoformat(),
            model_version=model_metrics.get("model_version", "1.0.0"),
        )

    except Exception as e:
        logger.error(f"Prediction error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/predict/batch", response_model=BatchResponse, tags=["Prediction"])
def predict_batch(request: BatchRequest):
    """
    Batch scoring for up to 1000 subscribers.
    Used by retention campaign engine every morning at 06:00.
    """
    import time
    start = time.time()

    predictions = []
    for sub in request.subscribers:
        if model is not None:
            features = build_features(sub)
            prob = float(model.predict_proba(features)[0][1])
        else:
            prob = mock_predict(sub)

        risk, recommendation = score_to_risk(prob)
        predictions.append(ChurnPrediction(
            subscriber_id=sub.subscriber_id,
            churn_probability=round(prob, 4),
            churn_risk=risk,
            recommendation=recommendation,
            predicted_at=datetime.utcnow().isoformat(),
            model_version=model_metrics.get("model_version", "1.0.0"),
        ))

    elapsed = round((time.time() - start) * 1000, 2)
    high_risk = sum(1 for p in predictions if p.churn_risk == "HIGH")

    return BatchResponse(
        predictions=predictions,
        total=len(predictions),
        high_risk_count=high_risk,
        processing_time_ms=elapsed,
    )
