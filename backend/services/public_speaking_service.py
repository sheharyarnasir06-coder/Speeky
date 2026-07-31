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

from fastapi import Depends, WebSocket
from prisma import Json
from lib import llm_client, prompts, prosody_engine, recording_engine, session_scorer, voice_ws
from lib.audio_io import AudioDecodeError
from lib.prisma_client import db
from lib.session_scorer import AudioFeatures, ScoredSession
from lib.speech_config import load_speech_config
from middlewares.auth_middleware import require_auth, ws_require_auth
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
    def __init__(self, pitch_range_semitones: float):
        self.pitch_range_semitones = pitch_range_semitones


class _AgentAnalysis:
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
    # A fresh start supersedes any other open Public Speaking session this user
    # has running — mirrors pronunciation_coach_service._start_session's guard.
    await db.publicspeakingsession.update_many(
        where={"userId": user_id, "status": {"in": ["in_progress", "qa_phase"]}},
        data={"status": "abandoned"},
    )

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


async def find_resumable_session(user_id: str) -> Dict:
    """Mirrors pronunciation_coach_service._find_resumable_session's shape —
    used by the Public Speaking landing page to offer Resume before showing the
    normal speech-type picker."""
    row = await db.publicspeakingsession.find_first(
        where={"userId": user_id, "status": {"in": ["in_progress", "qa_phase"]}},
        order={"createdAt": "desc"},
    )
    # Engagement gate: "in_progress" with no transcript yet means the learner landed
    # on the page and hasn't actually delivered anything — reaching "qa_phase" (or
    # having a transcript at all) is the real signal something's worth resuming.
    if not row or (row.status == "in_progress" and row.transcript is None):
        return {"found": False}
    speech_config = SPEECH_TYPES.get(row.speechType, SPEECH_TYPES["business_pitch"])
    return {
        "found": True, "session_id": row.id, "speech_type": row.speechType,
        "label": speech_config["label"], "started_at": row.createdAt.isoformat(),
    }


async def submit_turn(
    session_id: str,
    user_id: str,
    turn: PublicSpeakingTurnSchema,
) -> Dict:
    session = await db.publicspeakingsession.find_unique(where={"id": session_id})
    if not session or session.userId != user_id:
        raise SessionNotFoundError("Public speaking session not found")
    
    speech_config = SPEECH_TYPES.get(session.speechType, SPEECH_TYPES["business_pitch"])
    
    if turn.audio_data:
        transcript, audio_features, analysis = await _process_audio(turn.audio_data)
        text_content = transcript
    elif turn.audio_features or turn.duration_seconds is not None:
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
        text_content = turn.text_content or ""
        audio_features = None
        analysis = None

    scorecard = await _generate_scorecard(
        speech_type=str(session.speechType),
        text_content=text_content,
        audio_features=audio_features,
        analysis=analysis,
        speech_config=speech_config,
    )
    
    # Update session — audioFeatures is optional (Json?). Skip the key entirely when
    # there's no audio instead of sending None, which prisma-client-py can't serialize.
    update_data = {
        "transcript": text_content,
        "status": "completed" if turn.is_final else "in_progress",
        "completedAt": datetime.now(timezone.utc) if turn.is_final else None,
        "scorecard": Json(scorecard),
    }
    if audio_features:
        update_data["audioFeatures"] = Json(asdict(audio_features))

    await db.publicspeakingsession.update(
        where={"id": session_id},
        data=update_data,
    )
    
    should_trigger_qa = (
        turn.is_final and 
        len(text_content) > 100 and
        not _is_nonsense_content(text_content)
    )
    
    if should_trigger_qa:
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
    session = await db.publicspeakingsession.find_unique(where={"id": session_id})
    if not session or session.userId != user_id:
        raise SessionNotFoundError("Public speaking session not found")
    
    if session.status != "qa_phase":
        raise InvalidSubmissionError("This session is not in the Q&A phase.")
    
    if response.audio_data:
        transcript, audio_features, _analysis = await _process_audio(response.audio_data)
        text_content = transcript
    elif response.duration_seconds is not None:
        text_content = response.text_content or ""
        audio_features = AudioFeatures(transcript=text_content, duration_seconds=response.duration_seconds)
    else:
        text_content = response.text_content or ""
        audio_features = None
    
    qa_score = await _evaluate_qa_response(
        original_speech=session.transcript or "",
        ai_question=session.aiQuestion or "",
        user_response=text_content,
        audio_features=audio_features,
    )
    
    await db.publicspeakingsession.update(
        where={"id": session_id},
        data={
            "userQaResponse": text_content,
            "status": "completed",
            "completedAt": datetime.now(timezone.utc),
            "qaScore": Json(qa_score),
        }
    )
    
    updated_scorecard = session.scorecard or {}
    updated_scorecard["qa_handling"] = qa_score
    
    return {
        "qa_score": qa_score,
        "updated_scorecard": updated_scorecard,
        "session_id": session_id,
    }


