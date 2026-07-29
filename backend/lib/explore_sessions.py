"""
Cross-feature "unfinished session" guard + discovery for the four practice modes
reachable from the Explore page (AI Conversation, Scenario-Based Learning,
Workplace Coaching, Interview Coach). Fixes a real gap: each feature's own
`start_session` created a brand-new session unconditionally, so a user who
navigated away mid-session (to any *other* Explore-group feature) just silently
orphaned the old in-progress row and could pile up any number of open sessions.

Two operations, mirroring the one place in this codebase that already solved this
exact problem correctly (pronunciation_coach_service._start_session's "a fresh
start supersedes any session this user still has open elsewhere"):

- `supersede_open_explore_sessions(user_id)` — call at the top of every Explore-group
  start_session, before creating the new row. Marks any other still-open session
  (any of the 4 types) as abandoned, so starting something new never leaves a
  second one silently running.
- `find_open_explore_session(user_id)` — used by the Explore page to show a resume
  banner *before* the user picks something new, so superseding only ever happens
  when they deliberately choose to (the banner offers Resume vs. Start Something
  New; superseding is what "Start Something New" quietly relies on).

Each feature keeps its own status vocabulary (no shared enum) — this module just
knows what "open" and "terminal" mean for each one.
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional

from lib import kv_store, prompts
from lib.prisma_client import db
from prisma.enums import CoachingStatus

CONVERSATION_NS = "conversation_sessions"
INTERVIEW_COACH_NS = "interview_coach_sessions"


async def _is_db_connected() -> bool:
    """Same guard used by accent_tracker_service/progress_dashboard_service/etc —
    lets this module's KV-only callers (conversation, interview coach) stay
    network-free in tests that never connect Postgres, without special-casing
    each caller. Always true in production (db.connect() runs at app startup)."""
    try:
        return db.is_connected()
    except Exception:
        return False


def _topic_label(session: Dict) -> str:
    if session.get("custom_topic"):
        return session["custom_topic"]
    return prompts.TOPICS.get(session.get("topic_key"), session.get("topic_key", "Conversation"))


# ── Engagement gates ────────────────────────────────────────────────────────────
# A session that was merely *created* (landing on the page auto-starts one, or a
# "Start" click fired the opening AI line) isn't something worth resuming — the
# learner hasn't actually done anything yet. Without this, visiting a section and
# immediately leaving marks it "resumable" and the prompt follows you around
# forever (each visit/"Start Fresh" just creates another empty one). "Engaged"
# means at least one real learner turn/answer/attempt exists.
def _conversation_engaged(session: Dict) -> bool:
    return len(session.get("turns") or []) > 1  # index 0 is always the AI opening line


def _interview_coach_engaged(session: Dict) -> bool:
    return any(ex.get("answer") for ex in (session.get("exchanges") or []))


async def _latest_raw_conversation(user_id: str) -> Optional[Dict]:
    sessions = [
        s for s in await kv_store.store.list_values(CONVERSATION_NS)
        if s.get("user_id") == user_id and s.get("status") == "active"
    ]
    return max(sessions, key=lambda s: s["started_at"]) if sessions else None


async def _latest_raw_interview_coach(user_id: str) -> Optional[Dict]:
    sessions = [
        s for s in await kv_store.store.list_values(INTERVIEW_COACH_NS)
        if s.get("user_id") == user_id and s.get("status") in ("active", "paused")
    ]
    return max(sessions, key=lambda s: s["started_at"]) if sessions else None


async def _open_conversation(user_id: str) -> Optional[Dict]:
    latest = await _latest_raw_conversation(user_id)
    if not latest or not _conversation_engaged(latest):
        return None
    return {
        "feature": "conversation", "session_id": latest["session_id"],
        "label": _topic_label(latest), "resume_path": f"/dashboard/conversation/{latest['session_id']}",
        "started_at": latest["started_at"],
    }


async def _open_scenario(user_id: str) -> Optional[Dict]:
    if not await _is_db_connected():
        return None
    row = await db.scenariosession.find_first(
        where={"userId": user_id, "status": "in_progress"}, order={"createdAt": "desc"}
    )
    if not row or len(row.turns) <= 1:  # index 0 is always the AI opening line
        return None
    return {
        "feature": "scenario", "session_id": row.id, "scenario_key": row.scenarioKey,
        "label": None,  # frontend resolves the pretty label via getScenarioDetail(scenario_key)
        "resume_path": f"/dashboard/scenarios/{row.scenarioKey}?resume={row.id}",
        "started_at": row.createdAt,
    }


async def _open_coaching(user_id: str) -> Optional[Dict]:
    if not await _is_db_connected():
        return None
    row = await db.coachingsession.find_first(
        where={"userId": user_id, "status": CoachingStatus.IN_PROGRESS}, order={"createdAt": "desc"}
    )
    if not row:
        return None
    scenario_key = str(row.scenario).lower()
    meta = prompts.WORKPLACE_SCENARIOS.get(scenario_key, {})
    # Draft-type scenarios (email_writing, presentation_prep, general_workplace) never
    # persist partial progress server-side — the draft text lives only in the browser
    # until final submit — so there's nothing real to resume; only roleplay sessions
    # with an actual back-and-forth are ever "open".
    if not meta.get("roleplay") or len(row.turns) <= 1:
        return None
    return {
        "feature": "coaching", "session_id": row.id, "scenario_key": scenario_key,
        "label": None,  # frontend resolves via getCoachingScenarios()
        "resume_path": f"/dashboard/coaching/{scenario_key}?resume={row.id}",
        "started_at": row.createdAt,
    }


async def _open_interview_coach(user_id: str) -> Optional[Dict]:
    latest = await _latest_raw_interview_coach(user_id)
    if not latest or not _interview_coach_engaged(latest):
        return None
    return {
        "feature": "interview_coach", "session_id": latest["session_id"],
        "label": f"{latest.get('mode', 'Interview')} interview".replace("_", " ").title(),
        "resume_path": f"/dashboard/interview-coach/{latest['session_id']}",
        "started_at": latest["started_at"],
    }


async def find_open_explore_session(user_id: str) -> Optional[Dict]:
    """Returns the single most recently started open session across all 4 Explore
    features, or None. There should only ever be one at a time once the supersede
    guard is in place everywhere, but this is defensive against pre-existing rows."""
    candidates: List[Dict] = []
    for finder in (_open_conversation, _open_scenario, _open_coaching, _open_interview_coach):
        found = await finder(user_id)
        if found:
            candidates.append(found)
    if not candidates:
        return None
    latest = max(candidates, key=lambda c: c["started_at"])
    latest["started_at"] = latest["started_at"].isoformat()
    return latest


async def supersede_open_explore_sessions(user_id: str) -> None:
    """Cleanup uses the RAW (un-gated) finders, not the engagement-gated ones above —
    an empty/unengaged session still needs to be superseded when something new
    starts, even though it never counted as "resumable" for display purposes."""
    now = datetime.now(timezone.utc)

    conv = await _latest_raw_conversation(user_id)
    if conv:
        session = await kv_store.store.get(CONVERSATION_NS, conv["session_id"])
        if session:
            session["status"] = "abandoned"
            session["completed_at"] = now
            await kv_store.store.update(CONVERSATION_NS, conv["session_id"], session)

    if await _is_db_connected():
        await db.scenariosession.update_many(
            where={"userId": user_id, "status": "in_progress"},
            data={"status": "ended_early", "completedAt": now},
        )

        await db.coachingsession.update_many(
            where={"userId": user_id, "status": CoachingStatus.IN_PROGRESS},
            data={"status": CoachingStatus.ENDED_EARLY, "completedAt": now},
        )

    ic = await _latest_raw_interview_coach(user_id)
    if ic:
        session = await kv_store.store.get(INTERVIEW_COACH_NS, ic["session_id"])
        if session:
            session["status"] = "abandoned"
            session["ended_at"] = now
            await kv_store.store.update(INTERVIEW_COACH_NS, ic["session_id"], session)
