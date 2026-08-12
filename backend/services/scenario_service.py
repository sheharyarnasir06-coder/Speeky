"""
Scenario-Based Learning — SBL-US-01 .. SBL-US-11.

Persona-driven roleplay practice across 9 built-in real-world scenarios (restaurant,
airport, customer support, business meeting, doctor's appointment, apartment hunting,
public transportation, academic office hours, casual networking) plus admin-authored
custom scenarios (SBL-US-06).

Deliberately structured like coaching_service.py:
  * Pure, DB-free helpers (_classify_turn / _vocab_coverage / offline grading) hold the
    exception-handling rules and are unit-tested directly.
  * _roleplay_reply calls Groq (lib/llm_client) for in-character dialogue and grading,
    falling back to deterministic offline behaviour when Groq is unavailable.
  * The FastAPI controllers at the bottom are thin: gate access, persist ScenarioSession
    rows, and delegate to the helpers.

MVP scope note: text-only (no live mic capture exists anywhere in this app yet — see
plan doc); no code-switch detector; silence/rambling are approximated from message
length rather than real-time audio timers. See services.coaching_service for the
aggression phrase bank reused here.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from fastapi import Depends, WebSocket
from fastapi.responses import JSONResponse
from prisma import Json

from lib import explore_sessions, llm_client, prompts, relevance, voice_ws
from lib.prisma_client import db
from middlewares.auth_middleware import require_admin, require_auth, ws_require_auth
from schemas.scenario_schemas import (
    CustomScenarioSchema,
    ScenarioPreviewSchema,
    ScenarioTurnSchema,
    StartScenarioSchema,
)
from services import content_scoring_service, deployment_confidence_service
from services.category_service import valid_category_names
from services.coaching_service import _AGGRESSIVE, _find_phrases

logger = logging.getLogger(__name__)

# Exception-handling thresholds
SILENCE_MIN_CHARS = 3        # shorter than this ⇒ treated as "didn't really answer"
RAMBLING_WORD_COUNT = 150    # longer than this ⇒ flagged as rambling
SILENCE_STREAK_LIMIT = 3     # 2 nudges, then the 3rd consecutive silent/idle turn auto-closes
AGGRESSION_STREAK_LIMIT = 2  # 1 warning, then the 2nd consecutive aggressive/cursing turn ends it

_EMERGENCY_PHRASES = [
    "heart attack", "can't breathe", "cannot breathe", "i'm dying", "im dying",
    "chest pain", "call an ambulance", "emergency", "suicidal", "kill myself",
]

# _AGGRESSIVE catches accusatory phrasing ("you failed", "unacceptable");
# it has no actual swear words, so cursing needs its own bank.
_PROFANITY = [
    "fuck", "fucking", "shit", "bullshit", "bitch", "asshole", "bastard", "damn you",
    "screw you", "piss off", "shut the hell up", "go to hell", "moron", "prick", "scumbag", "ass"
]

_POLITE_MARKERS = ["please", "could i", "could you", "would you mind", "thank you", "thanks"]
_RUDE_MARKERS = ["give me", "now.", "shut up", "whatever", "i don't care", "i dont care"]


def _is_medical_emergency(text: str) -> bool:
    lowered = f" {text.lower()} "
    return any(p in lowered for p in _EMERGENCY_PHRASES)


def _classify_turn(scenario_meta: Dict, message: str) -> str:
    """Generic exception classifier applied uniformly across all scenarios (mirrors
    interview_coach_service's answer classifier) rather than bespoke per-scenario code."""
    text = (message or "").strip()
    if scenario_meta.get("safety_mode") and _is_medical_emergency(text):
        return "emergency"
    if len(text) < SILENCE_MIN_CHARS:
        return "silence"
    lowered = f" {text.lower()} "
    if _find_phrases(lowered, _AGGRESSIVE) or _find_phrases(lowered, _PROFANITY):
        return "aggressive"
    if len(text.split()) > RAMBLING_WORD_COUNT:
        return "rambling"
    return "ok"


def _vocab_coverage(turns: List[Dict], target_vocab: List[str]) -> Dict[str, List[str]]:
    user_text = " ".join(t["content"] for t in turns if t.get("role") == "user").lower()
    used, missing = [], []
    for word in target_vocab:
        if word.lower() in user_text:
            used.append(word)
        else:
            missing.append(word)
    return {"used": used, "missing": missing}


def _offline_politeness(turns: List[Dict]) -> float:
    """Marker-count politeness, used ONLY for tip selection — never as a score.

    It used to start at 78.0 and adjust, so a learner who said nothing recognisable was
    graded "politely spoken" at 78. See `grade_session`: the graded politeness number now
    comes from the LLM or does not exist.
    """
    user_text = " ".join(t["content"] for t in turns if t.get("role") == "user").lower()
    score = 78.0
    for m in _POLITE_MARKERS:
        if m in user_text:
            score += 4.0
    for m in _RUDE_MARKERS:
        if m in user_text:
            score -= 12.0
    return round(max(0.0, min(100.0, score)), 2)


def _offline_tips(scenario_meta: Dict, turns: List[Dict], vocab_used: List[str], met_goal: bool) -> List[str]:
    """Deterministic 'tips' derivation from data already computed elsewhere — no LLM call,
    used both as the offline grader's tips and to backfill LLM tips that come back empty."""
    tips: List[str] = []
    missing = [w for w in scenario_meta.get("target_vocab", []) if w not in vocab_used]
    if missing:
        tips.append(f"Try working these words in next time: {', '.join(missing[:3])}.")
    politeness = _offline_politeness(turns)
    if politeness < 70:
        tips.append("Soften your phrasing — lead with \"Could I...\" or \"Would you mind...\" instead of blunt demands.")
    if scenario_meta.get("goal_type") == "negotiation" and not met_goal:
        tips.append("Don't accept the first answer — push back once more with a clear reason before settling.")
    if not tips:
        tips.append("Solid run — keep practicing to build consistency.")
    return tips[:3]


def ungraded_result(scenario_meta: Dict, turns: List[Dict], vocab_used: List[str]) -> Dict:
    """What comes back when the grader can't run: tips and vocabulary, but no politeness
    number and no verdict on the goal.

    This replaces `offline_grade`, which returned `politeness = _offline_politeness(...)`
    (base 78) and `met_goal = True` for every non-negotiation scenario — so an empty or
    hostile session was reported as polite and successful.
    """
    tips = _offline_tips(scenario_meta, turns, vocab_used, met_goal=False)
    return {
        "politeness": None,
        "met_goal": None,
        "summary": "Scoring is temporarily unavailable — your transcript is saved.",
        "suggestion": tips[0],
        "tips": tips,
        # Rewriting prose convincingly needs an LLM — offline mode skips it rather than faking one.
        "original_line": "",
        "polished_line": "",
        "_source": relevance.SOURCE_UNAVAILABLE,
    }


async def grade_session(scenario_meta: Dict, turns: List[Dict], vocab_used: List[str]) -> Dict:
    if not llm_client.is_configured():
        return ungraded_result(scenario_meta, turns, vocab_used)

    transcript = "\n".join(
        t["content"] for t in turns if t.get("role") == "user"
    )

    # Nothing worth grading — no LLM call, and no politeness score for silence.
    gate = relevance.evaluate_substance(transcript, scenario_meta.get("intent"))
    if gate.rejected:
        tips = _offline_tips(scenario_meta, turns, vocab_used, met_goal=False)
        return {
            "politeness": 0.0, "met_goal": False,
            "summary": "There wasn't enough here to grade — try working through the scenario in full.",
            "suggestion": tips[0], "tips": tips,
            "original_line": "", "polished_line": "", "_source": relevance.SOURCE_GATE,
        }

    grading_prompt = prompts.build_scenario_grading_prompt(scenario_meta, transcript, vocab_used)
    try:
        raw = await llm_client.chat_json(
            [{"role": "user", "content": grading_prompt}], temperature=0.2, max_tokens=500
        )
        politeness = relevance._clamp_score(raw.get("politeness"))
        if politeness is None:
            logger.warning("SBL grader returned no usable politeness: %r", raw)
            return ungraded_result(scenario_meta, turns, vocab_used)
        # Fail low: an omitted verdict is not a passing one.
        met_goal = bool(raw.get("met_goal", False))
        tips = [str(t).strip() for t in (raw.get("tips") or []) if str(t).strip()][:3]
        if not tips:
            tips = _offline_tips(scenario_meta, turns, vocab_used, met_goal)
        return {
            "politeness": politeness,
            "met_goal": met_goal,
            "summary": raw.get("summary", ""),
            "suggestion": raw.get("suggestion", "") or tips[0],
            "tips": tips,
            "original_line": raw.get("original_line", "") or "",
            "polished_line": raw.get("polished_line", "") or "",
            "_source": "llm",
        }
    except (llm_client.LLMError, TypeError, ValueError) as e:
        logger.warning("Groq SBL grading failed (%s); session will be reported ungraded", e)
        return ungraded_result(scenario_meta, turns, vocab_used)


# ── Scenario registry (built-in + admin custom) ────────────────────────────────
def _normalize_custom(row) -> Dict:
    return {
        "label": row.title,
        "category": row.category,
        "persona": row.persona,
        "intent": row.intent or row.systemPrompt[:160],
        "goal_type": row.goalType,
        "difficulty": row.difficulty,
        "safety_mode": row.safetyMode,
        "corporate_tone": row.corporateTone,
        "target_vocab": row.targetVocab,
        "opening_fallback": row.openingLine or f"Let's begin — {row.title}.",
        "instructions": row.systemPrompt,
        "status": row.status,
    }


async def list_scenarios() -> List[Dict]:
    # CM-US-04 E-03: archived scenarios never appear for learners starting a new
    # session — they stay in the DB only so already-in-progress sessions can finish.
    custom_rows = await db.customscenario.find_many(
        where={"status": "ACTIVE"}, order={"createdAt": "desc"}
    )
    items = [
        {"key": key, **meta} for key, meta in prompts.SBL_SCENARIOS.items()
    ] + [
        {"key": f"custom:{row.id}", **_normalize_custom(row)} for row in custom_rows
    ]
    return [
        {
            "key": it["key"],
            "label": it["label"],
            "category": it["category"],
            "persona": it["persona"],
            "intent": it["intent"],
            "goal_type": it["goal_type"],
            "target_vocab": it["target_vocab"],
        }
        for it in items
    ]


async def scenario_meta(scenario_key: str) -> Optional[Dict]:
    if scenario_key.startswith("custom:"):
        row = await db.customscenario.find_unique(where={"id": scenario_key.split(":", 1)[1]})
        return _normalize_custom(row) if row else None
    return prompts.SBL_SCENARIOS.get(scenario_key)


# ═══════════════════════════════════════════════════════════════════════════════
# Roleplay dialogue (LLM with offline fallback) — mirrors coaching_service pattern
# ═══════════════════════════════════════════════════════════════════════════════
async def _roleplay_opening(scenario_key: str, meta: Dict) -> str:
    if not llm_client.is_configured():
        return meta["opening_fallback"]
    system = prompts.build_scenario_roleplay_prompt(meta)
    try:
        return await llm_client.chat(
            [{"role": "system", "content": system},
             {"role": "user", "content": "Begin the scene now with your first line."}],
            temperature=0.7, max_tokens=150,
        )
    except llm_client.LLMError:
        return meta["opening_fallback"]


_EMERGENCY_REPLY = (
    "I need to pause this practice session — what you're describing sounds like it could be "
    "a real medical emergency. Please contact real emergency services or a doctor right away. "
    "This session has been paused for your safety."
)

_SILENCE_AUTO_CLOSE_REPLY = (
    "It looks like you've stepped away, so I'll close this session here — your progress up to "
    "this point has been saved. Feel free to start a new scenario anytime."
)

_AGGRESSION_AUTO_CLOSE_REPLY = (
    "I did ask you to keep this respectful, and that hasn't happened, so I'm ending this practice "
    "session here. Your progress up to this point has been saved."
)


async def _roleplay_reply(meta: Dict, turns: List[Dict], classification: str) -> str:
    if classification == "emergency":
        return _EMERGENCY_REPLY
    if classification == "silence":
        return "Sorry, I didn't quite catch that — It looks like we may have lost you for a moment so whenever you're ready, go ahead and continue."

    if not llm_client.is_configured():
        if classification == "aggressive":
            return "That tone isn't necessary here — let's keep this respectful, please."
        if classification == "rambling":
            return "Okay — could you sum that up in a sentence or two?"
        return meta["opening_fallback"]

    system = prompts.build_scenario_roleplay_prompt(meta)
    if classification == "aggressive":
        # First/only warning — the caller (send_turn) decides when the streak limit is hit and
        # ends the session outright without calling this at all (see _AGGRESSION_AUTO_CLOSE_REPLY).
        system += ("\n\nThe user was rude, cursed, or aggressive. In character, react realistically: "
                   "show real displeasure and firmly ask them to be respectful, but don't end the "
                   "conversation yet — give them one more chance.")
    if classification == "rambling":
        system += "\n\nThe user's last message was long-winded. In character, politely ask them to summarize."
    messages = [{"role": "system", "content": system}] + [
        {"role": t["role"], "content": t["content"]} for t in turns
    ]
    try:
        return await llm_client.chat(messages, temperature=0.7, max_tokens=180)
    except llm_client.LLMError:
        return "Go on, I'm listening."


# ═══════════════════════════════════════════════════════════════════════════════
# FastAPI controllers
# ═══════════════════════════════════════════════════════════════════════════════
async def _require_access(user_id: str) -> Optional[JSONResponse]:
    from services.gating_service import GatedFeature, check_feature_access

    access = await check_feature_access(user_id, GatedFeature.SCENARIO_BASED_LEARNING.value)
    if not access["accessible"]:
        return JSONResponse(status_code=403, content={"error": access["reason"], "gating": access})
    return None


async def get_scenarios(user_id: str = Depends(require_auth)):
    return {"scenarios": await list_scenarios()}


# ── Voice mode: WebSocket transport straight to this backend (backend/lib/voice_ws.py).
# "transcript" mode: Scenario only ever needs the plain text back, no word-timings/prosody.
async def voice_socket(websocket: WebSocket, session_id: str):
    user_id = await ws_require_auth(websocket)
    if user_id is None:
        return  # ws_require_auth already closed the socket

    gate = await _require_access(user_id)
    if gate:
        await websocket.close(code=4403, reason="Feature not accessible")
        return

    session = await db.scenariosession.find_unique(where={"id": session_id})
    if not session or session.userId != user_id:
        await websocket.close(code=4404, reason="Scenario session not found")
        return

    await websocket.accept()
    # partial_interval_s: live-preview text streams in while the user keeps talking,
    # instead of nothing appearing until the utterance ends.
    await voice_ws.serve(websocket, mode="transcript", partial_interval_s=1.2)


async def get_scenario_detail(key: str, user_id: str = Depends(require_auth)):
    meta = await scenario_meta(key)
    if not meta:
        return JSONResponse(status_code=404, content={"error": "Unknown scenario"})
    return {"key": key, **meta}


async def start_session(payload: StartScenarioSchema, user_id: str = Depends(require_auth)):
    gate = await _require_access(user_id)
    if gate:
        return gate

    meta = await scenario_meta(payload.scenario_key)
    if not meta:
        return JSONResponse(status_code=400, content={"error": "Unknown scenario"})
    if meta.get("status") == "ARCHIVED":
        return JSONResponse(status_code=400, content={"error": "This scenario is no longer available"})

    # A fresh start supersedes any other open Explore-group session (conversation,
    # scenario, coaching, interview coach) this user still has running elsewhere —
    # the Explore page's resume banner is what lets them avoid hitting this path
    # by accident; this is what "start something new anyway" relies on.
    await explore_sessions.supersede_open_explore_sessions(user_id)

    opening = await _roleplay_opening(payload.scenario_key, meta)
    session = await db.scenariosession.create(
        data={
            "userId": user_id,
            "scenarioKey": payload.scenario_key,
            "targetVocab": meta["target_vocab"],
            "turns": Json([{"role": "assistant", "content": opening}]),
            # CM-US-04: freeze the meta this session started with, so a later admin
            # edit/rollback to the CustomScenario never changes an in-progress chat.
            "scenarioMeta": Json(meta),
        }
    )
    return {
        "session_id": session.id,
        "scenario_key": payload.scenario_key,
        "label": meta["label"],
        "persona": meta["persona"],
        "intent": meta["intent"],
        "target_vocab": meta["target_vocab"],
        "opening_message": opening,
    }


# Maps SBL's turn classifications onto session_memory_service.WEAKNESS_FLAGS' vocabulary —
# "emergency" and "ok" aren't weaknesses worth tracking across sessions, so they're omitted.
_WEAKNESS_FLAG_MAP = {"rambling": "rambling", "aggressive": "aggressive_tone", "silence": "prolonged_silence"}


async def _finalize_session(session_id: str, user_id: str, meta: Dict, target_vocab: List[str],
                            turns: List[Dict], status: str, flags: List[str]) -> Dict:
    """Grade + persist a session as done — shared by end_session (explicit) and
    send_turn's silence/aggression auto-close paths."""
    coverage = _vocab_coverage(turns, target_vocab)
    grade = await grade_session(meta, turns, coverage["used"])
    vocabulary_score = round(100 * len(coverage["used"]) / max(1, len(target_vocab)), 2)
    # No politeness grade means no confidence score. Averaging vocabulary against a
    # missing number would hand back half marks for an ungraded session.
    scoring_status = (relevance.STATUS_SCORED if grade["politeness"] is not None
                      else relevance.STATUS_UNAVAILABLE)
    confidence = (round((grade["politeness"] + vocabulary_score) / 2, 2)
                  if grade["politeness"] is not None else None)

    await db.scenariosession.update(
        where={"id": session_id},
        data={
            "turns": Json(turns),
            "status": status,
            "vocabUsed": coverage["used"],
            "politenessScore": grade["politeness"],
            "vocabularyScore": vocabulary_score,
            "confidenceScore": confidence,
            "metGoal": grade["met_goal"],
            "summary": grade["summary"],
            "tips": grade["tips"],
            "originalLine": grade["original_line"] or None,
            "polishedLine": grade["polished_line"] or None,
            "flags": Json(flags),
            "completedAt": datetime.now(timezone.utc),
        },
    )

    # Feed the generic cross-session memory profile (same shared infra conversation_service
    # uses) so recurring weak areas show up on the Profile page and in future personalized
    # openings, regardless of which feature the practice happened in.
    try:
        from services.session_memory_service import _record_session
        from schemas.session_memory_schemas import RecordSessionRequest

        await _record_session(user_id, RecordSessionRequest(
            session_id=session_id, session_type="scenario",
            flags_seen=flags, topic_or_mode=meta.get("label"),
            # Omitted when ungraded: session_memory treats >= 80 as a strength, and an
            # ungraded session is not evidence of anything.
            overall_score=int(round(confidence)) if confidence is not None else None,
        ))
    except Exception:
        pass  # best-effort — scenario scoring must not fail because memory logging did

    from services.vocabulary_progress_service import record_usage

    await record_usage(user_id, coverage["used"], coverage["missing"])

    return {
        "session_id": session_id,
        "status": status,
        "scoring_status": scoring_status,
        "scores": {"politeness": grade["politeness"], "vocabulary": vocabulary_score, "confidence": confidence},
        "vocab_used": coverage["used"],
        "vocab_missing": coverage["missing"],
        "met_goal": grade["met_goal"] if meta.get("goal_type") == "negotiation" else None,
        "summary": grade["summary"],
        "suggestion": grade["suggestion"],
        "tips": grade["tips"],
        "original_line": grade["original_line"],
        "polished_line": grade["polished_line"],
        "graded_by": grade["_source"],
    }


async def send_turn(session_id: str, payload: ScenarioTurnSchema, user_id: str = Depends(require_auth)):
    session = await db.scenariosession.find_unique(where={"id": session_id})
    if not session or session.userId != user_id:
        return JSONResponse(status_code=404, content={"error": "Scenario session not found"})
    if session.status != "in_progress":
        return JSONResponse(status_code=400, content={"error": "Session is no longer active"})

    # CM-US-04: use the meta frozen at start_session, not a live re-fetch — an admin
    # edit mid-conversation must not change this session's persona/prompt/rules.
    meta = session.scenarioMeta or await scenario_meta(session.scenarioKey)
    if not meta:
        return JSONResponse(status_code=400, content={"error": "Unknown scenario"})

    turns = list(session.turns) + [{"role": "user", "content": payload.message}]
    classification = _classify_turn(meta, payload.message)
    silence_streak = session.silenceStreak + 1 if classification == "silence" else 0
    aggression_streak = session.aggressionStreak + 1 if classification == "aggressive" else 0

    flags = list(session.flags)
    if classification in _WEAKNESS_FLAG_MAP:
        flags.append(_WEAKNESS_FLAG_MAP[classification])

    # (The frontend fires an empty turn after IDLE_TIMEOUT_SECONDS of inactivity, so this
    # also covers "stayed in the session but never spoke or typed", not just short replies.)
    if classification == "silence" and silence_streak >= SILENCE_STREAK_LIMIT:
        turns.append({"role": "assistant", "content": _SILENCE_AUTO_CLOSE_REPLY})
        await _finalize_session(session_id, user_id, meta, session.targetVocab, turns, "completed", flags)
        return {
            "session_id": session_id,
            "reply": _SILENCE_AUTO_CLOSE_REPLY,
            "status": "completed",
            "classification": "silence",
        }

    # One warning for aggression/cursing, then the scenario ends on the next offense —
    # graduated, matching how a real person would react, not an instant kill on turn one.
    if classification == "aggressive" and aggression_streak >= AGGRESSION_STREAK_LIMIT:
        turns.append({"role": "assistant", "content": _AGGRESSION_AUTO_CLOSE_REPLY})
        await _finalize_session(session_id, user_id, meta, session.targetVocab, turns, "ended_early", flags)
        return {
            "session_id": session_id,
            "reply": _AGGRESSION_AUTO_CLOSE_REPLY,
            "status": "ended_early",
            "classification": "aggressive",
        }

    reply = await _roleplay_reply(meta, turns, classification)
    turns.append({"role": "assistant", "content": reply})

    new_status = "ended_early" if classification == "emergency" else "in_progress"

    await db.scenariosession.update(
        where={"id": session_id},
        data={
            "turns": Json(turns), "status": new_status,
            "silenceStreak": silence_streak, "aggressionStreak": aggression_streak,
            "flags": Json(flags),
        },
    )
    return {
        "session_id": session_id,
        "reply": reply,
        "status": new_status,
        "classification": classification,
    }


async def end_session(session_id: str, user_id: str = Depends(require_auth)):
    session = await db.scenariosession.find_unique(where={"id": session_id})
    if not session or session.userId != user_id:
        return JSONResponse(status_code=404, content={"error": "Scenario session not found"})
    if session.completedAt:
        return JSONResponse(status_code=400, content={"error": "Session already completed"})

    meta = session.scenarioMeta or await scenario_meta(session.scenarioKey)
    final_status = session.status if session.status == "ended_early" else "completed"
    return await _finalize_session(
        session_id, user_id, meta, session.targetVocab, list(session.turns), final_status, list(session.flags)
    )


async def get_recent_sessions(user_id: str = Depends(require_auth)):
    """Recent scenario session history (started or completed), most recent first —
    powers the Learner Dashboard's "Recent Scenarios" cards with real data instead
    of a static mock list. Reads the scenarioMeta snapshot taken at start_session so
    the label/category shown matches what the learner actually saw, even if an admin
    has since edited (or archived) the underlying scenario."""
    rows = await db.scenariosession.find_many(
        where={"userId": user_id}, order={"createdAt": "desc"}, take=6
    )
    items = []
    for row in rows:
        meta = row.scenarioMeta or await scenario_meta(row.scenarioKey)
        meta = meta or {}
        items.append({
            "session_id": row.id,
            "scenario_key": row.scenarioKey,
            "title": meta.get("label", row.scenarioKey),
            "category": meta.get("category", "General"),
            "description": meta.get("intent", ""),
            "status": row.status,
            "met_goal": row.metGoal,
            "confidence_score": row.confidenceScore,
            "vocabulary_score": row.vocabularyScore,
            "started_at": row.createdAt.isoformat(),
            "completed_at": row.completedAt.isoformat() if row.completedAt else None,
        })
    return {"scenarios": items}


async def get_session(session_id: str, user_id: str = Depends(require_auth)):
    session = await db.scenariosession.find_unique(where={"id": session_id})
    if not session or session.userId != user_id:
        return JSONResponse(status_code=404, content={"error": "Scenario session not found"})
    return {
        "session_id": session.id,
        "scenario_key": session.scenarioKey,
        "status": session.status,
        "turns": session.turns,
        "target_vocab": session.targetVocab,
        "vocab_used": session.vocabUsed,
        "scores": {
            "politeness": session.politenessScore,
            "vocabulary": session.vocabularyScore,
            "confidence": session.confidenceScore,
        },
        "met_goal": session.metGoal,
        "summary": session.summary,
        "tips": session.tips,
        "original_line": session.originalLine,
        "polished_line": session.polishedLine,
        "completed_at": session.completedAt.isoformat() if session.completedAt else None,
    }


# ── Admin: custom scenario CRUD (SBL-US-06, CM-US-01 .. CM-US-07) ──────────────
def _serialize_custom(row) -> Dict:
    return {
        "id": row.id,
        "title": row.title,
        "category": row.category,
        "persona": row.persona,
        "intent": row.intent,
        "system_prompt": row.systemPrompt,
        "opening_line": row.openingLine,
        "target_vocab": row.targetVocab,
        "goal_type": row.goalType,
        "difficulty": row.difficulty,
        "safety_mode": row.safetyMode,
        "corporate_tone": row.corporateTone,
        "status": row.status,
        "archived_at": row.archivedAt.isoformat() if row.archivedAt else None,
        "version": row.version,
        "sandbox_tested": row.sandboxTested,
        "quality_score": row.qualityScore,
        "quality_feedback": row.qualityFeedback,
        "confidence_score": row.confidenceScore,
        "confidence_feedback": row.confidenceFeedback,
        "scored_at": row.scoredAt.isoformat() if row.scoredAt else None,
        "readiness_score": row.readinessScore,
        "readiness_checklist": row.readinessChecklist,
        # Sprint 3 content intelligence (US-192 / US-195 / US-198). Exposed on the
        # existing payload so the admin list can show badges without an extra
        # request per template.
        "vocab_coverage_score": row.vocabCoverageScore,
        "vocab_coverage_feedback": row.vocabCoverageFeedback,
        "vocab_coverage_at": row.vocabCoverageAt.isoformat() if row.vocabCoverageAt else None,
        "explainability_report": row.explainabilityReport,
        "explainability_at": row.explainabilityAt.isoformat() if row.explainabilityAt else None,
        "deployment_confidence": row.deploymentConfidence,
        "deployment_feedback": row.deploymentFeedback,
        "deployment_scored_at": row.deploymentScoredAt.isoformat() if row.deploymentScoredAt else None,
        "sandbox_runs": row.sandboxRuns,
        "sandbox_passes": row.sandboxPasses,
        "created_at": row.createdAt.isoformat(),
        "updated_at": row.updatedAt.isoformat(),
    }


# Fields snapshotted into CustomScenarioVersion.snapshot on every edit/rollback —
# and restored verbatim by admin_rollback_custom. camelCase to match the Prisma
# row shape 1:1 so restoring is a plain dict spread, not a field-by-field remap.
_SNAPSHOT_FIELDS = (
    "title", "category", "persona", "intent", "systemPrompt", "openingLine",
    "targetVocab", "goalType", "difficulty", "safetyMode", "corporateTone",
)


def _snapshot_fields(row) -> Dict:
    return {f: getattr(row, f) for f in _SNAPSHOT_FIELDS}


async def _save_version_snapshot(scenario_id: str, version: int, row) -> None:
    await db.customscenarioversion.create(
        data={"scenarioId": scenario_id, "version": version, "snapshot": Json(_snapshot_fields(row))}
    )


async def _validate_category(category: str) -> Optional[JSONResponse]:
    # CM-US-10 E-03 (US-194): an UNASSIGNED category is a distinct case from an
    # unrecognised one and the spec fixes the wording for it — telling an admin
    # who picked nothing that "" is not a recognized category is nonsense.
    if not (category or "").strip():
        return JSONResponse(
            status_code=400,
            content={
                "error": "Please assign this scenario to a Category so users can find it.",
                "field": "category",
            },
        )
    valid = await valid_category_names()
    if category not in valid:
        return JSONResponse(
            status_code=400,
            content={
                "error": f'"{category}" is not a recognized category — add it under Content Management first.',
                "field": "category",
            },
        )
    return None


# CM-US-04: auto-purge archived scenarios nobody is still mid-conversation in.
# The "lock" is already load-bearing code, not new: start_session (above) refuses to
# start on status=="ARCHIVED", so an archived scenario can never gain a new
# participant from the moment it's archived — there's nothing left to build there.
# What's missing is the actual delete. No cron/scheduler exists anywhere in this repo,
# so rather than add one for a single janitorial task, this runs opportunistically
# every time admin_list_custom is called (i.e. whenever an admin opens the page).
# ARCHIVE_PURGE_GRACE_HOURS gives a mis-click undo window via Restore before a purge
# is possible at all.
ARCHIVE_PURGE_GRACE_HOURS = 12

# CM-US-10 E-04: retries for the optimistic-concurrency guard on admin_update_custom.
# Three is ample — each retry only loses to another admin saving in the same
# millisecond, and an internal admin tool never has enough concurrent editors to
# starve a writer past that.
_MAX_WRITE_ATTEMPTS = 3


async def _purge_idle_archives() -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=ARCHIVE_PURGE_GRACE_HOURS)
    candidates = await db.customscenario.find_many(
        where={"status": "ARCHIVED", "archivedAt": {"lte": cutoff}}
    )
    deleted = 0
    for row in candidates:
        # plain count-then-delete, no SELECT-FOR-UPDATE — the only thing
        # that could race this is another admin hitting Restore in the same instant,
        # which is rare/low-stakes enough in an internal admin tool not to warrant
        # row-locking machinery. Cascades to CustomScenarioVersion (schema FK).
        in_progress = await db.scenariosession.count(
            where={"scenarioKey": f"custom:{row.id}", "status": "in_progress"}
        )
        if in_progress == 0:
            await db.customscenario.delete(where={"id": row.id})
            deleted += 1
    return deleted


