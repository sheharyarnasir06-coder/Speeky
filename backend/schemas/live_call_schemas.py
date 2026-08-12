from typing import Literal

from pydantic import BaseModel

# public_speaking's conversational agent is Q&A-only: the speech itself is a monologue that a
# live agent would talk over, so live_call_service refuses to mint a "qa" token until the
# session reaches "qa_phase".
LiveCallFeature = Literal[
    "conversation", "interview_coach", "scenario", "coaching", "public_speaking"
]

# "idle" is public_speaking's speech phase only: a silent avatar that stands in for an audience
# member, with no STT/LLM/TTS wired at all (see live_call/worker.py). It is a separate mode
# rather than a relaxation of the qa_phase gate — that gate keeps a *conversational* agent out
# of the monologue, which is still exactly what we want.
LiveCallMode = Literal["qa", "idle"]


class LiveCallTokenRequestSchema(BaseModel):
    feature: LiveCallFeature
    session_id: str
    # Defaulted so every existing caller keeps its current behaviour without change.
    mode: LiveCallMode = "qa"


class LiveCallTokenResponseSchema(BaseModel):
    token: str
    url: str
    room_name: str
