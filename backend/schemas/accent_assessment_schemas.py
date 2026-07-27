from typing import Optional

from pydantic import BaseModel, Field


class SelectTargetAccentSchema(BaseModel):
    """Body for POST /api/accent-assessment/target-accent (US-82 / ACC-US-03)."""

    accent_id: str
    local_calibration_active: bool = False


class RebaselineSchema(BaseModel):
    """Body for POST /api/accent-assessment/rebaseline (US-84 / ACC-US-05).

    `session_id` must reference the caller's own completed conversation
    session — its real, already-computed scores are reused as the new
    baseline's metrics rather than trusting client-supplied numbers.
    """

    session_id: str


class SubmitDisputeSchema(BaseModel):
    """Body for POST /api/accent-assessment/disputes (US-83 / ACC-US-04)."""

    assessment_id: str
    metric_name: str = Field(description='e.g. "fluency", "vocabulary", "pronunciation", "overall"')
    reason: str = Field(description="background_noise | misheard_word | unfair_penalty | other")
    user_comment: Optional[str] = None