async def admin_list_custom(user_id: str = Depends(require_admin)):
    await _purge_idle_archives()
    rows = await db.customscenario.find_many(order={"createdAt": "desc"})
    return {"scenarios": [_serialize_custom(r) for r in rows]}


# ── Compulsory publish gate (CM-US-02 quality, CM-US-06 confidence/guardrails,
# CM-US-07 readiness) — runs on every create/update. Two tiers:
#   1. HARD, never bypassable: sandbox must have been tested this edit.
#   2. SOFT, bypassable via `quality_acknowledged`: quality < 70 or the readiness
#      checklist isn't fully green. The CM-US-03 content-safety scan is a schema-level
#      validator (scenario_schemas.py), not part of this gate, and is never bypassable
#      by this flag either.
async def _deployment_gate(payload: CustomScenarioSchema, eval_result: Dict,
                           scenario_id: Optional[str]) -> Tuple[int, Dict]:
    """CM-US-14 (US-198) pre-deployment evaluation, folded into the existing
    publish gate rather than bolted on as a second gate the admin has to pass
    separately. Returns (score, breakdown).

    Vocabulary coverage is read from the stored row when there is one; a brand-new
    scenario has not been coverage-scored yet, so compute_breakdown's neutral
    default applies instead of penalising it for a score it never had a chance
    to earn."""
    previous, vocab_coverage = [], None
    if scenario_id:
        previous = await db.templatedeployment.find_many(
            where={"scenarioId": scenario_id}, order={"createdAt": "desc"}, take=20
        )
        existing = await db.customscenario.find_unique(where={"id": scenario_id})
        if existing:
            vocab_coverage = existing.vocabCoverageScore

    runs, passes = (1, 1) if payload.tested else (0, 0)
    breakdown = deployment_confidence_service.compute_breakdown(
        eval_result.get("quality_breakdown") or {},
        eval_result.get("confidence_score"),
        vocab_coverage,
        runs, passes, previous,
    )
    return deployment_confidence_service.score_from_breakdown(breakdown), breakdown


