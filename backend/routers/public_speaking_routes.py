"""Public Speaking Coach Routes — PSC-US-01, PSC-US-03, PSC-US-04, PSC-US-05, PSC-US-06, PSC-US-07, PSC-US-11, PSC-US-12, PSC-US-14"""

from fastapi import APIRouter, Depends, WebSocket

from middlewares.auth_middleware import require_auth
from schemas.public_speaking_schemas import (
    StartPublicSpeakingSchema,
    PublicSpeakingTurnSchema,
    QAResponseSchema,
)
# PSC-US-08 note: get_filler_words_for_session exists in TWO services and they are
# not interchangeable. This router uses the public_speaking_service one (below),
# which rebuilds the analysis from the session's stored transcript/audioFeatures and
# raises SessionNotFoundError. coaching_routes.py deliberately uses the
# filler_word_service one instead, for its CoachingSession + KV-store fallback.
from services.public_speaking_service import (
    start_session,
    submit_turn,
    submit_qa_response,
    get_session,
    voice_socket,
    get_filler_words_for_session,
    find_resumable_session,
)

router = APIRouter()


# Public Speaking Coach endpoints
@router.post("/start")
async def api_start_session(
    request: StartPublicSpeakingSchema,
    user_id: str = Depends(require_auth),
):
    """Start a new public speaking session"""
    return await start_session(user_id, request)


# Registered before "/{session_id}" so "resume" doesn't get swallowed by that path param.
@router.get("/resume")
async def api_find_resumable_session(user_id: str = Depends(require_auth)):
    """Find the user's latest unfinished session, if any (mirrors the pronunciation
    coach's GET /resume) — the landing page checks this before offering a fresh start."""
    return await find_resumable_session(user_id)


@router.post("/{session_id}/turn")
async def api_submit_turn(
    session_id: str,
    turn: PublicSpeakingTurnSchema,
    user_id: str = Depends(require_auth),
):
    """Submit a speech turn (audio or text)"""
    return await submit_turn(session_id, user_id, turn)


@router.post("/{session_id}/qa")
async def api_submit_qa_response(
    session_id: str,
    response: QAResponseSchema,
    user_id: str = Depends(require_auth),
):
    """Submit Q&A response"""
    return await submit_qa_response(session_id, user_id, response)


@router.websocket("/{session_id}/voice-ws")
async def api_voice_socket(websocket: WebSocket, session_id: str):
    await voice_socket(websocket, session_id)


@router.get("/{session_id}")
async def api_get_session(
    session_id: str,
    user_id: str = Depends(require_auth),
):
    """Get session details"""
    return await get_session(session_id, user_id)


@router.get("/{session_id}/filler-words")
async def api_get_filler_words(
    session_id: str,
    user_id: str = Depends(require_auth),
):
    """Get filler word breakdown and timeline markers for session (PSC-US-08)"""
    return await get_filler_words_for_session(session_id, user_id)