"""
Shared Assessment/Recording Engine — the foundation story both Pronunciation Coach
(services/pronunciation_coach_service.py, US-95) and Accent Assessment
(services/accent_assessment_service.py, US-93/US-89) call into, so neither duplicates
audio decoding, VAD, STT, or alignment logic.

Pure analysis only — no DB access, no HTTP concerns — so it's unit-testable in
isolation (see tests/test_recording_engine.py) and reusable by any future feature that
needs "record against a target text and get back what was said."
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Tuple

from lib import audio_io, prosody_engine, stt_engine, text_alignment, vad_engine
from lib.speech_config import SpeechConfig

logger = logging.getLogger(__name__)


class RejectionReason(str, Enum):
    """Canonical reason-code vocabulary returned to the client instead of a false score."""

    NO_SPEECH_DETECTED = "no_speech_detected"
    AUDIO_TOO_QUIET = "audio_too_quiet"
    BACKGROUND_NOISE_TOO_HIGH = "background_noise_too_high"
    INCOMPLETE_RECORDING = "incomplete_recording"
    MULTIPLE_VOICES_DETECTED = "multiple_voices_detected"
    PLAYBACK_DETECTED = "playback_detected"
    AUDIO_DISTORTION = "audio_distortion"




@dataclass
class RecordingAnalysis:
    transcript: str
    duration_seconds: float
    words: List[stt_engine.WordTiming]
    vad: vad_engine.VadResult
    avg_dbfs: float
    noise_floor_dbfs: float
    snr_db: float
    prosody: prosody_engine.ProsodyData
    multiple_voices_detected: bool
    rejection: Optional[RejectionReason] = None
    high_freq_energy_ratio: float = 1.0  # 1.0 default = "not suspicious" for callers/tests that don't set it


def _high_freq_energy_ratio(waveform, sample_rate: int) -> float:
    """Fraction of total spectral energy sitting in the top 10% of the Nyquist band.

    Best-effort proxy for compression artifacts (ACC-US-01's playback-detection AC
    explicitly names these): lossy speech codecs and multi-generation playback/
    re-recording commonly apply a low-pass cutoff well below Nyquist, silently gutting
    this band, while genuine live mic capture keeps a small but nonzero tail up there
    from sibilance and room/mic noise even in a quiet room. Not real spectral/codec
    analysis (no format sniffing, no MDCT-block artifact detection) -- a cheap signal
    alongside the existing noise-floor/SNR/pitch-flatness checks, not a replacement.
    """
    import numpy as np

    if len(waveform) < 1024:
        return 1.0
    spectrum = np.abs(np.fft.rfft(waveform))
    freqs = np.fft.rfftfreq(len(waveform), d=1.0 / sample_rate)
    total_energy = float(np.sum(spectrum ** 2))
    if total_energy <= 0:
        return 1.0
    cutoff_hz = 0.9 * (sample_rate / 2.0)
    high_energy = float(np.sum(spectrum[freqs >= cutoff_hz] ** 2))
    return high_energy / total_energy


def analyze_recording(audio_bytes: bytes, config: SpeechConfig, initial_prompt: Optional[str] = None) -> RecordingAnalysis:
    """Decode + run VAD/STT/prosody over a raw audio upload.

    Always returns a result, even a rejected one, so callers can tell the user *why*
    rather than raising for the ordinary "submitted silence" case. STT only runs when
    the audio clears the speech/quiet/noise checks — transcribing known-bad audio would
    just waste time and risk hallucinated text on silence.

    initial_prompt is passed straight through to stt_engine.transcribe — see that
    function's docstring for why (short/single-word clips benefit the most).

    Raises audio_io.AudioDecodeError only for a genuinely unreadable upload (corrupt
    file, empty body, unsupported container) — callers map that to a 400.
    """
    decoded = audio_io.decode_audio_bytes(audio_bytes, config.audio_sample_rate)
    waveform, sample_rate = decoded.waveform, decoded.sample_rate

    vad_result = vad_engine.detect_speech_segments(waveform, sample_rate, config)
    avg_dbfs = audio_io.rms_dbfs(waveform)
    noise_floor_dbfs, snr_db = vad_engine.estimate_noise_and_snr(waveform, sample_rate, vad_result)

    prosody = prosody_engine.analyze(waveform, sample_rate)
    multiple_voices = prosody_engine.detect_multiple_voices(prosody, config)

    import numpy as np
    clipping_ratio = float(np.sum(np.abs(waveform) > 0.98)) / max(1, len(waveform))

    rejection: Optional[RejectionReason] = None
    if clipping_ratio > 0.02:
        rejection = RejectionReason.AUDIO_DISTORTION
    elif not vad_result.has_speech:
        rejection = RejectionReason.NO_SPEECH_DETECTED
    elif avg_dbfs < config.min_avg_dbfs:
        rejection = RejectionReason.AUDIO_TOO_QUIET
    elif snr_db < config.min_snr_db:
        rejection = RejectionReason.BACKGROUND_NOISE_TOO_HIGH


    transcript, words = "", []
    if rejection is None:
        transcription = stt_engine.transcribe(waveform, sample_rate, config, initial_prompt=initial_prompt)
        transcript, words = transcription.text, transcription.words

    return RecordingAnalysis(
        transcript=transcript,
        duration_seconds=decoded.duration_seconds,
        words=words,
        vad=vad_result,
        avg_dbfs=avg_dbfs,
        noise_floor_dbfs=noise_floor_dbfs,
        snr_db=snr_db,
        prosody=prosody,
        multiple_voices_detected=multiple_voices,
        rejection=rejection,
        high_freq_energy_ratio=_high_freq_energy_ratio(waveform, sample_rate),
    )


def classify_word_status(
    target_word: str,
    timing: Optional[stt_engine.WordTiming],
    prosody: prosody_engine.ProsodyData,
    config: SpeechConfig,
) -> text_alignment.WordStatus:
    """Shared per-word classification used by both Pronunciation Coach (word-level
    scoring) and Accent Assessment (pronunciation/stress dimensions + weak-point
    detection) — one place decides what "mispronounced" vs. "stress-error" means.

    timing is None for a skipped word (present in target, absent in transcript, per
    lib/text_alignment.align_words). For a matched-but-different word (a difflib
    "replace" pairing — the target word's alignment slot got a transcript word whose
    text doesn't match), that's mispronounced by definition regardless of how confident
    the STT engine was in whatever it actually heard: high ASR confidence just means the
    engine is sure the speaker said a different word, not that the target word was said
    well. Confirmed against real recorded audio during review — the target word "nice"
    aligned to a transcribed "beautiful" was scoring CORRECT before this check existed,
    because confidence alone can never catch a substituted word.
    """
    if timing is None:
        return text_alignment.WordStatus.SKIPPED
    if not text_alignment.is_near_match(target_word, timing.word, config.word_near_match_ratio):
        return text_alignment.WordStatus.MISPRONOUNCED
    if timing.probability < config.word_confidence_threshold:
        return text_alignment.WordStatus.MISPRONOUNCED

    expected_stress = text_alignment.expected_stress_position(target_word)
    if expected_stress is not None:
        peak_pos = prosody_engine.word_stress_peak_position(prosody, timing.start, timing.end)
        if peak_pos is not None and abs(peak_pos - expected_stress) > config.stress_error_sensitivity:
            return text_alignment.WordStatus.STRESS_ERROR

    return text_alignment.WordStatus.CORRECT


def align_to_sentence(analysis: RecordingAnalysis, target_text: str) -> List[text_alignment.AlignedWord]:
    """WORD-level alignment — what Pronunciation Coach (US-95) needs."""
    transcript_words = [w.word for w in analysis.words]
    return text_alignment.align_words(target_text, transcript_words)


def align_to_passage(
    analysis: RecordingAnalysis, target_text: str, config: SpeechConfig
) -> Tuple[List[text_alignment.AlignedWord], text_alignment.PassageCoverage]:
    """PASSAGE-level alignment — what Accent Assessment (US-93) needs: the same
    word alignment, plus a coverage summary (including the trailing-window check that
    catches a reading that stops partway through)."""
    aligned = align_to_sentence(analysis, target_text)
    coverage = text_alignment.compute_passage_coverage(aligned, config.passage_trailing_coverage_window)
    return aligned, coverage


def detect_disfluency(analysis: RecordingAnalysis, config: SpeechConfig) -> bool:
    """Heuristic stutter/repetition flag: the same word spoken more than once within a
    short window. Informational only — word alignment already collapses repeats to a
    single matched occurrence (extra repeats are alignment "insertions", dropped rather
    than penalized), satisfying US-95's "score the final clean articulation, don't
    penalize the repetition itself" without any extra scoring logic.
    """
    words = analysis.words
    for i in range(1, len(words)):
        prev, curr = words[i - 1], words[i]
        if prev.word.lower() == curr.word.lower() and (curr.start - prev.end) <= config.disfluency_repetition_window_seconds:
            return True
    return False


# A synthetic/played-back clip is rejected only on strong evidence. Each individual
# signal below is environment-dependent — OS noise suppression, a close-talking headset,
# a tightly-trimmed clip or a slightly dull mic all push one of them into "suspicious"
# range for entirely genuine live speech (that is what made this reject real users on
# some machines and not others). So a single hint never rejects: either the pitch track
# is physically impossible for a human voice, or at least two independent hints agree.
_MIN_CORROBORATING_SIGNALS = 2

# Below this, a pitch track is flat to a degree a human larynx does not produce; that is
# a TTS/looped-tone fingerprint rather than an environmental artefact.
_SYNTHETIC_PITCH_STD_HZ = 0.5
_MIN_VOICED_FRAMES_FOR_PITCH_CHECK = 10


def _is_measured(value: float, sentinel: float) -> bool:
    """Sentinels mean 'nothing to measure against', not 'pristine studio capture'."""
    return value != sentinel


def _playback_signals(analysis: RecordingAnalysis, config: SpeechConfig) -> List[str]:
    """Weak, corroborating hints that a clip may not be live mic capture."""
    signals: List[str] = []

    if (
        _is_measured(analysis.noise_floor_dbfs, vad_engine.UNMEASURED_NOISE_FLOOR_DBFS)
        and analysis.noise_floor_dbfs < config.liveness_min_noise_floor_dbfs
    ):
        signals.append("unnaturally_flat_noise_floor")

    if (
        _is_measured(analysis.snr_db, vad_engine.UNMEASURED_SNR_DB)
        and analysis.duration_seconds > 2.0
        and analysis.snr_db > config.liveness_max_snr_db
    ):
        signals.append("implausible_snr")

    if (
        analysis.duration_seconds > 1.0
        and analysis.high_freq_energy_ratio < config.liveness_min_high_freq_energy_ratio
    ):
        signals.append("missing_high_frequency_energy")

    return signals


def _has_synthetic_pitch_track(analysis: RecordingAnalysis) -> bool:
    """Near-zero pitch variance across many voiced frames — decisive on its own."""
    if not analysis.prosody or len(analysis.prosody.pitch_hz) <= _MIN_VOICED_FRAMES_FOR_PITCH_CHECK:
        return False

    import numpy as np

    voiced = [f for f in analysis.prosody.pitch_hz if f > 0]
    if len(voiced) <= _MIN_VOICED_FRAMES_FOR_PITCH_CHECK:
        return False
    return bool(np.std(voiced) < _SYNTHETIC_PITCH_STD_HZ)


def detect_playback_audio(analysis: RecordingAnalysis, config: SpeechConfig) -> Optional[RejectionReason]:
    """ACC-US-01: reject pre-recorded or synthetic audio, without rejecting real speakers.

    Decisive on a physically implausible (flat) pitch track; otherwise requires at least
    _MIN_CORROBORATING_SIGNALS independent hints, and ignores any measurement the VAD
    could not actually take.
    """
    if _has_synthetic_pitch_track(analysis):
        return RejectionReason.PLAYBACK_DETECTED

    signals = _playback_signals(analysis, config)
    if len(signals) >= _MIN_CORROBORATING_SIGNALS:
        logger.info("Playback rejection on corroborating signals: %s", signals)
        return RejectionReason.PLAYBACK_DETECTED
    if signals:
        logger.debug("Liveness hint(s) seen but not corroborated, accepting: %s", signals)
    return None

