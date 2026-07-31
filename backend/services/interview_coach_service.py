"""
Interview Coach (US-45 base, US-40 panel, US-42 case study, US-43 multi-round,
US-44 mentor/peer review sharing).

Ported from speeky/interview_coach.py into backend conventions: persistence via
lib.kv_store (async), LLM via lib.ai_client, errors via utils.feature_errors, auth via
require_auth. Session state is a nested dict persisted as one KvEntry blob — the rich
turn/round/case logic is preserved verbatim; only the store/LLM calls became awaited and
ownership checks were added (a user may only act on their own sessions; only a share's
creator may revoke it).
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import Depends, WebSocket
from fastapi.responses import JSONResponse

from lib import ai_client, explore_sessions, kv_store, voice_ws
from middlewares.auth_middleware import require_auth, ws_require_auth
from schemas.interview_coach_schemas import (
    AIExchange,
    AnswerRequest,
    AnswerResponse,
    InterviewMode,
    PauseSessionRequest,
    PeerComment,
    PeerCommentRequest,
    RoundScorecard,
    SessionFeedback,
    SessionStartResponse,
    SessionStatus,
    ShareReviewRequest,
    ShareReviewResponse,
    StartSessionRequest,
    TakeBreakRequest,
)
from utils.feature_errors import (
    InvalidSubmissionError,
    SessionAlreadyEndedError,
    SessionNotFoundError,
)

# ── settings (were app.core.config) ───────────────────────────────────────────
MULTI_ROUND_DEFAULT_ROUNDS = [InterviewMode.STANDARD, InterviewMode.PANEL, InterviewMode.CASE_STUDY]
RAMBLING_SECONDS_THRESHOLD = 180
SHORT_ANSWER_WORD_THRESHOLD = 3
SILENCE_SECONDS_THRESHOLD = 10

NAMESPACE = "interview_coach_sessions"
SHARE_NAMESPACE = "interview_coach_shares"
COMMENT_NAMESPACE = "interview_coach_comments"

GENERAL_BEHAVIORAL_QUESTIONS = [
    "Tell me about a time you solved a difficult problem under pressure.",
    "Describe a situation where you had to work with a difficult teammate.",
    "What is a professional achievement you're most proud of?",
]

CASE_JUMP_TO_NUMBER_MIN_WORDS = 12
CASE_STRUCTURE_KEYWORDS = [
    "segment", "assume", "let's break", "first,", "start by", "population",
    "framework", "bucket", "categor", "estimate", "roughly", "on average",
]
CASE_STUDY_DIFFICULTY_HINTS = {
    "easy": "Keep the scenario simple and concrete, with few moving parts.",
    "medium": "Give the scenario a realistic amount of ambiguity typical of a first-round case interview.",
    "hard": "Make the scenario multi-layered, with at least one non-obvious wrinkle the candidate needs to uncover.",
}
CASE_STUDY_PROMPTS = {
    "market_sizing": (
        "Let's do a market-sizing case. Estimate how many artisanal coffee shops "
        "could realistically be supported in a mid-sized city of about 300,000 people. "
        "Walk me through your approach — I'll fill in any numbers you need as you ask."
    ),
    "brainteaser": (
        "Here's a brainteaser: How many piano tuners are there in a city of 5 million people? "
        "Think out loud — I want to hear your reasoning, not just a final number."
    ),
    "business_case": (
        "Our client is a mid-sized ride-sharing company considering entering a new "
        "international market. Revenue growth has plateaued domestically. "
        "How would you structure your recommendation on whether to expand?"
    ),
}
DEFAULT_MULTI_ROUND_PANELISTS = [
    {"name": "Jordan", "persona_tone": "formal_panel", "focus_area": "role fit and communication"},
    {"name": "Casey", "persona_tone": "strict_corporate", "focus_area": "technical depth"},
]
CLOSING_MESSAGE_TEMPLATES = {
    InterviewMode.STANDARD: "That wraps up our interview — thank you for your thoughtful answers today. Take a look below for your detailed feedback.",
    InterviewMode.PANEL: "That concludes the panel interview — thank you for your time, and for engaging with all of us today. You'll find feedback from each interviewer below.",
    InterviewMode.CASE_STUDY: "That's a wrap on this case — nice work walking through it with me. Take a look at your structure and numeracy feedback below.",
    InterviewMode.MULTI_ROUND: "That completes your full Interview Day — thank you for sticking with it through every round. Your consolidated feedback and performance trend are below.",
}
TECHNICAL_DEPTH_KEYWORDS = [
    "algorithm", "architecture", "database", "api", "system design", "code", "codebase",
    "performance", "scalability", "latency", "framework", "backend", "frontend", "infrastructure",
]
SOFT_SKILL_ONLY_KEYWORDS = ["team", "communicat", "collaborat", "people", "culture", "leadership"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# ── pure helpers ──────────────────────────────────────────────────────────────
def _current_round_type(session: dict) -> InterviewMode:
    if session["mode"] != InterviewMode.MULTI_ROUND:
        return session["mode"] if isinstance(session["mode"], InterviewMode) else InterviewMode(session["mode"])
    rounds = session["rounds"]
    idx = min(session["current_round_index"], len(rounds) - 1)
    r = rounds[idx]
    return r if isinstance(r, InterviewMode) else InterviewMode(r)


def _classify_answer(req: AnswerRequest) -> List[str]:
    """E-02 rambling / E-03 one-word / prolonged-silence detection."""
    flags = []
    word_count = len(req.answer_text.split())
    if req.response_duration_seconds > RAMBLING_SECONDS_THRESHOLD:
        flags.append("rambling")
    if word_count <= SHORT_ANSWER_WORD_THRESHOLD:
        flags.append("one_word_answer")
    if req.silence_before_seconds > SILENCE_SECONDS_THRESHOLD:
        flags.append("prolonged_silence")
    return flags


def _next_panel_speaker(session: dict) -> str:
    panelists = session["panelists"]
    if not panelists:
        return "AI"
    idx = len([e for e in session["exchanges"] if e.get("answer")]) % len(panelists)
    return panelists[idx]["name"]


def _panelist_for_last_question(session: dict) -> Optional[dict]:
    exchanges = session["exchanges"]
    if not exchanges:
        return None
    speaker_name = exchanges[-1]["speaker"]
    for p in session["panelists"]:
        if p["name"] == speaker_name:
            return p
    return None


def _is_vague_technical_answer(session: dict, answer_text: str) -> bool:
    """GAP-02 E-02: soft-skills-only answer to a technical persona."""
    panelist = _panelist_for_last_question(session)
    if not panelist or "technical" not in panelist["focus_area"].lower():
        return False
    lowered = answer_text.lower()
    has_technical = any(kw in lowered for kw in TECHNICAL_DEPTH_KEYWORDS)
    has_soft_only = any(kw in lowered for kw in SOFT_SKILL_ONLY_KEYWORDS)
    return has_soft_only and not has_technical


def _classify_case_answer(session: dict, answer_text: str) -> List[str]:
    """US-42: jumped_to_number (E-01) / clarifying_question (E-06)."""
    flags = []
    word_count = len(answer_text.split())
    has_digit = any(ch.isdigit() for ch in answer_text)
    has_structure_language = any(kw in answer_text.lower() for kw in CASE_STRUCTURE_KEYWORDS)
    prior_answers = [e.get("answer", "") for e in session["exchanges"] if e.get("answer")]
    prior_showed_structure = any(
        len(a.split()) > 20 or any(kw in a.lower() for kw in CASE_STRUCTURE_KEYWORDS)
        for a in prior_answers[:-1]
    )
    if has_digit and word_count < CASE_JUMP_TO_NUMBER_MIN_WORDS and not has_structure_language and not prior_showed_structure:
        flags.append("jumped_to_number")
    if answer_text.strip().endswith("?"):
        flags.append("clarifying_question")
    return flags


def _persona_description(session: dict) -> str:
    round_type = _current_round_type(session)
    tone = session["persona_tone"]
    tone_val = tone.value if hasattr(tone, "value") else str(tone)
    prefix = "Round of a multi-round Interview Day — " if session["mode"] == InterviewMode.MULTI_ROUND else ""
    if round_type == InterviewMode.PANEL:
        names = ", ".join(p["name"] for p in session["panelists"]) or "the panel"
        return f"{prefix}a panel interview with {names}, tone: {tone_val}"
    if round_type == InterviewMode.CASE_STUDY:
        constraints = session.get("case_established_constraints", [])
        locked = f" Constraints already established (keep these fixed): {'; '.join(constraints)}." if constraints else ""
        return f"{prefix}a {session.get('case_type', 'business_case').replace('_', ' ')} case interview, tone: {tone_val}.{locked}"
    return f"{prefix}a standard behavioral interview, tone: {tone_val}"


def _transcript_text(session: dict) -> str:
    lines = []
    for e in session["exchanges"]:
        lines.append(f"{e['speaker']}: {e['question']}")
        if e.get("answer"):
            lines.append(f"Candidate: {e['answer']}")
    return "\n".join(lines)


def _closing_message(session: dict) -> str:
    mode = session["mode"] if isinstance(session["mode"], InterviewMode) else InterviewMode(session["mode"])
    return CLOSING_MESSAGE_TEMPLATES.get(mode, "That wraps up your interview — thank you for your time today.")


# ── scoring (pure) ────────────────────────────────────────────────────────────
def _score_round(round_type: InterviewMode, exchanges: List[dict]) -> RoundScorecard:
    flags = [f for e in exchanges for f in e.get("flags", [])]
    base = 85 - 15 * flags.count("rambling") - 20 * flags.count("one_word_answer")
    base = max(base, 10)
    summary = "Solid, structured answers." if base >= 70 else "Answers need more structure and specific examples."
    return RoundScorecard(round_type=round_type, scores={"clarity": base, "structure": base - 5, "relevance": base + 5}, summary=summary)


def _score_panel_rounds(session: dict) -> List[RoundScorecard]:
    cards = []
    for panelist in session["panelists"]:
        name = panelist["name"]
        their = [e for e in session["exchanges"] if e["speaker"] == name and e.get("answer")]
        flags = [f for e in their for f in e.get("flags", [])]
        base = 85 - 15 * flags.count("rambling") - 20 * flags.count("one_word_answer") - 15 * flags.count("vague_technical_answer")
        base = max(base, 10)
        summary = (f"Answered {name}'s ({panelist['focus_area']}) questions well."
                   if base >= 70 else
                   f"Needs stronger answers when addressing {name}'s ({panelist['focus_area']}) questions.")
        cards.append(RoundScorecard(round_type=InterviewMode.PANEL, scores={f"{name}_score": base}, summary=summary))
    return cards


def _score_case_round(session: dict) -> RoundScorecard:
    flags = session.get("case_flags_log", [])
    jumped = flags.count("jumped_to_number")
    off_framework = flags.count("rambling")
    clarifying = flags.count("clarifying_question")
    structure_score = max(90 - (jumped * 25) - (off_framework * 20), 10)
    numeracy_score = max(90 - (jumped * 10), 20)
    communication_score = max(90 - (flags.count("prolonged_silence") * 15) + min(clarifying * 3, 9), 15)
    total_turns = len([e for e in session["exchanges"] if e.get("answer")])
    total_flags = len(flags)
    recalibration = None
    if total_turns <= 2 and total_flags == 0:
        recalibration = "Finished quickly with no issues — consider a harder difficulty next case."
    elif total_flags >= 3:
        recalibration = "Struggled significantly this case — consider an easier difficulty next time."
    summary = "Sound framework and clear assumptions." if structure_score >= 70 else "Needs a clearer upfront structure before diving into numbers."
    if recalibration:
        summary += f" {recalibration}"
    return RoundScorecard(
        round_type=InterviewMode.CASE_STUDY,
        scores={"structure": structure_score, "numeracy": numeracy_score, "communication_of_assumptions": communication_score},
        summary=summary,
    )


def _score_multi_round(session: dict) -> List[RoundScorecard]:
    rounds = session["rounds"]
    boundaries = session["round_boundaries"]
    exchanges = session["exchanges"]
    cards = []
    for i, r in enumerate(rounds[:len(boundaries)]):
        round_type = r if isinstance(r, InterviewMode) else InterviewMode(r)
        start = boundaries[i]
        end = boundaries[i + 1] if i + 1 < len(boundaries) else len(exchanges)
        cards.append(_score_round(round_type, exchanges[start:end]))
    if len(cards) >= 2:
        clarities = [sc.scores.get("clarity", 0) for sc in cards]
        if clarities[-1] > clarities[0] + 5:
            trend = "Performance improved over the course of the day."
        elif clarities[-1] < clarities[0] - 5:
            trend = "Performance declined across successive rounds — likely fatigue."
        else:
            trend = "Performance held steady across all rounds."
        cards[-1].summary += f" {trend}"
    if session.get("breaks_skipped") or session.get("break_pending"):
        cards[-1].summary += " Note: no recovery break was taken between one or more rounds."
    return cards


# ── async helpers (LLM + persistence) ─────────────────────────────────────────
async def _generate_case_opening(case_type: str, difficulty: str = "medium") -> str:
    """US-42: AI-generated fresh case opening, with a static-anchor fallback."""
    anchor = CASE_STUDY_PROMPTS.get(case_type, CASE_STUDY_PROMPTS["market_sizing"])
    difficulty_hint = CASE_STUDY_DIFFICULTY_HINTS.get(difficulty, CASE_STUDY_DIFFICULTY_HINTS["medium"])
    try:
        return await ai_client.generate(
            system_prompt=(
                "You are a case-study interviewer opening a fresh case for a candidate. "
                f"Write ONE short opening scenario in the spirit of this reference case: \"{anchor}\" — "
                "keep the SAME core topic/keyword from that reference, but vary the specific details, "
                f"numbers, or framing so it feels fresh. {difficulty_hint} "
                "End with an open invitation for them to start structuring their approach. No preamble."
            ),
            user_message="Generate the case opening.",
            max_tokens=300,
        )
    except Exception:
        return anchor


async def _round_opening_message(session: dict, round_type: InterviewMode, round_number: int) -> str:
    label = f"Round {round_number}: {round_type.value.replace('_', ' ').title()}. "
    if round_type == InterviewMode.CASE_STUDY:
        briefing = await _generate_case_opening(session.get("case_type", "market_sizing"), session.get("case_difficulty", "medium"))
        return f"{label}{briefing}"
    if round_type == InterviewMode.PANEL:
        panelists = session.get("panelists") or []
        first_name = panelists[0]["name"] if panelists else "the panel"
        return f"{label}({first_name}) Let's start — tell us a bit about your background and why you're a fit for this role."
    return f"{label}Let's continue — walk me through your resume."


async def _opening_question(req: StartSessionRequest) -> str:
    if req.mode == InterviewMode.CASE_STUDY:
        return await _generate_case_opening(req.case_type or "market_sizing", req.case_difficulty or "medium")
    if req.mode == InterviewMode.PANEL:
        first = req.panelists[0]
        return f"({first.name}) Let's start — tell us a bit about your background and why you're a fit for this role."
    if req.mode == InterviewMode.MULTI_ROUND:
        rounds = req.rounds or [InterviewMode.STANDARD]
        temp_session = {
            "case_type": req.case_type or "market_sizing",
            "case_difficulty": req.case_difficulty or "medium",
            "panelists": [p.model_dump() for p in req.panelists] if req.panelists else DEFAULT_MULTI_ROUND_PANELISTS,
        }
        return f"Welcome to your Interview Day. {await _round_opening_message(temp_session, rounds[0], 1)}"
    if not req.role_or_major:
        return GENERAL_BEHAVIORAL_QUESTIONS[0]  # E-01: fallback
    return f"Let's begin. Tell me why you're interested in the {req.role_or_major} position."


async def _get_session(session_id: str, user_id: str) -> dict:
    session = await kv_store.store.get(NAMESPACE, session_id)
    if session is None or session.get("user_id") != user_id:
        raise SessionNotFoundError(f"Session {session_id} not found")
    return session


# ── Voice mode: WebSocket transport ──────────────────
async def voice_socket(websocket: WebSocket, session_id: str):
    user_id = await ws_require_auth(websocket)
    if user_id is None:
        return  # ws_require_auth already closed the socket

    try:
        await _get_session(session_id, user_id)
    except SessionNotFoundError:
        await websocket.close(code=4404, reason="Interview session not found")
        return

    await websocket.accept()
    await voice_ws.serve(websocket, mode="transcript")


async def _generate_next_question(session: dict, speaker: str, instruction: str) -> str:
    system_prompt = (
        f"You are conducting {_persona_description(session)}. You are '{speaker}'. "
        "Read the conversation so far and ask ONE natural follow-up question that responds "
        f"specifically to the candidate's last answer. {instruction} "
        "Keep it to 1-2 sentences, no preamble, just the question."
    )
    return await ai_client.generate(system_prompt=system_prompt, user_message=_transcript_text(session), max_tokens=600)


async def _advance_round(session: dict):
    exchanges = session["exchanges"]
    mode = session["mode"] if isinstance(session["mode"], InterviewMode) else InterviewMode(session["mode"])
    rounds = session["rounds"]
    session["current_round_index"] += 1
    next_question = None
    next_speaker = "AI"
    session_complete = False

    if mode == InterviewMode.MULTI_ROUND and session["current_round_index"] < len(rounds):
        if session.get("break_pending"):
            session["breaks_skipped"].append(session["current_round_index"] - 1)  # E-02
        session["break_pending"] = True
        session["round_boundaries"].append(len(exchanges))
        next_round_type = rounds[session["current_round_index"]]
        next_round_type = next_round_type if isinstance(next_round_type, InterviewMode) else InterviewMode(next_round_type)
        next_question = await _round_opening_message(session, next_round_type, session["current_round_index"] + 1)
        if next_round_type == InterviewMode.PANEL:
            panelists = session.get("panelists") or []
            next_speaker = panelists[0]["name"] if panelists else "AI"
        exchanges.append(AIExchange(speaker=next_speaker, question=next_question).model_dump())
    else:
        session_complete = True
        session["status"] = SessionStatus.COMPLETED
        session["ended_at"] = _now()
        next_question = _closing_message(session)
        session["exchanges"].append(AIExchange(speaker="AI", question=next_question).model_dump())

    return next_question, next_speaker, True, session_complete


async def _handle_case_study_turn(session: dict, req: AnswerRequest, session_id: str, generic_flags: List[str]) -> AnswerResponse:
    exchanges = session["exchanges"]
    case_flags = _classify_case_answer(session, req.answer_text)
    all_flags = generic_flags + case_flags
    session["case_flags_log"].extend(all_flags)

    async def _reply(question: str) -> AnswerResponse:
        exchanges.append(AIExchange(speaker="AI", question=question).model_dump())
        await kv_store.store.update(NAMESPACE, session_id, session)
        return AnswerResponse(session_id=session_id, next_question=question, next_speaker="AI", flags=all_flags)

    if "prolonged_silence" in generic_flags:  # E-03
        return await _reply(await _generate_next_question(
            session, "AI",
            "The candidate has been silent while structuring the case. Offer one gentle scaffolding "
            "hint toward a starting segmentation, without giving away the answer."))
    if "jumped_to_number" in case_flags:  # E-01
        return await _reply(await _generate_next_question(
            session, "AI",
            "The candidate stated a final number without showing their reasoning. Do NOT accept it yet — "
            "ask them to walk back through their segmentation logic and assumptions first, politely but firmly."))
    if "clarifying_question" in case_flags:  # E-06
        constraint = await _generate_next_question(
            session, "AI",
            "The candidate asked a clarifying question. Improvise one concrete, reasonable constraint or data "
            "point that answers it directly. Keep it short and specific — treated as fixed for the rest of the case.")
        session["case_established_constraints"].append(constraint)
        return await _reply(constraint)
    if "rambling" in generic_flags:  # E-04
        return await _reply(await _generate_next_question(
            session, "AI",
            "The candidate went off-track from structuring the problem. Gently redirect them back to building "
            "out their framework — don't just ask for a summary."))

    boundary = session["round_boundaries"][-1]
    round_complete = len([e for e in exchanges[boundary:] if e.get("answer")]) >= 3
    session_complete = False
    next_speaker = "AI"
    if round_complete:
        follow_up, next_speaker, round_complete, session_complete = await _advance_round(session)
    else:
        follow_up = await _generate_next_question(
            session, "AI",
            "Continue the case. Either inject a realistic follow-up constraint/data point as a real case "
            "interviewer would, or probe the next layer of their framework.")
        exchanges.append(AIExchange(speaker="AI", question=follow_up).model_dump())
    await kv_store.store.update(NAMESPACE, session_id, session)
    return AnswerResponse(session_id=session_id, next_question=follow_up, next_speaker=next_speaker,
                          flags=all_flags, round_complete=round_complete, session_complete=session_complete)


# ── entry service functions ───────────────────────────────────────────────────
async def _start_session(user_id: str, req: StartSessionRequest) -> SessionStartResponse:
    # A fresh start supersedes any other open Explore-group session this user has
    # running elsewhere — see lib/explore_sessions.py.
    await explore_sessions.supersede_open_explore_sessions(user_id)

    session_id = _new_id("sess")
    now = _now()
    rounds = req.rounds or ([req.mode] if req.mode != InterviewMode.MULTI_ROUND else MULTI_ROUND_DEFAULT_ROUNDS)
    panelists = [p.model_dump() for p in req.panelists] if req.panelists else []
    if not panelists and InterviewMode.PANEL in rounds:
        panelists = DEFAULT_MULTI_ROUND_PANELISTS

    session_state = {
        "session_id": session_id, "user_id": user_id, "mode": req.mode, "status": SessionStatus.ACTIVE,
        "persona_tone": req.persona_tone, "panelists": panelists, "rounds": rounds,
        "current_round_index": 0, "exchanges": [], "started_at": now, "ended_at": None,
        "case_type": req.case_type or "market_sizing", "case_difficulty": req.case_difficulty or "medium",
        "case_established_constraints": [], "case_flags_log": [],
        "breaks_skipped": [], "round_boundaries": [0], "break_pending": False,
    }
    opening = await _opening_question(req)
    opening_speaker = req.panelists[0].name if req.mode == InterviewMode.PANEL and req.panelists else "AI"
    if req.mode == InterviewMode.MULTI_ROUND and rounds[0] == InterviewMode.PANEL:
        opening_speaker = panelists[0]["name"] if panelists else "AI"
    session_state["exchanges"].append(AIExchange(speaker=opening_speaker, question=opening).model_dump())
    await kv_store.store.create(NAMESPACE, session_id, session_state)

    current_round = None
    if req.mode == InterviewMode.MULTI_ROUND:
        current_round = rounds[0].value if hasattr(rounds[0], "value") else str(rounds[0])
    return SessionStartResponse(
        session_id=session_id, mode=req.mode, status=SessionStatus.ACTIVE,
        current_round=current_round, opening_question=opening, started_at=now,
    )


async def _submit_answer(user_id: str, session_id: str, req: AnswerRequest) -> AnswerResponse:
    session = await _get_session(session_id, user_id)
    if session["status"] == SessionStatus.COMPLETED:
        raise SessionAlreadyEndedError("Cannot submit an answer to a completed session")
    if not req.answer_text.strip():
        raise InvalidSubmissionError("answer_text cannot be empty")

    flags = _classify_answer(req)
    exchanges = session["exchanges"]
    if exchanges and exchanges[-1].get("answer") is None:
        exchanges[-1]["answer"] = req.answer_text
        exchanges[-1]["flags"] = flags

    current_round_type = _current_round_type(session)
    if current_round_type == InterviewMode.CASE_STUDY:
        return await _handle_case_study_turn(session, req, session_id, flags)

    if "one_word_answer" in flags:
        follow_up = await _generate_next_question(session, "AI", "Their answer was too short — politely ask them to elaborate with a specific example.")
        exchanges.append(AIExchange(speaker="AI", question=follow_up).model_dump())
        await kv_store.store.update(NAMESPACE, session_id, session)
        return AnswerResponse(session_id=session_id, next_question=follow_up, next_speaker="AI", flags=flags)

    if "rambling" in flags:
        follow_up = await _generate_next_question(session, "AI", "Their answer ran long — acknowledge it, then ask them to summarize the main point in one sentence.")
        exchanges.append(AIExchange(speaker="AI", question=follow_up).model_dump())
        await kv_store.store.update(NAMESPACE, session_id, session)
        return AnswerResponse(session_id=session_id, next_question=follow_up, next_speaker="AI", flags=flags)

    if current_round_type == InterviewMode.PANEL and _is_vague_technical_answer(session, req.answer_text):
        speaker = _panelist_for_last_question(session)["name"]
        follow_up = await _generate_next_question(
            session, speaker,
            "Their answer was soft-skills-focused with no technical substance, but you are the Technical Lead — "
            "push back in character and ask for concrete technical detail.")
        exchanges.append(AIExchange(speaker=speaker, question=follow_up).model_dump())
        await kv_store.store.update(NAMESPACE, session_id, session)
        flags = flags + ["vague_technical_answer"]
        return AnswerResponse(session_id=session_id, next_question=follow_up, next_speaker=speaker, flags=flags)

    boundary = session["round_boundaries"][-1]
    round_complete = len([e for e in exchanges[boundary:] if e.get("answer")]) >= 3
    session_complete = False
    next_speaker = "AI"
    next_question = None
    if round_complete:
        next_question, next_speaker, round_complete, session_complete = await _advance_round(session)
    else:
        if current_round_type == InterviewMode.PANEL:
            next_speaker = _next_panel_speaker(session)
            next_question = await _generate_next_question(session, next_speaker, "Ask a natural follow-up that digs deeper into their last answer, from your persona's focus area.")
        else:
            next_question = await _generate_next_question(session, "AI", "Ask a natural follow-up that digs deeper into their last answer.")
        exchanges.append(AIExchange(speaker=next_speaker, question=next_question).model_dump())
    await kv_store.store.update(NAMESPACE, session_id, session)
    return AnswerResponse(session_id=session_id, next_question=next_question, next_speaker=next_speaker,
                          flags=flags, round_complete=round_complete, session_complete=session_complete)


async def _pause_session(user_id: str, session_id: str, reason: str) -> dict:
    session = await _get_session(session_id, user_id)
    if session["status"] == SessionStatus.COMPLETED:
        raise SessionAlreadyEndedError("Cannot pause a completed session")
    session["status"] = SessionStatus.PAUSED
    await kv_store.store.update(NAMESPACE, session_id, session)
    return {"session_id": session_id, "status": SessionStatus.PAUSED.value, "reason": reason}


async def _resume_session(user_id: str, session_id: str) -> dict:
    session = await _get_session(session_id, user_id)
    if session["status"] != SessionStatus.PAUSED:
        raise InvalidSubmissionError("Session is not paused")
    session["status"] = SessionStatus.ACTIVE
    await kv_store.store.update(NAMESPACE, session_id, session)
    return {"session_id": session_id, "status": SessionStatus.ACTIVE.value}


async def _take_break(user_id: str, session_id: str) -> dict:
    """US-43 E-02: explicit break between rounds clears break_pending."""
    session = await _get_session(session_id, user_id)
    session["break_pending"] = False
    await kv_store.store.update(NAMESPACE, session_id, session)
    return {"session_id": session_id, "break_taken": True}


async def _end_session(user_id: str, session_id: str) -> SessionFeedback:
    session = await _get_session(session_id, user_id)
    rounds = session["rounds"]
    mode = session["mode"] if isinstance(session["mode"], InterviewMode) else InterviewMode(session["mode"])
    is_multi_round = mode == InterviewMode.MULTI_ROUND
    completed_all_rounds = not is_multi_round or session["current_round_index"] >= len(rounds) - 1

    if session["status"] != SessionStatus.COMPLETED:
        session["status"] = SessionStatus.COMPLETED if completed_all_rounds else SessionStatus.ABANDONED  # E-01
        session["ended_at"] = _now()
        await kv_store.store.update(NAMESPACE, session_id, session)

    if mode == InterviewMode.CASE_STUDY:
        scorecards = [_score_case_round(session)]
    elif mode == InterviewMode.PANEL:
        scorecards = _score_panel_rounds(session)
    elif is_multi_round:
        scorecards = _score_multi_round(session)
    else:
        scorecards = [_score_round(r if isinstance(r, InterviewMode) else InterviewMode(r), session["exchanges"]) for r in rounds]

    all_scores = [v for sc in scorecards for v in sc.scores.values()]
    overall = int(sum(all_scores) / max(len(all_scores), 1))

    script_instruction = "You are an interview coach producing a concise, actionable before/after rewrite of the user's weakest answer."
    if is_multi_round:
        script_instruction += (
            " This was a multi-round interview day — also note, in one sentence, any contradictions between "
            "what the candidate said in different rounds, if any exist.")
    try:
        script = await ai_client.generate(system_prompt=script_instruction, user_message=str(session["exchanges"]))
    except Exception:
        script = "Feedback script processing... please retry shortly."  # E-05

    closing = ("Looks like you stepped away before finishing — no worries, your progress is saved. "
               "Here's the feedback for what you completed."
               if session["status"] == SessionStatus.ABANDONED else _closing_message(session))
    return SessionFeedback(
        session_id=session_id, mode=mode, closing_message=closing,
        round_scorecards=scorecards, overall_score=overall, actionable_script=script,
        ended_at=session["ended_at"],
    )


# ── US-44 mentor/peer review sharing ──────────────────────────────────────────
async def _share_review(user_id: str, session_id: str, req: ShareReviewRequest) -> ShareReviewResponse:
    await _get_session(session_id, user_id)  # 404s if missing / not owner
    if req.access_level == "full" and not req.content_confirmed:  # E-03
        raise InvalidSubmissionError(
            "Full audio/video sharing requires content_confirmed=true — user must preview and confirm first.")
    share_id = _new_id("share")
    now = _now()
    expires_at = now + timedelta(hours=req.expiry_hours)
    await kv_store.store.create(SHARE_NAMESPACE, share_id, {
        "share_id": share_id, "session_id": session_id, "shared_by_user_id": user_id,
        "recipient": req.recipient_email_or_id, "note": req.note, "access_level": req.access_level,
        "expires_at": expires_at, "revoked": False, "reported_authors": {}, "created_at": now,
    })
    return ShareReviewResponse(
        share_id=share_id, session_id=session_id, shared_with=req.recipient_email_or_id,
        share_link=f"/api/interview-coach/reviews/{share_id}", access_level=req.access_level,
        expires_at=expires_at, created_at=now,
    )


async def _get_active_share(share_id: str) -> dict:
    """E-01 (expired) / E-05 (revoked) checks before any read/write."""
    share = await kv_store.store.get(SHARE_NAMESPACE, share_id)
    if share is None:
        raise SessionNotFoundError(f"Share {share_id} not found")
    if share.get("revoked"):
        raise InvalidSubmissionError("This share link has been revoked by the user.")
    if _now() > share["expires_at"]:
        raise InvalidSubmissionError("This share link has expired. Ask the user to generate a new one.")
    return share


async def _revoke_share(user_id: str, share_id: str) -> dict:
    """E-05: only the share's creator may revoke it."""
    share = await kv_store.store.get(SHARE_NAMESPACE, share_id)
    if share is None or share.get("shared_by_user_id") != user_id:
        raise SessionNotFoundError(f"Share {share_id} not found")
    share["revoked"] = True
    await kv_store.store.update(SHARE_NAMESPACE, share_id, share)
    return {"share_id": share_id, "revoked": True}


