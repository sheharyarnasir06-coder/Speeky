from datetime import datetime
from typing import Literal, Optional
from schemas.auth_schemas import _require_email_format
from pydantic import BaseModel, EmailStr, Field, field_validator


# US-08/US-10. Mirrors Frontend/lib/goals.ts LEARNING_GOALS — keep the two in sync.
LearningGoal = Literal[
    "improve_english",
    "job_interviews",
    "workplace_communication",
    "public_speaking",
]
DEFAULT_LEARNING_GOAL: str = "improve_english"


class LearningGoalSchema(BaseModel):
    """PATCH body — set/change the goal. Saving always marks learningGoalSet=true
    (see services.user_service.set_learning_goal), which is what clears the
    Frontend LearningGoalGate for pre-US-08 accounts."""

    learning_goal: LearningGoal


class LearningGoalStatusSchema(BaseModel):
    """GET response — includes learning_goal_set so the caller can tell a real
    choice apart from the untouched default (pre-US-08 accounts)."""

    learning_goal: LearningGoal
    learning_goal_set: bool


class UpdateProfileSchema(BaseModel):
    """Name only — email changes go through RequestEmailChangeSchema /
    VerifyEmailChangeSchema instead, since they need OTP verification."""

    name: str = Field(min_length=3, max_length=100, pattern=r"^[a-zA-Z0-9 _-]+$")


class RequestEmailChangeSchema(BaseModel):
    email: EmailStr

    _validate_gmail = field_validator("email")(_require_email_format)


class VerifyEmailChangeSchema(BaseModel):
    code: str = Field(min_length=6, max_length=6, pattern=r"^[A-Za-z0-9]{6}$")


class UpdateRoleSchema(BaseModel):
    role: Literal["USER", "ADMIN"]


class DeleteAccountSchema(BaseModel):
    password: str = Field(min_length=1)


class ConsentStatusSchema(BaseModel):
    is_consented: bool
    consent_version: Optional[str] = None
    consent_accepted_at: Optional[datetime] = None


class ConsentUpdateSchema(BaseModel):
    is_consented: bool
    policy_version: str


class AccentPreferenceSchema(BaseModel):
    accent_model_preference: str = Field(default="generic_global")
    sub_dialect_preference: Optional[str] = None
    notice: Optional[str] = None


class UpdateAccentPreferenceSchema(BaseModel):
    accent_model_preference: Literal["generic_global", "south_asian_pakistani"]
    sub_dialect_preference: Optional[str] = None

