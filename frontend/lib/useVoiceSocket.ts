"use client";

import * as React from "react";
import { API_URL } from "./api";
import { clearVoiceReady } from "./voiceReadiness";

const SAMPLE_RATE = 16000; // must match backend/lib/voice_ws.py's SAMPLE_RATE

export interface AudioFeatures {
  duration_seconds: number;
  word_timings: { word: string; start: number; end: number }[];
}

// Full-mode acoustic features (word timings + prosody + level) the backend attaches to
// a transcript. Undefined in transcript mode. Shape mirrors backend/lib/voice_ws.py.
export interface VoiceFeatures {
  word_timings?: { word: string; start: number; end: number }[];
  duration_seconds?: number;
  avg_db?: number;
  pitch_range_semitones?: number;
  /** Signal-to-noise, dB. The backend has always sent this; it was missing from this type, so
   *  it never reached the server's `_AgentAnalysis` and `voice_clarity` scored a constant ~85.3
   *  for every live-voice session. */
  snr_db?: number;
  /** Vocal arousal inputs for scenario-conditioned register scoring. */
  mean_pitch_hz?: number;
  intensity_variation_db?: number;
}

// Ceiling for how long stopVoice() waits for an in-flight transcript before giving up
// and disconnecting anyway — matches the product's stated max latency budget.
const STOP_WAIT_MS = 15000;

/**
 * Shared WebSocket voice-in hook — connects to a per-session voice-ws endpoint on the
 * FastAPI backend (see backend/lib/voice_ws.py), captures the mic as raw 16kHz PCM via
 * an AudioWorklet (public/voice-pcm-worklet.js), and forwards transcripts the backend
 * sends back to `onTranscript` — never auto-sends, callers decide what text state the
 * transcript fills.
 */