async def _add_peer_comment(author_id: str, share_id: str, comment_text: str) -> PeerComment:
    share = await _get_active_share(share_id)
    if not comment_text.strip():
        raise InvalidSubmissionError("comment_text cannot be empty")
    if share["reported_authors"].get(author_id, 0) >= 2:  # E-06
        raise InvalidSubmissionError("This author has been blocked from commenting after repeated reports.")
    comment_id = _new_id("cmt")
    comment = PeerComment(comment_id=comment_id, share_id=share_id, author_id=author_id,
                          comment_text=comment_text, hidden=False, created_at=_now())
    await kv_store.store.create(COMMENT_NAMESPACE, comment_id, comment.model_dump())
    return comment


async def _list_peer_comments(share_id: str) -> List[dict]:
    await _get_active_share(share_id)
    comments = [c for c in await kv_store.store.list_values(COMMENT_NAMESPACE) if c["share_id"] == share_id]
    comments.sort(key=lambda c: c["created_at"])
    return [c for c in comments if not c.get("hidden")]  # E-04


async def _report_comment(user_id: str, comment_id: str) -> dict:
    """E-06: hide the comment + track repeat-abuse blocking on its author."""
    comment = await kv_store.store.get(COMMENT_NAMESPACE, comment_id)
    if comment is None:
        raise SessionNotFoundError(f"Comment {comment_id} not found")
    comment["hidden"] = True
    await kv_store.store.update(COMMENT_NAMESPACE, comment_id, comment)
    share = await kv_store.store.get(SHARE_NAMESPACE, comment["share_id"])
    if share is not None:
        share["reported_authors"][comment["author_id"]] = share["reported_authors"].get(comment["author_id"], 0) + 1
        await kv_store.store.update(SHARE_NAMESPACE, comment["share_id"], share)
    return {"comment_id": comment_id, "hidden": True, "reported_by": user_id}


