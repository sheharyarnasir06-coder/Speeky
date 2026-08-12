"use client";

import * as React from "react";
import dynamic from "next/dynamic";
import { toast } from "react-toastify";
import { SessionRating } from "@/components/dashboard/SessionRating";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import {
  CheckCircle2,
  Headphones,
  Lock,
  Mic,
  MicOff,
  Phone,
  Sparkles,
  TriangleAlert,
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
import { ApiError } from "@/lib/api";
import {
  endScenarioSession,
  getScenarioDetail,
  getScenarioSession,
  getScenarioSessionState,
  sendScenarioTurn,
  startScenarioSession,
  type ScenarioDetail,
  type ScenarioEndResult,
  type StartScenarioResult,
} from "@/lib/scenario";
import { getPersonalizedOpening } from "@/lib/sessionMemory";
import { useAutoScroll } from "@/lib/useAutoScroll";
import { useAutoSpeak } from "@/lib/useAutoSpeak";
import { stopCurrent } from "@/lib/tts";
import { usePracticeTimePing } from "@/lib/usePracticeTimePing";
import { buildVoiceWsUrl, useVoiceSocket } from "@/lib/useVoiceSocket";
import { cn } from "@/lib/utils";

interface ChatTurn {
  role: "assistant" | "user";
  content: string;
}

// Mirrors the backend's IDLE_TIMEOUT_SECONDS (services/scenario_service.py) — if the user
// just sits in the session without typing or sending anything, fire an empty "check-in"
// turn, which the backend treats exactly like a silent reply (nudge, nudge, auto-close).
const IDLE_TIMEOUT_MS = 5 * 60 * 1000;

type Step =
  | { name: "loading" }
  | { name: "locked"; message: string }
  | { name: "error"; message: string }
  | { name: "intro"; detail: ScenarioDetail }
  | {
      name: "chat";
      session: StartScenarioResult;
      turns: ChatTurn[];
    }
  | { name: "results"; result: ScenarioEndResult };

export default function ScenarioSessionPage() {
  const params = useParams<{ key: string }>();
  const router = useRouter();
  const [step, setStep] = React.useState<Step>({ name: "loading" });
  const [chatInput, setChatInput] = React.useState("");
  const [isSubmitting, setIsSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [audioMode, setAudioMode] = React.useState(false);
  const [greeting, setGreeting] = React.useState<string | null>(null);
  const [liveCallOpen, setLiveCallOpen] = React.useState(false);
  const chatTurns = step.name === "chat" ? step.turns : null;
  const scrollRef = useAutoScroll(chatTurns?.length ?? 0);

  // Auto-speak assistant replies.
  useAutoSpeak(audioMode, chatTurns);

  // PDG-US-15: heartbeat pings while this scenario is the active practice
  // session, crediting lifetime practice time and surfacing any milestone
  // that unlocks mid-session.
  const isActivePractice = step.name === "chat";
  const { newlyUnlocked, dismissMilestone } = usePracticeTimePing(
    "scenario",
    step.name === "chat" ? step.session.session_id : null,
    isActivePractice,
  );

  // Voice mode: WebSocket mic-in straight to the backend (backend/lib/voice_ws.py) —
  // transcript fills the chat input for the user to review/edit, never auto-sent.
  // sessionIdRef tracks the active session id since the hook must be called
  // unconditionally at top level.
  const sessionIdRef = React.useRef<string | null>(null);
  React.useEffect(() => {
    if (step.name === "chat") sessionIdRef.current = step.session.session_id;
  }, [step]);
  const getWsUrl = React.useCallback(() => {
    if (!sessionIdRef.current) return null;
    return buildVoiceWsUrl(`/scenarios/${sessionIdRef.current}/voice-ws`);
  }, []);
  const onTranscript = React.useCallback((text: string) => {
    setChatInput((prev) => (prev.trim() ? `${prev.trim()} ${text}` : text));
  }, []);
  // Live-preview text while the user keeps talking — read-only, never touches
  // chatInput (which the user may be mid-edit on from a previous utterance). Clears
  // itself once the real transcript lands and gets appended above.
  const [livePreview, setLivePreview] = React.useState("");
  const {
    isVoiceActive,
    isConnectingVoice,
    isStoppingVoice,
    voiceStatus,
    error: voiceError,
    startVoice,
    stopVoice,
  } = useVoiceSocket(getWsUrl, onTranscript, setLivePreview);
  const { gate, runWithVoiceReadiness } = useVoiceReadinessGate({
    featureName: "Scenario Practice",
  });
  React.useEffect(() => {
    if (voiceError) setError(voiceError);
  }, [voiceError]);

  React.useEffect(() => {
    // Same shared cross-session memory profile Interview Coach's setup page reads from
    // (app/dashboard/interview-coach/page.tsx) — best-effort, silently skipped if it fails.
    getPersonalizedOpening()
      .then((data) => {
        if (data.has_history) setGreeting(data.opening_message);
      })
      .catch(() => {});
  }, []);

  const searchParams = useSearchParams();
  const resumeSessionId = searchParams.get("resume");

  React.useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const detail = await getScenarioDetail(params.key);
        if (cancelled) return;

        // ?resume=<session_id> (from the Explore resume banner / active-sessions
        // registry) — load the in-progress conversation directly instead of the
        // intro screen, so leaving and coming back never loses turns.
        if (resumeSessionId) {
          try {
            const state = await getScenarioSessionState(resumeSessionId);
            if (cancelled) return;
            if (state.status === "in_progress") {
              setStep({
                name: "chat",
                session: {
                  session_id: state.session_id,
                  scenario_key: state.scenario_key,
                  label: detail.label,
                  persona: detail.persona,
                  intent: detail.intent,
                  target_vocab: detail.target_vocab,
                  opening_message: "",
                },
                turns: state.turns.map((t) => ({
                  role: t.role === "user" ? "user" : "assistant",
                  content: t.content,
                })),
              });
              return;
            }
          } catch {
            // Resume link stale/invalid (e.g. already superseded) — fall through to intro.
          }
        }

        if (!cancelled) setStep({ name: "intro", detail });
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 403) {
          setStep({ name: "locked", message: err.message });
        } else {
          setStep({
            name: "error",
            message:
              err instanceof ApiError
                ? err.message
                : "Couldn't load this scenario.",
          });
        }
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [params.key, resumeSessionId]);

  async function handleStart() {
    if (step.name !== "intro") return;
    setError(null);
    setIsSubmitting(true);
    try {
      const session = await startScenarioSession(params.key);
      setStep({
        name: "chat",
        session,
        turns: [{ role: "assistant", content: session.opening_message }],
      });
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Couldn't start this scenario.",
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  // `message` is "" for an idle-timeout check-in — the backend classifies that exactly like
  // a silent reply, so no separate "no user bubble" branching is needed for that case here.
  const sendTurn = React.useCallback(
    async (sessionId: string, message: string) => {
      setError(null);
      setIsSubmitting(true);
      try {
        const result = await sendScenarioTurn(sessionId, message);
        // Ends on its own (silence auto-close, aggression, medical-emergency break) —
        // go straight to the scorecard instead of waiting for a manual "End Scenario" click.
        if (result.status !== "in_progress") {
          const finalResult = await getScenarioSession(sessionId);
          setStep({ name: "results", result: finalResult });
          return;
        }
        setStep((prev) => {
          if (prev.name !== "chat") return prev;
          const newTurns: ChatTurn[] = message
            ? [
                ...prev.turns,
                { role: "user", content: message },
                { role: "assistant", content: result.reply },
              ]
            : [...prev.turns, { role: "assistant", content: result.reply }];
          return { ...prev, turns: newTurns };
        });
      } catch (err) {
        setError(
          err instanceof ApiError ? err.message : "Something went wrong.",
        );
      } finally {
        setIsSubmitting(false);
      }
    },
    [],
  );

  async function handleSendChat() {
    if (step.name !== "chat" || !chatInput.trim() || isSubmitting) return;
    const message = chatInput.trim();
    setChatInput("");
    await sendTurn(step.session.session_id, message);
  }

  // Idle timeout: resets on every keystroke and every turn (sent or received). If nothing
  // happens for IDLE_TIMEOUT_MS, fire an empty turn — same nudge/nudge/auto-close behavior
  // as the user actually sending a blank message, just triggered by inactivity instead.
  React.useEffect(() => {
    if (step.name !== "chat" || isSubmitting) return;
    const sessionId = step.session.session_id;
    const timer = setTimeout(() => sendTurn(sessionId, ""), IDLE_TIMEOUT_MS);
    return () => clearTimeout(timer);
  }, [step, chatInput, isSubmitting, sendTurn]);

  // Re-fetches turns from the backend after a Live Call ends — the call's turns
  // already landed via the same send_turn path a typed message uses, this just
  // pulls them into view.
  async function refreshScenarioTurns() {
    if (step.name !== "chat") return;
    try {
      const state = await getScenarioSessionState(step.session.session_id);
      setStep((prev) =>
        prev.name === "chat"
          ? {
              ...prev,
              turns: state.turns.map((t) => ({
                role: t.role === "user" ? "user" : "assistant",
                content: t.content,
              })),
            }
          : prev,
      );
    } catch {
      toast.error("Couldn't refresh the transcript.");
    }
  }

  async function handleEnd() {
    if (step.name !== "chat") return;
    if (isVoiceActive) await stopVoice();
    setError(null);
    setIsSubmitting(true);
    try {
      const result = await endScenarioSession(step.session.session_id);
      setStep({ name: "results", result });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      stopCurrent();
      setIsSubmitting(false);
    }
  }

  if (step.name === "loading") {
    return (
      <div className="flex min-h-[50vh] items-center justify-center">
        <span
          className="h-6 w-6 animate-spin rounded-full border-2 border-current border-t-transparent text-muted-foreground"
          aria-hidden="true"
        />
      </div>
    );
  }

  if (step.name === "locked") {
    return (
      <div className="mx-auto flex max-w-lg flex-col items-center gap-4 rounded-2xl border border-warning/30 bg-warning/10 p-8 text-center">
        <Lock className="h-6 w-6 text-warning" aria-hidden="true" />
        <p className="text-sm text-foreground">{step.message}</p>
        <Button href="/dashboard/assessment" size="sm">
          Complete Assessment
        </Button>
      </div>
    );
  }

  if (step.name === "error") {
    return (
      <div className="mx-auto flex max-w-lg flex-col items-center gap-4 rounded-2xl border border-danger/30 bg-danger/5 p-8 text-center">
        <TriangleAlert className="h-6 w-6 text-danger" aria-hidden="true" />
        <p className="text-sm text-foreground">{step.message}</p>
        <Button href="/dashboard/explore" size="sm">
          Back to Explore
        </Button>
      </div>
    );
  }

  if (step.name === "intro") {
    const { detail } = step;
    return (
      <div className="mx-auto flex max-w-2xl flex-col gap-6">
        {gate}
        <div>
          <h1 className="font-serif text-h2 font-semibold text-foreground">
            {detail.label}
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Roleplay persona: {detail.persona}
          </p>
        </div>
        {greeting ? (
          <div className="flex items-start gap-2.5 rounded-xl border border-primary/20 bg-primary/5 px-4 py-3 text-sm text-foreground">
            <Sparkles
              className="mt-0.5 h-4 w-4 shrink-0 text-primary"
              aria-hidden="true"
            />
            {greeting}
          </div>
        ) : null}
        <div className="rounded-2xl border border-border bg-surface-elevated p-6 shadow-sm">
          <p className="text-sm text-foreground">{detail.intent}</p>
          <div className="mt-5">
            <p className="text-sm font-medium text-foreground">
              Target vocabulary
            </p>
            <div className="mt-2 flex flex-wrap gap-2">
              {detail.target_vocab.map((word) => (
                <span
                  key={word}
                  className="rounded-full bg-secondary px-3 py-1 text-xs font-medium text-secondary-foreground"
                >
                  {word}
                </span>
              ))}
            </div>
          </div>
          {error ? <p className="mt-3 text-sm text-danger">{error}</p> : null}
          <Button
            size="lg"
            className="mt-6"
            loading={isSubmitting}
            onClick={() => void runWithVoiceReadiness(handleStart)}
          >
            Start Scenario
          </Button>
        </div>
      </div>
    );
  }

  if (step.name === "chat") {
    return (
      <div className="mx-auto flex max-w-2xl flex-col gap-4">
        {gate}
        {liveCallOpen ? (
          <LiveCallModal
            feature="scenario"
            sessionId={step.session.session_id}
            open={liveCallOpen}
            onClose={() => setLiveCallOpen(false)}
            onEndSession={handleEnd}
            onCallEnded={() => void refreshScenarioTurns()}
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
            {step.session.label}
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
                  ? "Audio mode on — replies are spoken automatically"
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
              loading={isSubmitting}
              onClick={handleEnd}
            >
              End Scenario
            </Button>
          </div>
        </div>

        <div className="flex flex-col gap-4 rounded-2xl border border-border bg-surface-elevated p-6 shadow-sm">
          <div
            ref={scrollRef}
            className="flex max-h-[50vh] flex-col gap-4 overflow-y-auto"
          >
            {step.turns.map((turn, i) => (
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
                    {turn.role === "user" ? "You" : step.session.persona}
                  </span>
                  <div
                    className={
                      turn.role === "user"
                        ? "rounded-xl rounded-tr-sm bg-primary px-4 py-3 text-sm text-primary-foreground"
                        : "rounded-xl rounded-tl-sm bg-secondary px-4 py-3 text-sm text-secondary-foreground"
                    }
                  >
                    {turn.content}
                  </div>
                </div>
                {turn.role === "user" ? (
                  <UserChatAvatar className="mt-5" />
                ) : null}
              </div>
            ))}
          </div>

          <div className="flex flex-col gap-2 border-t border-border pt-4 sm:flex-row sm:items-center">
            <input
              type="text"
              value={chatInput}
              onChange={(event) => setChatInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  handleSendChat();
                }
              }}
              placeholder="Type your response..."
              className="h-11 min-w-0 sm:flex-1 rounded-xl border border-input bg-surface px-4 text-sm text-foreground placeholder:text-muted-foreground focus:border-primary focus:outline-none focus:ring-2 focus:ring-ring/40"
            />
            <div className="flex flex-wrap items-center justify-between gap-2">
              <Button
                size="md"
                loading={isSubmitting}
                disabled={!chatInput.trim()}
                onClick={handleSendChat}
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
                    onClick={() => void stopVoice()}
                  >
                    <MicOff className="h-4 w-4" aria-hidden="true" />
                    Stop Voice
                  </Button>
                ) : (
                  <Button
                    size="md"
                    variant="outline"
                    loading={isConnectingVoice}
                    onClick={() => void runWithVoiceReadiness(startVoice)}
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
          {error ? <p className="text-sm text-danger">{error}</p> : null}
        </div>
      </div>
    );
  }

  // step.name === "results"
  const { result } = step;
  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-6">
      {gate}
      <div className="animate-fade-up rounded-2xl border border-border bg-gradient-to-br from-primary to-primary-hover p-8 text-center text-primary-foreground shadow-sm">
        <Sparkles className="mx-auto h-6 w-6" aria-hidden="true" />
        <h1 className="mt-3 font-serif text-h2 font-semibold">
          {result.scores.politeness !== null
            ? `${Math.round(result.scores.politeness)}/100 Politeness`
            : "Not scored"}
        </h1>
        <p className="mt-2 text-sm text-primary-foreground/85">
          {result.summary}
        </p>
      </div>

      {/* US-193 "Learner satisfaction" / US-196 "user feedback" input. */}
      <SessionRating sessionId={result.session_id} />

      <div
        className="animate-fade-up rounded-2xl border border-border bg-surface-elevated p-6 shadow-sm"
        style={{ animationDelay: "100ms" }}
      >
        <h2 className="font-serif text-lg font-semibold text-foreground">
          Scores
        </h2>
        <div className="mt-4 grid grid-cols-2 gap-4 sm:grid-cols-3">
          {Object.entries(result.scores)
            .filter(([, value]) => value !== null)
            .map(([key, value]) => (
              <div
                key={key}
                className="rounded-xl border border-border bg-surface p-4"
              >
                <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  {key.replace(/_/g, " ")}
                </p>
                <p className="mt-1 text-xl font-semibold text-foreground">
                  {Math.round(value ?? 0)}
                </p>
              </div>
            ))}
        </div>
        {result.met_goal !== null ? (
          <div
            className={
              "mt-4 flex items-center gap-2 rounded-xl px-4 py-3 text-sm " +
              (result.met_goal
                ? "bg-success/10 text-success"
                : "bg-warning/10 text-warning")
            }
          >
            {result.met_goal ? (
              <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
            ) : (
              <TriangleAlert className="h-4 w-4" aria-hidden="true" />
            )}
            {result.met_goal
              ? "You achieved the scenario goal."
              : "You didn't fully achieve the scenario goal this time."}
          </div>
        ) : null}
      </div>

      <div
        className="animate-fade-up rounded-2xl border border-border bg-surface-elevated p-6 shadow-sm"
        style={{ animationDelay: "180ms" }}
      >
        <h2 className="font-serif text-lg font-semibold text-foreground">
          Target Vocabulary
        </h2>
        <div className="mt-3 flex flex-wrap gap-2">
          {result.vocab_used.map((word) => (
            <span
              key={word}
              className="rounded-full bg-success/15 px-3 py-1 text-xs font-medium text-success"
            >
              {word}
            </span>
          ))}
          {result.vocab_missing.map((word) => (
            <span
              key={word}
              className="rounded-full bg-muted px-3 py-1 text-xs font-medium text-muted-foreground"
            >
              {word}
            </span>
          ))}
        </div>
      </div>

      {result.tips.length > 0 || result.suggestion ? (
        <div
          className="animate-fade-up rounded-2xl border border-border bg-surface-elevated p-6 shadow-sm"
          style={{ animationDelay: "260ms" }}
        >
          <h2 className="font-serif text-lg font-semibold text-foreground">
            Tips for Next Time
          </h2>
          <ul className="mt-3 flex flex-col gap-2">
            {(result.tips.length > 0 ? result.tips : [result.suggestion]).map(
              (tip, i) => (
                <li
                  key={i}
                  className="flex items-start gap-2 text-sm text-muted-foreground"
                >
                  <span
                    className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-primary"
                    aria-hidden="true"
                  />
                  {tip}
                </li>
              ),
            )}
          </ul>
        </div>
      ) : null}

      {result.polished_line ? (
        <div
          className="animate-fade-up rounded-2xl border border-border bg-surface-elevated p-6 shadow-sm"
          style={{ animationDelay: "320ms" }}
        >
          <h2 className="font-serif text-lg font-semibold text-foreground">
            A Stronger Way to Say It
          </h2>
          {result.original_line ? (
            <p className="mt-3 text-sm text-muted-foreground line-through decoration-danger/40">
              {result.original_line}
            </p>
          ) : null}
          <p className="mt-2 rounded-xl bg-success/10 px-4 py-3 text-sm text-foreground">
            {result.polished_line}
          </p>
        </div>
      ) : null}

      <Button
        size="lg"
        variant="outline"
        className="self-center"
        onClick={() => router.push("/dashboard/explore")}
      >
        Back to Explore
      </Button>
    </div>
  );
}
