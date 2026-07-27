"""LiveKit worker for AI Conversation Practice's voice mode.

Room-naming contract: the LiveKit room name IS the conversation session_id
(see conversation_service._start_session: session["room_name"] = session_id,
and livekit_tokens.mint_room_token(session["room_name"], ...) — the frontend
joins that exact room with the token from POST /conversation/sessions/{id}/voice-token).

This worker auto-dispatches to every room a participant joins (default LiveKit
agent dispatch — no per-session launch needed). For each subscribed audio track
it runs Silero VAD to find speech segments, transcribes each segment locally
with faster-whisper, and sends results over the room's LiveKit data channel:

    topic="voice_transcript", payload={"text": "..."}   — "transcript" mode (default)
    topic="voice_transcript", payload={
        "text": "...", "duration_seconds": 1.23,
        "word_timings": [{"word": "hello", "start": 0.0, "end": 0.4}, ...]
    }                                                     — "timed" mode (Conversation)
    topic="voice_transcript", payload={"text": "...", "features": {...}}  — "full" mode
    topic="voice_status",     payload={"status": "speaking"|"idle"}  — live state

The pipeline mode is stamped into the LiveKit participant metadata by
livekit_tokens.mint_room_token() and read back via _participant_mode() below —
see that function's docstring for which page uses which mode and why.

The frontend (see ConversationSessionPage's RoomEvent.DataReceived handler)
appends transcript text into the message input box — the user reviews/edits it
and hits Send, reusing the existing POST /conversation/sessions/{id}/messages
path. Conversation's "timed" audio_features (duration_seconds + word_timings)
are stored locally in the frontend and sent alongside the message so the
backend records this as an "audio" turn, enabling pronunciation scoring
(US-79/74). The status packets drive a pulsing mic dot so the user sees when
speech is being detected. This worker never calls the backend directly and
never auto-sends on the user's behalf.
"""

import asyncio
import io
import json
import logging
from concurrent.futures import ThreadPoolExecutor

from lib import audio_io, prosody_engine, vad_engine
from lib.speech_config import load_speech_config
from dotenv import load_dotenv
from faster_whisper import WhisperModel
from livekit import rtc
from livekit.agents import JobContext, WorkerOptions, cli
from livekit.agents import vad as agents_vad
from livekit.plugins import silero

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("voice-agent")

model = WhisperModel("base", device="cpu", compute_type="int8")

# model.transcribe() is synchronous/CPU-bound; run it off the event loop so it never
# blocks the agent's WebRTC keepalives (a blocked loop for the several seconds
# transcription takes was tipping the LiveKit connection into a client-initiated
# disconnect mid-session). max_workers=1 also serializes calls onto one shared model
# instance, which isn't guaranteed safe for concurrent inference.
_executor = ThreadPoolExecutor(max_workers=1)


def transcribe_plain(frame: rtc.AudioFrame) -> str:
    """Fastest path — text only, no word alignment. Used by every mode that never
    reads word_timings/duration_seconds back (Scenario, Coaching, Interview Coach,
    Assessment), so they get the same speed/accuracy the old worker had rather than
    paying for word-timestamp alignment nobody consumes."""
    wav_bytes = frame.to_wav_bytes()
    # temperature=0: single decode pass. faster-whisper's default temperature-fallback
    # ladder retries up to 6x on low-confidence audio, turning one utterance into a
    # 7-10s+ block — the user reviews/edits the transcript before sending anyway, so a
    # rougher single-pass result beats a more "accurate" one that misses the latency budget.
    segments, _info = model.transcribe(io.BytesIO(wav_bytes), beam_size=5, temperature=0)
    return " ".join(seg.text.strip() for seg in segments).strip()


def transcribe_timed(frame: rtc.AudioFrame) -> dict:
    """timed mode — text + per-word timings + utterance duration, no prosody. Only
    Conversation reads these back, to record audio turns for pronunciation scoring
    (US-79/74)."""
    wav_bytes = frame.to_wav_bytes()

    # Calculate real duration from frame metadata rather than guessing.
    # AudioFrame.samples_per_channel / sample_rate = seconds of audio.
    duration_seconds = frame.samples_per_channel / frame.sample_rate if frame.sample_rate > 0 else 0.0

    # word_timestamps=True: get per-word start/end times for pronunciation scoring.
    segments, _ = model.transcribe(
        io.BytesIO(wav_bytes),
        beam_size=5,
        temperature=0,
        word_timestamps=True,
    )

    text_parts = []
    word_timings = []
    for segment in segments:
        text = segment.text.strip()
        if text:
            text_parts.append(text)
        for word in segment.words or []:
            cleaned = word.word.strip()
            if cleaned:
                word_timings.append({
                    "word": cleaned,
                    "start": round(word.start, 3),
                    "end": round(word.end, 3),
                })

    return {
        "text": " ".join(text_parts).strip(),
        "duration_seconds": round(duration_seconds, 3),
        "word_timings": word_timings,
    }


async def publish_transcript(room: rtc.Room, body: dict) -> None:
    """Publish one transcript payload. `body` always carries "text", plus whatever
    the mode adds (nothing / duration_seconds+word_timings / features)."""
    text = body.get("text")
    if not text:
        return
    payload = json.dumps(body).encode("utf-8")
    try:
        await room.local_participant.publish_data(payload, reliable=True, topic="voice_transcript")
        logger.info("Sent transcript to frontend: %r", text)
    except Exception:
        logger.exception("Failed to publish transcript over data channel")


