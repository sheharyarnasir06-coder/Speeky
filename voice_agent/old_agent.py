"""LiveKit worker for AI Conversation Practice's voice mode.

Room-naming contract: the LiveKit room name IS the conversation session_id
(see conversation_service._start_session: session["room_name"] = session_id,
and livekit_tokens.mint_room_token(session["room_name"], ...) — the frontend
joins that exact room with the token from POST /conversation/sessions/{id}/voice-token).

This worker auto-dispatches to every room a participant joins (default LiveKit
agent dispatch — no per-session launch needed). For each subscribed audio track
it runs Silero VAD to find speech segments, transcribes each segment locally
with faster-whisper, and sends results over the room's LiveKit data channel:

    topic="voice_transcript", payload={"text": "..."}   — final transcript
    topic="voice_status",     payload={"status": "speaking"|"idle"}  — live state

The frontend (see ConversationSessionPage's RoomEvent.DataReceived handler)
appends transcript text into the message input box — the user reviews/edits it
and hits Send, reusing the existing POST /conversation/sessions/{id}/messages
path. The status packets drive a pulsing mic dot so the user sees when speech
is being detected. This worker never calls the backend directly and never
auto-sends on the user's behalf.
"""

import asyncio
import io
import json
import logging
from concurrent.futures import ThreadPoolExecutor

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


def transcribe(frame: rtc.AudioFrame) -> str:
    # Hand faster-whisper a WAV file-like object (via to_wav_bytes(), which correctly tags the frame's real sample rate .
    # Silero's VAD event frame is at the track's native rate, e.g. 48kHz, NOT the 16kHz Silero resamples to internally for its own inference) instead of a raw ndarray.
    wav_bytes = frame.to_wav_bytes()
    # temperature=0: single decode pass. faster-whisper's default temperature-fallback
    # ladder retries up to 6x on low-confidence audio, turning one utterance into a
    # 7-10s+ block — the user reviews/edits the transcript before sending anyway, so a
    # rougher single-pass result beats a more "accurate" one that misses the latency budget.
    segments, _info = model.transcribe(io.BytesIO(wav_bytes), beam_size=5, temperature=0)
    return " ".join(seg.text.strip() for seg in segments).strip()


async def publish_transcript(room: rtc.Room, text: str) -> None:
    if not text:
        return
    payload = json.dumps({"text": text}).encode("utf-8")
    try:
        await room.local_participant.publish_data(payload, reliable=True, topic="voice_transcript")
        logger.info("Sent transcript to frontend: %r", text)
    except Exception:
        logger.exception("Failed to publish transcript over data channel")


async def publish_status(room: rtc.Room, status: str) -> None:
    """Send a speaking/idle hint so the frontend can show a live mic indicator."""
    payload = json.dumps({"status": status}).encode("utf-8")
    try:
        await room.local_participant.publish_data(payload, reliable=False, topic="voice_status")
    except Exception:
        pass  # best-effort — status hints are non-critical


async def process_audio(track: rtc.Track, identity: str, vad: silero.VAD, room: rtc.Room):
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
                text = await asyncio.get_running_loop().run_in_executor(
                    _executor, transcribe, event.frames[0]
                )
                logger.info("Speech ENDED (%s): %r", identity, text)
                await publish_transcript(room, text)

    await asyncio.gather(forward_frames(), read_vad_events())


async def entrypoint(ctx: JobContext):
    await ctx.connect()
    logger.info("Connected to room: %s", ctx.room.name)

    vad = silero.VAD.load()

    @ctx.room.on("track_subscribed")
    def on_track_subscribed(track: rtc.Track, publication, participant):
        if track.kind == rtc.TrackKind.KIND_AUDIO:
            logger.info("Subscribed to audio from %s", participant.identity)
            asyncio.create_task(process_audio(track, participant.identity, vad, ctx.room))

    # Drain tracks that were already published before this worker joined.
    # track_subscribed only fires for future subscriptions — without this loop
    # any mic the browser published before the agent connected is silently missed.
    for participant in ctx.room.remote_participants.values():
        for publication in participant.track_publications.values():
            if publication.track and publication.track.kind == rtc.TrackKind.KIND_AUDIO:
                logger.info("Processing pre-existing audio from %s", participant.identity)
                asyncio.create_task(
                    process_audio(publication.track, participant.identity, vad, ctx.room)
                )

    await asyncio.Event().wait()


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))