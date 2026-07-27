from typing import Optional

from pydantic import BaseModel


class AccessibilityProfileUpdateSchema(BaseModel):
    """Body for PATCH /api/pronunciation-coach/accessibility-profile (US-76)."""

    opted_in: bool
    disclosed_condition: Optional[str] = None
