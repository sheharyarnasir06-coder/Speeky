"""
Pronunciation Coach — US-74 (engine outage/timeout fallback), US-75 (cross-
session trouble words + spaced repetition), US-76 (accessibility safeguard),
US-79 (word-level highlighting). All four share ONE scoring call — no logic
is forked per story, matching how lib/pronunciation_coach/ itself is built:
one PronunciationPipeline run, wrapped by the reliability manager (US-74),
using the accessibility-aware entry point (US-76), whose per-word ColorTier
results feed the trouble-words bank (US-75) and are returned for highlighting
(US-79). Accent selection (US-82) is threaded in too via
pipeline.resolve_config_for_user(), so a user's target accent genuinely
affects this scoring, not a second copy of it.

Where the real data comes from:
This app has no dedicated "read this target sentence aloud" recording flow —
the only place real per-word ASR timing data exists is an AUDIO-mode turn in
AI Conversation Practice (conversation_service.py), whose word_timings are
now persisted on the turn (see that file's _send_message change). There is
no fixed "target sentence" in free-form conversation, so the turn's own
transcript is used as both the target and the ASR output being aligned
against it — asr_adapter.word_timings_to_attempts() still runs for real,
producing one WordAttempt per word with its real STT timing.

Honest limitation (flagged, not hidden): Faster-Whisper does not emit
per-word confidence (see asr_adapter.py's own docstring), so every
WordAttempt's confidence defaults to the same 0.5 constant. Real code runs
on real timing data, but the resulting tier classification will look
uniform across a turn until the STT layer supplies genuine per-word
confidence. Likewise, `predicted_phonemes`/`target_phonemes` and
`repetitions` are never populated by this ASR path, so the phoneme-pair
regional-variant check and the accessibility stutter-exemption both fall
back to their pre-existing default behavior (documented in
pronunciation_pipeline.py / accessibility_profile.py already).

Persistence: AccessibilityProfileStore, TroubleWordsBank, and the
reliability manager's pending-attempt/results queues are the SAME in-memory
classes lib/pronunciation_coach/ already ships ("no DB layer exists in this
module set" — their own docstrings). Kept in-memory here too (module-level
singletons) rather than bolted onto kv_store, since that would mean
re-implementing their internal (set/dataclass-based) state as JSON on every
call without changing what the feature does — a real conversion, not a
"wiring" change. They reset on backend restart; flagged in the final
summary. Scored turn results ARE persisted for real, via kv_store, since
that's a plain JSON blob with no such conflict.
"""

import logging
from typing import Dict, Optional

from fastapi import Depends
from fastapi.responses import JSONResponse

from lib import kv_store
from lib.accent_assessment.target_accent_selection import TargetAccentSelectionService
from lib.pronunciation_coach.accessibility_profile import (
    AccessibilityProfileStore,
    score_with_accessibility,
)
from lib.pronunciation_coach.asr_adapter import word_timings_to_attempts
from lib.pronunciation_coach.pronunciation_pipeline import (
    AccentPronunciationConfigRegistry,
    ColorTier,
    PronunciationPipeline,
    SentenceScoreResult,
    WordScoreResult,
)
from lib.pronunciation_coach.pronunciation_reliability import (
    PendingResultsBoard,
    PronunciationSubmissionManager,
    ScoringServiceError,
)
from lib.pronunciation_coach.trouble_words import TroubleWordsBank
from middlewares.auth_middleware import require_auth
from schemas.pronunciation_coach_schemas import AccessibilityProfileUpdateSchema

logger = logging.getLogger(__name__)

TURN_SCORE_NAMESPACE = "pronunciation_coach_turn_scores"

# Module-level singletons. `_pipeline` is shared by every request (config
# lookups are per-call via config_override, so this is safe to reuse
# concurrently — see pronunciation_pipeline.py's own docstring on this).
_pipeline = PronunciationPipeline(
    accent_registry=AccentPronunciationConfigRegistry(),
    accent_selection_service=TargetAccentSelectionService(),
)
_accessibility_store = AccessibilityProfileStore()
_trouble_bank = TroubleWordsBank()
_submission_manager = PronunciationSubmissionManager(results_board=PendingResultsBoard())


def _turn_score_key(session_id: str, turn_index: int) -> str:
    return f"{session_id}:{turn_index}"


async def _get_owned_turn(user_id: str, session_id: str, turn_index: int):
    """Loads the conversation turn this pronunciation score is for. Returns
    (session, turn) or an (error) JSONResponse."""
    from services import conversation_service

    session = await kv_store.store.get(conversation_service.NAMESPACE, session_id)
    if session is None or session["user_id"] != user_id:
        return JSONResponse(status_code=404, content={"error": f"Conversation session {session_id} not found"})
    turns = session["turns"]
    if turn_index < 0 or turn_index >= len(turns):
        return JSONResponse(status_code=404, content={"error": f"Turn {turn_index} not found on this session"})
    turn = turns[turn_index]
    if turn["role"] != "user" or turn.get("input_mode") != "audio":
        return JSONResponse(status_code=422, content={
            "error": "This turn has no spoken audio to score pronunciation on.",
        })
    if not turn.get("word_timings"):
        return JSONResponse(status_code=422, content={
            "error": "No word-level timing data was captured for this turn — nothing to score.",
        })
    return session, turn


