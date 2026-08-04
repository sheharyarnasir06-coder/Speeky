"""
Workplace English Coach — WEC-US-08 .. WEC-US-12.

Scenario-based professional-communication practice. Grades PROFESSIONAL TONE as the
headline metric (independent of grammar), routes typed drafts through the TEXT scoring
pipeline and spoken submissions through the AUDIO pipeline (lib/session_scorer), and
enforces the stories' exception handling.

Layering, deliberately:
  * Pure, DB-free, network-free helpers (precheck / offline_feedback / workplace_confidence
    / grade_submission) hold all the WEC rules and are unit-tested directly.
  * grade_submission() calls Groq (lib/llm_client) for the nuanced tone/clarity judgement
    and falls back to the offline heuristic grader when Groq is unavailable, so the product
    degrades gracefully and the suite runs offline.
  * The FastAPI controllers at the bottom are thin: gate access, persist CoachingSession
    rows, and delegate to the helpers.
"""

import logging
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from fastapi import Depends, WebSocket
from fastapi.responses import JSONResponse
from prisma import Json

from lib import explore_sessions, llm_client, prompts, session_scorer, voice_ws
from lib.prisma_client import db
from lib.session_scorer import AudioFeatures, ScoredSession
from middlewares.auth_middleware import require_auth, ws_require_auth
from prisma.enums import CoachingInputMode, CoachingScenario, CoachingStatus
from schemas.coaching_schemas import (
    RoleplayTurnSchema,
    StartCoachingSchema,
    SubmitCoachingSchema,
)

logger = logging.getLogger(__name__)

# ── Scenario key <-> enum ─────────────────────────────────────────────────────
SCENARIO_KEY_TO_ENUM = {
    "email_writing": CoachingScenario.EMAIL_WRITING,
    "client_communication": CoachingScenario.CLIENT_COMMUNICATION,
    "meeting_communication": CoachingScenario.MEETING_COMMUNICATION,
    "presentation_prep": CoachingScenario.PRESENTATION_PREP,
    "general_workplace": CoachingScenario.GENERAL_WORKPLACE,
}
SCENARIO_ENUM_TO_KEY = {v: k for k, v in SCENARIO_KEY_TO_ENUM.items()}

# Exception-handling thresholds (from the stories' text).
MIN_TEXT_CHARS = 20            # WEC-US-09 E-03: submit blocked until >20 chars
LONG_MONOLOGUE_SECONDS = 240   # WEC-US-10 E-03: 4-minute monologue
RAMBLING_SECONDS = 180         # WEC-US-11 E-03: 3-minute rambling proposal
MIC_QUIET_DB = -45.0           # WEC-US-12 E-04: ~0db input ⇒ mic muted/quiet
SLIDE_PAUSE_SECONDS = 5.0      # WEC-US-12 E-03: accept ~5s slide-transition pauses

# ── Offline heuristic word banks (used when Groq is unavailable) ───────────────
_SLANG = {
    "thx", "thanks!", "bro", "lol", "omg", "u", "ur", "pls", "plz", "gonna", "wanna",
    "gotta", "yo", "dude", "lemme", "idk", "imo", "tbh", "asap!!", "cya", "kinda", "sorta",
}
_AGGRESSIVE = [
    "you didn't", "you did not do your job", "you failed", "your fault", "you never",
    "you always", "incompetent", "unacceptable", "this is ridiculous", "what is wrong with you",
    "idiot", "loser" , "stupid"
]
_OVER_PROMISE = ["i guarantee", "100%", "i promise it will never", "whatever it takes",
                 "anything you want", "we'll do everything"]
_BOILERPLATE = ["to whom it may concern", "dear sir or madam", "dear sir/madam",
                "please find attached herewith", "lorem ipsum"]
_CASUAL_CONCLUSION = ["that's pretty much it", "so yeah", "that's it", "that's all folks",
                      "yeah that's it", "and yeah"]
_INTRO_MARKERS = ["today", "i'd like to", "i would like to", "i will cover", "i'll cover",
                  "agenda", "overview", "good morning", "good afternoon", "let's start",
                  "to begin", "welcome"]
