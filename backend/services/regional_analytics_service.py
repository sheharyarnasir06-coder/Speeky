"""
Regional / Locale-Based Segmentation Analytics (GAP-05 / US-203).

Acceptance criterion: the dashboard reads ONLY precomputed rollups
(`RegionalRollup`), never re-aggregates raw session tables on request — all
the raw-SQL grouping happens once, in `recompute_rollups()`, run on a timer
by `lib/scheduler.py`. This mirrors `services/platform_metrics_service.py`'s
query style (raw SQL, date-bucketed, off the same completions CTE) but grouped
by `users.country` as well, which platform_metrics_service intentionally
doesn't do — keeping the two pipelines' queries separate avoids retrofitting
an awkward optional region filter onto five already-shipped, tested queries.

Revenue is double-mock here: PAD-US-11's platform revenue is already a mock
MRR series (no billing gateway connected — see analytics_service.py), and
there's no per-user revenue attribution to split by region either. Regional
revenue rollups distribute that mock total proportional to each region's
active-user share for the day, then run it through the real E-04 currency
normalization pipeline (lib/currency.py) — the normalization math is real,
the revenue figure it operates on is not, until a real billing pipeline with
per-user, per-currency transactions exists.
"""

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import Depends
from fastapi.responses import JSONResponse

from lib import regional_math
from lib.admin_constants import ACTION_VIEW_RESTRICTED, ANALYTICS_MODULE_REVENUE
from lib.currency import currency_for_country, normalize_to_base_currency
from lib.prisma_client import db
from middlewares.auth_middleware import require_admin
from schemas.regional_schemas import (
    RegionDrilldownResponse,
    RegionFeatureAdoptionRow,
    RegionalSegmentationResponse,
    RegionRollupSchema,
)
from services.audit_log_service import log_action
from services.platform_metrics_service import DAILY_SIGNUPS, DAY7_RETENTION, METRIC_LABELS, REVENUE

logger = logging.getLogger(__name__)

ROLLUP_LOOKBACK_DAYS = 30
MIN_REGION_SAMPLE_SIZE = 20
ROLLUP_METRICS = (DAILY_SIGNUPS, DAY7_RETENTION, REVENUE)

REGION_LABELS: Dict[str, str] = {
    regional_math.UNKNOWN_REGION: "Unknown Region",
    regional_math.OTHER_REGIONS: "Other Regions",
}

# Reused from analytics_service.py rather than duplicated — same table/label
# mapping the Feature Adoption tab already uses.
from services.analytics_service import CROSS_FILTER_FEATURES  # noqa: E402


def _region_label(code: str) -> str:
    return REGION_LABELS.get(code, code)


def _to_date(value) -> date:
    """Raw ::date-cast query results come back as datetime.datetime (midnight) —
    same behavior platform_metrics_service._day_str already works around.
    Normalizing to a plain date here matters because these values get used as
    dict keys and compared against `date` objects built elsewhere (e.g.
    `start + timedelta(...)`); a stray datetime-vs-date mismatch would compare
    unequal even at identical midnights and silently drop every match."""
    return value.date() if isinstance(value, datetime) else value


async def _resolve_ip_inferred_share(region_code: str, day: date) -> Optional[float]:
    """No IP-geolocation service is connected anywhere in this codebase — this
    is the injection point a real one would fill in (same pattern
    reconciliation_service.py uses for payment providers). Returning None
    means "no signal", which lib.regional_math.detect_spoofing_flag treats as
    "never flag" rather than fabricating a false positive."""
    return None


_SQL_SIGNUPS_BY_REGION = """
SELECT date_trunc('day', "createdAt")::date AS day, COALESCE("country", $3) AS region, COUNT(*)::int AS value
FROM users
WHERE "createdAt" >= $1::date AND "createdAt" < ($2::date + interval '1 day')
GROUP BY day, region
ORDER BY day, region
"""

