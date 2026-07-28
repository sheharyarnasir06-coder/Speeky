from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class ChallengeStatus(str, Enum):
    PENDING = "pending"  # timer running (or not yet started) — under 5 minutes so far
    QUALIFIED = "qualified"


class StartChallengeRequest(BaseModel):
    # E-02: the LOCAL calendar date (client's clock) this attempt counts for — a
    # challenge started before midnight counts for the day it began, matching the
    # convention lib/dailyChallenge.ts's localDate() already documents for /status.
    local_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")


class StartChallengeResponse(BaseModel):
    session_id: str  # AI Conversation session id — frontend redirects here
    topic_key: str
    topic_label: str
    opening_message: str
    already_completed_today: bool


class ChallengeConversationStatusResponse(BaseModel):
    session_id: str
    status: ChallengeStatus
    just_completed: bool  # true exactly once: the poll that crossed the 5-minute mark
    seconds_remaining: int
    current_streak: int
    longest_streak: int
    milestone_days: Optional[int] = None
    milestone_message: Optional[str] = None
    overuse_nudge: Optional["OveruseNudgePayload"] = None


class StreakResponse(BaseModel):
    user_id: str
    current_streak: int
    longest_streak: int
    qualified_dates: List[str]


# Deferred import to avoid a circular dependency (overuse schemas don't need daily
# challenge schemas), resolved via forward ref above.
from schemas.overuse_schemas import OveruseNudgePayload  # noqa: E402

ChallengeConversationStatusResponse.model_rebuild()
