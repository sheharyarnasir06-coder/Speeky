"""Wraps lib/stt_engine.py's faster-whisper (batch, not streaming — same model instance
push-to-talk's voice_ws.py already uses) as a LiveKit STT plugin. LiveKit's
stt.StreamAdapter supplies the streaming/turn-segmentation shape on top via Silero VAD,
so this class only needs to answer "what did this one utterance say" — no new
transcription model, no behavior drift from the push-to-talk transcripts.
"""

import asyncio

import numpy as np
from livekit import rtc
from livekit.agents import stt, utils
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS, NOT_GIVEN, APIConnectOptions, NotGivenOr

from lib import stt_engine
from lib.speech_config import load_speech_config

_WHISPER_SAMPLE_RATE = 16000


class WhisperSTT(stt.STT):
    def __init__(self) -> None:
        super().__init__(capabilities=stt.STTCapabilities(streaming=False, interim_results=False))
        self._config = load_speech_config()

    async def _recognize_impl(
        self,
        buffer: utils.audio.AudioBuffer,
        *,
        language: NotGivenOr[str] = NOT_GIVEN,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> stt.SpeechEvent:
        combined = rtc.combine_audio_frames(buffer)
        waveform = _to_16k_float32(combined)
        result = await asyncio.to_thread(stt_engine.transcribe, waveform, _WHISPER_SAMPLE_RATE, self._config)
        return stt.SpeechEvent(
            type=stt.SpeechEventType.FINAL_TRANSCRIPT,
            alternatives=[stt.SpeechData(text=result.text, language="en")],
        )


def _to_16k_float32(frame: rtc.AudioFrame) -> np.ndarray:
    """LiveKit delivers mic audio at whatever rate the room negotiated (commonly 48kHz)
    — faster-whisper's array input path hard-requires 16kHz (lib/stt_engine.py), so this
    always resamples down rather than assuming the room already matches."""
    if frame.sample_rate != _WHISPER_SAMPLE_RATE:
        resampler = rtc.AudioResampler(frame.sample_rate, _WHISPER_SAMPLE_RATE, num_channels=frame.num_channels)
        resampled = resampler.push(frame) + resampler.flush()
        data = b"".join(bytes(f.data) for f in resampled)
    else:
        data = bytes(frame.data)

    samples = np.frombuffer(data, dtype=np.int16)
    if frame.num_channels > 1:
        samples = samples.reshape(-1, frame.num_channels).mean(axis=1).astype(np.int16)
    return samples.astype(np.float32) / 32768.0
