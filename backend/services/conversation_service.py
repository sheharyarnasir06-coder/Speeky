"""
AI Conversation Practice (AIC-US-01 .. AIC-US-16) — the app's core feature: open-ended
topic conversation with the AI, text or voice, scored like the assessment/coaching
pipelines already in this backend.

Architecture matches the rest of the ported feature set:
  * Session state (turns, level, rate-limit counters) persists as one KvEntry blob via
    lib.kv_store — same pattern as interview_coach_service / session_memory_service,
    chosen over a dedicated Prisma model because the shape (variable-length turns,
    per-session counters) is exactly what those two already use kv_store for.
  * The backend never touches raw audio — voice turns arrive as (transcript, AudioFeatures)
    from the STT/VAD agent, same contract as assessment/coaching (schemas.AudioFeaturesSchema).
  * LLM calls go through lib.ai_client / lib.llm_client (Groq), with the same offline
    fallback the rest of the app already relies on so this degrades gracefully and the
    test suite runs network-free.

What is deliberately NOT handled here (client/device concerns, not backend):
  * AIC-US-02 E-04 offline sync state, AIC-US-05 local caching of unsent turns,
    AIC-US-15 E-01/E-02 (network-drop caching, mic/keyboard UI locking), AIC-US-16
    E-01/E-03 (hardware mute detection, stopping playback on next send) — these are
    UI/client state with no backend action to take.
  * AIC-US-05 (session interruption & auto-resume) is NOT reimplemented here — it's
    generic across features and already lives in session_memory_service
    (log_interruption/resume_session/get_interruption_status). Callers pass
    session_type="conversation" and this session's id into those existing endpoints.
"""

import logging
import os
import re
import time
import uuid

logger = logging.getLogger(__name__)
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from fastapi import Depends, Header, WebSocket
from fastapi.responses import JSONResponse, Response

from lib import (
    ai_client,
    explore_sessions,
    grammar_checker,
    kv_store,
    llm_client,
    pii,
    prompts,
    relevance,
    session_scorer,
    tts_client,
    voice_ws,
)
from lib.session_scorer import AudioFeatures
from lib.code_switch.code_switch_text import TextCodeSwitchDetector
from services.code_switch_service import log_detected_word
from middlewares.auth_middleware import require_auth, ws_require_auth
from middlewares.error_handler import AuthError
from prisma.enums import LearningLevel
from schemas.conversation_schemas import (
    MemoryOptOutSchema,
    SendMessageSchema,
    StartConversationSchema,
    TTSRequestSchema,
)
from utils.feature_errors import InvalidSubmissionError, RateLimitedError, SessionNotFoundError

NAMESPACE = "conversation_sessions"
MEMORY_NS = "conversation_memory"

LEVEL_STALE_DAYS = 90  # E-02
RATE_LIMIT_WINDOW_SECONDS = 10
RATE_LIMIT_MAX_MESSAGES = 15  # E-01: 15+ messages within 10s
GIBBERISH_STRIKE_LIMIT = 3  # E-02: clarify a limited number of times, then end
LEVEL_JUDGE_WINDOW = 3  # E-04: rolling average of last 3 turns, not per-turn

# BAS-US LearningLevel (6 tiers) -> prompts.py's 3-tier conversation calibration.
_LEVEL_MAP = {
    LearningLevel.BEGINNER: "beginner",
    LearningLevel.ELEMENTARY: "beginner",
    LearningLevel.INTERMEDIATE: "intermediate",
    LearningLevel.UPPER_INTERMEDIATE: "intermediate",
    LearningLevel.ADVANCED: "advanced",
    LearningLevel.PROFICIENT: "advanced",
}

