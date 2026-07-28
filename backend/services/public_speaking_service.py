"""
Public Speaking Coach Service — PSC-US-01, PSC-US-03, PSC-US-04, PSC-US-05, PSC-US-06, PSC-US-07, PSC-US-11, PSC-US-12, PSC-US-14

Audio/text-based public speaking analysis. Ignores video-specific requirements (eye contact, physical presence).
Focuses on:
- Speech structure analysis (business pitch, classroom, TED-style)
- Speaking pace analytics (WPM calculation)
- Voice clarity and projection analysis
- Filler word tracking and visualization
- Tone variation and energy assessment
- Audience Q&A simulation
- Motivational speech evaluation
- Casual event speech feedback
"""

import base64
import binascii
import logging
import re
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from fastapi import Depends
from prisma import Json
from lib import llm_client, prompts, prosody_engine, recording_engine, session_scorer
from lib.audio_io import AudioDecodeError
from lib.prisma_client import db
from lib.session_scorer import AudioFeatures, ScoredSession
from lib.speech_config import load_speech_config
from middlewares.auth_middleware import require_auth
from utils.feature_errors import InvalidSubmissionError, SessionNotFoundError
from schemas.public_speaking_schemas import (
    PublicSpeakingScorecard,
    PublicSpeakingSession,
    StartPublicSpeakingSchema,
    PublicSpeakingTurnSchema,
    QAResponseSchema,
)

logger = logging.getLogger(__name__)

# Speech type configurations
SPEECH_TYPES = {
    "business_pitch": {
        "label": "Business Pitch",
        "structure_elements": ["hook", "problem", "solution", "ask"],
        "ideal_wpm_range": (130, 160),
        "prioritize_structure": True,
        "prioritize_persuasiveness": True,
    },
    "casual_event": {
        "label": "Casual Event Speech (Wedding/Toast)",
        "structure_elements": ["opening", "story", "emotional_peak", "closing"],
        "ideal_wpm_range": (120, 150),
        "disable_corporate_tone": True,
        "prioritize_warmth": True,
    },
    "motivational": {
        "label": "Motivational Speech",
        "structure_elements": ["hook", "struggle", "triumph", "call_to_action"],
        "ideal_wpm_range": (130, 160),
        "prioritize_energy": True,
        "prioritize_tone_variation": True,
    },
    "classroom": {
        "label": "Classroom Presentation",
        "structure_elements": ["introduction", "body", "conclusion"],
        "ideal_wpm_range": (130, 150),
        "check_transitions": True,
        "track_filler_words": True,
    },
    "ted_talk": {
        "label": "TED-Style Talk",
        "structure_elements": ["hook", "story", "core_idea", "conclusion"],
        "ideal_wpm_range": (130, 150),
        "prioritize_storytelling": True,
        "prioritize_engagement": True,
    },
}

# Filler word patterns
FILLER_PATTERNS = [
    r"\bum\b", r"\bah\b", r"\buh\b", r"\blike\b", r"\byou know\b", 
    r"\bso\b", r"\bactually\b", r"\bbasically\b", r"\bkind of\b", r"\bsort of\b"
]

# Speaking pace thresholds
IDEAL_WPM_MIN = 130
IDEAL_WPM_MAX = 160
RUSHED_WPM_THRESHOLD = 170
SLOW_WPM_THRESHOLD = 110

# Audio quality thresholds
MIC_QUIET_DB = -45.0
CLIPPING_DB = -3.0


class _AgentProsody:
    """Minimal stand-in for prosody_engine.ProsodyData carrying only the field the
    scorecard reads (pitch range), populated from the LiveKit full-mode features."""

    def __init__(self, pitch_range_semitones: float):
        self.pitch_range_semitones = pitch_range_semitones


class _AgentAnalysis:
    """Adapter that lets the scorecard treat LiveKit full-mode features like a
    recording_engine.RecordingAnalysis (same attributes it reads: prosody / avg_dbfs /
    snr_db / rejection). The voice_agent trims silence before it ever sees the audio, so a
    true noise-floor SNR isn't available — clarity therefore assumes a clean channel unless
    the agent later sends snr_db."""

    def __init__(self, features: Dict):
        self.prosody = _AgentProsody(float(features.get("pitch_range_semitones", 0.0)))
        self.avg_dbfs = float(features.get("avg_db", -20.0))
        self.snr_db = float(features.get("snr_db", 20.0))
        self.rejection = None


