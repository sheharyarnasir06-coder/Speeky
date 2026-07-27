"""
Single source of truth for every env-driven value used by the Pronunciation Coach
(US-95) and Accent Assessment (US-93 / US-89) module — model choice/device, audio
limits, and every scoring threshold. Nothing in lib/recording_engine.py,
lib/vad_engine.py, lib/stt_engine.py, lib/prosody_engine.py, lib/text_alignment.py,
or the pronunciation/accent services should hardcode a number; they all call
load_speech_config() and read a field from here instead.

Read lazily (not cached at import time) so tests can monkeypatch os.environ per-test,
same reasoning as lib/llm_client.py's _model()/_base_url() helpers.
"""

import os
from dataclasses import dataclass


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    return float(raw) if raw not in (None, "") else default


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return int(raw) if raw not in (None, "") else default


def _str_env(name: str, default: str) -> str:
    raw = os.environ.get(name)
    return raw if raw not in (None, "") else default


@dataclass(frozen=True)
class SpeechConfig:
    # ── STT (faster-whisper) ────────────────────────────────────────────────
    stt_model_size: str
    stt_device: str
    stt_compute_type: str

    # ── Audio limits ─────────────────────────────────────────────────────────
    audio_sample_rate: int
    min_recording_seconds: float
    max_recording_seconds: float
    pronunciation_max_upload_mb: float
    accent_max_upload_mb: float
    daily_challenge_max_upload_mb: float

    # ── VAD (silero-vad) ─────────────────────────────────────────────────────
    vad_speech_threshold: float

    # ── Silence / noise rejection ────────────────────────────────────────────
    min_avg_dbfs: float
    min_snr_db: float

    # ── Pronunciation Coach (US-95) ───────────────────────────────────────────
    word_confidence_threshold: float
    stress_error_sensitivity: float
    disfluency_repetition_window_seconds: float
    pronunciation_retry_limit: int  # 0 = unlimited

    # ── Accent Assessment (US-93) ─────────────────────────────────────────────
    passage_min_coverage: float
    passage_trailing_coverage_window: float
    multisyllabic_min_syllables: int
    clarity_skipped_multisyllabic_penalty_weight: float
    rhythm_max_acceptable_cv: float  # coefficient-of-variation ceiling -> rhythm_score floor
    intonation_ideal_range_min_semitones: float
    intonation_ideal_range_max_semitones: float

    # ── Multi-voice / interference heuristic ─────────────────────────────────
    multi_voice_pitch_jump_semitones: float
    multi_voice_min_voiced_segments: int
    multi_voice_min_run_seconds: float

    # ── Local Accent Calibration stub hook (US-90 not built yet) ─────────────
    default_accent_profile: str

    # ── Accent Profile & Improvement (US-89) ──────────────────────────────────
    exercise_batch_size: int

    # ── Pronunciation Coach TTS playback (PRN-US-10 / PRN-US-11) ──────────────
    pronunciation_tts_slow_length_scale: float
    pronunciation_tts_cache_ttl_seconds: int

    # ── Live Speech Verification (ACC-US-01) & Local Accent Calibration (ACC-US-11)
    liveness_min_noise_floor_dbfs: float
    liveness_token_ttl_seconds: int
    local_accent_model_available: bool
    liveness_min_high_freq_energy_ratio: float



