"use client";

import * as React from "react";
import { useParams, useRouter } from "next/navigation";
import { toast } from "react-toastify";
import { CheckCircle2, Mic, MicOff, Sparkles, TriangleAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useVoiceReadinessGate } from "@/components/common/VoiceReadinessGate";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { ApiError } from "@/lib/api";
import {
  getCoachingScenarios,
  getCoachingVoiceToken,
  sendRoleplayTurn,
  startCoachingSession,
  submitCoachingSession,
  type CoachingResult,
  type CoachingScenarioMeta,
  type StartCoachingResult,
} from "@/lib/coaching";
import { useAutoScroll } from "@/lib/useAutoScroll";
import { useLiveKitVoice } from "@/lib/useLiveKitVoice";
import { useSpeechRecognition } from "@/lib/useSpeechRecognition";

interface ChatTurn {
  role: "assistant" | "user";
  content: string;
}

type Step =
  | { name: "loading" }
  | { name: "error"; message: string }
  | { name: "draft"; session: StartCoachingResult; scenarioMeta: CoachingScenarioMeta }
  | {
      name: "roleplay";
      session: StartCoachingResult;
      scenarioMeta: CoachingScenarioMeta;
      turns: ChatTurn[];
      transcript: string;
      endedEarly: boolean;
    }
  | { name: "results"; result: CoachingResult };

