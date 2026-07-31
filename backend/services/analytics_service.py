"""
Analytics Dashboard (PAD-US-10 .. PAD-US-14).

Every real-data endpoint below computes live from the ORM, no cache layer, no
scheduled job, no raw SQL. This repo has zero cron/scheduler/job-queue infra
anywhere (confirmed while building the content-management admin work) — building
one just for a "nightly refresh" (PAD-US-10 E-03) isn't worth it while the whole
dashboard computes fast enough on demand at this app's current data scale.
`computed_at` is always "now" as a result — there's no such thing as a stale
response here, which is the honest simpler alternative to faking a cache.

ponytail: table sweeps use `getattr(db, table)` + Python-side grouping instead of
a raw UNION/DATE_TRUNC query. Fine at current row counts; if this ever gets slow,
the fix is one raw SQL aggregate query, not a rewrite.

PAD-US-11 (Platform Revenue) is explicitly mock, per instruction — no payment
gateway (Stripe/Apple/Google) is integrated anywhere in this app, so there is
nothing real to report. Every field in that response is flagged `mock: True`.
"""

import asyncio
import csv
import io
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set

from fastapi import Depends
from fastapi.responses import JSONResponse, Response

from lib import prompts
from lib.admin_constants import (
    ACTION_VIEW_RESTRICTED,
    ANALYTICS_MODULE_FEATURE_USAGE,
    ANALYTICS_MODULE_FUNNEL,
    ANALYTICS_MODULE_OVERVIEW,
    ANALYTICS_MODULE_RETENTION,
    ANALYTICS_MODULE_REVENUE,
)
from lib.prisma_client import db
from middlewares.auth_middleware import require_admin, require_super_admin
from services.audit_log_service import log_action

MAX_DAYS = 365  # PAD-US-10 E-01 / TC-05
DEFAULT_DAYS = 30
RETENTION_WINDOW_DAYS = 7
CROSS_FILTER_TIMEOUT_SECONDS = 8  # PAD-US-14 E-01

# Every practice surface with a userId + createdAt column — the shared definition
# of "active" across this whole module. Interview Coach is deliberately excluded:
# it's ported on the generic KvEntry blob store (no typed userId/createdAt query
# shape shared with the others), not a scope cut, just not wired into this sweep yet.
ACTIVITY_TABLES = (
    "scenariosession", "coachingsession", "publicspeakingsession",
    "pronunciationattempt", "accentassessment",
)

CROSS_FILTER_FEATURES: Dict[str, tuple] = {
    "scenario_based_learning": ("scenariosession", "Scenario-Based Learning"),
    "workplace_coaching": ("coachingsession", "Workplace English Coach"),
    "public_speaking": ("publicspeakingsession", "Public Speaking Coach"),
    "pronunciation_coach": ("pronunciationattempt", "Pronunciation Coach"),
    "accent_assessment": ("accentassessment", "Accent Assessment"),
}


def _bad_days(days: int) -> Optional[JSONResponse]:
    if days < 1 or days > MAX_DAYS:
        return JSONResponse(status_code=400, content={"error": f"days must be between 1 and {MAX_DAYS}."})
    return None


