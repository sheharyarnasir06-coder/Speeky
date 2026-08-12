"""
Initial Communication Assessment + Results Summary.

InMemoryStorage is replaced by BaselineAssessment rows — a row with
completedAt=None *is* "in progress" (no separate current-assessment state).
"""

import logging
import random
from pathlib import Path
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from fastapi import Depends, WebSocket
from fastapi.responses import JSONResponse
from prisma import Json

from lib import relevance
from lib.confidence_engine import ConfidenceScoreEngine, SessionScore
from lib.prisma_client import db
from middlewares.auth_middleware import require_auth, ws_require_auth
from prisma.enums import AssessmentStatus, LearningLevel
from prisma.models import BaselineAssessment
from schemas.assessment_schemas import SubmitResponseSchema

logger = logging.getLogger(__name__)


# ── Question bank ────────────────────────────────────────────────────────────
@dataclass
class AssessmentQuestion:
    question_id: str
    text: str
    category: str


class AssessmentQuestionBank:
    def __init__(self):
        path = Path(__file__).parent.parent / "data" / "assessment_qs.json"

        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)

            self.questions = {
                category: [AssessmentQuestion(**q) for q in questions]
                for category, questions in raw.items()
            }

        self._by_id = {q.question_id: q for qs in self.questions.values() for q in qs}
    
    def get_assessment_questions(
        self,
        text_count: int = 3,
        audio_count: int = 7,
    ) -> List[AssessmentQuestion]:
        text_categories = {"introduction", "vocabulary"}
        audio_categories = {"fluency", "pronunciation"}

        text_questions = [
            q for category, questions in self.questions.items()
            if category in text_categories
            for q in questions
        ]
        audio_questions = [
            q for category, questions in self.questions.items()
            if category in audio_categories
            for q in questions
        ]

        selected: List[AssessmentQuestion] = []
        selected.extend(random.sample(text_questions, min(text_count, len(text_questions))))
        selected.extend(random.sample(audio_questions, min(audio_count, len(audio_questions))))

        target_count = text_count + audio_count
        if len(selected) < target_count:
            all_questions = [q for qs in self.questions.values() for q in qs]
            remaining = [q for q in all_questions if q not in selected]
            needed = min(target_count - len(selected), len(remaining))
            if needed:
                selected.extend(random.sample(remaining, needed))

        random.shuffle(selected)
        return selected[:target_count]

    @staticmethod
    def get_question_mode(question: AssessmentQuestion) -> str:
        return "audio" if question.category in {"fluency", "pronunciation"} else "text"

    def get_by_id(self, question_id: str) -> Optional[AssessmentQuestion]:
        return self._by_id.get(question_id)


# ── Integrity checks  ───────────────────────────
class AssessmentIntegrityChecker:
    def check_text_integrity(self, text: str, clipboard_detected: bool = False) -> Tuple[bool, Optional[str]]:
        if not text or not text.strip():
            return True, "Empty text response"
        if clipboard_detected:
            return True, "Clipboard paste detected"

        words = text.split()
        if words:
            avg_length = sum(len(w) for w in words) / len(words)
            if avg_length < 2:
                return True, "Suspiciously short words (possible gibberish)"

        if re.search(r"(.)\1{4,}", text):
            return True, "Repetitive character pattern detected"

        return False, None

    def check_response_consistency(self, texts: List[str]) -> Tuple[bool, Optional[str]]:
        if len(texts) < 2:
            return False, None
        if len(set(texts)) == 1:
            return True, "Identical responses across multiple questions"
        return False, None


_question_bank = AssessmentQuestionBank()
_integrity_checker = AssessmentIntegrityChecker()

NEXT_STEPS_MAP = {
    LearningLevel.BEGINNER: [
        "Start with daily 5-minute practice sessions",
        "Focus on comfortable, everyday conversation topics",
        "Use the AI Conversation Practice for low-pressure learning",
    ],
    LearningLevel.ELEMENTARY: [
        "Practice common workplace and daily life scenarios",
        "Work on expanding your vocabulary range",
        "Try Scenario-Based Learning for real-world context",
    ],
    LearningLevel.INTERMEDIATE: [
        "Challenge yourself with technical and professional topics",
        "Focus on refining your fluency and natural flow",
        "Practice mock interviews for career development",
    ],
    LearningLevel.UPPER_INTERMEDIATE: [
        "Engage with complex topics and abstract discussions",
        "Work on nuance and sophisticated expression",
        "Practice advanced scenarios and negotiations",
    ],
    LearningLevel.ADVANCED: [
        "Focus on specialized vocabulary for your field",
        "Practice high-stakes communication scenarios",
        "Work on subtle aspects of tone and style",
    ],
    LearningLevel.PROFICIENT: [
        "Maintain and refine your advanced skills",
        "Practice complex, multi-participant discussions",
        "Focus on communication leadership and mentoring",
    ],
}

