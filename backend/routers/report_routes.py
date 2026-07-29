"""GAP-04 (US-202): scheduled report templates, history, and manual send."""

from fastapi import APIRouter

from services.report_service import (
    admin_create_template,
    admin_delete_template,
    admin_list_history,
    admin_list_templates,
    admin_send_now,
    admin_update_template,
)

router = APIRouter()

router.add_api_route("/templates", admin_list_templates, methods=["GET"])
router.add_api_route("/templates", admin_create_template, methods=["POST"])
router.add_api_route("/templates/{template_id}", admin_update_template, methods=["PATCH"])
router.add_api_route("/templates/{template_id}", admin_delete_template, methods=["DELETE"])
router.add_api_route("/templates/{template_id}/send-now", admin_send_now, methods=["POST"])

router.add_api_route("/history", admin_list_history, methods=["GET"])