export default function CoachingSessionPage() {
  const params = useParams<{ scenario: string }>();
  const router = useRouter();
  const [step, setStep] = React.useState<Step>({ name: "loading" });
  const [draftText, setDraftText] = React.useState("");
  const [subject, setSubject] = React.useState("");
  const [chatInput, setChatInput] = React.useState("");
  const [isSubmitting, setIsSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [voiceStatus, setVoiceStatus] = React.useState("");
  const scrollRef = useAutoScroll(step.name === "roleplay" ? step.turns.length : 0);
  const voiceStartedAt = React.useRef<number | null>(null);
  const { isSupported: isSpeechSupported, isListening, error: speechError, start, stop } =
    useSpeechRecognition();

  // Voice mode for the roleplay chat turns only (draft submission keeps the browser
  // dictation above — it's a one-shot monologue, not a back-and-forth). Same LiveKit
  // mic-in pattern as Conversation/Scenarios: transcript fills chatInput, never auto-sent.
  const roleplaySessionIdRef = React.useRef<string | null>(null);
  React.useEffect(() => {
    if (step.name === "roleplay") roleplaySessionIdRef.current = step.session.session_id;
  }, [step]);
  const fetchVoiceToken = React.useCallback(() => {
    if (!roleplaySessionIdRef.current) return Promise.reject(new Error("No active session"));
    return getCoachingVoiceToken(roleplaySessionIdRef.current);
  }, []);
  const onTranscript = React.useCallback((text: string) => {
    setChatInput((prev) => (prev.trim() ? `${prev.trim()} ${text}` : text));
  }, []);
  const {
    isVoiceActive,
    isConnectingVoice,
    isStoppingVoice,
    voiceStatus: liveVoiceStatus,
    error: voiceError,
    startVoice,
    stopVoice,
  } = useLiveKitVoice(fetchVoiceToken, onTranscript);
  const { gate, runWithVoiceReadiness } = useVoiceReadinessGate({
    featureName: "Coaching Session",
  });
  React.useEffect(() => {
    if (voiceError) setError(voiceError);
  }, [voiceError]);

  React.useEffect(() => {
    let cancelled = false;
    async function init() {
      try {
        const [{ scenarios }, session] = await Promise.all([
          getCoachingScenarios(),
          startCoachingSession({ scenario: params.scenario }),
        ]);
        if (cancelled) return;
        const meta = scenarios.find((s) => s.key === params.scenario);
        if (!meta) {
          setStep({ name: "error", message: "Unknown scenario." });
          return;
        }
        if (meta.roleplay) {
          setStep({
            name: "roleplay",
            session,
            scenarioMeta: meta,
            turns: session.opening_message
              ? [{ role: "assistant", content: session.opening_message }]
              : [],
            transcript: "",
            endedEarly: false,
          });
        } else {
          setStep({ name: "draft", session, scenarioMeta: meta });
        }
      } catch (err) {
        if (!cancelled) {
          setStep({
            name: "error",
            message: err instanceof ApiError ? err.message : "Couldn't start this session.",
          });
        }
      }
    }
    init();
    return () => {
      cancelled = true;
    };
  }, [params.scenario]);

  async function handleSubmitDraft() {
    if (step.name !== "draft") return;
    setError(null);
    setIsSubmitting(true);
    try {
      const audioFeatures =
        step.session.input_mode === "audio"
          ? {
              transcript: draftText,
              duration_seconds: voiceStartedAt.current
                ? Math.max(0, (performance.now() - voiceStartedAt.current) / 1000)
                : 0,
            }
          : undefined;
      const result = await submitCoachingSession(step.session.session_id, {
        submission: draftText,
        subject: step.scenarioMeta.key === "email_writing" ? subject : undefined,
        audio_features: audioFeatures,
      });
      voiceStartedAt.current = null;
      setVoiceStatus("");
      setStep({ name: "results", result });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setIsSubmitting(false);
    }
  }

  function handleStartDraftVoice() {
    if (step.name !== "draft" || step.session.input_mode !== "audio" || isListening) return;
    voiceStartedAt.current = performance.now();
    setVoiceStatus("Listening...");
    const started = start((text) => {
      setDraftText(text);
      setVoiceStatus("Transcript captured. Review and submit.");
    });
    if (!started) {
      voiceStartedAt.current = null;
      setVoiceStatus("Voice input unavailable.");
      toast.error("Voice input unavailable on this device/browser.");
    }
  }

  function handleStopDraftVoice() {
    stop();
    setVoiceStatus("Voice stopped.");
  }

  async function handleSendChat() {
    if (step.name !== "roleplay" || !chatInput.trim() || isSubmitting) return;
    setError(null);
    setIsSubmitting(true);
    const message = chatInput.trim();
    setChatInput("");
    try {
      const result = await sendRoleplayTurn(step.session.session_id, message);
      setStep({
        ...step,
        turns: [
          ...step.turns,
          { role: "user", content: message },
          { role: "assistant", content: result.reply },
        ],
        transcript: result.transcript,
        endedEarly: result.ended_early,
      });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleEndRoleplay() {
    if (step.name !== "roleplay") return;
    if (isVoiceActive) await stopVoice();
    setError(null);
    setIsSubmitting(true);
    try {
      const audioFeatures =
        step.session.input_mode === "audio"
          ? { transcript: step.transcript, duration_seconds: 0 }
          : undefined;
      const result = await submitCoachingSession(step.session.session_id, {
        submission: step.session.input_mode === "text" ? step.transcript : undefined,
        audio_features: audioFeatures,
      });
      setStep({ name: "results", result });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
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

  if (step.name === "error") {
    return (
      <div className="mx-auto flex max-w-lg flex-col items-center gap-4 rounded-2xl border border-danger/30 bg-danger/5 p-8 text-center">
        <TriangleAlert className="h-6 w-6 text-danger" aria-hidden="true" />
        <p className="text-sm text-foreground">{step.message}</p>
        <Button href="/dashboard/coaching" size="sm">
          Back to Coaching
        </Button>
      </div>
    );
  }

  if (step.name === "draft") {
    return (
      <div className="mx-auto flex max-w-2xl flex-col gap-6">
        {gate}
        <div>
          <h1 className="font-serif text-h2 font-semibold text-foreground">
            {step.session.label}
          </h1>
        </div>
        <div className="rounded-2xl border border-border bg-surface-elevated p-6 shadow-sm">
          <p className="text-sm font-medium text-foreground">Prompt</p>
          <p className="mt-1 text-sm text-muted-foreground">{step.session.prompt}</p>

          <div className="mt-5 flex flex-col gap-4">
            {step.scenarioMeta.key === "email_writing" ? (
              <Input
                label="Subject"
                value={subject}
                onChange={(event) => setSubject(event.target.value)}
              />
            ) : null}
            <Textarea
              label="Your response"
              value={draftText}
              onChange={(event) => setDraftText(event.target.value)}
              rows={8}
              placeholder="Write your response here..."
            />
          </div>

          {step.session.input_mode === "audio" ? (
            <div className="mt-3 flex items-center gap-2">
              <Button
                size="sm"
                variant="outline"
                disabled={!isSpeechSupported}
                onClick={
                  isListening
                    ? handleStopDraftVoice
                    : () => void runWithVoiceReadiness(handleStartDraftVoice)
                }
              >
                {isListening ? "Stop Voice" : "Speak Response"}
              </Button>
              <p className="text-xs text-muted-foreground">
                {isSpeechSupported
                  ? "Audio response sends transcript plus timing."
                  : "Speech recognition not supported in this browser."}
              </p>
            </div>
          ) : null}
          {speechError ? <p className="mt-2 text-sm text-danger">{speechError}</p> : null}
          {voiceStatus ? <p className="mt-2 text-sm text-muted-foreground">{voiceStatus}</p> : null}

          {error ? <p className="mt-3 text-sm text-danger">{error}</p> : null}

          <Button
            size="lg"
            className="mt-4"
            loading={isSubmitting}
            disabled={!draftText.trim()}
            onClick={handleSubmitDraft}
          >
            Submit for Feedback
          </Button>
        </div>
      </div>
    );
  }

  if (step.name === "roleplay") {
    return (
      <div className="mx-auto flex max-w-2xl flex-col gap-4">
        {gate}
        <div className="flex items-center justify-between">
          <h1 className="font-serif text-h2 font-semibold text-foreground">
            {step.session.label}
          </h1>
          <Button
            size="sm"
            variant="outline"
            loading={isSubmitting}
            onClick={handleEndRoleplay}
          >
            End &amp; Get Feedback
          </Button>
        </div>

        <div className="flex flex-col gap-4 rounded-2xl border border-border bg-surface-elevated p-6 shadow-sm">
          <div ref={scrollRef} className="flex max-h-[50vh] flex-col gap-4 overflow-y-auto">
            {step.turns.map((turn, i) => (
              <div
                key={i}
                className={turn.role === "user" ? "ml-auto max-w-[80%]" : "max-w-[80%]"}
              >
                <span className="mb-1 block text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  {turn.role === "user" ? "You" : "Coach"}
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
            ))}
          </div>

          {step.endedEarly ? (
            <p className="text-sm text-warning">
              This scenario ended early. Click &quot;End &amp; Get Feedback&quot; to see your results.
            </p>
          ) : (
            <div className="flex items-center gap-2 border-t border-border pt-4">
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
                className="h-11 flex-1 rounded-xl border border-input bg-surface px-4 text-sm text-foreground placeholder:text-muted-foreground focus:border-primary focus:outline-none focus:ring-2 focus:ring-ring/40"
              />
              <Button
                size="md"
                loading={isSubmitting}
                disabled={!chatInput.trim()}
                onClick={handleSendChat}
              >
                Send
              </Button>
              {isVoiceActive ? (
                <Button
                  size="md"
                  variant="outline"
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
            </div>
          )}
          {liveVoiceStatus ? (
            <p role="status" aria-live="polite" className="text-sm text-muted-foreground">
              {liveVoiceStatus}
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
          {Math.round(result.scores.professional_tone ?? 0)}/100 Professional Tone
        </h1>
        <p className="mt-2 text-sm text-primary-foreground/85">{result.summary}</p>
      </div>

      <div
        className="animate-fade-up rounded-2xl border border-border bg-surface-elevated p-6 shadow-sm"
        style={{ animationDelay: "100ms" }}
      >
        <h2 className="font-serif text-lg font-semibold text-foreground">Scores</h2>
        <div className="mt-4 grid grid-cols-2 gap-4 sm:grid-cols-3">
          {Object.entries(result.scores)
            .filter(([, value]) => value !== null)
            .map(([key, value]) => (
              <div key={key} className="rounded-xl border border-border bg-surface p-4">
                <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  {key.replace(/_/g, " ")}
                </p>
                <p className="mt-1 text-xl font-semibold text-foreground">{Math.round(value ?? 0)}</p>
              </div>
            ))}
        </div>
      </div>

      {result.flags.length > 0 ? (
        <div
          className="animate-fade-up rounded-2xl border border-border bg-surface-elevated p-6 shadow-sm"
          style={{ animationDelay: "180ms" }}
        >
          <h2 className="font-serif text-lg font-semibold text-foreground">Feedback</h2>
          <ul className="mt-3 flex flex-col gap-3">
            {result.flags.map((flag, i) => (
              <li key={i} className="rounded-xl bg-warning/10 p-3 text-sm">
                <p className="font-medium text-foreground">{flag.message ?? flag.type}</p>
                {flag.suggestion ? (
                  <p className="mt-1 text-muted-foreground">{flag.suggestion}</p>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <div
          className="animate-fade-up flex items-center gap-2.5 rounded-2xl border border-success/30 bg-success/10 p-4 text-sm text-success"
          style={{ animationDelay: "180ms" }}
        >
          <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
          No issues flagged — clean, professional communication.
        </div>
      )}

      {result.polished_version ? (
        <div
          className="animate-fade-up rounded-2xl border border-border bg-surface-elevated p-6 shadow-sm"
          style={{ animationDelay: "260ms" }}
        >
          <h2 className="font-serif text-lg font-semibold text-foreground">Polished Version</h2>
          <p className="mt-2 whitespace-pre-wrap text-sm text-muted-foreground">
            {result.polished_version}
          </p>
        </div>
      ) : null}

      <Button
        size="lg"
        variant="outline"
        className="self-center"
        onClick={() => router.push("/dashboard/coaching")}
      >
        Back to Coaching
      </Button>
    </div>
  );
}