def _result_to_dict(result: SentenceScoreResult) -> Dict:
    return {
        "target_sentence": result.target_sentence,
        "fluency_score": result.fluency_score,
        "scoring_profile": result.scoring_profile,
        "retry_recommended": result.retry_recommended,
        "words": [_word_to_dict(w) for w in result.words],
    }


def _word_to_dict(w: WordScoreResult) -> Dict:
    return {
        "index": w.index,
        "target_word": w.target_word,
        "tier": w.tier.value,
        "strikethrough": w.strikethrough,
        "final_score": w.final_score,
        "raw_confidence_pct": w.raw_confidence_pct,
        "note": w.note,
    }


async def score_turn(user_id: str, session_id: str, turn_index: int) -> Dict:
    """
    US-74 + US-79 (+ threads US-76/US-82). Scores one audio turn through the
    shared pipeline, wrapped in the reliability manager so a transient
    failure retries/queues instead of surfacing raw errors (US-74), and
    records RED/GRAY words into the trouble-words bank (US-75).
    """
    owned = await _get_owned_turn(user_id, session_id, turn_index)
    if isinstance(owned, JSONResponse):
        return owned
    session, turn = owned

    target_sentence = turn["content"]
    attempts = word_timings_to_attempts(turn["word_timings"], target_sentence)
    profile = _accessibility_store.get(user_id)
    config = await _pipeline.resolve_config_for_user(user_id)

    async def _run_scoring() -> SentenceScoreResult:
        try:
            return score_with_accessibility(
                _pipeline, target_sentence, attempts, profile,
                accent_calibration=True, config_override=config,
            )
        except Exception as exc:  # local scoring failure -> reliability layer's hard-failure path
            raise ScoringServiceError(str(exc)) from exc

    attempt_id = _turn_score_key(session_id, turn_index)
    outcome = await _submission_manager.submit(user_id, attempt_id, audio_ref=session_id, score_callable=_run_scoring)

    response: Dict = {"status": outcome.status.value, "message": outcome.message}
    if outcome.result is not None:
        result_dict = _result_to_dict(outcome.result)
        response["result"] = result_dict
        to_store = {"user_id": user_id, **result_dict}
        if await kv_store.store.get(TURN_SCORE_NAMESPACE, attempt_id) is None:
            await kv_store.store.create(TURN_SCORE_NAMESPACE, attempt_id, to_store)
        else:
            await kv_store.store.update(TURN_SCORE_NAMESPACE, attempt_id, to_store)

        # US-75: feed RED/GRAY words into the cross-session trouble-words bank.
        for word in outcome.result.words:
            if word.tier in (ColorTier.RED, ColorTier.GRAY):
                _trouble_bank.record_word_result(user_id, session_id, word.target_word, word.tier)

    return response


async def get_turn_score(user_id: str, session_id: str, turn_index: int):
    owned = await _get_owned_turn(user_id, session_id, turn_index)
    if isinstance(owned, JSONResponse):
        return owned
    cached = await kv_store.store.get(TURN_SCORE_NAMESPACE, _turn_score_key(session_id, turn_index))
    if cached is None or cached.get("user_id") != user_id:
        return JSONResponse(status_code=404, content={
            "error": "This turn hasn't been scored yet. POST to this URL first.",
        })
    cached.pop("user_id", None)
    return cached


async def get_pending_outcomes(user_id: str) -> Dict:
    """US-74 E-05: badge/notification for scoring that finished in the background
    after the user navigated away."""
    outcomes = _submission_manager.results_board.get_and_clear(user_id)
    return {"outcomes": [
        {"attempt_id": o.attempt_id, "status": o.status.value, "message": o.message,
         "result": _result_to_dict(o.result) if o.result else None}
        for o in outcomes
    ]}


# ── US-76: accessibility profile ────────────────────────────────────────────
async def get_accessibility_profile(user_id: str) -> Dict:
    profile = _accessibility_store.get(user_id)
    return {"opted_in": profile.opted_in, "disclosed_condition": profile.disclosed_condition}


async def update_accessibility_profile(user_id: str, payload: AccessibilityProfileUpdateSchema) -> Dict:
    profile = _accessibility_store.set_opt_in(user_id, payload.opted_in, payload.disclosed_condition)
    return {"opted_in": profile.opted_in, "disclosed_condition": profile.disclosed_condition}


# ── US-75: trouble words bank ───────────────────────────────────────────────
def _entry_to_dict(e) -> Dict:
    return {
        "pattern_key": e.pattern_key,
        "display_word": e.display_word,
        "fail_session_count": e.fail_session_count,
        "correct_session_count": len(e.correct_sessions),
        "related_words": sorted(e.related_words),
        "status": e.status,
        "manually_dismissed": e.manually_dismissed,
        "last_updated": e.last_updated.isoformat(),
    }


async def get_active_trouble_words(user_id: str) -> Dict:
    return {"words": [_entry_to_dict(e) for e in _trouble_bank.get_active_bank(user_id)]}


async def get_trouble_words_archive(user_id: str) -> Dict:
    return {"words": [_entry_to_dict(e) for e in _trouble_bank.get_archive(user_id)]}


async def get_next_review_word(user_id: str) -> Dict:
    entry = _trouble_bank.get_next_review_word(user_id)
    return {"word": _entry_to_dict(entry) if entry else None}


