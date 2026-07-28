"use client";

import * as React from "react";
import { useParams, useRouter } from "next/navigation";
import { toast } from "react-toastify";
import { Coffee, Mic, MicOff, Pause, Play, Share2, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { AiCoachAvatar } from "@/components/common/AiCoachAvatar";
import { UserChatAvatar } from "@/components/common/UserChatAvatar";
import { useVoiceReadinessGate } from "@/components/common/VoiceReadinessGate";
import { Modal } from "@/components/ui/modal";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { cn } from "@/lib/utils";
import { ApiError } from "@/lib/api";
import { useAutoScroll } from "@/lib/useAutoScroll";
import { useLiveKitVoice } from "@/lib/useLiveKitVoice";
import {
  endInterviewSession,
  getInterviewCoachVoiceToken,
  pauseInterviewSession,
  resumeInterviewSession,
  shareInterviewReview,
  submitInterviewAnswer,
  takeInterviewBreak,
  type InterviewMode,
  type SessionFeedback,
} from "@/lib/interviewCoach";
import {
  getInterruptionStatus,
  logInterruption,
  recordSessionMemory,
  resumeInterruptedSession,
} from "@/lib/sessionMemory";
import { getInterviewCoachFillerWords } from "@/lib/fillerWords";
import { FillerWordsScorecardSection } from "@/components/dashboard/public-speaking/FillerWordsScorecardSection";

interface Turn {
  speaker: string;
  question: string;
  answer: string | null;
  flags: string[];
}

export default function InterviewCoachSessionPage() {
  const params = useParams<{ sessionId: string }>();
  const router = useRouter();
  const sessionId = params.sessionId;
  const storageKey = `interview-session-${sessionId}`;

  const [mode, setMode] = React.useState<InterviewMode>("standard");
  const [turns, setTurns] = React.useState<Turn[]>([]);
  const scrollRef = useAutoScroll(turns.length);
  const [allFlags, setAllFlags] = React.useState<string[]>([]);
  const [answer, setAnswer] = React.useState("");
  const [status, setStatus] = React.useState<"active" | "paused">("active");
  const [isSubmitting, setIsSubmitting] = React.useState(false);
  const [isEnding, setIsEnding] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [feedback, setFeedback] = React.useState<SessionFeedback | null>(null);
  const [resumeBanner, setResumeBanner] = React.useState<string | null>(null);

  const questionShownAt = React.useRef<number>(Date.now());
  const firstKeystrokeAt = React.useRef<number | null>(null);
  // Mirrors `answer` for the interruption listeners below — those are set up
  // once (deps: [sessionId]) so they'd otherwise close over a stale "" from
  // mount forever and never actually capture what the user typed.
  const answerRef = React.useRef("");
  React.useEffect(() => {
    answerRef.current = answer;
  }, [answer]);

  // Voice mode: same LiveKit mic-in pattern as Conversation/Scenarios/Coaching —
  // transcript fills the answer input for the user to review/edit, never auto-sent.
  const fetchVoiceToken = React.useCallback(
    () => getInterviewCoachVoiceToken(sessionId),
    [sessionId],
  );
  const onTranscript = React.useCallback((text: string) => {
    if (!firstKeystrokeAt.current) firstKeystrokeAt.current = Date.now();
    setAnswer((prev) => (prev.trim() ? `${prev.trim()} ${text}` : text));
  }, []);
  const {
    isVoiceActive,
    isConnectingVoice,
    isStoppingVoice,
    voiceStatus,
    error: voiceError,
    startVoice,
    stopVoice,
  } = useLiveKitVoice(fetchVoiceToken, onTranscript);
  const { gate, runWithVoiceReadiness } = useVoiceReadinessGate({
    featureName: "Interview Coach",
  });
  React.useEffect(() => {
    if (voiceError) setError(voiceError);
  }, [voiceError]);

  // Rehydrate from sessionStorage (no GET-session endpoint exists to refetch
  // from the backend on reload — see lib/interviewCoach.ts).
  React.useEffect(() => {
    const raw = sessionStorage.getItem(storageKey);
    if (raw) {
      const parsed = JSON.parse(raw);
      setMode(parsed.mode);
      setTurns(parsed.turns);
    }
  }, [storageKey]);

  React.useEffect(() => {
    if (turns.length > 0) {
      sessionStorage.setItem(storageKey, JSON.stringify({ mode, turns }));
    }
  }, [turns, mode, storageKey]);

  // US-28: interruption detection + resume-on-return.
  React.useEffect(() => {
    getInterruptionStatus(sessionId)
      .then((status_) => {
        if (status_.has_active_interruption) {
          resumeInterruptedSession(sessionId)
            .then((result) => {
              setResumeBanner(result.message);
              if (result.partial_answer_text) setAnswer(result.partial_answer_text);
            })
            .catch(() => {});
        }
      })
      .catch(() => {});

    function handleVisibility() {
      if (document.hidden) {
        logInterruption({
          session_id: sessionId,
          session_type: "interview_coach",
          interruption_type: "app_backgrounded",
          partial_answer_text: answerRef.current || undefined,
        }).catch(() => {});
      }
    }
    function handleOffline() {
      logInterruption({
        session_id: sessionId,
        session_type: "interview_coach",
        interruption_type: "connectivity_drop",
        partial_answer_text: answerRef.current || undefined,
      }).catch(() => {});
    }
    document.addEventListener("visibilitychange", handleVisibility);
    window.addEventListener("offline", handleOffline);
    return () => {
      document.removeEventListener("visibilitychange", handleVisibility);
      window.removeEventListener("offline", handleOffline);
    };
  }, [sessionId]);

  async function finishSession() {
    if (isVoiceActive) await stopVoice();
    setIsEnding(true);
    try {
      const result = await endInterviewSession(sessionId);
      setFeedback(result);
      recordSessionMemory({
        session_id: sessionId,
        session_type: "interview_coach",
        flags_seen: allFlags,
        topic_or_mode: mode,
        overall_score: result.overall_score,
      }).catch(() => {});
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setIsEnding(false);
    }
  }

  async function handleSubmitAnswer() {
    if (!answer.trim() || isSubmitting) return;
    setError(null);
    setIsSubmitting(true);

    const now = Date.now();
    const silenceBefore = Math.round(((firstKeystrokeAt.current ?? now) - questionShownAt.current) / 1000);
    const duration = Math.round((now - (firstKeystrokeAt.current ?? now)) / 1000);
    const answerText = answer.trim();

    setTurns((prev) => {
      const next = [...prev];
      next[next.length - 1] = { ...next[next.length - 1], answer: answerText };
      return next;
    });
    setAnswer("");
    firstKeystrokeAt.current = null;

    try {
      const result = await submitInterviewAnswer(sessionId, {
        answer_text: answerText,
        response_duration_seconds: Math.max(duration, 0),
        silence_before_seconds: Math.max(silenceBefore, 0),
      });
      setAllFlags((prev) => [...prev, ...result.flags]);

      if (result.session_complete) {
        await finishSession();
        return;
      }
      if (result.next_question) {
        questionShownAt.current = Date.now();
        setTurns((prev) => [
          ...prev,
          { speaker: result.next_speaker ?? "AI", question: result.next_question!, answer: null, flags: [] },
        ]);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handlePauseResume() {
    try {
      if (status === "active") {
        if (isVoiceActive) await stopVoice();
        await pauseInterviewSession(sessionId);
        setStatus("paused");
      } else {
        await resumeInterviewSession(sessionId);
        setStatus("active");
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    }
  }

  async function handleTakeBreak() {
    try {
      await takeInterviewBreak(sessionId);
    } catch {
      toast.error("Couldn't start a break. Try again.");
    }
  }

  if (feedback) {
    return <ResultsView sessionId={sessionId} feedback={feedback} />;
  }

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-4">
      {gate}
      <div className="flex items-center justify-between">
        <h1 className="font-serif text-h2 font-semibold capitalize text-foreground">
          {mode.replace("_", " ")} Interview
        </h1>
        <div className="flex items-center gap-2">
          <Button size="sm" variant="outline" onClick={handleTakeBreak}>
            <Coffee className="h-4 w-4" aria-hidden="true" />
          </Button>
          <Button size="sm" variant="outline" onClick={handlePauseResume}>
            {status === "active" ? (
              <Pause className="h-4 w-4" aria-hidden="true" />
            ) : (
              <Play className="h-4 w-4" aria-hidden="true" />
            )}
            {status === "active" ? "Pause" : "Resume"}
          </Button>
          <Button size="sm" variant="danger" loading={isEnding} onClick={finishSession}>
            End Interview
          </Button>
        </div>
      </div>

      {resumeBanner ? (
        <div className="rounded-xl bg-secondary px-4 py-3 text-sm text-secondary-foreground">
          {resumeBanner}
        </div>
      ) : null}

      <div className="flex flex-col gap-4 rounded-2xl border border-border bg-surface-elevated p-6 shadow-sm">
        <div ref={scrollRef} className="flex max-h-[55vh] flex-col gap-4 overflow-y-auto">
          {turns.map((turn, i) => (
            <div key={i} className="flex flex-col gap-2">
              <div className="flex max-w-[88%] items-start gap-2">
                <AiCoachAvatar className="mt-5" />
                <div className="min-w-0 flex-1">
                  <span className="mb-1 block text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                    {turn.speaker}
                  </span>
                  <div className="rounded-xl rounded-tl-sm bg-secondary px-4 py-3 text-sm text-secondary-foreground">
                    {turn.question}
                  </div>
                </div>
              </div>
              {turn.answer ? (
                <div className="ml-auto flex max-w-[88%] items-start gap-2">
                  <div className="min-w-0 flex-1">
                    <span className="mb-1 block text-right text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                      You
                    </span>
                    <div className="rounded-xl rounded-tr-sm bg-primary px-4 py-3 text-sm text-primary-foreground">
                      {turn.answer}
                    </div>
                  </div>
                  <UserChatAvatar className="mt-5" />
                </div>
              ) : null}
            </div>
          ))}
        </div>

        {error ? <p className="text-sm text-danger">{error}</p> : null}

        {status === "paused" ? (
          <p className="text-sm text-warning">Session paused — click Resume to continue.</p>
        ) : (
          <div className="flex items-center gap-2 border-t border-border pt-4">
            <input
              type="text"
              value={answer}
              onChange={(event) => {
                if (!firstKeystrokeAt.current && event.target.value) {
                  firstKeystrokeAt.current = Date.now();
                }
                setAnswer(event.target.value);
              }}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  handleSubmitAnswer();
                }
              }}
              placeholder="Type your answer..."
              className="h-11 flex-1 rounded-xl border border-input bg-surface px-4 text-sm text-foreground placeholder:text-muted-foreground focus:border-primary focus:outline-none focus:ring-2 focus:ring-ring/40"
            />
            <Button size="md" loading={isSubmitting} disabled={!answer.trim()} onClick={handleSubmitAnswer}>
              Send
            </Button>
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
          </div>
        )}
        {voiceStatus ? (
          <p role="status" aria-live="polite" className="text-sm text-muted-foreground">
            {voiceStatus}
          </p>
        ) : null}
      </div>
    </div>
  );
}

function ResultsView({ sessionId, feedback }: { sessionId: string; feedback: SessionFeedback }) {
  const router = useRouter();
  const [shareOpen, setShareOpen] = React.useState(false);
  const [recipient, setRecipient] = React.useState("");
  const [note, setNote] = React.useState("");
  const [accessLevel, setAccessLevel] = React.useState<"transcript_only" | "full">("transcript_only");
  const [contentConfirmed, setContentConfirmed] = React.useState(false);
  const [isSharing, setIsSharing] = React.useState(false);
  const [shareLink, setShareLink] = React.useState<string | null>(null);
  const [shareError, setShareError] = React.useState<string | null>(null);

  async function handleShare() {
    if (!recipient.trim()) {
      setShareError("Enter a recipient email or username.");
      return;
    }
    setShareError(null);
    setIsSharing(true);
    try {
      const result = await shareInterviewReview({
        session_id: sessionId,
        recipient_email_or_id: recipient.trim(),
        note: note.trim() || undefined,
        access_level: accessLevel,
        content_confirmed: accessLevel === "full" ? contentConfirmed : undefined,
      });
      const fullUrl = `${window.location.origin}/dashboard/interview-coach/reviews/${result.share_id}`;
      setShareLink(fullUrl);
    } catch (err) {
      setShareError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setIsSharing(false);
    }
  }

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-6">
      <div className="animate-fade-up rounded-2xl border border-border bg-gradient-to-br from-primary to-primary-hover p-8 text-center text-primary-foreground shadow-sm">
        <Sparkles className="mx-auto h-6 w-6" aria-hidden="true" />
        <h1 className="mt-3 font-serif text-h2 font-semibold">Overall Score: {feedback.overall_score}</h1>
        <p className="mt-2 text-sm text-primary-foreground/85">{feedback.closing_message}</p>
      </div>

      {feedback.round_scorecards.map((card, i) => (
        <div
          key={i}
          className="animate-fade-up rounded-2xl border border-border bg-surface-elevated p-6 shadow-sm"
          style={{ animationDelay: `${100 + i * 80}ms` }}
        >
          <h2 className="font-serif text-lg font-semibold capitalize text-foreground">
            {card.round_type.replace("_", " ")}
          </h2>
          <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3">
            {Object.entries(card.scores).map(([key, value]) => (
              <div key={key} className="rounded-xl border border-border bg-surface p-3">
                <p className="text-xs font-medium capitalize text-muted-foreground">{key.replace(/_/g, " ")}</p>
                <p className="mt-1 text-lg font-semibold text-foreground">{Math.round(value)}</p>
              </div>
            ))}
          </div>
          <p className="mt-3 text-sm text-muted-foreground">{card.summary}</p>
        </div>
      ))}

      <div className="animate-fade-up rounded-2xl border border-border bg-surface-elevated p-6 shadow-sm">
        <h2 className="font-serif text-lg font-semibold text-foreground">Actionable Script</h2>
        <p className="mt-2 whitespace-pre-wrap text-sm text-muted-foreground">{feedback.actionable_script}</p>
      </div>

      {/* PSC-US-08: Filler word breakdown & timeline, same scorecard as Public Speaking */}
      <FillerWordsScorecardSection sessionId={sessionId} fetchFn={getInterviewCoachFillerWords} />

      <div className="flex flex-wrap items-center justify-center gap-3">
        <Button size="lg" variant="outline" onClick={() => setShareOpen(true)}>
          <Share2 className="h-4 w-4" aria-hidden="true" />
          Share for Peer Review
        </Button>
        <Button size="lg" onClick={() => router.push("/dashboard/interview-coach")}>
          Start Another Interview
        </Button>
      </div>

      <Modal
        open={shareOpen}
        onClose={() => {
          setShareOpen(false);
          setShareLink(null);
          setShareError(null);
        }}
        title="Share for Peer Review"
        description="Anyone with the link can view comments and leave feedback."
      >
        {shareLink ? (
          <div className="flex flex-col gap-3">
            <p className="text-sm text-foreground">Share link created:</p>
            <div className="flex items-center gap-2">
              <input
                readOnly
                value={shareLink}
                className="h-10 flex-1 rounded-lg border border-input bg-surface px-3 text-xs text-foreground"
              />
              <Button
                size="sm"
                onClick={() => {
                  navigator.clipboard.writeText(shareLink);
                  toast.success("Link copied to clipboard.");
                }}
              >
                Copy
              </Button>
            </div>
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            <Input
              label="Recipient email or username"
              value={recipient}
              onChange={(event) => setRecipient(event.target.value)}
            />
            <Input
              label="Note (optional)"
              value={note}
              onChange={(event) => setNote(event.target.value)}
            />
            <div className="flex gap-2">
              {(["transcript_only", "full"] as const).map((level) => (
                <button
                  key={level}
                  type="button"
                  onClick={() => setAccessLevel(level)}
                  className={cn(
                    "rounded-full px-3 py-1.5 text-xs font-medium transition-colors",
                    accessLevel === level
                      ? "bg-primary text-primary-foreground"
                      : "bg-surface text-muted-foreground hover:bg-muted",
                  )}
                >
                  {level === "transcript_only" ? "Transcript only" : "Full (audio/video)"}
                </button>
              ))}
            </div>
            {accessLevel === "full" ? (
              <Checkbox
                checked={contentConfirmed}
                onChange={(event) => setContentConfirmed(event.target.checked)}
                label="I've reviewed the content and confirm it's OK to share in full."
              />
            ) : null}
            {shareError ? <p className="text-sm text-danger">{shareError}</p> : null}
            <Button loading={isSharing} onClick={handleShare}>
              Create Share Link
            </Button>
          </div>
        )}
      </Modal>
    </div>
  );
}
