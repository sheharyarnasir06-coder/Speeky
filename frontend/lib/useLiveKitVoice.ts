"use client";

import * as React from "react";
import {
  Room,
  RoomEvent,
  Track,
  createLocalAudioTrack,
  type LocalAudioTrack,
} from "livekit-client";
import { ApiError } from "./api";

export interface VoiceTokenResult {
  url: string;
  token: string;
  room: string;
}

export interface AudioFeatures {
  duration_seconds: number;
  word_timings: { word: string; start: number; end: number }[];
}

// Ceiling for how long stopVoice() waits for an in-flight transcript before giving up
// and disconnecting anyway — matches the product's stated max latency budget.
const STOP_WAIT_MS = 15000;

/**
 * Shared LiveKit voice-in hook: connects to a per-session LiveKit room, publishes the
 * mic, and forwards transcripts the voice_agent/ worker sends back over the data
 * channel (topic "voice_transcript") to `onTranscript` — never auto-sends, callers
 * decide what text state the transcript fills. Mirrors the logic that originally lived
 * inline in the Conversation session page, generalized for Scenarios/Coaching/Interview
 * Coach to reuse.
 */
// Full-mode acoustic features the voice_agent attaches to a transcript (word timings +
// prosody + level). Undefined in transcript mode. Shape mirrors voice_agent/agent.py.
export interface VoiceFeatures {
  word_timings?: { word: string; start: number; end: number }[];
  duration_seconds?: number;
  avg_db?: number;
  pitch_range_semitones?: number;
}