async def dismiss_trouble_word(user_id: str, pattern_key: str) -> Dict:
    _trouble_bank.dismiss_word(user_id, pattern_key)
    return {"pattern_key": pattern_key, "dismissed": True}


# ═══════════════════════════════════════════════════════════════════════════
# FastAPI controllers
# ═══════════════════════════════════════════════════════════════════════════
async def score_turn_endpoint(session_id: str, turn_index: int, user_id: str = Depends(require_auth)):
    return await score_turn(user_id, session_id, turn_index)


async def get_turn_score_endpoint(session_id: str, turn_index: int, user_id: str = Depends(require_auth)):
    return await get_turn_score(user_id, session_id, turn_index)


async def get_pending_outcomes_endpoint(user_id: str = Depends(require_auth)):
    return await get_pending_outcomes(user_id)


async def get_accessibility_profile_endpoint(user_id: str = Depends(require_auth)):
    return await get_accessibility_profile(user_id)


async def update_accessibility_profile_endpoint(
    payload: AccessibilityProfileUpdateSchema, user_id: str = Depends(require_auth)
):
    return await update_accessibility_profile(user_id, payload)


async def get_active_trouble_words_endpoint(user_id: str = Depends(require_auth)):
    return await get_active_trouble_words(user_id)


async def get_trouble_words_archive_endpoint(user_id: str = Depends(require_auth)):
    return await get_trouble_words_archive(user_id)


async def get_next_review_word_endpoint(user_id: str = Depends(require_auth)):
    return await get_next_review_word(user_id)


async def dismiss_trouble_word_endpoint(pattern_key: str, user_id: str = Depends(require_auth)):
    return await dismiss_trouble_word(user_id, pattern_key)
"""Pronunciation Coach (GAP-03 / GAP-04 / GAP-05, US-71/72/73), the Retry Loop Mechanic
(US-071 / US-78), and Session Interruption Recovery (GAP-09) — one continuous session
flow: practice a phoneme-targeted sentence, retry specific words, resume if interrupted.

Session state is a nested dict persisted as one KvEntry blob (lib.kv_store), same
approach as interview_coach_service. Real audio scoring is NOT a stand-in here: attempt
and retry submissions take a raw audio upload and run it through lib/recording_engine.py
(STT + VAD + prosody), the same pipeline services/accent_assessment_service.py uses —
word correctness comes from lib/recording_engine.classify_word_status, not a text diff.

Also carries over from the original one-shot Pronunciation Coach (US-95), preserved
here rather than dropped when the session architecture replaced it:
  - ACC-US-01 Live Speech Verification: playback/replay detection, run on every
    attempt before scoring (_check_liveness).
  - ACC-US-11 / ACC-US-09 Local Accent Calibration: word results are calibrated for
    the user's accent/sub-dialect preference before being classified as errors
    (_score_words).
  - PRN-US-10 / PRN-US-11 "hear correct pronunciation" TTS playback
    (get_word_pronunciation_audio) — standalone, no session state needed.
"""

import base64
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from fastapi import Depends, File, Form, UploadFile
from fastapi.responses import JSONResponse, Response

from lib import kv_store, recording_engine, text_alignment, tts_client
from lib.audio_io import AudioDecodeError
from lib.prompts import (
    CODE_SWITCH_PARTIAL_OVERLAP_CEILING,
    DEFAULT_SENTENCE_SET,
    EXTENDED_ABSENCE_HOURS,
    INTERRUPTION_MESSAGES,
    MAX_CONSECUTIVE_OFFSCRIPT_ATTEMPTS,
    MAX_CONSECUTIVE_SAME_PHONEME,
    MAX_CONSECUTIVE_SILENT_ATTEMPTS,
    OFF_SCRIPT_PHONEME_OVERLAP_THRESHOLD,
    PRONUNCIATION_MESSAGES,
    RETRY_FRUSTRATION_THRESHOLD,
    RETRY_MESSAGES,
    SENTENCE_BANK,
    build_phoneme_tag,
    build_retry_diff_message,
)
from lib.recording_engine import RejectionReason
from lib.speech_config import load_speech_config
from lib.text_alignment import WordStatus
from middlewares.auth_middleware import require_auth
from schemas.pronunciation_schemas import (
    DeviceScopedRequest,
    RecordingRejectedSchema,
    StartSessionRequest,
    WordResultSchema,
)
from services import accent_calibration_service, liveness_service
from utils.feature_errors import (
    InvalidSubmissionError,
    SessionAlreadyEndedError,
    SessionNotFoundError,
    UnreadableAudioError,
    UploadTooLargeError,
)

NAMESPACE = "pronunciation_sessions"
PHONEME_ORDER = list(SENTENCE_BANK.keys())

# ── PRN-US-10 / PRN-US-11: "hear correct pronunciation" playback ────────────────
_TTS_CACHE_NS = "pronunciation_tts_cache"
_VALID_SPEEDS = ("normal", "slow")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return f"pron_{uuid.uuid4().hex[:12]}"


def _tokens(text: str) -> List[str]:
    return [w for w in re.sub(r"[^\w\s]", "", text.lower()).split() if w]