_TRANSITIONS = ["moving on", "next slide", "as you can see", "to summarize", "in summary",
                "turning to", "let's turn to", "next, ", "first, ", "finally, ",
                "in conclusion", "to wrap up", "on this slide"]
# Tiny romanized non-English (Urdu/Hindi) bank for offline code-switch/non-English detection.
_CODE_SWITCH = {"jaldi": "quickly", "kya": "what", "hai": "is", "nahi": "no", "acha": "okay",
                "theek": "fine", "bhai": "brother", "kal": "tomorrow", "abhi": "right now",
                "karo": "do", "reply karo": "please reply"}


def scenario_meta(scenario_key: str) -> Optional[Dict]:
    return prompts.WORKPLACE_SCENARIOS.get(scenario_key)


def list_scenarios() -> List[Dict]:
    return [
        {
            "key": key,
            "label": meta["label"],
            "story": meta["story"],
            "default_input_mode": meta["input_mode"],
            "roleplay": meta["roleplay"],
            "example_prompts": meta["prompts"],
        }
        for key, meta in prompts.WORKPLACE_SCENARIOS.items()
    ]


# ── Rule-based pre-checks (run before any LLM grading) ────────────────────────
def precheck(
    scenario_key: str,
    input_mode: str,
    submission: str,
    subject: Optional[str],
    audio: Optional[AudioFeatures],
) -> Tuple[Optional[Dict], List[Dict]]:
    """Apply the stories' rule-based exception handling.

    Returns (blocking, flags). `blocking` (a dict with `error`/`flag`/`message`) means the
    submission is rejected before grading (e.g. WEC-US-08 E-03 missing subject, WEC-US-09
    E-03 blank draft). `flags` are non-blocking exceptions attached to the graded result.
    """
    flags: List[Dict] = []
    text = (submission or "").strip()

    # WEC-US-08 E-03 — email scenario needs a subject line.
    if scenario_key == "email_writing" and input_mode == "text" and not (subject or "").strip():
        return (
            {
                "error": "missing_subject",
                "flag": "empty_subject",
                "message": "A professional email needs a clear subject line. Please add one.",
            },
            flags,
        )

    if input_mode == "text":
        # WEC-US-09 E-03 — block blank/too-short drafts.
        if len(text) < MIN_TEXT_CHARS:
            return (
                {
                    "error": "too_short",
                    "flag": "blank_submission",
                    "message": f"Please write at least {MIN_TEXT_CHARS} characters before submitting.",
                },
                flags,
            )
    else:  # audio
        # WEC-US-12 E-04 — mic muted/quiet: near-zero input level.
        if audio is not None and audio.avg_db is not None and audio.avg_db <= MIC_QUIET_DB:
            flags.append({
                "type": "microphone_quiet",
                "message": "Microphone seems quiet. Still practicing?",
            })
        # Empty / silent audio.
        if not text:
            if scenario_key == "meeting_communication":
                # WEC-US-11 E-01 — never interjected: missed opportunity, not an error.
                flags.append({
                    "type": "no_interjection",
                    "message": ("You let the meeting run its course without speaking. "
                                "Next time, jump in with a phrase like \"If I could just add something here...\""),
                })
            else:
                return (
                    {
                        "error": "no_speech",
                        "flag": "blank_submission",
                        "message": "We didn't catch any speech. Please try recording again.",
                    },
                    flags,
                )
        # WEC-US-10 E-03 — very long monologue penalizes active listening.
        if audio is not None and audio.duration_seconds >= LONG_MONOLOGUE_SECONDS:
            flags.append({
                "type": "long_monologue",
                "message": ("You spoke for a long time without pausing for input. "
                            "In client conversations, pause to let the other person respond."),
            })
        elif (
            scenario_key == "meeting_communication"
            and audio is not None
            and audio.duration_seconds >= RAMBLING_SECONDS
        ):
            flags.append({
                "type": "rambling",
                "message": "Could you summarize your main takeaway? Aim for a crisp, focused proposal.",
            })

    return None, flags


