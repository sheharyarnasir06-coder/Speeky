from typing import List, Literal, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator

# Mirrors services/platform_metrics_service.METRIC_KEYS — see schemas/alert_schemas.py
# for why this is a local closed vocabulary instead of an import from services.
ALLOWED_METRIC_KEYS = ("daily_signups", "day1_retention", "day7_retention", "churn_rate", "revenue")
ALLOWED_DATE_RANGE_TYPES = ("last_7_days", "last_30_days", "month_to_date")
ALLOWED_RECURRENCES = ("weekly", "monthly", "none")
ALLOWED_FORMATS = ("pdf", "csv", "both")


class RecipientSchema(BaseModel):
    type: Literal["internal", "external"]
    value: str = Field(min_length=1)  # internal: admin User.id — external: email address

    @field_validator("value")
    @classmethod
    def value_shape(cls, v: str, info) -> str:
        if info.data.get("type") == "external":
            # Reuses pydantic's EmailStr validator without requiring a second field.
            from pydantic import TypeAdapter

            TypeAdapter(EmailStr).validate_python(v)
        return v


class ReportTemplateCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    metrics: List[str] = Field(min_length=1)
    date_range_type: str = "last_7_days"
    recurrence: str = "weekly"
    recurrence_day: Optional[int] = None
    recurrence_hour: int = Field(9, ge=0, le=23)
    recurrence_minute: int = Field(0, ge=0, le=59)
    timezone: str = "UTC"
    recipients: List[RecipientSchema] = Field(min_length=1)
    format: str = "pdf"
    # E-04: required (true) whenever metrics includes "revenue" and any recipient is external.
    confirmed_external_send: bool = False

    @field_validator("metrics")
    @classmethod
    def valid_metrics(cls, v: List[str]) -> List[str]:
        invalid = [m for m in v if m not in ALLOWED_METRIC_KEYS]
        if invalid:
            raise ValueError(f"Unknown metric(s): {invalid}")
        return v

    @field_validator("date_range_type")
    @classmethod
    def valid_range(cls, v: str) -> str:
        if v not in ALLOWED_DATE_RANGE_TYPES:
            raise ValueError(f"date_range_type must be one of {ALLOWED_DATE_RANGE_TYPES}")
        return v

    @field_validator("recurrence")
    @classmethod
    def valid_recurrence(cls, v: str) -> str:
        if v not in ALLOWED_RECURRENCES:
            raise ValueError(f"recurrence must be one of {ALLOWED_RECURRENCES}")
        return v

    @field_validator("format")
    @classmethod
    def valid_format(cls, v: str) -> str:
        if v not in ALLOWED_FORMATS:
            raise ValueError(f"format must be one of {ALLOWED_FORMATS}")
        return v

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, v: str) -> str:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(v)
        except ZoneInfoNotFoundError:
            raise ValueError(f"Unknown IANA timezone: {v}")
        return v


class ReportTemplateUpdateRequest(BaseModel):
    name: Optional[str] = None
    metrics: Optional[List[str]] = None
    date_range_type: Optional[str] = None
    recurrence: Optional[str] = None
    recurrence_day: Optional[int] = None
    recurrence_hour: Optional[int] = Field(None, ge=0, le=23)
    recurrence_minute: Optional[int] = Field(None, ge=0, le=59)
    timezone: Optional[str] = None
    recipients: Optional[List[RecipientSchema]] = None
    format: Optional[str] = None
    is_active: Optional[bool] = None
    confirmed_external_send: bool = False
