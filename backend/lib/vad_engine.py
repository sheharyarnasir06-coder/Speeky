"""
Silero VAD wrapper — same model already trusted in backend/lib/voice_ws.py (there via
the raw `silero_vad.VADIterator` for realtime WebSocket streams; here via the batch
`get_speech_timestamps` since this module scores one-shot uploads, not a live stream).

Used for: no-speech detection, incomplete-recording detection (last speech segment vs.
total duration), and noise-floor/SNR estimation (speech-segment level vs. everything
else in the clip).
"""

from dataclasses import dataclass
from typing import List, Tuple

import numpy as np
from torch import from_numpy
from silero_vad import get_speech_timestamps, load_silero_vad

from lib.audio_io import rms_dbfs, slice_seconds
from lib.speech_config import SpeechConfig

_model = None

# Sentinels returned by estimate_noise_and_snr when the clip offers nothing to measure
# against (no speech at all, or no non-speech region). They are "unknown", not "perfect" —
# treating them as real measurements is what made continuous speech look synthetic.
UNMEASURED_NOISE_FLOOR_DBFS = -120.0
UNMEASURED_SNR_DB = 99.0


def _get_model():
    global _model
    if _model is None:
        _model = load_silero_vad()
    return _model


@dataclass
class SpeechSegment:
    start_s: float
    end_s: float


@dataclass
class VadResult:
    segments: List[SpeechSegment]
    total_duration_s: float

    @property
    def has_speech(self) -> bool:
        return len(self.segments) > 0

    @property
    def speech_seconds(self) -> float:
        return sum(s.end_s - s.start_s for s in self.segments)

    @property
    def last_speech_end_s(self) -> float:
        return self.segments[-1].end_s if self.segments else 0.0


def detect_speech_segments(waveform: np.ndarray, sample_rate: int, config: SpeechConfig) -> VadResult:
    """Run Silero VAD over the full waveform and return speech segment boundaries."""
    if sample_rate not in (8000, 16000):
        raise ValueError(f"Silero VAD requires 8000 or 16000 Hz audio, got {sample_rate}")

    model = _get_model()
    tensor = from_numpy(np.ascontiguousarray(waveform, dtype=np.float32))
    timestamps = get_speech_timestamps(
        tensor,
        model,
        sampling_rate=sample_rate,
        threshold=config.vad_speech_threshold,
    )
    segments = [
        SpeechSegment(start_s=t["start"] / sample_rate, end_s=t["end"] / sample_rate)
        for t in timestamps
    ]
    return VadResult(segments=segments, total_duration_s=len(waveform) / sample_rate)


def estimate_noise_and_snr(waveform: np.ndarray, sample_rate: int, vad_result: VadResult) -> Tuple[float, float]:
    """Return (noise_floor_dbfs, snr_db) from speech-segment level vs. everything else.

    When the clip has no measurable non-speech region (speech covers the whole duration,
    e.g. the speaker started immediately and never paused) the sentinels
    UNMEASURED_NOISE_FLOOR_DBFS / UNMEASURED_SNR_DB are returned. They mean "could not be
    measured", NOT "pristine studio audio" — callers that judge audio authenticity must
    skip these values rather than read them as evidence (see
    recording_engine.detect_playback_audio).
    """
    speech_chunks = [slice_seconds(waveform, sample_rate, s.start_s, s.end_s) for s in vad_result.segments]
    speech = np.concatenate(speech_chunks) if speech_chunks else np.empty(0, dtype=waveform.dtype)
    speech_level = rms_dbfs(speech) if speech.size else -120.0

    mask = np.ones(len(waveform), dtype=bool)
    for seg in vad_result.segments:
        start = max(0, int(seg.start_s * sample_rate))
        end = min(len(waveform), int(seg.end_s * sample_rate))
        mask[start:end] = False
    noise = waveform[mask]

    if not speech.size:
        return UNMEASURED_NOISE_FLOOR_DBFS, 0.0
    if not noise.size:
        return UNMEASURED_NOISE_FLOOR_DBFS, UNMEASURED_SNR_DB

    noise_level = rms_dbfs(noise)
    return noise_level, speech_level - noise_level
