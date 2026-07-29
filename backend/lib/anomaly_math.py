"""
Pure anomaly-detection math (GAP-03 / US-201). No DB, no I/O — everything here
takes plain data in and returns a decision, so it's directly unit-testable
(backend/tests/test_anomaly_math.py) without a live database, matching this
repo's existing pure-logic test convention (see tests/test_scenario.py).
"""

import statistics
from dataclasses import dataclass
from datetime import date
from typing import List, Optional, Tuple

ONGOING_STATUSES = ("open", "acknowledged")


@dataclass
class BaselineStats:
    mean: float
    stddev: float
    sample_size: int


def rolling_baseline(
    history: List[Tuple[date, float]],
    target_day: date,
    lookback_days: int = 28,
    min_same_weekday_samples: int = 3,
) -> BaselineStats:
    """E-02 (seasonal/day-of-week false positives): compares `target_day` only
    against prior occurrences of the SAME weekday within the lookback window
    (e.g. a Saturday dip is judged against prior Saturdays, not weekday
    averages) — an expected weekend dip stays inside its own baseline instead
    of reading as an anomaly. Falls back to all days in the window if there
    isn't enough same-weekday history yet (new metric / short history)."""
    same_weekday = [
        value
        for day, value in history
        if day.weekday() == target_day.weekday() and 0 < (target_day - day).days <= lookback_days
    ]
    samples = same_weekday if len(same_weekday) >= min_same_weekday_samples else [
        value for day, value in history if 0 < (target_day - day).days <= lookback_days
    ]
    if not samples:
        return BaselineStats(mean=0.0, stddev=0.0, sample_size=0)
    mean = statistics.fmean(samples)
    stddev = statistics.pstdev(samples) if len(samples) > 1 else 0.0
    return BaselineStats(mean=mean, stddev=stddev, sample_size=len(samples))


def is_breach(
    value: float,
    baseline: BaselineStats,
    threshold_type: str,
    threshold_value: float,
    direction: str = "any",
) -> Optional[float]:
    """Returns the signed deviation if `value` breaches the configured threshold
    vs `baseline`, else None. Insufficient baseline history (sample_size == 0,
    or a zero-spread stddev baseline for stddev_multiplier) never breaches —
    there's nothing to compare against yet, so no false alarm."""
    if baseline.sample_size == 0:
        return None

    if threshold_type == "stddev_multiplier":
        if baseline.stddev <= 0:
            return None
        deviation = (value - baseline.mean) / baseline.stddev
        breached = abs(deviation) >= threshold_value
    elif threshold_type == "percent_change":
        if baseline.mean == 0:
            return None
        deviation = ((value - baseline.mean) / abs(baseline.mean)) * 100.0
        breached = abs(deviation) >= threshold_value
    elif threshold_type == "absolute":
        deviation = value - baseline.mean
        breached = abs(deviation) >= threshold_value
    else:
        raise ValueError(f"Unknown threshold_type: {threshold_type}")

    if not breached:
        return None
    if direction == "above" and deviation <= 0:
        return None
    if direction == "below" and deviation >= 0:
        return None
    return deviation


def group_into_digest(breached_metric_keys: List[str], run_id: str) -> Optional[str]:
    """E-01 (alert storm): metrics that breach in the SAME detection run are one
    incident, not N. >1 simultaneous breach -> shared digest group id (the run
    id); a lone breach gets no digest grouping."""
    return run_id if len(breached_metric_keys) > 1 else None


def resolve_incident_key(metric_key: str, deviation: float) -> str:
    """Stable identity for 'the same ongoing anomaly' across checking intervals —
    keyed by metric + direction, so a metric swinging up then later down (two
    different, unrelated problems) doesn't get merged into one incident."""
    sign = "up" if deviation >= 0 else "down"
    return f"{metric_key}:{sign}"


def should_suppress_repeat(latest_alert_status: Optional[str]) -> bool:
    """E-05: an already-open (unresolved) alert for this incident means this
    breach is a continuation, not a new event — don't re-notify."""
    return latest_alert_status in ONGOING_STATUSES


def is_resolution(latest_alert_status: Optional[str], breached_now: bool) -> bool:
    """E-05: the metric just normalized after an ongoing incident -> exactly
    ONE resolution notice, not silence and not another breach alert."""
    return latest_alert_status in ONGOING_STATUSES and not breached_now