export function useVoiceSocket(
  getWsUrl: () => string | null,
  onTranscript: (text: string, features?: AudioFeatures | VoiceFeatures) => void,
  // Optional: growing preview text while the user keeps talking (backend/lib/voice_ws.py's
  // "partial" messages — only sent when the caller passed partial_interval_s server-side,
  // currently Conversation/Scenario). Called with "" when the real transcript lands, so
  // the caller can clear its preview state as the committed text takes over.
  onPartial?: (text: string) => void,
) {
  const [isVoiceActive, setIsVoiceActive] = React.useState(false);
  const [isConnectingVoice, setIsConnectingVoice] = React.useState(false);
  const [isStoppingVoice, setIsStoppingVoice] = React.useState(false);
  const [voiceStatus, setVoiceStatus] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);

  const socketRef = React.useRef<WebSocket | null>(null);
  const audioContextRef = React.useRef<AudioContext | null>(null);
  const workletNodeRef = React.useRef<AudioWorkletNode | null>(null);
  const micStreamRef = React.useRef<MediaStream | null>(null);
  const onTranscriptRef = React.useRef(onTranscript);
  onTranscriptRef.current = onTranscript;
  const onPartialRef = React.useRef(onPartial);
  onPartialRef.current = onPartial;
  // True from a "speaking" status until the matching transcript lands — lets stopVoice()
  // know whether there's anything worth waiting for, instead of always waiting/never
  // waiting.
  const utteranceInFlightRef = React.useRef(false);
  // Set by stopVoice() while it's waiting; the socket message handler resolves it early
  // the moment the transcript it's waiting for actually arrives.
  const pendingStopResolveRef = React.useRef<(() => void) | null>(null);
  // Stores the audio features from the most recent transcript — caller reads this
  // via getLastAudioFeatures() before clearing it on message send.
  const lastAudioFeaturesRef = React.useRef<AudioFeatures | null>(null);

  const teardownAudio = React.useCallback(() => {
    workletNodeRef.current?.disconnect();
    workletNodeRef.current = null;
    micStreamRef.current?.getTracks().forEach((track) => track.stop());
    micStreamRef.current = null;
    if (audioContextRef.current && audioContextRef.current.state !== "closed") {
      void audioContextRef.current.close();
    }
    audioContextRef.current = null;
  }, []);

  const startVoice = React.useCallback(async () => {
    if (socketRef.current) return;

    const wsUrl = getWsUrl();
    if (!wsUrl) {
      setError("No active session to start voice mode on.");
      return;
    }

    setError(null);
    setIsConnectingVoice(true);
    setVoiceStatus("Connecting voice...");
    utteranceInFlightRef.current = false;

    let socket: WebSocket | null = null;
    try {
      socket = new WebSocket(wsUrl);
      socket.binaryType = "arraybuffer";

      socket.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data as string);
          if (data.type === "status") {
            if (data.status === "speaking") utteranceInFlightRef.current = true;
            return;
          }
          if (data.type === "partial") {
            if (typeof data.text === "string") onPartialRef.current?.(data.text);
            return;
          }
          if (data.type !== "transcript") return;
          const text: string = data.text;
          utteranceInFlightRef.current = false;
          pendingStopResolveRef.current?.();
          onPartialRef.current?.(""); // clear the live preview — the real text is landing now
          if (!text) return;

          // backend/lib/voice_ws.py sends either:
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
          console.error("Failed to parse voice socket message:", err);
        }
      };

      await new Promise<void>((resolve, reject) => {
        if (!socket) return reject(new Error("Socket not created"));
        socket.onopen = () => resolve();
        socket.onerror = () => reject(new Error("Voice socket failed to connect"));
        socket.onclose = (event) => {
          setIsVoiceActive(false);
          setVoiceStatus("Voice disconnected.");
          if (event.code !== 1000) reject(new Error("Voice socket closed before it connected"));
        };
      });

      // Once open, onclose should only affect running-session state, not reject startVoice again.
      // Logged unconditionally (not just on an unexpected code) so an early/abnormal
      // disconnect shows up in devtools instead of silently doing nothing.
      socket.onclose = (event) => {
        const expected = event.code === 1000;
        if (!expected) {
          console.warn("[voice] socket closed unexpectedly — code:", event.code, "reason:", event.reason || "(none)");
          // Tear the capture side down too. Without this the socket was cleared from the UI's
          // point of view but not from the hook's: socketRef still held the dead socket, so
          // startVoice()'s `if (socketRef.current) return` guard made "Tap to Record" a no-op
          // and the session could not be restarted. The AudioWorklet also kept pushing PCM into
          // a closed socket, and the mic indicator stayed lit.
          if (socketRef.current === socket) {
            socketRef.current = null;
            teardownAudio();
          }
          utteranceInFlightRef.current = false;
          // stopVoice() may be parked on this; release it rather than making it serve the full
          // 15s timeout for a transcript that is never coming.
          pendingStopResolveRef.current?.();
        }
        setIsVoiceActive(false);
        setVoiceStatus(
          expected ? "Voice disconnected." : "Voice disconnected — tap the mic to start again.",
        );
      };

      let micStream: MediaStream;
      try {

        // 1st time prompts only else prev-suggestion used.
        micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      } catch (err) {
        clearVoiceReady(); // mic actually failed mid-session — don't trust the cached "ready" state
        throw err;
      }
      micStreamRef.current = micStream;

      const audioContext = new AudioContext({ sampleRate: SAMPLE_RATE });
      audioContextRef.current = audioContext;
      await audioContext.audioWorklet.addModule("/voice-pcm-worklet.js");

      const source = audioContext.createMediaStreamSource(micStream);
      const workletNode = new AudioWorkletNode(audioContext, "voice-pcm-processor");
      workletNodeRef.current = workletNode;
      let droppedChunkLogged = false;
      workletNode.port.onmessage = (event: MessageEvent<ArrayBuffer>) => {
        if (socketRef.current?.readyState === WebSocket.OPEN) {
          socketRef.current.send(event.data);
        } else if (!droppedChunkLogged) {
          // Log once, not per-chunk — this is the tell that the socket left OPEN
          // (closing/closed) while the mic is still capturing.
          droppedChunkLogged = true;
          console.warn(
            "[voice] dropping audio chunk — socket readyState:",
            socketRef.current?.readyState,
          );
        }
      };
      // Route through a muted gain node rather than leaving the worklet unconnected —
      // some browsers only keep calling an AudioWorkletNode's process() while it's part
      // of a graph that reaches the destination. Gain 0 means silent, no mic monitoring/echo.
      const mute = audioContext.createGain();
      mute.gain.value = 0;
      source.connect(workletNode);
      workletNode.connect(mute);
      mute.connect(audioContext.destination);

      socketRef.current = socket;
      setIsVoiceActive(true);
      setVoiceStatus("Voice connected. Microphone is active.");
    } catch (err) {
      console.error("[voice] failed to start voice:", err);
      teardownAudio();
      if (socket) {
        console.trace("[voice] disconnect call site: startVoice catch block");
        socket.close();
      }
      socketRef.current = null;
      setIsVoiceActive(false);
      setVoiceStatus("Could not start voice.");
      setError(
        err instanceof Error
          ? err.message
          : "Couldn't connect to voice mode. Check microphone permission and try again.",
      );
    } finally {
      setIsConnectingVoice(false);
    }
  }, [getWsUrl, teardownAudio]);

  const stopVoice = React.useCallback(async () => {
    const socket = socketRef.current;
    if (!socket) return;

    setIsStoppingVoice(true);
    try {
      // Stop capturing first — but that alone means the backend's VAD will never see
      // the silence it needs to naturally detect end-of-speech (no more audio is ever
      // coming). So if an utterance is mid-flight, explicitly tell the backend to flush
      // it now, while the socket is still open enough to send the transcript back —
      // waiting for close() to do it would be too late (see backend/lib/voice_ws.py's
      // serve()).
      teardownAudio();

      if (utteranceInFlightRef.current) {
        setVoiceStatus("Finishing up — transcribing your answer...");
        if (socket.readyState === WebSocket.OPEN) {
          socket.send(JSON.stringify({ type: "stop" }));
        }
        await new Promise<void>((resolve) => {
          pendingStopResolveRef.current = resolve;
          setTimeout(resolve, STOP_WAIT_MS);
        });
        pendingStopResolveRef.current = null;
      }

      socketRef.current = null;
      console.trace("[voice] disconnect call site: stopVoice (manual)");
      socket.close(1000);
    } finally {
      onPartialRef.current?.("");
      setIsStoppingVoice(false);
      setIsVoiceActive(false);
      setVoiceStatus("Voice stopped.");
    }
  }, [teardownAudio]);

  React.useEffect(() => {
    // Best-effort: a hard page reload/close skips React's async unmount cleanup below,
    // which can leave the socket open server-side — the next "Start Voice" then races
    // that zombie connection. pagehide fires reliably before unload (including bfcache
    // navigations), so disconnect there too.
    function disconnectNow() {
      teardownAudio();
      const socket = socketRef.current;
      socketRef.current = null;
      if (socket) {
        console.trace("[voice] disconnect call site: unmount/pagehide cleanup");
        socket.close(1000);
      }
    }
    window.addEventListener("pagehide", disconnectNow);
    return () => {
      window.removeEventListener("pagehide", disconnectNow);
      disconnectNow();
    };
  }, [teardownAudio]);

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

export function buildVoiceWsUrl(path: string): string {
  return `${API_URL.replace(/^http/, "ws")}${path}`;
}