def _has_non_english_word(text: str) -> bool:
    """Stand-in code-switch detector: any word containing non-ASCII letters (no real
    language-ID model here — orthogonal to the STT/alignment pipeline, which only
    tells us WHAT was said, not WHICH language it's in)."""
    return any(any(ord(ch) > 127 for ch in tok) for tok in _tokens(text))


def _analyze_upload(audio_bytes: bytes, config, initial_prompt: Optional[str] = None) -> recording_engine.RecordingAnalysis:
    max_bytes = config.pronunciation_max_upload_mb * 1024 * 1024
    if len(audio_bytes) > max_bytes:
        raise UploadTooLargeError(f"Recording exceeds the {config.pronunciation_max_upload_mb}MB limit")
    try:
        return recording_engine.analyze_recording(audio_bytes, config, initial_prompt=initial_prompt)
    except AudioDecodeError as e:
        raise UnreadableAudioError(str(e))


def _rejection_message(reason: RejectionReason) -> str:
    return {
        RejectionReason.NO_SPEECH_DETECTED: "No speech was detected in the recording. Please try again.",
        RejectionReason.AUDIO_TOO_QUIET: "The recording is too quiet to analyze. Please move closer to the microphone.",
        RejectionReason.BACKGROUND_NOISE_TOO_HIGH: "Background noise is too high to analyze. Please try again in a quieter environment.",
        RejectionReason.INCOMPLETE_RECORDING: "The recording appears to be incomplete.",
        RejectionReason.MULTIPLE_VOICES_DETECTED: "Multiple voices were detected in the recording.",
        RejectionReason.AUDIO_DISTORTION: "Audio distortion detected. Please move farther from the microphone and try again.",
    }[reason]


async def _check_liveness(user_id: str, item_id: str, analysis: recording_engine.RecordingAnalysis, config) -> Optional[JSONResponse]:
    """ACC-US-01 Live Speech Verification: playback/replay detection, shared by
    _submit_attempt and _retry_word so neither audio-submission path in this session
    flow can bypass anti-cheat. Returns a 422 JSONResponse if the submission must be
    rejected, else None."""
    playback_reason = recording_engine.detect_playback_audio(analysis, config)
    if playback_reason is not None:
        return JSONResponse(
            status_code=422,
            content=RecordingRejectedSchema(
                reason=playback_reason.value,
                message="Detected playback audio. Live speech required.",
            ).model_dump(),
        )
    return None


def _coverage_ratio(analysis: recording_engine.RecordingAnalysis, target_text: str) -> float:
    """Real matched-word ratio for off-script/code-switch gating. Deliberately NOT the
    same "matched" count lib/text_alignment.compute_passage_coverage uses (that counts
    difflib "replace" pairs as matched too, since passage coverage just wants to know
    how much was ATTEMPTED). Here we need real content overlap: a "replace" pair means
    some transcript word occupies that slot but ISN'T the target word — an unrelated
    transcript aligns nearly every slot that way, so counting it as "matched" would make
    off-script detection nearly impossible to trigger."""
    aligned = recording_engine.align_to_sentence(analysis, target_text)
    if not aligned:
        return 1.0
    matched = sum(
        1 for a in aligned
        if a.transcript_word is not None and text_alignment.normalize(a.transcript_word) == text_alignment.normalize(a.target_word)
    )
    return matched / len(aligned)


async def _score_words(
    analysis: recording_engine.RecordingAnalysis,
    target_text: str,
    config,
    accent_preference: str,
    sub_dialect_preference: Optional[str],
) -> Tuple[List[Dict], Optional[str], str]:
    """Real per-word status (correct/stress_error/mispronounced/skipped) via the shared
    recording_engine classifier (same one services/accent_assessment_service.py and the
    one-shot Pronunciation Coach both use), then calibrated for the user's accent/
    sub-dialect preference (ACC-US-11/ACC-US-09) so a valid regional stress or phonetic
    shift isn't counted as a genuine error. Returns (word dicts, calibration warning,
    model actually used) — callers that only need pass/fail check `status == "correct"`."""
    aligned = recording_engine.align_to_sentence(analysis, target_text)
    word_results = []
    for a in aligned:
        timing = analysis.words[a.transcript_index] if a.transcript_index is not None else None
        status = recording_engine.classify_word_status(a.target_word, timing, analysis.prosody, config)
        word_results.append(WordResultSchema(
            word=a.target_word,
            target_index=a.target_index,
            status=status.value,
            confidence=round(timing.probability, 3) if timing is not None else None,
        ))
    calibrated, warning, model_used = accent_calibration_service.calibrate_word_results(
        word_results, accent_preference, sub_dialect_preference=sub_dialect_preference,
    )
    return [w.model_dump() for w in calibrated], warning, model_used


def _next_sentence(session: dict, phoneme: str) -> str:
    seen = session["seen_sentences"].setdefault(phoneme, [])
    bank = SENTENCE_BANK.get(phoneme, DEFAULT_SENTENCE_SET)
    remaining = [s for s in bank if s not in seen]
    if remaining:
        sentence = remaining[0]
        seen.append(sentence)
        return sentence
    # GAP-03: bank exhausted for this phoneme — reuse, flagged via content_gap_flagged.
    sentence = bank[len(seen) % len(bank)]
    seen.append(sentence)
    return sentence


