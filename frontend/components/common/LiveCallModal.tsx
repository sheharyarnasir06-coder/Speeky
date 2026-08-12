"use client";

import * as React from "react";
import {
  LiveKitRoom,
  RoomAudioRenderer,
  VideoTrack,
  useVoiceAssistant,
  useLocalParticipant,
  useMultibandTrackVolume,
  useTranscriptions,
  type TrackReference,
} from "@livekit/components-react";
import type { LocalAudioTrack } from "livekit-client";
import {
  Mic,
  MicOff,
  PanelRightClose,
  PanelRightOpen,
  PhoneOff,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { fetchLiveCallToken, type LiveCallFeature } from "@/lib/liveCall";
import { stopCurrent } from "@/lib/tts";

const STATE_LABELS: Record<string, string> = {
  connecting: "Connecting…",
  initializing: "Connecting…",
  listening: "Listening…",
  thinking: "Thinking…",
  speaking: "Speaking…",
  disconnected: "Disconnected",
};

const ORB_BANDS = 4;

// Transcript panel (video mode) caps to the last N messages overall
const MAX_TRANSCRIPT_MESSAGES = 2;
const TRANSCRIPT_OPACITY_STEPS = [1, 0.5];

interface LiveCallModalProps {
  feature: LiveCallFeature;
  sessionId: string;
  open: boolean;
  onClose: () => void;
  /** "End Session" — finalize + show the feature's normal feedback report.
   *
   * Optional: when omitted the button is not rendered. Public Speaking's Q&A has no such
   * action, because the *agent* finalizes it — dispatch.py calls submit_qa_response itself once
   * the answer satisfies the relevance gate. A second, client-side finaliser would race it. */
  onEndSession?: () => void | Promise<void>;
  /** "End Call" — just hang up; the call's turns already persisted into the
   * session's normal history as they happened, so the user can keep going by
   * text/push-to-talk with full context. */
  onCallEnded?: () => void;
  /** Header text. Defaults to "Live Call". */
  title?: string;
  /** Rendered beside the avatar in the video layout. Omit for the audio-first features, whose
   *  "self" side is the orb driven by the local mic — Public Speaking passes a camera, because
   *  watching your own delivery while being questioned is most of what its Q&A is for. */
  selfView?: React.ReactNode;
}

/**
 * Shared Live Call UI with background + orb are a CSS-only ambient visualization
 * built from the app's own --primary/--accent theme
 * tokens, so it's themed automatically in both light and dark mode.
 */
export function LiveCallModal({
  feature,
  sessionId,
  open,
  onClose,
  onEndSession,
  onCallEnded,
  title = "Live Call",
  selfView,
}: LiveCallModalProps) {
  const [connection, setConnection] = React.useState<{
    token: string;
    url: string;
  } | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [connecting, setConnecting] = React.useState(false);
  const [endingSession, setEndingSession] = React.useState(false);
  // Live, not one-shot — mirrors useVoiceAssistant's state directly (via
  // setAgentConnecting, passed straight down as a stable setState reference) so the
  // connect sound and the "Connecting…" blink can never desync from what's on screen.
  const [agentConnecting, setAgentConnecting] = React.useState(true);
  // Whether an avatar video track is live — widens the modal into the side-by-side
  // layout once true. Starts false (portrait/audio sizing) since a Bey avatar isn't
  // known to exist until its video track actually arrives a few seconds into the call.
  const [hasAvatarVideo, setHasAvatarVideo] = React.useState(false);
  // Video-mode-only: hides the transcript panel and re-centers/grows the video pane.
  // Owned here (not lifted via a callback like the two above) since the toggle button
  // itself lives in this component's header, not inside LiveCallControls.
  const [transcriptCollapsed, setTranscriptCollapsed] = React.useState(false);

  React.useEffect(() => {
    if (!open) {
      setConnection(null);
      setError(null);
      setAgentConnecting(true);
      setHasAvatarVideo(false);
      setTranscriptCollapsed(false);
      return;
    }

    // Live Call owns the mic/speaker from here on.
    stopCurrent();
    let cancelled = false;
    setConnecting(true);
    setError(null);
    setAgentConnecting(true);
    setHasAvatarVideo(false);
    setTranscriptCollapsed(false);
    fetchLiveCallToken(feature, sessionId)
      .then((result) => {
        if (!cancelled) setConnection({ token: result.token, url: result.url });
      })
      .catch((err) => {
        if (!cancelled) {
          setError(
            err instanceof Error ? err.message : "Couldn't start the call.",
          );
        }
      })
      .finally(() => {
        if (!cancelled) setConnecting(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, feature, sessionId]);

  const isConnectingSound =
    open && !error && (connecting || !connection || agentConnecting);
  React.useEffect(() => {
    if (!isConnectingSound) return;
    const audio = new Audio("/sounds/livecall-connect.mp3");
    audio.loop = true;
    void audio.play().catch(() => {
      // Autoplay blocked or file missing — silently skip, no dead-air regression.
    });
    return () => {
      audio.pause();
      audio.currentTime = 0;
    };
  }, [isConnectingSound]);

  if (!open) return null;

  async function handleEndSession() {
    if (!onEndSession) return;
    setEndingSession(true);
    try {
      await onEndSession();
    } finally {
      setEndingSession(false);
      setConnection(null);
      onClose();
    }
  }

  function handleEndCall() {
    setConnection(null);
    onClose();
    onCallEnded?.();
  }

  return (
    <div
      className={cn(
        "fixed inset-0 z-50 flex items-end justify-center bg-black/60 backdrop-blur-sm sm:items-center",
        !hasAvatarVideo && "sm:p-4",
      )}
    >
      <div
        className={cn(
          "flex h-[100vh] w-full flex-col overflow-hidden bg-[radial-gradient(ellipse_at_50%_10%,hsl(var(--primary)/0.28),hsl(var(--background))_65%)]",
          // Video mode fills the whole viewport at every size — no cap, no card
          // chrome (rounded corners/border/shadow would show the backdrop peeking
          // rather than just resized). Audio-only keeps today's small centered card.
          !hasAvatarVideo &&
            "sm:h-[85vh] sm:max-h-[85vh] sm:w-[90vw] sm:max-w-md sm:rounded-2xl sm:border sm:border-border sm:shadow-xl md:w-3/5 md:max-w-2xl lg:w-1/2 lg:max-w-3xl",
        )}
      >
        <div className="flex shrink-0 items-center justify-between px-4 py-3 sm:px-5">
          <p className="text-sm font-semibold text-foreground">{title}</p>
          <div className="flex items-center gap-1">
            {hasAvatarVideo ? (
              <button
                type="button"
                onClick={() => setTranscriptCollapsed((prev) => !prev)}
                aria-pressed={transcriptCollapsed}
                aria-label={
                  transcriptCollapsed ? "Show transcript" : "Hide transcript"
                }
                title={
                  transcriptCollapsed ? "Show transcript" : "Hide transcript"
                }
                className="rounded-lg p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
              >
                {transcriptCollapsed ? (
                  <PanelRightOpen className="h-5 w-5" aria-hidden="true" />
                ) : (
                  <PanelRightClose className="h-5 w-5" aria-hidden="true" />
                )}
              </button>
            ) : null}
            <button
              type="button"
              onClick={handleEndCall}
              aria-label="Close"
              className="rounded-lg p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            >
              <X className="h-5 w-5" aria-hidden="true" />
            </button>
          </div>
        </div>

        {error ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-3 p-6 text-center">
            <p className="text-sm text-danger">{error}</p>
            <Button size="sm" variant="outline" onClick={onClose}>
              Close
            </Button>
          </div>
        ) : connecting || !connection ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-3 p-6">
            <span
              className="h-8 w-8 animate-spin rounded-full border-2 border-current border-t-transparent text-muted-foreground"
              aria-hidden="true"
            />
            <p className="text-sm text-muted-foreground animate-pulse">
              Connecting…
            </p>
          </div>
        ) : (
          <LiveKitRoom
            token={connection.token}
            serverUrl={connection.url}
            connect
            audio
            video={false}
            className="flex flex-1 flex-col sm:overflow-y-auto"
            onDisconnected={() => setConnection(null)}
          >
            <RoomAudioRenderer />
            <LiveCallControls
              endingSession={endingSession}
              onEndSession={onEndSession ? () => void handleEndSession() : undefined}
              onEndCall={handleEndCall}
              onConnectingChange={setAgentConnecting}
              onVideoChange={setHasAvatarVideo}
              transcriptCollapsed={transcriptCollapsed}
              selfView={selfView}
            />
          </LiveKitRoom>
        )}
      </div>
    </div>
  );
}

function LiveCallControls({
  endingSession,
  onEndSession,
  onEndCall,
  onConnectingChange,
  onVideoChange,
  transcriptCollapsed,
  selfView,
}: {
  endingSession: boolean;
  /** Undefined when the feature has no client-side finaliser; the button is then omitted. */
  onEndSession?: () => void;
  onEndCall: () => void;
  /** Kept in sync with every connecting/initializing transition (not one-shot) so
   * the modal's connect sound + "Connecting…" blink always mirror the real state. */
  onConnectingChange: (connecting: boolean) => void;
  /** Kept in sync with whether an avatar video track is live, so the modal can
   * widen into the side-by-side layout once one actually appears. */
  onVideoChange: (hasVideo: boolean) => void;
  transcriptCollapsed: boolean;
  selfView?: React.ReactNode;
}) {
  const { state, audioTrack, videoTrack, agent } = useVoiceAssistant();
  const { localParticipant, isMicrophoneEnabled, microphoneTrack } =
    useLocalParticipant();
  const localMicTrack = microphoneTrack?.track as LocalAudioTrack | undefined;
  const isAgentTurn = state === "speaking" || state === "thinking";
  const isConnectingState = state === "connecting" || state === "initializing";

  React.useEffect(() => {
    onConnectingChange(isConnectingState);
  }, [isConnectingState, onConnectingChange]);

  // Synced during render, not in an effect: the parent's `hasAvatarVideo` sizes the
  // outer card (small audio modal vs. full-viewport video layout), while this
  // component's own return already forks into the wide band1/band2 JSX the instant
  // `videoTrack` is truthy. An effect-based sync lags one commit behind, so for one
  // frame the wide layout painted inside the still-small card — squeezing band 2
  // (status text, buttons) into too little space right as "Listening…" first showed.
  // Calling the parent setter directly in the render body (React's documented
  // "adjusting state when a prop changes" pattern) keeps both in the same commit.
  const hasVideoNow = !!videoTrack;
  const [reportedVideo, setReportedVideo] = React.useState(hasVideoNow);
  if (reportedVideo !== hasVideoNow) {
    setReportedVideo(hasVideoNow);
    onVideoChange(hasVideoNow);
  }

  async function handleInterrupt() {
    if (!agent) return;
    try {
      await localParticipant.performRpc({
        destinationIdentity: agent.identity,
        method: "interrupt_agent",
        payload: "",
      });
    } catch {
      // Best-effort — a missed interrupt just means the agent keeps talking a beat longer.
    }
  }

  const statusLabel = (
    <p
      role="status"
      aria-live="polite"
      className={cn(
        "text-sm text-muted-foreground",
        isConnectingState && "animate-pulse",
      )}
    >
      {STATE_LABELS[state] ?? "Connected"}
    </p>
  );

  const jumpInButton =
    state === "speaking" ? (
      <button
        type="button"
        onClick={() => void handleInterrupt()}
        className="rounded-full border-0 bg-gradient-to-r from-primary to-accent px-3 py-1 text-xs font-medium text-primary-foreground shadow-sm transition-all duration-fast ease-spring hover:-translate-y-0.5 hover:shadow-md active:scale-95"
      >
        Jump in
      </button>
    ) : null;

  const controlsRow = (
    <div className="flex items-center gap-5">
      <button
        type="button"
        onClick={() =>
          void localParticipant.setMicrophoneEnabled(!isMicrophoneEnabled)
        }
        aria-pressed={isMicrophoneEnabled}
        aria-label={
          isMicrophoneEnabled ? "Mute microphone" : "Unmute microphone"
        }
        className={cn(
          "flex h-12 w-12 shrink-0 items-center justify-center rounded-full transition-all duration-fast ease-spring active:scale-95 sm:h-14 sm:w-14",
          isMicrophoneEnabled
            ? "bg-gradient-to-br from-accent to-accent/80 text-accent-foreground shadow-md hover:-translate-y-0.5 hover:shadow-lg"
            : "border border-danger bg-danger/10 text-danger hover:-translate-y-0.5",
        )}
      >
        {isMicrophoneEnabled ? (
          <Mic className="h-5 w-5" aria-hidden="true" />
        ) : (
          <MicOff className="h-5 w-5" aria-hidden="true" />
        )}
      </button>
      <button
        type="button"
        onClick={onEndCall}
        aria-label="End call — keep chatting by text"
        title="End call — keep chatting by text"
        className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-danger to-danger/80 text-white shadow-md transition-all duration-fast ease-spring hover:-translate-y-0.5 hover:shadow-lg active:scale-95 sm:h-14 sm:w-14"
      >
        <PhoneOff className="h-5 w-5" aria-hidden="true" />
      </button>
    </div>
  );

  // Omitted entirely for features whose session is finalized server-side (Public Speaking's
  // Q&A) — a button that races the agent's own submit is worse than no button.
  const endSessionButton = onEndSession ? (
    <Button
      size="sm"
      variant="outline"
      loading={endingSession}
      onClick={onEndSession}
      className="w-full border-0 bg-gradient-to-r from-primary to-accent bg-[length:200%_200%] text-primary-foreground shadow-sm transition-all duration-fast ease-spring animate-gradient-shift hover:-translate-y-0.5 hover:shadow-md sm:w-auto"
    >
      End Session &amp; See Report
    </Button>
  ) : null;

  if (videoTrack) {
    // Full-viewport layout (LiveCallModal drops its card sizing once hasAvatarVideo is
    // true). Two height bands from sm: up — band 1 (video + transcript) ~72%, band 2
    // (all controls) ~28%, centered. Below sm, both bands fall back to today's
    // flexible, content-sized stacking (mobile keeps its own proportions on purpose;
    return (
      <div className="flex min-h-0 flex-1 flex-col">
        <div className="flex min-h-0 flex-1 flex-col sm:h-[72%] sm:flex-none sm:flex-row">
          <div
            className={cn(
              "flex min-h-0 items-center justify-center p-4 sm:p-6",
              transcriptCollapsed ? "flex-1" : "shrink-0 sm:w-[56%]",
            )}
          >
            <div
              className={cn(
                "relative",
                transcriptCollapsed ? "h-full w-full" : "w-full",
                // The self-view shares this pane rather than becoming a third top-level column,
                // so the transcript keeps its flex-1 width and the collapse toggle keeps working
                // untouched. Stacked on narrow screens, side by side once there is room.
                selfView && "flex flex-col gap-3 sm:flex-row sm:items-center",
              )}
            >
              {isAgentTurn ? (
                <div className="absolute left-1/2 bottom-0 z-10 -translate-x-1/2 translate-y-1/2">
                  <LiveCallOrb
                    size="sm"
                    state={state}
                    agentAudioTrack={audioTrack}
                    localMicTrack={localMicTrack}
                  />
                </div>
              ) : null}
              <VideoTrack
                trackRef={videoTrack}
                className={cn(
                  "rounded-2xl object-cover shadow-lg",
                  transcriptCollapsed && !selfView ? "h-full w-full" : "aspect-video w-full",
                  selfView && "min-w-0 flex-1",
                )}
              />
              {selfView ? (
                <div className="aspect-video min-w-0 flex-1 overflow-hidden rounded-2xl bg-black shadow-lg">
                  {selfView}
                </div>
              ) : null}
            </div>
          </div>
          {/* Stays mounted (CSS-hidden, not unmounted) when collapsed — the
              underlying LiveKit text-stream subscription doesn't replay history to a late subscriber, so unmounting/remounting this on every toggle showed a
              blank transcript on re-expand until the next new line arrived. */}
          <div
            className={cn(
              "flex min-h-0 flex-1 flex-col border-t-2 border-border p-4 sm:border-l-2 sm:border-t-0 sm:p-6",
              transcriptCollapsed && "hidden",
            )}
          >
            <LiveCallTranscriptPanel
              localIdentity={localParticipant.identity}
            />
          </div>
        </div>
        <div className="flex shrink-0 flex-col items-center justify-center gap-3 border-t-2 border-border p-4 sm:h-[28%] sm:p-6">
          <div className="flex w-full max-w-xs flex-col items-center gap-3 sm:max-w-sm">
            {statusLabel}
            {jumpInButton}
            {!isAgentTurn ? (
              <LiveCallOrb
                size="sm"
                state={state}
                agentAudioTrack={audioTrack}
                localMicTrack={localMicTrack}
              />
            ) : null}
            {controlsRow}
            {endSessionButton}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col p-4 sm:p-6">
      {/* Orb + status never scroll or shrink — always fully visible no matter how
          long the caption text below grows or how much vertical room the modal has. */}
      <div className="flex shrink-0 flex-col items-center gap-3 pt-2">
        <LiveCallOrb
          state={state}
          agentAudioTrack={audioTrack}
          localMicTrack={localMicTrack}
        />
        {statusLabel}
        {jumpInButton}
      </div>
      {/* Also shown here, not only in the video layout. `videoTrack` is the *agent's* camera, so
          gating the self-view on it meant that whenever the avatar was unavailable — no
          BEY_API_KEY, provider down, avatar start failed — the caller's own feed vanished too,
          even though it has nothing to do with the agent publishing. */}
      {selfView ? (
        <div className="mt-3 aspect-video w-full max-w-[240px] shrink-0 self-center overflow-hidden rounded-2xl bg-black shadow-lg">
          {selfView}
        </div>
      ) : null}

      <div className="mt-3 flex min-h-[4.5rem] flex-1 flex-col items-center justify-center overflow-y-auto">
        <LiveCallLastLines localIdentity={localParticipant.identity} />
      </div>

      <div className="flex shrink-0 flex-col items-center gap-3 pt-3">
        {controlsRow}
        {endSessionButton}
      </div>
    </div>
  );
}

/**
 * Multi-band-reactive ambient orb — swaps between --accent (you're talking)
 * and --primary (agent talking); each of the 4 concentric layers is bound to
 * a different frequency band (low band on the outer glow, high band on the
 * core), so it visibly reshapes with pitch/timbre, not just loudness. Pure
 * CSS transforms off real Web Audio frequency data (useMultibandTrackVolume)
 * — no canvas, no WebGL, no third-party shader.
 */
function LiveCallOrb({
  state,
  agentAudioTrack,
  localMicTrack,
  size = "lg",
}: {
  state: string;
  agentAudioTrack?: TrackReference;
  localMicTrack?: LocalAudioTrack;
  /** "sm" is the turn-indicator badge shown alongside an avatar video; "lg"
   * (default) is the standalone orb shown when no avatar video is active. */
  size?: "lg" | "sm";
}) {
  const isAgentTurn = state === "speaking" || state === "thinking";
  const activeTrack = isAgentTurn ? agentAudioTrack : localMicTrack;
  const rawBands = useMultibandTrackVolume(activeTrack, {
    bands: ORB_BANDS,
    updateInterval: 50,
    // Library defaults (loPass:100/hiPass:600 bins, no smoothingTimeConstant override)
    // sit above most vocal energy and inherit the Web Audio AnalyserNode's spec
    // default smoothingTimeConstant of 0.8 — heavy frame-to-frame damping, which is
    // why the orb barely moved. Lower bins = more low/mid vocal range; low smoothing
    // = the orb actually snaps to what's being said instead of crawling toward it.
    loPass: 15,
    hiPass: 350,
    analyserOptions: { fftSize: 2048, smoothingTimeConstant: 0.15 },
  });
  const [bass, low, high, treble] =
    rawBands.length === ORB_BANDS
      ? rawBands.map((v) => Math.min(v, 1))
      : [0, 0, 0, 0];

  const colorClass = isAgentTurn ? "bg-primary" : "bg-accent";
  const colorVar = isAgentTurn ? "--primary" : "--accent";
  // Radial alpha mask instead of relying on blur alone for softness — flat blurred
  // discs stacked on each other mixed into a hazy, muddy-looking blob at their shared
  // edges. A true fade-to-transparent center-out reads as a clean glow instead, and
  // matches the radial-gradient glow language already used elsewhere in this app
  // (globals.css's own hover glows, this modal's own backdrop gradient).
  const glowMask = {
    maskImage: "radial-gradient(circle, black 0%, black 35%, transparent 78%)",
    WebkitMaskImage:
      "radial-gradient(circle, black 0%, black 35%, transparent 78%)",
  } as const;

  return (
    <div
      className={cn(
        "relative flex shrink-0 items-center justify-center",
        size === "lg"
          ? "h-28 w-28 sm:h-44 sm:w-44 md:h-52 md:w-52"
          : "h-14 w-14 sm:h-16 sm:w-16",
      )}
    >
      {/* Bass — outermost, softest, widest swing */}
      <div
        className={cn(
          "absolute inset-0 rounded-full blur-3xl transition-[background-color] duration-700 ease-out",
          colorClass,
        )}
        style={{
          ...glowMask,
          opacity: 0.28 + bass * 0.5,
          transform: `scale(${0.85 + bass * 0.45})`,
        }}
      />
      {/* Low-mid */}
      <div
        className={cn(
          "absolute h-4/5 w-4/5 rounded-full blur-2xl transition-[background-color] duration-500 ease-out",
          colorClass,
        )}
        style={{
          ...glowMask,
          opacity: 0.32 + low * 0.45,
          transform: `scale(${0.88 + low * 0.32})`,
        }}
      />
      {/* High-mid */}
      <div
        className={cn(
          "absolute h-3/5 w-3/5 rounded-full blur-xl transition-[background-color] duration-500 ease-out",
          colorClass,
        )}
        style={{
          ...glowMask,
          opacity: 0.4 + high * 0.4,
          transform: `scale(${0.9 + high * 0.22})`,
        }}
      />
      {/* Treble — core, sharpest response, real glow via box-shadow */}
      <div
        className={cn(
          "relative h-2/5 w-2/5 rounded-full transition-[background-color] duration-700 ease-out",
          colorClass,
        )}
        style={{
          transform: `scale(${0.94 + treble * 0.22})`,
          boxShadow: `0 0 ${30 + treble * 40}px ${6 + treble * 12}px hsl(var(${colorVar}) / ${0.35 + treble * 0.4})`,
        }}
      />
    </div>
  );
}

type TranscriptSegment = ReturnType<typeof useTranscriptions>[number];

/** Tracks a hand-off between two values keyed by id: the outgoing one stays
 * mounted just long enough to play its fade-out-up exit, then drops. */
function useFadeHandoff(value: TranscriptSegment | null) {
  const [{ current, exiting }, setPair] = React.useState<{
    current: TranscriptSegment | null;
    exiting: TranscriptSegment | null;
  }>({ current: value, exiting: null });
  const idRef = React.useRef(value?.streamInfo.id ?? null);

  React.useEffect(() => {
    const nextId = value?.streamInfo.id ?? null;
    if (nextId === idRef.current) {
      // Same segment, just more text streamed in (LiveKit paces long agent replies
      // out word-by-word under one stream id) — update in place, no fade handoff.
      // Without this branch `current` freezes on whatever text existed at the first
      // render for this id, which is why only the first word or two ever showed.
      setPair((prev) => ({ ...prev, current: value }));
      return;
    }
    idRef.current = nextId;
    setPair((prev) => ({ current: value, exiting: prev.current }));
    const timer = setTimeout(
      () => setPair((prev) => ({ ...prev, exiting: null })),
      320,
    );
    return () => clearTimeout(timer);
  }, [value]);

  return { current, exiting };
}

function FadingLine({
  segment,
  label,
  className,
}: {
  segment: TranscriptSegment;
  label: string;
  className?: string;
}) {
  return (
    <p className={cn("text-sm", className)}>
      <span className="mr-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {label}
      </span>
      {segment.text}
    </p>
  );
}

/** One speaker's slot: exiting line (fading/drifting up, absolutely
 * positioned so it doesn't push layout) behind the incoming line (fading up
 * into its normal position) — a real hand-off, not an instant swap. */
function LiveCallSpeakerSlot({
  segment,
  label,
  className,
}: {
  segment: TranscriptSegment | null;
  label: string;
  className?: string;
}) {
  const { current, exiting } = useFadeHandoff(segment);
  if (!current && !exiting) return null;

  return (
    <div className="relative w-full">
      {exiting ? (
        <div className="pointer-events-none absolute inset-x-0 bottom-full">
          <FadingLine
            key={exiting.streamInfo.id}
            segment={exiting}
            label={label}
            className={cn("animate-fade-out-up", className)}
          />
        </div>
      ) : null}
      {current ? (
        <FadingLine
          key={current.streamInfo.id}
          segment={current}
          label={label}
          className={cn("animate-fade-up", className)}
        />
      ) : null}
    </div>
  );
}

/**
 * Just the most recent AI line and most recent your-line, not a transcript or chat-log.
 */
function LiveCallLastLines({ localIdentity }: { localIdentity: string }) {
  const transcriptions = useTranscriptions();

  const latestFor = (matchLocal: boolean) => {
    let latest: TranscriptSegment | null = null;
    for (const seg of transcriptions) {
      const isLocal = seg.participantInfo.identity === localIdentity;
      if (isLocal !== matchLocal) continue;
      if (!latest || seg.streamInfo.timestamp > latest.streamInfo.timestamp)
        latest = seg;
    }
    return latest;
  };

  const latestAgent = latestFor(false);
  const latestUser = latestFor(true);

  if (!latestAgent && !latestUser) return null;

  return (
    <div className="flex w-full max-w-sm flex-col items-center gap-1.5 text-center sm:max-w-md md:max-w-xl lg:max-w-2xl">
      <LiveCallSpeakerSlot
        segment={latestAgent}
        label="Coach"
        className="text-foreground"
      />
      <LiveCallSpeakerSlot
        segment={latestUser}
        label="You"
        className="text-muted-foreground"
      />
    </div>
  );
}

// @livekit/components-core's setupTextStream gives each streamed chunk of an
// in-progress message a NEW streamInfo.id — it coalesces them into one array entry
// itself, matched by this attribute (confirmed in its source), but streamInfo.id on
// that entry still changes on every chunk. Keying rows by streamInfo.id therefore
// remounted the row on every word, which is why neither animation looked like it was
// running and why an in-progress reply could visually read as several messages —
// this attribute is the one part of a segment's identity that stays stable for its
// whole lifetime, so it's what dedupe/keying below use instead.
const TRANSCRIPTION_SEGMENT_ID_ATTR = "lk.segment_id";
function transcriptKey(segment: TranscriptSegment): string {
  return (
    segment.streamInfo.attributes?.[TRANSCRIPTION_SEGMENT_ID_ATTR] ??
    segment.streamInfo.id
  );
}

function speakerMeta(segment: TranscriptSegment, localIdentity: string) {
  const isLocal = segment.participantInfo.identity === localIdentity;
  return {
    label: isLocal ? "You" : "Coach",
    className: isLocal ? "text-muted-foreground" : "text-foreground",
  };
}

/** Caps to the last `max` distinct messages, and separately holds whichever ones just
 * aged out of that cap for exactly as long as their exit animation runs (320ms, same
 * duration as the fade-out-up keyframe below) — generalizes useFadeHandoff's single
 * current/exiting slot above into an N-item list. */
function useCappedTranscript(transcriptions: TranscriptSegment[], max: number) {
  const visible = React.useMemo(() => {
    // Defensive dedupe on top of the library's own coalescing — keep only the latest update per stable segment id before capping, so a duplicate/partial entry can never eat one of the N slots meant for a distinct message.
    const latestById = new Map<string, TranscriptSegment>();
    for (const segment of transcriptions) {
      const id = transcriptKey(segment);
      const existing = latestById.get(id);
      if (
        !existing ||
        segment.streamInfo.timestamp >= existing.streamInfo.timestamp
      ) {
        latestById.set(id, segment);
      }
    }
    return [...latestById.values()]
      .sort((a, b) => a.streamInfo.timestamp - b.streamInfo.timestamp)
      .slice(-max);
  }, [transcriptions, max]);

  const prevVisibleRef = React.useRef<TranscriptSegment[]>([]);
  const [exiting, setExiting] = React.useState<TranscriptSegment[]>([]);

  React.useEffect(() => {
    const prevVisible = prevVisibleRef.current;
    prevVisibleRef.current = visible;
    const currentIds = new Set(visible.map(transcriptKey));
    const dropped = prevVisible.filter(
      (s) => !currentIds.has(transcriptKey(s)),
    );
    if (dropped.length === 0) return;

    setExiting((prev) => [...prev, ...dropped]);
    const timer = setTimeout(() => {
      const droppedIds = new Set(dropped.map(transcriptKey));
      setExiting((prev) =>
        prev.filter((s) => !droppedIds.has(transcriptKey(s))),
      );
    }, 320);
    return () => clearTimeout(timer);
  }, [visible]);

  return { visible, exiting };
}

/**
 * Video-mode-only transcript: capped to the last MAX_TRANSCRIPT_MESSAGES (newest at
 * the bottom, auto-scrolling as new lines arrive). Older visible messages progressively
 * dim via TRANSCRIPT_OPACITY_STEPS (a plain CSS transition on an inner wrapper — kept
 * off the outer animate-fade-up element on purpose: a running/fill-forward CSS
 * *animation* wins the cascade over an inline style on the same property, which is why
 * opacity dimming did nothing while animate-fade-up sat on the same node). A message
 * aging past the cap plays the same animate-fade-out-up exit the audio-only caption
 * hand-off uses (useFadeHandoff above) before it's actually removed.
 */
function LiveCallTranscriptPanel({ localIdentity }: { localIdentity: string }) {
  const transcriptions = useTranscriptions();
  const { visible, exiting } = useCappedTranscript(
    transcriptions,
    MAX_TRANSCRIPT_MESSAGES,
  );
  const scrollRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [visible]);

  return (
    <>
      <p className="mb-2 shrink-0 text-overline text-muted-foreground">
        Transcript
      </p>
      <div ref={scrollRef} className="min-h-0 flex-1 space-y-3 overflow-y-auto">
        {visible.length === 0 && exiting.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            Captions will appear here once the call starts.
          </p>
        ) : (
          <>
            {exiting.map((segment) => {
              const meta = speakerMeta(segment, localIdentity);
              return (
                <div
                  key={transcriptKey(segment)}
                  className="animate-fade-out-up"
                >
                  <FadingLine
                    segment={segment}
                    label={meta.label}
                    className={meta.className}
                  />
                </div>
              );
            })}
            {visible.map((segment, index) => {
              const age = visible.length - 1 - index; // 0 = newest
              const meta = speakerMeta(segment, localIdentity);
              return (
                <div key={transcriptKey(segment)} className="animate-fade-up">
                  <div
                    className="transition-opacity duration-500 ease-standard"
                    style={{
                      opacity:
                        TRANSCRIPT_OPACITY_STEPS[
                          Math.min(age, TRANSCRIPT_OPACITY_STEPS.length - 1)
                        ],
                    }}
                  >
                    <FadingLine
                      segment={segment}
                      label={meta.label}
                      className={meta.className}
                    />
                  </div>
                </div>
              );
            })}
          </>
        )}
      </div>
    </>
  );
}
