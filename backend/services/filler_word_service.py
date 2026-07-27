"""
Filler Word Tracking & Visualization Service (PSC-US-08)

Provides precise breakdown and timeline markers for filler words (um, ah, uh, er, like, you know, etc.)
used during Public Speaking or Mock Interview sessions.

Features & Exception Handling:
  - E-01: Context-aware NLP check for "like" (differentiates verb/preposition vs. syntactic filler).
  - E-02: Acoustic confidence & spectral filter for heavy breathing / mic pops misinterpreted as "ah"/"uh".
  - E-03: Zero filler word detection returning "Flawless Delivery" badge indicator.
  - Actionable tip recommending strategic silence and pausing over filler words.
  - Waveform / timeline-ready markers with timestamps and character/word positions.
"""

import re
import logging
from typing import Dict, List, Optional, Tuple

from fastapi import Depends
from lib import kv_store
from lib.prisma_client import db
from middlewares.auth_middleware import require_auth
from schemas.filler_word_schemas import (
    FillerWordAnalysisSchema,
    FillerWordFrequencySchema,
    FillerWordMarkerSchema,
)
from utils.feature_errors import SessionNotFoundError

logger = logging.getLogger(__name__)

# Single-word and multi-word filler patterns
FILLER_PATTERNS = [
    r"\bum\b", r"\bah\b", r"\buh\b", r"\ber\b", r"\berm\b", r"\blike\b",
    r"\byou know\b", r"\bi mean\b", r"\bso\b", r"\bactually\b", r"\bbasically\b",
    r"\bkind of\b", r"\bsort of\b"
]

ACTIONABLE_FILLER_TIP = (
    "When you feel the urge to use filler words like 'um' or 'like', pause intentionally instead. "
    "Strategic silence projects confidence, gives your audience time to absorb your points, "
    "and eliminates nervous verbal tics."
)

FILLER_WORD_NS = "filler_word_sessions"
INTERVIEW_COACH_NS = "interview_coach_sessions"


async def _is_db_connected() -> bool:
    try:
        return db.is_connected()
    except Exception:
        return False


def is_valid_like_usage(text: str, match_start: int, match_end: int, words: List[str], word_idx: int) -> bool:
    """
    E-01 NLP Context Check: Differentiate "like" as a valid verb/preposition/conjunction
    vs. "like" as a syntactic filler word.
    """
    if word_idx < 0 or word_idx >= len(words):
        return False

    text_lower = text.lower()
    prev_word = words[word_idx - 1].lower() if word_idx > 0 else ""
    next_word = words[word_idx + 1].lower() if word_idx + 1 < len(words) else ""

    # Subject pronouns preceding 'like'
    subject_pronouns = {"i", "you", "we", "they", "he", "she", "who", "it"}
    # Modal, auxiliary, perception, or state verbs preceding 'like'
    verb_contexts = {
        "would", "should", "could", "might", "will", "do", "does", "did",
        "don't", "doesn't", "didn't", "looks", "look", "looked", "seems", "seem",
        "seemed", "feels", "feel", "felt", "sounds", "sound", "sounded", "tastes",
        "smells", "acts", "acted", "is", "are", "was", "were", "be", "been"
    }
    # Indefinite / comparison modifiers
    modifier_terms = {"something", "anything", "nothing", "everything", "someone", "anyone", "much", "more", "just"}

    # 1. Direct subject pronoun before 'like' (e.g., "I like this project", "They like it")
    if prev_word in subject_pronouns and next_word not in {"um", "uh", "ah", "like", "you", "know"}:
        return True

    # 2. Modal or perception verb before 'like' (e.g., "would like to", "looks like an apple", "seems like", "feel like")
    if prev_word in verb_contexts:
        return True

    # 3. Indefinite / comparative modifier before 'like' (e.g., "something like", "just like")
    if prev_word in modifier_terms:
        return True

    # 4. "like to" + infinitive verb (e.g., "like to code", "like to present")
    if next_word == "to":
        return True

    # 5. Comparative structure "like a / the / this / that" preceded by subject or verb
    if next_word in {"a", "an", "the", "this", "that", "these", "those", "my", "your", "our", "their"}:
        if prev_word in subject_pronouns or prev_word in verb_contexts or prev_word in {"is", "are", "was", "were", "be"}:
            return True

    # Also check snippet around match if position context is available
    window = text_lower[max(0, match_start - 15):min(len(text), match_end + 15)]
    valid_phrases = ["i like", "would like", "you like", "they like", "looks like", "seems like", "feels like", "sounds like", "something like"]
    if any(phrase in window for phrase in valid_phrases):
        return True

    return False


