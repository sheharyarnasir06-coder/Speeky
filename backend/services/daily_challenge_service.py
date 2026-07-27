"""
Anti-gaming detection for Daily Challenge completion (US-168 / GAP-07).

Wires content-quality scoring (lib/quality_scoring.py) into the Daily Challenge
completion flow before the streak increments, and drives the streak system itself
(there was no pre-existing streak backend to hook into — this module is now the
source of truth other features should call into, mirroring how
session_memory_service._record_session is the shared cross-feature signal hook).

Each turn is a real audio upload: lib/recording_engine.py (STT) supplies the
transcript text quality_scoring's repetition heuristic runs on, and
lib/prosody_engine.detect_multiple_voices (the same speaker-consistency heuristic
services/accent_assessment_service.py uses for MULTIPLE_VOICES_DETECTED) supplies the
non-interactive-audio signal for E-04 — neither is a client-supplied stub anymore.
"""

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Set

from fastapi import Depends, File, Form, UploadFile
from fastapi.responses import JSONResponse

from lib import kv_store, prosody_engine, recording_engine
from lib.audio_io import AudioDecodeError
from lib.prompts import (
    DAILY_CHALLENGE_MIN_DURATION_SECONDS,
    DAILY_CHALLENGE_MIN_QUALITY_SCORE,
    DAILY_CHALLENGE_MIN_TURNS,
    DISPUTE_CONFIRMED_MESSAGE,
    DISPUTE_DENIED_MESSAGE,
    LOW_ENGAGEMENT_NUDGE_MESSAGE,
    NON_INTERACTIVE_REJECTION_MESSAGE,
    STREAK_MILESTONE_DAYS,
    build_milestone_message,
)
from lib.quality_scoring import NON_INTERACTIVE_AUDIO, TurnSignal, score_engagement_quality
from lib.speech_config import load_speech_config
from middlewares.auth_middleware import require_admin, require_auth
from schemas.daily_challenge_schemas import (
    ChallengeStatus,
    ChallengeTurnResponse,
    CompleteChallengeRequest,
    CompleteChallengeResponse,
    DisputeSessionRequest,
    DisputeSessionResponse,
    DisputeStatus,
    ReviewSessionRequest,
    ReviewSessionResponse,
    StartChallengeRequest,
    StartChallengeResponse,
    StreakResponse,
)
from services import notification_service, overuse_service
from utils.feature_errors import (
    InvalidSubmissionError,
    SessionNotFoundError,
    UnreadableAudioError,
    UploadTooLargeError,
)

SESSIONS_NS = "daily_challenge_sessions"
STREAKS_NS = "daily_challenge_streaks"

INCOMPLETE_DURATION_MESSAGE = "Keep going a little longer to complete today's challenge."


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _date_str(dt: datetime) -> str:
    return dt.date().isoformat()


async def _get_session(user_id: str, session_id: str) -> Dict:
    session = await kv_store.store.get(SESSIONS_NS, session_id)
    if session is None or session["user_id"] != user_id:
        raise SessionNotFoundError(f"No daily challenge session {session_id} found")
    return session


# ── streak bookkeeping ─────────────────────────────────────────────────────
async def _get_streak_raw(user_id: str) -> Dict:
    raw = await kv_store.store.get(STREAKS_NS, user_id)
    if raw is None:
        raw = {"user_id": user_id, "current_streak": 0, "longest_streak": 0, "qualified_dates": []}
        await kv_store.store.create(STREAKS_NS, user_id, raw)
    return raw


def _recompute_current_streak(qualified_dates: Set[str]) -> int:
    if not qualified_dates:
        return 0
    day = max(date.fromisoformat(d) for d in qualified_dates)
    streak = 0
    while day.isoformat() in qualified_dates:
        streak += 1
        day -= timedelta(days=1)
    return streak


async def _credit_streak(user_id: str, day_str: str) -> Dict:
    raw = await _get_streak_raw(user_id)
    dates: Set[str] = set(raw["qualified_dates"])
    dates.add(day_str)
    raw["qualified_dates"] = sorted(dates)
    raw["current_streak"] = _recompute_current_streak(dates)
    raw["longest_streak"] = max(raw["longest_streak"], raw["current_streak"])
    await kv_store.store.update(STREAKS_NS, user_id, raw)
    return raw


# ── challenge lifecycle ──────────────────────────────────────────────────────
async def _start_challenge(user_id: str, req: StartChallengeRequest) -> StartChallengeResponse:
    session_id = _new_id("dchal")
    now = _now()
    session = {
        "session_id": session_id, "user_id": user_id, "started_at": now,
        "turns": [], "status": "active", "dispute_status": DisputeStatus.NONE,
        "completed_at": None, "quality_score": None, "pattern": None,
    }
    await kv_store.store.create(SESSIONS_NS, session_id, session)
    return StartChallengeResponse(session_id=session_id, user_id=user_id, started_at=now)


