"""
Cross-feature "Recent Activity" feed for the Learner Dashboard — the last few
things a learner actually did, across every practice mode (Scenario, AI
Conversation, Pronunciation Coach, Interview Coach, Accent Assessment), most
recent first.

Mirrors lib/explore_sessions.py's per-feature finder pattern (same engagement
gates: a session that was auto-created but never touched isn't "activity"),
but surfaces ALL recent sessions (any status), not just open/resumable ones.
"""

from datetime import datetime, timezone
from typing import Dict, List

from lib import explore_sessions, kv_store
from lib.prisma_client import db
from prisma.enums import AccentAssessmentStatus

PRONUNCIATION_NS = "pronunciation_sessions"  # pronunciation_coach_service.NAMESPACE

_CONVERSATION_STATUS = {"active": "in_progress", "completed": "completed", "abandoned": "ended_early"}
_INTERVIEW_STATUS = {"active": "in_progress", "paused": "in_progress", "completed": "completed", "abandoned": "ended_early"}
_PRONUNCIATION_STATUS = {"active": "in_progress", "interrupted": "in_progress", "completed": "completed"}


async def _recent_scenarios(user_id: str, limit: int) -> List[Dict]:
    if not await explore_sessions._is_db_connected():
        return []
    from services.scenario_service import scenario_meta  # avoid import cycle at module load

    rows = await db.scenariosession.find_many(
        where={"userId": user_id}, order={"createdAt": "desc"}, take=limit * 2,
    )
    items = []
    for row in rows:
        if len(row.turns) <= 1:  # never actually engaged with — see explore_sessions._open_scenario
            continue
        meta = row.scenarioMeta or await scenario_meta(row.scenarioKey)
        meta = meta or {}
        items.append({
            "type": "scenario",
            "activity_id": row.id,
            "title": meta.get("label", row.scenarioKey),
            "subtitle": meta.get("category", "Scenario"),
            "status": row.status,
            "score": row.confidenceScore,
            "score_label": "confidence",
            "occurred_at": row.completedAt or row.createdAt,
            "href": (
                f"/dashboard/scenarios/{row.scenarioKey}?resume={row.id}"
                if row.status == "in_progress"
                else f"/dashboard/scenarios/{row.scenarioKey}"
            ),
        })
        if len(items) >= limit:
            break
    return items


async def _recent_conversations(user_id: str, limit: int) -> List[Dict]:
    sessions = [
        s for s in await kv_store.store.list_values(explore_sessions.CONVERSATION_NS)
        if s.get("user_id") == user_id and explore_sessions._conversation_engaged(s)
    ]
    sessions.sort(key=lambda s: s["started_at"], reverse=True)
    return [
        {
            "type": "conversation",
            "activity_id": s["session_id"],
            "title": explore_sessions._topic_label(s),
            "subtitle": "AI Conversation",
            "status": _CONVERSATION_STATUS.get(s.get("status"), "in_progress"),
            "score": None,
            "score_label": None,
            "occurred_at": s.get("completed_at") or s["started_at"],
            "href": f"/dashboard/conversation/{s['session_id']}",
        }
        for s in sessions[:limit]
    ]


async def _recent_pronunciation(user_id: str, limit: int) -> List[Dict]:
    sessions = [
        s for s in await kv_store.store.list_values(PRONUNCIATION_NS)
        if s.get("user_id") == user_id and s.get("attempts")
    ]
    sessions.sort(key=lambda s: s.get("last_active_at") or s["started_at"], reverse=True)
    items = []
    for s in sessions[:limit]:
        words = [w for a in s["attempts"] for w in a.get("words", [])]
        accuracy = round(100 * sum(1 for w in words if w["status"] == "correct") / len(words), 1) if words else None
        items.append({
            "type": "pronunciation",
            "activity_id": s["session_id"],
            "title": "Pronunciation Practice",
            "subtitle": "Pronunciation Coach",
            "status": _PRONUNCIATION_STATUS.get(s.get("status"), "in_progress"),
            "score": accuracy,
            "score_label": "accuracy",
            "occurred_at": s.get("ended_at") or s.get("last_active_at") or s["started_at"],
            "href": "/dashboard/pronunciation",
        })
    return items


async def _recent_interview_coach(user_id: str, limit: int) -> List[Dict]:
    sessions = [
        s for s in await kv_store.store.list_values(explore_sessions.INTERVIEW_COACH_NS)
        if s.get("user_id") == user_id and explore_sessions._interview_coach_engaged(s)
    ]
    sessions.sort(key=lambda s: s["started_at"], reverse=True)
    return [
        {
            "type": "interview_coach",
            "activity_id": s["session_id"],
            "title": f"{s.get('mode', 'Interview')} Interview".replace("_", " ").title(),
            "subtitle": "Interview Coach",
            "status": _INTERVIEW_STATUS.get(s.get("status"), "in_progress"),
            "score": None,
            "score_label": None,
            "occurred_at": s.get("ended_at") or s["started_at"],
            "href": f"/dashboard/interview-coach/{s['session_id']}",
        }
        for s in sessions[:limit]
    ]


async def _recent_accent_assessments(user_id: str, limit: int) -> List[Dict]:
    if not await explore_sessions._is_db_connected():
        return []
    rows = await db.accentassessment.find_many(
        where={"userId": user_id, "status": AccentAssessmentStatus.COMPLETED}, order={"createdAt": "desc"}, take=limit,
    )
    return [
        {
            "type": "accent",
            "activity_id": row.id,
            "title": "Accent Assessment",
            "subtitle": "Accent",
            "status": "completed",
            "score": row.pronunciationScore,
            "score_label": "pronunciation",
            "occurred_at": row.completedAt or row.createdAt,
            "href": "/dashboard/accent-assessment",
        }
        for row in rows
    ]


async def get_recent_activity(user_id: str, limit: int = 3) -> List[Dict]:
    """The learner's `limit` most recent practice activities across every feature,
    most recent first. Each source is asked for up to `limit` of its own so the
    final cross-feature merge never has to worry about a single feature hoarding
    every slot."""

    def _key(item: Dict):
        occurred = item["occurred_at"]
        if isinstance(occurred, str):
            occurred = datetime.fromisoformat(occurred)
        if occurred.tzinfo is None:
            occurred = occurred.replace(tzinfo=timezone.utc)
        return occurred

    candidates: List[Dict] = []
    for fetch in (
        _recent_scenarios, _recent_conversations, _recent_pronunciation,
        _recent_interview_coach, _recent_accent_assessments,
    ):
        candidates.extend(await fetch(user_id, limit))

    candidates.sort(key=_key, reverse=True)
    top = candidates[:limit]
    for item in top:
        occurred = item["occurred_at"]
        item["occurred_at"] = occurred.isoformat() if hasattr(occurred, "isoformat") else occurred
    return top
