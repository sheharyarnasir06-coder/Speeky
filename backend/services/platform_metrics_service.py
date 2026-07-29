"""
Shared Platform Analytics data-aggregation pipeline (GAP-03 / GAP-04).

This is the ONE place platform-wide metrics are computed. The anomaly monitor
(services/anomaly_detection_service.py), the scheduled-report generator
(services/report_service.py), and the admin analytics dashboard endpoint below
all call into this module — so a report can never show a different number
than the dashboard for the same window (GAP-04 acceptance criterion).

Unlike services/progress_dashboard_service.py (which pulls a single user's
rows into Python and reduces them there), these queries are platform-wide, so
they use date-bucketed raw SQL (`db.query_raw`, same primitive already used in
services/script_practice_service.py:261) instead of pulling whole tables.

Metrics:
  - daily_signups   : count of User rows created per day.
  - day1_retention  : % of a day's signup cohort with >=1 completed session
                       within 1 day of signing up.
  - day7_retention  : same, within 7 days.
  - churn_rate      : % of users active in the [day-28, day-14) window with
                       no activity in the following [day-14, day) window.
  - revenue         : NO BILLING/SUBSCRIPTION MODEL EXISTS ANYWHERE IN THIS
                       CODEBASE (checked schema.prisma) — this is a flagged
                       placeholder (always 0, unavailable=True) so thresholds/
                       report-selection/the E-04 external-send confirmation
                       are all real and testable. Wire a real billing pipeline
                       here when one exists.

"Retention" and "churn" are both approximated from completed-session
timestamps across the same 4 tables progress_dashboard_service.py already
reads (BaselineAssessment, CoachingSession, ScenarioSession,
PublicSpeakingSession) — this app has no separate "activity" event log.
"""

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, TypedDict

from fastapi import Depends

from lib.prisma_client import db
from middlewares.auth_middleware import require_admin

logger = logging.getLogger(__name__)

DAILY_SIGNUPS = "daily_signups"
DAY1_RETENTION = "day1_retention"
DAY7_RETENTION = "day7_retention"
CHURN_RATE = "churn_rate"
REVENUE = "revenue"

METRIC_KEYS = (DAILY_SIGNUPS, DAY1_RETENTION, DAY7_RETENTION, CHURN_RATE, REVENUE)

METRIC_LABELS: Dict[str, str] = {
    DAILY_SIGNUPS: "Daily Signups",
    DAY1_RETENTION: "Day-1 Retention",
    DAY7_RETENTION: "Day-7 Retention",
    CHURN_RATE: "Churn Rate",
    REVENUE: "Revenue",
}

# E-04: metrics that trigger the external-recipient confirmation warning.
SENSITIVE_METRICS = frozenset({REVENUE})


class MetricPoint(TypedDict):
    date: str  # YYYY-MM-DD
    value: float


# Every "session completion" event this app has, unioned. Reused by both the
# retention and churn queries so they agree on what "active" means.
_COMPLETIONS_CTE = """
completions AS (
  SELECT "userId", "completedAt" FROM baseline_assessments WHERE "completedAt" IS NOT NULL
  UNION ALL
  SELECT "userId", "completedAt" FROM coaching_sessions WHERE "completedAt" IS NOT NULL
  UNION ALL
  SELECT "userId", "completedAt" FROM scenario_sessions WHERE "completedAt" IS NOT NULL
  UNION ALL
  SELECT "userId", "completedAt" FROM public_speaking_sessions WHERE "completedAt" IS NOT NULL
)
"""

_SQL_SIGNUPS = """
SELECT d::date AS day, COUNT(u.id)::int AS value
FROM generate_series($1::date, $2::date, interval '1 day') AS d
LEFT JOIN users u ON u."createdAt" >= d AND u."createdAt" < d + interval '1 day'
GROUP BY d
ORDER BY d
"""

_SQL_RETENTION = f"""
WITH days AS (
  SELECT d::date AS day FROM generate_series($1::date, $2::date, interval '1 day') AS d
),
cohort AS (
  SELECT id AS "userId", date_trunc('day', "createdAt") AS signup_day
  FROM users
  WHERE "createdAt" >= $1::date AND "createdAt" < ($2::date + interval '1 day')
),
{_COMPLETIONS_CTE}
SELECT days.day AS day,
       COUNT(DISTINCT cohort."userId")::int AS cohort_size,
       COUNT(DISTINCT CASE WHEN completions."completedAt" IS NOT NULL
             AND completions."completedAt" < cohort.signup_day + (interval '1 day' * $3::int)
             THEN cohort."userId" END)::int AS retained
FROM days
LEFT JOIN cohort ON cohort.signup_day = days.day
LEFT JOIN completions ON completions."userId" = cohort."userId"
GROUP BY days.day
ORDER BY days.day
"""

