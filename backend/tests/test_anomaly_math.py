"""Anomaly Detection & Proactive Alerting (GAP-03 / US-201) — pure math in
lib/anomaly_math.py. No DB, no network (matches this repo's pure-logic test
convention, see tests/test_scenario.py)."""

import datetime as dt

from lib import anomaly_math as am


# ── TC-01: breach detection ──────────────────────────────────────────────────
def test_breach_detected_when_far_from_baseline():
    baseline = am.BaselineStats(mean=100.0, stddev=5.0, sample_size=10)
    deviation = am.is_breach(70.0, baseline, "stddev_multiplier", 2.0, "any")
    assert deviation is not None
    assert deviation < 0  # signed: value dropped below baseline


def test_no_breach_within_threshold():
    baseline = am.BaselineStats(mean=100.0, stddev=5.0, sample_size=10)
    assert am.is_breach(102.0, baseline, "stddev_multiplier", 2.0, "any") is None


def test_direction_filter_ignores_opposite_direction():
    baseline = am.BaselineStats(mean=100.0, stddev=5.0, sample_size=10)
    # Value dropped, but this threshold only cares about increases.
    assert am.is_breach(70.0, baseline, "stddev_multiplier", 2.0, "above") is None
    assert am.is_breach(130.0, baseline, "stddev_multiplier", 2.0, "above") is not None


def test_no_breach_without_enough_baseline_history():
    baseline = am.BaselineStats(mean=0.0, stddev=0.0, sample_size=0)
    assert am.is_breach(1000.0, baseline, "stddev_multiplier", 2.0, "any") is None


def test_percent_change_threshold_type():
    baseline = am.BaselineStats(mean=100.0, stddev=0.0, sample_size=5)
    assert am.is_breach(60.0, baseline, "percent_change", 25.0, "any") is not None
    assert am.is_breach(90.0, baseline, "percent_change", 25.0, "any") is None


# ── TC-02: alert storm -> single digest ──────────────────────────────────────
def test_multiple_simultaneous_breaches_grouped_into_digest():
    group_id = am.group_into_digest(["daily_signups", "churn_rate", "day1_retention"], "run-42")
    assert group_id == "run-42"


def test_lone_breach_gets_no_digest_grouping():
    assert am.group_into_digest(["daily_signups"], "run-42") is None


def test_zero_breaches_gets_no_digest_grouping():
    assert am.group_into_digest([], "run-42") is None


# ── TC-03: seasonal/day-of-week baseline avoids false positives ────────────
def test_seasonal_baseline_compares_against_same_weekday_only():
    # Monday..Sunday values: weekdays high (100), weekends low but with a
    # little natural variance (38/40/42) — an expected weekend dip.
    monday = dt.date(2026, 6, 1)
    history = []
    for i in range(35):
        day = monday + dt.timedelta(days=i)
        if day.weekday() == 5:  # Saturday
            value = [38.0, 40.0, 42.0][(i // 7) % 3]
        elif day.weekday() == 6:  # Sunday
            value = 40.0
        else:
            value = 100.0
        history.append((day, value))

    # A Saturday just past the history window.
    target_saturday = monday + dt.timedelta(days=40)
    assert target_saturday.weekday() == 5

    baseline = am.rolling_baseline(history, target_saturday, lookback_days=28)
    # Weekday-blended mean would be far higher than 40 — asserting the
    # baseline landed near the Saturday-only mean proves it used same-weekday
    # samples, not everything in the window.
    assert 35.0 < baseline.mean < 45.0

    # A typical Saturday dip (39) must NOT breach against its own baseline.
    deviation = am.is_breach(39.0, baseline, "stddev_multiplier", 2.0, "any")
    assert deviation is None


def test_seasonal_baseline_falls_back_to_all_days_when_sparse():
    # Only 2 days of history total — not enough same-weekday samples, so the
    # fallback (all days in window) still produces a usable baseline instead
    # of an empty one.
    monday = dt.date(2026, 6, 1)
    history = [(monday, 100.0), (monday + dt.timedelta(days=1), 90.0)]
    baseline = am.rolling_baseline(history, monday + dt.timedelta(days=2))
    assert baseline.sample_size == 2


# ── TC-05: ongoing-incident suppression + single resolution notice ─────────
def test_incident_key_stable_by_direction():
    assert am.resolve_incident_key("churn_rate", 3.2) == "churn_rate:up"
    assert am.resolve_incident_key("churn_rate", -3.2) == "churn_rate:down"


def test_repeat_breach_suppressed_while_incident_open():
    assert am.should_suppress_repeat("open") is True
    assert am.should_suppress_repeat("acknowledged") is True


def test_repeat_breach_not_suppressed_once_resolved_or_new():
    assert am.should_suppress_repeat("resolved") is False
    assert am.should_suppress_repeat("false_positive") is False
    assert am.should_suppress_repeat(None) is False


def test_resolution_fires_exactly_once_when_metric_normalizes():
    assert am.is_resolution("open", breached_now=False) is True
    # Still breaching -> not a resolution.
    assert am.is_resolution("open", breached_now=True) is False
    # No prior ongoing incident -> nothing to resolve.
    assert am.is_resolution(None, breached_now=False) is False
    assert am.is_resolution("resolved", breached_now=False) is False