_LEVEL_LABELS = {
    LearningLevel.BEGINNER: "Foundational",
    LearningLevel.ELEMENTARY: "Developing",
    LearningLevel.INTERMEDIATE: "Progressing",
    LearningLevel.UPPER_INTERMEDIATE: "Advanced",
    LearningLevel.ADVANCED: "Proficient",
    LearningLevel.PROFICIENT: "Expert",
}


def _level_label(level: LearningLevel) -> str:
    return _LEVEL_LABELS.get(level, "Developing")


def _level_rank(level: LearningLevel) -> int:
    return list(LearningLevel).index(level)


#: Scoring outcome for a completed row, shared with every other scored module. Kept as
#: plain strings rather than a Prisma enum so adding an outcome later needs no migration
#: on a column that is only ever read by name.
SCORING_STATUS_SCORED = relevance.STATUS_SCORED
SCORING_STATUS_UNAVAILABLE = relevance.STATUS_UNAVAILABLE


def _estimate_vocabulary_score(text: str) -> float:
    """Thin wrapper kept for the historical call sites; the implementation now lives in
    lib/session_scorer.py so the strict/lenient split has exactly one definition."""
    from lib.session_scorer import estimate_vocabulary_score

    return estimate_vocabulary_score(text, strict=True)


def _relevance_fields(judgement: relevance.RelevanceResult) -> Dict:
    """Persist the relevance verdict alongside the scores so a low result is explainable
    ("answered a different question") rather than an unexplained number."""
    return {
        "relevance": judgement.relevance,
        "relevance_verdict": judgement.verdict,
        "relevance_source": judgement.source,
        "relevance_reason": judgement.reason,
    }


def _determine_learning_level(confidence_score: float) -> LearningLevel:
    if confidence_score >= 90:
        return LearningLevel.PROFICIENT
    elif confidence_score >= 80:
        return LearningLevel.ADVANCED
    elif confidence_score >= 70:
        return LearningLevel.UPPER_INTERMEDIATE
    elif confidence_score >= 60:
        return LearningLevel.INTERMEDIATE
    elif confidence_score >= 40:
        return LearningLevel.ELEMENTARY
    else:
        return LearningLevel.BEGINNER


async def _score_confidence(user_id: str, new_session: SessionScore) -> float:
    """Reconstruct the engine from completed history + this new session (stateless per request)."""
    engine = ConfidenceScoreEngine()
    prior = await db.baselineassessment.find_many(
        where={"userId": user_id, "completedAt": {"not": None}},
        order={"completedAt": "asc"},
    )
    for row in prior:
        engine.add_session_score(
            SessionScore(
                timestamp=row.completedAt,
                fluency_score=row.fluencyScore or 0.0,
                vocabulary_score=row.vocabularyScore or 0.0,
                pronunciation_score=row.pronunciationScore,
                is_text_only=row.pronunciationScore is None,
                is_complete=True,
            )
        )
    engine.add_session_score(new_session)
    return engine.get_confidence_score()


# ── Controllers ───────────────────────────────────────────────────────────────
async def start_assessment(user_id: str = Depends(require_auth)):
    # Public baseline entry: refuse a second baseline once one is already completed —
    # repeat runs must go through /reassessment/start so the 30-day cycle + early-retake
    # cooldown apply. Re-assessment calls _begin_assessment directly to bypass this guard.
    completed = await db.baselineassessment.count(
        where={"userId": user_id, "completedAt": {"not": None}}
    )
    if completed:
        return JSONResponse(
            status_code=400,
            content={"error": "Baseline already completed. Use re-assessment to retake."},
        )
    return await _begin_assessment(user_id)


