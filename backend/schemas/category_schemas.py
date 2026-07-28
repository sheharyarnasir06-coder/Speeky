from pydantic import BaseModel, Field, field_validator

# Curated icon-name set — keys into frontend/lib/icon-map.ts's lucide lookup.
# Closed vocabulary (CM-US-05 E-03 analog: unknown icon falls back to a default
# rather than breaking the learner-facing tile), kept in sync with the frontend map.
ALLOWED_ICONS = (
    "folder", "briefcase", "coffee", "plane", "utensils", "heart",
    "book", "shopping-bag", "graduation-cap", "stethoscope", "home", "globe",
)


class CategorySchema(BaseModel):
    name: str = Field(min_length=2, max_length=40)
    icon: str = "folder"
    order: int = 0

    @field_validator("name")
    @classmethod
    def strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Category name is required.")
        return v

    @field_validator("icon")
    @classmethod
    def valid_icon(cls, v: str) -> str:
        return v if v in ALLOWED_ICONS else "folder"
