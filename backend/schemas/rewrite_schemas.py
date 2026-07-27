"""
Post-Session Actionable Script — Rewrite feature schemas.

Covers three self-contained user stories that all operate on an
{original, rewrite} pair:

  - US-158 / PSA-US-06  Personalized Rewrite Difficulty  -> /generate
  - US-156 / PSA-US-04  Rewrite Improvement Score        -> /score
  - US-159 / PSA-US-07  Rewrite Explainability           -> /explain

Stateless by design: no persistence, no new Prisma model — the endpoints take
text in and return analysis, so they never touch existing session tables.
"""

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class DifficultyLevel(str, Enum):
    """The four learner-facing rewrite tiers from PSA-US-06.

    Not the same axis as the 6-value CEFR-style LearningLevel enum on User —
    'executive' is a professional register, not a proficiency. `LEVEL_MAP` in
    rewrite_service maps the stored LearningLevel onto these four when the
    caller lets us auto-detect (difficulty omitted)."""

    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"
    EXECUTIVE = "executive"


# ── US-158: Personalized Rewrite Difficulty ───────────────────────────────────
class GenerateRewriteRequest(BaseModel):
    original: str = Field(..., min_length=1, description="The learner's own wording to improve")
    context: Optional[str] = Field(
        None, description="Optional situation hint, e.g. 'HR interview answer' or 'client email'"
    )
    # None => auto-detect from the learner's assessed level (E-01 defaults to intermediate).
    difficulty: Optional[DifficultyLevel] = Field(
        None, description="Manual override; omit to personalize from the learner's level"
    )


# ── US-161: Rewrite Reliability & Quality Validation ──────────────────────────
class ValidationResult(BaseModel):
    """Outcome of the quality gate that every generated rewrite passes through.

    checks maps each dimension (fact_preservation, tone_consistency,
    professional_vocabulary, readability, no_hallucination, context_preservation)
    to pass/fail. `validated=False` means the gate was skipped (LLM unavailable),
    not that it failed."""

    passed: bool
    validated: bool
    checks: dict = Field(default_factory=dict)
    issues: List[str] = Field(default_factory=list)


class GenerateRewriteResponse(BaseModel):
    original: str
    rewrite: str
    difficulty_used: DifficultyLevel
    auto_detected: bool  # True when difficulty was resolved from the learner's stored level
    generated_by: str    # "llm" | "offline"
    # US-161: quality gate result + how many generations it took to pass.
    validation: Optional[ValidationResult] = None
    attempts: int = 1


class ValidateRewriteRequest(BaseModel):
    original: str = Field(..., min_length=1)
    rewrite: str = Field(..., min_length=1)
    difficulty: Optional[DifficultyLevel] = Field(
        None, description="Optional level, so vocabulary-complexity is judged against the right tier"
    )


# ── US-156: Rewrite Improvement Score ─────────────────────────────────────────
class DimensionScore(BaseModel):
    name: str  # grammar | professional_tone | vocabulary | sentence_organization | conciseness
    score: int = Field(..., ge=0, le=100, description="Improvement on this axis; 50 = no change")
    explanation: str


class ScoreRewriteRequest(BaseModel):
    original: str = Field(..., min_length=1)
    rewrite: str = Field(..., min_length=1)


class ScoreRewriteResponse(BaseModel):
    overall_score: int = Field(..., ge=0, le=100)
    dimensions: List[DimensionScore]
    summary: str
    # E-01/E-02: when the original was already strong, we say so rather than inflating changes.
    significant_improvement: bool
    graded_by: str  # "llm" | "offline"


# ── US-159: Rewrite Explainability ────────────────────────────────────────────
class ChangeExplanation(BaseModel):
    category: str  # grammar | vocabulary | tone | conciseness | structure
    before: str
    after: str
    explanation: str


class ExplainRewriteRequest(BaseModel):
    original: str = Field(..., min_length=1)
    rewrite: str = Field(..., min_length=1)


class ExplainRewriteResponse(BaseModel):
    changes: List[ChangeExplanation]
    summary: str
    # E-01: no meaningful edits -> reassure instead of fabricating an explanation list.
    has_meaningful_changes: bool
    explained_by: str  # "llm" | "offline"