async def _begin_assessment(user_id: str):
    existing = await db.baselineassessment.find_first(where={"userId": user_id, "completedAt": None})
    if existing:
        # BAS-US-01 E-02 recovery: every question is already answered but the row never
        # completed (scoring crashed / the app died between the last answer and scoring).
        # Handing back the last question here would dead-end the user for good — the next
        # submit answers "No more questions to submit", /start keeps returning the same
        # question, and assessmentStatus stays IN_PROGRESS so the whole app remains locked.
        # /start is the one entry point the UI always has after a crash (the assessment_id
        # is gone), so retry scoring from the saved responses right here instead.
        if existing.currentIndex >= len(existing.questionIds):
            result = await _try_complete_assessment(existing)
            if result.get("status") == "processing":
                return result  # still failing — honest "results processing", not a dead question
            return {**result, "resumed": True, "recovered": True}

        # Resume, don't dead-end. A browser back / refresh / accidental navigation loses
        # the client-side assessment_id; the old 400 then trapped the user (can't start a
        # second, can't resume the first). Return the current question so "Start" resumes
        # exactly where they left off.
        idx = min(existing.currentIndex, len(existing.questionIds) - 1)
        resume_q = _question_bank.get_by_id(existing.questionIds[idx])
        return {
            "assessment_id": existing.id,
            "total_questions": len(existing.questionIds),
            "current_question": resume_q.text if resume_q else "",
            "question_index": idx,
            "question_mode": _question_bank.get_question_mode(resume_q) if resume_q else "text",
            "estimated_duration_minutes": len(existing.questionIds),
            "resumed": True,
        }

    questions = _question_bank.get_assessment_questions(text_count=3, audio_count=7)

    assessment = await db.baselineassessment.create(
        data={"userId": user_id, "questionIds": [q.question_id for q in questions]}
    )
    await db.user.update(where={"id": user_id}, data={"assessmentStatus": AssessmentStatus.IN_PROGRESS})

    return {
        "assessment_id": assessment.id,
        "total_questions": len(questions),
        "current_question": questions[0].text,
        "question_index": 0,
        "question_mode": _question_bank.get_question_mode(questions[0]),
        "estimated_duration_minutes": len(questions),
    }