async def start_session(
    user_id: str,
    request: StartPublicSpeakingSchema,
) -> Dict:
    """Start a new public speaking session"""
    session_id = str(uuid.uuid4())
    
    speech_config = SPEECH_TYPES.get(request.speech_type, SPEECH_TYPES["business_pitch"])
    
    # Create session record
    session = await db.publicspeakingsession.create(
        data={
            "id": session_id,
            "userId": user_id,
            "speechType": request.speech_type,
            "inputMode": request.input_mode,
            "status": "in_progress",
            "createdAt": datetime.now(timezone.utc),
            "topic": request.topic,
        }
    )
    
    return {
        "session_id": session_id,
        "speech_type": request.speech_type,
        "label": speech_config["label"],
        "input_mode": request.input_mode,
        "structure_elements": speech_config["structure_elements"],
        "ideal_wpm_range": speech_config["ideal_wpm_range"],
        "topic": request.topic,
        "status": "in_progress",
    }


async def submit_turn(
    session_id: str,
    user_id: str,
    turn: PublicSpeakingTurnSchema,
) -> Dict:
    """Process a speech turn (audio or text) and return analysis"""
    session = await db.publicspeakingsession.find_unique(where={"id": session_id})
    if not session or session.userId != user_id:
        raise SessionNotFoundError("Public speaking session not found")
    
    speech_config = SPEECH_TYPES.get(session.speechType, SPEECH_TYPES["business_pitch"])
    
    # Process audio or text input
    if turn.audio_data:
        # Legacy base64-upload pipeline (full prosody/SNR delivery metrics).
        transcript, audio_features, analysis = await _process_audio(turn.audio_data)
        text_content = transcript
    elif turn.audio_features or turn.duration_seconds is not None:
        # Shared LiveKit voice pipeline. In FULL mode the voice_agent also sends acoustic
        # features (word timings + prosody + level), so we recover real WPM/tone/clarity —
        # matching the base64 recording_engine path. In transcript mode only duration
        # arrives, so tone/clarity fall back to proxies (like Conversation / Baseline).
        text_content = turn.text_content or ""
        feats = turn.audio_features or {}
        dur = turn.duration_seconds if turn.duration_seconds is not None else feats.get("duration_seconds", 0.0)
        audio_features = AudioFeatures(
            transcript=text_content,
            duration_seconds=dur or 0.0,
            word_timings=feats.get("word_timings", []),
            avg_db=feats.get("avg_db"),
        )
        analysis = _AgentAnalysis(feats) if feats.get("pitch_range_semitones") is not None else None
    else:
        # Typed text
        text_content = turn.text_content or ""
        audio_features = None
        analysis = None

    # Generate comprehensive scorecard
    scorecard = await _generate_scorecard(
        speech_type=str(session.speechType),
        text_content=text_content,
        audio_features=audio_features,
        analysis=analysis,
        speech_config=speech_config,
    )
    
    # Update session
    await db.publicspeakingsession.update(
        where={"id": session_id},
        data={
            "transcript": text_content,
            "status": "completed" if turn.is_final else "in_progress",
            "completedAt": datetime.now(timezone.utc) if turn.is_final else None,
            "scorecard": Json(scorecard),
            "audioFeatures": _audio_features_json(audio_features),
        }
    )
    
    # Check if Q&A should be triggered (PSC-US-12)
    should_trigger_qa = (
        turn.is_final and 
        len(text_content) > 100 and  # Minimum content for meaningful Q&A
        not _is_nonsense_content(text_content)
    )
    
    if should_trigger_qa:
        # Generate AI question based on speech content
        ai_question = await _generate_qa_question(session.speechType, text_content)
        await db.publicspeakingsession.update(
            where={"id": session_id},
            data={
                "status": "qa_phase",
                "aiQuestion": ai_question,
            }
        )
        return {
            "scorecard": scorecard,
            "qa_triggered": True,
            "ai_question": ai_question,
            "session_id": session_id,
        }
    
    return {
        "scorecard": scorecard,
        "qa_triggered": False,
        "session_id": session_id,
    }


async def submit_qa_response(
    session_id: str,
    user_id: str,
    response: QAResponseSchema,
) -> Dict:
    """Process Q&A response and evaluate performance"""
    session = await db.publicspeakingsession.find_unique(where={"id": session_id})
    if not session or session.userId != user_id:
        raise SessionNotFoundError("Public speaking session not found")
    
    if session.status != "qa_phase":
        raise InvalidSubmissionError("This session is not in the Q&A phase.")
    
    # Process response
    if response.audio_data:
        transcript, audio_features, _analysis = await _process_audio(response.audio_data)
        text_content = transcript
    elif response.duration_seconds is not None:
        text_content = response.text_content or ""
        audio_features = AudioFeatures(transcript=text_content, duration_seconds=response.duration_seconds)
    else:
        text_content = response.text_content or ""
        audio_features = None
    
    # Evaluate Q&A performance
    qa_score = await _evaluate_qa_response(
        original_speech=session.transcript or "",
        ai_question=session.aiQuestion or "",
        user_response=text_content,
        audio_features=audio_features,
    )
    
    # Update session with Q&A results
    await db.publicspeakingsession.update(
        where={"id": session_id},
        data={
            "userQaResponse": text_content,
            "status": "completed",
            "completedAt": datetime.now(timezone.utc),
            "qaScore": Json(qa_score),
        }
    )
    
    # Merge Q&A score into existing scorecard
    updated_scorecard = session.scorecard or {}
    updated_scorecard["qa_handling"] = qa_score
    
    return {
        "qa_score": qa_score,
        "updated_scorecard": updated_scorecard,
        "session_id": session_id,
    }


