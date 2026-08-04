"""WebSocket voice transcription — replaces the LiveKit-based voice_agent/ worker.

The browser streams raw 16-bit PCM mono 16kHz mic audio over a plain WebSocket (see
frontend/lib/useVoiceSocket.ts + voicePcmWorklet.ts); this module segments it into
utterances with Silero VAD and transcribes each one with faster-whisper, mirroring what
LiveKit data channel did — same three richness tiers ("transcript"/"timed"/"full"), 
same message shapes, just without the WebRTC transport, the separate deployable process or duplicates.

Message shapes sent via `on_message` (a WebSocket.send_json-shaped callable):
    {"type": "status", "status": "speaking" | "idle"}
    {"type": "transcript", "text": "..."}                                  — transcript mode
    {"type": "transcript", "text": "...", "duration_seconds": .., "word_timings": [...]}  — timed
    {"type": "transcript", "text": "...", "features": {...}}               — full
"""

import asyncio
import logging
import os
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from typing import Awaitable, Callable, List, Optional

import numpy as np
import torch
from fastapi import WebSocket
from silero_vad import VADIterator, load_silero_vad

from lib import audio_io, prosody_engine, stt_engine, vad_engine
from lib.speech_config import load_speech_config

logger = logging.getLogger("voice-ws")

SAMPLE_RATE = 16000    # Silero VAD's window size below is architecturally tied to this rate
WINDOW_SAMPLES = 512   # Silero VAD's required inference chunk size at 16kHz
PRE_ROLL_SAMPLES = 8000  # 0.5s lead-in kept before speech is detected (matches the
# prefix_padding_duration livekit-plugins-silero used by default in agent.py)

# Same reasoning agent.py had for its executor: transcription is synchronous/CPU-bound,
# so it must run off the event loop. Unlike agent.py's max_workers=1 (which serialized
# every utterance from every user behind one one thread), each worker here gets its own
# thread-local WhisperModel via stt_engine.get_model(), so independent users' utterances
# actually run in parallel instead of queueing.
_executor = ThreadPoolExecutor(max_workers=min(4, os.cpu_count() or 2))
_vad_model = None


def _get_vad_model():
    global _vad_model
    if _vad_model is None:
        _vad_model = load_silero_vad()
    return _vad_model


def _transcribe(waveform: np.ndarray, mode: str) -> dict:
    """Runs on the executor's thread. Mirrors agent.py's transcribe_plain/timed/full
    tiers exactly (same beam_size/temperature/word_timestamps choices, same "full"
    feature set), just fed the already-decoded PCM directly instead of round-tripping
    through frame.to_wav_bytes() + a WAV re-decode."""
    config = load_speech_config()
    model = stt_engine.get_model(config)
    # temperature=0: single decode pass — the user reviews/edits the transcript 
    # before sending anyway, so a rougher single-pass result beats a more "accurate" 
    # one that misses the latency budget.
    # word_timestamps only computed for modes that actually read it back — this is the
    # exact optimization being preserved: "transcript" mode (Scenario/Coaching/Interview
    # Coach/Assessment) never pays for word-alignment nobody consumes.
    segments, _info = model.transcribe(
        waveform, beam_size=5, temperature=0, word_timestamps=(mode != "transcript"), language="en",
    )
    text_parts: List[str] = []
    word_timings: List[dict] = []
    for seg in segments:
        stripped = seg.text.strip()
        if stripped:
            text_parts.append(stripped)
        for w in (seg.words or []):
            cleaned = w.word.strip()
            if cleaned:
                word_timings.append({"word": cleaned, "start": round(float(w.start), 3), "end": round(float(w.end), 3)})
    text = " ".join(text_parts).strip()
    duration_seconds = round(len(waveform) / SAMPLE_RATE, 3)

    if mode == "full":
        prosody = prosody_engine.analyze(waveform, SAMPLE_RATE)
        vad_result = vad_engine.detect_speech_segments(waveform, SAMPLE_RATE, config)
        _noise_floor, snr_db = vad_engine.estimate_noise_and_snr(waveform, SAMPLE_RATE, vad_result)
        return {
            "text": text,
            "features": {
                "word_timings": word_timings,
                "duration_seconds": duration_seconds,
                "avg_db": round(audio_io.rms_dbfs(waveform), 2),
                "pitch_range_semitones": round(float(prosody.pitch_range_semitones), 2),
                "snr_db": round(float(snr_db), 1),
            },
        }
    if mode == "timed":
        return {"text": text, "duration_seconds": duration_seconds, "word_timings": word_timings}
    return {"text": text}


