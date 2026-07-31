from fastapi import APIRouter

from services.interview_coach_service import (
    add_peer_comment,
    end_session,
    get_session_state,
    list_peer_comments,
    pause_session,
    report_comment,
    resume_session,
    revoke_share,
    share_review,
    start_session,
    submit_answer,
    take_break,
    voice_socket,
)
from services.filler_word_service import get_filler_words_for_interview_session

router = APIRouter()

# Interview Coach (Ubase, panel, multi-round)
router.add_api_route("/sessions", start_session, methods=["POST"], status_code=201)
router.add_api_route("/sessions/{session_id}", get_session_state, methods=["GET"])
router.add_api_route("/sessions/{session_id}/answer", submit_answer, methods=["POST"])
router.add_api_websocket_route("/sessions/{session_id}/voice-ws", voice_socket)
router.add_api_route("/sessions/{session_id}/pause", pause_session, methods=["POST"])
router.add_api_route("/sessions/{session_id}/resume", resume_session, methods=["POST"])
router.add_api_route("/sessions/{session_id}/break", take_break, methods=["POST"])
router.add_api_route("/sessions/{session_id}/end", end_session, methods=["POST"])
router.add_api_route("/sessions/{session_id}/filler-words", get_filler_words_for_interview_session, methods=["GET"])

# mentor/peer review sharing
router.add_api_route("/reviews", share_review, methods=["POST"], status_code=201)
router.add_api_route("/reviews/{share_id}/comments", add_peer_comment, methods=["POST"], status_code=201)
router.add_api_route("/reviews/{share_id}/comments", list_peer_comments, methods=["GET"])
router.add_api_route("/reviews/{share_id}/revoke", revoke_share, methods=["POST"])
router.add_api_route("/reviews/comments/{comment_id}/report", report_comment, methods=["POST"])
