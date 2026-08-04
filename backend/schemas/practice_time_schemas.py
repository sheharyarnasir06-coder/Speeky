from pydantic import BaseModel, Field, field_validator

ALLOWED_SESSION_TYPES = ("scenario", "conversation", "coaching", "interview_coach", "public_speaking")


class PracticeTimePingSchema(BaseModel):
    session_type: str
    session_id: str = Field(min_length=1)

    @field_validator("session_type")
    @classmethod
    def valid_session_type(cls, v: str) -> str:
        if v not in ALLOWED_SESSION_TYPES:
            raise ValueError(f"session_type must be one of {ALLOWED_SESSION_TYPES}")
        return v