async def submit_response(
    assessment_id: str, payload: SubmitResponseSchema, user_id: str = Depends(require_auth)
):
    assessment = await db.baselineassessment.find_unique(where={"id": assessment_id})
    if not assessment or assessment.userId != user_id:
        return JSONResponse(status_code=404, content={"error": "Assessment not found"})
    elif assessment.completedAt:
        return JSONResponse(status_code=400, content={"error": "Assessment already completed"})
    elif assessment.currentIndex >= len(assessment.questionIds):
        return JSONResponse(status_code=400, content={"error": "No more questions to submit"})
    
    question_id = assessment.questionIds[assessment.currentIndex]
    question = _question_bank.get_by_id(question_id)

    is_flagged, flag_reason = _integrity_checker.check_text_integrity(
        payload.text_data, payload.clipboard_detected
    )
    is_audio = payload.audio_features is not None

    # Does the answer address the question? Nothing here used to ask, so a fluent answer
    # about an unrelated subject scored exactly like a fluent answer to the question.
    judgement = await relevance.assess(
        question.text if question else None,
        payload.text_data,
        context=f"baseline English assessment, {question.category} question" if question else None,
    )

    if is_flagged:
        # An integrity-flagged answer is scored ZERO, not dropped. It used to carry
        # processing_success=False, which _complete_assessment filtered out entirely —
        # so nine blank answers plus one real one scored exactly like one real answer.
        # processing_success now means only "the scorer ran", which is what it says.
        processing_result = {
            "question_id": question_id,
            "category": question.category if question else None,
            "is_flagged": True,
            "flag_reason": flag_reason,
            "transcription": payload.text_data,
            "fluency_score": 0.0,
            "pronunciation_score": None,
            "vocabulary_score": 0.0,
            "is_audio": is_audio,
            "processing_success": True,
            "relevance": 0.0,
            "relevance_verdict": "integrity_flag",
            "relevance_source": relevance.SOURCE_GATE,
            "relevance_reason": flag_reason,
        }
    elif is_audio:
        # AUDIO pipeline — spoken answer scored via fluency + pronunciation.
        from lib.session_scorer import AudioFeatures, aggregate_audio_turns, score_audio_session

        af = payload.audio_features
        if af.turns:
            # Per-utterance timings combined by the function built for exactly this, so a
            # natural pause between utterances is not counted as hesitation within one.
            combined = aggregate_audio_turns([
                AudioFeatures(
                    transcript=t.transcript,
                    duration_seconds=t.duration_seconds,
                    word_timings=t.word_timings,
                )
                for t in af.turns
            ])
            features = AudioFeatures(
                # The user can edit the transcript before submitting, so the submitted
                # text wins; the delivery metrics still come from what was actually said.
                transcript=payload.text_data,
                duration_seconds=combined.duration_seconds,
                speech_rate=combined.speech_rate,
                pause_count=combined.pause_count,
                mean_pause_duration=combined.mean_pause_duration,
                filled_pauses=af.filled_pauses,
                avg_db=af.avg_db,
                pronunciation_score=af.pronunciation_score,
            )
        else:
            features = AudioFeatures(
                transcript=payload.text_data,
                duration_seconds=af.duration_seconds,
                word_timings=af.word_timings,
                speech_rate=af.speech_rate,
                pause_count=af.pause_count,
                mean_pause_duration=af.mean_pause_duration,
                filled_pauses=af.filled_pauses,
                avg_db=af.avg_db,
                pronunciation_score=af.pronunciation_score,
            )
        scored = score_audio_session(features, strict=True)
        processing_result = {
            "question_id": question_id,
            "category": question.category if question else None,
            "is_flagged": False,
            "flag_reason": None,
            "transcription": payload.text_data,
            "fluency_score": relevance.apply(scored.fluency_score, judgement.relevance),
            "pronunciation_score": relevance.apply(scored.pronunciation_score, judgement.relevance),
            "vocabulary_score": relevance.apply(scored.vocabulary_score, judgement.relevance),
            "is_audio": True,
            "processing_success": judgement.graded,
            **_relevance_fields(judgement),
        }
    else:
        # TEXT pipeline — typed answer. Written fluency is a real measure (length,
        # diversity, sentence structure); it used to be hardcoded to 0 here, which both
        # threw the measurement away and — because only audio answers feed the fluency
        # mean — let mixed assessments avoid ever paying for it.
        from lib.session_scorer import score_text_session

        scored = score_text_session(payload.text_data, strict=True)
        processing_result = {
            "question_id": question_id,
            "category": question.category if question else None,
            "is_flagged": False,
            "flag_reason": None,
            "transcription": payload.text_data,
            "fluency_score": relevance.apply(scored.fluency_score, judgement.relevance),
            "pronunciation_score": None,
            "vocabulary_score": relevance.apply(scored.vocabulary_score, judgement.relevance),
            "is_audio": False,
            "processing_success": judgement.graded,
            **_relevance_fields(judgement),
        }

    responses = list(assessment.responses) + [processing_result]
    new_index = assessment.currentIndex + 1

    updated = await db.baselineassessment.update(
        where={"id": assessment_id},
        data={"responses": Json(responses), "currentIndex": new_index},
    )

    if new_index >= len(assessment.questionIds):
        return await _try_complete_assessment(updated)

    next_question = _question_bank.get_by_id(assessment.questionIds[new_index])
    return {
        "status": "in_progress",
        "next_question": next_question.text if next_question else None,
        "question_index": new_index,
        "next_question_mode": _question_bank.get_question_mode(next_question) if next_question else None,
        "previous_result": processing_result,
    }


async def _try_complete_assessment(assessment: BaselineAssessment) -> Dict:
    """BAS-US-01 E-02: responses are already durably saved by the time this runs (the
    caller persists them before invoking completion), so a scoring failure here — a
    confidence-engine bug, a transient DB error — must not strand the user with no way
    forward. Flag the row for retry instead of raising, so a later call (background
    job or the next /summary request) can pick up scoring again from saved responses."""
    try:
        return await _complete_assessment(assessment)
    except Exception:
        logger.exception(f"Scoring failed for assessment {assessment.id}; flagging for retry")
        await db.baselineassessment.update(
            where={"id": assessment.id},
            data={"scoringFailed": True},
        )
        return {
            "status": "processing",
            "assessment_id": assessment.id,
            "message": "Your responses are saved and your results are still processing. Check back shortly.",
        }


