"""
Accent Progress Tracker — ACC-US-15: Month-Over-Month Matrix Visualization.

Compares a user's Month 1 (baseline) Accent Assessment against their Month 3
(current) one across the four SOW-defined metrics: Pronunciation, Word Stress,
Intonation, Clarity. `monthIndex` is computed the same way
reassessment_service tracks BaselineAssessment cycles — one Accent Assessment
allowed per 30-day month, month 1 being the user's first ever submission.

Sits on top of the real recording pipeline's `AccentAssessment` model (US-93,
`AccentAssessmentStatus`) rather than a standalone table: only COMPLETED rows
count as valid data points here (REJECTED_* rows carry no real scores and must
never read as a baseline/current data point). `submit_assessment` is a manual
check-in stand-in for that pipeline — same score contract, so swapping in the
real recording flow later needs no changes on this tracker's side. `passageId`
is a required column on that model with no meaning for a manual check-in, so
it's set to a fixed sentinel here.
"""

import logging
from datetime import datetime, timezone
from typing import Dict, Optional

from fastapi import Depends

from lib.prisma_client import db
from middlewares.auth_middleware import require_auth
from prisma.enums import AccentAssessmentStatus
from schemas.accent_progress_schemas import SubmitAccentAssessmentSchema
from utils.app_error import AppError

logger = logging.getLogger(__name__)

CYCLE_DAYS = 30
BASELINE_MONTH = 1
CURRENT_MONTH = 3
SCORE_EPSILON = 0.01  # scores within this margin count as "stagnated", not improved/degraded
MANUAL_CHECKIN_PASSAGE_ID = "manual-checkin"

# (Prisma field name, display label) — order drives the matrix's row order.
METRICS = [
    ("pronunciationScore", "Pronunciation"),
    ("wordStressScore", "Word Stress"),
    ("intonationScore", "Intonation"),
    ("clarityScore", "Clarity"),
]


async def _next_month_index(user_id: str) -> int:
    first = await db.accentassessment.find_first(
        where={
            "userId": user_id,
            "status": AccentAssessmentStatus.COMPLETED,
            "completedAt": {"not": None},
        },
        order={"completedAt": "asc"},
    )
    if not first:
        return BASELINE_MONTH
    days_since = (datetime.now(timezone.utc) - first.completedAt).days
    return days_since // CYCLE_DAYS + 1


def _tune_up_prompt(label: str) -> str:
    return f"{label} dipped slightly this month. Let's do a quick 3-minute tune-up drill!"


def _metric_row(field: str, label: str, baseline, current) -> Dict:
    month1_score = getattr(baseline, field)
    month3_score = getattr(current, field) if current else None

    trend: Optional[str] = None
    tune_up_prompt: Optional[str] = None
    if month3_score is not None:
        if month3_score > month1_score + SCORE_EPSILON:
            trend = "improved"
        elif month3_score < month1_score - SCORE_EPSILON:
            trend = "degraded"
            tune_up_prompt = _tune_up_prompt(label)
        else:
            trend = "stagnated"

    return {
        "key": field,
        "label": label,
        "month1_score": round(month1_score, 1),
        "month3_score": round(month3_score, 1) if month3_score is not None else None,
        "trend": trend,
        "tune_up_prompt": tune_up_prompt,
    }


# ── Controllers ───────────────────────────────────────────────────────────────
async def submit_assessment(
    payload: SubmitAccentAssessmentSchema, user_id: str = Depends(require_auth)
):
    month_index = await _next_month_index(user_id)

    existing = await db.accentassessment.find_first(
        where={
            "userId": user_id,
            "monthIndex": month_index,
            "status": AccentAssessmentStatus.COMPLETED,
        }
    )
    if existing:
        raise AppError(
            f"You've already completed this month's Accent Assessment (month {month_index}).",
            409,
        )

    now = datetime.now(timezone.utc)
    assessment = await db.accentassessment.create(
        data={
            "userId": user_id,
            "passageId": MANUAL_CHECKIN_PASSAGE_ID,
            "monthIndex": month_index,
            "status": AccentAssessmentStatus.COMPLETED,
            "pronunciationScore": payload.pronunciation_score,
            "wordStressScore": payload.word_stress_score,
            "intonationScore": payload.intonation_score,
            "clarityScore": payload.clarity_score,
            "completedAt": now,
        }
    )
    return {
        "assessment_id": assessment.id,
        "month_index": assessment.monthIndex,
        "completed_at": assessment.completedAt.isoformat(),
        "is_baseline": assessment.monthIndex == BASELINE_MONTH,
    }


async def get_progress_matrix(user_id: str = Depends(require_auth)):
    # E-03: no baseline yet — force the user through a baseline Accent Assessment
    # before rendering any historical matrix. Only a COMPLETED reading counts —
    # a REJECTED_* attempt (bad audio, no speech, etc.) must never read as one.
    baseline = await db.accentassessment.find_first(
        where={
            "userId": user_id,
            "monthIndex": BASELINE_MONTH,
            "status": AccentAssessmentStatus.COMPLETED,
        },
        order={"completedAt": "asc"},
    )
    if not baseline:
        return {
            "has_baseline": False,
            "force_baseline": True,
            "message": "Complete your baseline Accent Assessment to unlock your Progress Tracker.",
        }

    current = await db.accentassessment.find_first(
        where={
            "userId": user_id,
            "monthIndex": CURRENT_MONTH,
            "status": AccentAssessmentStatus.COMPLETED,
        },
        order={"completedAt": "desc"},
    )

    # E-01: Month 3 not reached/completed yet — lock the column instead of
    # rendering blank/null data.
    locked = current is None
    days_until_unlock = None
    unlock_message = None
    if locked:
        days_since_baseline = (datetime.now(timezone.utc) - baseline.completedAt).days
        days_until_unlock = max(0, (CURRENT_MONTH - 1) * CYCLE_DAYS - days_since_baseline)
        # Once the chronological window has passed, time is no longer what's blocking the
        # column — the learner simply hasn't recorded the Month 3 reading yet. Saying
        # "unlocking in 0 days" there is the exact nonsense render E-01 exists to avoid,
        # so the copy is built here (one source of truth, correct pluralization).
        unlock_message = (
            f"Data unlocking in {days_until_unlock} day{'s' if days_until_unlock != 1 else ''}"
            if days_until_unlock > 0
            else "Your Month 3 check-in is ready — record it to unlock this column"
        )

    metrics = [_metric_row(field, label, baseline, current) for field, label in METRICS]

    return {
        "has_baseline": True,
        "force_baseline": False,
        "locked": locked,
        "days_until_unlock": days_until_unlock,
        "unlock_message": unlock_message,
        "baseline_completed_at": baseline.completedAt.isoformat(),
        "current_completed_at": current.completedAt.isoformat() if current else None,
        "metrics": metrics,
    }