# ── Offline heuristic grader (fallback when Groq is unavailable) ──────────────
def _find_phrases(lowered: str, phrases) -> List[str]:
    return [p for p in phrases if p in lowered]


def detect_transitions(text: str) -> List[str]:
    lowered = f" {text.lower()} "
    return [p.strip().strip(",") for p in _TRANSITIONS if p in lowered]


def offline_feedback(
    scenario_key: str,
    prompt: str,
    submission: str,
    input_mode: str,
    delivery: Optional[Dict] = None,
) -> Dict:
    """Deterministic grader used when Groq isn't configured/reachable.

    Same output shape as the LLM grader (prompts.WORKPLACE_FEEDBACK_PROMPT), driven by the
    word banks above. Intentionally conservative — it catches the clear-cut WEC exception
    cases (slang, code-switch, aggression, boilerplate, casual conclusions, missing intro)
    so behaviour and tests hold without a network.
    """
    text = submission or ""
    lowered = f" {text.lower()} "
    words = re.findall(r"[a-z']+", text.lower())
    flags: List[Dict] = []

    # slang / text-speak
    slang_hits = sorted({w for w in words if w in _SLANG})
    for w in slang_hits:
        flags.append({"type": "slang", "phrase": w,
                      "explanation": "Informal/text-speak, inappropriate for a corporate setting.",
                      "suggestion": "Use full, professional wording."})

    # code-switching / non-English
    cs_hits = [w for w in _CODE_SWITCH if w in lowered]
    for w in cs_hits:
        flags.append({"type": "code_switch", "phrase": w,
                      "explanation": "Non-English word mixed into a professional message.",
                      "suggestion": f'Use the English equivalent: "{_CODE_SWITCH[w]}".'})
    if cs_hits and len(cs_hits) >= 2:
        flags.append({"type": "non_english", "phrase": "",
                      "explanation": "Message mixes in another language.",
                      "suggestion": "Please continue in English for this practice session."})

    # aggressive tone
    for p in _find_phrases(lowered, _AGGRESSIVE):
        flags.append({"type": "aggressive_tone", "phrase": p.strip(),
                      "explanation": "Accusatory/confrontational phrasing.",
                      "suggestion": "Rephrase diplomatically, focusing on the issue rather than blame."})

    # over-promising (client)
    if scenario_key == "client_communication":
        for p in _find_phrases(lowered, _OVER_PROMISE):
            flags.append({"type": "over_promising", "phrase": p.strip(),
                          "explanation": "Promises an unrealistic or absolute outcome.",
                          "suggestion": "Set realistic expectations you can actually meet."})

    # boilerplate
    for p in _find_phrases(lowered, _BOILERPLATE):
        flags.append({"type": "boilerplate", "phrase": p.strip(),
                      "explanation": "Generic corporate template with no personalization.",
                      "suggestion": "Rewrite it in your own words, tailored to the scenario."})

    # presentation-specific
    if scenario_key == "presentation_prep":
        if not any(m in lowered for m in _INTRO_MARKERS):
            flags.append({"type": "missing_intro", "phrase": "",
                          "explanation": "Jumped into content without setting context/agenda.",
                          "suggestion": 'Open with something like "Today I\'d like to cover..."'})
        for p in _find_phrases(lowered, _CASUAL_CONCLUSION):
            flags.append({"type": "casual_conclusion", "phrase": p.strip(),
                          "explanation": "Informal wrap-up for a corporate presentation.",
                          "suggestion": 'Close strongly, e.g. "To summarize our main takeaways..."'})

    # highlights: transitions + a little expected vocab
    highlights = [{"kind": "transition", "phrase": t} for t in detect_transitions(text)]

    # heuristic scores — start high, subtract per flag severity; tone is the headline.
    tone = 88.0
    clarity = 82.0
    effectiveness = 82.0
    severity = {"slang": 12, "code_switch": 12, "aggressive_tone": 22, "over_promising": 14,
                "boilerplate": 16, "missing_intro": 12, "casual_conclusion": 10,
                "missing_context": 15, "non_english": 20}
    for f in flags:
        s = severity.get(f["type"], 6)
        tone -= s
        clarity -= s * 0.5
        effectiveness -= s * 0.6

    # short/empty submissions can't be very effective
    wc = len(text.split())
    if wc < 15:
        effectiveness -= 10
        clarity -= 8

    tone = max(0.0, min(100.0, tone))
    clarity = max(0.0, min(100.0, clarity))
    effectiveness = max(0.0, min(100.0, effectiveness))

    met_objective = wc >= 15 and not any(f["type"] in ("missing_context", "non_english") for f in flags)

    return {
        "professional_tone": round(tone),
        "clarity": round(clarity),
        "effectiveness": round(effectiveness),
        "met_objective": met_objective,
        "flags": flags,
        "highlights": highlights,
        "polished_version": text,
        "summary": _offline_summary(flags, tone),
        "_source": "offline",
    }


