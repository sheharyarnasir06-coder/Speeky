from fastapi import APIRouter

from services.coaching_service import (
    get_scenarios,
    get_session,
    roleplay_turn,
    start_session,
    submit_session,
    voice_token,
)
from services.code_switch_service import (
    delete_code_switch_word,
    list_code_switch_words,
)

from services.filler_word_service import get_filler_words_for_session

router = APIRouter()

# Workplace English Coaching
router.add_api_route("/scenarios", get_scenarios, methods=["GET"])
router.add_api_route("/start", start_session, methods=["POST"])
# CSC-US-01 practice tracker — registered BEFORE the /{session_id} param route so the
# literal path isn't swallowed as a session id.
router.add_api_route("/code-switch-words", list_code_switch_words, methods=["GET"])
router.add_api_route("/code-switch-words/{word_id}", delete_code_switch_word, methods=["DELETE"])
router.add_api_route("/{session_id}/turn", roleplay_turn, methods=["POST"])
router.add_api_route("/{session_id}/voice-token", voice_token, methods=["POST"])
router.add_api_route("/{session_id}/submit", submit_session, methods=["POST"])
router.add_api_route("/{session_id}/filler-words", get_filler_words_for_session, methods=["GET"])
router.add_api_route("/sessions/{session_id}/filler-words", get_filler_words_for_session, methods=["GET"])
router.add_api_route("/{session_id}", get_session, methods=["GET"])