def _transcribe_partial(waveform: np.ndarray) -> dict:
    """Cheap partial pass over the buffered-so-far audio for a live preview —
    beam_size=1, no word_timestamps, speed over accuracy. Gets replaced within a second
    or two by the real per-mode _transcribe() once the utterance actually finishes."""
    config = load_speech_config()
    model = stt_engine.get_model(config)
    segments, _info = model.transcribe(waveform, beam_size=1, temperature=0, language="en")
    text = " ".join(seg.text.strip() for seg in segments if seg.text.strip()).strip()
    return {"text": text}


_TRAILING_SILENCE_WINDOW_S = 0.1
_TRAILING_SILENCE_DBFS = -40.0  # same speech/silence line as SpeechConfig.min_avg_dbfs


def _trim_trailing_silence(waveform: np.ndarray, sample_rate: int) -> np.ndarray:
    """Drop trailing near-silent windows (a mid-passage pause, a breath, background
    hum) off the end of a growing buffer. A cheap RMS-per-window scan rather than a VAD
    pass -- this runs on every partial tick (every 1.2s, over a buffer that can grow to
    180s), so it needs to be fast, not exact."""
    window = int(_TRAILING_SILENCE_WINDOW_S * sample_rate)
    if window <= 0 or len(waveform) <= window:
        return waveform
    end = len(waveform)
    while end > window and audio_io.rms_dbfs(waveform[end - window : end]) < _TRAILING_SILENCE_DBFS:
        end -= window
    return waveform[:end]


def _transcribe_live_preview(waveform: np.ndarray) -> dict:
    """Same cheap pass as _transcribe_partial, but first drops a trailing near-silent
    stretch. LivePreviewSession re-transcribes the whole buffer from t=0 on every
    partial, so the tail is often silence, a breath, or background noise while the
    reader pauses mid-passage -- feeding Whisper a buffer that ends in near-silence is
    exactly when it hallucinates a word to fill the gap, which is what surfaces
    client-side as the live preview marking words ahead of what was actually said."""
    return _transcribe_partial(_trim_trailing_silence(waveform, SAMPLE_RATE))