async def get_voice_token(session_id: str, user_id: str) -> Dict:
    """Mint a LiveKit room token for a spoken turn — the shared voice pipeline used by
    Conversation / Baseline. Room name is the session_id; the generic voice_agent worker
    auto-joins, transcribes (Silero VAD + faster-whisper), and pushes the transcript over
    the data channel. Backend never touches raw audio here."""
    from fastapi.responses import JSONResponse
    from lib import livekit_tokens

    session = await db.publicspeakingsession.find_unique(where={"id": session_id})
    if not session or session.userId != user_id:
        return JSONResponse(status_code=404, content={"error": "Session not found"})
    if not livekit_tokens.is_configured():
        return JSONResponse(
            status_code=503,
            content={"error": "Voice mode unavailable. Use text mode instead."},
        )
    # Public Speaking needs delivery metrics -> full mode (word timings + prosody + level).
    return livekit_tokens.mint_room_token(session_id, identity=user_id, mode="full")


async def get_session(session_id: str, user_id: str) -> Dict:
    """Get session details"""
    session = await db.publicspeakingsession.find_unique(where={"id": session_id})
    if not session or session.userId != user_id:
        raise SessionNotFoundError("Public speaking session not found")
    
    return {
        "session_id": session.id,
        "speech_type": session.speechType,
        "input_mode": session.inputMode,
        "status": session.status,
        "created_at": session.createdAt.isoformat(),
        "completed_at": session.completedAt.isoformat() if session.completedAt else None,
        "topic": session.topic,
        "transcript": session.transcript,
        "scorecard": session.scorecard,
        "ai_question": session.aiQuestion,
        "user_qa_response": session.userQaResponse,
        "qa_score": session.qaScore,
    }


def _audio_features_json(audio_features: Optional[AudioFeatures]):
    """Serializes AudioFeatures (incl. real per-word timings) for the audioFeatures
    Json column, so get_filler_words_for_session can read real timestamps back out
    instead of falling back to synthetic evenly-spaced ones."""
    return Json(asdict(audio_features)) if audio_features else None


async def _process_audio(
    audio_data: str,
) -> Tuple[str, Optional[AudioFeatures], Optional["recording_engine.RecordingAnalysis"]]:
    """Process audio input: decode base64, then run it through the same shared
    decode+VAD+STT+prosody pipeline Pronunciation Coach / Accent Assessment use
    (lib/recording_engine.py) instead of duplicating that logic here.

    Returns the transcript, a fully populated session_scorer.AudioFeatures (with word
    timings + filled-pause count, so the real fluency scorer works — not the empty stub
    Devin passed before), and the raw RecordingAnalysis so the scorecard can read real
    prosody / SNR / rejection instead of hardcoded 75s."""
    try:
        # Frontend sends either a raw base64 string or a data: URI — strip the prefix if present.
        raw = audio_data.split(",", 1)[1] if audio_data.startswith("data:") else audio_data
        audio_bytes = base64.b64decode(raw)
        config = load_speech_config()
        analysis = recording_engine.analyze_recording(audio_bytes, config)
        # PSC-US-08: keep real per-word STT timestamps + confidence so the filler-word
        # service lands "Um: 12 times" markers on the actual moment each was spoken,
        # instead of synthetic evenly-spaced fallbacks.
        word_timings = [
            {"word": w.word, "start": w.start, "end": w.end, "confidence": w.probability}
            for w in analysis.words
        ]
        audio_features = AudioFeatures(
            transcript=analysis.transcript,
            duration_seconds=analysis.duration_seconds,
            word_timings=word_timings,
            avg_db=analysis.avg_dbfs,
            filled_pauses=session_scorer.count_filled_pauses(analysis.transcript),
        )
        return analysis.transcript, audio_features, analysis
    except (AudioDecodeError, binascii.Error) as e:
        logger.error(f"Audio processing failed: {e}")
        return "", None, None


