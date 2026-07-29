"""
Accent Improvement Targeted Exercises Service (ACC-US-13)

Dynamically generates personalized drills from the user's Accent Profile weak points.
Reuses the liveness gate (ACC-US-01), regional calibration (ACC-US-11), and sub-dialect
tolerance (ACC-US-09). Handles:
  E-01: No baseline assessment → block access with clear CTA.
  E-02: 5 consecutive failures on same phoneme → pause drill, return tongue/mouth placement tip.
  E-03: Audio distortion → reject with "Audio distortion detected" (extends recording_engine.py).
  E-04: Rapid exercise skipping → log zero progress, return consistency reminder.
"""

import logging
import uuid
from typing import Dict, List, Optional

from fastapi import Depends, File, Form, UploadFile
from fastapi.responses import JSONResponse

from lib import kv_store, recording_engine
from lib.audio_io import AudioDecodeError
from lib.prisma_client import db
from lib.recording_engine import RejectionReason
from lib.speech_config import load_speech_config
from lib.text_alignment import WordStatus
from middlewares.auth_middleware import require_auth
from schemas.accent_schemas import (
    RecordingRejectedSchema,
    TargetedDrillResultSchema,
    TargetedDrillSchema,
    TargetedDrillSkipResponseSchema,
)
from services import accent_calibration_service, liveness_service
from utils.feature_errors import NoCompletedAssessmentError, UnreadableAudioError, UploadTooLargeError

logger = logging.getLogger(__name__)

DRILL_STREAK_NS = "targeted_drill_phoneme_streak"
DRILL_SESSION_NS = "targeted_drill_sessions"
DRILL_SENTENCE_NS = "targeted_drill_sentences"
MAX_CONSECUTIVE_FAILURES = 5
MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB

# Tongue/mouth placement tips per phoneme cluster
PLACEMENT_TIPS: Dict[str, str] = {
    "th": "For /th/ sounds: place your tongue lightly between your upper and lower front teeth, then blow air gently.",
    "r": "For /r/ sounds: curl the tip of your tongue back slightly without touching the roof of your mouth.",
    "v": "For /v/ sounds: rest your upper front teeth lightly on your lower lip and vibrate your vocal cords.",
    "w": "For /w/ sounds: round your lips tightly as if whistling, then open them while voicing.",
    "p": "For /p/ sounds: press both lips together and release with a puff of air.",
    "default": "Focus on relaxing your jaw and lips. Try slowing down to isolate each sound clearly.",
}


async def _is_db_connected() -> bool:
    try:
        return db.is_connected()
    except Exception:
        return False


def _get_placement_tip(phoneme: str) -> str:
    phoneme_lower = phoneme.lower().strip()
    # Sort keys longest-first so 'th' matches before 't', etc.
    for key in sorted((k for k in PLACEMENT_TIPS if k != "default"), key=len, reverse=True):
        if phoneme_lower == key or phoneme_lower.startswith(key):
            return PLACEMENT_TIPS[key]
    return PLACEMENT_TIPS["default"]



async def _get_streak(user_id: str, phoneme: str) -> int:
    key = f"{user_id}::{phoneme}"
    entry = await kv_store.store.get(DRILL_STREAK_NS, key)
    if entry and isinstance(entry, dict):
        return entry.get("count", 0)
    return 0


async def _set_streak(user_id: str, phoneme: str, count: int) -> None:
    key = f"{user_id}::{phoneme}"
    entry = {"phoneme": phoneme, "count": count}
    existing = await kv_store.store.get(DRILL_STREAK_NS, key)
    if existing is None:
        await kv_store.store.create(DRILL_STREAK_NS, key, entry)
    else:
        await kv_store.store.update(DRILL_STREAK_NS, key, entry)


async def _get_latest_profile(user_id: str):
    """Fetch latest AccentProfile from DB (returns None if not connected or not found)."""
    if await _is_db_connected():
        try:
            profile = await db.accentprofile.find_first(
                where={"userId": user_id}, order={"createdAt": "desc"}
            )
            return profile
        except Exception as e:
            logger.warning(f"DB query for accent profile failed: {e}")
    return None