async def _add_turn(user_id: str, session_id: str, audio_bytes: bytes) -> ChallengeTurnResponse:
    session = await _get_session(user_id, session_id)
    if session["status"] != "active":
        raise InvalidSubmissionError("Session is no longer active")

    config = load_speech_config()
    max_bytes = config.daily_challenge_max_upload_mb * 1024 * 1024
    if len(audio_bytes) > max_bytes:
        raise UploadTooLargeError(f"Recording exceeds the {config.daily_challenge_max_upload_mb}MB limit")
    try:
        analysis = recording_engine.analyze_recording(audio_bytes, config)
    except AudioDecodeError as e:
        raise UnreadableAudioError(str(e))

    # E-04: real speaker-consistency heuristic (background TV/media -> multiple
    # pitch-discontinuous voiced runs), the same one accent assessment uses for
    # MULTIPLE_VOICES_DETECTED — not a client-supplied flag.
    non_interactive = prosody_engine.detect_multiple_voices(analysis.prosody, config)

    session["turns"].append({
        "text": analysis.transcript or "",
        "non_interactive_audio_signal": non_interactive,
        "created_at": _now(),
    })
    await kv_store.store.update(SESSIONS_NS, session_id, session)
    return ChallengeTurnResponse(session_id=session_id, turn_count=len(session["turns"]))


def _evaluate(session: Dict, now: datetime):
    duration_seconds = (now - session["started_at"]).total_seconds()
    turn_count = len(session["turns"])
    duration_ok = duration_seconds >= DAILY_CHALLENGE_MIN_DURATION_SECONDS and turn_count >= DAILY_CHALLENGE_MIN_TURNS

    signals = [
        TurnSignal(text=t["text"], non_interactive_audio_signal=t["non_interactive_audio_signal"])
        for t in session["turns"]
    ]
    quality = score_engagement_quality(signals)

    if quality.pattern == NON_INTERACTIVE_AUDIO:
        return ChallengeStatus.REJECTED_NON_INTERACTIVE, quality, NON_INTERACTIVE_REJECTION_MESSAGE
    if duration_ok and quality.pattern is None and quality.quality >= DAILY_CHALLENGE_MIN_QUALITY_SCORE:
        return ChallengeStatus.QUALIFIED, quality, None
    if duration_ok:  # duration/turns met, but content quality failed (E-02)
        return ChallengeStatus.INCOMPLETE_LOW_ENGAGEMENT, quality, LOW_ENGAGEMENT_NUDGE_MESSAGE
    return ChallengeStatus.INCOMPLETE_DURATION, quality, INCOMPLETE_DURATION_MESSAGE


async def _complete_challenge(user_id: str, req: CompleteChallengeRequest) -> CompleteChallengeResponse:
    session = await _get_session(user_id, req.session_id)
    if session["status"] != "active":
        raise InvalidSubmissionError("Session already completed")

    now = _now()
    status, quality, message = _evaluate(session, now)

    session["status"] = "completed"
    session["completed_at"] = now
    session["quality_score"] = quality.quality
    session["pattern"] = quality.pattern
    session["challenge_status"] = status
    await kv_store.store.update(SESSIONS_NS, req.session_id, session)

    milestone_days: Optional[int] = None
    milestone_message: Optional[str] = None
    streak = await _get_streak_raw(user_id)
    if status == ChallengeStatus.QUALIFIED:
        streak = await _credit_streak(user_id, _date_str(now))
        if streak["current_streak"] in STREAK_MILESTONE_DAYS:
            milestone_days = streak["current_streak"]
            milestone_message = build_milestone_message(milestone_days)
            await notification_service.notify_milestone(user_id, milestone_days, live_session=True, now=now)

    # Completing a challenge is activity — feed the shared continuous-usage tracker
    # (US-170) so overuse nudges stay accurate across features (E-04 ordering).
    heartbeat = await overuse_service._record_heartbeat(user_id, now=now)

    return CompleteChallengeResponse(
        session_id=req.session_id, status=status,
        current_streak=streak["current_streak"], longest_streak=streak["longest_streak"],
        quality_score=quality.quality, pattern=quality.pattern, message=message,
        milestone_days=milestone_days, milestone_message=milestone_message,
        overuse_nudge=heartbeat.nudge,
    )


# ── dispute / review (E-03) ───────────────────────────────────────────────────
async def _dispute_session(user_id: str, req: DisputeSessionRequest) -> DisputeSessionResponse:
    session = await _get_session(user_id, req.session_id)
    if session["challenge_status"] != ChallengeStatus.INCOMPLETE_LOW_ENGAGEMENT:
        raise InvalidSubmissionError("Only low-engagement sessions can be disputed")
    session["dispute_status"] = DisputeStatus.PENDING
    await kv_store.store.update(SESSIONS_NS, req.session_id, session)
    return DisputeSessionResponse(
        session_id=req.session_id, dispute_status=DisputeStatus.PENDING,
        message="Session flagged for review.",
    )


