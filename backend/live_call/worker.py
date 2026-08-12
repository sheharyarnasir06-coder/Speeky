"""Live Call agent worker entrypoint.

Run locally while iterating (auto-reconnects, verbose):
    uv run python -m live_call.worker dev
Run as the long-running deployed worker:
    uv run python -m live_call.worker start

Deliberately NOT part of the FastAPI process (backend/main.py) — LiveKit Cloud
dispatches one job per room to this worker. It talks to Postgres directly
(lib.prisma_client.db) and imports services/* directly, so a Live Call session's data
is identical in shape to a typed/push-to-talk one — no HTTP relay back to the API.
"""

import asyncio
import contextlib
import logging
import os

from dotenv import load_dotenv

load_dotenv(override=True)  # must run before any project-lib import for proper envs.

import numpy as np
from livekit import agents, rtc
from livekit.agents import Agent, AgentSession, stt
from livekit.agents.voice.room_io import RoomInputOptions, RoomOutputOptions
from livekit.agents.voice.room_io._output import _ParticipantAudioOutput
from livekit.agents.voice.turn import TurnHandlingOptions
from livekit.plugins import bey, silero
from prisma.engine.errors import EngineError

from lib import stt_engine, tts_client
from lib.prisma_client import db
from lib.speech_config import load_speech_config
from live_call import dispatch
from live_call.llm_plugin import ServiceLLM
from live_call.stt_plugin import WhisperSTT
from live_call.tts_plugin import PiperTTS

logger = logging.getLogger("live-call-agent")

# `dev` mode's CLI defaults the root logger to DEBUG, which makes every query call breakdown so reduce that to warning level.
for _noisy in ("prisma", "asyncio", "piper"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)
logging.getLogger("livekit").setLevel(logging.INFO)

_db_connected = False
_db_lock = asyncio.Lock()


async def _ensure_db_connected() -> None:
    global _db_connected
    if _db_connected:
        return
    async with _db_lock:
        if not _db_connected:
            await db.connect()
            _db_connected = True


async def _reset_db_connection() -> None:
    """ _ensure_db_connected() spins up a fresh one instead of reusing a dead one."""
    global _db_connected
    async with _db_lock:
        _db_connected = False
        with contextlib.suppress(Exception):
            await db.disconnect()


_SETUP_TIMEOUT_S = 15


def _prewarm(proc: agents.JobProcess) -> None:
    """Runs once per worker subprocess, before it accepts any job — loads Silero
    once instead of on every entrypoint() call (official LiveKit prewarm pattern)."""
    proc.userdata["vad"] = silero.VAD.load(min_silence_duration=1.1)


def _warm_stt_tts() -> None:
    """faster-whisper (thread-local) and Piper (process-global) both lazy-load their
    model on first real call — several seconds of load time on top of actual inference.
    That cost lands on whichever turn happens first in a call (the
    canned opener's TTS, or worse, the caller's own STT if they talk over it), reading as the agent going silent. Fired fire-and-forget right after room connect so it overlaps the existing DB/setup awaits instead of adding wall-clock time. Piper's
    warm-up is a permanent win (global singleton); whisper's is best-effort only since
    a later call can still land on a different, cold executor thread."""
    with contextlib.suppress(Exception):
        stt_engine.transcribe(np.zeros(8000, dtype=np.float32), 16000, load_speech_config())
    with contextlib.suppress(Exception):
        tts_client.synthesize(" ")


# Matches RoomOutputOptions' own audio defaults (livekit.agents.voice.room_io.types) —
# reproducing exactly what RoomIO would have published had the avatar never started.
_FALLBACK_AUDIO_SAMPLE_RATE = 24000
_FALLBACK_AUDIO_NUM_CHANNELS = 1

# Bey's own join briefly disconnects-then-reconnects as normal setup churn (observed in
# practice: a disconnect event fires, then "remote participant ready" ~100ms later) — a
# bare disconnect is not proof of death, only staying gone past this grace window is.
_AVATAR_DISCONNECT_GRACE_S = 3.0