async def _generate_scorecard(
    speech_type: str,
    text_content: str,
    audio_features: Optional[AudioFeatures],
    analysis: Optional["recording_engine.RecordingAnalysis"],
    speech_config: Dict,
) -> Dict:
    """Generate comprehensive scorecard based on speech analysis.

    Scores are derived from the shared analysis engines — session_scorer for
    fluency/vocabulary/pronunciation, prosody for tone variation, VAD/SNR for clarity —
    not from the constant 75.0 placeholders. When audio was rejected (silence, too
    quiet, too noisy) the scorecard reports that instead of fabricating a score."""

    # Run the same fluency/vocabulary/pronunciation scorer the other speaking modules use.
    if audio_features:
        scored = session_scorer.score_audio_session(audio_features)
    else:
        scored = session_scorer.score_text_session(text_content)

    # Calculate speaking pace (PSC-US-11)
    wpm_metrics = _calculate_wpm(text_content, audio_features)

    # Analyze filler words (PSC-US-08)
    # PSC-US-08: pass audio_features so filler markers use real per-word timestamps.
    filler_analysis = _analyze_filler_words(text_content, audio_features)

    # Assess tone variation and energy (PSC-US-05, PSC-US-07) — real pitch range when audio present.
    tone_analysis = _analyze_tone_variation(text_content, analysis)


    # Evaluate structure based on speech type
    structure_analysis = _evaluate_structure(speech_type, text_content, speech_config)

    # Voice clarity analysis (PSC-US-14) — real SNR / input level, not a constant.
    clarity_analysis = _analyze_voice_clarity(analysis)

    # Calculate overall scores
    scores = _calculate_overall_scores(
        speech_type=speech_type,
        wpm_metrics=wpm_metrics,
        filler_analysis=filler_analysis,
        tone_analysis=tone_analysis,
        structure_analysis=structure_analysis,
        clarity_analysis=clarity_analysis,
        scored=scored,
        speech_config=speech_config,
    )

    # Generate feedback and flags
    flags = _generate_flags(
        speech_type=speech_type,
        wpm_metrics=wpm_metrics,
        filler_analysis=filler_analysis,
        tone_analysis=tone_analysis,
        structure_analysis=structure_analysis,
        clarity_analysis=clarity_analysis,
    )

    highlights = _generate_highlights(
        speech_type=speech_type,
        structure_analysis=structure_analysis,
        tone_analysis=tone_analysis,
    )

    # Generate summary and actionable tips
    summary, actionable_tips = _generate_feedback_summary(
        speech_type=speech_type,
        scores=scores,
        flags=flags,
        speech_config=speech_config,
    )

    return {
        "speech_type": str(speech_type),
        "input_mode": "audio" if audio_features else "text",
        "overall_score": scores["overall"],
        "confidence": scores["confidence"],
        "pacing": scores["pacing"],
        "tone_variation": scores["tone_variation"],
        "voice_clarity": scores["voice_clarity"],
        "structure": scores["structure"],
        "audience_engagement": scores["audience_engagement"],
        "fluency": scored.fluency_score,
        "vocabulary": scored.vocabulary_score,
        "pronunciation": scored.pronunciation_score,
        "words_per_minute": wpm_metrics["wpm"],
        "filler_word_count": filler_analysis["count"],
        "filler_words": filler_analysis["words"],
        "audio_rejected": analysis.rejection.value if analysis and analysis.rejection else None,
        "flags": flags,
        "highlights": highlights,
        "summary": summary,
        "actionable_tips": actionable_tips,
        "delivery": scored.delivery if audio_features else None,
    }


def _calculate_wpm(text: str, audio_features: Optional[AudioFeatures]) -> Dict:
    """Calculate words per minute and pacing metrics"""
    words = text.split()
    word_count = len(words)

    # WPM needs real speaking time. Text submissions have none, so report it as
    # unmeasurable ("not_applicable") rather than inventing 150 — the old default made
    # every typed speech read as perfectly paced.
    if audio_features and audio_features.duration_seconds > 0:
        wpm = round((word_count / audio_features.duration_seconds) * 60, 1)
    else:
        wpm = None

    if wpm is None:
        pacing_quality = "not_applicable"
    elif IDEAL_WPM_MIN <= wpm <= IDEAL_WPM_MAX:
        pacing_quality = "optimal"
    elif wpm > RUSHED_WPM_THRESHOLD:
        pacing_quality = "rushed"
    elif wpm < SLOW_WPM_THRESHOLD:
        pacing_quality = "slow"
    else:
        pacing_quality = "acceptable"

    return {
        "wpm": wpm,
        "word_count": word_count,
        "pacing_quality": pacing_quality,
    }


