from fastapi import APIRouter

from services.pronunciation_coach_service import (
    check_resumable_session,
    end_session,
    get_session,
    get_word_pronunciation_audio,
    interrupt_session,
    resume_session,
    retry_word,
    start_session,
    submit_attempt,
    voice_socket_preview,
)

router = APIRouter()

# Pronunciation Coach (GAP-03/04/05) + Retry Loop (US-071) + Session Interruption
# Recovery (GAP-09) — one continuous session.
router.add_api_route("/start", start_session, methods=["POST"], status_code=201)
router.add_api_route("/resume", check_resumable_session, methods=["GET"])
router.add_api_route("/{session_id}/attempt", submit_attempt, methods=["POST"])
router.add_api_websocket_route("/{session_id}/attempt-preview-ws", voice_socket_preview)
router.add_api_route("/{session_id}/retry", retry_word, methods=["POST"])
router.add_api_route("/{session_id}/interrupt", interrupt_session, methods=["POST"])
router.add_api_route("/{session_id}/resume", resume_session, methods=["POST"])
router.add_api_route("/{session_id}/end", end_session, methods=["POST"])
router.add_api_route("/{session_id}", get_session, methods=["GET"])

# "Hear correct pronunciation" playback (PRN-US-10 / PRN-US-11) — standalone, no
# session state needed, so it slots in alongside the session-based routes above.
router.add_api_route("/words/{word}/audio", get_word_pronunciation_audio, methods=["GET"])