async def _start_avatar_or_skip(session: AgentSession, room: rtc.Room) -> bey.AvatarSession | None:
    """Optional Beyond Presence lip-synced avatar. Env-gated (unset key or blocked/dropped = audio-call only)."""
    if not os.getenv("BEY_API_KEY"):
        return None
    try:
        avatar = bey.AvatarSession(avatar_id=os.getenv("BEY_AVATAR_ID","694c83e2-8895-4a98-bd16-56332ca3f449"))
        await asyncio.wait_for(avatar.start(session, room=room), timeout=_SETUP_TIMEOUT_S)
        return avatar
    except Exception:
        logger.exception("Beyond Presence avatar failed to start; continuing audio-only")
        return None


def _watch_avatar_health(session: AgentSession, room: rtc.Room, avatar: bey.AvatarSession) -> None:
    """ The avatar publishes as its own room participant (avatar.avatar_identity), 
    so its disconnect is the signal — but only once it's stayed gone past _AVATAR_DISCONNECT_GRACE_S; swapping on the bare event fired
    on a transient reconnect blip and severed a still-recovering avatar mid-setup."""
    fallen_back = False

    async def _confirm_and_fallback() -> None:
        nonlocal fallen_back
        await asyncio.sleep(_AVATAR_DISCONNECT_GRACE_S)
        if fallen_back or avatar.avatar_identity in room.remote_participants:
            return
        fallen_back = True
        room.off("participant_disconnected", _on_disconnected)
        logger.warning("Beyond Presence avatar disconnected mid-call; falling back to audio-only")
        session.output.replace_audio_tail(
            _ParticipantAudioOutput(
                room,
                sample_rate=_FALLBACK_AUDIO_SAMPLE_RATE,
                num_channels=_FALLBACK_AUDIO_NUM_CHANNELS,
                track_publish_options=rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE),
            )
        )

    def _on_disconnected(participant: rtc.RemoteParticipant) -> None:
        if participant.identity != avatar.avatar_identity:
            return
        asyncio.create_task(_confirm_and_fallback())

    room.on("participant_disconnected", _on_disconnected)


async def _run_idle_audience(ctx: agents.JobContext, session_id: str, user_id: str) -> None:
    """Public Speaking's speech phase: an avatar to speak *to*, that never speaks back.

    The session is built with no stt, llm, tts or turn_handling — not disabled, absent. That is
    what makes this safe to run during a monologue being recorded and scored: there is no
    transcription path for the speaker's own voice to leak into, and nothing that could ever
    produce speech over them (dispatch.IdleAvatarSetup carries no turn_handler for the same
    reason). Without the avatar there is nothing to show, so this is a no-op rather than an
    audio-only fallback.
    """
    try:
        await asyncio.wait_for(_ensure_db_connected(), timeout=_SETUP_TIMEOUT_S)
        setup = await asyncio.wait_for(
            dispatch.build_idle_setup(session_id, user_id), timeout=_SETUP_TIMEOUT_S
        )
    except Exception:
        logger.exception("Idle audience setup failed: session_id=%s", session_id)
        ctx.shutdown(reason="idle audience setup failed")
        return

    session = AgentSession()
    if not await _start_avatar_or_skip(session, ctx.room):
        logger.warning("No avatar available; idle audience has nothing to render")
        ctx.shutdown(reason="idle audience unavailable")
        return

    # Do not even subscribe to the speaker's microphone. With no STT there is nowhere for that
    # audio to go, but the speech being recorded here is the thing under assessment — the room
    # should not receive it at all. Transcription output is off for the same reason.
    #
    # audio_enabled=False for the reason described in entrypoint(): RoomIO would otherwise take
    # ownership of the audio output the avatar just claimed. This session has no voice to lose
    # today, but the ownership is the avatar's either way.
    await session.start(
        room=ctx.room,
        agent=Agent(instructions=setup.instructions),
        room_input_options=RoomInputOptions(audio_enabled=False, text_enabled=False),
        room_output_options=RoomOutputOptions(audio_enabled=False, transcription_enabled=False),
    )