async def _complete_assessment(assessment: BaselineAssessment) -> Dict:
    responses = assessment.responses

    # If the relevance grader could not run for any answer, this assessment has no
    # honest score. Producing one anyway — as the offline heuristics used to — is worse
    # than producing none, because the user cannot tell the difference.
    ungraded = [r for r in responses if r.get("relevance_source") == relevance.SOURCE_UNAVAILABLE]
    if ungraded:
        return await _mark_scoring_unavailable(assessment, len(ungraded), len(responses))

    # Every answered question counts. Answers that failed the integrity check or were
    # judged irrelevant contribute their (zero) scores rather than being filtered out.
    scored_responses = [r for r in responses if "vocabulary_score" in r]

    vocabulary_scores = [r["vocabulary_score"] or 0.0 for r in scored_responses]
    avg_vocabulary = round(sum(vocabulary_scores) / len(vocabulary_scores), 2) if vocabulary_scores else 0.0

    # Fluency is now measured on BOTH pipelines — written fluency for typed answers,
    # delivery fluency for spoken ones — so it averages across every answer instead of
    # only the audio ones. Pronunciation stays audio-only: there is no such measurement
    # for typed text, and None makes confidence_engine renormalize rather than average
    # in a zero (see ScoringWeights normalization in confidence_engine.py).
    fluency_scores = [r["fluency_score"] or 0.0 for r in scored_responses]
    avg_fluency = round(sum(fluency_scores) / len(fluency_scores), 2) if fluency_scores else 0.0

    audio_responses = [r for r in scored_responses if r.get("is_audio")]
    pron_scores = [r["pronunciation_score"] for r in audio_responses if r.get("pronunciation_score") is not None]
    avg_pronunciation = round(sum(pron_scores) / len(pron_scores), 2) if pron_scores else None
    is_text_only = not audio_responses

    is_flagged, flag_reason = _integrity_checker.check_response_consistency(
        [r["transcription"] for r in scored_responses if r.get("transcription")]
    )
    if not is_flagged:
        # Any flagged answer now raises the flag. The old strict-majority rule existed
        # because the flag changed nothing numerically; now that flagged answers score
        # zero, the flag is what explains the resulting low score to the user.
        flagged_responses = [r for r in responses if r.get("is_flagged")]
        is_flagged = bool(flagged_responses)
        flag_reason = flagged_responses[0].get("flag_reason") if flagged_responses else None

    confidence_score = await _score_confidence(
        assessment.userId,
        SessionScore(
            timestamp=datetime.now(timezone.utc),
            fluency_score=avg_fluency,
            vocabulary_score=avg_vocabulary,
            pronunciation_score=avg_pronunciation,
            is_text_only=is_text_only,
            is_complete=True,
        ),
    )
    learning_level = _determine_learning_level(confidence_score)
    completed_at = datetime.now(timezone.utc)

    updated = await db.baselineassessment.update(
        where={"id": assessment.id},
        data={
            "completedAt": completed_at,
            "scoringFailed": False,
            "fluencyScore": avg_fluency,
            "vocabularyScore": avg_vocabulary,
            "pronunciationScore": avg_pronunciation,
            "confidenceScore": confidence_score,
            "learningLevel": learning_level,
            "isFlagged": is_flagged,
            "flagReason": flag_reason,
            "scoringStatus": SCORING_STATUS_SCORED,
        },
    )
    await db.user.update(
        where={"id": assessment.userId},
        data={"assessmentStatus": AssessmentStatus.COMPLETED, "learningLevel": learning_level},
    )

    # regression check — only meaningful once a prior completed
    # assessment exists. Local import breaks the assessment/reassessment
    # service import cycle (reassessment_service reuses start_assessment).
    from services import reassessment_service

    regression = None
    prior_count = await db.baselineassessment.count(
        where={"userId": assessment.userId, "completedAt": {"not": None}, "id": {"not": assessment.id}}
    )
    if prior_count > 0:
        regression_data = await reassessment_service.detect_score_regression(
            assessment.userId, confidence_score, exclude_assessment_id=assessment.id
        )
        regression = reassessment_service.handle_regression_flag(regression_data)

    return {
        "status": "completed",
        "scoring_status": SCORING_STATUS_SCORED,
        "assessment_id": updated.id,
        "confidence_score": confidence_score,
        "fluency_score": avg_fluency,
        "vocabulary_score": avg_vocabulary,
        "pronunciation_score": avg_pronunciation,
        "learning_level": learning_level.value,
        "duration_seconds": (completed_at - assessment.startedAt).total_seconds(),
        "is_flagged": is_flagged,
        "flag_reason": flag_reason,
        "regression": regression,
    }


