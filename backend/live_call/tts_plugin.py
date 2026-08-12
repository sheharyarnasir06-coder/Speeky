"""Wraps lib/tts_client.py's Piper synthesis (local ONNX, no cloud call — same voice
push-to-talk's /tts endpoint uses) as a LiveKit TTS plugin. Piper returns one complete
WAV blob per call, not a token-by-token stream, so this is a non-streaming ChunkedStream
(same shape most REST-based TTS plugins use)."""

import asyncio

from livekit.agents import tts, utils
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS, APIConnectOptions

from lib import tts_client

# Piper's "medium" voices (both en_GB-alba-medium and en_US-lessac-medium — see
# data/tts/README.md) synthesize at 22050Hz. The WAV blob is self-describing and
# AudioEmitter resamples to whatever this declares regardless, so a mismatch here
# would degrade quality, not break playback.
_SAMPLE_RATE = 22050


class PiperTTS(tts.TTS):
    def __init__(self) -> None:
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=False),
            sample_rate=_SAMPLE_RATE,
            num_channels=1,
        )

    def synthesize(
        self, text: str, *, conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS
    ) -> "PiperChunkedStream":
        return PiperChunkedStream(tts=self, input_text=text, conn_options=conn_options)


class PiperChunkedStream(tts.ChunkedStream):
    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        wav_bytes = await asyncio.to_thread(tts_client.synthesize, self._input_text)
        output_emitter.initialize(
            request_id=utils.shortuuid(),
            sample_rate=_SAMPLE_RATE,
            num_channels=1,
            mime_type="audio/wav",
        )
        output_emitter.push(wav_bytes)