def _offline_summary(flags: List[Dict], tone: float) -> str:
    if not flags:
        return "Clear, professional communication. Tone and clarity are on point — keep it up."
    kinds = {f["type"] for f in flags}
    bits = []
    if "aggressive_tone" in kinds:
        bits.append("soften the accusatory tone")
    if "slang" in kinds:
        bits.append("replace casual/text-speak wording")
    if "code_switch" in kinds or "non_english" in kinds:
        bits.append("keep it fully in English")
    if "boilerplate" in kinds:
        bits.append("make it more personal and specific")
    if "missing_intro" in kinds:
        bits.append("open by setting the agenda")
    if "casual_conclusion" in kinds:
        bits.append("close with a strong professional summary")
    if "over_promising" in kinds:
        bits.append("set realistic expectations")
    focus = "; ".join(bits) if bits else "tighten the professional tone"
    return f"Good effort. To sound more professional: {focus}."


def _normalize_llm_feedback(raw: Dict) -> Dict:
    """Coerce the LLM's JSON into the canonical grader shape, dropping unknown flag types."""
    def clamp(v, d=0.0):
        try:
            return max(0.0, min(100.0, float(v)))
        except (TypeError, ValueError):
            return d

    flags = []
    for f in raw.get("flags") or []:
        if isinstance(f, dict) and f.get("type") in prompts.FLAG_TYPES:
            flags.append({
                "type": f["type"],
                "phrase": f.get("phrase", ""),
                "explanation": f.get("explanation", ""),
                "suggestion": f.get("suggestion", ""),
            })
    highlights = [
        {"kind": h.get("kind"), "phrase": h.get("phrase", "")}
        for h in (raw.get("highlights") or [])
        if isinstance(h, dict) and h.get("kind") in prompts.HIGHLIGHT_KINDS
    ]
    return {
        "professional_tone": clamp(raw.get("professional_tone")),
        "clarity": clamp(raw.get("clarity")),
        "effectiveness": clamp(raw.get("effectiveness")),
        "met_objective": bool(raw.get("met_objective", True)),
        "flags": flags,
        "highlights": highlights,
        "polished_version": raw.get("polished_version", ""),
        "summary": raw.get("summary", ""),
        "_source": "llm",
    }


async def grade_submission(
    scenario_key: str,
    prompt: str,
    submission: str,
    input_mode: str,
    delivery: Optional[Dict] = None,
) -> Dict:
    """Grade tone/clarity/effectiveness via Groq, falling back to the offline heuristic."""
    scen = scenario_meta(scenario_key) or {"label": scenario_key}
    if not llm_client.is_configured():
        return offline_feedback(scenario_key, prompt, submission, input_mode, delivery)

    grader_prompt = prompts.build_workplace_feedback_prompt(
        scenario_label=scen["label"],
        prompt=prompt,
        submission=submission,
        input_mode=input_mode,
        delivery_metrics=delivery,
    )
    try:
        raw = await llm_client.chat_json(
            [{"role": "user", "content": grader_prompt}],
            temperature=0.2,
            max_tokens=1200,
        )
        return _normalize_llm_feedback(raw)
    except llm_client.LLMError as e:
        logger.warning("Groq grading failed (%s); using offline grader", e)
        return offline_feedback(scenario_key, prompt, submission, input_mode, delivery)