async def _mark_scoring_unavailable(
    assessment: BaselineAssessment, ungraded_count: int, total: int
) -> Dict:
    """The relevance grader could not run — record that, and produce no score.

    Reuses the existing scoringFailed retry path: the row stays incomplete, so a later
    /summary call re-runs scoring against the already-saved responses once the grader is
    reachable again. Nothing is lost and nothing is invented in the meantime.
    """
    logger.warning(
        "Relevance grader unavailable for %s of %s answers on assessment %s; withholding score",
        ungraded_count, total, assessment.id,
    )
    await db.baselineassessment.update(
        where={"id": assessment.id},
        data={"scoringFailed": True, "scoringStatus": SCORING_STATUS_UNAVAILABLE},
    )
    return {
        "status": "processing",
        "scoring_status": SCORING_STATUS_UNAVAILABLE,
        "assessment_id": assessment.id,
        "confidence_score": None,
        "message": "Your responses are saved. Scoring is temporarily unavailable — check back shortly.",
    }


# ── Voice mode: WebSocket transpor. Replaces the browser Web Speech API path, 
# which needed a secure context (HTTPS/localhost) and was Chromium-only — the cause of the original baseline audio error.
async def voice_socket(websocket: WebSocket, assessment_id: str):
    from lib import voice_ws

    user_id = await ws_require_auth(websocket)
    if user_id is None:
        return  # ws_require_auth already closed the socket

    assessment = await db.baselineassessment.find_unique(where={"id": assessment_id})
    if not assessment or assessment.userId != user_id:
        await websocket.close(code=4404, reason="Assessment not found")
        return
    if assessment.completedAt:
        await websocket.close(code=4409, reason="Assessment already completed")
        return

    await websocket.accept()
    # "timed" rather than "transcript": the assessment scores pause frequency and speech
    # rate, and "transcript" mode does not compute word timings. Without them
    # _derive_timing defaulted pause_count to 0, so every spoken answer collected the
    # full "no pauses" bonus — flawless delivery inferred from data that was never captured.
    await voice_ws.serve(websocket, mode="timed")


async def restart_assessment(user_id: str = Depends(require_auth)):
    """Discard an unfinished baseline and hand back a fresh one (BAS-US-01 E-02 escape hatch).

    Without this, a baseline that can never finish scoring — corrupt saved responses, a
    permanently failing scorer — leaves the account stuck at `assessment_required` with
    every gated feature locked and no user-reachable way out.

    Deliberately refuses once a baseline HAS completed: that path must go through
    /reassessment/start so the 30-day cycle and early-retake cooldown still apply, and so
    a finished baseline can never be silently thrown away.
    """
    completed = await db.baselineassessment.count(
        where={"userId": user_id, "completedAt": {"not": None}}
    )
    if completed:
        return JSONResponse(
            status_code=400,
            content={"error": "Baseline already completed. Use re-assessment to retake."},
        )

    discarded = await db.baselineassessment.delete_many(
        where={"userId": user_id, "completedAt": None}
    )
    # Back to UNASSESSED so gating reports "not started" rather than a phantom in-progress run.
    await db.user.update(
        where={"id": user_id}, data={"assessmentStatus": AssessmentStatus.UNASSESSED}
    )
    logger.info("Restarted baseline for user %s (discarded %s unfinished row(s))", user_id, discarded)

    fresh = await _begin_assessment(user_id)
    return {**fresh, "restarted": True, "discarded_attempts": discarded}