def _advance(session: dict, had_error: bool) -> None:
    """GAP-03 E-03: stick with a phoneme the user is getting wrong, but cap consecutive
    repeats so they aren't stuck forever on one sound."""
    if had_error and session["phoneme_streak"] < MAX_CONSECUTIVE_SAME_PHONEME:
        session["phoneme_streak"] += 1
    else:
        current_index = PHONEME_ORDER.index(session["current_phoneme"])
        session["current_phoneme"] = PHONEME_ORDER[(current_index + 1) % len(PHONEME_ORDER)]
        session["phoneme_streak"] = 1
    session["current_sentence"] = _next_sentence(session, session["current_phoneme"])


async def _get_session(session_id: str, user_id: str) -> dict:
    session = await kv_store.store.get(NAMESPACE, session_id)
    if session is None or session.get("user_id") != user_id:
        raise SessionNotFoundError(f"Session {session_id} not found")
    return session


def _record_attempt(session: dict, message_key: str, words: List[Dict]) -> None:
    session["attempts"].append({
        "phoneme": session["current_phoneme"],
        "sentence": session["current_sentence"],
        "message_key": message_key,
        "words": words,
        "created_at": _now(),
    })
    session["last_completed"] = {
        "phoneme": session["current_phoneme"],
        "sentence": session["current_sentence"],
        # Lowercased keys — _retry_word looks these up by target_word.lower(), and
        # target_word here can be capitalized (sentence-initial word, proper noun like
        # "Rachel"). Mismatched casing made every such word fail "not part of the last
        # completed attempt" even though it plainly was.
        "words": {w["word"].lower(): w["status"] for w in words},
    }


# ── entry service functions ───────────────────────────────────────────────────
async def _start_session(user_id: str, device_id: str) -> dict:
    now = _now()
    # GAP-09: a fresh start supersedes any session this user still has open elsewhere —
    # what makes conflict_second_device meaningful if the old device tries to resume it.
    existing = await kv_store.store.list_values(NAMESPACE)
    for other in existing:
        if other["user_id"] == user_id and other["status"] != "completed" and not other.get("superseded"):
            other["superseded"] = True
            other["superseded_by_device_id"] = device_id
            await kv_store.store.update(NAMESPACE, other["session_id"], other)

    session_id = _new_id()
    phoneme = PHONEME_ORDER[0]
    session = {
        "session_id": session_id, "user_id": user_id, "status": "active",
        "current_phoneme": phoneme, "current_sentence": DEFAULT_SENTENCE_SET[0],
        "phoneme_streak": 1, "seen_sentences": {},
        "consecutive_silent": 0, "consecutive_offscript": 0,
        "attempts": [], "last_completed": None,
        "active_device_id": device_id, "last_active_at": now,
        "superseded": False, "superseded_by_device_id": None,
        "started_at": now, "ended_at": None,
    }
    await kv_store.store.create(NAMESPACE, session_id, session)
    return session