# ── Workplace confidence (headline, grammar-independent) ─────────────────────
_FLAG_PENALTY = {
    "aggressive_tone": 15, "non_english": 15, "over_promising": 8, "boilerplate": 8,
    "missing_context": 10, "missing_intro": 6, "casual_conclusion": 5, "slang": 6,
    "code_switch": 6, "long_monologue": 10, "rambling": 8, "off_agenda": 6,
    "no_interjection": 25, "microphone_quiet": 0, "empty_subject": 0, "blank_submission": 0,
}


def workplace_confidence(grader: Dict, scored: ScoredSession, flags: List[Dict]) -> float:
    """Confidence-first workplace score (0-100), independent of grammar.

    Professional tone is the dominant term. Delivery (fluency/pronunciation) only
    contributes on the AUDIO pipeline; the TEXT pipeline leans on written fluency instead.
    Exception flags apply bounded penalties.
    """
    tone = grader.get("professional_tone", 0.0)
    clarity = grader.get("clarity", 0.0)
    effectiveness = grader.get("effectiveness", 0.0)

    if scored.is_text_only:
        base = 0.45 * tone + 0.25 * clarity + 0.15 * effectiveness + 0.15 * scored.fluency_score
    else:
        base = (0.35 * tone + 0.20 * clarity + 0.15 * effectiveness
                + 0.15 * scored.fluency_score + 0.15 * (scored.pronunciation_score or 0.0))

    penalty = sum(_FLAG_PENALTY.get(f.get("type"), 0) for f in flags)
    return round(max(0.0, min(100.0, base - penalty)), 2)


def build_result(
    scenario_key: str,
    input_mode: str,
    grader: Dict,
    scored: ScoredSession,
    rule_flags: List[Dict],
) -> Dict:
    """Merge grader output + scorer output + rule flags into the final graded payload."""
    # Presentation slide-pause tolerance (WEC-US-12 E-03) already handled at scoring time.
    all_flags = list(rule_flags) + [
        {"type": f["type"], "phrase": f.get("phrase", ""),
         "message": f.get("explanation", ""), "suggestion": f.get("suggestion", "")}
        for f in grader.get("flags", [])
    ]
    confidence = workplace_confidence(grader, scored, all_flags)

    return {
        "input_mode": input_mode,
        "scores": {
            "professional_tone": grader.get("professional_tone"),
            "clarity": grader.get("clarity"),
            "effectiveness": grader.get("effectiveness"),
            "fluency": scored.fluency_score,
            "vocabulary": scored.vocabulary_score,
            "pronunciation": scored.pronunciation_score,
            "confidence": confidence,
        },
        "headline_metric": "professional_tone",
        "met_objective": grader.get("met_objective"),
        "flags": all_flags,
        "highlights": grader.get("highlights", []),
        "polished_version": grader.get("polished_version", ""),
        "summary": grader.get("summary", ""),
        "delivery": scored.delivery,
        "graded_by": grader.get("_source", "llm"),
    }


# ── Scoring-pipeline entry: pick TEXT vs AUDIO ────────────────────────────────
def _adjust_presentation_pauses(audio: AudioFeatures) -> AudioFeatures:
    """WEC-US-12 E-03: treat long ~slide-transition pauses as acceptable when the speaker
    brackets them with transition phrases, so they don't drag down the fluency score."""
    if not detect_transitions(audio.transcript):
        return audio
    # Drop 'slide-click' pauses from the count used for fluency.
    if audio.mean_pause_duration is not None and audio.mean_pause_duration >= SLIDE_PAUSE_SECONDS - 1:
        audio.pause_count = min(audio.pause_count or 0, 2)
    return audio


def score_submission(scenario_key: str, input_mode: str, submission: str,
                     audio: Optional[AudioFeatures]) -> ScoredSession:
    if input_mode == "audio":
        assert audio is not None
        if scenario_key == "presentation_prep":
            audio = _adjust_presentation_pauses(audio)
        return session_scorer.score_audio_session(audio)
    return session_scorer.score_text_session(submission)


