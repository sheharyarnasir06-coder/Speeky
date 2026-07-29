"""
Daily Challenge (PDG-US-11).

Redirects the learner into a real AI Conversation session on the topic that matches
their signup learning goal (users.learningGoal -> lib.prompts.GOAL_TOPIC_MAP), then
completes the challenge purely on elapsed time: the timer starts at the user's FIRST
prompt in that session (services.conversation_service._send_message calls
on_conversation_prompt below, best-effort, right after it), and the challenge qualifies
once 5 minutes have passed — checked by the frontend polling
get_conversation_challenge_status as the conversation continues. There is no
turn-count/audio-quality gate: the conversation's own guardrails (rate limiting,
gibberish-strike cutoff, PII redaction) are the anti-gaming layer, since the user is
having a real scored conversation rather than uploading disposable audio clips.

Streak bookkeeping (_get_streak_raw/_streak_view) is the one source of truth other
features read from — progress_dashboard_service.get_daily_streak_days and
notification_service both go through it — so those two stay stable across this rewrite.
"""

from datetime import date, datetime, timedelta, timezone
from typing import Dict, Optional, Set

from fastapi import Depends
from fastapi.responses import JSONResponse

from lib import kv_store
from lib.prompts import DAILY_CHALLENGE_MIN_DURATION_SECONDS, GOAL_TOPIC_MAP, STREAK_MILESTONE_DAYS, build_milestone_message
from middlewares.auth_middleware import require_auth
from schemas.conversation_schemas import StartConversationSchema
from schemas.daily_challenge_schemas import (
    ChallengeConversationStatusResponse,
    ChallengeStatus,
    StartChallengeRequest,
    StartChallengeResponse,
    StreakResponse,
)
from services import overuse_service
from utils.feature_errors import SessionNotFoundError

STREAKS_NS = "daily_challenge_streaks"
LINKS_NS = "daily_challenge_links"  # keyed by the linked conversation session_id


def _now() -> datetime:
    return datetime.now(timezone.utc)


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
    from lib.prisma_client import db
    from services import conversation_service

    user = await db.user.find_unique(where={"id": user_id})
    topic_key = GOAL_TOPIC_MAP.get(user.learningGoal if user else None, "daily_life")

    conv = await conversation_service._start_session(
        user_id, StartConversationSchema(topic_key=topic_key)
    )

    streak = await _get_streak_raw(user_id)
    already_completed_today = req.local_date in set(streak["qualified_dates"])

    link = {
        "session_id": conv["session_id"], "user_id": user_id,
        "local_date": req.local_date, "first_prompt_at": None,
        "completed": already_completed_today,
    }
    await kv_store.store.create(LINKS_NS, conv["session_id"], link)

    return StartChallengeResponse(
        session_id=conv["session_id"], topic_key=conv["topic_key"],
        topic_label=conv["topic_label"], opening_message=conv["opening_message"],
        already_completed_today=already_completed_today,
    )


async def on_conversation_prompt(user_id: str, session_id: str, now: Optional[datetime] = None) -> None:
    """Called by conversation_service._send_message right after it stores the user's
    turn, best-effort (never raises into the conversation flow). Starts this challenge's
    timer on the FIRST prompt only — later prompts in the same session are a no-op."""
    link = await kv_store.store.get(LINKS_NS, session_id)
    if link is None or link["user_id"] != user_id or link["completed"]:
        return
    if link["first_prompt_at"] is None:
        link["first_prompt_at"] = now or _now()
        await kv_store.store.update(LINKS_NS, session_id, link)


async def _get_conversation_challenge_status(
    user_id: str, session_id: str, local_date: str
) -> ChallengeConversationStatusResponse:
    link = await kv_store.store.get(LINKS_NS, session_id)
    if link is None or link["user_id"] != user_id:
        raise SessionNotFoundError(f"No daily challenge linked to conversation session {session_id}")

    streak = await _get_streak_raw(user_id)

    if link["completed"]:
        return ChallengeConversationStatusResponse(
            session_id=session_id, status=ChallengeStatus.QUALIFIED, just_completed=False,
            seconds_remaining=0, current_streak=streak["current_streak"],
            longest_streak=streak["longest_streak"],
        )

    if link["first_prompt_at"] is None:
        return ChallengeConversationStatusResponse(
            session_id=session_id, status=ChallengeStatus.PENDING, just_completed=False,
            seconds_remaining=DAILY_CHALLENGE_MIN_DURATION_SECONDS,
            current_streak=streak["current_streak"], longest_streak=streak["longest_streak"],
        )

    now = _now()
    elapsed = (now - link["first_prompt_at"]).total_seconds()
    remaining = DAILY_CHALLENGE_MIN_DURATION_SECONDS - elapsed
    if remaining > 0:
        return ChallengeConversationStatusResponse(
            session_id=session_id, status=ChallengeStatus.PENDING, just_completed=False,
            seconds_remaining=int(remaining), current_streak=streak["current_streak"],
            longest_streak=streak["longest_streak"],
        )

    # Crossed the 5-minute mark on this poll — credit once, using the LOCAL date the
    # challenge STARTED on (link["local_date"], set at /start), not the date it happens
    # to be credited on, so a session that began just before midnight still counts for
    # the day it began (E-02).
    link["completed"] = True
    await kv_store.store.update(LINKS_NS, session_id, link)

    streak = await _credit_streak(user_id, link["local_date"])
    milestone_days: Optional[int] = None
    milestone_message: Optional[str] = None
    if streak["current_streak"] in STREAK_MILESTONE_DAYS:
        milestone_days = streak["current_streak"]
        milestone_message = build_milestone_message(milestone_days)
        from services import notification_service

        await notification_service.notify_milestone(user_id, milestone_days, live_session=True, now=now)

    # Completing a challenge is activity — feed the shared continuous-usage tracker
    # (US-170) so overuse nudges stay accurate across features.
    heartbeat = await overuse_service._record_heartbeat(user_id, now=now)

    return ChallengeConversationStatusResponse(
        session_id=session_id, status=ChallengeStatus.QUALIFIED, just_completed=True,
        seconds_remaining=0, current_streak=streak["current_streak"],
        longest_streak=streak["longest_streak"], milestone_days=milestone_days,
        milestone_message=milestone_message, overuse_nudge=heartbeat.nudge,
    )


async def _get_streak(user_id: str) -> StreakResponse:
    raw = await _get_streak_raw(user_id)
    return StreakResponse(
        user_id=user_id, current_streak=raw["current_streak"],
        longest_streak=raw["longest_streak"], qualified_dates=raw["qualified_dates"],
    )


# ── controllers (auth-gated) ────────────────────────────────────────────────
async def start_challenge(payload: StartChallengeRequest, user_id: str = Depends(require_auth)):
    from services import conversation_service

    gate = await conversation_service._require_access(user_id)  # same gate AI Conversation itself uses
    if gate is not None:
        return gate
    return await _start_challenge(user_id, payload)


async def get_conversation_challenge_status(
    session_id: str, local_date: str, user_id: str = Depends(require_auth)
):
    return await _get_conversation_challenge_status(user_id, session_id, local_date)


async def get_streak(user_id: str = Depends(require_auth)):
    return await _get_streak(user_id)


# ── PDG-US-11 status + PDG-US-13 in-app reminder ─────────────────────────────
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