async def _review_session(req: ReviewSessionRequest) -> ReviewSessionResponse:
    """Admin/support action: resolves a disputed session. Confirmed-genuine sessions
    are retroactively credited to the streak using the ORIGINAL session date, not
    today's date."""
    raw_session = await kv_store.store.get(SESSIONS_NS, req.session_id)
    if raw_session is None:
        raise SessionNotFoundError(f"No daily challenge session {req.session_id} found")
    if raw_session["dispute_status"] != DisputeStatus.PENDING:
        raise InvalidSubmissionError("Session has no pending dispute")

    user_id = raw_session["user_id"]
    if req.confirmed_genuine:
        raw_session["challenge_status"] = ChallengeStatus.QUALIFIED_RETROACTIVE
        raw_session["dispute_status"] = DisputeStatus.RESOLVED_GENUINE
        streak = await _credit_streak(user_id, _date_str(raw_session["completed_at"]))
        message = DISPUTE_CONFIRMED_MESSAGE
    else:
        raw_session["dispute_status"] = DisputeStatus.RESOLVED_DENIED
        streak = await _get_streak_raw(user_id)
        message = DISPUTE_DENIED_MESSAGE
    await kv_store.store.update(SESSIONS_NS, req.session_id, raw_session)

    return ReviewSessionResponse(
        session_id=req.session_id, dispute_status=raw_session["dispute_status"],
        status=raw_session["challenge_status"], current_streak=streak["current_streak"],
        longest_streak=streak["longest_streak"], message=message,
    )


async def _get_streak(user_id: str) -> StreakResponse:
    raw = await _get_streak_raw(user_id)
    return StreakResponse(
        user_id=user_id, current_streak=raw["current_streak"],
        longest_streak=raw["longest_streak"], qualified_dates=raw["qualified_dates"],
    )


# ── controllers (auth-gated) ────────────────────────────────────────────────
async def start_challenge(payload: StartChallengeRequest, user_id: str = Depends(require_auth)):
    return await _start_challenge(user_id, payload)


async def add_turn(
    session_id: str = Form(...),
    audio: UploadFile = File(...),
    user_id: str = Depends(require_auth),
):
    audio_bytes = await audio.read()
    return await _add_turn(user_id, session_id, audio_bytes)


async def complete_challenge(payload: CompleteChallengeRequest, user_id: str = Depends(require_auth)):
    return await _complete_challenge(user_id, payload)


async def dispute_session(payload: DisputeSessionRequest, user_id: str = Depends(require_auth)):
    return await _dispute_session(user_id, payload)


async def review_session(payload: ReviewSessionRequest, _admin_id: str = Depends(require_admin)):
    return await _review_session(payload)


async def get_streak(user_id: str = Depends(require_auth)):
    return await _get_streak(user_id)


# ── PDG-US-11 status + PDG-US-13 in-app reminder (merged from the streak feature) ─────
# These read the SAME kv streak store the US-168 flow above writes (STREAKS_NS via
# _get_streak_raw) — the parallel User.currentStreak columns from the other branch are NOT
# used, so streak state has one source of truth.
NOTIFY_HOUR = 18  # 6:00 PM local — PDG-US-13 trigger


def _parse_local_date(d: str) -> Optional[date]:
    try:
        return date.fromisoformat(d)
    except (ValueError, TypeError):
        return None


def _next_milestone(streak: int) -> Optional[int]:
    for d in STREAK_MILESTONE_DAYS:
        if streak < d:
            return d
    return None


def _streak_view(raw: Dict, today: date):
    """Derive (completed_today, alive_streak) from the kv streak's qualified_dates."""
    qualified = set(raw.get("qualified_dates", []))
    completed_today = today.isoformat() in qualified
    alive = completed_today or (today - timedelta(days=1)).isoformat() in qualified
    return completed_today, (raw.get("current_streak", 0) if alive else 0)


async def get_challenge_status(local_date: str, user_id: str = Depends(require_auth)):
    """PDG-US-11 status for the dashboard card / navbar streak icon."""
    today = _parse_local_date(local_date)
    if today is None:
        return JSONResponse(status_code=400, content={"error": "Invalid local_date"})
    raw = await _get_streak_raw(user_id)
    completed_today, current = _streak_view(raw, today)
    longest = raw.get("longest_streak", 0)
    return {
        "completed_today": completed_today,
        "current_streak": current,
        "longest_streak": longest,
        "badges": [d for d in STREAK_MILESTONE_DAYS if longest >= d],
        "next_milestone": _next_milestone(current),
        "required_minutes": DAILY_CHALLENGE_MIN_DURATION_SECONDS // 60,
    }


async def get_notification(local_date: str, local_hour: int, user_id: str = Depends(require_auth)):
    """PDG-US-13 in-app Streak-Warning decision: not done today, past 6 PM local, live streak."""
    today = _parse_local_date(local_date)
    if today is None:
        return JSONResponse(status_code=400, content={"error": "Invalid local_date"})
    raw = await _get_streak_raw(user_id)
    completed_today, streak = _streak_view(raw, today)
    show = (not completed_today) and local_hour >= NOTIFY_HOUR and streak > 0
    message = (
        f"Don't lose your {streak}-day streak! 5 minutes of practice is all it takes."
        if show
        else None
    )
    return {"show_streak_warning": show, "current_streak": streak, "message": message}