# ═══════════════════════════════════════════════════════════════════════════════
# FastAPI controllers
# ═══════════════════════════════════════════════════════════════════════════════
async def get_scenarios(user_id: str = Depends(require_auth)):
    return {"scenarios": list_scenarios()}


async def _require_access(user_id: str) -> Optional[JSONResponse]:
    """Gate coaching behind a completed baseline assessment (feature-access gating)."""
    from services.gating_service import GatedFeature, check_feature_access

    access = await check_feature_access(user_id, GatedFeature.WORKPLACE_ENGLISH_COACH.value)
    if not access["accessible"]:
        return JSONResponse(status_code=403, content={"error": access["reason"], "gating": access})
    return None


def _resolve_input_mode(scenario_key: str, requested: Optional[str]) -> str:
    meta = scenario_meta(scenario_key)
    default = meta["input_mode"] if meta else "text"
    if scenario_key == "general_workplace" and requested in ("text", "audio"):
        return requested  # WEC-US-08 allows either
    return default


async def start_session(payload: StartCoachingSchema, user_id: str = Depends(require_auth)):
    gate = await _require_access(user_id)
    if gate:
        return gate

    scenario_key = payload.scenario
    meta = scenario_meta(scenario_key)
    if not meta:
        return JSONResponse(status_code=400, content={"error": "Unknown scenario"})

    # A fresh start supersedes any other open Explore-group session this user has
    # running elsewhere — see lib/explore_sessions.py.
    await explore_sessions.supersede_open_explore_sessions(user_id)

    input_mode = _resolve_input_mode(scenario_key, payload.input_mode)
    prompt_text = payload.prompt or (meta["prompts"][0] if meta["prompts"] else meta["label"])

    session = await db.coachingsession.create(
        data={
            "userId": user_id,
            "scenario": SCENARIO_KEY_TO_ENUM[scenario_key],
            "inputMode": CoachingInputMode.AUDIO if input_mode == "audio" else CoachingInputMode.TEXT,
            "promptText": prompt_text,
        }
    )

    resp = {
        "session_id": session.id,
        "scenario": scenario_key,
        "label": meta["label"],
        "input_mode": input_mode,
        "roleplay": meta["roleplay"],
        "prompt": prompt_text,
    }
    # Roleplay scenarios kick off with the AI's opening turn (WEC-US-10 / WEC-US-11).
    if meta["roleplay"]:
        resp["opening_message"] = await _roleplay_opening(scenario_key, prompt_text)
    return resp


async def _roleplay_opening(scenario_key: str, prompt_text: str) -> str:
    system = prompts.build_workplace_roleplay_prompt(scenario_key, prompt_text)
    if not llm_client.is_configured():
        # Deterministic opener so the flow works offline.
        if scenario_key == "client_communication":
            return "Hi, thanks for taking my call. I have to say, I'm quite frustrated about how this was handled."
        return "Priya: Right, let's move on to the budget. Sam, what are your thoughts on the current numbers?"
    try:
        return await llm_client.chat(
            [{"role": "system", "content": system},
             {"role": "user", "content": "Begin the scenario now with your first turn."}],
            temperature=0.7, max_tokens=200,
        )
    except llm_client.LLMError:
        return "Let's begin. Go ahead when you're ready."


def _audio_from_payload(payload: SubmitCoachingSchema) -> Optional[AudioFeatures]:
    af = payload.audio_features
    if af is None:
        return None
    return AudioFeatures(
        transcript=payload.submission or af.transcript or "",
        duration_seconds=af.duration_seconds or 0.0,
        word_timings=af.word_timings or [],
        speech_rate=af.speech_rate,
        pause_count=af.pause_count,
        mean_pause_duration=af.mean_pause_duration,
        filled_pauses=af.filled_pauses,
        avg_db=af.avg_db,
        pronunciation_score=af.pronunciation_score,
    )


