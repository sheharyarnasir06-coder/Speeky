from typing import Literal, Optional
from schemas.auth_schemas import _require_email_format
from pydantic import BaseModel, EmailStr, Field, field_validator


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


class AccentPreferenceSchema(BaseModel):
    accent_model_preference: str = Field(default="generic_global")
    sub_dialect_preference: Optional[str] = None
    notice: Optional[str] = None


class UpdateAccentPreferenceSchema(BaseModel):
    accent_model_preference: Literal["generic_global", "south_asian_pakistani"]
    sub_dialect_preference: Optional[str] = None