class VoiceSession:
    """Per-connection VAD segmenter + transcription dispatcher. One instance per open
    WebSocket; fed raw int16 PCM bytes as they arrive, emits status/transcript messages
    the same shape agent.py's LiveKit data-channel payloads used."""

    def __init__(
        self, mode: str, on_message: Callable[[dict], Awaitable[None]],
        partial_interval_s: Optional[float] = None,
    ):
        self._mode = mode
        self._on_message = on_message
        self._iterator = VADIterator(
            _get_vad_model(), threshold=0.5, sampling_rate=SAMPLE_RATE,
            min_silence_duration_ms=550, speech_pad_ms=500,
        )
        self._window = np.empty(0, dtype=np.int16)  # partial window, <512 samples
        self._pre_roll: deque = deque(maxlen=PRE_ROLL_SAMPLES)
        self._speaking = False
        self._current: List[np.ndarray] = []
        # Live-partial preview (opt-in — None keeps every existing caller's behavior
        # unchanged): while speaking, every partial_interval_s a cheap transcribe runs
        # over the buffered-so-far audio and streams a "partial" message, so a long
        # utterance shows growing text instead of nothing until it ends.
        self._partial_interval_s = partial_interval_s
        self._samples_since_partial = 0
        self._partial_in_flight = False

    async def push(self, chunk: bytes) -> None:
        """Feed raw int16 PCM bytes off the WebSocket. Buffers to Silero's required
        512-sample window size, then runs VAD inference per window."""
        samples = np.frombuffer(chunk, dtype=np.int16)
        self._window = np.concatenate([self._window, samples])
        while len(self._window) >= WINDOW_SAMPLES:
            frame, self._window = self._window[:WINDOW_SAMPLES], self._window[WINDOW_SAMPLES:]
            await self._process_window(frame)

    async def _process_window(self, frame: np.ndarray) -> None:
        if self._speaking:
            self._current.append(frame)
            await self._maybe_send_partial()
        else:
            self._pre_roll.extend(frame.tolist())

        tensor = torch.from_numpy(frame.astype(np.float32) / 32768.0)
        try:
            event = self._iterator(tensor, return_seconds=False)
        except Exception:
            # Never let one bad window kill the session — same resilience fix just
            # applied to agent.py: log and keep going, don't let an exception here
            # silently end transcription for the rest of the connection.
            logger.exception("VAD inference failed")
            return

        if event is None:
            return
        if "start" in event and not self._speaking:
            self._speaking = True
            self._current = [np.array(self._pre_roll, dtype=np.int16)]
            self._samples_since_partial = 0
            await self._safe_send({"type": "status", "status": "speaking"})
        elif "end" in event and self._speaking:
            self._speaking = False
            await self._finalize()

    async def _maybe_send_partial(self) -> None:
        if not self._partial_interval_s or self._partial_in_flight:
            return
        self._samples_since_partial += WINDOW_SAMPLES
        if self._samples_since_partial < self._partial_interval_s * SAMPLE_RATE:
            return
        self._samples_since_partial = 0
        samples = np.concatenate(self._current) if self._current else np.empty(0, dtype=np.int16)
        if samples.size == 0:
            return
        self._partial_in_flight = True
        asyncio.create_task(self._run_partial(samples.astype(np.float32) / 32768.0))

    async def _run_partial(self, waveform: np.ndarray) -> None:
        loop = asyncio.get_running_loop()
        try:
            body = await loop.run_in_executor(_executor, _transcribe_partial, waveform)
        except Exception:
            logger.exception("Partial transcription failed")
            return
        finally:
            self._partial_in_flight = False
        # Only send if the utterance this partial covers is still in progress — the
        # transcribe call runs in the background, so the "end" event (and the real,
        # authoritative "transcript") can land while a partial is still in flight.
        # Sending a stale partial after the final would show old text with nothing to
        # clear it until the *next* utterance starts.
        if self._speaking and body["text"]:
            await self._safe_send({"type": "partial", "text": body["text"]})

    async def _safe_send(self, message: dict) -> None:
        """The socket can drop between the receive loop noticing (WebSocketDisconnect)
        and close()'s finally-block flushing any in-progress utterance — e.g. the user
        hits Stop mid-utterance, or the browser tab just drops the connection. Sending
        on an already-dead socket must never crash the WS handler, same reasoning as
        agent.py wrapping publish_data in try/except."""
        try:
            await self._on_message(message)
        except Exception:
            # visible by default (INFO) — a silent debug-level swallow here was the bug:
            # a send failure (dead socket, or anything else) had no way to surface.
            logger.warning("Voice session message send failed: %s", message.get("type"), exc_info=True)
        else:
            if message.get("type") == "transcript":
                logger.info("Sent transcript to frontend: %r", message.get("text"))

    async def _finalize(self) -> None:
        await self._safe_send({"type": "status", "status": "idle"})
        samples = np.concatenate(self._current) if self._current else np.empty(0, dtype=np.int16)
        self._current = []
        waveform = (samples.astype(np.float32) / 32768.0)
        logger.info("Utterance ended: %.2fs of audio, transcribing (mode=%s)", len(samples) / SAMPLE_RATE, self._mode)

        loop = asyncio.get_running_loop()
        try:
            body = await loop.run_in_executor(_executor, _transcribe, waveform, self._mode)
        except Exception:
            # A transcription failure must never take the session down — an unhandled
            # exception here would previously (agent.py, pre-fix) silently end
            # transcription for the rest of the connection. Always notify the frontend
            # so it doesn't hang waiting on a message that will never come.
            logger.exception("Transcription failed (mode=%s)", self._mode)
            body = {"text": ""}
        await self._safe_send({"type": "transcript", **body})

    async def close(self) -> None:
        """Flush whatever utterance was in progress when the socket closed — mirrors
        agent.py's forward_frames() calling vad_stream.end_input(), so speech still in
        progress at Stop time still gets transcribed and sent."""
        if self._speaking:
            self._speaking = False
            await self._finalize()


# Generous cap on how much audio a live-preview session will keep transcribing against —
# not a product limit (the caller's own upload endpoint enforces the real one via
# speech_config.max_recording_seconds), just a memory/cost backstop against a forgotten-
# open recording. Comfortably above any real Pronunciation Coach sentence or Accent
# Assessment passage read.
MAX_PREVIEW_SECONDS = 180