export function useLiveKitVoice(
  fetchToken: () => Promise<VoiceTokenResult>,
  onTranscript: (text: string, features?: AudioFeatures | VoiceFeatures) => void,
) {
  const [isVoiceActive, setIsVoiceActive] = React.useState(false);
  const [isConnectingVoice, setIsConnectingVoice] = React.useState(false);
  const [isStoppingVoice, setIsStoppingVoice] = React.useState(false);
  const [voiceStatus, setVoiceStatus] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);

  const roomRef = React.useRef<Room | null>(null);
  const microphoneTrackRef = React.useRef<LocalAudioTrack | null>(null);
  const onTranscriptRef = React.useRef(onTranscript);
  onTranscriptRef.current = onTranscript;
  // True from a "speaking" status until the matching transcript lands — lets stopVoice()
  // know whether there's anything worth waiting for, instead of always waiting/never
  // waiting.
  const utteranceInFlightRef = React.useRef(false);
  // Set by stopVoice() while it's waiting; the DataReceived handler resolves it early
  // the moment the transcript it's waiting for actually arrives.
  const pendingStopResolveRef = React.useRef<(() => void) | null>(null);
  // Stores the audio features from the most recent transcript — caller reads this
  // via getLastAudioFeatures() before clearing it on message send.
  const lastAudioFeaturesRef = React.useRef<AudioFeatures | null>(null);

  const startVoice = React.useCallback(async () => {
    if (roomRef.current) return;

    setError(null);
    setIsConnectingVoice(true);
    setVoiceStatus("Connecting voice...");
    utteranceInFlightRef.current = false;

    // Local reference (not the ref) so the catch block can clean up a room that
    // connected but failed a later step (e.g. mic publish) — roomRef itself is only
    // set once the whole sequence succeeds, so relying on roomRef here would leak an
    // orphaned, still-connected room under this user's identity on any partial failure.
    let room: Room | null = null;

    try {
      const voiceData = await fetchToken();
      room = new Room();

      room.on(RoomEvent.Disconnected, () => {
        // console.log("[voice] room disconnected, reason:", reason);
        setIsVoiceActive(false);
        setVoiceStatus("Voice disconnected.");
      });

      // room.on(RoomEvent.ParticipantConnected, (p) => {
      //   console.log("[voice] participant joined room:", p.identity);
      // });

      // reason=1 (CLIENT_INITIATED) only tells us the JS SDK sent the leave — not WHY.
      // These catch every path that could trigger it "reconnecting, reconnected, media-device-error" etc... with the mic track itself dying (device/permission issue).

      // Logged unconditionally (not just on topic match) so a topic/payload mismatch
      // shows up in devtools instead of silently doing nothing.
      room.on(RoomEvent.DataReceived, (payload, participant, _kind, topic) => {
        console.log("[voice] data received", {
          topic,
          from: participant?.identity,
          bytes: payload.length,
        });
        try {
          const data = JSON.parse(new TextDecoder().decode(payload));
          if (topic === "voice_status") {
            if (data.status === "speaking") utteranceInFlightRef.current = true;
            return;
          }
          if (topic !== "voice_transcript") return;
          const text: string = data.text;
          utteranceInFlightRef.current = false;
          pendingStopResolveRef.current?.();
          if (!text) return;

          // voice_agent/agent.py sends either:
          //   full mode:    { text, features: { word_timings, duration_seconds, ... } }
          //   simple mode:  { text, duration_seconds, word_timings }  (flat, no "features" key)
          // Normalize both into one `features` object so callers get a consistent shape.
          const features: VoiceFeatures | AudioFeatures | undefined = data.features ?? (
            typeof data.duration_seconds === "number" && Array.isArray(data.word_timings)
              ? { duration_seconds: data.duration_seconds, word_timings: data.word_timings }
              : undefined
          );

          lastAudioFeaturesRef.current =
            features && Array.isArray((features as AudioFeatures).word_timings) &&
            typeof (features as AudioFeatures).duration_seconds === "number"
              ? {
                  duration_seconds: (features as AudioFeatures).duration_seconds,
                  word_timings: (features as AudioFeatures).word_timings,
                }
              : null;

          onTranscriptRef.current(text, features);
          setVoiceStatus("Heard you — review and hit Send.");
        } catch (err) {
          console.error("Failed to parse voice data payload:", err);
        }
      });

      await room.connect(voiceData.url, voiceData.token);
      console.log(
        "[voice] connected to room",
        voiceData.room,
        "state:",
        room.state,
      );

      const microphoneTrack = await createLocalAudioTrack();
      microphoneTrack.mediaStreamTrack.addEventListener("ended", () =>
        console.error(
          "[voice] mic MediaStreamTrack ended unexpectedly (device lost/revoked?)",
        ),
      );
      await room.localParticipant.publishTrack(microphoneTrack, {
        source: Track.Source.Microphone,
      });
      console.log("[voice] mic track published, sid:", microphoneTrack.sid);

      roomRef.current = room;
      microphoneTrackRef.current = microphoneTrack;

      setIsVoiceActive(true);
      setVoiceStatus("Voice connected. Microphone is active.");
    } catch (err) {
      console.error("[voice] failed to start voice:", err);

      microphoneTrackRef.current?.stop();
      microphoneTrackRef.current = null;
      roomRef.current = null;

      if (room) {
        console.trace("[voice] disconnect call site: startVoice catch block");
        await room.disconnect();
      }

      setIsVoiceActive(false);
      setVoiceStatus("Could not start voice.");
      setError(
        err instanceof ApiError
          ? err.message
          : "Couldn't connect to voice mode. Check microphone permission and try again.",
      );
    } finally {
      setIsConnectingVoice(false);
    }
  }, [fetchToken]);

  const stopVoice = React.useCallback(async () => {
    const room = roomRef.current;
    if (!room) return;

    setIsStoppingVoice(true);
    try {
      // Unpublish (not disconnect) first — this ends the agent's audio stream, which
      // already flushes/finalizes any in-progress speech (agent.py's forward_frames()
      // calls vad_stream.end_input() when the stream ends), so a transcript for
      // whatever was just said still arrives even though the user hit Stop mid-utterance.
      if (microphoneTrackRef.current) {
        const track = microphoneTrackRef.current;
        microphoneTrackRef.current = null;
        await room.localParticipant.unpublishTrack(
          track,
          /* stopOnUnpublish */ true,
        );
      }

      if (utteranceInFlightRef.current) {
        setVoiceStatus("Finishing up — transcribing your answer...");
        await new Promise<void>((resolve) => {
          pendingStopResolveRef.current = resolve;
          setTimeout(resolve, STOP_WAIT_MS);
        });
        pendingStopResolveRef.current = null;
      }

      console.trace("[voice] disconnect call site: stopVoice (manual or auto)");
      roomRef.current = null;
      await room.disconnect();
    } finally {
      setIsStoppingVoice(false);
      setIsVoiceActive(false);
      setVoiceStatus("Voice stopped.");
    }
  }, []);

  React.useEffect(() => {
    // Best-effort: a hard page reload/close skips React's async unmount cleanup below,
    // which can leave the room connected server-side under this user's identity — the
    // next "Start Voice" then races that zombie connection. pagehide fires reliably
    // before unload (including bfcache navigations), so disconnect there too.
    function disconnectNow() {
      microphoneTrackRef.current?.stop();
      microphoneTrackRef.current = null;
      const room = roomRef.current;
      roomRef.current = null;
      if (room) {
        console.trace("[voice] disconnect call site: unmount/pagehide cleanup");
        void room.disconnect();
      }
    }
    window.addEventListener("pagehide", disconnectNow);
    return () => {
      window.removeEventListener("pagehide", disconnectNow);
      disconnectNow();
    };
  }, []);

  const getLastAudioFeatures = React.useCallback((): AudioFeatures | null => {
    const features = lastAudioFeaturesRef.current;
    lastAudioFeaturesRef.current = null; // consume once — clear after reading
    return features;
  }, []);

  return {
    isVoiceActive,
    isConnectingVoice,
    isStoppingVoice,
    voiceStatus,
    error,
    startVoice,
    stopVoice,
    getLastAudioFeatures,
  };
}