"""Platform Analytics Dashboard data endpoint — the shared pipeline GAP-03's
alerts and GAP-04's reports both read from too (services/platform_metrics_service.py)."""

from fastapi import APIRouter

from services.platform_metrics_service import admin_get_snapshot

router = APIRouter()

router.add_api_route("/snapshot", admin_get_snapshot, methods=["GET"])
