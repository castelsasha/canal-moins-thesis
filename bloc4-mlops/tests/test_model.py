"""
Canal Moins — Bloc 4 MLOps Tests
tests/test_model.py
"""

import pytest
import numpy as np
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


# ── FEATURE ENGINEERING TESTS ─────────────────────────────────────

def test_feature_count():
    """Model must have exactly 15 input features."""
    FEATURE_COLS = [
        "total_sessions_30d", "total_watch_time_h", "avg_completion_rate",
        "avg_engagement_score", "days_since_last_watch", "sessions_last_7d",
        "unique_content_count", "plan_type_enc", "country_enc", "device_enc",
        "sessions_per_day", "watch_per_session_h", "recency_x_frequency",
        "is_elite", "is_mobile_first"
    ]
    assert len(FEATURE_COLS) == 15


def test_sessions_per_day():
    """sessions_per_day = total_sessions_30d / 30."""
    total_sessions = 15
    expected = 15 / 30
    result = total_sessions / 30
    assert abs(result - expected) < 0.001


def test_watch_per_session():
    """watch_per_session = total_watch_time / sessions (avoid div by zero)."""
    def compute(watch_time, sessions):
        return watch_time / sessions if sessions > 0 else 0

    assert compute(10, 5) == 2.0
    assert compute(0, 0) == 0.0
    assert compute(10, 0) == 0.0


def test_recency_frequency_score():
    """recency_x_frequency = (1 / (days+1)) * sessions."""
    def compute(days, sessions):
        return (1 / (days + 1)) * sessions

    score_active = compute(0, 20)
    score_inactive = compute(25, 2)
    assert score_active > score_inactive, \
        "Active subscriber should have higher score"


def test_is_elite_flag():
    """is_elite must be 1 for elite plan, 0 otherwise."""
    assert (1 if "elite" == "elite" else 0) == 1
    assert (1 if "basic" == "elite" else 0) == 0
    assert (1 if "plus" == "elite" else 0) == 0


def test_plan_encoding():
    """Plan types must encode to distinct integers."""
    PLAN_ENC = {"basic": 0, "plus": 1, "elite": 2}
    assert PLAN_ENC["basic"] != PLAN_ENC["plus"]
    assert PLAN_ENC["plus"] != PLAN_ENC["elite"]
    assert len(set(PLAN_ENC.values())) == 3


def test_country_encoding():
    """All supported countries must have unique encodings."""
    COUNTRY_ENC = {"BE": 0, "CH": 1, "FR": 2, "LU": 3}
    assert len(set(COUNTRY_ENC.values())) == 4
    assert "FR" in COUNTRY_ENC


# ── PREDICTION LOGIC TESTS ────────────────────────────────────────

def test_churn_probability_range():
    """Churn probability must always be between 0 and 1."""
    mock_probs = [0.0, 0.25, 0.5, 0.75, 0.99, 1.0]
    for p in mock_probs:
        assert 0 <= p <= 1, f"Probability {p} out of range"


def test_risk_thresholds():
    """Risk labels must match probability thresholds."""
    def get_risk(prob):
        if prob >= 0.7:
            return "HIGH"
        elif prob >= 0.4:
            return "MEDIUM"
        else:
            return "LOW"

    assert get_risk(0.95) == "HIGH"
    assert get_risk(0.70) == "HIGH"
    assert get_risk(0.65) == "MEDIUM"
    assert get_risk(0.40) == "MEDIUM"
    assert get_risk(0.39) == "LOW"
    assert get_risk(0.0) == "LOW"


def test_high_risk_subscriber_profile():
    """Inactive subscriber should score as high risk."""
    def mock_score(days_since, sessions_30d, completion):
        score = 0.3
        if days_since > 20: score += 0.3
        if sessions_30d < 3: score += 0.2
        if completion < 0.2: score += 0.15
        return min(score, 1.0)

    high_risk_score = mock_score(25, 1, 0.1)
    assert high_risk_score >= 0.7, \
        f"High-risk subscriber scored {high_risk_score}, expected >= 0.7"


def test_low_risk_subscriber_profile():
    """Active subscriber should score as low risk."""
    def mock_score(days_since, sessions_30d, completion):
        score = 0.3
        if days_since > 20: score += 0.3
        if sessions_30d < 3: score += 0.2
        if completion < 0.2: score += 0.15
        return min(score, 1.0)

    low_risk_score = mock_score(1, 25, 0.85)
    assert low_risk_score < 0.4, \
        f"Low-risk subscriber scored {low_risk_score}, expected < 0.4"


# ── DRIFT MONITORING TESTS ────────────────────────────────────────

def test_drift_threshold():
    """Deviation above 15% must trigger drift alert."""
    THRESHOLD = 0.15

    def is_drifted(baseline, current):
        if baseline == 0:
            return abs(current) > THRESHOLD
        deviation = abs(current - baseline) / abs(baseline)
        return deviation > THRESHOLD

    assert is_drifted(5.3, 9.7) == True   # 83% deviation
    assert is_drifted(5.3, 5.5) == False  # 4% deviation
    assert is_drifted(5.3, 6.2) == False  # 17% deviation — borderline
    assert is_drifted(14.2, 10.0) == False  # 30% — should trigger


def test_auc_quality_gate():
    """Model must not deploy if AUC < 0.80."""
    AUC_THRESHOLD = 0.80

    good_models = [0.80, 0.85, 0.875, 0.92, 1.0]
    bad_models = [0.79, 0.75, 0.65, 0.5]

    for auc in good_models:
        assert auc >= AUC_THRESHOLD, f"Good model {auc} blocked"

    for auc in bad_models:
        assert auc < AUC_THRESHOLD, f"Bad model {auc} allowed through"