_SQL_CHURN = f"""
WITH days AS (
  SELECT d::date AS day FROM generate_series($1::date, $2::date, interval '1 day') AS d
),
{_COMPLETIONS_CTE},
prior_active AS (
  SELECT days.day, completions."userId"
  FROM days
  JOIN completions
    ON completions."completedAt" >= days.day - interval '28 days'
   AND completions."completedAt" < days.day - interval '14 days'
  GROUP BY days.day, completions."userId"
),
recent_active AS (
  SELECT days.day, completions."userId"
  FROM days
  JOIN completions
    ON completions."completedAt" >= days.day - interval '14 days'
   AND completions."completedAt" < days.day
  GROUP BY days.day, completions."userId"
)
SELECT days.day AS day,
       COUNT(DISTINCT prior_active."userId")::int AS prior_active_count,
       COUNT(DISTINCT CASE WHEN recent_active."userId" IS NULL THEN prior_active."userId" END)::int AS churned_count
FROM days
LEFT JOIN prior_active ON prior_active.day = days.day
LEFT JOIN recent_active ON recent_active.day = days.day AND recent_active."userId" = prior_active."userId"
GROUP BY days.day
ORDER BY days.day
"""


def _day_str(value) -> str:
    if isinstance(value, str):
        return value[:10]
    return value.date().isoformat() if hasattr(value, "date") else str(value)[:10]


async def _signups_series(start: date, end: date) -> List[MetricPoint]:
    rows = await db.query_raw(_SQL_SIGNUPS, start.isoformat(), end.isoformat())
    return [{"date": _day_str(r["day"]), "value": float(r["value"])} for r in rows]


async def _retention_series(start: date, end: date, within_days: int) -> List[MetricPoint]:
    rows = await db.query_raw(_SQL_RETENTION, start.isoformat(), end.isoformat(), within_days)
    points: List[MetricPoint] = []
    for r in rows:
        cohort_size = r["cohort_size"] or 0
        pct = round((r["retained"] / cohort_size) * 100.0, 2) if cohort_size else 0.0
        points.append({"date": _day_str(r["day"]), "value": pct})
    return points


async def _churn_series(start: date, end: date) -> List[MetricPoint]:
    rows = await db.query_raw(_SQL_CHURN, start.isoformat(), end.isoformat())
    points: List[MetricPoint] = []
    for r in rows:
        prior = r["prior_active_count"] or 0
        pct = round((r["churned_count"] / prior) * 100.0, 2) if prior else 0.0
        points.append({"date": _day_str(r["day"]), "value": pct})
    return points


def _revenue_series(start: date, end: date) -> List[MetricPoint]:
    days = (end - start).days
    return [
        {"date": (start + timedelta(days=i)).isoformat(), "value": 0.0}
        for i in range(days + 1)
    ]


async def get_metric_timeseries(metric_key: str, start: date, end: date) -> List[MetricPoint]:
    """The single source of truth every consumer (dashboard, alerts, reports) calls."""
    if metric_key == DAILY_SIGNUPS:
        return await _signups_series(start, end)
    if metric_key == DAY1_RETENTION:
        return await _retention_series(start, end, within_days=1)
    if metric_key == DAY7_RETENTION:
        return await _retention_series(start, end, within_days=7)
    if metric_key == CHURN_RATE:
        return await _churn_series(start, end)
    if metric_key == REVENUE:
        return _revenue_series(start, end)
    raise ValueError(f"Unknown metric_key: {metric_key}")


async def get_current_value(metric_key: str) -> float:
    """Today's (UTC) value — used by the anomaly monitor's live comparison."""
    today = datetime.now(timezone.utc).date()
    series = await get_metric_timeseries(metric_key, today, today)
    return series[-1]["value"] if series else 0.0


def is_metric_available(metric_key: str) -> bool:
    return metric_key != REVENUE


async def get_dashboard_snapshot(metric_keys: List[str], start: date, end: date) -> Dict[str, List[MetricPoint]]:
    """Batch fetch for the interactive dashboard / report renderer — same calls
    get_metric_timeseries makes one at a time, just parallel-friendly grouping."""
    snapshot: Dict[str, List[MetricPoint]] = {}
    for key in metric_keys:
        try:
            snapshot[key] = await get_metric_timeseries(key, start, end)
        except Exception as exc:
            logger.warning(f"platform_metrics_service: {key} series failed: {exc}")
            snapshot[key] = []
    return snapshot


# ── HTTP handler — the interactive Platform Analytics Dashboard endpoint,
# and the deep-link target every anomaly alert points at (GAP-03 acceptance
# criterion: alerts always link to a filtered view of THIS data, never a
# generic homepage) ──────────────────────────────────────────────────────
async def admin_get_snapshot(metrics: str, date_from: Optional[str] = None, date_to: Optional[str] = None, _admin_id: str = Depends(require_admin)):
    requested = [m.strip() for m in metrics.split(",") if m.strip()]
    invalid = [m for m in requested if m not in METRIC_KEYS]
    if invalid:
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=400, content={"error": f"Unknown metric(s): {invalid}"})

    today = datetime.now(timezone.utc).date()
    end = date.fromisoformat(date_to) if date_to else today
    start = date.fromisoformat(date_from) if date_from else end - timedelta(days=13)

    snapshot = await get_dashboard_snapshot(requested, start, end)
    return {
        "metrics": {
            key: {"label": METRIC_LABELS.get(key, key), "available": is_metric_available(key), "points": points}
            for key, points in snapshot.items()
        },
        "date_from": start.isoformat(),
        "date_to": end.isoformat(),
    }