def transcribe_full(frame: rtc.AudioFrame) -> dict:
    """FULL mode: transcript + word timings + prosody + input level for one utterance."""
    wav_bytes = frame.to_wav_bytes()
    segments, _info = model.transcribe(
        io.BytesIO(wav_bytes), beam_size=5, temperature=0, word_timestamps=True
    )
    text_parts, word_timings = [], []
    for seg in segments:
        text_parts.append(seg.text.strip())
        for w in (seg.words or []):
            word_timings.append(
                {"word": w.word.strip(), "start": round(float(w.start), 3), "end": round(float(w.end), 3)}
            )
    text = " ".join(text_parts).strip()

    features = {"word_timings": word_timings}
    cfg = load_speech_config()
    decoded = audio_io.decode_audio_bytes(wav_bytes, cfg.audio_sample_rate)
    waveform, sr = decoded.waveform, decoded.sample_rate
    prosody = prosody_engine.analyze(waveform, sr)
    vad_result = vad_engine.detect_speech_segments(waveform, sr, cfg)
    _noise_floor, snr_db = vad_engine.estimate_noise_and_snr(waveform, sr, vad_result)
    features.update(
        {
            "duration_seconds": round(decoded.duration_seconds, 3),
            "avg_db": round(audio_io.rms_dbfs(waveform), 2),
            "pitch_range_semitones": round(float(prosody.pitch_range_semitones), 2),
            "snr_db": round(float(snr_db), 1),
        }
    )

    return {"text": text, "features": features}



async def publish_status(room: rtc.Room, status: str) -> None:
    """Send a speaking/idle hint so the frontend can show a live mic indicator."""
    payload = json.dumps({"status": status}).encode("utf-8")
    try:
        await room.local_participant.publish_data(payload, reliable=False, topic="voice_status")
    except Exception:
        pass  # best-effort — status hints are non-critical


async def process_audio(track: rtc.Track, identity: str, vad: silero.VAD, room: rtc.Room, mode: str):
    audio_stream = rtc.AudioStream(track)
    vad_stream = vad.stream()

    async def forward_frames():
        async for event in audio_stream:
            vad_stream.push_frame(event.frame)
        vad_stream.end_input()

    async def read_vad_events():
        async for event in vad_stream:
            if event.type == agents_vad.VADEventType.START_OF_SPEECH:
                logger.info("Speech STARTED (%s)", identity)
                await publish_status(room, "speaking")
            elif event.type == agents_vad.VADEventType.END_OF_SPEECH:
                await publish_status(room, "idle")
                # Silero's END_OF_SPEECH event carries the whole utterance as a single
                # already-combined frame (see livekit/plugins/silero/vad.py's
                # _copy_speech_buffer) — no need to concatenate multiple frames.

                loop = asyncio.get_running_loop()
                if mode == "full":
                    result = await loop.run_in_executor(_executor, transcribe_full, event.frames[0])
                    logger.info("Speech ENDED (%s) [full]: %r", identity, result["text"])
                    await publish_transcript(room, result)
                elif mode == "timed":
                    result = await loop.run_in_executor(_executor, transcribe_timed, event.frames[0])
                    logger.info("Speech ENDED (%s) [timed]: %r", identity, result["text"])
                    await publish_transcript(room, result)
                else:
                    text = await loop.run_in_executor(_executor, transcribe_plain, event.frames[0])
                    logger.info("Speech ENDED (%s): %r", identity, text)
                    await publish_transcript(room, {"text": text})

    await asyncio.gather(forward_frames(), read_vad_events())


def _participant_mode(participant: rtc.RemoteParticipant) -> str:
    """Read the pipeline mode the caller requested from its participant metadata (stamped
    by livekit_tokens.mint_room_token):
      "transcript" (default) — Scenario / Coaching / Interview Coach / Assessment
      "timed"                — Conversation (word_timings + duration_seconds)
      "full"                 — Public Speaking Coach (+ prosody)"""
    try:
        meta = json.loads(participant.metadata or "{}")
        mode = meta.get("mode")
        return mode if mode in ("full", "timed") else "transcript"
    except Exception:
        return "transcript"


async def entrypoint(ctx: JobContext):
    await ctx.connect()
    logger.info("Connected to room: %s", ctx.room.name)

    vad = silero.VAD.load()

    @ctx.room.on("track_subscribed")
    def on_track_subscribed(track: rtc.Track, publication, participant):
        if track.kind == rtc.TrackKind.KIND_AUDIO:
            mode = _participant_mode(participant)
            logger.info("Subscribed to audio from %s (mode=%s)", participant.identity, mode)
            asyncio.create_task(process_audio(track, participant.identity, vad, ctx.room, mode))

    # Drain tracks that were already published before this worker joined.
    # track_subscribed only fires for future subscriptions — without this loop
    # any mic the browser published before the agent connected is silently missed.
    for participant in ctx.room.remote_participants.values():
        mode = _participant_mode(participant)
        for publication in participant.track_publications.values():
            if publication.track and publication.track.kind == rtc.TrackKind.KIND_AUDIO:
                logger.info("Processing pre-existing audio from %s (mode=%s)", participant.identity, mode)
                asyncio.create_task(
                    process_audio(publication.track, participant.identity, vad, ctx.room, mode)
                )

    await asyncio.Event().wait()


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