async def submit_session(session_id: str, payload: SubmitCoachingSchema,
                         user_id: str = Depends(require_auth)):
    session = await db.coachingsession.find_unique(where={"id": session_id})
    if not session or session.userId != user_id:
        return JSONResponse(status_code=404, content={"error": "Coaching session not found"})
    if session.completedAt:
        return JSONResponse(status_code=400, content={"error": "Session already completed"})

    scenario_key = SCENARIO_ENUM_TO_KEY[session.scenario]
    input_mode = "audio" if session.inputMode == CoachingInputMode.AUDIO else "text"
    audio = _audio_from_payload(payload) if input_mode == "audio" else None
    submission = payload.submission or (audio.transcript if audio else "") or ""

    # 1) Rule-based exception handling (may block before grading).
    blocking, rule_flags = precheck(scenario_key, input_mode, submission, payload.subject, audio)
    if blocking:
        return JSONResponse(status_code=422, content=blocking)

    # 2) Score via the correct pipeline (TEXT vs AUDIO).
    scored = score_submission(scenario_key, input_mode, submission, audio)

    # 3) Grade tone/clarity/effectiveness (LLM or offline).
    grader = await grade_submission(
        scenario_key, session.promptText, submission, input_mode, scored.delivery
    )

    result = build_result(scenario_key, input_mode, grader, scored, rule_flags)

    # CSC-US-01: drop proper-noun false positives (E-01) from the code_switch flags and
    # log the genuine code-switched words into the learner's practice list (TC-003). Done
    # before the flags are persisted/returned so "Lahore" is never shown as a violation.
    from services import code_switch_service

    result["flags"] = await code_switch_service.track_from_flags(
        user_id, result["flags"], submission
    )

    status = CoachingStatus.COMPLETED
    if any(f.get("type") == "aggressive_tone" for f in result["flags"]) and scenario_key == "client_communication":
        status = CoachingStatus.ENDED_EARLY  # WEC-US-10 E-01 de-escalation cut-off

    update_data = {
        "submission": submission,
        "status": status,
        "professionalTone": result["scores"]["professional_tone"],
        "clarityScore": result["scores"]["clarity"],
        "effectivenessScore": result["scores"]["effectiveness"],
        "fluencyScore": result["scores"]["fluency"],
        "vocabularyScore": result["scores"]["vocabulary"],
        "pronunciationScore": result["scores"]["pronunciation"],
        "confidenceScore": result["scores"]["confidence"],
        "feedback": Json({"summary": result["summary"],
                          "polished_version": result["polished_version"],
                          "highlights": result["highlights"],
                          "graded_by": result["graded_by"]}),
        "flags": Json(result["flags"]),
        "metObjective": result["met_objective"],
        "completedAt": datetime.now(timezone.utc),
    }
    # Omit audioFeatures for text mode: prisma-client-py rejects an explicit None
    # for an optional Json? field ("a value is required but not set") — the key
    # must be absent, not null, to leave the column NULL.
    if input_mode == "audio":
        update_data["audioFeatures"] = Json(scored.delivery)

    await db.coachingsession.update(where={"id": session_id}, data=update_data)

    result["session_id"] = session_id
    result["status"] = status.value
    return result


# ── Voice mode: WebSocket transport ──────────────────
async def voice_socket(websocket: WebSocket, session_id: str):
    user_id = await ws_require_auth(websocket)
    if user_id is None:
        return  # ws_require_auth already closed the socket

    gate = await _require_access(user_id)
    if gate:
        await websocket.close(code=4403, reason="Feature not accessible")
        return

    session = await db.coachingsession.find_unique(where={"id": session_id})
    if not session or session.userId != user_id:
        await websocket.close(code=4404, reason="Coaching session not found")
        return

    await websocket.accept()
    # partial_interval_s: live-preview text streams in while the user keeps talking,
    # instead of nothing appearing until the utterance ends.
    await voice_ws.serve(websocket, mode="transcript", partial_interval_s=1.2)


