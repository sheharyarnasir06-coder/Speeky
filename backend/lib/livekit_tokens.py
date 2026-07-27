"""LiveKit room-token minting for AI Conversation Practice's voice mode.

The backend still never touches raw audio (see conversation_service.py) — this
module only signs a short-lived join token so the client can publish its mic into
a LiveKit room, and the voice_agent/ worker can subscribe and transcribe it.
"""

import json
import os

from livekit import api


def is_configured() -> bool:
    return bool(
        os.environ.get("LIVEKIT_URL")
        and os.environ.get("LIVEKIT_API_KEY")
        and os.environ.get("LIVEKIT_API_SECRET")
    )


def mint_room_token(room: str, identity: str, mode: str = "transcript") -> dict:
    """Mint a join token. `mode` is stamped into the participant metadata so the shared
    voice_agent worker knows which pipeline to run:
      "transcript" — fastest, text only (Scenario / Coaching / Interview Coach / Assessment)
      "timed"      — text + word_timings + duration_seconds, no prosody (Conversation, for
                     pronunciation scoring on audio turns)
      "full"       — text + word_timings + prosody + level, for delivery scoring
                     (Public Speaking Coach)."""
    token = (
        api.AccessToken(os.environ["LIVEKIT_API_KEY"], os.environ["LIVEKIT_API_SECRET"])
        .with_identity(identity)
        .with_metadata(json.dumps({"mode": mode}))
        .with_grants(api.VideoGrants(room_join=True, room=room))
        .to_jwt()
    )
    return {"url": os.environ["LIVEKIT_URL"], "token": token, "room": room, "mode": mode}
