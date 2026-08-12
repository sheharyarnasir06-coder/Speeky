import os
import secrets
from datetime import timedelta

from fastapi import Depends
from fastapi.responses import JSONResponse
from livekit import api

from middlewares.auth_middleware import require_auth
from schemas.live_call_schemas import (
    LiveCallFeature,
    LiveCallMode,
    LiveCallTokenRequestSchema,
    LiveCallTokenResponseSchema,
)
from services.coaching_service import get_session as _get_coaching_session
from services.conversation_service import _get_session as _get_conversation_session
from services.interview_coach_service import _get_session as _get_interview_coach_session
from services.public_speaking_service import get_session as _get_public_speaking_session
from services.scenario_service import get_session as _get_scenario_session
from utils.feature_errors import SessionNotFoundError

# Short-lived — a token only needs to outlive the connect handshake plus one call.
TOKEN_TTL = timedelta(hours=2)


async def _session_belongs_to_user(
    feature: LiveCallFeature, session_id: str, user_id: str, mode: LiveCallMode = "qa"
) -> bool:
    """Reuses each feature's own session lookup rather than re-deriving ownership
    checks here, so Live Call access rules can never drift from the feature's own."""
    # Idle is a public_speaking-only concept — nothing else has a phase where a silent
    # avatar makes sense, so refuse it everywhere else rather than minting a token for a
    # room the worker has no idle path for.
    if mode == "idle" and feature != "public_speaking":
        return False
    try:
        if feature == "conversation":
            await _get_conversation_session(session_id, user_id)
        elif feature == "interview_coach":
            await _get_interview_coach_session(session_id, user_id)
        elif feature == "scenario":
            # get_session returns a JSONResponse(404) instead of raising on miss.
            result = await _get_scenario_session(session_id, user_id)
            if isinstance(result, JSONResponse):
                return False
        elif feature == "coaching":
            result = await _get_coaching_session(session_id, user_id)
            if isinstance(result, JSONResponse):
                return False
        elif feature == "public_speaking":
            session = await _get_public_speaking_session(session_id, user_id)
            # Ownership is not enough here. Unlike the free-flowing features, Public Speaking has
            # a phase where a live agent must NOT be present: during the speech it would talk
            # over the speaker and its voice would land in the audio being scored. The room only
            # exists for the Q&A that follows.
            #
            # The idle avatar is the deliberate exception, and it is the inverse gate rather
            # than a weaker one: it is allowed *only* during the speech, and the worker gives
            # that room no STT/LLM/TTS at all, so there is nothing to talk over or transcribe.
            required_status = "in_progress" if mode == "idle" else "qa_phase"
            if session.get("status") != required_status:
                return False
        return True
    except SessionNotFoundError:
        return False


async def _mint_token(user_id: str, req: LiveCallTokenRequestSchema) -> LiveCallTokenResponseSchema:
    if not await _session_belongs_to_user(req.feature, req.session_id, user_id, req.mode):
        raise SessionNotFoundError(f"{req.feature} session {req.session_id} not found")

    # Self-describing room name: the agent worker parses feature + session straight
    # back out of ctx.room.name, no separate metadata channel needed.
    #
    # public_speaking carries the mode too, so the worker knows which kind of agent to start
    # from the room name alone. It is the mode this function just *validated*, never the raw
    # request — the room name is what the worker trusts, so it must not be caller-controlled.
    #
    # Trailing nonce: LiveKit's automatic agent dispatch fires once per room *creation*, not
    # per join — a session's room name used to be fully deterministic, so re-opening Live Call
    # on the same session after an abrupt disconnect (e.g. closing the modal while the avatar
    # was still speaking) could rejoin the still-alive old room and get no agent at all. A random nonce per mint makes every attempt its own
    # room, so a fresh dispatch always fires. dispatch.parse_room_name strips it back off.
    nonce = secrets.token_hex(4)
    room_name = (
        f"livecall_public_speaking_{req.mode}_{req.session_id}_{nonce}"
        if req.feature == "public_speaking"
        else f"livecall_{req.feature}_{req.session_id}_{nonce}"
    )
    token = (
        api.AccessToken(os.environ["LIVEKIT_API_KEY"], os.environ["LIVEKIT_API_SECRET"])
        .with_identity(user_id)
        .with_ttl(TOKEN_TTL)
        .with_grants(api.VideoGrants(room_join=True, room=room_name, can_publish=True, can_subscribe=True))
        .to_jwt()
    )
    return LiveCallTokenResponseSchema(token=token, url=os.environ["LIVEKIT_URL"], room_name=room_name)


async def mint_token(payload: LiveCallTokenRequestSchema, user_id: str = Depends(require_auth)):
    return await _mint_token(user_id, payload)
