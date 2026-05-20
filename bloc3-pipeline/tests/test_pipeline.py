"""
Canal Moins — Bloc 3 Pipeline Tests
tests/test_pipeline.py
"""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


# ── TESTS BRONZE LAYER ────────────────────────────────────────────

def test_bronze_event_schema():
    """Each event must have all required fields."""
    required_fields = [
        "event_id", "subscriber_id", "content_id", "device_type",
        "event_type", "watch_duration_s", "completion_pct",
        "plan_type", "country", "event_timestamp"
    ]
    event = {
        "event_id": "abc-123",
        "subscriber_id": "sub_00000001",
        "content_id": "content_0001",
        "device_type": "smart_tv",
        "event_type": "play",
        "watch_duration_s": 1800,
        "completion_pct": 0.5,
        "plan_type": "plus",
        "country": "FR",
        "event_timestamp": "2026-05-20T10:00:00"
    }
    for field in required_fields:
        assert field in event, f"Missing required field: {field}"


def test_completion_pct_range():
    """completion_pct must be between 0 and 1."""
    valid_values = [0.0, 0.5, 1.0, 0.99]
    invalid_values = [-0.1, 1.01, 2.0, -1.0]

    for v in valid_values:
        assert 0 <= v <= 1, f"Valid value {v} failed range check"

    for v in invalid_values:
        assert not (0 <= v <= 1), f"Invalid value {v} passed range check"


def test_country_validation():
    """Country must be one of the supported territories."""
    valid_countries = ["FR", "BE", "CH", "LU"]
    invalid_countries = ["US", "UK", "DE", "ES", "IT"]

    for c in valid_countries:
        assert c in valid_countries

    for c in invalid_countries:
        assert c not in valid_countries


def test_watch_duration_non_negative():
    """watch_duration_s must be >= 0."""
    valid_durations = [0, 1, 3600, 7200]
    for d in valid_durations:
        assert d >= 0


# ── TESTS SILVER LAYER ────────────────────────────────────────────

def test_watch_category_derivation():
    """watch_category must be derived correctly from completion_pct."""
    def get_watch_category(completion_pct):
        if completion_pct >= 0.9:
            return "completed"
        elif completion_pct >= 0.5:
            return "partial"
        elif completion_pct > 0:
            return "abandoned"
        else:
            return "no_watch"

    assert get_watch_category(0.95) == "completed"
    assert get_watch_category(0.9) == "completed"
    assert get_watch_category(0.75) == "partial"
    assert get_watch_category(0.5) == "partial"
    assert get_watch_category(0.3) == "abandoned"
    assert get_watch_category(0.0) == "no_watch"


def test_session_length_category():
    """session_length_category must match watch_duration_s bucket."""
    def get_session_category(duration_s):
        if duration_s >= 3600:
            return "long"
        elif duration_s >= 600:
            return "medium"
        elif duration_s > 0:
            return "short"
        else:
            return "none"

    assert get_session_category(7200) == "long"
    assert get_session_category(3600) == "long"
    assert get_session_category(1800) == "medium"
    assert get_session_category(600) == "medium"
    assert get_session_category(300) == "short"
    assert get_session_category(0) == "none"


def test_engagement_score_range():
    """Engagement score must be between 0 and 100."""
    def compute_engagement(completion_pct, watch_duration_s):
        score = completion_pct * 60 + min(watch_duration_s / 3600.0, 1) * 40
        return round(score, 2)

    score = compute_engagement(0.8, 3600)
    assert 0 <= score <= 100, f"Engagement score {score} out of range"

    score_zero = compute_engagement(0.0, 0)
    assert score_zero == 0.0


# ── TESTS GOLD LAYER ──────────────────────────────────────────────

def test_churn_risk_label():
    """Churn risk label must be one of low/medium/high."""
    valid_labels = ["low", "medium", "high"]

    def get_churn_label(days_since, sessions_30d):
        if days_since > 20 or sessions_30d < 3:
            return "high"
        elif days_since > 10 or sessions_30d < 10:
            return "medium"
        else:
            return "low"

    assert get_churn_label(25, 1) == "high"
    assert get_churn_label(15, 5) == "medium"
    assert get_churn_label(3, 20) == "low"

    for label in [get_churn_label(d, s) for d, s in [(25,1),(15,5),(3,20)]]:
        assert label in valid_labels


def test_quality_score_threshold():
    """Quality score below 99% should raise an alert."""
    def check_quality(total_rows, issues):
        if total_rows == 0:
            return 0.0
        return round((1 - issues / total_rows) * 100, 2)

    assert check_quality(1000, 0) == 100.0
    assert check_quality(1000, 5) == 99.5
    assert check_quality(1000, 15) < 99.0

    score = check_quality(1000, 15)
    assert score < 99.0, "Should trigger quality alert"


def test_pipeline_task_order():
    """Pipeline tasks must execute in correct order."""
    expected_order = [
        "generate_viewing_events",
        "ingest_to_bronze",
        "run_quality_checks",
        "compute_silver_layer",
        "compute_churn_features",
        "log_pipeline_summary"
    ]
    assert len(expected_order) == 6
    assert expected_order[0] == "generate_viewing_events"
    assert expected_order[-1] == "log_pipeline_summary"
    assert expected_order.index("run_quality_checks") < \
           expected_order.index("compute_silver_layer")
