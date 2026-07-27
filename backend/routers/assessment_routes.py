from fastapi import APIRouter

from services.assessment_service import (
    get_assessment_status,
    get_progress_comparison,
    get_results_summary,
    get_voice_token,
    start_assessment,
    submit_response,
)
from services.gating_service import (
    attempt_skip_assessment,
    confirm_skip_assessment,
    get_user_feature_summary,
)
from services.reassessment_service import (
    dismiss_prompt,
    get_re_assessment_summary,
    start_re_assessment,
)

router = APIRouter()

# Initial Communication Assessment + Results Summary 
router.add_api_route("/start", start_assessment, methods=["POST"])
router.add_api_route("/{assessment_id}/respond", submit_response, methods=["POST"])
router.add_api_route("/{assessment_id}/voice-token", get_voice_token, methods=["POST"])
router.add_api_route("/{assessment_id}/status", get_assessment_status, methods=["GET"])
router.add_api_route("/{assessment_id}/summary", get_results_summary, methods=["GET"])
router.add_api_route("/progress", get_progress_comparison, methods=["GET"])

# Feature-Access Gating
router.add_api_route("/access", get_user_feature_summary, methods=["GET"])
router.add_api_route("/skip", attempt_skip_assessment, methods=["POST"])
router.add_api_route("/skip/confirm", confirm_skip_assessment, methods=["POST"])

# Periodic Re-Assessment
router.add_api_route("/reassessment/eligibility", get_re_assessment_summary, methods=["GET"])
router.add_api_route("/reassessment/start", start_re_assessment, methods=["POST"])
router.add_api_route("/reassessment/dismiss", dismiss_prompt, methods=["POST"])