from services import filler_word_service

def _analyze_filler_words(text: str, audio_features: Optional[AudioFeatures] = None) -> Dict:
    """Analyze filler word usage using filler_word_service (PSC-US-08)"""
    af_dict = None
    if audio_features:
        af_dict = {
            "duration_seconds": audio_features.duration_seconds,
            "word_timings": getattr(audio_features, "word_timings", []),
            "avg_db": getattr(audio_features, "avg_db", None),
        }

    analysis = filler_word_service.analyze_filler_words(text, audio_features=af_dict)
    
    words_list = [
        {
            "word": m.word,
            "position": m.position,
            "start_time": m.start_time,
            "end_time": m.end_time,
        }
        for m in analysis.timeline_markers
    ]

    return {
        "count": analysis.total_filler_count,
        "words": words_list,
        "flawless_delivery": analysis.flawless_delivery,
        "badge": analysis.badge,
        "filler_frequencies": analysis.filler_frequencies,
        "actionable_tip": analysis.actionable_tip,
    }


def _analyze_tone_variation(
    text: str, analysis: Optional["recording_engine.RecordingAnalysis"]
) -> Dict:
    """Analyze tone variation and vocal energy.

    For audio, the real signal is pitch range: the prosody engine already computes
    pitch_range_semitones (5th–95th percentile spread of the voiced F0 contour). A flat
    delivery sits near 0; expressive speech spans ~8-12 st. That replaces the constant
    75.0 the old code produced because it called prosody_engine.analyze() with the wrong
    argument and swallowed the resulting exception.

    For text (no audio), fall back to the sentence-length-variance heuristic — it's a
    weak proxy, so it only flags monotone risk, it does not fabricate an energy number.
    """
    sentences = [s.strip() for s in text.split('.') if s.strip()]

    if analysis is not None and analysis.prosody is not None:
        pitch_range = float(analysis.prosody.pitch_range_semitones)
        # Map 0 st -> 0, 10 st -> 100 (clamped). 10 st ≈ lively presentation delivery.
        energy_score = max(0.0, min(100.0, (pitch_range / 10.0) * 100.0))
        monotone_risk = pitch_range < 3.0  # under a minor third of spread reads as flat
        energy_measured = True
    else:
        sentence_lengths = [len(s.split()) for s in sentences]
        if len(sentence_lengths) > 1:
            length_variance = max(sentence_lengths) - min(sentence_lengths)
            monotone_risk = length_variance < 5
        else:
            monotone_risk = False
        energy_score = None  # not measurable from text
        energy_measured = False

    return {
        "energy_score": energy_score,
        "energy_measured": energy_measured,
        "monotone_risk": monotone_risk,
        "sentence_count": len(sentences),
    }


def _evaluate_structure(speech_type: str, text: str, speech_config: Dict) -> Dict:
    """Evaluate speech structure based on type"""
    structure_elements = speech_config["structure_elements"]
    found_elements = []
    
    text_lower = text.lower()
    
    # Define keyword patterns for each structure element
    element_patterns = {
        "hook": [r"imagine", r"picture this", r"let me tell you", r"have you ever"],
        "problem": [r"problem", r"challenge", r"issue", r"struggle", r"pain point"],
        "solution": [r"solution", r"answer", r"approach", r"we propose", r"our product"],
        "ask": [r"ask", r"investment", r"funding", r"partnership", r"next steps", r"call to action"],
        "introduction": [r"introduction", r"today i", r"i will", r"let's start", r"agenda"],
        "body": [r"first", r"second", r"third", r"next", r"moving on", r"furthermore"],
        "conclusion": [r"in conclusion", r"to summarize", r"finally", r"wrap up", r"in summary"],
        "story": [r"story", r"experience", r"remember when", r"back when", r"personal"],
        "emotional_peak": [r"inspire", r"believe", r"passion", r"love", r"dream"],
        "closing": [r"thank you", r"appreciate", r"grateful", r"conclude"],
        "struggle": [r"struggle", r"difficult", r"hard", r"challenge", r"overcome"],
        "triumph": [r"success", r"achieve", r"accomplish", r"breakthrough", r"victory"],
        "call_to_action": [r"act now", r"join me", r"let's", r"together", r"start"],
        "opening": [r"hello", r"welcome", r"good morning", r"good afternoon", r"thank you for being here"],
    }
    
    for element in structure_elements:
        patterns = element_patterns.get(element, [])
        if any(re.search(pattern, text_lower) for pattern in patterns):
            found_elements.append(element)
    
    structure_score = (len(found_elements) / len(structure_elements)) * 100 if structure_elements else 75.0
    
    return {
        "found_elements": found_elements,
        "missing_elements": [e for e in structure_elements if e not in found_elements],
        "structure_score": round(structure_score, 1),
    }


