"""
Live Speech Verification & Anti-Cheat Service (ACC-US-01)

Implements session prompt token generation/validation, playback detection gating,
liveness flag tracking, account suspension after 3+ flags, and false-positive appeal workflows.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

from lib import kv_store, recording_engine
from lib.prisma_client import db
from lib.speech_config import load_speech_config

logger = logging.getLogger(__name__)

LIVENESS_TOKEN_NS = "liveness_tokens"
LIVENESS_APPEAL_NS = "liveness_appeals"
LIVENESS_USER_NS = "liveness_user_state"


async def _is_db_connected() -> bool:
    try:
        return db.is_connected()
    except Exception:
        return False


async def create_prompt_token(user_id: str, item_id: str) -> str:
    """Generate a dynamic runtime prompt token per session (ACC-US-01 / E-04)."""
    token = f"prm_{uuid.uuid4().hex}"
    value = {
        "user_id": user_id,
        "item_id": item_id,
        "used": False,
        "created_at": datetime.now(timezone.utc),
    }
    await kv_store.store.create(LIVENESS_TOKEN_NS, token, value)
    return token


async def validate_and_consume_prompt_token(user_id: str, item_id: str, prompt_token: Optional[str]) -> bool:
    """Check prompt token validity and mark single-use (E-04 static prompt reuse rejection)."""
    if not prompt_token:
        return False

    entry = await kv_store.store.get(LIVENESS_TOKEN_NS, prompt_token)
    if not entry:
        return False

    if entry.get("used"):
        return False

    if entry.get("user_id") != user_id or entry.get("item_id") != item_id:
        return False

    config = load_speech_config()
    created_at = entry.get("created_at")
    if created_at:
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        age = (datetime.now(timezone.utc) - created_at).total_seconds()
        if age > config.liveness_token_ttl_seconds:
            return False

    # Mark as used (single-use token)
    entry["used"] = True
    await kv_store.store.update(LIVENESS_TOKEN_NS, prompt_token, entry)
    return True


async def check_user_suspended(user_id: str) -> bool:
    """Check if account is suspended from accent assessment (ACC-US-01 E-03)."""
    if await _is_db_connected():
        try:
            user = await db.user.find_unique(where={"id": user_id})
            if user:
                return bool(user.isAccentSuspended or user.livenessFlagCount >= 3)
        except Exception:
            pass

    state = await kv_store.store.get(LIVENESS_USER_NS, user_id)
    if state:
        return bool(state.get("is_suspended") or state.get("flag_count", 0) >= 3)
    return False


async def record_liveness_flag(
    user_id: str, item_id: Optional[str], prompt_token: Optional[str], reason: str
) -> Dict[str, str]:
    """Record a playback/liveness flag for a user, update flag count, and generate appeal token (E-01 / E-02 / E-03)."""
    state = await kv_store.store.get(LIVENESS_USER_NS, user_id) or {"flag_count": 0, "is_suspended": False}
    new_count = state["flag_count"] + 1
    is_suspended = new_count >= 3
    state["flag_count"] = new_count
    state["is_suspended"] = is_suspended

    if await kv_store.store.get(LIVENESS_USER_NS, user_id) is None:
        await kv_store.store.create(LIVENESS_USER_NS, user_id, state)
    else:
        await kv_store.store.update(LIVENESS_USER_NS, user_id, state)

    if await _is_db_connected():
        try:
            await db.livenessflag.create(
                data={
                    "userId": user_id,
                    "passageId": item_id,
                    "promptToken": prompt_token,
                    "reason": reason,
                    "appealed": False,
                    "appealPassed": False,
                }
            )
            user = await db.user.find_unique(where={"id": user_id})
            if user:
                await db.user.update(
                    where={"id": user_id},
                    data={
                        "livenessFlagCount": new_count,
                        "isAccentSuspended": is_suspended,
                    },
                )
        except Exception as e:
            logger.warning(f"DB update failed: {e}")

    appeal_token = f"app_{uuid.uuid4().hex}"
    appeal_value = {
        "user_id": user_id,
        "item_id": item_id,
        "used": False,
        "created_at": datetime.now(timezone.utc),
    }
    await kv_store.store.create(LIVENESS_APPEAL_NS, appeal_token, appeal_value)

    return {
        "appeal_token": appeal_token,
        "appeal_prompt": "Please read aloud this quick live verification sentence: 'The quick brown fox jumps over the lazy dog.'",
        "flag_count": new_count,
        "is_suspended": is_suspended,
    }


async def process_appeal(user_id: str, appeal_token: str, analysis: recording_engine.RecordingAnalysis) -> Tuple[bool, str]:
    """E-02 false positive appeal verification flow using secondary live prompt."""
    entry = await kv_store.store.get(LIVENESS_APPEAL_NS, appeal_token)
    if not entry or entry.get("user_id") != user_id or entry.get("used"):
        return False, "Invalid or expired appeal token."

    config = load_speech_config()
    playback_reason = recording_engine.detect_playback_audio(analysis, config)
    
    # Mark appeal token as used
    entry["used"] = True
    await kv_store.store.update(LIVENESS_APPEAL_NS, appeal_token, entry)

    if playback_reason is not None:
        return False, "Appeal recording failed liveness check. Playback audio characteristics still detected."

    # Appeal passed! Clear user flag in KV store and DB
    state = await kv_store.store.get(LIVENESS_USER_NS, user_id) or {"flag_count": 1, "is_suspended": False}
    new_count = max(0, state["flag_count"] - 1)
    state["flag_count"] = new_count
    state["is_suspended"] = new_count >= 3
    await kv_store.store.update(LIVENESS_USER_NS, user_id, state)

    if await _is_db_connected():
        try:
            user = await db.user.find_unique(where={"id": user_id})
            if user and user.livenessFlagCount > 0:
                await db.user.update(
                    where={"id": user_id},
                    data={
                        "livenessFlagCount": new_count,
                        "isAccentSuspended": new_count >= 3,
                    },
                )
        except Exception as e:
            logger.warning(f"DB update failed: {e}")

    return True, "Appeal verified successfully! Liveness check passed."