def is_breathing_or_mic_pop(timing: dict) -> bool:
    """
    E-02 Acoustic Confidence & Spectral Check: Discard candidate filler detections matching
    breathing or mic-pop decibel/spectral profile rather than counting them as fillers.
    """
    if not timing:
        return False

    # Explicit acoustic flags
    if timing.get("is_breathing") or timing.get("is_mic_pop"):
        return True

    # Acoustic confidence threshold (< 0.60)
    confidence = timing.get("acoustic_confidence", timing.get("confidence", 1.0))
    if confidence < 0.60:
        return True

    # Decibel and spectral signal check for open breath sounds ("ah", "uh")
    word = str(timing.get("word", "")).lower().strip()
    avg_db = timing.get("avg_db", 0.0)
    snr_db = timing.get("snr_db", 30.0)
    start = timing.get("start", 0.0)
    end = timing.get("end", 0.0)
    duration = end - start if end > start else 0.0

    if word in {"ah", "uh", "er", "oh"}:
        if avg_db < -42.0 or snr_db < 10.0 or (duration > 0 and duration < 0.20 and confidence < 0.75):
            return True

    return False


def analyze_filler_words(
    text: str,
    audio_features: Optional[dict] = None,
    word_timings: Optional[List[dict]] = None,
    session_id: str = "session_default",
    speech_type: Optional[str] = None,
) -> FillerWordAnalysisSchema:
    """
    Core filler word analysis logic.
    Identifies filler words explicitly, applies E-01 (like filter), E-02 (acoustic filter),
    E-03 (flawless delivery badge), and builds timeline markers + actionable tips.
    """
    if not text:
        return FillerWordAnalysisSchema(
            session_id=session_id,
            speech_type=speech_type,
            total_filler_count=0,
            flawless_delivery=True,
            badge="Flawless Delivery",
            filler_frequencies={},
            filler_counts=[],
            timeline_markers=[],
            actionable_tip=ACTIONABLE_FILLER_TIP,
            analysis_summary="Flawless delivery! Zero filler words detected.",
        )

    text_clean = text.strip()
    words_split = re.findall(r"\b\w+\b", text_clean)
    words_lower = [w.lower() for w in words_split]

    raw_candidates = []
    text_lower = text_clean.lower()

    # Search multi-word and single-word filler patterns
    for pattern in FILLER_PATTERNS:
        for match in re.finditer(pattern, text_lower):
            word_str = match.group()
            start_pos = match.start()
            end_pos = match.end()

            # Find corresponding word index in words_split
            prefix = text_clean[:start_pos]
            prefix_words = re.findall(r"\b\w+\b", prefix)
            word_idx = len(prefix_words)

            # E-01: Check "like" context
            if word_str == "like":
                if is_valid_like_usage(text_clean, start_pos, end_pos, words_split, word_idx):
                    continue  # Ignore valid verb/preposition usage

            raw_candidates.append({
                "word": word_str,
                "start_pos": start_pos,
                "end_pos": end_pos,
                "word_idx": word_idx,
            })

    # Sort candidates by position
    raw_candidates.sort(key=lambda c: c["start_pos"])

    # Match candidates with word timings or audio features for E-02 acoustic check and timestamps
    timings = word_timings or (audio_features.get("word_timings") if isinstance(audio_features, dict) else None) or []
    
    filtered_markers: List[FillerWordMarkerSchema] = []
    frequencies: Dict[str, int] = {}

    total_words = max(1, len(words_split))
    est_duration = audio_features.get("duration_seconds") if isinstance(audio_features, dict) else (total_words * 0.4)
    sec_per_word = est_duration / total_words if total_words > 0 else 0.4

    for candidate in raw_candidates:
        w_str = candidate["word"]
        idx = candidate["word_idx"]

        # E-02 acoustic check if matching word timing data exists
        timing_item = timings[idx] if idx < len(timings) and isinstance(timings[idx], dict) else {}
        if is_breathing_or_mic_pop(timing_item):
            continue  # Discard heavy breathing / mic pop false positives

        start_time = timing_item.get("start") if timing_item.get("start") is not None else round(idx * sec_per_word, 2)
        end_time = timing_item.get("end") if timing_item.get("end") is not None else round((idx + 1) * sec_per_word, 2)
        conf = timing_item.get("confidence", 0.95)

        marker = FillerWordMarkerSchema(
            word=w_str,
            start_time=start_time,
            end_time=end_time,
            position=idx,
            confidence=conf,
            category="filler",
        )
        filtered_markers.append(marker)
        frequencies[w_str] = frequencies.get(w_str, 0) + 1

    total_count = len(filtered_markers)
    freq_list = [FillerWordFrequencySchema(word=w, count=c) for w, c in frequencies.items()]

    # E-03: Zero filler words -> Flawless Delivery Badge
    if total_count == 0:
        flawless_delivery = True
        badge = "Flawless Delivery"
        summary = "Flawless delivery! Zero filler words detected. You maintained clear, confident speech throughout your presentation."
    else:
        flawless_delivery = False
        badge = None
        top_filler = max(frequencies, key=frequencies.get) if frequencies else "filler words"
        summary = f"Detected {total_count} filler words. Focus on eliminating '{top_filler}' to improve speech fluency."

    return FillerWordAnalysisSchema(
        session_id=session_id,
        speech_type=speech_type,
        total_filler_count=total_count,
        flawless_delivery=flawless_delivery,
        badge=badge,
        filler_frequencies=frequencies,
        filler_counts=freq_list,
        timeline_markers=filtered_markers,
        actionable_tip=ACTIONABLE_FILLER_TIP,
        analysis_summary=summary,
    )


