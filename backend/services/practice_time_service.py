"""
Practice Time Milestones — PDG-US-15.

Lifetime practice time is credited incrementally via 60-second heartbeat
pings from an active session (Scenario-Based Learning, AI Conversation,
Workplace Coaching, Interview Coach, Public Speaking — see
schemas.practice_time_schemas.ALLOWED_SESSION_TYPES), not from a session's
wall-clock createdAt/completedAt span. This gives the exception handling for free:

- E-01 (app crash mid-session): each ping already credited its slice before
  the crash, so partial time survives regardless of whether the session ever
  reaches end_session.
- E-02 (concurrent cross-device sessions): the KvEntry-backed "active
  session" registration only credits the session already registered as
  primary; a second session pinging concurrently is rejected.
- E-03 (silent/zero-input session): a session that never pings never credits
  anything, so a silently-abandoned session contributes 0 minutes.
"""

import logging
from datetime import datetime, timezone
from typing import Dict, List

from fastapi import Depends

from lib import kv_store
from lib.prisma_client import db
from middlewares.auth_middleware import require_auth
from schemas.practice_time_schemas import PracticeTimePingSchema

logger = logging.getLogger(__name__)

# Spaced logarithmically per the story's own example (1h, 5h, 10h, 50h, ...).
MILESTONE_HOURS = [1, 5, 10, 50, 100, 250, 500]

ACTIVE_SESSION_NAMESPACE = "practice_time_active_session"
STALE_AFTER_SECONDS = 90  # > the 60s ping cadence, so one missed beat isn't fatal
PING_CREDIT_CAP_SECONDS = 60.0  # never credit more than one ping interval at a time


def _is_stale(active: Dict, now: datetime) -> bool:
    return (now - active["last_ping_at"]).total_seconds() > STALE_AFTER_SECONDS


def _is_same_session(active: Dict, session_type: str, session_id: str) -> bool:
    return active["session_type"] == session_type and active["session_id"] == session_id


def _badge_label(hours: int) -> str:
    return f"You've spoken English for {hours} Hour{'s' if hours != 1 else ''}!"


def _check_milestones(unlocked_hours: List[int], total_seconds: float) -> Dict:
    total_hours = total_seconds / 3600
    already = set(unlocked_hours)
    newly_unlocked = [h for h in MILESTONE_HOURS if h not in already and total_hours >= h]
    updated = sorted(already | set(newly_unlocked))
    return {
        "newly_unlocked": [{"hours": h, "message": _badge_label(h)} for h in newly_unlocked],
        "updated_unlocked_hours": updated,
    }


# ── Controllers ───────────────────────────────────────────────────────────────
async def ping_practice_time(
    payload: PracticeTimePingSchema, user_id: str = Depends(require_auth)
):
    session_type, session_id = payload.session_type, payload.session_id
    now = datetime.now(timezone.utc)
    active = await kv_store.store.get(ACTIVE_SESSION_NAMESPACE, user_id)

    if active and not _is_stale(active, now) and not _is_same_session(active, session_type, session_id):
        # E-02: another session is already the credited primary for this user.
        return {
            "credited_seconds": 0.0,
            "is_primary_session": False,
            "lifetime_hours": None,
            "newly_unlocked": [],
        }

    credited = 0.0
    if active and not _is_stale(active, now) and _is_same_session(active, session_type, session_id):
        elapsed = (now - active["last_ping_at"]).total_seconds()
        credited = max(0.0, min(elapsed, PING_CREDIT_CAP_SECONDS))

    new_registration = {
        "user_id": user_id,
        "session_type": session_type,
        "session_id": session_id,
        "last_ping_at": now,
    }
    if active is None:
        await kv_store.store.create(ACTIVE_SESSION_NAMESPACE, user_id, new_registration)
    else:
        await kv_store.store.update(ACTIVE_SESSION_NAMESPACE, user_id, new_registration)

    if credited <= 0:
        return {
            "credited_seconds": 0.0,
            "is_primary_session": True,
            "lifetime_hours": None,
            "newly_unlocked": [],
        }

    # Atomic increment — the database adds the credit, so two pings that interleave can
    # never lose time. A read-modify-write here dropped concurrent updates (measured: 10
    # parallel +10s credits landed 40s instead of 100s), because each request read the
    # same stale total before any of them wrote back.
    updated = await db.user.update(
        where={"id": user_id},
        data={"lifetimePracticeSeconds": {"increment": credited}},
    )
    new_total = updated.lifetimePracticeSeconds

    # Milestones are derived from the authoritative post-increment total and the set is
    # idempotent, so a concurrent ping can't double-award or skip a badge.
    milestones = _check_milestones(updated.unlockedMilestoneHours, new_total)
    if milestones["newly_unlocked"]:
        await db.user.update(
            where={"id": user_id},
            data={"unlockedMilestoneHours": milestones["updated_unlocked_hours"]},
        )

    return {
        "credited_seconds": round(credited, 1),
        "is_primary_session": True,
        "lifetime_hours": round(new_total / 3600, 2),
        "newly_unlocked": milestones["newly_unlocked"],
    }


async def get_trophy_case(user_id: str = Depends(require_auth)):
    user = await db.user.find_unique(where={"id": user_id})
    total_hours = user.lifetimePracticeSeconds / 3600
    unlocked = sorted(user.unlockedMilestoneHours)
    next_milestone = next((h for h in MILESTONE_HOURS if h not in unlocked), None)
    progress_to_next = round(min(1.0, total_hours / next_milestone), 4) if next_milestone else 1.0

    return {
        "lifetime_hours": round(total_hours, 2),
        "unlocked_milestone_hours": unlocked,
        "trophies": [{"hours": h, "message": _badge_label(h)} for h in unlocked],
        "next_milestone_hours": next_milestone,
        "progress_to_next": progress_to_next,
    }