def load_speech_config() -> SpeechConfig:
    return SpeechConfig(
        stt_model_size=_str_env("STT_MODEL_SIZE", "base"),
        stt_device=_str_env("STT_DEVICE", "cpu"),
        stt_compute_type=_str_env("STT_COMPUTE_TYPE", "int8"),
        audio_sample_rate=_int_env("AUDIO_SAMPLE_RATE", 16000),
        min_recording_seconds=_float_env("MIN_RECORDING_SECONDS", 0.5),
        max_recording_seconds=_float_env("MAX_RECORDING_SECONDS", 120.0),
        pronunciation_max_upload_mb=_float_env("PRONUNCIATION_MAX_UPLOAD_MB", 15.0),
        accent_max_upload_mb=_float_env("ACCENT_MAX_UPLOAD_MB", 25.0),
        daily_challenge_max_upload_mb=_float_env("DAILY_CHALLENGE_MAX_UPLOAD_MB", 15.0),
        vad_speech_threshold=_float_env("VAD_SPEECH_THRESHOLD", 0.5),
        min_avg_dbfs=_float_env("MIN_AVG_DBFS", -40.0),
        min_snr_db=_float_env("MIN_SNR_DB", 6.0),
        # 0.05, not the originally-committed 0.55: real browser mic audio (compressed
        # webm/opus, resampled) on the "base" model regularly scored correct words well
        # below 0.55 (confirmed live on "cat" verbatim). Progressively lowered through
        # 0.35 and 0.2 before landing here. At 0.05 this gate only catches
        # near-zero-confidence transcription (effectively noise/garbage), not genuine
        # mispronunciation — recalibrate upward against real samples if that's too loose.
        word_confidence_threshold=_float_env("WORD_CONFIDENCE_THRESHOLD", 0.05),
        stress_error_sensitivity=_float_env("STRESS_ERROR_SENSITIVITY", 0.4),
        disfluency_repetition_window_seconds=_float_env("DISFLUENCY_REPETITION_WINDOW_SECONDS", 2.0),
        pronunciation_retry_limit=_int_env("PRONUNCIATION_RETRY_LIMIT", 0),
        passage_min_coverage=_float_env("PASSAGE_MIN_COVERAGE", 0.85),
        passage_trailing_coverage_window=_float_env("PASSAGE_TRAILING_COVERAGE_WINDOW", 0.15),
        multisyllabic_min_syllables=_int_env("MULTISYLLABIC_MIN_SYLLABLES", 2),
        clarity_skipped_multisyllabic_penalty_weight=_float_env("CLARITY_SKIPPED_MULTISYLLABIC_PENALTY_WEIGHT", 1.5),
        rhythm_max_acceptable_cv=_float_env("RHYTHM_MAX_ACCEPTABLE_CV", 2.0),
        intonation_ideal_range_min_semitones=_float_env("INTONATION_IDEAL_RANGE_MIN_SEMITONES", 3.0),
        intonation_ideal_range_max_semitones=_float_env("INTONATION_IDEAL_RANGE_MAX_SEMITONES", 12.0),
        # 20.0 (not the original 7.0): measured against real clean single-voice readings,
        # a single speaker's own natural pitch resets at sentence/phrase boundaries hit
        # 12-16 semitones on longer passages -- 7.0 flagged effectively all of them as
        # "multiple voices". No threshold can perfectly separate that from a genuine second
        # voice (a mismatched-pitch overlay measured as low as ~11 semitones in testing), so
        # this trades missing some multi-voice interference for not blocking every legitimate
        # single-voice submission -- the single-voice false positive is the more costly failure.
        multi_voice_pitch_jump_semitones=_float_env("MULTI_VOICE_PITCH_JUMP_SEMITONES", 20.0),
        multi_voice_min_voiced_segments=_int_env("MULTI_VOICE_MIN_VOICED_SEGMENTS", 4),
        multi_voice_min_run_seconds=_float_env("MULTI_VOICE_MIN_RUN_SECONDS", 0.06),
        default_accent_profile=_str_env("DEFAULT_ACCENT_PROFILE", "neutral"),
        exercise_batch_size=_int_env("EXERCISE_BATCH_SIZE", 6),
        pronunciation_tts_slow_length_scale=_float_env("PRONUNCIATION_TTS_SLOW_LENGTH_SCALE", 1.6),
        pronunciation_tts_cache_ttl_seconds=_int_env("PRONUNCIATION_TTS_CACHE_TTL_SECONDS", 604800),
        liveness_min_noise_floor_dbfs=_float_env("LIVENESS_MIN_NOISE_FLOOR_DBFS", -75.0),
        liveness_token_ttl_seconds=_int_env("LIVENESS_TOKEN_TTL_SECONDS", 900),
        local_accent_model_available=_str_env("LOCAL_ACCENT_MODEL_AVAILABLE", "true").lower() in ("true", "1", "yes"),
        # Fraction of total spectral energy expected in the top 10% of the Nyquist band
        # (7200Hz-8000Hz at the default 16kHz sample rate). Lossy speech codecs and
        # multi-generation playback/re-recording commonly low-pass well below Nyquist;
        # genuine live mic capture keeps a small but nonzero tail up there from sibilance
        # and room/mic noise even in a quiet room. Best-effort proxy, not real codec
        # artifact detection -- see recording_engine._high_freq_energy_ratio.
        liveness_min_high_freq_energy_ratio=_float_env("LIVENESS_MIN_HIGH_FREQ_ENERGY_RATIO", 0.0005),
    )