async def _submit_attempt(user_id: str, session_id: str, audio_bytes: bytes):
    session = await _get_session(session_id, user_id)
    if session["status"] == "completed":
        raise SessionAlreadyEndedError("Cannot submit an attempt to a completed session")

    config = load_speech_config()
    sentence = session["current_sentence"]
    # initial_prompt biases STT toward the sentence the user was asked to read — see
    # lib/stt_engine.transcribe's docstring for why this materially helps accuracy.
    analysis = _analyze_upload(audio_bytes, config, initial_prompt=sentence)

    # ACC-US-01: liveness/playback-audio check, before any content scoring — replayed
    # audio must never advance a session or update phoneme-accuracy stats.
    rejection_response = await _check_liveness(user_id, session_id, analysis, config)
    if rejection_response is not None:
        return rejection_response

    session["last_active_at"] = _now()
    transcript = analysis.transcript or ""

    # GAP-04: silence / volume gating, before any content scoring — real, driven by
    # recording_engine.analyze_recording's VAD + dBFS/SNR rejection classification.
    if analysis.rejection == RejectionReason.NO_SPEECH_DETECTED:
        session["consecutive_silent"] += 1
        key = (
            "mic_troubleshoot"
            if session["consecutive_silent"] >= MAX_CONSECUTIVE_SILENT_ATTEMPTS
            else "no_speech_detected"
        )
        await kv_store.store.update(NAMESPACE, session_id, session)
        return {"session_id": session_id, "message_key": key, "message": PRONUNCIATION_MESSAGES[key], "words": [], "transcript": transcript}

    if analysis.rejection in (RejectionReason.AUDIO_TOO_QUIET, RejectionReason.BACKGROUND_NOISE_TOO_HIGH):
        await kv_store.store.update(NAMESPACE, session_id, session)
        return {
            "session_id": session_id, "message_key": "too_quiet",
            "message": PRONUNCIATION_MESSAGES["too_quiet"], "words": [], "transcript": transcript,
        }

    session["consecutive_silent"] = 0

    # ACC-US-11 / ACC-US-09: fetch once per attempt, applied inside _score_words to
    # every branch below so a genuine regional accent never gets marked as an error.
    accent_preference, sub_dialect_preference, _ = await accent_calibration_service.get_user_accent_preference(user_id)

    # GAP-05: off-script / code-switch detection, via real alignment coverage against
    # the full target sentence (lib/text_alignment.align_words under the hood).
    coverage = _coverage_ratio(analysis, sentence)
    if coverage < OFF_SCRIPT_PHONEME_OVERLAP_THRESHOLD:
        session["consecutive_offscript"] += 1
        key = (
            "off_script_repeated"
            if session["consecutive_offscript"] >= MAX_CONSECUTIVE_OFFSCRIPT_ATTEMPTS
            else "off_script"
        )
        await kv_store.store.update(NAMESPACE, session_id, session)
        return {"session_id": session_id, "message_key": key, "message": PRONUNCIATION_MESSAGES[key], "words": [], "transcript": transcript}

    session["consecutive_offscript"] = 0
    sentence_word_count = len(_tokens(sentence))
    transcript_word_count = len(_tokens(transcript))
    # Only the portion of the sentence actually attempted gets scored — mirrors the
    # target sentence down to however many words came through, so an honestly partial/
    # code-switched attempt isn't penalized for words never reached.
    attempted_sentence = " ".join(sentence.split()[:transcript_word_count]) or sentence

    # A non-English word mixed into an otherwise on-script attempt -> code-switch, not a
    # plain mispronunciation. (A single wrong English word just gets marked incorrect below.)
    # Never a clean full read, so it never advances — same sentence again, whole thing.
    if _has_non_english_word(transcript) and coverage < CODE_SWITCH_PARTIAL_OVERLAP_CEILING:
        words, warning, model_used = await _score_words(analysis, attempted_sentence, config, accent_preference, sub_dialect_preference)
        _record_attempt(session, "code_switch_partial", words)
        await kv_store.store.update(NAMESPACE, session_id, session)
        return {
            "session_id": session_id, "message_key": "code_switch_partial",
            "message": PRONUNCIATION_MESSAGES["code_switch_partial"], "words": words, "transcript": transcript,
            "accent_profile": model_used, "warning": warning, "model_used": model_used,
        }

    # Cut off mid-sentence but what came through was on-script: mark scored words only.
    # Incomplete either way, so it never advances — same sentence again, whole thing.
    if transcript_word_count < sentence_word_count * 0.6:
        words, warning, model_used = await _score_words(analysis, attempted_sentence, config, accent_preference, sub_dialect_preference)
        _record_attempt(session, "partial_muted", words)
        await kv_store.store.update(NAMESPACE, session_id, session)
        return {
            "session_id": session_id, "message_key": "partial_muted",
            "message": PRONUNCIATION_MESSAGES["partial_muted"], "words": words, "transcript": transcript,
            "accent_profile": model_used, "warning": warning, "model_used": model_used,
        }

    # Only a fully correct read of the whole sentence advances. Any word wrong -> same
    # sentence again in full, no per-word retry — _advance (phoneme rotation, new
    # sentence) only runs on a clean pass.
    words, warning, model_used = await _score_words(analysis, sentence, config, accent_preference, sub_dialect_preference)
    had_error = any(w["status"] != WordStatus.CORRECT.value for w in words)
    message_key = "needs_retry" if had_error else "scored_ok"
    _record_attempt(session, message_key, words)
    if had_error:
        await kv_store.store.update(NAMESPACE, session_id, session)
        return {
            "session_id": session_id, "message_key": "needs_retry",
            "message": PRONUNCIATION_MESSAGES["needs_retry"], "words": words, "transcript": transcript,
            "accent_profile": model_used, "warning": warning, "model_used": model_used,
        }

    _advance(session, False)
    await kv_store.store.update(NAMESPACE, session_id, session)
    return {
        "session_id": session_id, "message_key": "scored_ok",
        "message": PRONUNCIATION_MESSAGES["scored_ok"], "words": words, "transcript": transcript,
        "next_sentence": session["current_sentence"], "next_phoneme": session["current_phoneme"],
        "next_phoneme_tag": build_phoneme_tag(session["current_phoneme"]),
        "accent_profile": model_used, "warning": warning, "model_used": model_used,
    }


