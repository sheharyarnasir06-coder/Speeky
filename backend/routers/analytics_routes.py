"""Platform Analytics Dashboard endpoints.

Two complementary surfaces share this router/prefix:
  - PAD-US-10..14 (services/analytics_service.py): the live admin dashboard —
    overview, onboarding funnel, feature adoption, retention cross-filter,
    and a mock revenue view.
  - GAP-03/GAP-04 (services/platform_metrics_service.py): the shared
    signup/retention/churn/revenue time-series pipeline the anomaly monitor
    and scheduled reports both read from — exposed here as /snapshot, the
    deep-link target every anomaly alert points at.
"""

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
from services.audit_log_service import (
    http_export_data,
    http_list_audit_logs,
    http_verify_audit_log,
)
from services.dashboard_view_service import (
    http_create_view,
    http_delete_view,
    http_get_view,
    http_list_views,
)
from services.platform_metrics_service import admin_get_snapshot
from services.reconciliation_service import (
    http_get_reconciliation_status,
    http_resync_user,
    http_run_reconciliation,
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

# GAP-03/GAP-04 — the anomaly-alert/report data pipeline, and the deep-link target.
router.add_api_route("/snapshot", admin_get_snapshot, methods=["GET"])

# US-205 Audit Trail & Fail-Closed Data Export
router.add_api_route("/audit-logs", http_list_audit_logs, methods=["GET"])
router.add_api_route("/audit-logs/verify", http_verify_audit_log, methods=["GET"])
router.add_api_route("/export", http_export_data, methods=["POST"])

# US-206 Custom Dashboard Layout & Saved Views
router.add_api_route("/views", http_list_views, methods=["GET"])
router.add_api_route("/views", http_create_view, methods=["POST"])
router.add_api_route("/views/{view_id}", http_get_view, methods=["GET"])
router.add_api_route("/views/{view_id}", http_delete_view, methods=["DELETE"])

# US-207 Cross-Source Data Reconciliation
router.add_api_route("/reconciliation/status", http_get_reconciliation_status, methods=["GET"])
router.add_api_route("/reconciliation/run", http_run_reconciliation, methods=["POST"])
router.add_api_route("/reconciliation/resync", http_resync_user, methods=["POST"])
