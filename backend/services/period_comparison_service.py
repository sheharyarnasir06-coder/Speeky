"""
Period-over-Period Comparative Analysis (GAP-06 / US-204).

Reads from the SAME shared pipeline GAP-03/04 and the dashboard already use
(services/platform_metrics_service.py) — never a second/duplicated data path.
Everything metric-specific (WoW/MoM/YoY range math, delta %, availability,
divide-by-zero handling) is the pure logic in lib/period_comparison_math.py;
this module is just the DB-touching glue around it.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

from fastapi import Depends
from fastapi.responses import JSONResponse

from lib import kv_store, period_comparison_math as pcm
from lib.prisma_client import db
from middlewares.auth_middleware import require_admin
from schemas.period_comparison_schemas import (
    AvailableBasesResponse,
    ComparisonResponse,
    IncidentCreateRequest,
    IncidentListResponse,
    IncidentSchema,
)
from services import platform_metrics_service as pms

logger = logging.getLogger(__name__)

INCIDENTS_NS = "platform_incidents"

# Percent-shaped metrics are averaged over a period; count-shaped metrics are
# summed. active_users sums daily distinct-active counts (a returning user is
# counted once per day they're active, not once per period) — a reasonable
# activity-volume approximation for a trend indicator, not a true period-wide
# distinct-user count (that needs a different, heavier query shape).
_AVERAGED_METRICS = frozenset({pms.DAY1_RETENTION, pms.DAY7_RETENTION, pms.CHURN_RATE})


def _aggregate(points: List[dict], metric_key: str) -> float:
    values = [p["value"] for p in points]
    if not values:
        return 0.0
    if metric_key in _AVERAGED_METRICS:
        return round(sum(values) / len(values), 2)
    return round(sum(values), 2)


async def _platform_launch_date():
    earliest = await db.user.find_first(order={"createdAt": "asc"})
    return earliest.createdAt.date() if earliest else datetime.now(timezone.utc).date()


async def list_incidents() -> List[Dict]:
    return await kv_store.store.list_values(INCIDENTS_NS)


async def add_incident(label: str, start_at: str, end_at: str) -> Dict:
    incident_id = f"incident_{uuid.uuid4().hex[:12]}"
    data = {"id": incident_id, "label": label, "start_at": start_at, "end_at": end_at}
    await kv_store.store.create(INCIDENTS_NS, incident_id, data)
    return data


async def _outage_note_for_window(window_start, window_end) -> Optional[str]:
    incidents = await list_incidents()
    for incident in incidents:
        i_start = datetime.fromisoformat(incident["start_at"]).date()
        i_end = datetime.fromisoformat(incident["end_at"]).date()
        if pcm.outage_overlaps_window(i_start, i_end, window_start, window_end):
            return f"Baseline period includes a known data-collection gap: {incident['label']} ({incident['start_at']} to {incident['end_at']})."
    return None


async def get_comparison(metric_key: str, basis: str, reference_date=None) -> ComparisonResponse:
    reference_date = reference_date or datetime.now(timezone.utc).date()
    period = pcm.resolve_period_range(basis, reference_date)

    current_points = await pms.get_metric_timeseries(metric_key, period.current_start, period.current_end)
    prior_points = await pms.get_metric_timeseries(metric_key, period.prior_start, period.prior_end)

    current_value = _aggregate(current_points, metric_key)
    prior_value = _aggregate(prior_points, metric_key)
    delta = pcm.compute_delta(current_value, prior_value)

    outage_note = await _outage_note_for_window(period.prior_start, period.prior_end)

    return ComparisonResponse(
        metric_key=metric_key, metric_label=pms.METRIC_LABELS.get(metric_key, metric_key), basis=basis,
        current_start=period.current_start.isoformat(), current_end=period.current_end.isoformat(),
        prior_start=period.prior_start.isoformat(), prior_end=period.prior_end.isoformat(),
        current_value=delta.current_value, prior_value=delta.prior_value, pct_change=delta.pct_change,
        direction=delta.direction, is_new=delta.is_new, day_count_mismatch=period.day_count_mismatch,
        outage_flagged=outage_note is not None, outage_note=outage_note,
    )


async def list_available_bases() -> AvailableBasesResponse:
    launch_date = await _platform_launch_date()
    now = datetime.now(timezone.utc).date()
    available = pcm.available_comparison_bases(launch_date, now)
    return AvailableBasesResponse(available=available, launch_date=launch_date.isoformat(), days_of_history=(now - launch_date).days)


# ── HTTP handlers ────────────────────────────────────────────────────────────
async def admin_get_comparison(metric: str, basis: str, _admin_id: str = Depends(require_admin)):
    if metric not in pms.METRIC_KEYS:
        return JSONResponse(status_code=400, content={"error": f"Unknown metric: {metric}"})
    if basis not in pcm.VALID_BASES:
        return JSONResponse(status_code=400, content={"error": f"basis must be one of {pcm.VALID_BASES}"})
    available = (await list_available_bases()).available
    if basis not in available:
        return JSONResponse(status_code=400, content={
            "error": "insufficient_history",
            "message": "Not enough historical data for this comparison basis yet.",
            "available": available,
        })
    return await get_comparison(metric, basis)


async def admin_list_available_bases(_admin_id: str = Depends(require_admin)):
    return await list_available_bases()


async def admin_list_incidents(_admin_id: str = Depends(require_admin)):
    rows = await list_incidents()
    return IncidentListResponse(incidents=[IncidentSchema(**r) for r in rows])


async def admin_add_incident(payload: IncidentCreateRequest, _admin_id: str = Depends(require_admin)):
    row = await add_incident(payload.label, payload.start_at, payload.end_at)
    return IncidentSchema(**row)