async def _run_publish_gate(payload: CustomScenarioSchema,
                            scenario_id: Optional[str] = None) -> Tuple[Optional[JSONResponse], Dict]:
    shaped = {
        "title": payload.title, "category": payload.category, "persona": payload.persona,
        "intent": payload.intent, "system_prompt": payload.system_prompt,
        "opening_line": payload.opening_line, "target_vocab": payload.target_vocab,
        "goal_type": payload.goal_type, "difficulty": payload.difficulty,
        "sandbox_tested": payload.tested,
    }
    if not payload.tested:
        return JSONResponse(
            status_code=400,
            content={
                "error": "Run the sandbox tester successfully before publishing this scenario.",
                "gate": "not_tested",
            },
        ), {}

    eval_result = await content_scoring_service.evaluate_template(shaped)
    readiness = content_scoring_service.assess_readiness(
        shaped, eval_result["quality_score"], eval_result["confidence_score"]
    )

    scores = {
        "qualityScore": eval_result["quality_score"],
        "qualityFeedback": Json({
            "breakdown": eval_result["quality_breakdown"],
            "recommendations": eval_result["quality_recommendations"],
            "source": eval_result["_source"],
        }),
        "confidenceScore": eval_result["confidence_score"],
        "confidenceFeedback": Json({
            "explanation": eval_result["confidence_explanation"],
            "warnings": eval_result["confidence_warnings"],
            "guardrail_suggestions": eval_result["confidence_guardrail_suggestions"],
            "source": eval_result["_source"],
        }),
        "scoredAt": datetime.now(timezone.utc),
        "readinessScore": readiness["score"],
        "readinessChecklist": Json(readiness),
    }

    deployment_score, deployment_breakdown = await _deployment_gate(payload, eval_result, scenario_id)
    # CM-US-14 acceptance: "Templates with low deployment confidence require
    # administrator review before publication." Routed through the SAME
    # acknowledgement flag as the quality gate rather than a second, separate
    # confirmation — one deliberate override, not two.
    low_deployment_confidence = deployment_score < deployment_confidence_service.LOW_CONFIDENCE_THRESHOLD

    scores["deploymentConfidence"] = deployment_score
    scores["deploymentFeedback"] = Json({
        "breakdown": deployment_breakdown,
        "blocking": [],
        "warnings": [],
        "recommendation": (
            "Requires administrator review before publication."
            if low_deployment_confidence else "Cleared for deployment."
        ),
    })
    scores["deploymentScoredAt"] = datetime.now(timezone.utc)

    needs_ack = (
        eval_result["quality_score"] < content_scoring_service.QUALITY_PUBLISH_THRESHOLD
        or not readiness["ready"]
        or low_deployment_confidence
    )
    if needs_ack and not payload.quality_acknowledged:
        reasons = []
        if eval_result["quality_score"] < content_scoring_service.QUALITY_PUBLISH_THRESHOLD:
            reasons.append(f"quality scored {eval_result['quality_score']}/100")
        if not readiness["ready"]:
            reasons.append("the readiness checklist isn't complete")
        if low_deployment_confidence:
            reasons.append(f"deployment confidence is {deployment_score}/100")
        return JSONResponse(
            status_code=400,
            content={
                "error": (
                    "Not ready to publish — " + "; ".join(reasons)
                    + ". Review the feedback, then publish anyway if you're sure."
                ),
                "gate": "needs_acknowledgment",
                "quality_score": eval_result["quality_score"],
                "confidence_score": eval_result["confidence_score"],
                "deployment_confidence": deployment_score,
                "deployment_breakdown": deployment_breakdown,
                "quality_recommendations": eval_result["quality_recommendations"],
                "confidence_warnings": eval_result["confidence_warnings"],
                "guardrail_suggestions": eval_result["confidence_guardrail_suggestions"],
                "readiness_missing": readiness["missing"],
            },
        ), {}

    return None, scores


