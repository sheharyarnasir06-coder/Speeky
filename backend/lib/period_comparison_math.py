"""
Pure period-over-period comparison math (GAP-06 / US-204). No DB, no I/O —
directly unit-testable (backend/tests/test_period_comparison_math.py),
matching this repo's pure-logic test convention.
"""

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from typing import List, Optional

WOW = "WoW"
MOM = "MoM"
YOY = "YoY"
VALID_BASES = (WOW, MOM, YOY)

MIN_DAYS_FOR_WOW = 14   # need a full prior week too
MIN_DAYS_FOR_MOM = 60   # need a full prior calendar month too
MIN_DAYS_FOR_YOY = 365


@dataclass
class PeriodRange:
    current_start: date
    current_end: date
    prior_start: date
    prior_end: date
    day_count_mismatch: bool  # E-03


@dataclass
class DeltaResult:
    current_value: float
    prior_value: float
    pct_change: Optional[float]  # None when is_new
    direction: str  # "up" | "down" | "flat" | "new"
    is_new: bool  # E-04


def _add_months(d: date, months: int) -> date:
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def resolve_period_range(basis: str, reference_date: date) -> PeriodRange:
    """Current period always ends at `reference_date` (inclusive). The prior
    period is the immediately preceding equivalent window.

    E-03: MoM uses real calendar months (via `_add_months`/`calendar.monthrange`,
    same clamping approach as lib/recurrence.py) rather than a fixed 30-day
    window, so a February-vs-31-day-month comparison is explicitly flagged via
    `day_count_mismatch` instead of silently understating/overstating the delta.
    """
    if basis == WOW:
        current_start = reference_date - timedelta(days=6)
        current_end = reference_date
        prior_start = current_start - timedelta(days=7)
        prior_end = current_end - timedelta(days=7)
        mismatch = False
    elif basis == MOM:
        current_start = reference_date.replace(day=1)
        current_end = reference_date
        prior_month_end = current_start - timedelta(days=1)
        prior_start = prior_month_end.replace(day=1)
        # Prior period covers the same day-of-month count as the current
        # (partial or full) month, clamped to the prior month's real length.
        days_elapsed = (current_end - current_start).days
        prior_end = min(prior_start + timedelta(days=days_elapsed), prior_month_end)
        current_len = (current_end - current_start).days + 1
        prior_len = (prior_end - prior_start).days + 1
        mismatch = current_len != prior_len
    elif basis == YOY:
        current_start = reference_date.replace(month=1, day=1)
        current_end = reference_date
        prior_start = _add_months(current_start, -12)
        prior_end = _add_months(current_end, -12)
        current_len = (current_end - current_start).days + 1
        prior_len = (prior_end - prior_start).days + 1
        mismatch = current_len != prior_len  # leap-year Feb 29 edge case
    else:
        raise ValueError(f"Unknown comparison basis: {basis}")

    return PeriodRange(current_start, current_end, prior_start, prior_end, mismatch)


def compute_delta(current: float, prior: float) -> DeltaResult:
    """E-04: a zero prior value (e.g. a feature that had 0 sessions before
    launch) can't produce a percentage — returns `is_new=True` instead of
    dividing by zero or fabricating an infinite/undefined percent."""
    if prior == 0:
        return DeltaResult(
            current_value=current, prior_value=prior, pct_change=None,
            direction="new" if current > 0 else "flat", is_new=True,
        )
    pct = round(((current - prior) / abs(prior)) * 100.0, 2)
    direction = "up" if pct > 0 else "down" if pct < 0 else "flat"
    return DeltaResult(current_value=current, prior_value=prior, pct_change=pct, direction=direction, is_new=False)


def available_comparison_bases(launch_date: date, now: date) -> List[str]:
    """E-01: a comparison basis is only offered once there's enough history
    for BOTH the current and prior equivalent windows to be real data, not a
    misleading partial one. Returns the subset of VALID_BASES usable today."""
    days_of_history = (now - launch_date).days
    available = []
    if days_of_history >= MIN_DAYS_FOR_WOW:
        available.append(WOW)
    if days_of_history >= MIN_DAYS_FOR_MOM:
        available.append(MOM)
    if days_of_history >= MIN_DAYS_FOR_YOY:
        available.append(YOY)
    return available


def outage_overlaps_window(incident_start: date, incident_end: date, window_start: date, window_end: date) -> bool:
    """E-02: whether a known data-collection-gap incident overlaps the prior
    (baseline) comparison window — used to attach a footnote so the delta
    isn't misread as a genuine trend."""
    return incident_start <= window_end and incident_end >= window_start
