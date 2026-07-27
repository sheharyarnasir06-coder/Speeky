"""Public Speaking Coach Routes — PSC-US-01, PSC-US-03, PSC-US-04, PSC-US-05, PSC-US-06, PSC-US-07, PSC-US-11, PSC-US-12, PSC-US-14"""

from fastapi import APIRouter, Depends

from middlewares.auth_middleware import require_auth
from schemas.public_speaking_schemas import (
    StartPublicSpeakingSchema,
    PublicSpeakingTurnSchema,
    QAResponseSchema,
)
from services.public_speaking_service import (
    start_session,
    submit_turn,
    submit_qa_response,
    get_session,
    get_voice_token,
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


@router.post("/{session_id}/voice-token")
async def api_voice_token(
    session_id: str,
    user_id: str = Depends(require_auth),
):
    """Mint a LiveKit room token for a spoken turn (shared voice pipeline)."""
    return await get_voice_token(session_id, user_id)


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