async def get_assessment_status(assessment_id: str, user_id: str = Depends(require_auth)):
    assessment = await db.baselineassessment.find_unique(where={"id": assessment_id})
    if not assessment or assessment.userId != user_id:
        return JSONResponse(status_code=404, content={"error": "Assessment not found"})

    if assessment.completedAt:
        return {
            "status": "completed",
            "confidence_score": assessment.confidenceScore,
            "learning_level": assessment.learningLevel,
        }

    elapsed = (datetime.now(timezone.utc) - assessment.startedAt).total_seconds()
    all_answered = assessment.currentIndex >= len(assessment.questionIds)
    return {
        "status": "processing" if (all_answered and assessment.scoringFailed) else "in_progress",
        "current_question_index": assessment.currentIndex,
        "total_questions": len(assessment.questionIds),
        "elapsed_seconds": elapsed,
    }


def _encouraging_message(confidence_score: float, learning_level: LearningLevel) -> str:
    if confidence_score >= 80:
        messages = [
            "Excellent start! You have strong communication foundations to build upon.",
            "Great job! Your confidence is high - let's maintain this momentum.",
            "Wonderful! You're showing advanced communication skills already.",
        ]
    elif confidence_score >= 60:
        messages = [
            "Good start! You have solid fundamentals with room to grow.",
            "Well done! Your communication skills are developing nicely.",
            "Nice work! You're on a great path to improvement.",
        ]
    elif confidence_score >= 40:
        messages = [
            "Welcome! This is your starting point - every expert was once a beginner.",
            "Great first step! You've begun your journey to better communication.",
            "Perfect place to start! Let's build your confidence together.",
        ]
    else:
        messages = [
            "Welcome! This assessment helps us understand where to begin your journey.",
            "Great that you're here! Let's work together to build your confidence.",
            "Starting point established! Every improvement journey begins somewhere.",
        ]
    # learning_level is whatever Prisma handed back for the enum column
    # (a plain str, not a coerced LearningLevel instance) — hash() works on
    # either, so no .value access needed here.
    return messages[hash(learning_level) % len(messages)]


def _skill_description(skill: str, score: float) -> str:
    descriptions = {
        "fluency": {
            "high": "You speak with natural flow and good pacing.",
            "medium": "You show developing flow in your speech patterns.",
            "developing": "Building your natural speaking rhythm.",
        },
        "vocabulary": {
            "high": "You use varied and appropriate vocabulary effectively.",
            "medium": "You have a good foundation with room to expand.",
            "developing": "Building your word choice variety.",
        },
        "pronunciation": {
            "high": "Your pronunciation is clear and accurate.",
            "medium": "Your pronunciation is generally clear with some areas to refine.",
            "developing": "Working on clarity and accuracy in pronunciation.",
        },
        "confidence": {
            "high": "You come across as self-assured and composed.",
            "medium": "You're showing steady confidence with room to grow.",
            "developing": "Building your confidence one session at a time.",
        },
    }
    tier = "high" if score >= 70 else "medium" if score >= 50 else "developing"
    return descriptions[skill][tier]


def _skill_strength(score: float) -> str:
    if score >= 70:
        return "strong"
    elif score >= 50:
        return "developing"
    else:
        return "emerging"


def _skill_breakdown(assessment: BaselineAssessment) -> Dict:
    breakdown = {
        "fluency": {
            "score": assessment.fluencyScore,
            "display": f"{assessment.fluencyScore:.1f}/100",
            "label": "Fluency",
            "description": _skill_description("fluency", assessment.fluencyScore),
            "strength": _skill_strength(assessment.fluencyScore),
        },
        "vocabulary": {
            "score": assessment.vocabularyScore,
            "display": f"{assessment.vocabularyScore:.1f}/100",
            "label": "Vocabulary",
            "description": _skill_description("vocabulary", assessment.vocabularyScore),
            "strength": _skill_strength(assessment.vocabularyScore),
        },
    }
    if assessment.pronunciationScore is not None:
        breakdown["pronunciation"] = {
            "score": assessment.pronunciationScore,
            "display": f"{assessment.pronunciationScore:.1f}/100",
            "label": "Pronunciation",
            "description": _skill_description("pronunciation", assessment.pronunciationScore),
            "strength": _skill_strength(assessment.pronunciationScore),
        }
    # BAS-US-01 AC: breakdown must cover Fluency/Vocabulary/Pronunciation/Confidence —
    # Confidence as its own row here, distinct from the separate top-line score above.
    breakdown["confidence"] = {
        "score": assessment.confidenceScore,
        "display": f"{assessment.confidenceScore:.1f}/100",
        "label": "Confidence",
        "description": _skill_description("confidence", assessment.confidenceScore),
        "strength": _skill_strength(assessment.confidenceScore),
    }
    return breakdown


