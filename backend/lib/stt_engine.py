"""
faster-whisper wrapper — same model this thread-local get_model() shares with
backend/lib/voice_ws.py's realtime WebSocket pipeline; here it runs in-process against
a one-shot upload instead of a streamed utterance.

Gives word-level timestamps *and* per-word confidence (`probability`), which
lib/text_alignment.py and services/pronunciation_coach_service.py use to tell a
mispronounced word apart from a skipped one.
"""

import threading
from dataclasses import dataclass
from typing import List, Optional

import numpy as np
from faster_whisper import WhisperModel

from lib.speech_config import SpeechConfig

# One WhisperModel instance per thread, not a shared global — faster-whisper/ctranslate2
# model instances aren't guaranteed safe for concurrent inference from multiple threads at
# once, and lib/voice_ws.py now calls get_model() from a multi-worker executor pool so
# independent users' utterances can transcribe in parallel instead of queueing behind each
# other. Callers that only ever run on one thread (the upload-analysis path via
# lib/recording_engine.py) see identical behavior: same thread -> same cached instance.
_local = threading.local()


def _get_model(config: SpeechConfig) -> WhisperModel:
    key = (config.stt_model_size, config.stt_device, config.stt_compute_type)
    if getattr(_local, "model", None) is None or _local.model_key != key:
        _local.model = WhisperModel(config.stt_model_size, device=config.stt_device, compute_type=config.stt_compute_type)
        _local.model_key = key
    return _local.model


def get_model(config: SpeechConfig) -> WhisperModel:
    """Public accessor so other callers needing raw model access (lib/voice_ws.py's
    realtime tiers, which need transcribe() options this module's transcribe() doesn't
    expose) share this same thread-local cache instead of loading a second model instance."""
    return _get_model(config)


@dataclass
class WordTiming:
    word: str
    start: float
    end: float
    probability: float


@dataclass
class TranscriptionResult:
    text: str
    words: List[WordTiming]


def transcribe(
    waveform: np.ndarray, sample_rate: int, config: SpeechConfig, initial_prompt: Optional[str] = None
) -> TranscriptionResult:
    """Transcribe a mono float32 waveform. faster-whisper's numpy-array input path
    expects 16kHz PCM — the recording engine always decodes at config.audio_sample_rate,
    so this is a guard against a misconfigured .env, not a normal runtime path.

    initial_prompt biases decoding toward expected vocabulary (the target sentence for
    a Pronunciation Coach attempt, the target word for a retry) — short, single-word
    clips in particular have little context for the model to disambiguate against on
    their own, so this materially improves recognition on exactly that case without
    forcing the output (Whisper still transcribes what it actually hears)."""
    if sample_rate != 16000:
        raise ValueError(f"faster-whisper expects 16000 Hz audio for array input, got {sample_rate}")

    model = _get_model(config)
    segments, _info = model.transcribe(
        waveform.astype(np.float32),
        beam_size=5,
        word_timestamps=True,
        language="en",
        initial_prompt=initial_prompt,
    )

    words: List[WordTiming] = []
    text_parts: List[str] = []
    for segment in segments:
        text_parts.append(segment.text)
        for w in segment.words or []:
            words.append(
                WordTiming(word=w.word.strip(), start=w.start, end=w.end, probability=w.probability)
            )

    return TranscriptionResult(text=" ".join(p.strip() for p in text_parts).strip(), words=words)
