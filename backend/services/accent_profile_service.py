"""
Accent Profile & Improvement (US-89): turns a COMPLETED Accent Assessment (US-93) into
a persisted baseline profile, and generates a first batch of targeted practice
exercises from its weak points.

generate_profile_from_assessment() is called by services/accent_assessment_service.py
right after it persists a COMPLETED assessment — never triggered independently, so a
profile can't exist without a completed assessment behind it.
"""

import logging
import random
from typing import Dict, List

from fastapi import Depends
from prisma import Json

from lib import llm_client
from lib.prisma_client import db
from lib.prompts import SENTENCE_BANK, DEFAULT_SENTENCE_SET
from lib.speech_config import SpeechConfig, load_speech_config
from middlewares.auth_middleware import require_auth
from schemas.accent_schemas import AccentProfileSchema, WeakPointSchema
from utils.feature_errors import NoCompletedAssessmentError

logger = logging.getLogger(__name__)

_GENERIC_TEMPLATES = {
    "speech rhythm": 'Read this aloud slowly, tapping once per syllable to build a steady rhythm: "{sentence}"',
    "intonation range": 'Read this sentence twice — first flat, then with clear pitch rises and falls: "{sentence}"',
}


async def generate_profile_from_assessment(assessment) -> None:
    config = load_speech_config()
    weak_points = list(assessment.weakPoints)
    exercises = await _generate_exercises(weak_points, config)

    await db.accentprofile.create(
        data={
            "userId": assessment.userId,
            "sourceAssessmentId": assessment.id,
            "pronunciationScore": assessment.pronunciationScore,
            "stressScore": assessment.stressScore,
            "rhythmScore": assessment.rhythmScore,
            "intonationScore": assessment.intonationScore,
            "clarityScore": assessment.clarityScore,
            "weakPoints": Json(weak_points),
            "exercises": Json(exercises),
        }
    )


async def get_profile(user_id: str = Depends(require_auth)):
    profile = await db.accentprofile.find_first(where={"userId": user_id}, order={"createdAt": "desc"})
    if not profile:
        raise NoCompletedAssessmentError("No completed Accent Assessment found yet. Complete an assessment first.")
    return _to_schema(profile)


async def get_exercises(user_id: str = Depends(require_auth)):
    profile = await db.accentprofile.find_first(where={"userId": user_id}, order={"createdAt": "desc"})
    if not profile:
        raise NoCompletedAssessmentError("No completed Accent Assessment found yet. Complete an assessment first.")
    return {"exercises": list(profile.exercises)}


def _to_schema(profile) -> AccentProfileSchema:
    return AccentProfileSchema(
        profile_id=profile.id,
        source_assessment_id=profile.sourceAssessmentId,
        pronunciation_score=profile.pronunciationScore,
        stress_score=profile.stressScore,
        rhythm_score=profile.rhythmScore,
        intonation_score=profile.intonationScore,
        clarity_score=profile.clarityScore,
        weak_points=[WeakPointSchema(**wp) for wp in profile.weakPoints],
        exercises=list(profile.exercises),
        created_at=profile.createdAt.isoformat(),
    )


# ── Exercise generation ──────────────────────────────────────────────────────────────
async def _generate_exercises(weak_points: List[Dict], config: SpeechConfig) -> List[str]:
    if not weak_points:
        return []
    if llm_client.is_configured():
        try:
            raw = await llm_client.chat(
                [{"role": "user", "content": _build_exercise_prompt(weak_points, config.exercise_batch_size)}],
                temperature=0.5,
                max_tokens=500,
            )
            lines = [line.strip("-*• ").strip() for line in raw.splitlines() if line.strip()]
            if lines:
                return lines[: config.exercise_batch_size]
        except llm_client.LLMError:
            logger.warning("Exercise-generation LLM call failed; falling back to templated exercises")
    return _template_exercises(weak_points, config.exercise_batch_size)


def _build_exercise_prompt(weak_points: List[Dict], batch_size: int) -> str:
    issues = "; ".join(f"{wp['issue']} ({wp['detail']})" for wp in weak_points)
    return (
        f"An English learner's spoken-accent assessment found these weak points: {issues}. "
        f"Write {batch_size} short practice sentences (one per line, no numbering, no extra "
        f"commentary) that specifically target these weak points for spoken pronunciation practice."
    )


def _template_exercises(weak_points: List[Dict], batch_size: int) -> List[str]:
    """Offline fallback: reuse the Pronunciation Coach sentence bank (phoneme ->
    sentence list), matching a weak point's issue keyword to a phoneme key, plus a
    generic templated drill for prosodic weak points (rhythm/intonation) that aren't
    tied to a specific sound."""
    sentence_pool = [s for sentences in SENTENCE_BANK.values() for s in sentences] or list(DEFAULT_SENTENCE_SET)
    exercises: List[str] = []

    per_weak_point = max(1, batch_size // max(1, len(weak_points)))
    for wp in weak_points:
        issue = wp["issue"].lower()
        matching_phonemes = [p for p in SENTENCE_BANK if issue.split()[0] in p.lower()]
        matching = [s for p in matching_phonemes for s in SENTENCE_BANK[p]]
        if matching:
            exercises.extend(matching[:per_weak_point])
        elif issue in _GENERIC_TEMPLATES:
            sentence = random.choice(sentence_pool)
            exercises.append(_GENERIC_TEMPLATES[issue].format(sentence=sentence))

    if not exercises:
        exercises = random.sample(sentence_pool, min(3, len(sentence_pool)))

    return exercises[:batch_size]