_SQL_RETENTION_BY_REGION = """
WITH cohort AS (
  SELECT id AS "userId", date_trunc('day', "createdAt") AS signup_day, COALESCE("country", $3) AS region
  FROM users
  WHERE "createdAt" >= $1::date AND "createdAt" < ($2::date + interval '1 day')
),
completions AS (
  SELECT "userId", "completedAt" FROM baseline_assessments WHERE "completedAt" IS NOT NULL
  UNION ALL
  SELECT "userId", "completedAt" FROM coaching_sessions WHERE "completedAt" IS NOT NULL
  UNION ALL
  SELECT "userId", "completedAt" FROM scenario_sessions WHERE "completedAt" IS NOT NULL
  UNION ALL
  SELECT "userId", "completedAt" FROM public_speaking_sessions WHERE "completedAt" IS NOT NULL
)
SELECT cohort.signup_day::date AS day, cohort.region AS region,
       COUNT(DISTINCT cohort."userId")::int AS cohort_size,
       COUNT(DISTINCT CASE WHEN completions."completedAt" IS NOT NULL
             AND completions."completedAt" < cohort.signup_day + interval '7 days'
             THEN cohort."userId" END)::int AS retained
FROM cohort
LEFT JOIN completions ON completions."userId" = cohort."userId"
GROUP BY day, region
ORDER BY day, region
"""

_SQL_ACTIVE_USERS_BY_REGION = """
WITH completions AS (
  SELECT "userId", "completedAt" FROM baseline_assessments WHERE "completedAt" IS NOT NULL
  UNION ALL
  SELECT "userId", "completedAt" FROM coaching_sessions WHERE "completedAt" IS NOT NULL
  UNION ALL
  SELECT "userId", "completedAt" FROM scenario_sessions WHERE "completedAt" IS NOT NULL
  UNION ALL
  SELECT "userId", "completedAt" FROM public_speaking_sessions WHERE "completedAt" IS NOT NULL
)
SELECT date_trunc('day', completions."completedAt")::date AS day, COALESCE(u."country", $3) AS region,
       COUNT(DISTINCT completions."userId")::int AS value
FROM completions
JOIN users u ON u.id = completions."userId"
WHERE completions."completedAt" >= $1::date AND completions."completedAt" < ($2::date + interval '1 day')
GROUP BY day, region
ORDER BY day, region
"""


async def _signups_by_region(start: date, end: date) -> List[Dict[str, Any]]:
    rows = await db.query_raw(_SQL_SIGNUPS_BY_REGION, start.isoformat(), end.isoformat(), regional_math.UNKNOWN_REGION)
    return [{"day": r["day"], "region": r["region"], "value": float(r["value"]), "sample_size": int(r["value"])} for r in rows]


async def _retention_by_region(start: date, end: date) -> List[Dict[str, Any]]:
    rows = await db.query_raw(_SQL_RETENTION_BY_REGION, start.isoformat(), end.isoformat(), regional_math.UNKNOWN_REGION)
    out = []
    for r in rows:
        cohort_size = r["cohort_size"] or 0
        pct = round((r["retained"] / cohort_size) * 100.0, 2) if cohort_size else 0.0
        out.append({"day": r["day"], "region": r["region"], "value": pct, "sample_size": cohort_size})
    return out


async def _active_users_by_region(start: date, end: date) -> Dict[Any, Dict[str, int]]:
    """Used only as the distribution weight for mock regional revenue below —
    not stored as its own rollup metric (ACTIVE_USERS rollups aren't part of
    this story's scope)."""
    rows = await db.query_raw(_SQL_ACTIVE_USERS_BY_REGION, start.isoformat(), end.isoformat(), regional_math.UNKNOWN_REGION)
    by_day: Dict[Any, Dict[str, int]] = {}
    for r in rows:
        by_day.setdefault(_to_date(r["day"]), {})[r["region"]] = int(r["value"])
    return by_day


async def _revenue_by_region(start: date, end: date) -> List[Dict[str, Any]]:
    """Distributes the same mock global MRR total analytics_service.get_revenue
    uses, proportional to each region's active-user share that day, then runs
    the result through the real currency-normalization pipeline (E-04) —
    demonstrating that pipeline end-to-end even though the revenue figure
    itself is a placeholder (see module docstring)."""
    active_by_day = await _active_users_by_region(start, end)
    out = []
    days = (end - start).days
    for i in range(days + 1):
        day = start + timedelta(days=i)
        global_mock_mrr = round(1200 + i * 14.5 + (i % 7) * 30, 2)
        regions = active_by_day.get(day, {})
        total_active = sum(regions.values())
        if total_active == 0:
            continue
        for region, active_count in regions.items():
            share = active_count / total_active
            local_amount = round(global_mock_mrr * share, 2)
            currency = currency_for_country(None if region == regional_math.UNKNOWN_REGION else region)
            normalized = normalize_to_base_currency(local_amount, currency)
            out.append({"day": day, "region": region, "value": normalized, "sample_size": active_count})
    return out


