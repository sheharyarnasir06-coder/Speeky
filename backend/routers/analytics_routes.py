from fastapi import APIRouter

from services.analytics_service import (
    export_feature_usage,
    export_funnel,
    export_retention_by_feature,
    get_feature_usage,
    get_funnel,
    get_overview,
    get_retention_by_feature,
    get_revenue,
)

router = APIRouter()

# PAD-US-10
router.add_api_route("/overview", get_overview, methods=["GET"])
# PAD-US-12
router.add_api_route("/funnel", get_funnel, methods=["GET"])
router.add_api_route("/funnel/export", export_funnel, methods=["GET"])
# PAD-US-13
router.add_api_route("/feature-usage", get_feature_usage, methods=["GET"])
router.add_api_route("/feature-usage/export", export_feature_usage, methods=["GET"])
# PAD-US-14
router.add_api_route("/retention-by-feature", get_retention_by_feature, methods=["GET"])
router.add_api_route("/retention-by-feature/export", export_retention_by_feature, methods=["GET"])
# PAD-US-11 — Super Admin only, mock (see analytics_service docstring)
router.add_api_route("/revenue", get_revenue, methods=["GET"])