async def _get_baseline_score(user_id: str) -> Optional[float]:
    """Fetch the overall pronunciation baseline from the latest AccentAssessment."""
    if await _is_db_connected():
        try:
            assessment = await db.accentassessment.find_first(
                where={"userId": user_id, "status": "COMPLETED"},
                order={"createdAt": "desc"},
            )
            if assessment:
                return assessment.pronunciationScore
        except Exception as e:
            logger.warning(f"DB query for baseline assessment failed: {e}")
    return None


async def get_targeted_drills(user_id: str = Depends(require_auth)) -> Dict:
    """ACC-US-13: Fetch dynamically generated targeted drills from the user's accent weak points."""
    # E-01: Block if no completed assessment
    profile = await _get_latest_profile(user_id)
    if not profile:
        raise NoCompletedAssessmentError(
            "Take your Accent Assessment first to unlock personalized drills."
        )

    weak_points = list(profile.weakPoints) if profile.weakPoints else []
    exercises = list(profile.exercises) if profile.exercises else []

    if not weak_points:
        # If assessment exists but no weak points, return a generic encouragement drill
        weak_points = [{"issue": "general pronunciation", "detail": "Keep refining your overall pronunciation clarity."}]

    drills: List[TargetedDrillSchema] = []
    for i, wp in enumerate(weak_points):
        phoneme = wp.get("issue", "general")
        exercise_text = exercises[i] if i < len(exercises) else f"Practice the sound: {phoneme}"
        drill_id = f"drill_{uuid.uuid4().hex[:12]}"

        # FIX: persist this drill's actual sentence so submit_targeted_drill_attempt
        # can align against real drill text instead of the phoneme label.
        await kv_store.store.create(DRILL_SENTENCE_NS, drill_id, {"sentence": exercise_text})

        # Check phoneme failure streak (E-02)
        streak = await _get_streak(user_id, phoneme)
        is_paused = streak >= MAX_CONSECUTIVE_FAILURES
        placement_tip = _get_placement_tip(phoneme) if is_paused else None

        # Mint a unique prompt_token per drill for liveness gating (ACC-US-01)
        prompt_token = await liveness_service.create_prompt_token(user_id=user_id, item_id=drill_id)

        drills.append(
            TargetedDrillSchema(
                drill_id=drill_id,
                target_phoneme=phoneme,
                issue_description=wp.get("detail", ""),
                sentence=exercise_text,
                prompt_token=prompt_token,
                placement_tip=placement_tip,
                is_paused=is_paused,
            )
        )

    return {"drills": [d.model_dump() for d in drills]}


