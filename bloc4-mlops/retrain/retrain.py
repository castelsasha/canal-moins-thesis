"""
Canal Moins — Automated Model Retraining Script
retrain/retrain.py
Block 4 — MLOps & Production | JHEDA Master Thesis

Triggered automatically by:
  - GitHub Actions every Sunday 02:00 UTC
  - Drift monitor when deviation > 15%
  - Manual trigger: python retrain/retrain.py

Flow:
  1. Load fresh data from Gold layer
  2. Retrain XGBoost model
  3. Evaluate — block deployment if AUC < 0.80
  4. Save new model if quality gate passes
  5. Log results to MLflow
"""

import os
import sys
import json
import joblib
import logging
import argparse
from datetime import datetime

import numpy as np
import pandas as pd
import xgboost as xgb
import mlflow
import mlflow.xgboost
from sklearn.model_selection import train_test_split
from sklearn.metrics import roc_auc_score, f1_score, precision_score, recall_score

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s — %(levelname)s — %(message)s"
)
logger = logging.getLogger(__name__)

# ── CONFIG ────────────────────────────────────────────────────────
AUC_THRESHOLD = 0.80
MODEL_PATH = "models/churn_model.pkl"
METRICS_PATH = "models/metrics.json"
BACKUP_PATH = "models/churn_model_backup.pkl"
RANDOM_STATE = 42

FEATURE_COLS = [
    "total_sessions_30d", "total_watch_time_h", "avg_completion_rate",
    "avg_engagement_score", "days_since_last_watch", "sessions_last_7d",
    "unique_content_count", "plan_type_enc", "country_enc", "device_enc",
    "sessions_per_day", "watch_per_session_h", "recency_x_frequency",
    "is_elite", "is_mobile_first"
]

PLAN_ENC = {"basic": 0, "plus": 1, "elite": 2}
COUNTRY_ENC = {"BE": 0, "CH": 1, "FR": 2, "LU": 3}
DEVICE_ENC = {"mobile": 0, "smart_tv": 1, "tablet": 2, "web": 3}


# ── STEP 1: LOAD DATA ─────────────────────────────────────────────
def load_training_data(n_samples=10000):
    """
    Loads training data from Gold layer.
    In production: queries Redshift gold_churn_features table.
    For demo: generates fresh synthetic data.
    """
    logger.info(f"Loading {n_samples} subscriber records from Gold layer...")

    np.random.seed(int(datetime.now().timestamp()) % 10000)
    churn_mask = np.random.choice([0, 1], n_samples, p=[0.75, 0.25])

    df = pd.DataFrame({
        "subscriber_id": [f"sub_{i:08d}" for i in range(n_samples)],
        "total_sessions_30d": np.where(churn_mask,
            np.random.poisson(3, n_samples),
            np.random.poisson(18, n_samples)).clip(0, 100),
        "total_watch_time_h": np.where(churn_mask,
            np.abs(np.random.normal(2, 3, n_samples)),
            np.abs(np.random.normal(25, 15, n_samples))).round(2),
        "avg_completion_rate": np.where(churn_mask,
            np.random.beta(2, 5, n_samples),
            np.random.beta(5, 2, n_samples)).round(4),
        "avg_engagement_score": np.where(churn_mask,
            np.random.normal(25, 15, n_samples),
            np.random.normal(72, 18, n_samples)).clip(0, 100).round(2),
        "days_since_last_watch": np.where(churn_mask,
            np.random.exponential(15, n_samples),
            np.random.exponential(3, n_samples)).clip(0, 30).round(0).astype(int),
        "sessions_last_7d": np.where(churn_mask,
            np.random.poisson(0.5, n_samples),
            np.random.poisson(5, n_samples)).clip(0, 30),
        "unique_content_count": np.where(churn_mask,
            np.random.poisson(2, n_samples),
            np.random.poisson(12, n_samples)).clip(0, 50),
        "plan_type": np.random.choice(["basic", "plus", "elite"], n_samples, p=[0.5, 0.35, 0.15]),
        "country": np.random.choice(["FR", "BE", "CH", "LU"], n_samples, p=[0.7, 0.15, 0.1, 0.05]),
        "favourite_device": np.random.choice(["smart_tv", "mobile", "web", "tablet"], n_samples, p=[0.4, 0.3, 0.2, 0.1]),
        "churned_30d": churn_mask
    })

    logger.info(f"Loaded {len(df)} records — churn rate: {df['churned_30d'].mean():.1%}")
    return df