_ROLLUP_FETCHERS = {
    DAILY_SIGNUPS: _signups_by_region,
    DAY7_RETENTION: _retention_by_region,
    REVENUE: _revenue_by_region,
}


async def recompute_rollups(now: Optional[datetime] = None) -> Dict[str, int]:
    """Scheduler entry point (lib/scheduler.py) — the ONLY place regional
    rollups are written. Upserts one row per (metric, region, day)."""
    now = now or datetime.now(timezone.utc)
    end = now.date()
    start = end - timedelta(days=ROLLUP_LOOKBACK_DAYS - 1)
    written = 0

    for metric_key in ROLLUP_METRICS:
        fetcher = _ROLLUP_FETCHERS[metric_key]
        try:
            rows = await fetcher(start, end)
        except Exception as exc:
            logger.error(f"Regional rollup fetch failed for {metric_key}: {exc}")
            continue

        # Declared-locale share per region for this metric's window — the
        # signal detect_spoofing_flag compares against an (absent) IP signal.
        total_sample = sum(r["sample_size"] for r in rows) or 1

        for row in rows:
            region = row["region"]
            sample_size = row["sample_size"]
            is_low_volume = region != regional_math.UNKNOWN_REGION and sample_size < MIN_REGION_SAMPLE_SIZE
            declared_share = sample_size / total_sample
            ip_share = await _resolve_ip_inferred_share(region, row["day"])
            spoofing_note = regional_math.detect_spoofing_flag(declared_share, ip_share)

            day_dt = row["day"] if isinstance(row["day"], datetime) else datetime.combine(row["day"], datetime.min.time())
            day_dt = day_dt.replace(tzinfo=timezone.utc)

            existing = await db.regionalrollup.find_unique(
                where={"metricKey_regionCode_date": {"metricKey": metric_key, "regionCode": region, "date": day_dt}}
            )
            data = {
                "value": row["value"],
                "sampleSize": sample_size,
                "isLowVolume": is_low_volume,
                "isSpoofingFlagged": spoofing_note is not None,
                "spoofingNote": spoofing_note,
                "computedAt": now,
            }
            if existing:
                await db.regionalrollup.update(where={"id": existing.id}, data=data)
            else:
                await db.regionalrollup.create(data={"metricKey": metric_key, "regionCode": region, "date": day_dt, **data})
            written += 1

    return {"rows_written": written}


def _row_to_schema(row) -> RegionRollupSchema:
    return RegionRollupSchema(
        region_code=row.regionCode,
        region_label=_region_label(row.regionCode),
        value=row.value,
        sample_size=row.sampleSize,
        is_low_volume=row.isLowVolume,
        is_unknown=row.regionCode == regional_math.UNKNOWN_REGION,
        is_other_bucket=False,
        is_spoofing_flagged=row.isSpoofingFlagged,
        spoofing_note=row.spoofingNote,
    )


async def get_regional_segmentation(metric_key: str, days: int) -> RegionalSegmentationResponse:
    """Acceptance criterion: reads ONLY the precomputed RegionalRollup table."""
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=days - 1)
    start_dt = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
    end_dt = datetime.combine(end, datetime.min.time(), tzinfo=timezone.utc)

    rows = await db.regionalrollup.find_many(
        where={"metricKey": metric_key, "date": {"gte": start_dt, "lte": end_dt}},
        order={"date": "desc"},
    )
    if not rows:
        return RegionalSegmentationResponse(
            metric_key=metric_key, metric_label=METRIC_LABELS.get(metric_key, metric_key),
            date_from=start.isoformat(), date_to=end.isoformat(), min_sample_size=MIN_REGION_SAMPLE_SIZE,
            regions=[], stale=True,
        )

    # Latest day's rollup per region — the "compare regions right now" view.
    latest_date = rows[0].date
    latest_rows = [r for r in rows if r.date == latest_date]

    all_regions = [
        regional_math.RegionRow(region_code=r.regionCode, value=r.value, sample_size=r.sampleSize)
        for r in latest_rows
    ]
    folded = regional_math.fold_low_volume_regions(all_regions, MIN_REGION_SAMPLE_SIZE)

    by_region = {r.regionCode: r for r in latest_rows}
    schemas: List[RegionRollupSchema] = []
    for f in folded:
        if f.is_bucket:
            schemas.append(RegionRollupSchema(
                region_code=f.region_code, region_label=_region_label(f.region_code), value=f.value,
                sample_size=f.sample_size, is_low_volume=False, is_unknown=False, is_other_bucket=True,
                is_spoofing_flagged=False, spoofing_note=None,
            ))
        else:
            schemas.append(_row_to_schema(by_region[f.region_code]))

    return RegionalSegmentationResponse(
        metric_key=metric_key, metric_label=METRIC_LABELS.get(metric_key, metric_key),
        date_from=start.isoformat(), date_to=end.isoformat(), min_sample_size=MIN_REGION_SAMPLE_SIZE,
        regions=schemas, computed_at=rows[0].computedAt.isoformat(), stale=False,
    )