def deployment_breakdown_of(scores: Dict) -> Dict:
    """Pull the breakdown back out of the Json-wrapped feedback the gate built, so
    the deployment record stores the same numbers the scenario row does."""
    feedback = scores.get("deploymentFeedback")
    raw = getattr(feedback, "data", feedback) or {}
    return raw.get("breakdown", {}) if isinstance(raw, dict) else {}


async def admin_create_custom(payload: CustomScenarioSchema, user_id: str = Depends(require_admin)):
    existing = await db.customscenario.find_unique(where={"title": payload.title})
    if existing:
        return JSONResponse(status_code=409, content={"error": "A scenario with this title already exists"})
    invalid_category = await _validate_category(payload.category)
    if invalid_category:
        return invalid_category

    gate_error, scores = await _run_publish_gate(payload)
    if gate_error:
        return gate_error

    row = await db.customscenario.create(
        data={
            "title": payload.title,
            "category": payload.category,
            "persona": payload.persona,
            "intent": payload.intent,
            "systemPrompt": payload.system_prompt,
            "openingLine": payload.opening_line,
            "targetVocab": payload.target_vocab,
            "goalType": payload.goal_type,
            "difficulty": payload.difficulty,
            "safetyMode": payload.safety_mode,
            "corporateTone": payload.corporate_tone,
            "sandboxTested": payload.tested,
            **scores,
        }
    )
    # CM-US-14: history is the input to the NEXT confidence score and the record
    # E-03 compares against to spot a regression, so every publish is logged.
    await deployment_confidence_service.record_deployment(
        row.id, row.version, scores.get("deploymentConfidence") or 0,
        deployment_breakdown_of(scores),
        outcome="DEPLOYED", note="Created",
    )
    return _serialize_custom(row)


