"""
Raw-audio decoding + low-level waveform math shared by the recording engine.

Decoding goes through PyAV (`av`) — already a transitive dependency of faster-whisper
(lib/stt_engine.py), so accepting an arbitrary upload container (wav/webm/m4a/mp3) needs
no extra library beyond what STT already pulled in. Everything downstream (VAD, STT,
prosody) works off the same mono float32 waveform this module produces, so none of them
re-decode the upload.
"""

import io
from dataclasses import dataclass

import numpy as np

try:
    import av
except ImportError:  # pragma: no cover - exercised only when faster-whisper isn't installed
    av = None


class AudioDecodeError(Exception):
    """Upload isn't readable as audio (corrupt file, unsupported/empty container)."""


@dataclass
class DecodedAudio:
    waveform: np.ndarray  # mono float32, range [-1.0, 1.0]
    sample_rate: int

    @property
    def duration_seconds(self) -> float:
        return len(self.waveform) / self.sample_rate if self.sample_rate else 0.0


def decode_audio_bytes(data: bytes, target_sample_rate: int) -> DecodedAudio:
    """Decode an uploaded audio file into a mono float32 waveform at target_sample_rate.

    Raises AudioDecodeError if the bytes aren't a readable/non-empty audio container.
    """
    if av is None:
        raise AudioDecodeError("Audio decoding is unavailable: the 'av' package is not installed")
    if not data:
        raise AudioDecodeError("Empty upload")

    try:
        container = av.open(io.BytesIO(data))
    except Exception as e:
        raise AudioDecodeError(f"Could not read audio file: {e}") from e

    try:
        stream = next((s for s in container.streams if s.type == "audio"), None)
        if stream is None:
            raise AudioDecodeError("Upload does not contain an audio stream")

        resampler = av.AudioResampler(format="flt", layout="mono", rate=target_sample_rate)
        chunks = []
        for frame in container.decode(stream):
            for resampled in resampler.resample(frame):
                chunks.append(resampled.to_ndarray())
        for resampled in resampler.resample(None):  # flush
            chunks.append(resampled.to_ndarray())
    except AudioDecodeError:
        raise
    except Exception as e:
        raise AudioDecodeError(f"Failed to decode audio stream: {e}") from e
    finally:
        container.close()

    if not chunks:
        raise AudioDecodeError("No audio samples decoded from upload")

    waveform = np.concatenate(chunks, axis=-1).flatten().astype(np.float32)
    if waveform.size == 0:
        raise AudioDecodeError("Decoded audio contains zero samples")

    return DecodedAudio(waveform=waveform, sample_rate=target_sample_rate)


# HVAC/desk rumble sits almost entirely below 40Hz. Deliberately well under any
# adult voice fundamental (lowest ~85Hz) -- because this only needs to
# feed the noise-floor/SNR gate (recording_engine.analyze_recording), never
# prosody_engine's pitch tracking: a cutoff that close to the pitch floor risks
# attenuating F0 itself on lower voices, which is what silently corrupted the
# multi-voice heuristic (pitch-jump-based) into false-positive territory the last time
# this was tried at 80Hz.
_RUMBLE_CUTOFF_HZ = 40.0


def remove_low_frequency_rumble(waveform: np.ndarray, sample_rate: int) -> np.ndarray:
    """Callers that need a denoised copy for a level/SNR measurement should filter their
    own copy via this rather than have decode_audio_bytes filter for everyone -- see
    _RUMBLE_CUTOFF_HZ."""
    import torch
    import torchaudio.functional as taf

    filtered = taf.highpass_biquad(torch.from_numpy(waveform).unsqueeze(0), sample_rate, _RUMBLE_CUTOFF_HZ)
    return filtered.squeeze(0).numpy().astype(np.float32)


def rms_dbfs(waveform: np.ndarray) -> float:
    """Root-mean-square level of a float32 [-1, 1] waveform, in dBFS. Silence -> -inf,
    clamped to -120.0 so callers can compare it against a threshold without special-casing."""
    if waveform.size == 0:
        return -120.0
    rms = float(np.sqrt(np.mean(np.square(waveform, dtype=np.float64))))
    if rms <= 1e-9:
        return -120.0
    return max(-120.0, 20.0 * np.log10(rms))


def slice_seconds(waveform: np.ndarray, sample_rate: int, start_s: float, end_s: float) -> np.ndarray:
    start = max(0, int(start_s * sample_rate))
    end = min(len(waveform), int(end_s * sample_rate))
    if end <= start:
        return np.empty(0, dtype=waveform.dtype)
    return waveform[start:end]