async def _speak_and_disconnect(ctx: agents.JobContext, message: str) -> None:
    """DB/session lookup failed — leaving the caller in silence staring at "Connecting…"
    forever is worse than a short spoken apology. TTS-only session, no STT/LLM needed."""
    session = AgentSession(tts=PiperTTS())
    await session.start(room=ctx.room, agent=Agent(instructions=message))
    # The apology is best-effort: if TTS is what broke, disconnecting still beats hanging.
    with contextlib.suppress(Exception):
        handle = session.say(message)
        await handle.wait_for_playout()
    ctx.shutdown(reason="live call setup failed")


async def entrypoint(ctx: agents.JobContext) -> None:
    # Join the room FIRST, before anything DB-dependent — a slow/unreachable database
    # must never block the room join itself, or the caller sees an agent that never
    # even connects (indistinguishable from a crash) instead of a spoken error.
    await ctx.connect()
    asyncio.create_task(asyncio.to_thread(_warm_stt_tts))

    feature, mode, session_id = dispatch.parse_room_name(ctx.room.name)
    participant = await ctx.wait_for_participant()
    user_id = participant.identity  # set via .with_identity(user_id) at token mint time
    logger.info(
        "Live Call job: feature=%s mode=%s session_id=%s participant_identity=%s",
        feature, mode, session_id, user_id,
    )

    # The idle audience has no voice by design, so it must be dispatched before the TTS check
    # below — that check is about a *talking* agent being unable to do its job.
    if mode == "idle":
        await _run_idle_audience(ctx, session_id, user_id)
        return

    # A voice agent with no voice cannot do anything the caller came for, and the failure is
    # otherwise invisible: the room connects, the avatar may even appear, then the first
    # session.say() raises and kills the job mid-call. Fail here instead, loudly and with the
    # fix in the log — the model file is gitignored, so a fresh machine hits this every time.
    if not tts_client.is_configured():
        logger.error(
            "No Piper voice model — expected %s. Download it (see data/tts/README.md); the "
            "filename must match TTS_VOICE_MODEL. Dropping this call.",
            tts_client._model_path(),
        )
        ctx.shutdown(reason="tts voice model missing")
        return

    try:
        await asyncio.wait_for(_ensure_db_connected(), timeout=_SETUP_TIMEOUT_S)
        setup = await asyncio.wait_for(
            dispatch.build_setup(feature, session_id, user_id), timeout=_SETUP_TIMEOUT_S
        )
    except (EngineError, asyncio.TimeoutError):
        # Engine-level failure or a hang long enough to time out — force a reconnect.
        logger.exception("Live Call DB engine unhealthy; forcing reconnect: feature=%s session_id=%s", feature, session_id)
        await _reset_db_connection()
        await _speak_and_disconnect(
            ctx, "Sorry, I'm having trouble connecting right now. Please try again in a moment."
        )
        return
    except Exception:
        logger.exception("Live Call setup failed: feature=%s session_id=%s", feature, session_id)
        await _speak_and_disconnect(
            ctx, "Sorry, I'm having trouble connecting right now. Please try again in a moment."
        )
        return

    # One VAD instance shared by the STT segmentation adapter and the session's own
    # turn-taking/interruption detection — two distinct concerns, no reason to load the
    # Silero model twice in the same process.
    #
    # min_silence_duration is longer than push-to-talk's 0.55s (lib/voice_ws.py):
    # push-to-talk is "read one sentence", Live Call is free conversation where an ESL
    # learner routinely pauses mid-sentence to find a word. At 0.55s that pause reads as
    # "done talking"
    vad = ctx.proc.userdata["vad"]
    session = AgentSession(
        stt=stt.StreamAdapter(stt=WhisperSTT(), vad=vad),
        llm=ServiceLLM(setup.turn_handler),
        tts=PiperTTS(),
        vad=vad,
        # Our STT is a single batch transcription per utterance, not a real streaming
        # STT with interim results — LiveKit's default smart turn-detector expects the
        # latter (it makes a semantic "is this sentence actually finished" call over
        # interim text, which timed out and mis-fired here, cutting users off mid-
        # sentence). Plain VAD silence-based endpointing, on both turn-taking and
        # interruption detection, matches what we can actually signal from a batch STT.
        #
        # "dynamic" mode starts at min_delay (snappier than the old fixed 1.1s) and
        # learns this caller's actual pause length from their own speech, floating the
        # wait up toward max_delay when they hesitate mid-sentence — fast by default,
        # still forgiving of a real pause, instead of every user paying a flat tax.
        turn_handling=TurnHandlingOptions(
            turn_detection="vad",
            endpointing={"mode": "dynamic", "min_delay": 0.7, "max_delay": 5.0},
            interruption={"mode": "vad"},
        ),
    )
    # The avatar takes ownership of the audio output (bey swaps in a DataStreamAudioOutput that
    # streams speech to it for lip-sync). RoomIO would then assign its own output straight over
    # that — `self._agent_session.output.audio = self.audio_output`, a whole-chain replacement —
    # and the agent would publish to the room directly while the avatar, receiving nothing, sat
    # frozen. Suppressing RoomIO's audio output is what leaves the avatar's in place; without an
    # avatar it is still needed, hence the flag rather than a constant.
    avatar = await _start_avatar_or_skip(session, ctx.room)
    await session.start(
        room=ctx.room,
        agent=Agent(instructions=setup.instructions),
        room_output_options=RoomOutputOptions(audio_enabled=avatar is None),
    )
    if avatar is not None:
        _watch_avatar_health(session, ctx.room, avatar)

    # Voice barge-in (talking over the agent) is already handled by
    # TurnHandlingOptions(interruption={"mode": "vad"}) above — the framework cuts off
    # whatever's currently playing the instant VAD detects the user speaking. This adds
    # the other trigger the frontend wants: a manual "interrupt" button for when the
    # user wants to jump in without out-talking the agent. 
    def _on_interrupt_rpc(_data: rtc.RpcInvocationData) -> str:
        session.interrupt()
        return "ok"

    ctx.room.local_participant.register_rpc_method("interrupt_agent", _on_interrupt_rpc)

    # Public Speaking's opening line is the question being asked, and an avatar adds seconds of
    # its own before any audio plays (DataStreamAudioOutput blocks until the avatar participant
    # has published). A caller saying "hello" into that gap used to interrupt the question away,
    # leaving them to answer something they never heard. Speak it regardless of what they are
    # doing, and let nothing cut it short.
    if setup.opening_is_essential:
        await session.say(setup.opening_line, allow_interruptions=False)
        return

    # The caller's mic is live the instant start() returns, and our STT is a single
    # batch transcription per VAD segment, not a real streaming one — if the canned
    # opener starts playing on top of speech that's already in progress, the framework
    # commits whatever's buffered as its own turn the moment agent speech begins, which
    # is what split a caller's opening sentence into two disconnected turns. Skip the
    # greeting if they've already started talking (their utterance becomes the natural
    # first turn instead), and bail out of it early if they start mid-line too.
    if session.user_state == "speaking":
        return

    greeting = session.say(setup.opening_line)

    def _yield_floor_if_user_speaks(ev) -> None:
        if ev.new_state == "speaking":
            greeting.interrupt()

    session.on("user_state_changed", _yield_floor_if_user_speaks)
    try:
        await greeting
    finally:
        session.off("user_state_changed", _yield_floor_if_user_speaks)


if __name__ == "__main__":
    agents.cli.run_app(agents.WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=_prewarm))