def _positive_highlight(assessment: BaselineAssessment) -> str:
    highlights = []
    if assessment.fluencyScore >= 70:
        highlights.append("strong natural speaking flow")
    if assessment.vocabularyScore >= 70:
        highlights.append("good vocabulary range")
    if assessment.pronunciationScore is not None and assessment.pronunciationScore >= 70:
        highlights.append("clear pronunciation")

    if highlights:
        return f"You show {', '.join(highlights)} - great foundation to build on!"
    return "You've taken the first step - consistency will lead to improvement."


def _positive_framing(assessment: BaselineAssessment) -> Dict:
    return {
        "title": "Your Communication Journey Starts Here",
        "subtitle": f"Starting Level: {_level_label(assessment.learningLevel)}",
        "message": (
            f"This isn't a grade - it's your personalized starting point. "
            f"Your confidence score of {assessment.confidenceScore:.1f} shows where you are now, "
            f"and every practice session will help you improve from here."
        ),
        "highlight": _positive_highlight(assessment),
    }


async def get_results_summary(assessment_id: str, user_id: str = Depends(require_auth)):
    assessment = await db.baselineassessment.find_unique(where={"id": assessment_id})
    if not assessment or assessment.userId != user_id:
        return JSONResponse(status_code=404, content={"error": "Assessment not found"})
    if not assessment.completedAt:
        # BAS-US-01 E-02: all responses are in but a prior scoring attempt failed (or
        # this is the first attempt reaching a fully-answered assessment) — retry
        # scoring now instead of flatly 400ing forever.
        if assessment.currentIndex >= len(assessment.questionIds):
            retry_result = await _try_complete_assessment(assessment)
            if retry_result.get("status") == "processing":
                return JSONResponse(status_code=202, content=retry_result)
            assessment = await db.baselineassessment.find_unique(where={"id": assessment_id})
        else:
            return JSONResponse(status_code=400, content={"error": "Assessment not completed"})

    user = await db.user.find_unique(where={"id": user_id})

    return {
        "assessment_id": assessment.id,
        "user_id": user_id,
        "display_name": user.name or user.email,
        "scoring_status": assessment.scoringStatus,
        "completed_at": assessment.completedAt.isoformat(),
        "learning_level": {
            "level": assessment.learningLevel,
            "label": _level_label(assessment.learningLevel),
        },
        "confidence_score": {
            "score": assessment.confidenceScore,
            "display": f"{assessment.confidenceScore:.1f}/100",
            "message": _encouraging_message(assessment.confidenceScore, assessment.learningLevel),
        },
        "skill_breakdown": _skill_breakdown(assessment),
        "positive_framing": _positive_framing(assessment),
        "next_steps": NEXT_STEPS_MAP.get(assessment.learningLevel, NEXT_STEPS_MAP[LearningLevel.BEGINNER]),
        "is_flagged": assessment.isFlagged,
        "flag_reason": assessment.flagReason,
    }


async def get_progress_comparison(user_id: str = Depends(require_auth)):
    assessments = await db.baselineassessment.find_many(
        where={"userId": user_id, "completedAt": {"not": None}},
        order={"completedAt": "asc"},
    )
    if len(assessments) < 2:
        return {"message": "Not enough data to compare", "has_comparison": False}

    prev, latest = assessments[-2], assessments[-1]

    def _delta(change: float) -> Dict:
        return {
            "change": change,
            "display": f"+{change:.1f}" if change > 0 else f"{change:.1f}",
            "positive": change > 0,
        }

    return {
        "has_comparison": True,
        "days_between": (latest.completedAt - prev.completedAt).days,
        "assessment_count": len(assessments),
        "improvements": {
            "confidence": _delta(latest.confidenceScore - prev.confidenceScore),
            "fluency": _delta(latest.fluencyScore - prev.fluencyScore),
            "vocabulary": _delta(latest.vocabularyScore - prev.vocabularyScore),
        },
        "level_progression": {
            "from": _level_label(prev.learningLevel),
            "to": _level_label(latest.learningLevel),
            "improved": _level_rank(latest.learningLevel) > _level_rank(prev.learningLevel),
        },
    }
