from fastapi import APIRouter

from services.script_practice_service import (
    get_history,
    get_practice,
    start_practice,
    submit_after,
    submit_baseline,
)

router = APIRouter()

# Script Practice Confidence Score (US-157 / PSA-US-05)
router.add_api_route("/start", start_practice, methods=["POST"])
router.add_api_route("/history", get_history, methods=["GET"])
router.add_api_route("/{session_id}/baseline", submit_baseline, methods=["POST"])
router.add_api_route("/{session_id}/after", submit_after, methods=["POST"])
router.add_api_route("/{session_id}", get_practice, methods=["GET"])