async def roleplay_turn(session_id: str, payload: RoleplayTurnSchema,
                        user_id: str = Depends(require_auth)):
    """Advance an interactive roleplay (WEC-US-10 client / WEC-US-11 meeting) by one turn.

    The AI persona reacts dynamically to the user's message; the accumulating dialogue is
    kept in `turns`. When the user is done they call /submit, which grades the full
    transcript. If the user switches out of English, the persona asks them to continue in
    English (WEC-US-10 E-04). Aggression ends the client scenario early (WEC-US-10 E-01).
    """
    session = await db.coachingsession.find_unique(where={"id": session_id})
    if not session or session.userId != user_id:
        return JSONResponse(status_code=404, content={"error": "Coaching session not found"})
    if session.completedAt or session.status == CoachingStatus.ENDED_EARLY:
        return JSONResponse(status_code=400, content={"error": "Session is no longer active"})

    scenario_key = SCENARIO_ENUM_TO_KEY[session.scenario]
    meta = scenario_meta(scenario_key)
    if not meta or not meta["roleplay"]:
        return JSONResponse(status_code=400, content={"error": "This scenario is not interactive"})

    turns = list(session.turns) + [{"role": "user", "content": payload.message}]

    lowered = payload.message.lower()
    end_early = (
        scenario_key == "client_communication"
        and any(p in f" {lowered} " for p in _AGGRESSIVE)
    )
    switched_language = sum(1 for w in _CODE_SWITCH if w in f" {lowered} ") >= 2

    reply = await _roleplay_reply(scenario_key, session.promptText, turns,
                                  end_early=end_early, switched_language=switched_language)
    turns.append({"role": "assistant", "content": reply})

    new_status = CoachingStatus.ENDED_EARLY if end_early else CoachingStatus.IN_PROGRESS
    await db.coachingsession.update(
        where={"id": session_id},
        data={"turns": Json(turns), "status": new_status},
    )
    return {
        "session_id": session_id,
        "reply": reply,
        "status": new_status.value,
        "ended_early": end_early,
        "transcript": " ".join(t["content"] for t in turns if t["role"] == "user"),
    }


async def _roleplay_reply(scenario_key: str, prompt_text: str, turns: List[Dict],
                          end_early: bool, switched_language: bool) -> str:
    if switched_language:
        return "Could we continue in English, please? That's what we're here to practise."
    if not llm_client.is_configured():
        if end_early:
            return ("I don't think this is going anywhere productive. Let's end here — "
                    "I'll follow up over email.")
        if scenario_key == "client_communication":
            return "Okay, I hear you. So what exactly are you going to do to fix this for me?"
        return "Sam: That's a fair point. Priya, how does that affect the timeline on your end?"

    system = prompts.build_workplace_roleplay_prompt(scenario_key, prompt_text)
    if end_early:
        system += "\n\nThe user has been aggressive/rude. Show dissatisfaction and wind the conversation down now."
    messages = [{"role": "system", "content": system}] + [
        {"role": t["role"], "content": t["content"]} for t in turns
    ]
    try:
        return await llm_client.chat(messages, temperature=0.7, max_tokens=200)
    except llm_client.LLMError:
        return "Understood. Please go on."


async def get_session(session_id: str, user_id: str = Depends(require_auth)):
    session = await db.coachingsession.find_unique(where={"id": session_id})
    if not session or session.userId != user_id:
        return JSONResponse(status_code=404, content={"error": "Coaching session not found"})
    scenario_key = SCENARIO_ENUM_TO_KEY[session.scenario]
    meta = scenario_meta(scenario_key)
    return {
        "session_id": session.id,
        "scenario": scenario_key,
        "label": meta["label"] if meta else scenario_key,
        "roleplay": meta["roleplay"] if meta else False,
        "turns": session.turns,  # roleplay chat history — used to resume mid-conversation
        "input_mode": "audio" if session.inputMode == CoachingInputMode.AUDIO else "text",
        "status": session.status,
        "prompt": session.promptText,
        "submission": session.submission,
        "scores": {
            "professional_tone": session.professionalTone,
            "clarity": session.clarityScore,
            "effectiveness": session.effectivenessScore,
            "fluency": session.fluencyScore,
            "vocabulary": session.vocabularyScore,
            "pronunciation": session.pronunciationScore,
            "confidence": session.confidenceScore,
        },
        "met_objective": session.metObjective,
        "flags": session.flags,
        "feedback": session.feedback,
        "completed_at": session.completedAt.isoformat() if session.completedAt else None,
    }
