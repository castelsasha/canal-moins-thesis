"""
Canal Moins — Churn Prediction Model
Block 4 — MLOps & Production | JHEDA Master Thesis

Model: XGBoost binary classifier
Target: churn in next 30 days (1 = churns, 0 = stays)
Features: viewing behaviour from Gold layer (Block 3)
"""

import pandas as pd
import numpy as np
import xgboost as xgb
import mlflow
import mlflow.xgboost
import joblib
import json
import os
from datetime import datetime
from sklearn.model_selection import train_test_split, StratifiedKFold
from sklearn.metrics import (
    roc_auc_score, f1_score, precision_score,
    recall_score, confusion_matrix, classification_report
)
from sklearn.preprocessing import LabelEncoder

# ── CONFIG ────────────────────────────────────────────────────────
RANDOM_STATE = 42
MODEL_VERSION = "1.0.0"
MODEL_PATH = "models/churn_model.pkl"
METRICS_PATH = "models/metrics.json"
FEATURES_PATH = "models/feature_importance.json"

os.makedirs("models", exist_ok=True)

# ── 1. GENERATE TRAINING DATA ────────────────────────────────────
def generate_training_data(n_samples=10000):
    """
    Simulates the gold_churn_features table from Block 3.
    In production: reads directly from Redshift Gold layer.
    """
    np.random.seed(RANDOM_STATE)

    print(f"📊 Generating {n_samples} subscriber records...")

    # Churners tend to have lower activity
    churn_mask = np.random.choice([0, 1], n_samples, p=[0.75, 0.25])

    data = {
        "subscriber_id": [f"sub_{i:08d}" for i in range(n_samples)],

        # Volume features — churners watch less
        "total_sessions_30d": np.where(
            churn_mask,
            np.random.poisson(3, n_samples),
            np.random.poisson(18, n_samples)
        ).clip(0, 100),

        "total_watch_time_h": np.where(
            churn_mask,
            np.abs(np.random.normal(2, 3, n_samples)),
            np.abs(np.random.normal(25, 15, n_samples))
        ).round(2),

        # Engagement features — churners complete less
        "avg_completion_rate": np.where(
            churn_mask,
            np.random.beta(2, 5, n_samples),
            np.random.beta(5, 2, n_samples)
        ).round(4),

        "avg_engagement_score": np.where(
            churn_mask,
            np.random.normal(25, 15, n_samples),
            np.random.normal(72, 18, n_samples)
        ).clip(0, 100).round(2),

        # Recency features — churners haven't watched recently
        "days_since_last_watch": np.where(
            churn_mask,
            np.random.exponential(15, n_samples),
            np.random.exponential(3, n_samples)
        ).clip(0, 30).round(0).astype(int),

        "sessions_last_7d": np.where(
            churn_mask,
            np.random.poisson(0.5, n_samples),
            np.random.poisson(5, n_samples)
        ).clip(0, 30),

        # Content diversity
        "unique_content_count": np.where(
            churn_mask,
            np.random.poisson(2, n_samples),
            np.random.poisson(12, n_samples)
        ).clip(0, 50),

        # Categorical features
        "plan_type": np.random.choice(
            ["basic", "plus", "elite"],
            n_samples,
            p=[0.5, 0.35, 0.15]
        ),
        "country": np.random.choice(
            ["FR", "BE", "CH", "LU"],
            n_samples,
            p=[0.7, 0.15, 0.1, 0.05]
        ),
        "favourite_device": np.random.choice(
            ["smart_tv", "mobile", "web", "tablet"],
            n_samples,
            p=[0.4, 0.3, 0.2, 0.1]
        ),

        # Target
        "churned_30d": churn_mask
    }

    df = pd.DataFrame(data)
    print(f"✅ Dataset: {df.shape[0]} rows, {df.shape[1]} columns")
    print(f"   Churn rate: {df['churned_30d'].mean():.1%}")
    return df


# ── 2. FEATURE ENGINEERING ───────────────────────────────────────
def engineer_features(df):
    """Derives additional predictive features."""
    print("⚙️  Engineering features...")

    df = df.copy()

    # Encode categoricals
    le_plan = LabelEncoder()
    le_country = LabelEncoder()
    le_device = LabelEncoder()

    df["plan_type_enc"] = le_plan.fit_transform(df["plan_type"])
    df["country_enc"] = le_country.fit_transform(df["country"])
    df["device_enc"] = le_device.fit_transform(df["favourite_device"])

    # Derived features
    df["sessions_per_day"] = (df["total_sessions_30d"] / 30).round(4)
    df["watch_per_session_h"] = np.where(
        df["total_sessions_30d"] > 0,
        df["total_watch_time_h"] / df["total_sessions_30d"],
        0
    ).round(4)
    df["recency_x_frequency"] = (
        (1 / (df["days_since_last_watch"] + 1)) * df["total_sessions_30d"]
    ).round(4)
    df["is_elite"] = (df["plan_type"] == "elite").astype(int)
    df["is_mobile_first"] = (df["favourite_device"] == "mobile").astype(int)

    print(f"✅ Features engineered: {df.shape[1]} total columns")
    return df, le_plan, le_country, le_device


