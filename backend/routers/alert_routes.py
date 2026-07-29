"""GAP-03 (US-201): anomaly threshold config + Alert Center endpoints."""

from fastapi import APIRouter

from services.anomaly_detection_service import (
    admin_acknowledge_alert,
    admin_deactivate_threshold,
    admin_list_alerts,
    admin_list_thresholds,
    admin_mark_false_positive,
    admin_trigger_detection_now,
    admin_upsert_threshold,
    super_admin_assign_unassigned,
    super_admin_list_unassigned,
)

router = APIRouter()

router.add_api_route("/thresholds", admin_list_thresholds, methods=["GET"])
router.add_api_route("/thresholds", admin_upsert_threshold, methods=["POST"])
router.add_api_route("/thresholds/{threshold_id}", admin_deactivate_threshold, methods=["DELETE"])

router.add_api_route("/", admin_list_alerts, methods=["GET"])
router.add_api_route("/{alert_id}/acknowledge", admin_acknowledge_alert, methods=["POST"])
router.add_api_route("/{alert_id}/false-positive", admin_mark_false_positive, methods=["POST"])

# Super Admin only — E-04 Unassigned Alerts queue.
router.add_api_route("/unassigned", super_admin_list_unassigned, methods=["GET"])
router.add_api_route("/{alert_id}/assign-owner", super_admin_assign_unassigned, methods=["POST"])

# Dev-only manual trigger (disabled in production, see the handler).
router.add_api_route("/dev-trigger", admin_trigger_detection_now, methods=["POST"])