class LivePreviewSession:
    """Continuous live-preview transcription with no VAD segmentation — for reading a
    known target sentence/passage aloud (Pronunciation Coach, Accent Assessment), where
    natural mid-passage pauses must NOT be treated as end-of-speech the way a
    push-to-talk VoiceSession's utterance boundaries would. Buffers the whole recording
    and periodically streams a cheap partial transcript; never sends a "final" — the
    authoritative, per-word-classified result always comes from the caller's existing
    MediaRecorder-blob upload endpoint, completely unchanged. The frontend does its own
    lightweight positional word-compare against text it already has (the target
    sentence/passage) to decide live colors — this class only supplies growing text."""

    def __init__(self, on_message: Callable[[dict], Awaitable[None]], partial_interval_s: float = 1.2):
        self._on_message = on_message
        self._partial_interval_s = partial_interval_s
        self._buffer: List[np.ndarray] = []
        self._total_samples = 0
        self._samples_since_partial = 0
        self._partial_in_flight = False
        self._closed = False

    async def push(self, chunk: bytes) -> None:
        if self._closed or self._total_samples >= MAX_PREVIEW_SECONDS * SAMPLE_RATE:
            return
        samples = np.frombuffer(chunk, dtype=np.int16)
        self._buffer.append(samples)
        self._total_samples += len(samples)
        self._samples_since_partial += len(samples)

        if self._partial_in_flight or self._samples_since_partial < self._partial_interval_s * SAMPLE_RATE:
            return
        self._samples_since_partial = 0
        waveform = np.concatenate(self._buffer).astype(np.float32) / 32768.0
        self._partial_in_flight = True
        asyncio.create_task(self._run_partial(waveform))

    async def _run_partial(self, waveform: np.ndarray) -> None:
        loop = asyncio.get_running_loop()
        try:
            body = await loop.run_in_executor(_executor, _transcribe_live_preview, waveform)
        except Exception:
            logger.exception("Live-preview transcription failed")
            return
        finally:
            self._partial_in_flight = False
        if self._closed or not body["text"]:
            return
        try:
            await self._on_message({"type": "partial", "text": body["text"]})
        except Exception:
            logger.warning("Live-preview message send failed", exc_info=True)

    async def close(self) -> None:
        self._closed = True


async def serve_preview(websocket: WebSocket, partial_interval_s: float = 1.2) -> None:
    """Like serve(), but for a continuous LivePreviewSession — no VAD, no "stop" flush
    semantics needed, since there's no authoritative transcript on this channel to lose:
    the real result always comes from the caller's separate upload endpoint."""
    session = LivePreviewSession(on_message=websocket.send_json, partial_interval_s=partial_interval_s)
    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                return
            data = message.get("bytes")
            if data is not None:
                await session.push(data)
    finally:
        await session.close()


async def serve(websocket: WebSocket, mode: str, partial_interval_s: Optional[float] = None) -> None:
    """Owns the receive loop + resilient teardown for one already-accept()ed voice-ws
    connection — shared by every voice-enabled route (scenario/coaching/interview-coach/
    assessment/conversation/public-speaking) instead of each one duplicating this same
    try/except/finally shape. Also the one place that logs *why* a socket went down —
    previously `except WebSocketDisconnect: pass` silently swallowed the close code,
    making an early/unexpected client disconnect impossible to diagnose from server logs.

    partial_interval_s: opt-in live-preview streaming (see VoiceSession) — None (the
    default) keeps every existing caller's behavior exactly as before.

    Handles two frame kinds: binary (raw PCM, fed to the VAD segmenter) and text (a
    small JSON control message, currently only {"type": "stop"}). The text message
    matters: useVoiceSocket.ts's stopVoice() stops the mic feed immediately, which means
    Silero's natural end-of-speech detection — which needs a stretch of *continued
    silence* to fire — will never trigger on its own once the mic is dead. Without an
    explicit flush signal sent while the socket is still open, whatever utterance was
    in progress at Stop time is lost: relying on close()'s finally-block flush arrives
    too late, after WebSocketDisconnect already tore down the send side."""
    session = VoiceSession(mode=mode, on_message=websocket.send_json, partial_interval_s=partial_interval_s)
    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                logger.info("Voice socket disconnected (code=%s)", message.get("code"))
                return
            data = message.get("bytes")
            if data is not None:
                await session.push(data)
            elif message.get("text") is not None:
                await session.close()  # flush now, while the socket can still send
    finally:
        await session.close()  # no-op if already flushed above (VoiceSession.close() is idempotent)