# ── 3. TRAIN MODEL ───────────────────────────────────────────────
FEATURE_COLS = [
    "total_sessions_30d", "total_watch_time_h", "avg_completion_rate",
    "avg_engagement_score", "days_since_last_watch", "sessions_last_7d",
    "unique_content_count", "plan_type_enc", "country_enc", "device_enc",
    "sessions_per_day", "watch_per_session_h", "recency_x_frequency",
    "is_elite", "is_mobile_first"
]

def train_model(df):
    """Trains XGBoost classifier with MLflow tracking."""
    print("\n🤖 Training XGBoost churn model...")

    X = df[FEATURE_COLS]
    y = df["churned_30d"]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=RANDOM_STATE, stratify=y
    )

    print(f"   Train: {X_train.shape[0]} | Test: {X_test.shape[0]}")

    # XGBoost parameters
    params = {
        "n_estimators": 200,
        "max_depth": 6,
        "learning_rate": 0.05,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "min_child_weight": 3,
        "scale_pos_weight": 3,  # handles class imbalance
        "random_state": RANDOM_STATE,
        "eval_metric": "auc",
        "early_stopping_rounds": 20,
    }

    mlflow.set_experiment("canal-moins-churn")

    with mlflow.start_run(run_name=f"xgboost-v{MODEL_VERSION}"):
        mlflow.log_params(params)

        model = xgb.XGBClassifier(**params)
        model.fit(
            X_train, y_train,
            eval_set=[(X_test, y_test)],
            verbose=50
        )

        # Evaluate
        y_pred = model.predict(X_test)
        y_prob = model.predict_proba(X_test)[:, 1]

        metrics = {
            "auc_roc": round(roc_auc_score(y_test, y_prob), 4),
            "f1_score": round(f1_score(y_test, y_pred), 4),
            "precision": round(precision_score(y_test, y_pred), 4),
            "recall": round(recall_score(y_test, y_pred), 4),
            "train_size": int(X_train.shape[0]),
            "test_size": int(X_test.shape[0]),
            "model_version": MODEL_VERSION,
            "trained_at": datetime.utcnow().isoformat(),
        }

        mlflow.log_metrics({k: v for k, v in metrics.items()
                           if isinstance(v, (int, float))})
        mlflow.xgboost.log_model(model, "model")

        print(f"\n📈 Model Performance:")
        print(f"   AUC-ROC   : {metrics['auc_roc']:.4f}")
        print(f"   F1 Score  : {metrics['f1_score']:.4f}")
        print(f"   Precision : {metrics['precision']:.4f}")
        print(f"   Recall    : {metrics['recall']:.4f}")

        print(f"\n{classification_report(y_test, y_pred, target_names=['stays', 'churns'])}")

        # Feature importance
        importance = dict(zip(
            FEATURE_COLS,
            model.feature_importances_.tolist()
        ))
        importance_sorted = dict(sorted(
            importance.items(), key=lambda x: x[1], reverse=True
        ))

        print(f"\n🔍 Top 5 features:")
        for feat, imp in list(importance_sorted.items())[:5]:
            print(f"   {feat}: {imp:.4f}")

        # Save artifacts
        joblib.dump(model, MODEL_PATH)
        with open(METRICS_PATH, "w") as f:
            json.dump(metrics, f, indent=2)
        with open(FEATURES_PATH, "w") as f:
            json.dump(importance_sorted, f, indent=2)

        print(f"\n✅ Model saved to {MODEL_PATH}")
        return model, metrics, importance_sorted


# ── MAIN ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print("🎬 CANAL MOINS — CHURN PREDICTION MODEL TRAINING")
    print("=" * 60)

    df_raw = generate_training_data(n_samples=10000)
    df_features, le_plan, le_country, le_device = engineer_features(df_raw)
    model, metrics, importance = train_model(df_features)

    print("\n" + "=" * 60)
    print("🏁 TRAINING COMPLETE")
    print(f"   AUC-ROC: {metrics['auc_roc']} | F1: {metrics['f1_score']}")
    print("=" * 60)