def _analyze_voice_clarity(
    analysis: Optional["recording_engine.RecordingAnalysis"],
) -> Dict:
    """Analyze voice clarity and projection (PSC-US-14) from real acoustic signals.

    Clarity tracks SNR (how far the voice sits above the noise floor); projection tracks
    average input level (dBFS). Both come straight from the VAD/level analysis the shared
    recording engine already ran. Text mode has no audio, so clarity is reported as
    not-measured (None) rather than a placeholder 75.0.
    """
    if analysis is None:
        return {
            "clarity_score": None,
            "projection_score": None,
            "measured": False,
            "issues": [],
        }

    issues = []

    # If the whole recording was rejected, surface why — don't score fake clarity on it.
    if analysis.rejection is not None:
        reason_messages = {
            "no_speech_detected": "No speech was detected. Please record again and speak clearly.",
            "audio_too_quiet": "Microphone volume is very low. Please check device settings.",
            "background_noise_too_high": "Too much background noise. Find a quieter space and retry.",
        }
        issues.append({
            "type": analysis.rejection.value,
            "message": reason_messages.get(
                analysis.rejection.value, "Recording could not be analyzed."
            ),
        })
        return {
            "clarity_score": 0.0,
            "projection_score": 0.0,
            "measured": True,
            "issues": issues,
        }

    # Clarity from SNR: <=8 dB poor (~50), >=25 dB excellent (~100).
    snr = analysis.snr_db
    clarity_score = max(0.0, min(100.0, 50.0 + (snr - 8.0) * (50.0 / 17.0)))

    # Projection from input level: too quiet or clipping both hurt.
    avg_db = analysis.avg_dbfs
    projection_score = max(0.0, min(100.0, (avg_db - MIC_QUIET_DB) * (100.0 / 42.0)))
    if avg_db <= MIC_QUIET_DB:
        issues.append({
            "type": "microphone_quiet",
            "message": "Microphone volume is very low. Please check device settings.",
        })
        projection_score = 50.0  # hardware issue — don't over-penalize the speaker
    elif avg_db >= CLIPPING_DB:
        issues.append({
            "type": "audio_clipping",
            "message": "Audio distortion detected. Please move farther from microphone.",
        })
        clarity_score = min(clarity_score, 50.0)

    return {
        "clarity_score": round(max(0.0, min(100.0, clarity_score)), 1),
        "projection_score": round(max(0.0, min(100.0, projection_score)), 1),
        "measured": True,
        "issues": issues,
    }


def _calculate_overall_scores(
    speech_type: str,
    wpm_metrics: Dict,
    filler_analysis: Dict,
    tone_analysis: Dict,
    structure_analysis: Dict,
    clarity_analysis: Dict,
    scored: "session_scorer.ScoredSession",
    speech_config: Dict,
) -> Dict:
    """Calculate overall scores based on all analyses.

    Where a dimension can't be measured (text has no pacing/clarity/energy), we fall back
    to the session_scorer fluency score — a real signal derived from the submission —
    instead of the old constant 75.0 placeholders.
    """
    fluency = scored.fluency_score

    # Base scores. Text submissions have no measurable pace, so pacing tracks written
    # fluency rather than an invented "optimal 100".
    if wpm_metrics["pacing_quality"] == "not_applicable":
        pacing_score = fluency
    elif wpm_metrics["pacing_quality"] == "rushed":
        pacing_score = 60.0
    elif wpm_metrics["pacing_quality"] == "slow":
        pacing_score = 70.0
    else:
        pacing_score = 100.0

    # Penalize excessive filler words
    filler_penalty = min(filler_analysis["count"] * 2, 30)  # Max 30 point penalty

    # Tone variation score — real pitch spread when audio, else fluency proxy.
    tone_score = tone_analysis["energy_score"]
    if tone_score is None:
        tone_score = fluency
    if tone_analysis["monotone_risk"]:
        tone_score -= 20
    tone_score = max(0.0, min(100.0, tone_score))

    # Structure score
    structure_score = structure_analysis["structure_score"]

    # Clarity score — real SNR when audio, else fluency proxy.
    clarity_score = clarity_analysis["clarity_score"]
    if clarity_score is None:
        clarity_score = fluency

    # Calculate overall based on speech type priorities
    if speech_config.get("prioritize_energy"):
        # Motivational: prioritize tone and energy
        overall = (0.35 * tone_score + 0.25 * structure_score + 
                   0.2 * pacing_score + 0.1 * clarity_score + 
                   0.1 * (100 - filler_penalty))
    elif speech_config.get("prioritize_storytelling"):
        # TED-style: prioritize structure and engagement
        overall = (0.3 * structure_score + 0.25 * tone_score + 
                   0.2 * pacing_score + 0.15 * clarity_score + 
                   0.1 * (100 - filler_penalty))
    elif speech_config.get("prioritize_structure"):
        # Business pitch: prioritize structure and persuasiveness
        overall = (0.35 * structure_score + 0.2 * pacing_score + 
                   0.2 * tone_score + 0.15 * clarity_score + 
                   0.1 * (100 - filler_penalty))
    elif speech_config.get("disable_corporate_tone"):
        # Casual event: prioritize warmth, lower structure weight
        overall = (0.3 * tone_score + 0.2 * structure_score + 
                   0.2 * pacing_score + 0.2 * clarity_score + 
                   0.1 * (100 - filler_penalty))
    else:
        # Default balanced scoring
        overall = (0.25 * structure_score + 0.25 * pacing_score + 
                   0.2 * tone_score + 0.15 * clarity_score + 
                   0.15 * (100 - filler_penalty))
    
    # Audience engagement derived from tone and structure
    audience_engagement = (tone_score + structure_score) / 2
    
    # Confidence score (overall adjusted for major issues)
    confidence = overall
    if clarity_analysis["issues"]:
        confidence -= 10
    
    return {
        "overall": round(max(0.0, min(100.0, overall)), 1),
        "confidence": round(max(0.0, min(100.0, confidence)), 1),
        "pacing": round(pacing_score, 1),
        "tone_variation": round(max(0.0, min(100.0, tone_score)), 1),
        "voice_clarity": round(clarity_score, 1),
        "structure": round(structure_score, 1),
        "audience_engagement": round(audience_engagement, 1),
    }