async def admin_update_custom(scenario_id: str, payload: CustomScenarioSchema, user_id: str = Depends(require_admin)):
    row = await db.customscenario.find_unique(where={"id": scenario_id})
    if not row:
        return JSONResponse(status_code=404, content={"error": "Custom scenario not found"})
    collision = await db.customscenario.find_unique(where={"title": payload.title})
    if collision and collision.id != scenario_id:
        return JSONResponse(status_code=409, content={"error": "A scenario with this title already exists"})
    invalid_category = await _validate_category(payload.category)
    if invalid_category:
        return invalid_category

    gate_error, scores = await _run_publish_gate(payload, scenario_id=scenario_id)
    if gate_error:
        return gate_error

    fields = {
        "title": payload.title,
        "category": payload.category,
        "persona": payload.persona,
        "intent": payload.intent,
        "systemPrompt": payload.system_prompt,
        "openingLine": payload.opening_line,
        "targetVocab": payload.target_vocab,
        "goalType": payload.goal_type,
        "difficulty": payload.difficulty,
        "safetyMode": payload.safety_mode,
        "corporateTone": payload.corporate_tone,
        "sandboxTested": payload.tested,
    }

    # CM-US-10 E-04 (US-194): concurrent editing is last-write-wins, but the spec
    # also requires that "the system stores version histories so the overwritten
    # data can be restored". A read-then-write did NOT deliver that: two admins
    # saving at once both read version N, both snapshotted the same N, and both
    # wrote N+1 — so one admin's work vanished with no snapshot of it, and the
    # version counter silently lost an increment.
    #
    # The write is now guarded on the version we actually read (optimistic
    # concurrency). A racing writer invalidates the guard, we re-read, and we
    # snapshot the state we genuinely replaced. Last write still wins; nothing is
    # lost from history.
    updated = None
    for _ in range(_MAX_WRITE_ATTEMPTS):
        current = await db.customscenario.find_unique(where={"id": scenario_id})
        if not current:
            return JSONResponse(status_code=404, content={"error": "Custom scenario not found"})

        applied = await db.customscenario.update_many(
            where={"id": scenario_id, "version": current.version},
            data={**fields, "version": current.version + 1, **scores},
        )
        if applied:
            # Snapshot AFTER winning the race, using the row this write replaced.
            await _save_version_snapshot(scenario_id, current.version, current)
            updated = await db.customscenario.find_unique(where={"id": scenario_id})
            break

    if updated is None:
        return JSONResponse(
            status_code=409,
            content={"error": "This scenario is being edited by someone else — reload and try again."},
        )

    await deployment_confidence_service.record_deployment(
        updated.id, updated.version, scores.get("deploymentConfidence") or 0,
        deployment_breakdown_of(scores), outcome="DEPLOYED", note="Updated",
    )
    return _serialize_custom(updated)


