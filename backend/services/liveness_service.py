"""
Live Speech Verification & Anti-Cheat Service (ACC-US-01)

Implements session prompt token generation/validation and playback-detection gating.
Each recording is judged independently on its own signal characteristics — no
cross-attempt flag counting, account suspension, or appeal workflow.
"""

from datetime import datetime, timezone
from typing import Optional
import uuid

from lib import kv_store
from lib.speech_config import load_speech_config

LIVENESS_TOKEN_NS = "liveness_tokens"


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


async def validate_prompt_token(user_id: str, item_id: str, prompt_token: Optional[str]) -> bool:
    """Read-only validity check — does NOT mark the token used. Callers that might still
    reject the attempt for a content-quality reason (too quiet, multiple voices,
    incomplete) after this check should call this first and only consume_prompt_token()
    once the attempt is confirmed to proceed past those gates. Consuming here would burn
    the token on a legitimate retry, so the user's very next attempt (same passage, same
    token) fails with a confusing "stale token" error instead of showing them what
    actually went wrong the second time too."""
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

    return True


async def consume_prompt_token(prompt_token: str) -> None:
    """Mark an already-validated token single-use. Call only once an attempt is
    confirmed to proceed — see validate_prompt_token."""
    entry = await kv_store.store.get(LIVENESS_TOKEN_NS, prompt_token)
    if not entry:
        return
    entry["used"] = True
    await kv_store.store.update(LIVENESS_TOKEN_NS, prompt_token, entry)


async def validate_and_consume_prompt_token(user_id: str, item_id: str, prompt_token: Optional[str]) -> bool:
    """Combined check+consume for callers with no content-quality gate to defer past."""
    if not await validate_prompt_token(user_id, item_id, prompt_token):
        return False
    await consume_prompt_token(prompt_token)  # type: ignore[arg-type]  -- non-None, validated above
    return True