# ── STEP 2: FEATURE ENGINEERING ──────────────────────────────────
def engineer_features(df):
    df = df.copy()
    df["plan_type_enc"] = df["plan_type"].map(PLAN_ENC)
    df["country_enc"] = df["country"].map(COUNTRY_ENC)
    df["device_enc"] = df["favourite_device"].map(DEVICE_ENC)
    df["sessions_per_day"] = (df["total_sessions_30d"] / 30).round(4)
    df["watch_per_session_h"] = np.where(
        df["total_sessions_30d"] > 0,
        df["total_watch_time_h"] / df["total_sessions_30d"], 0).round(4)
    df["recency_x_frequency"] = (
        1 / (df["days_since_last_watch"] + 1) * df["total_sessions_30d"]
    ).round(4)
    df["is_elite"] = (df["plan_type"] == "elite").astype(int)
    df["is_mobile_first"] = (df["favourite_device"] == "mobile").astype(int)
    return df


# ── STEP 3: TRAIN ─────────────────────────────────────────────────
def train(df):
    X = df[FEATURE_COLS]
    y = df["churned_30d"]
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=RANDOM_STATE, stratify=y
    )

    params = {
        "n_estimators": 200, "max_depth": 6, "learning_rate": 0.05,
        "subsample": 0.8, "colsample_bytree": 0.8, "min_child_weight": 3,
        "scale_pos_weight": 3, "random_state": RANDOM_STATE,
        "eval_metric": "auc", "early_stopping_rounds": 20,
    }

    model = xgb.XGBClassifier(**params)
    model.fit(X_train, y_train, eval_set=[(X_test, y_test)], verbose=False)

    y_pred = model.predict(X_test)
    y_prob = model.predict_proba(X_test)[:, 1]

    metrics = {
        "auc_roc": round(roc_auc_score(y_test, y_prob), 4),
        "f1_score": round(f1_score(y_test, y_pred), 4),
        "precision": round(precision_score(y_test, y_pred), 4),
        "recall": round(recall_score(y_test, y_pred), 4),
        "train_size": int(X_train.shape[0]),
        "test_size": int(X_test.shape[0]),
        "retrained_at": datetime.utcnow().isoformat(),
        "model_version": "auto-retrain",
    }
    return model, metrics


# ── STEP 4: QUALITY GATE ──────────────────────────────────────────
def quality_gate(metrics):
    auc = metrics["auc_roc"]
    if auc < AUC_THRESHOLD:
        logger.error(f"QUALITY GATE FAILED: AUC {auc} < {AUC_THRESHOLD}")
        logger.error("Deployment blocked. Keeping previous model.")
        return False
    logger.info(f"QUALITY GATE PASSED: AUC {auc} >= {AUC_THRESHOLD}")
    return True


# ── STEP 5: SAVE & LOG ────────────────────────────────────────────
def save_model(model, metrics):
    os.makedirs("models", exist_ok=True)

    if os.path.exists(MODEL_PATH):
        import shutil
        shutil.copy(MODEL_PATH, BACKUP_PATH)
        logger.info(f"Previous model backed up to {BACKUP_PATH}")

    joblib.dump(model, MODEL_PATH)
    with open(METRICS_PATH, "w") as f:
        json.dump(metrics, f, indent=2)

    logger.info(f"New model saved to {MODEL_PATH}")
    logger.info(f"Metrics: AUC={metrics['auc_roc']} F1={metrics['f1_score']}")


# ── MAIN ──────────────────────────────────────────────────────────
def main(n_samples=10000, force=False):
    print("=" * 60)
    print("🔄 CANAL MOINS — AUTOMATED MODEL RETRAINING")
    print(f"   Triggered at: {datetime.utcnow().isoformat()}")
    print("=" * 60)

    mlflow.set_experiment("canal-moins-churn-retrain")

    with mlflow.start_run(run_name=f"retrain-{datetime.utcnow().strftime('%Y%m%d-%H%M')}"):

        df = load_training_data(n_samples)
        df = engineer_features(df)
        model, metrics = train(df)

        mlflow.log_metrics({k: v for k, v in metrics.items()
                           if isinstance(v, (int, float))})

        if not quality_gate(metrics) and not force:
            print("\n❌ Retraining BLOCKED — quality gate failed")
            print(f"   AUC: {metrics['auc_roc']} (required: {AUC_THRESHOLD})")
            sys.exit(1)

        save_model(model, metrics)
        mlflow.xgboost.log_model(model, "model")

    print("\n✅ Retraining COMPLETE")
    print(f"   AUC-ROC  : {metrics['auc_roc']}")
    print(f"   F1 Score : {metrics['f1_score']}")
    print(f"   Model    : {MODEL_PATH}")
    print("=" * 60)
    return metrics


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Canal Moins — Model Retraining")
    parser.add_argument("--samples", type=int, default=10000)
    parser.add_argument("--force", action="store_true",
                        help="Force deploy even if AUC < threshold")
    args = parser.parse_args()
    main(n_samples=args.samples, force=args.force)