MEMORY_FACT_CATEGORIES = {"job", "hobby", "interest", "goal"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# ── AIC-US-01: custom topic validation ─────────────────────────────────────────
async def validate_topic(topic: str) -> Dict:
    """Returns {"verdict": safe|unsafe|vague, "preset_match": key|None, "reason": str}."""
    if len(topic.strip()) < 3:
        return {"verdict": "vague", "preset_match": None, "reason": "Topic is too short."}

    if not llm_client.is_configured():
        # Offline: silently route obvious preset matches, otherwise accept as-is.
        lowered = topic.strip().lower()
        for key, label in prompts.TOPICS.items():
            if lowered == key or lowered == label.lower() or lowered in label.lower():
                return {"verdict": "safe", "preset_match": key, "reason": "Matches an existing preset."}
        return {"verdict": "safe", "preset_match": None, "reason": "Offline mode — accepted without classification."}

    raw = await ai_client.generate(
        system_prompt=prompts.build_topic_validation_prompt(topic), user_message="", max_tokens=100,
    )
    verdict, preset_match, reason = "safe", None, "Looks fine."
    for line in raw.splitlines():
        if line.upper().startswith("VERDICT:"):
            verdict = line.split(":", 1)[1].strip().lower()
        elif line.upper().startswith("PRESET_MATCH:"):
            val = line.split(":", 1)[1].strip().lower()
            preset_match = val if val in prompts.TOPICS else None
        elif line.upper().startswith("REASON:"):
            reason = line.split(":", 1)[1].strip()
    if verdict not in ("safe", "unsafe", "vague"):
        verdict = "safe"
    return {"verdict": verdict, "preset_match": preset_match, "reason": reason}


# ── AIC-US-03: proficiency-level resolution ────────────────────────────────────
async def _resolve_level(user_id: str, level_override: Optional[str]):
    """Returns (level, source, stale_warning)."""
    from lib.prisma_client import db

    if level_override:
        override = level_override.lower()
        if override not in prompts.VALID_LEVELS:
            raise InvalidSubmissionError(f"level_override must be one of {prompts.VALID_LEVELS}")
        return override, "override", None

    latest = await db.baselineassessment.find_first(
        where={"userId": user_id, "completedAt": {"not": None}}, order={"completedAt": "desc"},
    )
    if not latest or not latest.learningLevel:
        return "intermediate", "default", None  # E-01

    stale_warning = None
    if _now() - latest.completedAt > timedelta(days=LEVEL_STALE_DAYS):  # E-02
        stale_warning = "Your level may have changed — consider retaking your Baseline Assessment."
    return _LEVEL_MAP.get(latest.learningLevel, "intermediate"), "baseline", stale_warning


async def _maybe_adjust_level(session: dict) -> None:
    """E-04: judge on a rolling window of the last N user turns, adjust at most once/session."""
    if session["level_locked"]:
        return
    window = session["recent_user_texts"][-LEVEL_JUDGE_WINDOW:]
    if len(window) < LEVEL_JUDGE_WINDOW or not llm_client.is_configured():
        return
    try:
        raw = await ai_client.generate(
            system_prompt=prompts.build_level_judge_prompt(window), user_message="", max_tokens=10,
        )
    except Exception:
        return
    judged = raw.strip().lower()
    if judged in prompts.VALID_LEVELS and judged != session["level"]:
        session["level"] = judged
        session["level_locked"] = True


# ── AIC-US-08: abuse / rate-limit ──────────────────────────────────────────────
def _check_rate_limit(session: dict) -> None:
    now = time.time()
    window_start = now - RATE_LIMIT_WINDOW_SECONDS
    timestamps = [t for t in session["message_timestamps"] if t >= window_start]
    timestamps.append(now)
    session["message_timestamps"] = timestamps[-50:]  # bounded, don't grow forever
    if len(timestamps) > RATE_LIMIT_MAX_MESSAGES:
        raise RateLimitedError("Let's slow down a bit — take your time.")


def _looks_like_gibberish(text: str) -> bool:
    """Cheap heuristic mirroring assessment_service's integrity checker: repetitive
    characters or suspiciously short/garbled words, not a real message."""
    stripped = text.strip()
    if not stripped:
        return False
    if re.search(r"(.)\1{4,}", stripped):
        return True
    words = stripped.split()
    if words:
        avg_len = sum(len(w) for w in words) / len(words)
        if avg_len < 2 and len(stripped) > 5:
            return True
    return False


# ── AIC-US-06: cross-session personalization memory ────────────────────────────
async def _get_memory(user_id: str) -> Dict:
    existing = await kv_store.store.get(MEMORY_NS, user_id)
    return existing or {"user_id": user_id, "opted_out": False, "facts": []}


async def _extract_and_store_facts(user_id: str, transcript_texts: List[str]) -> List[Dict]:
    memory = await _get_memory(user_id)
    if memory["opted_out"] or not llm_client.is_configured() or not transcript_texts:
        return []

    new_facts: List[Dict] = []
    for text in transcript_texts[-5:]:  # cap LLM calls per session
        try:
            raw = await llm_client.chat_json(
                [{"role": "user", "content": prompts.build_memory_fact_extraction_prompt(text)}],
                temperature=0.0, max_tokens=200,
            )
        except llm_client.LLMError:
            continue
        for f in raw.get("facts", []):
            category = f.get("category")
            value = (f.get("value") or "").strip()
            if category in MEMORY_FACT_CATEGORIES and value:
                new_facts.append({"category": category, "value": value})

    if not new_facts:
        return []

    facts = list(memory["facts"])
    for nf in new_facts:
        # E-01/E-04: a new fact in the same category silently replaces the old one
        # (most-recently-stated wins — no correction UI needed).
        facts = [f for f in facts if f["category"] != nf["category"]]
        facts.append({
            "fact_id": _new_id("fact"), "category": nf["category"], "value": nf["value"],
            "updated_at": _now(),
        })
    memory["facts"] = facts
    if await kv_store.store.get(MEMORY_NS, user_id) is None:
        await kv_store.store.create(MEMORY_NS, user_id, memory)
    else:
        await kv_store.store.update(MEMORY_NS, user_id, memory)
    return new_facts


def _memory_callback_note(memory: Dict) -> str:
    if not memory["facts"]:
        return ""
    top = memory["facts"][-2:]  # "no more than once or twice per session"
    bits = [f"{f['category']}: {f['value']}" for f in top]
    return (
        "You know a few durable facts about this user from past sessions — "
        f"{'; '.join(bits)}. If it fits naturally, reference ONE of these briefly "
        "to make the conversation feel continuous. Don't force it, and never mention "
        "more than one."
    )


# ── gating (matches coaching_service._require_access) ──────────────────────────
async def _require_access(user_id: str):
    from services.gating_service import GatedFeature, check_feature_access

    access = await check_feature_access(user_id, GatedFeature.AI_CONVERSATION_PRACTICE.value)
    if not access["accessible"]:
        return JSONResponse(status_code=403, content={"error": access["reason"], "gating": access})
    return None


async def _get_session(session_id: str, user_id: str) -> dict:
    session = await kv_store.store.get(NAMESPACE, session_id)
    if session is None or session["user_id"] != user_id:
        raise SessionNotFoundError(f"Conversation session {session_id} not found")
    return session


def _topic_label(session: dict) -> str:
    if session["custom_topic"]:
        return session["custom_topic"]
    return prompts.TOPICS.get(session["topic_key"], session["topic_key"])


def _transcript_text(session: dict) -> str:
    """Flatten turns into one block — ai_client.generate() takes a single user_message,
    not a message array (same convention as interview_coach_service._transcript_text)."""
    lines = []
    for t in session["turns"]:
        if not t["content"]:
            continue
        speaker = "AI" if t["role"] == "assistant" else "Candidate"
        lines.append(f"{speaker}: {t['content']}")
    return "\n".join(lines)


def _build_system_prompt(session: dict, safety_note: Optional[str] = None) -> str:
    return prompts.build_system_prompt(
        session["topic_key"], custom_topic=session["custom_topic"], level=session["level"],
        safety_note=safety_note,
    )


# ── AIC-US-01/09..14: start a session ───────────────────────────────────────────
async def _start_session(user_id: str, req: StartConversationSchema) -> Dict:
    topic_key = "custom" if req.custom_topic else req.topic_key
    custom_topic = None
    if req.custom_topic:
        validation = await validate_topic(req.custom_topic)
        if validation["verdict"] == "unsafe":  # E-01
            raise InvalidSubmissionError("Please choose a different topic.")
        if validation["preset_match"]:  # E-03: silently route into the matching preset
            topic_key, custom_topic = validation["preset_match"], None
        else:
            topic_key, custom_topic = "custom", req.custom_topic
    elif req.topic_key not in prompts.TOPICS:
        raise InvalidSubmissionError(f"Unknown topic_key. Valid: {list(prompts.TOPICS)}")

    # A fresh start supersedes any other open Explore-group session this user has
    # running elsewhere — see lib/explore_sessions.py.
    await explore_sessions.supersede_open_explore_sessions(user_id)

    level, level_source, stale_warning = await _resolve_level(user_id, req.level_override)

    session_id = _new_id("conv")
    now = _now()
    session = {
        "session_id": session_id, "user_id": user_id,
        "topic_key": topic_key, "custom_topic": custom_topic,
        "level": level, "level_source": level_source, "level_locked": False,
        "recent_user_texts": [],
        "show_corrections": req.show_corrections,
        "turns": [], "status": "active",
        "message_timestamps": [], "gibberish_strikes": 0, "pii_reminder_shown": False,
        "room_name": session_id,  # LiveKit room for voice mode — session_id is already "conv_..."
        "started_at": now, "completed_at": None,
    }

    memory = await _get_memory(user_id)
    memory_note = _memory_callback_note(memory)
    system_prompt = _build_system_prompt(session, safety_note=memory_note or None)
    opening = await ai_client.generate(system_prompt=system_prompt, user_message="", max_tokens=150)

    session["turns"].append({"role": "assistant", "content": opening, "input_mode": None,
                             "correction_chip": None, "created_at": now})
    await kv_store.store.create(NAMESPACE, session_id, session)

    return {
        "session_id": session_id, "topic_key": topic_key, "topic_label": _topic_label(session),
        "level": level, "level_source": level_source, "level_stale_warning": stale_warning,
        "opening_message": opening, "started_at": now,
    }


# ── AIC-US-09: send a turn ──────────────────────────────────────────────────────
async def _send_message(user_id: str, session_id: str, req: SendMessageSchema) -> Dict:
    session = await _get_session(session_id, user_id)
    if session["status"] != "active":
        raise InvalidSubmissionError("This session is no longer active")

    _check_rate_limit(session)  # E-01, raises RateLimitedError (429) if tripped

    text = req.text.strip() or (req.audio_features.transcript.strip() if req.audio_features else "")
    now = _now()
    flags: List[str] = []

    # AIC-US-07: redact PII before it's stored or forwarded to the LLM.
    redacted_text, redacted_types = pii.redact(text)
    pii_note = None
    if redacted_types and not session["pii_reminder_shown"]:
        pii_note = prompts.PII_SAFETY_NOTE
        session["pii_reminder_shown"] = True
        flags.append("pii_redacted")

    # AIC-US-08 E-02/E-03: gibberish tolerance, then graceful early end. A strong
    # system prompt ("never break character / reveal instructions") already covers
    # prompt-injection resistance (E-03) without extra code here.
    session_ended = False
    if _looks_like_gibberish(redacted_text):
        session["gibberish_strikes"] += 1
        flags.append("gibberish")
        if session["gibberish_strikes"] >= GIBBERISH_STRIKE_LIMIT:
            session["status"] = "abandoned"
            session["completed_at"] = now
            session_ended = True

    # AIC-US-04: grammar chip (opt-in, suppressed in voice mode).
    show_corrections = req.show_corrections if req.show_corrections is not None else session["show_corrections"]
    chip_result = {"chip": None, "suppressed_reason": None}
    if not session_ended and redacted_text:
        chip_result = await grammar_checker.get_correction_chip(
            redacted_text, show_corrections=show_corrections, is_voice_mode=(req.input_mode == "audio"),
        )

    session["turns"].append({
        "role": "user", "content": redacted_text, "input_mode": req.input_mode,
        "correction_chip": chip_result["chip"], "created_at": now,
        # Word-level timing from the STT agent, kept for pronunciation_coach's
        # word-level scoring/highlighting (US-79) — the turn itself doesn't use it.
        "duration_seconds": req.audio_features.duration_seconds if req.audio_features else 0.0,
        "word_timings": req.audio_features.word_timings if req.audio_features else [],
    })

    # PDG-US-11: if this session was started via the Daily Challenge redirect, this is
    # what starts that challenge's 5-minute timer (first prompt only — a no-op on later
    # turns or on sessions with no linked challenge). Best-effort: a daily-challenge
    # bookkeeping failure must never break sending a conversation message.
    try:
        from services.daily_challenge_service import on_conversation_prompt

        await on_conversation_prompt(user_id, session_id, now)
    except Exception as exc:
        logger.warning("Daily Challenge prompt-timer update failed silently: %s", exc)

    if session_ended:
        reply = "Let's pause here for now — thanks for practicing today."
    else:
        session["recent_user_texts"].append(redacted_text)
        await _maybe_adjust_level(session)
        system_prompt = _build_system_prompt(session, safety_note=pii_note)
        # ai_client.generate() takes one flattened user_message, not a message array
        # (same convention interview_coach_service._transcript_text uses) — pass the
        # whole turn history as one block so multi-turn context/topic-steering holds.
        reply = await ai_client.generate(
            system_prompt=system_prompt, user_message=_transcript_text(session), max_tokens=250,
        )

    session["turns"].append({"role": "assistant", "content": reply, "input_mode": None,
                             "correction_chip": None, "created_at": _now()})
    await kv_store.store.update(NAMESPACE, session_id, session)

    # US-152: Silently detect code-switched words and log to the personal word list.
    # Runs after the reply is already saved — never blocks the user-facing response.
    if not session_ended:
        try:
            detector = TextCodeSwitchDetector()
            detection = await detector.detect(text)
            for flagged in detection.get("flagged", []):
                await log_detected_word(
                    user_id=user_id,
                    word=flagged["token"],
                    english_equivalent=flagged["suggestion"],
                    context_sentence=text,
                )
        except Exception as exc:
            # Never let detection errors surface to the user.
            logger.warning("US-152 code-switch detection failed silently: %s", exc)

    return {
        "session_id": session_id, "reply": reply, "level": session["level"],
        "correction_chip": chip_result["chip"], "flags": flags, "session_ended": session_ended,
    }


# ── Voice mode: WebSocket transport (backend/lib/voice_ws.py) ──────────────────
# "timed": Conversation attaches word_timings + duration_seconds to the outgoing
# message for pronunciation scoring (US-79/74) — the only caller that needs those.
async def voice_socket(websocket: WebSocket, session_id: str):
    user_id = await ws_require_auth(websocket)
    if user_id is None:
        return  # ws_require_auth already closed the socket

    gate = await _require_access(user_id)
    if gate:
        await websocket.close(code=4403, reason="Feature not accessible")
        return

    try:
        await _get_session(session_id, user_id)
    except SessionNotFoundError:
        await websocket.close(code=4404, reason="Conversation session not found")
        return

    await websocket.accept()
    # partial_interval_s: live-preview text streams in while the user keeps talking,
    # instead of nothing appearing until the utterance ends.
    await voice_ws.serve(websocket, mode="timed", partial_interval_s=1.2)


async def _agent_send_message(session_id: str, req: SendMessageSchema, secret: Optional[str]) -> Dict:
    """Internal-only intake for a trusted server-side caller — not a browser caller, so
    it can't hold the user's auth cookie. Trusted via a shared secret instead, and the
    user_id is read from the session itself, never taken from the caller."""
    expected = os.environ.get("INTERNAL_AGENT_SECRET")
    if not expected or secret != expected:
        raise AuthError("Invalid internal secret")

    session = await kv_store.store.get(NAMESPACE, session_id)
    if session is None:
        raise SessionNotFoundError(f"Conversation session {session_id} not found")

    return await _send_message(session["user_id"], session_id, req)


# ── end session: score + memory extraction ─────────────────────────────────────
async def _end_session(user_id: str, session_id: str) -> Dict:
    session = await _get_session(session_id, user_id)
    if session["status"] not in ("active",):
        raise InvalidSubmissionError("Session already ended")

    user_turns = [t for t in session["turns"] if t["role"] == "user"]
    full_text = " ".join(t["content"] for t in user_turns)
    has_audio_turn = any(t["input_mode"] == "audio" for t in user_turns)

    if has_audio_turn:
        per_turn = [
            AudioFeatures(transcript=t["content"], duration_seconds=t.get("duration_seconds", 0.0),
                          word_timings=t.get("word_timings", []))
            for t in user_turns
        ]
        scored = session_scorer.score_audio_session(
            session_scorer.aggregate_audio_turns(per_turn), strict=True
        )
    else:
        scored = session_scorer.score_text_session(full_text, strict=True)

    # Did the learner actually converse about the topic they picked? The session's topic
    # was never compared with anything they said, so a session spent ignoring it scored
    # identically to one spent on it. `_looks_like_gibberish` caught only crude patterns
    # and, on a strike-out, still let the session be scored on the way through.
    judgement = await relevance.assess(
        _topic_label(session), full_text,
        context="an open-ended English conversation-practice session on this topic",
    )
    # Delivery fluency/vocabulary are measured from the turns themselves and remain a real
    # score without the LLM, so this stays "scored" — unlike the baseline assessment, where
    # the judgement IS the score. An ungraded topic check just leaves the scores unscaled
    # and `topic_relevance` null, which is the narrower and more honest claim.
    scoring_status = relevance.STATUS_SCORED
    if judgement.graded:
        scored = session_scorer.ScoredSession(
            fluency_score=relevance.apply(scored.fluency_score, judgement.relevance) or 0.0,
            vocabulary_score=relevance.apply(scored.vocabulary_score, judgement.relevance) or 0.0,
            pronunciation_score=relevance.apply(scored.pronunciation_score, judgement.relevance),
            is_text_only=scored.is_text_only,
            delivery=scored.delivery,
        )

    duration = (_now() - session["started_at"]).total_seconds()
    session["status"] = "completed"
    session["completed_at"] = _now()
    # Persisted (not just returned) so a later accent re-baseline request (US-84)
    # can reuse this session's real scores instead of re-scoring or accepting
    # client-supplied numbers.
    session["fluency_score"] = scored.fluency_score
    session["vocabulary_score"] = scored.vocabulary_score
    session["pronunciation_score"] = scored.pronunciation_score
    await kv_store.store.update(NAMESPACE, session_id, session)

    new_facts = await _extract_and_store_facts(user_id, [t["content"] for t in user_turns])

    # Feed into the generic cross-session memory profile (AIC-US-05/06 shared infra).
    try:
        from services.session_memory_service import _record_session
        from schemas.session_memory_schemas import RecordSessionRequest

        await _record_session(user_id, RecordSessionRequest(
            session_id=session_id, session_type="conversation",
            flags_seen=[], topic_or_mode=_topic_label(session),
            overall_score=int(round(scored.fluency_score)),
        ))
    except Exception:
        pass  # best-effort — conversation scoring must not fail because memory logging did

    # US-84/US-83: record this session's real scores as an accent-assessment drill
    # so accent-profile staleness/dispute have real data to operate on.
    try:
        from services.accent_assessment_service import record_conversation_drill

        await record_conversation_drill(
            user_id, session_id,
            {"fluency": scored.fluency_score, "vocabulary": scored.vocabulary_score,
             "pronunciation": scored.pronunciation_score},
        )
    except Exception:
        pass  # best-effort — conversation scoring must not fail because accent logging did

    return {
        "session_id": session_id, "status": session["status"], "duration_seconds": duration,
        "scoring_status": scoring_status,
        "topic_relevance": judgement.relevance,
        "fluency_score": scored.fluency_score, "vocabulary_score": scored.vocabulary_score,
        "pronunciation_score": scored.pronunciation_score, "level": session["level"],
        "new_memory_facts": new_facts,
    }


# ── AIC-US-02: transcript review ────────────────────────────────────────────────
async def _get_transcript(user_id: str, session_id: str) -> Dict:
    session = await _get_session(session_id, user_id)
    return {
        "session_id": session_id, "topic_label": _topic_label(session), "status": session["status"],
        "turns": session["turns"],
        "incomplete": session["status"] == "abandoned",
    }


async def _list_sessions(user_id: str) -> List[Dict]:
    mine = [s for s in await kv_store.store.list_values(NAMESPACE) if s["user_id"] == user_id]
    mine.sort(key=lambda s: s["started_at"], reverse=True)
    return [
        {
            "session_id": s["session_id"], "topic_label": _topic_label(s), "status": s["status"],
            "started_at": s["started_at"], "completed_at": s["completed_at"],
        }
        for s in mine
    ]


# ── AIC-US-06: memory facts management ──────────────────────────────────────────
async def _list_memory_facts(user_id: str) -> List[Dict]:
    memory = await _get_memory(user_id)
    return memory["facts"]


async def _delete_memory_fact(user_id: str, fact_id: str) -> Dict:
    memory = await _get_memory(user_id)
    remaining = [f for f in memory["facts"] if f["fact_id"] != fact_id]
    if len(remaining) == len(memory["facts"]):
        raise SessionNotFoundError(f"Memory fact {fact_id} not found")
    memory["facts"] = remaining
    await kv_store.store.update(MEMORY_NS, user_id, memory)
    return {"fact_id": fact_id, "deleted": True}


async def _set_memory_opt_out(user_id: str, enabled: bool) -> Dict:
    """E-02: opting out purges existing facts (immediately here — "within 24 hours" in
    the story accommodates an async job; there is no such job in this codebase, so this
    purges synchronously, which satisfies the requirement with a tighter bound)."""
    memory = await _get_memory(user_id)
    memory["opted_out"] = enabled
    if enabled:
        memory["facts"] = []
    if await kv_store.store.get(MEMORY_NS, user_id) is None:
        await kv_store.store.create(MEMORY_NS, user_id, memory)
    else:
        await kv_store.store.update(MEMORY_NS, user_id, memory)
    return {"opted_out": enabled, "facts": memory["facts"]}


# ── AIC-US-16: TTS ──────────────────────────────────────────────────────────────
def synthesize_speech(text: str, length_scale: float = 1.0) -> bytes:
    return tts_client.synthesize(text, length_scale=length_scale)


# ═══════════════════════════════════════════════════════════════════════════════
# FastAPI controllers
# ═══════════════════════════════════════════════════════════════════════════════
async def list_topics(user_id: str = Depends(require_auth)):
    return {"topics": [{"key": k, "label": v} for k, v in prompts.TOPICS.items()]}


async def check_topic(topic: str, user_id: str = Depends(require_auth)):
    return await validate_topic(topic)


async def start_session(payload: StartConversationSchema, user_id: str = Depends(require_auth)):
    gate = await _require_access(user_id)
    if gate:
        return gate
    return await _start_session(user_id, payload)


async def send_message(session_id: str, payload: SendMessageSchema, user_id: str = Depends(require_auth)):
    return await _send_message(user_id, session_id, payload)


async def agent_send_message(
    session_id: str,
    payload: SendMessageSchema,
    x_internal_secret: Optional[str] = Header(None),
):
    return await _agent_send_message(session_id, payload, x_internal_secret)


async def end_session(session_id: str, user_id: str = Depends(require_auth)):
    return await _end_session(user_id, session_id)


async def get_transcript(session_id: str, user_id: str = Depends(require_auth)):
    return await _get_transcript(user_id, session_id)


async def list_sessions(user_id: str = Depends(require_auth)):
    return {"sessions": await _list_sessions(user_id)}


async def list_memory_facts(user_id: str = Depends(require_auth)):
    return {"facts": await _list_memory_facts(user_id)}


async def delete_memory_fact(fact_id: str, user_id: str = Depends(require_auth)):
    return await _delete_memory_fact(user_id, fact_id)


async def set_memory_opt_out(payload: MemoryOptOutSchema, user_id: str = Depends(require_auth)):
    return await _set_memory_opt_out(user_id, payload.enabled)


async def text_to_speech(payload: TTSRequestSchema, user_id: str = Depends(require_auth)):
    if not tts_client.is_configured():
        return JSONResponse(status_code=503, content={
            "error": "TTS engine unavailable. Fall back to your device's native text-to-speech.",
        })
    try:
        audio = synthesize_speech(payload.text, payload.length_scale)
    except tts_client.TTSError as e:
        return JSONResponse(status_code=503, content={"error": str(e)})
    return Response(content=audio, media_type="audio/wav")