async def _retry_word(user_id: str, session_id: str, target_word: str, audio_bytes: bytes):
    session = await _get_session(session_id, user_id)
    last = session.get("last_completed")
    target = target_word.lower().strip()
    if last is None or target not in last["words"]:
        raise InvalidSubmissionError(f"'{target_word}' is not part of the last completed attempt")

    config = load_speech_config()
    # initial_prompt biases STT toward the single word being retried — isolated
    # single-word clips have the least context of any audio this pipeline handles, so
    # this is where prompt-biasing helps recognition accuracy the most.
    analysis = _analyze_upload(audio_bytes, config, initial_prompt=target)

    # ACC-US-01: same liveness/playback-audio gate as the main attempt path — a
    # replayed clip must not be able to "fix" a word via retry either.
    rejection_response = await _check_liveness(user_id, session_id, analysis, config)
    if rejection_response is not None:
        return rejection_response

    session["last_active_at"] = _now()

    # E-03: empty/too-short audio is rejected outright — real recording duration/VAD,
    # not a client-supplied guess, and it never touches the frustration counter below.
    if analysis.duration_seconds < config.min_recording_seconds or not analysis.vad.has_speech:
        await kv_store.store.update(NAMESPACE, session_id, session)
        return {
            "session_id": session_id, "message": RETRY_MESSAGES["empty_audio"],
            "frustration_breakdown": False, "transcript": analysis.transcript or "",
        }

    accent_preference, sub_dialect_preference, _ = await accent_calibration_service.get_user_accent_preference(user_id)
    aligned = recording_engine.align_to_sentence(analysis, target)
    timing = None
    if aligned and aligned[0].transcript_index is not None:
        timing = analysis.words[aligned[0].transcript_index]
    status = recording_engine.classify_word_status(target, timing, analysis.prosody, config)
    word_result = WordResultSchema(
        word=target, target_index=0, status=status.value,
        confidence=round(timing.probability, 3) if timing is not None else None,
    )
    calibrated, _warning, _model_used = accent_calibration_service.calibrate_word_results(
        [word_result], accent_preference, sub_dialect_preference=sub_dialect_preference,
    )
    new_status = calibrated[0].status
    new_correct = new_status == WordStatus.CORRECT.value

    was_status = last["words"][target]
    last["words"][target] = new_status

    fail_counts = session.setdefault("retry_fail_counts", {})
    if new_correct:
        fail_counts[target] = 0
    else:
        fail_counts[target] = fail_counts.get(target, 0) + 1

    frustration = fail_counts[target] >= RETRY_FRUSTRATION_THRESHOLD
    if frustration:
        message = RETRY_MESSAGES["frustration_breakdown"]
    else:
        fixed_word = target if (new_correct and was_status != WordStatus.CORRECT.value) else None
        broken_word = target if not new_correct else None
        message = build_retry_diff_message(fixed_word, broken_word)

    await kv_store.store.update(NAMESPACE, session_id, session)
    return {
        "session_id": session_id, "message": message, "frustration_breakdown": frustration,
        "transcript": analysis.transcript or "",
    }


async def _interrupt_session(user_id: str, session_id: str) -> dict:
    session = await _get_session(session_id, user_id)
    if session["status"] == "completed":
        raise SessionAlreadyEndedError("Cannot interrupt a completed session")
    session["status"] = "interrupted"
    session["last_active_at"] = _now()
    await kv_store.store.update(NAMESPACE, session_id, session)
    return {"session_id": session_id, "status": session["status"], "message": INTERRUPTION_MESSAGES["discard_in_flight"]}


async def _find_resumable_session(user_id: str) -> dict:
    # Engagement gate: a session with zero submitted attempts is one the learner
    # never actually practiced in (auto-started on page load, then abandoned) —
    # nothing real to resume, so it shouldn't keep re-surfacing the resume prompt
    # on every later visit.
    sessions = [
        s for s in await kv_store.store.list_values(NAMESPACE)
        if s["user_id"] == user_id and s["status"] != "completed" and s.get("attempts") and not s.get("superseded")
    ]
    if not sessions:
        return {"found": False, "message": INTERRUPTION_MESSAGES["not_found"]}
    latest = max(sessions, key=lambda s: s["last_active_at"])
    stale = _now() - latest["last_active_at"] > timedelta(hours=EXTENDED_ABSENCE_HOURS)
    message = INTERRUPTION_MESSAGES["stale_resume_prompt"] if stale else INTERRUPTION_MESSAGES["resume_prompt"]
    return {"found": True, "session_id": latest["session_id"], "message": message, "stale": stale}


async def _resume_session(user_id: str, session_id: str, device_id: str) -> dict:
    session = await _get_session(session_id, user_id)
    if session["status"] == "completed":
        raise SessionAlreadyEndedError("Cannot resume a completed session")
    if session.get("superseded") and session.get("superseded_by_device_id") != device_id:
        raise InvalidSubmissionError(INTERRUPTION_MESSAGES["conflict_second_device"])

    stale = _now() - session["last_active_at"] > timedelta(hours=EXTENDED_ABSENCE_HOURS)
    session["status"] = "active"
    session["active_device_id"] = device_id
    session["last_active_at"] = _now()
    await kv_store.store.update(NAMESPACE, session_id, session)
    message = INTERRUPTION_MESSAGES["stale_resume_prompt"] if stale else INTERRUPTION_MESSAGES["resume_prompt"]
    return {
        "session_id": session_id, "status": session["status"],
        "phoneme": session["current_phoneme"], "phoneme_tag": build_phoneme_tag(session["current_phoneme"]),
        "sentence": session["current_sentence"], "message": message,
    }


async def _end_session(user_id: str, session_id: str) -> dict:
    session = await _get_session(session_id, user_id)
    if session["status"] != "completed":
        session["status"] = "completed"
        session["ended_at"] = _now()
        await kv_store.store.update(NAMESPACE, session_id, session)

    by_phoneme: Dict[str, Dict] = {}
    for attempt in session["attempts"]:
        entry = by_phoneme.setdefault(attempt["phoneme"], {"attempts": 0, "correct_words": 0, "total_words": 0})
        entry["attempts"] += 1
        entry["total_words"] += len(attempt["words"])
        entry["correct_words"] += sum(1 for w in attempt["words"] if w["status"] == WordStatus.CORRECT.value)

    return {
        "session_id": session_id, "status": session["status"],
        "attempt_count": len(session["attempts"]),
        "phoneme_accuracy": [
            {"phoneme": phoneme, **stats} for phoneme, stats in by_phoneme.items()
        ],
        "ended_at": session["ended_at"],
    }


