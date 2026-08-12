"""
Text-to-Speech via Piper — a local neural TTS engine (ONNX model, no cloud
call, no API key). Piper is the "natural-sounding neural voice model" the story requires;
a legacy OS/robotic voice is explicitly out per the acceptance criteria.

Model files ship in data/tts/ (voice .onnx + .onnx.json — see data/tts/README). Guarded
import mirrors resume_jd_service's pypdf/python-docx pattern: missing package or model
=> is_configured() False => callers degrade (client falls back to its own native TTS,
per the story's E-02 resolution — that fallback is a client concern, not this backend's).
"""

import io
import os
import threading
import wave
from pathlib import Path

try:
    from piper import PiperVoice
except ImportError:
    PiperVoice = None

_MODEL_DIR = Path(__file__).parent.parent / "data" / "tts"
_DEFAULT_MODEL = os.environ.get("TTS_VOICE_MODEL", "en_US-lessac-medium.onnx")

_voice = None
_load_attempted = False
_voice_lock = threading.Lock()


class TTSError(Exception):
    """Synthesis unavailable or failed."""


class TTSNotConfigured(TTSError):
    """Piper package or voice model file not available."""


def _model_path() -> Path:
    return _MODEL_DIR / _DEFAULT_MODEL


def is_configured() -> bool:
    return PiperVoice is not None and _model_path().exists()


def _get_voice():
    """live_call/worker.py's STT/TTS warm-up (fired in a background thread right after
    room connect) can now call this concurrently with a real in-flight synthesize() —
    without the lock, two threads racing the old check-then-act (_voice is None,
    _load_attempted is False) could see _load_attempted flip True on one thread while
    _voice is still None on the other, making that second caller's synthesize() return
    None -> raise TTSNotConfigured -> that turn's reply arrives as text with no audio."""
    global _voice, _load_attempted
    if _voice is not None:
        return _voice
    with _voice_lock:
        if _voice is not None:
            return _voice
        if _load_attempted:
            return None
        _load_attempted = True
        if not is_configured():
            return None
        _voice = PiperVoice.load(str(_model_path()))
        return _voice


def synthesize(text: str, length_scale: float = 1.0) -> bytes:
    """Synthesize `text` to a WAV file (bytes). Raises TTSNotConfigured / TTSError.

    length_scale: 1.0 normal speed, >1.0 slower — passed straight to Piper's
    synthesis config (time-stretch, no pitch shift).
    """
    voice = _get_voice()
    if voice is None:
        raise TTSNotConfigured("Piper TTS is not installed or the voice model is missing")

    text = (text or "").strip()
    if not text:
        raise TTSError("Nothing to synthesize")

    buf = io.BytesIO()
    try:
        with wave.open(buf, "wb") as wav_file:
            synth_config = None
            try:
                from piper import SynthesisConfig

                synth_config = SynthesisConfig(length_scale=length_scale)
            except ImportError:
                pass
            if synth_config is not None:
                voice.synthesize_wav(text, wav_file, syn_config=synth_config)
            else:
                voice.synthesize_wav(text, wav_file)
    except Exception as e:
        raise TTSError(f"Piper synthesis failed: {e}") from e

    return buf.getvalue()
