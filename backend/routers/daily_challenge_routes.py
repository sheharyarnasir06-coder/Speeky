from fastapi import APIRouter

from services.daily_challenge_service import (
    add_turn,
    complete_challenge,
    dispute_session,
    get_challenge_status,
    get_notification,
    get_streak,
    review_session,
    start_challenge,
)

router = APIRouter()

router.add_api_route("/start", start_challenge, methods=["POST"], status_code=201)
router.add_api_route("/turn", add_turn, methods=["POST"])
router.add_api_route("/complete", complete_challenge, methods=["POST"])
router.add_api_route("/dispute", dispute_session, methods=["POST"])
router.add_api_route("/review", review_session, methods=["POST"])  # admin-only
router.add_api_route("/streak", get_streak, methods=["GET"])
# PDG-US-11 status + PDG-US-13 in-app reminder (read the same kv streak store)
router.add_api_route("/status", get_challenge_status, methods=["GET"])
router.add_api_route("/notification", get_notification, methods=["GET"])
