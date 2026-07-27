from fastapi import APIRouter

from services.pronunciation_coach_service import (
    dismiss_trouble_word_endpoint,
    get_accessibility_profile_endpoint,
    get_active_trouble_words_endpoint,
    get_next_review_word_endpoint,
    get_pending_outcomes_endpoint,
    get_trouble_words_archive_endpoint,
    get_turn_score_endpoint,
    score_turn_endpoint,
    update_accessibility_profile_endpoint,
)

router = APIRouter(tags=["pronunciation-coach"])

# US-74 (outage/timeout fallback) + US-79 (word-level highlighting) — one
# shared scoring call per conversation turn.
router.add_api_route(
    "/sessions/{session_id}/turns/{turn_index}/score", score_turn_endpoint, methods=["POST"],
)
router.add_api_route(
    "/sessions/{session_id}/turns/{turn_index}/score", get_turn_score_endpoint, methods=["GET"],
)
router.add_api_route("/pending-outcomes", get_pending_outcomes_endpoint, methods=["GET"])  # US-74 E-05

# US-76: accessibility safeguard
router.add_api_route("/accessibility-profile", get_accessibility_profile_endpoint, methods=["GET"])
router.add_api_route("/accessibility-profile", update_accessibility_profile_endpoint, methods=["PATCH"])

# US-75: cross-session trouble words bank & spaced repetition
router.add_api_route("/trouble-words", get_active_trouble_words_endpoint, methods=["GET"])
router.add_api_route("/trouble-words/archive", get_trouble_words_archive_endpoint, methods=["GET"])
router.add_api_route("/trouble-words/next-review", get_next_review_word_endpoint, methods=["GET"])
router.add_api_route("/trouble-words/{pattern_key}/dismiss", dismiss_trouble_word_endpoint, methods=["POST"])