# ── Voice mode: WebSocket transport (backend/lib/voice_ws.py). "full": Public Speaking
# is the only caller that needs prosody + level alongside the transcript.
async def voice_socket(websocket: WebSocket, session_id: str):
    user_id = await ws_require_auth(websocket)
    if user_id is None:
        return  # ws_require_auth already closed the socket

    session = await db.publicspeakingsession.find_unique(where={"id": session_id})
    if not session or session.userId != user_id:
        await websocket.close(code=4404, reason="Session not found")
        return

    await websocket.accept()
    await voice_ws.serve(websocket, mode="full")


async def get_session(session_id: str, user_id: str) -> Dict:
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


async def get_filler_words_for_session(session_id: str, user_id: str) -> Dict:
    """Return filler word breakdown + timeline for a session (PSC-US-08). Rebuilds the
    analysis from the stored transcript + audioFeatures (real word timings when audio was
    used) instead of requiring a separate stored copy."""
    session = await db.publicspeakingsession.find_unique(where={"id": session_id})
    if not session or session.userId != user_id:
        raise SessionNotFoundError("Public speaking session not found")

    transcript = session.transcript or ""
    stored_features = session.audioFeatures if isinstance(session.audioFeatures, dict) else None

    analysis = filler_word_service.analyze_filler_words(transcript, audio_features=stored_features)

    return {
        "total_filler_count": analysis.total_filler_count,
        "flawless_delivery": analysis.flawless_delivery,
        "badge": analysis.badge,
        "analysis_summary": getattr(analysis, "analysis_summary", None),
        "actionable_tip": analysis.actionable_tip,
        "timeline_markers": [
            {
                "word": m.word,
                "position": m.position,
                "start_time": m.start_time,
                "end_time": m.end_time,
            }
            for m in analysis.timeline_markers
        ],
        "filler_counts": [
            {"word": word, "count": count}
            for word, count in (analysis.filler_frequencies or {}).items()
        ],
    }


def _audio_features_json(audio_features: Optional[AudioFeatures]):
    return Json(asdict(audio_features)) if audio_features else None


async def _process_audio(
    audio_data: str,
) -> Tuple[str, Optional[AudioFeatures], Optional["recording_engine.RecordingAnalysis"]]:
    try:
        raw = audio_data.split(",", 1)[1] if audio_data.startswith("data:") else audio_data
        audio_bytes = base64.b64decode(raw)
        config = load_speech_config()
        analysis = recording_engine.analyze_recording(audio_bytes, config)
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
    if audio_features:
        scored = session_scorer.score_audio_session(audio_features)
    else:
        scored = session_scorer.score_text_session(text_content)

    wpm_metrics = _calculate_wpm(text_content, audio_features)
    filler_analysis = _analyze_filler_words(text_content, audio_features)
    tone_analysis = _analyze_tone_variation(text_content, analysis)
    structure_analysis = _evaluate_structure(speech_type, text_content, speech_config)
    clarity_analysis = _analyze_voice_clarity(analysis)

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
    words = text.split()
    word_count = len(words)

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
    sentences = [s.strip() for s in text.split('.') if s.strip()]

    if analysis is not None and analysis.prosody is not None:
        pitch_range = float(analysis.prosody.pitch_range_semitones)
        energy_score = max(0.0, min(100.0, (pitch_range / 10.0) * 100.0))
        monotone_risk = pitch_range < 3.0
        energy_measured = True
    else:
        sentence_lengths = [len(s.split()) for s in sentences]
        if len(sentence_lengths) > 1:
            length_variance = max(sentence_lengths) - min(sentence_lengths)
            monotone_risk = length_variance < 5
        else:
            monotone_risk = False
        energy_score = None
        energy_measured = False

    return {
        "energy_score": energy_score,
        "energy_measured": energy_measured,
        "monotone_risk": monotone_risk,
        "sentence_count": len(sentences),
    }