def _session_state_response(session: dict) -> dict:
    """Read-only session snapshot for resume — no GET-by-id route existed for this
    feature before (the frontend relied entirely on sessionStorage, which doesn't
    survive a fresh navigation from the Explore resume banner)."""
    return {
        "session_id": session["session_id"], "mode": session["mode"], "status": session["status"],
        "exchanges": session["exchanges"], "current_round_index": session["current_round_index"],
        "started_at": session["started_at"].isoformat(),
    }


# ── controllers (auth-gated) ──────────────────────────────────────────────────
async def start_session(payload: StartSessionRequest, user_id: str = Depends(require_auth)):
    return await _start_session(user_id, payload)


async def get_session_state(session_id: str, user_id: str = Depends(require_auth)):
    session = await _get_session(session_id, user_id)  # raises SessionNotFoundError if missing/not owned
    return _session_state_response(session)


async def submit_answer(session_id: str, payload: AnswerRequest, user_id: str = Depends(require_auth)):
    return await _submit_answer(user_id, session_id, payload)


async def pause_session(session_id: str, payload: PauseSessionRequest, user_id: str = Depends(require_auth)):
    return await _pause_session(user_id, session_id, payload.reason)


async def resume_session(session_id: str, user_id: str = Depends(require_auth)):
    return await _resume_session(user_id, session_id)


async def take_break(session_id: str, payload: TakeBreakRequest, user_id: str = Depends(require_auth)):
    return await _take_break(user_id, session_id)


async def end_session(session_id: str, user_id: str = Depends(require_auth)):
    return await _end_session(user_id, session_id)


async def share_review(payload: ShareReviewRequest, user_id: str = Depends(require_auth)):
    if not payload.session_id:
        raise InvalidSubmissionError("session_id is required")
    return await _share_review(user_id, payload.session_id, payload)


async def add_peer_comment(share_id: str, payload: PeerCommentRequest, user_id: str = Depends(require_auth)):
    return await _add_peer_comment(user_id, share_id, payload.comment_text)


async def list_peer_comments(share_id: str, user_id: str = Depends(require_auth)):
    return await _list_peer_comments(share_id)


async def revoke_share(share_id: str, user_id: str = Depends(require_auth)):
    return await _revoke_share(user_id, share_id)


async def report_comment(comment_id: str, user_id: str = Depends(require_auth)):
    return await _report_comment(user_id, comment_id)