async def get_region_drilldown(region_code: str, days: int) -> RegionDrilldownResponse:
    """E-01 applies here too: drilling into a below-threshold region still
    returns "insufficient data" rather than individually-identifying figures
    for a handful of users."""
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=days - 1)
    start_dt = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
    end_dt = datetime.combine(end, datetime.min.time(), tzinfo=timezone.utc)

    latest = await db.regionalrollup.find_first(
        where={"regionCode": region_code, "metricKey": DAILY_SIGNUPS, "date": {"gte": start_dt, "lte": end_dt}},
        order={"date": "desc"},
    )
    sample_size = latest.sampleSize if latest else 0
    is_low_volume = region_code != regional_math.UNKNOWN_REGION and sample_size < MIN_REGION_SAMPLE_SIZE

    if is_low_volume:
        return RegionDrilldownResponse(
            region_code=region_code, region_label=_region_label(region_code), is_low_volume=True,
            sample_size=sample_size, features=[], insufficient_data=True,
        )

    where_country = {"country": None} if region_code == regional_math.UNKNOWN_REGION else {"country": region_code}
    region_users = await db.user.find_many(where=where_country)
    user_ids = [u.id for u in region_users]

    features: List[RegionFeatureAdoptionRow] = []
    if user_ids:
        for _key, (table, label) in CROSS_FILTER_FEATURES.items():
            rows = await getattr(db, table).find_many(where={"userId": {"in": user_ids}, "createdAt": {"gte": start_dt}})
            started = len(rows)
            completed = sum(1 for r in rows if getattr(r, "status", None) == "completed" or getattr(r, "completedAt", None) is not None)
            features.append(RegionFeatureAdoptionRow(
                feature_label=label, started=started, completed=completed,
                completion_rate=round(100 * completed / started, 1) if started else 0.0,
            ))

    return RegionDrilldownResponse(
        region_code=region_code, region_label=_region_label(region_code), is_low_volume=False,
        sample_size=sample_size, features=features, insufficient_data=False,
    )


# ── HTTP handlers ────────────────────────────────────────────────────────────
async def admin_get_regional_segmentation(metric: str, days: int = ROLLUP_LOOKBACK_DAYS, admin_id: str = Depends(require_admin)):
    if metric not in ROLLUP_METRICS:
        return JSONResponse(status_code=400, content={"error": f"metric must be one of {ROLLUP_METRICS}"})
    if metric == REVENUE:
        await _log_revenue_view(admin_id, {"days": days, "view": "regional_segmentation"})
    return await get_regional_segmentation(metric, min(days, ROLLUP_LOOKBACK_DAYS))


async def admin_get_region_drilldown(region_code: str, days: int = ROLLUP_LOOKBACK_DAYS, admin_id: str = Depends(require_admin)):
    return await get_region_drilldown(region_code, min(days, ROLLUP_LOOKBACK_DAYS))


async def _log_revenue_view(admin_id: str, scope: Dict[str, Any]) -> None:
    """Reuses the established US-205 audit pattern for Revenue-segment views
    (analytics_service.py's `_log_view` does the same for the global Revenue
    tab) — not a parallel logging system."""
    try:
        user = await db.user.find_unique(where={"id": admin_id})
        actor_role = getattr(user, "role", "ADMIN")
        if hasattr(actor_role, "value"):
            actor_role = actor_role.value
        await log_action(actor_id=admin_id, actor_role=actor_role, action_type=ACTION_VIEW_RESTRICTED, module=ANALYTICS_MODULE_REVENUE, scope=scope)
    except Exception as exc:
        logger.warning(f"Revenue-segment audit log failed: {exc}")
