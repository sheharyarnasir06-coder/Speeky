from fastapi import APIRouter

from services.daily_challenge_service import (
    get_challenge_status,
    get_conversation_challenge_status,
    get_notification,
    get_streak,
    start_challenge,
)

router = APIRouter()

router.add_api_route("/start", start_challenge, methods=["POST"], status_code=201)
router.add_api_route("/conversation-status", get_conversation_challenge_status, methods=["GET"])
router.add_api_route("/streak", get_streak, methods=["GET"])
# PDG-US-11 status + PDG-US-13 in-app reminder (read the same kv streak store)
router.add_api_route("/status", get_challenge_status, methods=["GET"])
router.add_api_route("/notification", get_notification, methods=["GET"])