def _generate_flags(
    speech_type: str,
    wpm_metrics: Dict,
    filler_analysis: Dict,
    tone_analysis: Dict,
    structure_analysis: Dict,
    clarity_analysis: Dict,
) -> List[Dict]:
    """Generate flags for issues and suggestions"""
    flags = []
    
    # Pacing flags
    if wpm_metrics["pacing_quality"] == "rushed":
        flags.append({
            "type": "rushed_pacing",
            "message": f"Speaking at {wpm_metrics['wpm']} WPM - too fast for audience comprehension.",
            "suggestion": "Slow down and add strategic pauses after key points.",
        })
    elif wpm_metrics["pacing_quality"] == "slow":
        flags.append({
            "type": "slow_pacing",
            "message": f"Speaking at {wpm_metrics['wpm']} WPM - may lose audience engagement.",
            "suggestion": "Increase energy and pace slightly to maintain attention.",
        })
    
    # Filler word flags
    if filler_analysis["count"] > 10:
        flags.append({
            "type": "excessive_filler_words",
            "message": f"Used {filler_analysis['count']} filler words - breaks fluency.",
            "suggestion": "Practice pausing silently instead of using 'um' or 'ah'.",
        })
    
    # Tone flags
    if tone_analysis["monotone_risk"]:
        flags.append({
            "type": "monotone_delivery",
            "message": "Speech lacks vocal variety - may sound flat to audience.",
            "suggestion": "Vary your pitch and volume, especially on emotional words.",
        })
    
    # Structure flags
    for missing in structure_analysis["missing_elements"]:
        flags.append({
            "type": "missing_structure_element",
            "message": f"Speech missing key element: {missing}",
            "suggestion": f"Add a clear {missing} section to improve structure.",
        })
    
    # Clarity flags
    for issue in clarity_analysis["issues"]:
        flags.append(issue)
    
    return flags


def _generate_highlights(
    speech_type: str,
    structure_analysis: Dict,
    tone_analysis: Dict,
) -> List[Dict]:
    """Generate positive highlights"""
    highlights = []
    
    for element in structure_analysis["found_elements"]:
        highlights.append({
            "kind": "structure",
            "phrase": f"Strong {element} section",
        })
    
    if not tone_analysis["monotone_risk"]:
        highlights.append({
            "kind": "tone",
            "phrase": "Good vocal variety and energy",
        })
    
    return highlights


