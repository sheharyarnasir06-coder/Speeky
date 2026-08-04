"""Catalogue-wide content intelligence (US-193 Template Performance Dashboard,
US-196 Content Drift Detection).

Per-template endpoints live on the scenarios router alongside the rest of the
custom-scenario admin surface; this router owns only the cross-catalogue views,
which have no single scenario id to hang off.
"""

from fastapi import APIRouter

from services.content_intelligence_service import (
    admin_acknowledge_drift_alert,
    admin_drift_detail,
    admin_drift_overview,
    admin_performance_overview,
)

router = APIRouter()

# US-193
router.add_api_route("/performance", admin_performance_overview, methods=["GET"])

# US-196 — literal paths before the "/{scenario_id}" style route below.
router.add_api_route("/drift", admin_drift_overview, methods=["GET"])
router.add_api_route("/drift/alerts/{alert_id}/acknowledge", admin_acknowledge_drift_alert, methods=["POST"])
router.add_api_route("/drift/{scenario_id}", admin_drift_detail, methods=["GET"])
