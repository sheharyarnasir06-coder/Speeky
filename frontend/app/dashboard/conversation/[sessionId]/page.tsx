"use client";

import * as React from "react";
import dynamic from "next/dynamic";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { toast } from "react-toastify";
import {
  CheckCircle2,
  Headphones,
  Mic,
  MicOff,
  Phone,
  PhoneOff,
  Volume2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { AiCoachAvatar } from "@/components/common/AiCoachAvatar";
import { UserChatAvatar } from "@/components/common/UserChatAvatar";
import { useVoiceReadinessGate } from "@/components/common/VoiceReadinessGate";

// livekit-client is ~150KB — load it only once a user actually opens a call,
// not on every visit to this page.
const LiveCallModal = dynamic(
  () => import("@/components/common/LiveCallModal").then((m) => m.LiveCallModal),
  { ssr: false },
);
import { MilestoneCelebrationModal } from "@/components/dashboard/MilestoneCelebrationModal";
import { cn } from "@/lib/utils";
import { ApiError } from "@/lib/api";
import {
  endConversationSession,
  getConversationTranscript,
  sendConversationMessage,
  type ConversationTurn,
  type EndConversationResult,
} from "@/lib/conversation";
import { usePracticeTimePing } from "@/lib/usePracticeTimePing";
import {
  scoreConversationTurn,
  type SentenceScoreResult,
} from "@/lib/pronunciationCoach";
import { localDate } from "@/lib/dailyChallenge";
import { getChallengeConversationStatus } from "@/lib/daily-challenge";
import { ScoreDisputeButton } from "@/components/dashboard/ScoreDisputeButton";
import { playText, stopCurrent } from "@/lib/tts";
import { useAutoScroll } from "@/lib/useAutoScroll";
import {
  buildVoiceWsUrl,
  useVoiceSocket,
  type AudioFeatures,
  type VoiceFeatures,
} from "@/lib/useVoiceSocket";

const TIER_CLASSES: Record<string, string> = {
  green: "bg-success/15 text-success",
  orange: "bg-warning/15 text-warning",
  red: "bg-danger/15 text-danger",
  gray: "bg-muted text-muted-foreground line-through",
  unscorable: "bg-muted text-muted-foreground",
};

/**
 * US-79/US-74: word-level pronunciation highlighting for one audio turn,
 * fetched from the real shared pipeline (pronunciation_coach_service.score_turn).
 * Only ever renders for a turn with input_mode "audio".
 */
function PronunciationBreakdown({
  sessionId,
  turnIndex,
}: {
  sessionId: string;
  turnIndex: number;
}) {
  const [result, setResult] = React.useState<SentenceScoreResult | null>(null);
  const [status, setStatus] = React.useState<"idle" | "loading" | "error">(
    "idle",
  );
  const [message, setMessage] = React.useState<string | null>(null);

  async function handleScore() {
    setStatus("loading");
    setMessage(null);
    try {
      const response = await scoreConversationTurn(sessionId, turnIndex);
      if (response.result) {
        setResult(response.result);
        setStatus("idle");
      } else {
        // US-74: outage/retry/hard-failure states — real backend status, not a crash.
        setMessage(response.message);
        setStatus("error");
      }
    } catch (err) {
      setMessage(
        err instanceof ApiError ? err.message : "Couldn't score this turn.",
      );
      setStatus("error");
    }
  }

  if (result) {
    return (
      <p className="mt-1.5 flex flex-wrap gap-1 text-sm">
        {result.words.map((w) => (
          <span
            key={w.index}
            title={w.note}
            className={cn("rounded px-1", TIER_CLASSES[w.tier] ?? "")}
          >
            {w.target_word}
          </span>
        ))}
      </p>
    );
  }

  return (
    <div className="mt-1.5">
      <button
        type="button"
        onClick={handleScore}
        disabled={status === "loading"}
        className="text-[11px] text-muted-foreground transition-colors hover:text-foreground disabled:opacity-50"
      >
        {status === "loading"
          ? "Scoring pronunciation…"
          : "View pronunciation breakdown"}
      </button>
      {status === "error" && message ? (
        <p className="mt-1 text-[11px] text-danger">{message}</p>
      ) : null}
    </div>
  );
}

const DAILY_CHALLENGE_POLL_MS = 15_000;

export default function ConversationSessionPage() {
  const params = useParams<{ sessionId: string }>();
  const router = useRouter();
  const searchParams = useSearchParams();
  const isDailyChallenge = searchParams.get("daily") === "1";
  const [turns, setTurns] = React.useState<ConversationTurn[] | null>(null);
  const [topicLabel, setTopicLabel] = React.useState("");
  const [message, setMessage] = React.useState("");
  const [isSending, setIsSending] = React.useState(false);
  const [isEnding, setIsEnding] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [playingIndex, setPlayingIndex] = React.useState<number | null>(null);
  const [audioMode, setAudioMode] = React.useState(false);
  const [summary, setSummary] = React.useState<EndConversationResult | null>(
    null,
  );
  const [liveCallOpen, setLiveCallOpen] = React.useState(false);

  const scrollRef = useAutoScroll(turns?.length ?? 0);
  const lastAutoPlayed = React.useRef(-1);
  const audioModeWasOn = React.useRef(false);

  // Backend transcribes speech over a WebSocket (backend/lib/voice_ws.py) instead of
  // auto-sending — fills the input box so the user can review/edit before hitting Send.
  const getWsUrl = React.useCallback(
    () =>
      buildVoiceWsUrl(`/conversation/sessions/${params.sessionId}/voice-ws`),
    [params.sessionId],
  );
  // Stores the latest audio features from the voice agent so handleSend can
  // attach them to the message and mark the turn as input_mode="audio".
  const pendingAudioFeaturesRef = React.useRef<{
    duration_seconds: number;
    word_timings: { word: string; start: number; end: number }[];
  } | null>(null);
  const onTranscript = React.useCallback(
    (text: string, audioFeatures?: AudioFeatures | VoiceFeatures) => {
      pendingAudioFeaturesRef.current =
        audioFeatures &&
        Array.isArray((audioFeatures as AudioFeatures).word_timings) &&
        typeof (audioFeatures as AudioFeatures).duration_seconds === "number"
          ? {
              duration_seconds: (audioFeatures as AudioFeatures)
                .duration_seconds,
              word_timings: (audioFeatures as AudioFeatures).word_timings,
            }
          : null;
      setMessage((prev) => (prev.trim() ? `${prev.trim()} ${text}` : text));
    },
    [],
  );
  // Live-preview text while the user keeps talking — read-only, never touches the
  // editable message field (the user may be mid-edit on a previous utterance). Clears
  // itself once the real transcript lands and gets appended into `message` above.
  const [livePreview, setLivePreview] = React.useState("");
  const {
    isVoiceActive,
    isConnectingVoice,
    isStoppingVoice,
    voiceStatus,
    error: voiceError,
    startVoice,
    stopVoice,
    getLastAudioFeatures,
  } = useVoiceSocket(getWsUrl, onTranscript, setLivePreview);
  const { gate, runWithVoiceReadiness } = useVoiceReadinessGate({
    featureName: "AI Conversation",
  });

  // PDG-US-15: heartbeat pings while this conversation is the active practice
  // session, crediting lifetime practice time and surfacing any milestone
  // that unlocks mid-session.
  const { newlyUnlocked, dismissMilestone } = usePracticeTimePing(
    "conversation",
    params.sessionId,
    !summary,
  );

  React.useEffect(() => {
    getConversationTranscript(params.sessionId)
      .then((data) => {
        setTurns(data.turns);
        setTopicLabel(data.topic_label);
      })
      .catch((err) =>
        setError(
          err instanceof ApiError ? err.message : "Couldn't load this session.",
        ),
      );
  }, [params.sessionId]);

  // Audio mode: auto-speak each new assistant turn as it arrives. Also
  // re-speak the current last turn right when audioMode flips back on —
  // otherwise the "already played" guard silently blocks it and toggling
  // off/on again looks broken.
  const refreshTranscript = React.useCallback(async () => {
    try {
      const data = await getConversationTranscript(params.sessionId);
      setTurns(data.turns);
      setTopicLabel(data.topic_label);
    } catch (err) {
      console.error("Failed to refresh conversation transcript:", err);
      toast.error("Couldn't refresh the transcript.");
    }
  }, [params.sessionId]);

  const handlePlay = React.useCallback(async (index: number, text: string) => {
    setPlayingIndex(index);
    try {
      await playText(text);
    } finally {
      setPlayingIndex(null);
    }
  }, []);

  React.useEffect(() => {
    if (!audioMode || !turns?.length) {
      stopCurrent();
      audioModeWasOn.current = audioMode;
      return;
    }
    const turnedOn = !audioModeWasOn.current;
    audioModeWasOn.current = true;
    const lastIndex = turns.length - 1;
    const last = turns[lastIndex];
    if (
      last.role === "assistant" &&
      (turnedOn || lastAutoPlayed.current !== lastIndex)
    ) {
      lastAutoPlayed.current = lastIndex;
      void handlePlay(lastIndex, last.content);
    }
  }, [audioMode, turns, handlePlay]);

  React.useEffect(() => {
    if (voiceError) setError(voiceError);
  }, [voiceError]);

  // PDG-US-11: this session was started via the Daily Challenge redirect. The 5-minute
  // timer runs server-side off the first prompt, so poll rather than compute it
  // client-side — that way it still completes (and the user still gets the alert) even
  // if they go quiet after one message instead of sending another.
  const [challengeDone, setChallengeDone] = React.useState(false);
  React.useEffect(() => {
    if (!isDailyChallenge || challengeDone) return;

    let cancelled = false;
    async function poll() {
      try {
        const res = await getChallengeConversationStatus(
          params.sessionId,
          localDate(),
        );
        if (cancelled) return;
        if (res.status === "qualified") {
          setChallengeDone(true);
          if (res.just_completed) {
            toast.success(
              `🔥 Daily Challenge complete — ${res.current_streak}-day streak!${
                res.milestone_message ? ` ${res.milestone_message}` : ""
              }`,
            );
            window.dispatchEvent(new CustomEvent("speeky:streak-updated"));
          }
        }
      } catch {
        // Best-effort — a poll failure just tries again next tick.
      }
    }

    void poll();
    const interval = window.setInterval(poll, DAILY_CHALLENGE_POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [isDailyChallenge, challengeDone, params.sessionId]);

  async function handleStartVoice() {
    setError(null);
    await startVoice();
  }

  async function handleStopVoice() {
    await stopVoice();
    await refreshTranscript();
  }

  async function handleSend() {
    if (!message.trim() || isSending) return;

    setError(null);
    setIsSending(true);
    const text = message.trim();
    // Consume pending audio features from the voice agent (set by onTranscript).
    // getLastAudioFeatures() clears the ref so a second text send doesn't re-use them.
    const audioFeatures =
      pendingAudioFeaturesRef.current ?? getLastAudioFeatures();
    pendingAudioFeaturesRef.current = null;
    const isAudioTurn = audioFeatures !== null;
    setMessage("");
    setTurns((prev) => [
      ...(prev ?? []),
      {
        role: "user",
        content: text,
        input_mode: isAudioTurn ? "audio" : "text",
        correction_chip: null,
        created_at: "",
      },
    ]);

    try {
      const payload: Parameters<typeof sendConversationMessage>[1] = { text };
      if (isAudioTurn && audioFeatures) {
        payload.input_mode = "audio";
        payload.audio_features = {
          transcript: text,
          duration_seconds: audioFeatures.duration_seconds,
          word_timings: audioFeatures.word_timings,
        };
      }
      const result = await sendConversationMessage(params.sessionId, payload);
      setTurns((prev) => [
        ...(prev ?? []),
        {
          role: "assistant",
          content: result.reply,
          input_mode: null,
          correction_chip: null,
          created_at: "",
        },
      ]);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setIsSending(false);
    }
  }

  async function handleEnd() {
    if (isVoiceActive) {
      await handleStopVoice();
    }

    setIsEnding(true);
    setError(null);
    try {
      const result = await endConversationSession(params.sessionId);
      setSummary(result);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      stopCurrent();
      setIsEnding(false);
    }
  }

  if (summary) {
    return (
      <div className="mx-auto flex max-w-xl flex-col gap-6">
        <MilestoneCelebrationModal
          milestone={newlyUnlocked[0] ?? null}
          onClose={() =>
            newlyUnlocked[0] && dismissMilestone(newlyUnlocked[0].hours)
          }
        />
        <div className="animate-fade-up rounded-2xl border border-border bg-gradient-to-br from-primary to-primary-hover p-8 text-center text-primary-foreground shadow-sm">
          <CheckCircle2 className="mx-auto h-6 w-6" aria-hidden="true" />
          <h1 className="mt-3 font-serif text-h2 font-semibold">
            Session Complete
          </h1>
          <p className="mt-2 text-sm text-primary-foreground/85">
            {Math.round(summary.duration_seconds)}s · Level: {summary.level}
          </p>
        </div>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <div className="rounded-xl border border-border bg-surface-elevated p-4 text-center shadow-sm">
            <p className="text-xs text-muted-foreground">Fluency</p>
            <p className="mt-1 text-xl font-semibold text-foreground">
              {Math.round(summary.fluency_score)}
            </p>
            <ScoreDisputeButton
              assessmentId={summary.session_id}
              metricName="fluency"
              metricLabel="Fluency"
            />
          </div>
          <div className="rounded-xl border border-border bg-surface-elevated p-4 text-center shadow-sm">
            <p className="text-xs text-muted-foreground">Vocabulary</p>
            <p className="mt-1 text-xl font-semibold text-foreground">
              {Math.round(summary.vocabulary_score)}
            </p>
            <ScoreDisputeButton
              assessmentId={summary.session_id}
              metricName="vocabulary"
              metricLabel="Vocabulary"
            />
          </div>
          <div className="rounded-xl border border-border bg-surface-elevated p-4 text-center shadow-sm">
            <p className="text-xs text-muted-foreground">Pronunciation</p>
            <p className="mt-1 text-xl font-semibold text-foreground">
              {summary.pronunciation_score !== null
                ? Math.round(summary.pronunciation_score)
                : "—"}
            </p>
            {summary.pronunciation_score !== null ? (
              <ScoreDisputeButton
                assessmentId={summary.session_id}
                metricName="pronunciation"
                metricLabel="Pronunciation"
              />
            ) : null}
          </div>
        </div>
        {summary.new_memory_facts.length > 0 ? (
          <div className="rounded-2xl border border-border bg-surface-elevated p-6 shadow-sm">
            <p className="text-sm font-medium text-foreground">
              Speeky remembered
            </p>
            <ul className="mt-2 flex flex-col gap-1 text-sm text-muted-foreground">
              {summary.new_memory_facts.map((fact, i) => (
                <li key={i}>
                  {fact.category}: {fact.value}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        <Button
          size="lg"
          variant="outline"
          className="self-center"
          onClick={() => router.push("/dashboard/conversation")}
        >
          Start Another Conversation
        </Button>
      </div>
    );
  }

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-4">
      {gate}
      {liveCallOpen ? (
        <LiveCallModal
          feature="conversation"
          sessionId={params.sessionId}
          open={liveCallOpen}
          onClose={() => setLiveCallOpen(false)}
          onEndSession={handleEnd}
          onCallEnded={() => void refreshTranscript()}
        />
      ) : null}
      <MilestoneCelebrationModal
        milestone={newlyUnlocked[0] ?? null}
        onClose={() =>
          newlyUnlocked[0] && dismissMilestone(newlyUnlocked[0].hours)
        }
      />
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="font-serif text-h2 font-semibold text-foreground">
          {topicLabel || "Conversation"}
        </h1>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setAudioMode((v) => !v)}
            aria-pressed={audioMode}
            aria-label={
              audioMode ? "Turn off audio mode" : "Turn on audio mode"
            }
            title={
              audioMode
                ? "Audio mode on - replies are spoken automatically"
                : "Turn on audio mode"
            }
            className={
              "flex h-9 w-9 items-center justify-center rounded-xl border transition-colors " +
              (audioMode
                ? "border-primary bg-primary text-primary-foreground"
                : "border-border bg-surface text-muted-foreground hover:text-foreground")
            }
          >
            <Headphones className="h-4 w-4" aria-hidden="true" />
          </button>
          <Button
            size="sm"
            variant="outline"
            loading={isEnding}
            onClick={handleEnd}
          >
            <PhoneOff className="h-4 w-4" aria-hidden="true" />
            End Session
          </Button>
        </div>
      </div>

      <div className="flex flex-col gap-4 rounded-2xl border border-border bg-surface-elevated p-6 shadow-sm">
        <div
          ref={scrollRef}
          className="flex max-h-[55vh] flex-col gap-4 overflow-y-auto"
        >
          {(turns ?? []).map((turn, i) => (
            <div
              key={i}
              className={
                turn.role === "user"
                  ? "ml-auto flex max-w-[86%] items-start gap-2"
                  : "flex max-w-[86%] items-start gap-2"
              }
            >
              {turn.role === "assistant" ? (
                <AiCoachAvatar className="mt-5" />
              ) : null}
              <div className="min-w-0 flex-1">
                <span
                  className={cn(
                    "mb-1 block text-xs font-semibold uppercase tracking-wide text-muted-foreground",
                    turn.role === "user" && "text-right",
                  )}
                >
                  {turn.role === "user" ? "You" : "Coach"}
                </span>
                <div
                  className={
                    turn.role === "user"
                      ? "rounded-xl rounded-tr-sm bg-primary px-4 py-3 text-sm text-primary-foreground"
                      : "flex items-start gap-2 rounded-xl rounded-tl-sm bg-secondary px-4 py-3 text-sm text-secondary-foreground"
                  }
                >
                  <span className="flex-1">{turn.content}</span>
                  {turn.role === "assistant" ? (
                    <button
                      type="button"
                      onClick={() => void handlePlay(i, turn.content)}
                      disabled={playingIndex === i}
                      aria-label="Play audio"
                      className="shrink-0 text-primary hover:opacity-70 disabled:animate-pulse"
                    >
                      <Volume2 className="h-4 w-4" aria-hidden="true" />
                    </button>
                  ) : null}
                </div>
                {turn.correction_chip ? (
                  <div className="mt-1.5 rounded-lg bg-warning/10 px-3 py-2 text-xs text-foreground">
                    <span className="line-through opacity-70">
                      {turn.correction_chip.original}
                    </span>{" "}
                    <span className="font-medium text-success">
                      {turn.correction_chip.corrected}
                    </span>
                    <p className="mt-0.5 text-muted-foreground">
                      {turn.correction_chip.explanation}
                    </p>
                  </div>
                ) : null}
                {turn.role === "user" && turn.input_mode === "audio" ? (
                  <PronunciationBreakdown
                    sessionId={params.sessionId}
                    turnIndex={i}
                  />
                ) : null}
              </div>
              {turn.role === "user" ? (
                <UserChatAvatar className="mt-5" />
              ) : null}
            </div>
          ))}
        </div>

        {error ? <p className="text-sm text-danger">{error}</p> : null}

        <div className="flex flex-col gap-2 border-t border-border pt-4 sm:flex-row sm:items-center">
          <input
            type="text"
            value={message}
            onChange={(event) => setMessage(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                void handleSend();
              }
            }}
            placeholder="Type a message..."
            className="h-11 min-w-0 sm:flex-1 rounded-xl border border-input bg-surface px-4 text-sm text-foreground placeholder:text-muted-foreground focus:border-primary focus:outline-none focus:ring-2 focus:ring-ring/40"
          />
          <div className="flex flex-wrap items-center justify-between gap-2">
            <Button
              size="md"
              loading={isSending}
              disabled={!message.trim()}
              onClick={() => void handleSend()}
            >
              Send
            </Button>

            <div className="flex flex-wrap items-center gap-2">
              {isVoiceActive ? (
                <Button
                  size="md"
                  variant="outline"
                  className="voice-listening-button"
                  loading={isStoppingVoice}
                  onClick={() => void handleStopVoice()}
                >
                  <MicOff className="h-4 w-4" aria-hidden="true" />
                  Stop Voice
                </Button>
              ) : (
                <Button
                  size="md"
                  variant="outline"
                  loading={isConnectingVoice}
                  onClick={() => void runWithVoiceReadiness(handleStartVoice)}
                >
                  <Mic className="h-4 w-4" aria-hidden="true" />
                  Start Voice
                </Button>
              )}
              <Button
                size="md"
                variant="outline"
                onClick={() =>
                  void runWithVoiceReadiness(() => setLiveCallOpen(true))
                }
              >
                <Phone className="h-4 w-4" aria-hidden="true" />
                Live Call
              </Button>
            </div>
          </div>
        </div>

        {voiceStatus ? (
          <p
            role="status"
            aria-live="polite"
            className="text-sm text-muted-foreground"
          >
            {voiceStatus}
          </p>
        ) : null}
        {livePreview ? (
          <p
            role="status"
            aria-live="polite"
            className="text-sm italic text-muted-foreground"
          >
            {livePreview}
          </p>
        ) : null}
      </div>
    </div>
  );
}