# ── Versioning & rollback (CM-US-04) ────────────────────────────────────────────
async def admin_list_versions(scenario_id: str, user_id: str = Depends(require_admin)):
    row = await db.customscenario.find_unique(where={"id": scenario_id})
    if not row:
        return JSONResponse(status_code=404, content={"error": "Custom scenario not found"})
    versions = await db.customscenarioversion.find_many(
        where={"scenarioId": scenario_id}, order={"version": "desc"}
    )
    return {
        "current_version": row.version,
        "versions": [
            {"version": v.version, "snapshot": v.snapshot, "created_at": v.createdAt.isoformat()}
            for v in versions
        ],
    }


async def admin_rollback_custom(scenario_id: str, version: int, user_id: str = Depends(require_admin)):
    row = await db.customscenario.find_unique(where={"id": scenario_id})
    if not row:
        return JSONResponse(status_code=404, content={"error": "Custom scenario not found"})
    snapshot_row = await db.customscenarioversion.find_first(
        where={"scenarioId": scenario_id, "version": version}
    )
    if not snapshot_row:
        return JSONResponse(status_code=404, content={"error": f"No saved version {version} for this scenario"})

    # CM-US-04: rollback is a hard reset, not a new branch on top — every stored
    # snapshot at or above the target version is discarded (the target's own snapshot
    # becomes redundant once it's live again; anything newer than it is the abandoned
    # future the admin is explicitly reverting away from). This does NOT touch anyone
    # already mid-conversation: ScenarioSession carries its own frozen scenarioMeta
    # snapshot taken at session start, never a live reference into this table.
    await db.customscenarioversion.delete_many(
        where={"scenarioId": scenario_id, "version": {"gte": version}}
    )

    restore: Dict = dict(snapshot_row.snapshot)
    updated = await db.customscenario.update(
        where={"id": scenario_id},
        data={
            **restore,
            "version": version,
            # Reverted content needs a fresh test + publish-gate pass before it can be
            # saved again — same as any other content change (CM-US-02/07).
            "sandboxTested": False,
            "qualityScore": None, "qualityFeedback": Json(None),
            "confidenceScore": None, "confidenceFeedback": Json(None),
            "scoredAt": None, "readinessScore": None, "readinessChecklist": Json(None),
        },
    )
    return _serialize_custom(updated)