async def _get_session_snapshot(user_id: str, session_id: str) -> dict:
    session = await _get_session(session_id, user_id)
    return {
        "session_id": session_id, "status": session["status"],
        "phoneme": session["current_phoneme"], "phoneme_tag": build_phoneme_tag(session["current_phoneme"]),
        "sentence": session["current_sentence"],
    }


# ── controllers (auth-gated) ──────────────────────────────────────────────────
async def _require_access(user_id: str) -> Optional[JSONResponse]:
    """Gate Pronunciation Coach behind a completed baseline assessment, same gate/shape
    as coaching_service._require_access."""
    from services.gating_service import GatedFeature, check_feature_access

    access = await check_feature_access(user_id, GatedFeature.SCENARIO_BASED_LEARNING.value)
    if not access["accessible"]:
        return JSONResponse(status_code=403, content={"error": access["reason"], "gating": access})
    return None


async def start_session(payload: StartSessionRequest, user_id: str = Depends(require_auth)):
    gate = await _require_access(user_id)
    if gate:
        return gate
    session = await _start_session(user_id, payload.device_id)
    # Shape to SessionStartResponse: _start_session returns the internal session dict
    # (current_phoneme/current_sentence, plus fields that aren't the client's business),
    # not the wire response — this mapping is what the frontend's `sentence`/
    # `phoneme`/`phoneme_tag` fields actually come from.
    return {
        "session_id": session["session_id"],
        "status": session["status"],
        "phoneme": session["current_phoneme"],
        "phoneme_tag": build_phoneme_tag(session["current_phoneme"]),
        "sentence": session["current_sentence"],
        "message": None,
        "started_at": session["started_at"],
    }


async def submit_attempt(session_id: str, audio: UploadFile = File(...), user_id: str = Depends(require_auth)):
    audio_bytes = await audio.read()
    return await _submit_attempt(user_id, session_id, audio_bytes)


async def retry_word(
    session_id: str,
    target_word: str = Form(...),
    audio: UploadFile = File(...),
    user_id: str = Depends(require_auth),
):
    audio_bytes = await audio.read()
    return await _retry_word(user_id, session_id, target_word, audio_bytes)


async def interrupt_session(session_id: str, user_id: str = Depends(require_auth)):
    return await _interrupt_session(user_id, session_id)


async def check_resumable_session(user_id: str = Depends(require_auth)):
    return await _find_resumable_session(user_id)


async def resume_session(session_id: str, payload: DeviceScopedRequest, user_id: str = Depends(require_auth)):
    return await _resume_session(user_id, session_id, payload.device_id)


async def end_session(session_id: str, user_id: str = Depends(require_auth)):
    return await _end_session(user_id, session_id)


async def get_session(session_id: str, user_id: str = Depends(require_auth)):
    return await _get_session_snapshot(user_id, session_id)


# ── PRN-US-10 / PRN-US-11: "hear correct pronunciation" playback (standalone,
# no session state needed — kept unchanged from the original one-shot coach) ────
def _tts_cache_key(word: str, speed: str) -> str:
    return f"{word.strip().lower()}::{speed}"


async def _get_cached_audio(word: str, speed: str, ttl_seconds: int) -> Optional[bytes]:
    entry = await kv_store.store.get(_TTS_CACHE_NS, _tts_cache_key(word, speed))
    if entry is None:
        return None
    cached_at: datetime = entry["cached_at"]
    age = (datetime.now(timezone.utc) - cached_at).total_seconds()
    if age > ttl_seconds:
        return None
    return base64.b64decode(entry["audio_b64"])


async def _store_cached_audio(word: str, speed: str, audio: bytes) -> None:
    key = _tts_cache_key(word, speed)
    value = {"audio_b64": base64.b64encode(audio).decode("ascii"), "cached_at": datetime.now(timezone.utc)}
    if await kv_store.store.get(_TTS_CACHE_NS, key) is None:
        await kv_store.store.create(_TTS_CACHE_NS, key, value)
    else:
        await kv_store.store.update(_TTS_CACHE_NS, key, value)


async def get_word_pronunciation_audio(word: str, speed: str = "normal", user_id: str = Depends(require_auth)):
    """Correct-pronunciation playback for a single word/short phrase — fires when the
    user taps a mispronounced word (PRN-US-10, speed=normal) or when the retry loop
    hits PRN-US-11's E-01 exception and offers a slow breakdown instead (speed=slow).
    `word` is reused as-is from a word result the client already has; no server-side
    retry-streak tracking is added here, that stays a frontend concern."""
    if speed not in _VALID_SPEEDS:
        raise InvalidSubmissionError(f"speed must be one of {_VALID_SPEEDS}")

    config = load_speech_config()
    cached = await _get_cached_audio(word, speed, config.pronunciation_tts_cache_ttl_seconds)
    if cached is not None:
        return Response(content=cached, media_type="audio/wav")

    if not tts_client.is_configured():
        return JSONResponse(status_code=503, content={
            "error": "TTS engine unavailable. Fall back to your device's native text-to-speech.",
        })

    length_scale = 1.0 if speed == "normal" else config.pronunciation_tts_slow_length_scale
    try:
        audio = tts_client.synthesize(word, length_scale=length_scale)
    except tts_client.TTSError as e:
        return JSONResponse(status_code=503, content={"error": str(e)})

    await _store_cached_audio(word, speed, audio)
    return Response(content=audio, media_type="audio/wav")