async def submit_targeted_drill_attempt(
    drill_id: str,
    target_phoneme: str = Form(...),
    prompt_token: str = Form(...),
    audio: UploadFile = File(...),
    user_id: str = Depends(require_auth),
):
    """ACC-US-13: Submit a drill recording, apply liveness gate + accent calibration, compare to baseline."""
    config = load_speech_config()

    # Size guard
    audio_bytes = await audio.read()
    if len(audio_bytes) > MAX_UPLOAD_BYTES:
        raise UploadTooLargeError("Audio upload exceeds 25 MB limit.")

    # Analyze audio
    try:
        analysis = recording_engine.analyze_recording(audio_bytes, config)
    except AudioDecodeError as exc:
        raise UnreadableAudioError(str(exc)) from exc

    # E-03: Audio distortion detected (extends existing recording_engine distortion check)
    if analysis.rejection == RejectionReason.AUDIO_DISTORTION:
        return JSONResponse(
            status_code=422,
            content=RecordingRejectedSchema(
                reason=RejectionReason.AUDIO_DISTORTION.value,
                message="Audio distortion detected. Please use a clean recording in a quiet environment.",
            ).model_dump(),
        )

    # Reject other audio quality issues (reuse existing rejection logic)
    if analysis.rejection is not None:
        return JSONResponse(
            status_code=422,
            content=RecordingRejectedSchema(
                reason=analysis.rejection.value,
                message=f"Recording rejected: {analysis.rejection.value}. Please try again.",
            ).model_dump(),
        )

    # Liveness gate — validate single-use prompt_token (ACC-US-01)
    token_valid = await liveness_service.validate_and_consume_prompt_token(
        user_id=user_id, item_id=drill_id, prompt_token=prompt_token
    )
    if not token_valid:
        return JSONResponse(
            status_code=422,
            content=RecordingRejectedSchema(
                reason="stale_token",
                message="Session token is invalid or has already been used. Please fetch a fresh drill.",
            ).model_dump(),
        )

    # Playback detection (ACC-US-01)
    playback_reason = recording_engine.detect_playback_audio(analysis, config)
    if playback_reason:
        return JSONResponse(
            status_code=422,
            content=RecordingRejectedSchema(
                reason=playback_reason.value,
                message="Detected playback audio. Live speech required for targeted drill scoring.",
            ).model_dump(),
        )

    # Accent calibration (ACC-US-11 + ACC-US-09 sub-dialect)
    user_pref, sub_pref, _ = await accent_calibration_service.get_user_accent_preference(user_id)

    # FIX: align against the drill's actual sentence, not the phoneme label
    # (target_phoneme is e.g. "word-final stress" — aligning to that always scored 0%
    # no matter what was said). Fall back to target_phoneme only if lookup fails.
    sentence_entry = await kv_store.store.get(DRILL_SENTENCE_NS, drill_id)
    target_sentence = sentence_entry["sentence"] if sentence_entry else target_phoneme

    # Compute pronunciation score for this drill
    aligned_words = recording_engine.align_to_sentence(analysis, target_sentence)
    from schemas.pronunciation_schemas import WordResultSchema

    # FIX: services.pronunciation_coach_service._classify_word does not exist.
    # Use the same real classifier pronunciation_coach_service.py itself calls
    # (lib.recording_engine.classify_word_status), applied to each aligned word.
    word_results = []
    for a in aligned_words:
        timing = analysis.words[a.transcript_index] if a.transcript_index is not None else None
        status = recording_engine.classify_word_status(a.target_word, timing, analysis.prosody, config)
        word_results.append(WordResultSchema(
            word=a.target_word,
            target_index=a.target_index,
            status=status.value,
            confidence=round(timing.probability, 3) if timing is not None else None,
        ))

    word_results, calibration_warning, model_used = accent_calibration_service.calibrate_word_results(
        word_results, user_pref, sub_dialect_preference=sub_pref
    )

    correct = sum(1 for w in word_results if w.status == WordStatus.CORRECT.value)
    total = max(1, len(word_results))
    overall_score = round((correct / total) * 100.0, 2)

    # Compare to baseline
    baseline_score = await _get_baseline_score(user_id)
    improved = baseline_score is not None and overall_score > baseline_score

    # E-02: Update failure streak for this phoneme
    streak = await _get_streak(user_id, target_phoneme)
    if overall_score < 60.0:
        new_streak = streak + 1
    else:
        new_streak = 0
    await _set_streak(user_id, target_phoneme, new_streak)

    placement_tip = None
    if new_streak >= MAX_CONSECUTIVE_FAILURES:
        placement_tip = _get_placement_tip(target_phoneme)

    return TargetedDrillResultSchema(
        drill_id=drill_id,
        target_phoneme=target_phoneme,
        overall_score=overall_score,
        improved_vs_baseline=improved,
        baseline_score=baseline_score,
        placement_tip=placement_tip,
        warning=calibration_warning,
        model_used=model_used,
    )


async def skip_targeted_exercises_session(user_id: str = Depends(require_auth)) -> TargetedDrillSkipResponseSchema:
    """ACC-US-13 E-04: User skips all exercises — log zero progress and return consistency reminder."""
    session_id = f"skip_{uuid.uuid4().hex[:10]}"
    entry = {"user_id": user_id, "session_id": session_id, "score": 0, "status": "skipped"}
    await kv_store.store.create(DRILL_SESSION_NS, session_id, entry)
    return TargetedDrillSkipResponseSchema(
        status="skipped",
        message="Consistent practice is required for measurable improvement. Don't skip your drills — even 5 minutes a day makes a difference!",
    )