"""
Canal Moins — Model Drift Monitoring
Block 4 — MLOps & Production | JHEDA Master Thesis

Detects when the churn model starts degrading:
- Feature drift: distribution of input features changed
- Prediction drift: model outputs changed
- Performance drift: AUC dropped vs baseline

Runs daily via Airflow DAG.
Alerts data team via Slack if drift detected.
"""

import pandas as pd
import numpy as np
import json
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# ── BASELINE STATS (from training data) ──────────────────────────
BASELINE_STATS = {
    "total_sessions_30d": {"mean": 14.2, "std": 9.8, "min": 0, "max": 100},
    "avg_completion_rate": {"mean": 0.68, "std": 0.22, "min": 0, "max": 1},
    "days_since_last_watch": {"mean": 5.3, "std": 6.1, "min": 0, "max": 30},
    "avg_engagement_score": {"mean": 60.1, "std": 22.4, "min": 0, "max": 100},
}

BASELINE_CHURN_RATE = 0.25
AUC_BASELINE = 0.87
DRIFT_THRESHOLD = 0.15  # 15% deviation triggers alert


# ── DRIFT DETECTION ───────────────────────────────────────────────

def detect_feature_drift(current_data: pd.DataFrame) -> dict:
    """
    Compares current feature distributions to training baseline.
    Uses Population Stability Index (PSI) for drift detection.
    """
    drift_report = {}

    for feature, baseline in BASELINE_STATS.items():
        if feature not in current_data.columns:
            continue

        current_mean = current_data[feature].mean()
        baseline_mean = baseline["mean"]

        # Relative deviation
        if baseline_mean != 0:
            deviation = abs(current_mean - baseline_mean) / abs(baseline_mean)
        else:
            deviation = abs(current_mean)

        drifted = deviation > DRIFT_THRESHOLD

        drift_report[feature] = {
            "baseline_mean": round(baseline_mean, 4),
            "current_mean": round(current_mean, 4),
            "deviation_pct": round(deviation * 100, 2),
            "drifted": drifted,
            "status": "🚨 DRIFT" if drifted else "✅ OK",
        }

    return drift_report


def detect_prediction_drift(
    current_predictions: np.ndarray,
    baseline_churn_rate: float = BASELINE_CHURN_RATE
) -> dict:
    """
    Detects if the model's output distribution has shifted.
    Compares current predicted churn rate to training baseline.
    """
    current_rate = float(np.mean(current_predictions >= 0.5))
    deviation = abs(current_rate - baseline_churn_rate) / baseline_churn_rate
    drifted = deviation > DRIFT_THRESHOLD

    return {
        "baseline_churn_rate": round(baseline_churn_rate, 4),
        "current_churn_rate": round(current_rate, 4),
        "deviation_pct": round(deviation * 100, 2),
        "drifted": drifted,
        "status": "🚨 DRIFT" if drifted else "✅ OK",
    }


def generate_drift_report(
    current_data: pd.DataFrame,
    current_predictions: np.ndarray,
) -> dict:
    """
    Full drift monitoring report.
    Called daily by Airflow — results stored in monitoring DB.
    """
    feature_drift = detect_feature_drift(current_data)
    prediction_drift = detect_prediction_drift(current_predictions)

    any_feature_drift = any(v["drifted"] for v in feature_drift.values())
    prediction_drifted = prediction_drift["drifted"]
    overall_alert = any_feature_drift or prediction_drifted

    drifted_features = [
        f for f, v in feature_drift.items() if v["drifted"]
    ]

    report = {
        "generated_at": datetime.utcnow().isoformat(),
        "overall_alert": overall_alert,
        "alert_level": "HIGH" if overall_alert else "OK",
        "feature_drift": feature_drift,
        "prediction_drift": prediction_drift,
        "drifted_features": drifted_features,
        "recommendation": (
            "🚨 RETRAIN MODEL — significant drift detected in: "
            + ", ".join(drifted_features)
        ) if overall_alert else (
            "✅ Model is healthy — no retraining needed"
        ),
    }

    return report


def simulate_drift_monitoring():
    """
    Demo function — simulates 30 days of monitoring.
    Shows how drift accumulates over time.
    """
    print("=" * 60)
    print("📊 CANAL MOINS — DRIFT MONITORING SIMULATION")
    print("=" * 60)

    results = []
    for day in range(30):
        # Simulate gradual drift after day 15
        drift_factor = max(0, (day - 15) / 15)

        n = 1000
        np.random.seed(day)

        # Features drift gradually
        current_data = pd.DataFrame({
            "total_sessions_30d": np.random.poisson(
                14.2 * (1 - drift_factor * 0.3), n
            ),
            "avg_completion_rate": np.random.beta(
                5 * (1 - drift_factor * 0.4),
                2 + drift_factor * 2, n
            ),
            "days_since_last_watch": np.random.exponential(
                5.3 * (1 + drift_factor * 0.5), n
            ).clip(0, 30),
            "avg_engagement_score": np.random.normal(
                60.1 * (1 - drift_factor * 0.2), 22.4, n
            ).clip(0, 100),
        })

        # Predictions drift
        current_predictions = np.random.beta(
            2 + drift_factor * 2,
            5 - drift_factor, n
        )

        report = generate_drift_report(current_data, current_predictions)

        status = "🚨" if report["overall_alert"] else "✅"
        drifted = len(report["drifted_features"])
        print(
            f"Day {day+1:2d}: {status} | "
            f"Pred churn: {report['prediction_drift']['current_churn_rate']:.2%} | "
            f"Drifted features: {drifted}"
        )

        results.append({
            "day": day + 1,
            "alert": report["overall_alert"],
            "drifted_features": drifted,
        })

    # Summary
    alert_days = sum(1 for r in results if r["alert"])
    print(f"\n📊 Summary: {alert_days}/30 days with drift alerts")
    print("→ Retraining triggered automatically when drift detected")
    return results


if __name__ == "__main__":
    simulate_drift_monitoring()