# ── Archive / restore — delete = archive, never a hard delete (CM-US-04 E-03) ──
async def admin_archive_custom(scenario_id: str, user_id: str = Depends(require_admin)):
    row = await db.customscenario.find_unique(where={"id": scenario_id})
    if not row:
        return JSONResponse(status_code=404, content={"error": "Custom scenario not found"})
    if row.status == "ARCHIVED":
        return JSONResponse(status_code=409, content={"error": "Scenario is already archived"})
    updated = await db.customscenario.update(
        where={"id": scenario_id},
        data={"status": "ARCHIVED", "archivedAt": datetime.now(timezone.utc)},
    )
    return _serialize_custom(updated)


async def admin_restore_custom(scenario_id: str, user_id: str = Depends(require_admin)):
    row = await db.customscenario.find_unique(where={"id": scenario_id})
    if not row:
        return JSONResponse(status_code=404, content={"error": "Custom scenario not found"})
    if row.status == "ACTIVE":
        return JSONResponse(status_code=409, content={"error": "Scenario is already active"})

    # CM-US-02/07: restoring makes it live for learners again, so it must still clear
    # the same publish gate — using the row's cached scores (no LLM call needed; they
    # were computed and persisted the last time this content was actually saved).
    if row.qualityScore is None or row.confidenceScore is None:
        return JSONResponse(
            status_code=409,
            content={"error": "This scenario has never passed evaluation — edit and save it again before restoring."},
        )
    readiness = content_scoring_service.assess_readiness(_serialize_custom(row), row.qualityScore, row.confidenceScore)
    if row.qualityScore < content_scoring_service.QUALITY_PUBLISH_THRESHOLD or not readiness["ready"]:
        return JSONResponse(
            status_code=409,
            content={
                "error": f"Scored {row.qualityScore}/100 and isn't publish-ready — edit and save it again to re-pass the gate before restoring.",
                "readiness_missing": readiness["missing"],
            },
        )

    updated = await db.customscenario.update(
        where={"id": scenario_id}, data={"status": "ACTIVE", "archivedAt": None}
    )
    return _serialize_custom(updated)