async def get_filler_words_for_session(
    session_id: str,
    user_id: str = Depends(require_auth),
) -> Dict:
    """
    API handler for GET /sessions/{session_id}/filler-words.
    Fetches completed session from PublicSpeakingSession, CoachingSession, or KV store fallback.
    """
    transcript = None
    speech_type = None
    audio_features = None

    # 1. Query PublicSpeakingSession DB table
    if await _is_db_connected():
        try:
            ps_session = await db.publicspeakingsession.find_unique(where={"id": session_id})
            if ps_session and ps_session.userId == user_id:
                transcript = ps_session.transcript
                speech_type = ps_session.speechType
                audio_features = ps_session.audioFeatures
        except Exception as e:
            logger.warning(f"PublicSpeakingSession DB lookup error: {e}")

        # 2. Query CoachingSession DB table if not found
        if not transcript:
            try:
                c_session = await db.coachingsession.find_unique(where={"id": session_id})
                if c_session and c_session.userId == user_id:
                    transcript = c_session.submission or c_session.promptText
                    speech_type = str(c_session.scenario) if hasattr(c_session, "scenario") else "coaching"
                    audio_features = c_session.audioFeatures
            except Exception as e:
                logger.warning(f"CoachingSession DB lookup error: {e}")

    # 3. KV Store Fallback (for offline testing & dynamic sessions)
    if not transcript:
        kv_data = await kv_store.store.get(FILLER_WORD_NS, session_id)
        if not kv_data:
            # Check direct session_id key
            kv_data = await kv_store.store.get("public_speaking_sessions", session_id)
        if not kv_data:
            kv_data = await kv_store.store.get("coaching_sessions", session_id)

        if kv_data and isinstance(kv_data, dict):
            # Verify user ownership if user_id present
            if "userId" in kv_data and kv_data["userId"] != user_id:
                raise SessionNotFoundError(f"Session '{session_id}' not found")
            transcript = kv_data.get("transcript") or kv_data.get("submission") or ""
            speech_type = kv_data.get("speechType") or kv_data.get("speech_type")
            audio_features = kv_data.get("audioFeatures") or kv_data.get("audio_features")

    if transcript is None:
        raise SessionNotFoundError(f"Session '{session_id}' not found")

    analysis = analyze_filler_words(
        text=transcript,
        audio_features=audio_features,
        session_id=session_id,
        speech_type=speech_type,
    )
    return analysis.model_dump()


async def get_filler_words_for_interview_session(
    session_id: str,
    user_id: str = Depends(require_auth),
) -> Dict:
    """
    API handler for GET /interview-coach/sessions/{session_id}/filler-words (US-102).
    Mock Interview has no separate audio-features pipeline of its own — sessions are a
    text Q&A exchange (interview_coach_service.py's kv_store-backed session dict), so
    the candidate's answer transcript is built from that session's exchanges and run
    through the same analyze_filler_words() Public Speaking uses.
    """
    session = await kv_store.store.get(INTERVIEW_COACH_NS, session_id)
    if not session or not isinstance(session, dict) or session.get("user_id") != user_id:
        raise SessionNotFoundError(f"Session '{session_id}' not found")

    candidate_text = " ".join(
        e["answer"] for e in session.get("exchanges", []) if e.get("answer")
    )
    mode = session.get("mode")
    speech_type = mode.value if hasattr(mode, "value") else (str(mode) if mode else "interview")

    analysis = analyze_filler_words(
        text=candidate_text,
        session_id=session_id,
        speech_type=speech_type,
    )
    return analysis.model_dump()
