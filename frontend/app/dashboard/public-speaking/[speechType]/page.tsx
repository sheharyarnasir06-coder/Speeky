"use client";

import * as React from "react";
import dynamic from "next/dynamic";
import { useParams, useRouter } from "next/navigation";
import {
  ArrowLeft,
  CheckCircle,
  Clock,
  Lightbulb,
  ListOrdered,
  MessageCircleQuestion,
  Mic,
  Send,
  AlertCircle,
  Smile,
  Timer,
  Video,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { useVoiceReadinessGate } from "@/components/common/VoiceReadinessGate";
import { useCameraReadinessGate } from "@/components/common/CameraReadinessGate";
import { MilestoneCelebrationModal } from "@/components/dashboard/MilestoneCelebrationModal";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { FillerWordsScorecardSection } from "@/components/dashboard/public-speaking/FillerWordsScorecardSection";
import { DeliverySparkline } from "@/components/dashboard/public-speaking/DeliverySparkline";
// Static import is safe only because ./Panel is LiveKit-free — importing it from
// AvatarVideoPanel instead took this page's First Load from 140kB to 291kB.
import { Panel } from "@/components/dashboard/public-speaking/Panel";
/**
 * Lazy: @livekit/components-react is ~150kB and only a fraction of sessions open the
 * face-to-face Q&A at all. Imported statically it landed in this page's bundle for everyone,
 * taking First Load from 137kB to 288kB — the same mistake the MediaPipe loader avoids by
 * splitting the vision runtime into its own async chunk.
 *
 * ssr:false because LiveKit touches browser media APIs on import.
 */
const LiveCallModal = dynamic(
  () => import("@/components/common/LiveCallModal").then((m) => m.LiveCallModal),
  { ssr: false },
);
const IdleAudiencePanel = dynamic(
  () =>
    import("@/components/dashboard/public-speaking/IdleAudiencePanel").then(
      (m) => m.IdleAudiencePanel,
    ),
  { ssr: false },
);
import { ApiError } from "@/lib/api";
import {
  getPublicSpeakingSession,
  startPublicSpeakingSession,
  submitPublicSpeakingTurn,
  submitPublicSpeakingQa,
  type PublicSpeakingScorecard,
  type SpeechType,
} from "@/lib/publicSpeaking";
import { useSelfCamera } from "@/lib/useSelfCamera";
import { buildVoiceWsUrl, useVoiceSocket, type VoiceFeatures } from "@/lib/useVoiceSocket";
import { usePracticeTimePing } from "@/lib/usePracticeTimePing";
import { formatClock, useSpeechTimer } from "@/lib/useSpeechTimer";
import { useVideoAnalysis } from "@/lib/vision/useVideoAnalysis";
import type { GazeBucket } from "@/lib/vision/gaze";
import type { FramingState, VideoRejectionReason } from "@/lib/vision/types";

/** Short, live-overlay phrasing — terser than the calibration modal's copy, since this shows
 *  during active recording and must not compete with the transcript for attention. Framing
 *  takes priority over gaze: a bad gaze reading is meaningless until framing is fixed. */
const LIVE_FRAMING_HINTS: Partial<Record<FramingState, string>> = {
  too_close: "Move back a little",
  too_far: "Move a little closer",
  off_center: "Centre yourself in frame",
  shoulders_cropped: "Tilt your screen back",
};

const LIVE_GAZE_HINTS: Partial<Record<GazeBucket, string>> = {
  down: "Try looking up at the camera",
  up: "Try looking at the camera",
  side: "Try looking at the camera",
  offscreen: "You're out of frame",
};

/** Time-limit presets, in minutes. null is "No limit" — the untimed behaviour this feature had
 *  before, kept because rehearsing a speech you haven't finished writing is a real use. */
const TIME_LIMIT_OPTIONS: (number | null)[] = [null, 2, 3, 5, 10];

interface SpeechTypeConfig {
  label: string;
  description: string;
  ideal_wpm: string;
  /** Mirrors backend SPEECH_TYPES[...]["qa_enabled"]. Duplicated here only because the setup
   *  card must describe the flow BEFORE a session exists; once one does, the server's
   *  `qa_enabled` from /start is what the flow actually keys off. */
  qaEnabled: boolean;
  /** Preselected time limit, in minutes. */
  suggestedLimitMinutes: number;
  /** Shown as numbered steps on the setup card, so the shape of the session is known before
   *  the user commits to it — the Q&A in particular used to arrive unannounced. */
  flow: string[];
}

const DELIVERY_STEP = "Deliver your speech — pause and resume the mic as often as you like";

const SPEECH_TYPE_CONFIG: Record<string, SpeechTypeConfig> = {
  business_pitch: {
    label: "Business Pitch",
    description: "Structure: Hook → Problem → Solution → Ask",
    ideal_wpm: "130-160 WPM",
    qaEnabled: true,
    suggestedLimitMinutes: 5,
    flow: [
      "Deliver your pitch — pause and resume the mic as often as you like",
      "Field one impromptu question from the audience, straight after the pitch",
      "See your total score: 70% pitch delivery, 30% Q&A handling",
    ],
  },
  casual_event: {
    label: "Casual Event Speech",
    description: "Focus on warmth, storytelling, and emotional connection",
    ideal_wpm: "120-150 WPM",
    qaEnabled: false,
    suggestedLimitMinutes: 3,
    flow: [DELIVERY_STEP, "See your score: warmth, storytelling, pacing and delivery"],
  },
  motivational: {
    label: "Motivational Speech",
    description: "Prioritize energy, tone variation, and strategic pausing",
    ideal_wpm: "130-160 WPM",
    qaEnabled: false,
    suggestedLimitMinutes: 5,
    flow: [DELIVERY_STEP, "See your score: energy, tone variation, pacing and delivery"],
  },
  classroom: {
    label: "Classroom Presentation",
    description: "Include clear transitions and minimize filler words",
    ideal_wpm: "130-150 WPM",
    qaEnabled: true,
    suggestedLimitMinutes: 10,
    flow: [
      "Deliver your presentation — pause and resume the mic as often as you like",
      "Field one question from the class, straight after the presentation",
      "See your total score: 70% presentation, 30% Q&A handling",
    ],
  },
  ted_talk: {
    label: "TED-Style Talk",
    description: "Craft a narrative arc with personal stories",
    ideal_wpm: "130-150 WPM",
    qaEnabled: true,
    suggestedLimitMinutes: 10,
    flow: [
      "Deliver your talk — pause and resume the mic as often as you like",
      "Field one question from the audience, straight after the talk",
      "See your total score: 70% talk delivery, 30% Q&A handling",
    ],
  },
};

export default function PublicSpeakingSessionPage() {
  const params = useParams();
  const router = useRouter();
  const speechType = params.speechType as string;
  const config = SPEECH_TYPE_CONFIG[speechType] || SPEECH_TYPE_CONFIG.business_pitch;

  const [inputMode, setInputMode] = React.useState<"audio" | "text">("audio");
  // Opt-in, off by default, and only meaningful alongside voice. Enabling it routes Start
  // Session through the camera gate, which is what produces the gaze calibration; skip that and
  // the payload reports itself as uncalibrated and the results tile withholds its numbers.
  const [cameraEnabled, setCameraEnabled] = React.useState(false);
  const [textContent, setTextContent] = React.useState("");
  const [isSubmitting, setIsSubmitting] = React.useState(false);
  const [sessionId, setSessionId] = React.useState<string | null>(null);
  // Seeded from the local catalogue so the setup card can describe the flow before any session
  // exists, then replaced by the server's answer at /start — that is the authority, so a
  // scenario's flow can change backend-side without waiting on a frontend release.
  const [qaEnabled, setQaEnabled] = React.useState(config.qaEnabled);
  const [scorecard, setScorecard] = React.useState<any>(null);
  const [qaQuestion, setQaQuestion] = React.useState<string | null>(null);
  const [qaResponse, setQaResponse] = React.useState("");
  const [qaScore, setQaScore] = React.useState<any>(null);
  const [error, setError] = React.useState<string | null>(null);
  // Minutes, or null for no limit. Chosen at setup; never sent to the server, because the limit
  // only stops input — it does not enter scoring.
  const [timeLimitMinutes, setTimeLimitMinutes] = React.useState<number | null>(
    config.suggestedLimitMinutes,
  );
  // Latched by the timer. Nothing is submitted from inside the expiry callback — see the effect
  // below for why the stop and the submit have to be two separate steps.
  const [timeExpired, setTimeExpired] = React.useState(false);
  // Both avatar panels are opt-in. The Q&A one talks, so it is Q&A-only: during the speech it
  // would talk over the speaker and its voice would reach the mic feeding the audio scorer. The
  // backend refuses a "qa" token before qa_phase regardless.
  const [qaCallActive, setQaCallActive] = React.useState(false);
  // The speech-phase one is silent — no STT, LLM or TTS exist in that room — so it is presence
  // to speak to, with nothing to talk over and nothing listening. Gated on in_progress instead.
  const [idleAudienceActive, setIdleAudienceActive] = React.useState(false);

  const sessionIdRef = React.useRef<string | null>(null);
  sessionIdRef.current = sessionId;
  const textContentRef = React.useRef("");
  textContentRef.current = textContent;
  const voiceStartedAt = React.useRef<number | null>(null);
  const voiceDurationRef = React.useRef<number>(0);
  const featuresRef = React.useRef({
    has: false,
    word_timings: [] as { word: string; start: number; end: number }[],
    duration_seconds: 0,
    avg_db: undefined as number | undefined,
    pitch_range_semitones: 0,
    snr_db: undefined as number | undefined,
    mean_pitch_hz: undefined as number | undefined,
    intensity_variation_db: 0,
  });
  const getWsUrl = React.useCallback(() => {
    const id = sessionIdRef.current;
    if (!id) return null;
    return buildVoiceWsUrl(`/public-speaking/${id}/voice-ws`);
  }, []);

  // Live text is spliced directly into the (editable) textarea instead of a separate
  // preview line — but the textarea is editable at any time, so a naive splice risks
  // clobbering an in-progress edit. committedTextRef is the "locked" baseline (real,
  // finalized transcript text, or whatever the user typed); splicedPartialRef is the
  // live guess currently appended after it, or null when no live guess is showing.
  // Each update only touches the textarea if its current value still exactly matches
  // what we last spliced — the moment the user types anything, both callbacks back off
  // and leave their edit alone until the next utterance starts.
  const committedTextRef = React.useRef("");
  const splicedPartialRef = React.useRef<string | null>(null);

  const onPartial = React.useCallback((text: string) => {
    if (!text) return;
    setTextContent((current) => {
      const base = committedTextRef.current;
      const expected =
        splicedPartialRef.current === null ? base : `${base}${base ? " " : ""}${splicedPartialRef.current}`;
      if (current !== expected) return current; // user has edited — leave it alone
      if (splicedPartialRef.current === null) committedTextRef.current = current; // snapshot baseline
      splicedPartialRef.current = text;
      return `${committedTextRef.current}${committedTextRef.current ? " " : ""}${text}`;
    });
  }, []);

  const {
    isVoiceActive,
    isConnectingVoice,
    isStoppingVoice,
    voiceStatus,
    error: voiceError,
    startVoice,
    stopVoice,
  } = useVoiceSocket(
    getWsUrl,
    (text, features?: VoiceFeatures) => {
      setTextContent((prev) => {
        const base = committedTextRef.current;
        const expected =
          splicedPartialRef.current === null ? null : `${base}${base ? " " : ""}${splicedPartialRef.current}`;
        // Still showing our own live guess untouched? Replace it with the real text
        // instead of appending on top of the guess. Otherwise (no live guess, or the
        // user edited) fall back to the original append-to-whatever's-there behavior.
        const from = expected !== null && prev === expected ? base : prev;
        const next = from.trim() ? `${from.trim()} ${text}` : text;
        committedTextRef.current = next; // locked
        splicedPartialRef.current = null; // ready for the next utterance
        return next;
      });
      if (features) {
        const acc = featuresRef.current;
        if (features.word_timings) acc.word_timings.push(...features.word_timings);
        if (typeof features.duration_seconds === "number") acc.duration_seconds += features.duration_seconds;
        if (typeof features.avg_db === "number") acc.avg_db = features.avg_db;
        if (typeof features.pitch_range_semitones === "number")
          acc.pitch_range_semitones = Math.max(acc.pitch_range_semitones, features.pitch_range_semitones);
        // Worst SNR across the session, not the last one: a single noisy utterance is the
        // clarity problem worth surfacing, and taking the latest would hide it.
        if (typeof features.snr_db === "number")
          acc.snr_db = acc.snr_db === undefined ? features.snr_db : Math.min(acc.snr_db, features.snr_db);
        if (typeof features.mean_pitch_hz === "number") acc.mean_pitch_hz = features.mean_pitch_hz;
        if (typeof features.intensity_variation_db === "number")
          acc.intensity_variation_db = Math.max(
            acc.intensity_variation_db,
            features.intensity_variation_db,
          );
        acc.has = true;
      }
    },
    onPartial,
  );
  const { gate: voiceGate, runWithVoiceReadiness } = useVoiceReadinessGate({
    featureName: "Public Speaking Practice",
  });
  const {
    gate: cameraGate,
    runWithCameraReadiness,
    calibration,
  } = useCameraReadinessGate({ featureName: "delivery analysis" });

  const {
    isVideoActive,
    isStartingVideo,
    videoStatus,
    error: videoError,
    loadProgress,
    startVideo,
    stopVideo,
    videoRef,
    getVideoFeatures,
    liveFraming,
    liveGazeBucket,
    gazeScorable,
  } = useVideoAnalysis({ calibration: calibration ?? undefined });

  // Deliberately the plain getUserMedia hook, not useVideoAnalysis: the Q&A is not scored on
  // body language, and this one has no MediaPipe pipeline to compete with the call for CPU.
  const { videoRef: qaSelfVideoRef, error: qaSelfCameraError } = useSelfCamera(qaCallActive);

  const liveVisualHint = isVideoActive
    ? (LIVE_FRAMING_HINTS[liveFraming] ??
      (liveGazeBucket ? LIVE_GAZE_HINTS[liveGazeBucket] : undefined))
    : undefined;

  // PDG-US-15: heartbeat pings while this speech is the active practice
  // session, crediting lifetime practice time and surfacing any milestone
  // that unlocks mid-session. "Active" until scored, and — if a follow-up
  // Q&A got triggered — until that's answered too.
  const isSessionDone = scorecard !== null && (qaQuestion === null || qaScore !== null);
  const { newlyUnlocked, dismissMilestone } = usePracticeTimePing(
    "public_speaking",
    sessionId,
    sessionId !== null && !isSessionDone,
  );

  const handleStartVoice = async () => {
    if (isVoiceActive) return;
    voiceStartedAt.current = performance.now();
    committedTextRef.current = textContent;
    splicedPartialRef.current = null;
    // Camera first: if it fails we still want the speech recorded. useVideoAnalysis swallows
    // its own failures into `videoError`, so this never blocks the voice path.
    //
    // On a restart after a pause this is a no-op — startVideo returns early while a stream is
    // open — which is the point: the aggregator keeps one continuous timeline across pauses
    // instead of discarding the first half of the session.
    if (cameraEnabled) await startVideo();
    await startVoice();
  };

  // Audio only. The camera deliberately outlives every mic pause and is released in
  // handleSubmitSpeech — pausing to gather your thoughts should not end body-language capture
  // for the rest of the session, and restarting it mid-session would reset the aggregate.
  const handleStopVoice = async () => {
    await stopVoice();
    if (voiceStartedAt.current != null) {
      voiceDurationRef.current += (performance.now() - voiceStartedAt.current) / 1000;
      voiceStartedAt.current = null;
    }
  };

  const handleStartSession = async () => {
    setIsSubmitting(true);
    setError(null);
    try {
      const data = await startPublicSpeakingSession({
        speech_type: speechType as SpeechType,
        input_mode: inputMode === "audio" && cameraEnabled ? "audio_video" : inputMode,
      });
      setSessionId(data.session_id);
      setQaEnabled(data.qa_enabled);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to start session");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleSubmitSpeech = async () => {
    if (!sessionId) return;
    if (isVoiceActive) await handleStopVoice();
    // Submitting flips the session to qa_phase, which invalidates the idle room's own gate.
    // Close it here rather than letting the branch switch unmount it, so teardown is ordered.
    setIdleAudienceActive(false);
    // Read through the ref, not the closure: this can be reached straight after an awaited
    // handleStopVoice(), whose trailing transcript lands in state that this closure predates.
    const content = textContentRef.current.trim();
    if (!content) {
      setError(
        inputMode === "audio"
          ? "Record your speech before submitting."
          : "Enter your speech before submitting.",
      );
      return;
    }
    setIsSubmitting(true);
    setError(null);
    try {
      // Submit is where the camera is released — it runs through the whole session, mic pauses
      // included. stopVideo() is what builds the aggregate, so this must precede
      // getVideoFeatures(); reversing the two hands back an empty payload.
      if (isVideoActive) await stopVideo();
      const f = featuresRef.current;
      // Consume-once, exactly like the audio features above.
      const video = getVideoFeatures();
      const data = await submitPublicSpeakingTurn(sessionId, {
        text_content: content,
        duration_seconds:
          inputMode === "audio"
            ? Math.max(1, f.duration_seconds || voiceDurationRef.current)
            : null,
        audio_features: f.has
          ? {
              word_timings: f.word_timings,
              avg_db: f.avg_db,
              pitch_range_semitones: f.pitch_range_semitones,
              snr_db: f.snr_db,
              mean_pitch_hz: f.mean_pitch_hz,
              intensity_variation_db: f.intensity_variation_db,
              duration_seconds: f.duration_seconds,
            }
          : undefined,
        video_features: video ?? undefined,
        is_final: true,
      });
      setScorecard(data.scorecard);
      if (data.qa_triggered) {
        setQaQuestion(data.ai_question ?? null);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to submit speech");
    } finally {
      setIsSubmitting(false);
    }
  };

  // The clock runs on `isVoiceActive`, which useVoiceSocket sets when the recording socket opens
  // and clears when it closes — so tapping the mic button to stop freezes the countdown, and
  // tapping it again resumes from where it froze. Time spent paused costs the speaker nothing.
  const { elapsedSeconds, remainingSeconds } = useSpeechTimer({
    limitSeconds: timeLimitMinutes === null ? null : timeLimitMinutes * 60,
    running: isVoiceActive,
    onExpire: () => setTimeExpired(true),
  });

  // Two steps rather than one, driven off state instead of called from onExpire directly:
  // stopVoice() waits up to 15s for the utterance still in flight, so submitting in the same
  // breath would post a transcript missing its last sentence. The stop happens first; the
  // submit only fires on the later render where the socket is closed and that transcript has
  // landed. `submittedRef` keeps a re-render from posting the speech twice.
  const forcedSubmitRef = React.useRef(false);
  React.useEffect(() => {
    if (!timeExpired || scorecard || forcedSubmitRef.current) return;
    if (isVoiceActive) {
      if (!isStoppingVoice) void handleStopVoice();
      return;
    }
    if (isSubmitting) return;
    if (!textContentRef.current.trim()) {
      // Nothing was said. Stopping the mic is the whole of what the limit promises here —
      // submitting an empty speech would score a session that never happened.
      setError("Time's up — but nothing was recorded, so there's nothing to analyse.");
      return;
    }
    forcedSubmitRef.current = true;
    void handleSubmitSpeech();
    // handleStopVoice/handleSubmitSpeech are redefined every render; the guards above are what
    // make this safe to run on any of them, so they are deliberately not dependencies.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [timeExpired, isVoiceActive, isStoppingVoice, isSubmitting, scorecard]);

  // The face-to-face Q&A is scored entirely server-side: the agent calls submit_qa_response once
  // the answer clears the relevance gate, which flips the session to "completed". So when the
  // call ends there is nothing left to submit — the client just has to go and read the result.
  // Without this the user was stranded: pressing "Submit Response" afterwards hit
  // "This session is not in the Q&A phase." and their spoken, already-scored answer was lost.
  const handleQaCallEnded = async () => {
    setQaCallActive(false);
    if (!sessionId) return;
    try {
      const session = await getPublicSpeakingSession(sessionId);
      if (session.qa_score) {
        setQaScore(session.qa_score);
        if (session.scorecard) setScorecard(session.scorecard);
      }
      // No qa_score means the agent never got a usable answer (the caller hung up, or never
      // satisfied the gate). Fall through to the typed flow, which is still open.
    } catch {
      // A failed read must not strand the user either — the typed form is still there.
    }
  };

  const handleSubmitQaResponse = async () => {
    if (!sessionId) return;
    setIsSubmitting(true);
    setError(null);
    try {
      const data = await submitPublicSpeakingQa(sessionId, {
        audio_data: null,
        text_content: qaResponse,
      });
      setQaScore(data.qa_score);
      // The blended card — overall_score is now 70% speech / 30% Q&A, with the delivery half
      // preserved as speech_only_score. The results screen renders this, not the pre-Q&A card.
      setScorecard(data.updated_scorecard);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to submit Q&A response");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="flex flex-col gap-6">
      {voiceGate}
      {cameraGate}
      <MilestoneCelebrationModal
        milestone={newlyUnlocked[0] ?? null}
        onClose={() => newlyUnlocked[0] && dismissMilestone(newlyUnlocked[0].hours)}
      />
      <div className="flex items-center gap-4">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => router.back()}
          className="!w-9 shrink-0 !px-0"
        >
          <ArrowLeft className="h-5 w-5" />
        </Button>
        <div>
          <h1 className="font-serif text-h2 font-semibold text-foreground">
            {config.label}
          </h1>
          <p className="text-sm text-muted-foreground">{config.description}</p>
        </div>
      </div>

      {error && (
        <div className="flex items-start gap-2.5 rounded-xl border border-danger/30 bg-danger/10 px-4 py-3 text-sm text-foreground">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-danger" aria-hidden="true" />
          {error}
        </div>
      )}

      {!sessionId ? (
        <div className="flex flex-col gap-6 rounded-2xl border border-border bg-surface-elevated p-6">
          <div>
            <h2 className="font-semibold text-foreground">Session Setup</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Choose your input mode and start your practice session.
            </p>
          </div>

          <div className="flex gap-4">
            <button
              onClick={() => setInputMode("audio")}
              className={cn(
                "flex flex-1 flex-col items-center gap-3 rounded-xl border-2 p-4 transition-all",
                inputMode === "audio"
                  ? "border-primary bg-primary/5"
                  : "border-border hover:border-primary/50"
              )}
            >
              <Mic className="h-8 w-8 text-primary" />
              <div className="text-center">
                <div className="font-medium text-foreground">Voice</div>
                <div className="text-xs text-muted-foreground">Speak naturally</div>
              </div>
            </button>

            <button
              onClick={() => setInputMode("text")}
              className={cn(
                "flex flex-1 flex-col items-center gap-3 rounded-xl border-2 p-4 transition-all",
                inputMode === "text"
                  ? "border-primary bg-primary/5"
                  : "border-border hover:border-primary/50"
              )}
            >
              <Send className="h-8 w-8 text-primary" />
              <div className="text-center">
                <div className="font-medium text-foreground">Text</div>
                <div className="text-xs text-muted-foreground">Type your speech</div>
              </div>
            </button>
          </div>

          {/* Camera is an add-on to Voice, never a mode of its own — physical delivery is only
              meaningful alongside a spoken turn. Off by default; the consent line stays visible
              rather than hiding behind a modal, because it is the whole basis for trusting this. */}
          <label
            className={cn(
              "flex cursor-pointer gap-3 rounded-xl border-2 p-4 transition-all",
              inputMode !== "audio" && "cursor-not-allowed opacity-50",
              cameraEnabled && inputMode === "audio"
                ? "border-primary bg-primary/5"
                : "border-border",
            )}
          >
            <input
              type="checkbox"
              checked={cameraEnabled && inputMode === "audio"}
              disabled={inputMode !== "audio"}
              onChange={(e) => setCameraEnabled(e.target.checked)}
              className="mt-1 h-4 w-4 shrink-0 accent-[var(--color-primary)]"
            />
            <div className="flex flex-col gap-1">
              <span className="flex items-center gap-2 font-medium text-foreground">
                <Video className="h-4 w-4 text-primary" />
                Also analyse my body language
                <span className="rounded bg-muted px-1.5 py-0.5 text-xs font-normal text-muted-foreground">
                  Beta
                </span>
              </span>
              <span className="text-xs text-muted-foreground">
                {inputMode === "audio"
                  ? "Your camera feed never leaves this device. We analyse it in your browser and only send a summary — no video, no images, and no frame data are uploaded or stored."
                  : "Available with Voice input."}
              </span>
            </div>
          </label>

          {/* Said before the session starts, not discovered during it. The Q&A in particular
              used to arrive unannounced after the score, which is the wrong order to learn that
              you will be questioned on what you just said. */}
          <div className="rounded-lg bg-muted/50 p-4">
            <div className="flex items-center gap-2 text-sm">
              <ListOrdered className="h-4 w-4 text-muted-foreground" />
              <span className="font-medium text-foreground">How this session runs</span>
            </div>
            <ol className="mt-3 flex flex-col gap-2">
              {config.flow.map((step, index) => (
                <li key={step} className="flex items-start gap-3 text-sm text-muted-foreground">
                  <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary">
                    {index + 1}
                  </span>
                  {step}
                </li>
              ))}
            </ol>
          </div>

          {/* A hard stop, not a nudge: at zero the recording ends and the session moves on by
              itself. It never touches the score — real speaking slots have a clock, and the
              point is practising inside one. */}
          <div className="rounded-lg bg-muted/50 p-4">
            <div className="flex items-center gap-2 text-sm">
              <Timer className="h-4 w-4 text-muted-foreground" />
              <span className="font-medium text-foreground">Time limit</span>
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              {TIME_LIMIT_OPTIONS.map((minutes) => (
                <button
                  key={minutes ?? "none"}
                  type="button"
                  onClick={() => setTimeLimitMinutes(minutes)}
                  className={cn(
                    "rounded-full border-2 px-4 py-1.5 text-sm transition-all",
                    timeLimitMinutes === minutes
                      ? "border-primary bg-primary/5 font-medium text-foreground"
                      : "border-border text-muted-foreground hover:border-primary/50",
                  )}
                >
                  {minutes === null ? "No limit" : `${minutes} min`}
                  {minutes === config.suggestedLimitMinutes ? (
                    <span className="ml-1.5 text-xs text-muted-foreground">suggested</span>
                  ) : null}
                </button>
              ))}
            </div>
            <p className="mt-3 text-xs text-muted-foreground">
              {timeLimitMinutes === null
                ? "Your speech runs as long as you need. Nothing stops the recording but you."
                : `Recording stops automatically at ${timeLimitMinutes}:00 and the session moves on. The clock pauses whenever you pause the mic, and doesn't affect your score.`}
            </p>
          </div>

          <div className="rounded-lg bg-muted/50 p-4">
            <div className="flex items-center gap-2 text-sm">
              <Clock className="h-4 w-4 text-muted-foreground" />
              <span className="font-medium text-foreground">Target Pace: {config.ideal_wpm}</span>
            </div>
          </div>

          <Button
          onClick={
            inputMode !== "audio"
              ? handleStartSession
              : cameraEnabled
                // Voice first (required modality), camera second (optional add-on). The camera
                // gate is only invoked when the user opted in — prompting for a webcam during a
                // voice-only session would be an unpleasant surprise.
                ? () =>
                    void runWithVoiceReadiness(() =>
                      runWithCameraReadiness(handleStartSession),
                    )
                : () => void runWithVoiceReadiness(handleStartSession)
          }
            disabled={isSubmitting}
            className="w-full"
          >
            {isSubmitting ? "Starting..." : "Start Session"}
          </Button>
        </div>
      ) : !scorecard ? (
        <div className="flex flex-col gap-6 rounded-2xl border border-border bg-surface-elevated p-6">
          <div>
            <h2 className="font-semibold text-foreground">Deliver Your Speech</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              {inputMode === "audio"
                ? "Record your speech when ready. Speak clearly and at a natural pace."
                : "Type your speech below. Focus on structure and clarity."}
            </p>
          </div>

          {inputMode === "audio" ? (
            <div className="flex flex-col gap-4">
              {/* The stage: your own delivery beside the room you are delivering it to, the same
                  you-and-them layout the Q&A screen uses. The audience used to be a separate
                  card further down the page, which meant you could look at one or the other.

                  This grid element is ALWAYS rendered and the self-view is ALWAYS its first
                  child — only the className and the second cell change. startVideo() assigns
                  srcObject once, so moving the <video> to a different parent or sibling index
                  would remount it and blank the preview while capture silently continued. */}
              <div
                className={cn(
                  "grid gap-3",
                  cameraEnabled && idleAudienceActive && "md:grid-cols-2",
                )}
              >
                {/* Mounted whenever the camera is opted in, not only while active — the hook
                    needs the element to exist before startVideo() can attach the stream.
                    Mirrored for comfort; the frames fed to MediaPipe are NOT mirrored. */}
                {cameraEnabled ? (
                  <Panel label="You">
                    <video
                      ref={videoRef}
                      muted
                      playsInline
                      className="h-full w-full -scale-x-100 object-cover"
                    />
                    {!isVideoActive ? (
                      <div className="absolute inset-0 flex items-center justify-center bg-black/70 px-4 text-center text-xs text-white">
                        {isStartingVideo
                          ? `${videoStatus}${loadProgress !== null ? ` ${Math.round(loadProgress * 100)}%` : ""}`
                          : "Camera starts when you begin recording, and stays on through pauses until you submit"}
                      </div>
                    ) : null}
                    {/* Live visual feedback, mirroring the calibration modal's framing banner but
                        terse — this competes with the transcript for attention during recording,
                        so it only appears when there's actually something to fix. */}
                    {liveVisualHint ? (
                      <div className="absolute inset-x-0 bottom-0 bg-warning/90 px-2 py-1 text-center text-[11px] font-medium text-white">
                        {liveVisualHint}
                      </div>
                    ) : null}
                  </Panel>
                ) : null}

                {/* Speaking to a face beats speaking to a browser tab, but it is still a live
                    room — opt in, same as the Q&A call does. The avatar here is silent by
                    construction, so it cannot intrude on what is being recorded. */}
                {idleAudienceActive ? (
                  <IdleAudiencePanel
                    sessionId={sessionId!}
                    active={idleAudienceActive}
                    onHide={() => setIdleAudienceActive(false)}
                  />
                ) : (
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => setIdleAudienceActive(true)}
                    className="w-full"
                  >
                    Show an audience to speak to
                  </Button>
                )}
              </div>

              {videoError ? (
                <p className="text-center text-sm text-warning">{videoError}</p>
              ) : null}

              {/* Said here rather than only in the results, where it arrives too late to act on:
                  the camera looks identical whether or not eye contact will be scored, so
                  without this the first sign is a tile that declines to show a number. */}
              {isVideoActive && !gazeScorable ? (
                <p className="text-center text-sm text-muted-foreground">
                  Posture and gestures are being measured. Eye contact isn&apos;t — that needs the
                  camera calibration step, which was skipped or didn&apos;t take. Restart the
                  session to run it.
                </p>
              ) : null}

              <div className="flex flex-col items-center gap-3 rounded-xl border-2 border-dashed border-border p-6">
                {/* Counts down when a limit was set, up when it wasn't. Either way it advances
                    only while the recording socket is open, so a paused clock is the honest
                    reading of how much speaking time has actually been used. */}
                <div className="flex items-center gap-2">
                  <Timer
                    className={cn(
                      "h-4 w-4",
                      remainingSeconds !== null && remainingSeconds <= 30
                        ? "text-warning"
                        : "text-muted-foreground",
                    )}
                    aria-hidden="true"
                  />
                  <span
                    className={cn(
                      "font-mono text-2xl font-semibold tabular-nums",
                      remainingSeconds !== null && remainingSeconds <= 30
                        ? "text-warning"
                        : "text-foreground",
                    )}
                  >
                    {formatClock(remainingSeconds ?? elapsedSeconds)}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {remainingSeconds === null
                      ? "elapsed"
                      : isVoiceActive
                        ? "left"
                        : "left — paused"}
                  </span>
                </div>
                <button
                  onClick={isVoiceActive ? handleStopVoice : () => void runWithVoiceReadiness(handleStartVoice)}
                  disabled={isConnectingVoice || isStoppingVoice || timeExpired}
                  className={cn(
                    "flex h-20 w-20 items-center justify-center rounded-full transition-all disabled:opacity-60",
                    isVoiceActive
                      ? "bg-danger text-white animate-pulse"
                      : "bg-primary text-white hover:scale-110",
                  )}
                >
                  <Mic className="h-10 w-10" />
                </button>
                <div className="text-center">
                  <div className="font-medium text-foreground">
                    {timeExpired
                      ? "Time's up"
                      : isConnectingVoice
                        ? "Connecting..."
                        : isVoiceActive
                          ? "Recording — tap to stop"
                          : "Tap to Record"}
                  </div>
                  <div className="text-sm text-muted-foreground">
                    {timeExpired
                      ? qaEnabled
                        ? "Moving on to the Q&A..."
                        : "Scoring your speech..."
                      : voiceStatus ||
                        "We transcribe as you speak — review below before submitting."}
                  </div>
                </div>
              </div>

              <Textarea
                label="Transcript (editable)"
                value={textContent}
                onChange={(e) => setTextContent(e.target.value)}
                placeholder="Your spoken words appear here..."
                rows={6}
              />
              {voiceError ? (
                <p className="text-sm text-danger">{voiceError}</p>
              ) : null}
            </div>
          ) : (
            <Textarea
              label="Your speech"
              value={textContent}
              onChange={(e) => setTextContent(e.target.value)}
              placeholder="Type your speech here..."
              rows={8}
            />
          )}

          {/* On a Q&A scenario this does not end the session — it hands over to the questioner,
              and the score comes after that. The label says so, because "Submit for Analysis"
              promised a scorecard that no longer appears at this point. */}
          <Button
            onClick={handleSubmitSpeech}
            disabled={isSubmitting || isVoiceActive || !textContent.trim()}
            className="w-full"
          >
            {isSubmitting
              ? "Analyzing..."
              : qaEnabled
                ? "Move onto Q&A"
                : "Submit for Analysis"}
          </Button>
        </div>
      ) : qaQuestion && !qaScore ? (
        <div className="flex flex-col gap-6 rounded-2xl border border-border bg-surface-elevated p-6">
          <div>
            <h2 className="font-semibold text-foreground">Audience Q&A</h2>
            {/* No score has been shown yet, deliberately: knowing how the speech scored before
                answering turns an impromptu question into a post-mortem. */}
            <p className="mt-1 text-sm text-muted-foreground">
              An audience member has a follow-up question. Answer it impromptu — your score for
              the whole session comes next, and this answer is 30% of it.
            </p>
          </div>

          {/* The same full-screen live-call window AI Conversation uses, plus a self-view: being
              watched while you answer is most of what makes Q&A practice worth doing. No
              "End Session & See Report" button — the agent finalizes this one server-side. */}
          {qaCallActive ? (
            <LiveCallModal
              feature="public_speaking"
              sessionId={sessionId!}
              open={qaCallActive}
              title="Audience Q&A"
              selfView={
                qaSelfCameraError ? (
                  <div className="flex h-full w-full items-center justify-center px-4 text-center text-xs text-white/80">
                    {qaSelfCameraError}
                  </div>
                ) : (
                  <video
                    ref={qaSelfVideoRef}
                    muted
                    playsInline
                    className="h-full w-full -scale-x-100 object-cover"
                  />
                )
              }
              onClose={() => void handleQaCallEnded()}
            />
          ) : null}

          <div className="rounded-lg bg-secondary/20 p-4">
            <div className="flex items-start gap-3">
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary text-white shrink-0">
                ?
              </div>
              <div>
                <div className="font-medium text-foreground">Question</div>
                <p className="mt-1 text-sm text-foreground">{qaQuestion}</p>
              </div>
            </div>
          </div>

          {/* Facing a person is most of what makes Q&A practice worth doing, but it is a
              live call — opt in rather than opening a room the moment the speech ends. */}
          <Button
            type="button"
            variant="outline"
            onClick={() => setQaCallActive(true)}
            className="w-full"
          >
            Answer face-to-face instead
          </Button>

          <Textarea
            label="Or type your response"
            value={qaResponse}
            onChange={(e) => setQaResponse(e.target.value)}
            placeholder="Type your response..."
            rows={5}
          />

          <Button
            onClick={handleSubmitQaResponse}
            disabled={isSubmitting || !qaResponse.trim()}
            className="w-full"
          >
            {isSubmitting ? "Evaluating..." : "Submit Response"}
          </Button>
        </div>
      ) : (
        <div className="flex flex-col gap-6 rounded-2xl border border-border bg-surface-elevated p-6">
          <div className="flex items-center gap-3">
            <CheckCircle className="h-8 w-8 text-success" />
            <div>
              <h2 className="font-semibold text-foreground">Analysis Complete</h2>
              <p className="text-sm text-muted-foreground">
                Great job! Here's your performance breakdown.
              </p>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
            {/* The headline moves once a Q&A has been answered, so it says what it is made of
                rather than silently meaning something different than it did last session. */}
            <ScoreCard
              label={qaScore ? "Total (70% speech · 30% Q&A)" : "Overall"}
              score={scorecard.overall_score}
            />
            <ScoreCard label="Pacing" score={scorecard.pacing} />
            <ScoreCard label="Tone" score={scorecard.tone_variation} />
            <ScoreCard label="Clarity" score={scorecard.voice_clarity} />
          </div>

          {qaScore && scorecard.speech_only_score !== null &&
          scorecard.speech_only_score !== undefined ? (
            <p className="-mt-2 text-sm text-muted-foreground">
              Speech alone scored{" "}
              <span className="font-medium text-foreground">
                {Math.round(scorecard.speech_only_score)}
              </span>
              {qaScore.composure === null || qaScore.relevance === null
                ? " — the Q&A couldn't be graded this time, so your total is the speech on its own."
                : "; the Q&A moved it to your total above."}
            </p>
          ) : null}

          <div className="rounded-lg bg-muted/50 p-4">
            <div className="flex items-center gap-2 text-sm">
              <Clock className="h-4 w-4 text-muted-foreground" />
              <span className="font-medium text-foreground">
                Speaking Pace: {scorecard.words_per_minute?.toFixed(1)} WPM
              </span>
            </div>
          </div>

          {scorecard.video ? (
            <VideoPresenceSection video={scorecard.video} timeline={scorecard.video_timeline} />
          ) : null}

          {scorecard.register_detail ? (
            <EmotionalRegisterSection
              register={scorecard.register_detail}
              speechLabel={config.label}
            />
          ) : null}

          {sessionId && <FillerWordsScorecardSection sessionId={sessionId} />}

          {/* Folded into the results rather than living on its own screen: the Q&A is part of
              this session's score now, not a separate exercise with a separate verdict. */}
          {qaScore ? (
            <div className="rounded-lg border border-border bg-muted/30 p-4">
              <div className="flex items-center gap-2">
                <MessageCircleQuestion className="h-5 w-5 text-primary" />
                <span className="font-medium text-foreground">Q&A Handling</span>
              </div>

              {qaQuestion ? (
                <p className="mt-3 text-sm text-muted-foreground">
                  You were asked: <span className="text-foreground">{qaQuestion}</span>
                </p>
              ) : null}

              <div className="mt-4 grid grid-cols-2 gap-3">
                {[
                  { label: "Composure", value: qaScore.composure },
                  { label: "Relevance", value: qaScore.relevance },
                ].map(({ label, value }) => (
                  <div key={label} className="rounded-lg bg-surface-elevated p-3 text-center">
                    {/* An em dash, never a 0 — same rule as the video sub-scores: null means the
                        grader was unavailable, and that must not read as a bad answer. */}
                    <div className="text-xl font-semibold text-foreground">
                      {value === null || value === undefined ? "—" : Math.round(value)}
                    </div>
                    <div className="text-xs text-muted-foreground">{label}</div>
                  </div>
                ))}
              </div>

              <p className="mt-3 text-sm text-muted-foreground">{qaScore.feedback}</p>
            </div>
          ) : null}

          <div className="rounded-lg bg-secondary/20 p-4">
            <div className="flex items-start gap-3">
              <Lightbulb className="mt-0.5 h-5 w-5 text-primary shrink-0" />
              <div>
                <div className="font-medium text-foreground">Key Feedback</div>
                <p className="mt-1 text-sm text-muted-foreground">{scorecard.summary}</p>
              </div>
            </div>
          </div>

          {scorecard.actionable_tips && scorecard.actionable_tips.length > 0 && (
            <div>
              <h3 className="font-medium text-foreground">Actionable Tips</h3>
              <ul className="mt-2 space-y-2">
                {scorecard.actionable_tips.map((tip: string, index: number) => (
                  <li key={index} className="flex items-start gap-2 text-sm text-muted-foreground">
                    <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-primary" />
                    {tip}
                  </li>
                ))}
              </ul>
            </div>
          )}

          <Button onClick={() => router.push("/dashboard/public-speaking")} className="w-full">
            Try Another Speech Type
          </Button>
        </div>
      )}
    </div>
  );
}

/** What each capture-quality warning means, phrased as "here is what to distrust and why".
 *
 *  These used to replace the whole delivery panel — hitting any one of them meant "Delivery not
 *  measured" and no numbers at all. They now sit *alongside* the scores. A speaker who turned
 *  their camera on should see what was measured, and a caveated number they can interpret beats
 *  a blank panel they cannot; a single failing check usually leaves the other families fine. */
const VIDEO_WARNING_COPY: Record<VideoRejectionReason, string> = {
  no_face_detected: "We barely saw your face, so anything facial here is unreliable.",
  face_coverage_too_low:
    "Your face was out of frame for much of the session — eye contact and expression are rough.",
  too_dark: "The room was dark, which makes every facial measurement noisier than usual.",
  clip_too_short: "The session was short, so there wasn't much to measure from.",
  framing_unusable:
    "We couldn't judge your framing — your body was rarely in shot, so posture and gestures are rough.",
  device_too_slow:
    "Your device couldn't keep up, so these numbers come from fewer frames than usual.",
  camera_stopped_early:
    "The camera stopped before you submitted, so this covers only part of your speech.",
};

function VideoPresenceSection({
  video,
  timeline,
}: {
  video: NonNullable<PublicSpeakingScorecard["video"]>;
  timeline: PublicSpeakingScorecard["video_timeline"];
}) {
  // `warnings` is absent on scorecards stored before it existed; fall back to the single
  // `rejection` those rows carry so old sessions still explain themselves.
  const warnings: VideoRejectionReason[] =
    video.warnings ?? (video.rejection ? [video.rejection] : []);

  if (warnings.some((w) => !(w in VIDEO_WARNING_COPY))) {
    // An unmapped code silently rendering as some other reason is how "too short" spent its
    // whole life telling people we couldn't see their face.
    console.warn("[psc] unmapped video warning code(s)", warnings);
  }

  const subScores: { label: string; value: number | null }[] = [
    { label: "Eye Contact", value: video.eye_contact },
    { label: "Posture", value: video.posture },
    { label: "Gestures", value: video.gestures },
    { label: "Expression", value: video.expression },
  ];

  return (
    <div className="rounded-lg border border-border bg-muted/30 p-4">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Video className="h-5 w-5 text-primary" />
          <span className="font-medium text-foreground">Physical Delivery</span>
        </div>
        {video.visual_presence !== null ? (
          <span className="text-2xl font-bold text-foreground">
            {Math.round(video.visual_presence)}
          </span>
        ) : null}
      </div>

      <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-4">
        {subScores.map(({ label, value }) => (
          <div key={label} className="rounded-lg bg-surface-elevated p-3 text-center">
            {/* An em dash, never a 0 — null means we couldn't measure it, and the two must not
                look the same to a reader. */}
            <div className="text-xl font-semibold text-foreground">
              {value === null ? "—" : Math.round(value)}
            </div>
            <div className="text-xs text-muted-foreground">{label}</div>
          </div>
        ))}
      </div>

      {/* Named, not generic. "Delivery not measured" told the user nothing they could act on;
          "the room was dark" tells them what to change before the next session. */}
      {warnings.length > 0 ? (
        <ul className="mt-4 flex flex-col gap-2 rounded-lg border border-warning/30 bg-warning/10 p-3">
          {warnings.map((warning) => (
            <li key={warning} className="flex items-start gap-2 text-xs text-foreground">
              <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" aria-hidden="true" />
              {VIDEO_WARNING_COPY[warning] ??
                "Something about this capture was off, so treat these numbers as rough."}
            </li>
          ))}
        </ul>
      ) : null}

      {timeline && timeline.length > 1 ? (
        <div className="mt-5 flex flex-col gap-4">
          {/* Only channels that were actually measured render — DeliverySparkline returns null
              when a channel has fewer than two real values, so a session without the pose model
              simply shows fewer charts rather than an empty axis. */}
          <DeliverySparkline
            label="Eye contact over time"
            values={timeline.eye_contact}
            binSeconds={timeline.bin_seconds}
          />
          <DeliverySparkline
            label="Posture over time"
            values={timeline.posture.map((v) => (v === null ? null : v / 100))}
            binSeconds={timeline.bin_seconds}
            className="stroke-success"
          />
          <DeliverySparkline
            label="Gesture activity"
            values={timeline.gesture_activity}
            binSeconds={timeline.bin_seconds}
            className="stroke-warning"
            format={(mean) => `${mean.toFixed(2)} avg`}
          />
        </div>
      ) : null}

      {/* Camera position varies between setups, so an uncalibrated session's numbers carry an
          unmodelled bias. They are shown anyway — withholding them left the panel blank with no
          way for the user to tell a broken feature from a bad camera angle — but the caveat
          scales with how little we trust them. */}
      {video.confidence_weight < 0.35 ? (
        <p className="mt-3 text-xs text-muted-foreground">
          Treat these as indicative only. This session&apos;s camera calibration didn&apos;t take,
          so the numbers carry a large margin of error. Run the calibration step at the start of
          your next session and hold still through the countdown. Nothing was uploaded — your body
          language was analysed on your device.
        </p>
      ) : video.confidence_weight < 0.7 ? (
        <p className="mt-3 text-xs text-muted-foreground">
          These delivery numbers are provisional — camera position varies between setups, so
          treat them as a rough guide rather than an exact measurement.
        </p>
      ) : null}
    </div>
  );
}

/**
 * Emotional register — the delivery's energy, warmth and formality, each scored against what
 * this scenario asks for rather than in the abstract.
 *
 * This runs on every submission (voice and text, camera or not) and used to be discarded
 * wholesale by the client: `emotional_register`, `emotional_connection` and `register_detail`
 * crossed the wire on every scorecard and nothing rendered them. Only the scorer's prose
 * side-effects reached the user, mixed anonymously into the general flags and tips.
 *
 * Deliberately no new measurement here — this shows exactly what register_scorer.py already
 * computes. Warmth in particular is the simple smile/expressiveness read from the face
 * blendshapes; it is not an emotion classifier and must not be labelled as one.
 */
function EmotionalRegisterSection({
  register,
  speechLabel,
}: {
  register: NonNullable<PublicSpeakingScorecard["register_detail"]>;
  speechLabel: string;
}) {
  const channels: { label: string; value: number | null; absent: string }[] = [
    {
      label: "Vocal energy",
      value: register.voice_arousal,
      absent: "Needs a spoken turn",
    },
    {
      label: "Warmth",
      value: register.face_warmth,
      absent: "Needs the camera on",
    },
    {
      label: "Formality",
      value: register.word_formality,
      absent: "Needs 20+ words",
    },
  ];

  const band = register.detail?.expected;
  const expectation = band?.formality
    ? `A ${speechLabel.toLowerCase()} calls for ${band.formality} language${
        band.arousal_band ? ` and energy around ${band.arousal_band[0]}-${band.arousal_band[1]}` : ""
      }.`
    : null;

  return (
    <div className="rounded-lg border border-border bg-muted/30 p-4">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Smile className="h-5 w-5 text-primary" />
          <span className="font-medium text-foreground">Emotional Register</span>
        </div>
        {register.emotional_register !== null ? (
          <span className="text-2xl font-bold text-foreground">
            {Math.round(register.emotional_register)}
          </span>
        ) : null}
      </div>

      <p className="mt-1 text-xs text-muted-foreground">
        How well your delivery matched this occasion — not a reading of how you felt.
      </p>

      <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
        {channels.map(({ label, value, absent }) => (
          <div key={label} className="rounded-lg bg-surface-elevated p-3 text-center">
            {/* Em dash plus the reason, never a 0 — a channel with no source and a channel that
                scored badly must not look the same. */}
            <div className="text-xl font-semibold text-foreground">
              {value === null ? "—" : Math.round(value)}
            </div>
            <div className="text-xs text-muted-foreground">{label}</div>
            {value === null ? (
              <div className="mt-1 text-[11px] text-muted-foreground">{absent}</div>
            ) : null}
          </div>
        ))}
      </div>

      {expectation ? (
        <p className="mt-3 text-xs text-muted-foreground">{expectation}</p>
      ) : null}

      {register.confidence_weight < 0.6 ? (
        <p className="mt-2 text-xs text-muted-foreground">
          Based on {register.detail?.channels_measured?.length ?? 0} of 3 channels, so treat the
          combined figure as rough.
        </p>
      ) : null}
    </div>
  );
}

function ScoreCard({ label, score }: { label: string; score: number }) {
  const getColor = (score: number) => {
    if (score >= 80) return "text-success";
    if (score >= 60) return "text-warning";
    return "text-danger";
  };

  return (
    <div className="rounded-lg bg-muted/50 p-4 text-center">
      <div className="text-2xl font-bold text-foreground">{score}</div>
      <div className="text-xs text-muted-foreground">{label}</div>
    </div>
  );
}