# ── Quality Score + Prompt Confidence + Readiness (CM-US-02, CM-US-06, CM-US-07) ─
async def admin_evaluate_template(scenario_id: str, user_id: str = Depends(require_admin)):
    row = await db.customscenario.find_unique(where={"id": scenario_id})
    if not row:
        return JSONResponse(status_code=404, content={"error": "Custom scenario not found"})

    result = await content_scoring_service.evaluate_template(_serialize_custom(row))
    updated = await db.customscenario.update(
        where={"id": scenario_id},
        data={
            "qualityScore": result["quality_score"],
            "qualityFeedback": Json({
                "breakdown": result["quality_breakdown"],
                "recommendations": result["quality_recommendations"],
                "source": result["_source"],
            }),
            "confidenceScore": result["confidence_score"],
            "confidenceFeedback": Json({
                "explanation": result["confidence_explanation"],
                "warnings": result["confidence_warnings"],
                "source": result["_source"],
            }),
            "scoredAt": datetime.now(timezone.utc),
        },
    )
    return _serialize_custom(updated)


async def admin_assess_readiness(scenario_id: str, user_id: str = Depends(require_admin)):
    row = await db.customscenario.find_unique(where={"id": scenario_id})
    if not row:
        return JSONResponse(status_code=404, content={"error": "Custom scenario not found"})

    # Auto-run the (cached-per-edit) quality/confidence evaluation first if this
    # version hasn't been scored yet — readiness needs both to judge the bar.
    if row.qualityScore is None or row.confidenceScore is None:
        evaluated = await admin_evaluate_template(scenario_id, user_id)
        if isinstance(evaluated, JSONResponse):
            return evaluated
        row = await db.customscenario.find_unique(where={"id": scenario_id})

    checklist = content_scoring_service.assess_readiness(
        _serialize_custom(row), row.qualityScore, row.confidenceScore
    )
    updated = await db.customscenario.update(
        where={"id": scenario_id},
        data={"readinessScore": checklist["score"], "readinessChecklist": Json(checklist)},
    )
    return _serialize_custom(updated)


async def admin_preview_custom(payload: ScenarioPreviewSchema, user_id: str = Depends(require_admin)):
    meta = {
        "label": "Preview",
        "persona": payload.persona,
        "intent": "",
        "goal_type": payload.goal_type,
        "safety_mode": payload.safety_mode,
        "corporate_tone": payload.corporate_tone,
        "target_vocab": payload.target_vocab or ["(none set)"],
        "opening_fallback": payload.opening_line or f"Let's begin — {payload.persona}.",
        "instructions": payload.system_prompt,
    }
    turns = [t.model_dump() for t in payload.turns]

    if not payload.message:
        opening = await _roleplay_opening("preview", meta)
        return {"reply": opening, "classification": "ok"}

    turns.append({"role": "user", "content": payload.message})
    classification = _classify_turn(meta, payload.message)
    reply = await _roleplay_reply(meta, turns, classification)

    # CM-US-14 (US-198): tally the run against the saved scenario so deployment
    # confidence has a real sandbox success rate.
    #
    # A run PASSES when the tester produced a reply with the persona intact.
    # Deliberately NOT `classification == "ok"`: _classify_turn describes the
    # LEARNER's message (silence / rambling / aggressive), not the prompt's
    # behaviour, so treating those as failures would score the template down for
    # how the tester happened to type. The one classification that does reflect
    # the scenario itself is an emergency safety break, where the AI must abandon
    # the persona — that is a genuine reliability event.
    if payload.scenario_id:
        await deployment_confidence_service.record_sandbox_run(
            payload.scenario_id,
            passed=bool(reply) and classification != "emergency",
        )

    return {"reply": reply, "classification": classification}
