"""Request schemas for the Sprint 3 content-intelligence endpoints (US-192,
US-193, US-195, US-196, US-198)."""

from pydantic import BaseModel, Field, field_validator

# CM-US-09 "Learner satisfaction" is captured on the classic 1-5 scale. Bounded
# in the schema so an out-of-range value is rejected at the edge rather than
# silently skewing the dashboard average.
MIN_SATISFACTION = 1
MAX_SATISFACTION = 5


class SatisfactionRatingSchema(BaseModel):
    rating: int = Field(ge=MIN_SATISFACTION, le=MAX_SATISFACTION)

    @field_validator("rating", mode="before")
    @classmethod
    def reject_bool(cls, v):
        """`bool` is a subclass of `int` in Python, so pydantic happily coerced
        `true` into 1 — a buggy client sending a boolean silently recorded the
        WORST satisfaction score, polluting both the CM-US-09 dashboard average
        and the CM-US-12 user-feedback drift signal. A boolean is never a rating.
        """
        if isinstance(v, bool):
            raise ValueError("rating must be a number from 1 to 5, not a boolean")
        return v