def _period_start(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


async def _log_view(actor_id: str, module: str, scope: Dict[str, Any]) -> None:
    """
    US-205: Fire-and-forget VIEW_RESTRICTED audit entry.
    Does NOT block the analytics response if the KV write fails — unlike exports,
    views are logged best-effort. (E-01 fail-closed applies only to data exports.)
    """
    try:
        user = await db.user.find_unique(where={"id": actor_id})
        actor_role = getattr(user, "role", "ADMIN")
        if hasattr(actor_role, "value"):
            actor_role = actor_role.value
        await log_action(
            actor_id=actor_id,
            actor_role=actor_role,
            action_type=ACTION_VIEW_RESTRICTED,
            module=module,
            scope=scope,
        )
    except Exception:
        pass  # Best-effort: never surface audit write errors to the admin dashboard


async def _activity_rows(since: Optional[datetime] = None, user_ids: Optional[Set[str]] = None) -> List[Dict]:
    where: Dict = {}
    if since is not None:
        where["createdAt"] = {"gte": since}
    if user_ids is not None:
        where["userId"] = {"in": list(user_ids)}
    rows: List[Dict] = []
    for table in ACTIVITY_TABLES:
        found = await getattr(db, table).find_many(where=where)
        rows.extend({"userId": r.userId, "createdAt": r.createdAt} for r in found)
    return rows


def _daily_series(days: int, timestamps: List[datetime]) -> List[Dict]:
    buckets: Dict[str, int] = defaultdict(int)
    for ts in timestamps:
        buckets[ts.date().isoformat()] += 1
    today = datetime.now(timezone.utc).date()
    return [
        {"date": (today - timedelta(days=offset)).isoformat(),
         "count": buckets.get((today - timedelta(days=offset)).isoformat(), 0)}
        for offset in range(days - 1, -1, -1)
    ]


async def _retention_rate() -> Optional[float]:
    """% of users who signed up more than RETENTION_WINDOW_DAYS ago and have at
    least one activity row in the trailing RETENTION_WINDOW_DAYS. None (not 0) when
    there's no eligible cohort yet — an early-stage product with no week-old users
    isn't "0% retention", it's "not enough data" (PAD-US-10 E-02 spirit)."""
    window_start = datetime.now(timezone.utc) - timedelta(days=RETENTION_WINDOW_DAYS)
    eligible = await db.user.find_many(where={"createdAt": {"lt": window_start}})
    eligible_ids = {u.id for u in eligible}
    if not eligible_ids:
        return None
    recent_rows = await _activity_rows(since=window_start, user_ids=eligible_ids)
    returned_ids = {r["userId"] for r in recent_rows}
    return round(100 * len(returned_ids) / len(eligible_ids), 1)


async def _scenario_label_map(include_archived: bool) -> Dict[str, Dict]:
    labels = {
        key: {"label": meta["label"], "category": meta["category"], "new": False, "archived": False}
        for key, meta in prompts.SBL_SCENARIOS.items()
    }
    where = {} if include_archived else {"status": "ACTIVE"}
    rows = await db.customscenario.find_many(where=where)
    now = datetime.now(timezone.utc)
    for row in rows:
        labels[f"custom:{row.id}"] = {
            "label": row.title, "category": row.category,
            "new": (now - row.createdAt) < timedelta(days=14),  # PAD-US-13 E-01
            "archived": row.status == "ARCHIVED",
        }
    return labels


async def _feature_usage_counts(since: datetime, include_archived: bool) -> List[Dict]:
    labels = await _scenario_label_map(include_archived)
    rows = await db.scenariosession.find_many(where={"createdAt": {"gte": since}})
    started: Dict[str, int] = defaultdict(int)
    completed: Dict[str, int] = defaultdict(int)
    for r in rows:
        started[r.scenarioKey] += 1
        if r.status == "completed":
            completed[r.scenarioKey] += 1

    result = []
    for key, count in started.items():
        meta = labels.get(key)
        if meta is None:
            continue  # archived custom scenario, show_archived=False — excluded (E-02 toggle)
        comp = completed.get(key, 0)
        result.append({
            "key": key, "label": meta["label"], "category": meta["category"],
            "started": count, "completed": comp,
            "completion_rate": round(100 * comp / count, 1) if count else 0.0,
            "new": meta["new"], "archived": meta["archived"],
        })
    result.sort(key=lambda x: x["started"], reverse=True)
    return result


async def _onboarding_funnel(since: datetime) -> List[Dict]:
    """Cohort funnel, not independent per-step totals: everyone who registered in
    the window is tracked through Assessment and First Practice specifically (so a
    step's % is genuinely "of the people who registered", matching PAD-US-12's
    "40% of users drop off during Initial Assessment" framing). The doc's funnel
    starts at "Web-App" (pre-registration visits) — this app has no page-view/
    anonymous-visitor tracking anywhere, so that step is omitted rather than faked;
    Registered is the first honestly-available step.
    """
    cohort = await db.user.find_many(where={"createdAt": {"gte": since}})
    cohort_ids = {u.id for u in cohort}
    total = len(cohort_ids)

    if total == 0:
        return [
            {"step": step, "count": 0, "pct_of_start": 0.0, "drop_off_pct": 0.0}
            for step in ("Registered", "Completed Assessment", "First Practice Session")
        ]

    assessed_rows = await db.baselineassessment.find_many(
        where={"userId": {"in": list(cohort_ids)}, "completedAt": {"not": None}}
    )
    assessed_ids = {r.userId for r in assessed_rows} & cohort_ids

    activity_rows = await _activity_rows(user_ids=cohort_ids)
    practiced_ids = {r["userId"] for r in activity_rows}

    steps = [("Registered", total), ("Completed Assessment", len(assessed_ids)), ("First Practice Session", len(practiced_ids))]
    out, prev = [], total
    for name, count in steps:
        drop_off = round(100 * (1 - count / prev), 1) if prev and name != "Registered" else 0.0
        out.append({
            "step": name, "count": count,
            "pct_of_start": round(100 * count / total, 1),
            "drop_off_pct": drop_off,
        })
        prev = count
    return out


def _csv_response(rows: List[Dict], fieldnames: List[str], filename: str) -> Response:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow({k: row.get(k, "") for k in fieldnames})
    return Response(
        content=buf.getvalue(), media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ═══════════════════════════════════════════════════════════════════════════════
# PAD-US-10: Analytics Dashboard Monitoring — Administrator (+ Super Admin)
# ═══════════════════════════════════════════════════════════════════════════════
async def get_overview(days: int = DEFAULT_DAYS, _admin_id: str = Depends(require_admin)):
    bad = _bad_days(days)
    if bad:
        return bad
    since = _period_start(days)

    # US-205: log restricted module view (fire-and-forget)
    asyncio.ensure_future(_log_view(_admin_id, ANALYTICS_MODULE_OVERVIEW, {"days": days}))

    rows = await _activity_rows(since=since)
    active_user_ids = {r["userId"] for r in rows}
    daily_sessions = _daily_series(days, [r["createdAt"] for r in rows])
    retention_rate = await _retention_rate()
    feature_usage = (await _feature_usage_counts(since, include_archived=False))[:5]
    funnel = await _onboarding_funnel(since)

    return {
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "period_days": days,
        "active_users": len(active_user_ids),
        "daily_sessions": daily_sessions,
        "retention_rate": retention_rate,
        "top_feature_usage": feature_usage,
        "onboarding_funnel": funnel,
        "zero_data": len(active_user_ids) == 0,  # PAD-US-10 E-02
    }


# ═══════════════════════════════════════════════════════════════════════════════
# PAD-US-12: Admin Drop-off Funnel Analysis — Administrator (+ Super Admin)
# ═══════════════════════════════════════════════════════════════════════════════
async def get_funnel(days: int = DEFAULT_DAYS, _admin_id: str = Depends(require_admin)):
    bad = _bad_days(days)
    if bad:
        return bad
    since = _period_start(days)

    # US-205: log restricted module view (fire-and-forget)
    asyncio.ensure_future(_log_view(_admin_id, ANALYTICS_MODULE_FUNNEL, {"days": days}))

    funnel = await _onboarding_funnel(since)
    return {
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "period_days": days,
        "funnel": funnel,
        "zero_data": funnel[0]["count"] == 0,  # PAD-US-12 E-02
    }


async def export_funnel(days: int = DEFAULT_DAYS, _admin_id: str = Depends(require_admin)):
    bad = _bad_days(days)
    if bad:
        return bad
    funnel = await _onboarding_funnel(_period_start(days))
    return _csv_response(funnel, ["step", "count", "pct_of_start", "drop_off_pct"], "funnel.csv")


# ═══════════════════════════════════════════════════════════════════════════════
# PAD-US-13: Admin Feature Adoption & Usage Analytics — Administrator (+ Super Admin)
# ═══════════════════════════════════════════════════════════════════════════════
async def get_feature_usage(
    days: int = DEFAULT_DAYS, show_archived: bool = False, _admin_id: str = Depends(require_admin)
):
    bad = _bad_days(days)
    if bad:
        return bad

    # US-205: log restricted module view (fire-and-forget)
    asyncio.ensure_future(_log_view(
        _admin_id, ANALYTICS_MODULE_FEATURE_USAGE, {"days": days, "show_archived": show_archived}
    ))

    usage = await _feature_usage_counts(_period_start(days), include_archived=show_archived)
    return {
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "period_days": days,
        "show_archived": show_archived,
        "features": usage,
        "zero_data": len(usage) == 0,
    }


async def export_feature_usage(
    days: int = DEFAULT_DAYS, show_archived: bool = False, _admin_id: str = Depends(require_admin)
):
    bad = _bad_days(days)
    if bad:
        return bad
    usage = await _feature_usage_counts(_period_start(days), include_archived=show_archived)
    return _csv_response(
        usage, ["label", "category", "started", "completed", "completion_rate", "new", "archived"],
        "feature_usage.csv",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# PAD-US-14: Retention vs. Feature Usage Cross-Filtering — Administrator (+ Super Admin)
# ═══════════════════════════════════════════════════════════════════════════════
async def _cross_filter(days: int, feature: str) -> Dict:
    table, label = CROSS_FILTER_FEATURES[feature]
    cohort = await db.user.find_many(where={"createdAt": {"gte": _period_start(days)}})
    cohort_ids = {u.id for u in cohort}
    if not cohort_ids:
        return {"feature": feature, "feature_label": label, "zero_data": True, "engaged": None, "general": None}

    signup_by_user = {u.id: u.createdAt for u in cohort}
    feature_rows = await getattr(db, table).find_many(where={"userId": {"in": list(cohort_ids)}})
    engaged_ids = {
        r.userId for r in feature_rows
        if r.userId in signup_by_user and (r.createdAt - signup_by_user[r.userId]) <= timedelta(days=RETENTION_WINDOW_DAYS)
    }
    general_ids = cohort_ids - engaged_ids

    recent_since = datetime.now(timezone.utc) - timedelta(days=RETENTION_WINDOW_DAYS)
    recent_rows = await _activity_rows(since=recent_since, user_ids=cohort_ids)
    recent_active_ids = {r["userId"] for r in recent_rows}

    def group(ids: Set[str]) -> Dict:
        return {
            "cohort_size": len(ids),
            "retention_rate": round(100 * len(ids & recent_active_ids) / len(ids), 1) if ids else None,
        }

    return {
        "feature": feature, "feature_label": label, "zero_data": False,
        "engaged": group(engaged_ids), "general": group(general_ids),
    }


async def get_retention_by_feature(
    days: int = DEFAULT_DAYS, feature: str = "scenario_based_learning", _admin_id: str = Depends(require_admin)
):
    bad = _bad_days(days)
    if bad:
        return bad
    if feature not in CROSS_FILTER_FEATURES:
        return JSONResponse(
            status_code=400,
            content={"error": f"Unknown feature. Choose one of: {', '.join(CROSS_FILTER_FEATURES)}"},
        )

    # US-205: log restricted module view (fire-and-forget)
    asyncio.ensure_future(_log_view(
        _admin_id, ANALYTICS_MODULE_RETENTION, {"days": days, "feature": feature}
    ))

    try:
        result = await asyncio.wait_for(_cross_filter(days, feature), timeout=CROSS_FILTER_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        return JSONResponse(
            status_code=202,
            content={"status": "processing", "message": "Compiling complex report. This will take a moment — try a narrower date range or check back shortly."},
        )
    result["computed_at"] = datetime.now(timezone.utc).isoformat()
    result["period_days"] = days
    return result


async def export_retention_by_feature(
    days: int = DEFAULT_DAYS, feature: str = "scenario_based_learning", _admin_id: str = Depends(require_admin)
):
    bad = _bad_days(days)
    if bad:
        return bad
    if feature not in CROSS_FILTER_FEATURES:
        return JSONResponse(status_code=400, content={"error": f"Unknown feature. Choose one of: {', '.join(CROSS_FILTER_FEATURES)}"})
    result = await _cross_filter(days, feature)
    rows = [
        {"group": "engaged", **(result["engaged"] or {"cohort_size": 0, "retention_rate": ""})},
        {"group": "general", **(result["general"] or {"cohort_size": 0, "retention_rate": ""})},
    ]
    return _csv_response(rows, ["group", "cohort_size", "retention_rate"], "retention_by_feature.csv")


# ═══════════════════════════════════════════════════════════════════════════════
# PAD-US-11: Platform Revenue & Retention Tracking — System (Super) Admin only, MOCK
# ═══════════════════════════════════════════════════════════════════════════════
async def get_revenue(days: int = DEFAULT_DAYS, _super_admin_id: str = Depends(require_super_admin)):
    bad = _bad_days(days)
    if bad:
        return bad

    # US-205: Revenue is in RESTRICTED_ANALYTICS_MODULES; log every view (fire-and-forget)
    asyncio.ensure_future(_log_view(_super_admin_id, ANALYTICS_MODULE_REVENUE, {"days": days}))
    today = datetime.now(timezone.utc).date()
    mrr_series = [
        {"date": (today - timedelta(days=i)).isoformat(), "mrr": round(1200 + (days - i) * 14.5 + (i % 7) * 30, 2)}
        for i in range(days - 1, -1, -1)
    ]
    return {
        "mock": True,
        "note": "Demo data — no payment gateway (Stripe/Apple/Google) is connected yet.",
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "period_days": days,
        "currency": "USD",
        "mrr_series": mrr_series,
        "current_mrr": mrr_series[-1]["mrr"],
        "churn_rate_pct": 4.2,
        # PAD-US-11 E-03: cohorts younger than the window show None ("TBD" in the UI),
        # never a misleading 0%.
        "cohort_retention": [
            {"cohort": "This week", "day1": 62.0, "day7": 38.0, "day30": None},
            {"cohort": "Last week", "day1": 58.0, "day7": 34.0, "day30": None},
            {"cohort": "4 weeks ago", "day1": 65.0, "day7": 40.0, "day30": 22.0},
        ],
    }