def _evaluate_structure(speech_type: str, text: str, speech_config: Dict) -> Dict:
    structure_elements = speech_config["structure_elements"]
    found_elements = []
    
    text_lower = text.lower()
    
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
    if analysis is None:
        return {
            "clarity_score": None,
            "projection_score": None,
            "measured": False,
            "issues": [],
        }

    issues = []

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

    snr = analysis.snr_db
    clarity_score = max(0.0, min(100.0, 50.0 + (snr - 8.0) * (50.0 / 17.0)))

    avg_db = analysis.avg_dbfs
    projection_score = max(0.0, min(100.0, (avg_db - MIC_QUIET_DB) * (100.0 / 42.0)))
    if avg_db <= MIC_QUIET_DB:
        issues.append({
            "type": "microphone_quiet",
            "message": "Microphone volume is very low. Please check device settings.",
        })
        projection_score = 50.0
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
    fluency = scored.fluency_score

    if wpm_metrics["pacing_quality"] == "not_applicable":
        pacing_score = fluency
    elif wpm_metrics["pacing_quality"] == "rushed":
        pacing_score = 60.0
    elif wpm_metrics["pacing_quality"] == "slow":
        pacing_score = 70.0
    else:
        pacing_score = 100.0

    filler_penalty = min(filler_analysis["count"] * 2, 30)

    tone_score = tone_analysis["energy_score"]
    if tone_score is None:
        tone_score = fluency
    if tone_analysis["monotone_risk"]:
        tone_score -= 20
    tone_score = max(0.0, min(100.0, tone_score))

    structure_score = structure_analysis["structure_score"]

    clarity_score = clarity_analysis["clarity_score"]
    if clarity_score is None:
        clarity_score = fluency

    if speech_config.get("prioritize_energy"):
        overall = (0.35 * tone_score + 0.25 * structure_score + 
                   0.2 * pacing_score + 0.1 * clarity_score + 
                   0.1 * (100 - filler_penalty))
    elif speech_config.get("prioritize_storytelling"):
        overall = (0.3 * structure_score + 0.25 * tone_score + 
                   0.2 * pacing_score + 0.15 * clarity_score + 
                   0.1 * (100 - filler_penalty))
    elif speech_config.get("prioritize_structure"):
        overall = (0.35 * structure_score + 0.2 * pacing_score + 
                   0.2 * tone_score + 0.15 * clarity_score + 
                   0.1 * (100 - filler_penalty))
    elif speech_config.get("disable_corporate_tone"):
        overall = (0.3 * tone_score + 0.2 * structure_score + 
                   0.2 * pacing_score + 0.2 * clarity_score + 
                   0.1 * (100 - filler_penalty))
    else:
        overall = (0.25 * structure_score + 0.25 * pacing_score + 
                   0.2 * tone_score + 0.15 * clarity_score + 
                   0.15 * (100 - filler_penalty))
    
    audience_engagement = (tone_score + structure_score) / 2
    
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
    flags = []
    
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
    
    if filler_analysis["count"] > 10:
        flags.append({
            "type": "excessive_filler_words",
            "message": f"Used {filler_analysis['count']} filler words - breaks fluency.",
            "suggestion": "Practice pausing silently instead of using 'um' or 'ah'.",
        })
    
    if tone_analysis["monotone_risk"]:
        flags.append({
            "type": "monotone_delivery",
            "message": "Speech lacks vocal variety - may sound flat to audience.",
            "suggestion": "Vary your pitch and volume, especially on emotional words.",
        })
    
    for missing in structure_analysis["missing_elements"]:
        flags.append({
            "type": "missing_structure_element",
            "message": f"Speech missing key element: {missing}",
            "suggestion": f"Add a clear {missing} section to improve structure.",
        })
    
    for issue in clarity_analysis["issues"]:
        flags.append(issue)
    
    return flags


def _generate_highlights(
    speech_type: str,
    structure_analysis: Dict,
    tone_analysis: Dict,
) -> List[Dict]:
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
    overall = scores["overall"]
    if overall >= 85:
        summary = "Excellent delivery! Your speech demonstrates strong structure and engaging delivery."
    elif overall >= 70:
        summary = "Good speech with room for improvement. Focus on the flagged areas to elevate your delivery."
    elif overall >= 50:
        summary = "Your speech shows potential. Work on structure and pacing to strengthen audience engagement."
    else:
        summary = "This speech needs significant revision. Focus on fundamentals: clear structure, appropriate pacing, and vocal variety."
    
    tips = []
    for flag in flags:
        if flag.get("suggestion"):
            tips.append(flag["suggestion"])
    
    if speech_config.get("prioritize_energy"):
        tips.append("For motivational speeches: practice varying your volume and pause for dramatic effect.")
    elif speech_config.get("prioritize_storytelling"):
        tips.append("For TED-style talks: start with a personal story to hook your audience.")
    elif speech_config.get("disable_corporate_tone"):
        tips.append("For casual events: prioritize warmth and authenticity over formal structure.")
    
    return summary, tips[:5]


def _is_nonsense_content(text: str) -> bool:
    words = text.split()
    if len(words) < 20:
        return True
    
    unique_words = set(word.lower() for word in words)
    if len(unique_words) < 5:
        return True
    
    return False


async def _generate_qa_question(speech_type: str, transcript: str) -> str:
    if not llm_client.is_configured():
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
    if len(user_response.strip()) < 10:
        return {
            "composure": 30.0,
            "relevance": 20.0,
            "feedback": "You froze when asked the question. Practice buying time with phrases like 'That's a great question, let me think about that...'",
        }
    
    aggressive_indicators = ["wrong", "stupid", "ridiculous", "don't agree", "incorrect"]
    if any(indicator in user_response.lower() for indicator in aggressive_indicators):
        return {
            "composure": 40.0,
            "relevance": 60.0,
            "feedback": "Your response sounded defensive. Accept audience questions gracefully, even if you disagree.",
        }
    
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
    
    words = user_response.split()
    composure = min(100.0, 50.0 + len(words) * 2)
    relevance = 75.0
    
    return {
        "composure": round(composure, 1),
        "relevance": round(relevance, 1),
        "feedback": "Good effort. Continue practicing impromptu responses to build confidence.",
    }