def _generate_feedback_summary(
    speech_type: str,
    scores: Dict,
    flags: List[Dict],
    speech_config: Dict,
) -> Tuple[str, List[str]]:
    """Generate overall summary and actionable tips"""
    
    # Generate summary based on overall score
    overall = scores["overall"]
    if overall >= 85:
        summary = "Excellent delivery! Your speech demonstrates strong structure and engaging delivery."
    elif overall >= 70:
        summary = "Good speech with room for improvement. Focus on the flagged areas to elevate your delivery."
    elif overall >= 50:
        summary = "Your speech shows potential. Work on structure and pacing to strengthen audience engagement."
    else:
        summary = "This speech needs significant revision. Focus on fundamentals: clear structure, appropriate pacing, and vocal variety."
    
    # Generate actionable tips from flags
    tips = []
    for flag in flags:
        if flag.get("suggestion"):
            tips.append(flag["suggestion"])
    
    # Add speech-type specific tips
    if speech_config.get("prioritize_energy"):
        tips.append("For motivational speeches: practice varying your volume and pause for dramatic effect.")
    elif speech_config.get("prioritize_storytelling"):
        tips.append("For TED-style talks: start with a personal story to hook your audience.")
    elif speech_config.get("disable_corporate_tone"):
        tips.append("For casual events: prioritize warmth and authenticity over formal structure.")
    
    return summary, tips[:5]  # Limit to top 5 tips


def _is_nonsense_content(text: str) -> bool:
    """Check if content is too minimal/nonsense for Q&A (PSC-US-12 E-01)"""
    words = text.split()
    if len(words) < 20:
        return True
    
    # Check for repetitive patterns
    unique_words = set(word.lower() for word in words)
    if len(unique_words) < 5:
        return True
    
    return False


async def _generate_qa_question(speech_type: str, transcript: str) -> str:
    """Generate relevant Q&A question based on speech content (PSC-US-12)"""
    if not llm_client.is_configured():
        # Fallback questions
        fallback_questions = {
            "BUSINESS_PITCH": "What makes your solution unique compared to competitors?",
            "CLASSROOM": "Can you elaborate on your main supporting argument?",
            "MOTIVATIONAL": "How did you overcome the biggest challenge you mentioned?",
            "TED_TALK": "What's the one thing you hope the audience remembers?",
            "CASUAL_EVENT": "What inspired you to share this particular story?",
        }
        return fallback_questions.get(speech_type.upper(), "Can you tell us more about your main point?")
    
    prompt = f"""Based on this {str(speech_type)} transcript, generate one relevant follow-up question an audience member might ask:

Transcript: {transcript}

Generate a specific, thoughtful question related to the content. Return only the question, no explanation."""
    
    try:
        response = await llm_client.chat(
            [{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=100,
        )
        return response.strip()
    except Exception as e:
        logger.error(f"Q&A question generation failed: {e}")
        return "Can you elaborate on your main point?"


async def _evaluate_qa_response(
    original_speech: str,
    ai_question: str,
    user_response: str,
    audio_features: Optional[AudioFeatures],
) -> Dict:
    """Evaluate Q&A response performance (PSC-US-12)"""
    
    # Check for silence/freezing (PSC-US-12 E-02)
    if len(user_response.strip()) < 10:
        return {
            "composure": 30.0,
            "relevance": 20.0,
            "feedback": "You froze when asked the question. Practice buying time with phrases like 'That's a great question, let me think about that...'",
        }
    
    # Check for aggressive/defensive tone (PSC-US-12 E-03)
    aggressive_indicators = ["wrong", "stupid", "ridiculous", "don't agree", "incorrect"]
    if any(indicator in user_response.lower() for indicator in aggressive_indicators):
        return {
            "composure": 40.0,
            "relevance": 60.0,
            "feedback": "Your response sounded defensive. Accept audience questions gracefully, even if you disagree.",
        }
    
    # Use LLM for detailed evaluation if available
    if llm_client.is_configured():
        prompt = f"""Evaluate this Q&A response:

Original Speech Context: {original_speech[:500]}
Question: {ai_question}
Response: {user_response}

Rate the response on:
1. Composure (0-100): Did the speaker remain calm and professional?
2. Relevance (0-100): Did the response directly address the question?

Provide a brief, constructive feedback tip.

Return JSON with keys: composure, relevance, feedback"""
        
        try:
            result = await llm_client.chat_json(
                [{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=200,
            )
            return {
                "composure": result.get("composure", 70.0),
                "relevance": result.get("relevance", 70.0),
                "feedback": result.get("feedback", "Good response."),
            }
        except Exception as e:
            logger.error(f"Q&A evaluation failed: {e}")
    
    # Fallback heuristic evaluation
    words = user_response.split()
    composure = min(100.0, 50.0 + len(words) * 2)  # Longer responses suggest more composure
    relevance = 75.0  # Default assumption
    
    return {
        "composure": round(composure, 1),
        "relevance": round(relevance, 1),
        "feedback": "Good effort. Continue practicing impromptu responses to build confidence.",
    }
