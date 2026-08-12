"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import {
  CheckCircle2,
  ClipboardList,
  Clock,
  Loader2,
  RefreshCw,
  Sparkles,
  TriangleAlert,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { useVoiceReadinessGate } from "@/components/common/VoiceReadinessGate";
import { Textarea } from "@/components/ui/textarea";
import { ApiError } from "@/lib/api";
import {
  attemptSkipAssessment,
  confirmSkipAssessment,
  getResultsSummary,
  isAssessmentQuestion,
  restartAssessment,
  startAssessment,
  submitAssessmentResponse,
  type AssessmentSummary,
  type SkipAttemptResult,
} from "@/lib/assessment";
import { buildVoiceWsUrl, useVoiceSocket } from "@/lib/useVoiceSocket";
import { useAssessmentAccess } from "@/contexts/AssessmentContext";

type Step =
  | { name: "loading" }
  | { name: "already-assessed" }
  | { name: "intro" }
  | { name: "skip-confirm"; result: SkipAttemptResult }
  | {
      name: "question";
      assessmentId: string;
      questionIndex: number;
      totalQuestions: number;
      question: string;
      questionMode: "text" | "audio";
    }
  | { name: "analyzing"; assessmentId: string }
  | { name: "results"; summary: AssessmentSummary };

export default function AssessmentPage() {
  const router = useRouter();
  const { access, isLoading: accessLoading, refresh } = useAssessmentAccess();
  const [step, setStep] = React.useState<Step>({ name: "loading" });
  const [answer, setAnswer] = React.useState("");
  const [isSubmitting, setIsSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  // BAS-US-01: Delay timer for >10s processing notification
  const [analysisDuration, setAnalysisDuration] = React.useState(0);
  const analysisTimerRef = React.useRef<NodeJS.Timeout | null>(null);

  // Decide the initial step exactly once. refresh() (called after finishing
  // the assessment) toggles accessLoading true->false again, which would
  // otherwise re-run this and clobber the "results" step with
  // "already-assessed" right after the user finishes — see hasInitialized.
  const hasInitialized = React.useRef(false);

  // BAS-US-01: Force-close restoration check
  React.useEffect(() => {
    if (accessLoading || hasInitialized.current) return;
    hasInitialized.current = true;

    // Check if there was a pending assessment result saved in localStorage
    const pendingId = localStorage.getItem("speeky_pending_baseline_id");
    if (pendingId) {
      getResultsSummary(pendingId)
        .then((summary) => {
          if ("status" in summary) {
            // BAS-US-01 E-02/E-03: still scoring — keep the pending ID and resume
            // the analyzing/retry flow rather than rendering an incomplete summary.
            fetchResultsWithAnalysisStep(pendingId);
            return;
          }
          localStorage.removeItem("speeky_pending_baseline_id");
          setStep({ name: "results", summary });
        })
        .catch(() => {
          // If fetch fails, clear and check normal access
          localStorage.removeItem("speeky_pending_baseline_id");
          if (
            access?.assessment_status === "COMPLETED" ||
            access?.assessment_status === "PLATEAUED"
          ) {
            setStep({ name: "already-assessed" });
          } else {
            setStep({ name: "intro" });
          }
        });
      return;
    }

    if (
      access?.assessment_status === "COMPLETED" ||
      access?.assessment_status === "PLATEAUED"
    ) {
      setStep({ name: "already-assessed" });
    } else {
      setStep({ name: "intro" });
    }
  }, [accessLoading, access]);
  const voiceStartedAt = React.useRef<number | null>(null);
  const voiceAnswerUsed = React.useRef(false);
  const voiceTurns = React.useRef<
    {
      transcript: string;
      duration_seconds: number;
      word_timings: { word: string; start: number; end: number }[];
    }[]
  >([]);

  // WebSocket voice mode — same proven pipeline as AI Conversation (server-side Silero
  // VAD + faster-whisper in backend/lib/voice_ws.py), replacing the browser Web Speech
  // API which needed a secure context and was Chromium-only. The socket's path is the
  // assessment_id, so getWsUrl must read the *current* one — hence the ref, since
  // assessmentId lives in step state and this hook is at the top level.
  const assessmentIdRef = React.useRef<string | null>(null);
  const getWsUrl = React.useCallback(() => {
    const id = assessmentIdRef.current;
    if (!id) return null;
    return buildVoiceWsUrl(`/assessment/${id}/voice-ws`);
  }, []);
  const {
    isVoiceActive,
    isConnectingVoice,
    isStoppingVoice,
    voiceStatus,
    error: voiceError,
    startVoice,
    stopVoice,
  } = useVoiceSocket(getWsUrl, (text, features) => {
    // Accumulate every VAD utterance until the user hits Stop, instead of overwriting
    // with the latest sentence. The backend sends one final transcript per utterance
    // (backend/lib/voice_ws.py), so a natural pause used to drop everything said before it.
    // Appending (same as AI Conversation) keeps the whole spoken answer and shows it
    // growing live. Reset happens on Stop/submit/new-question via setAnswer("").
    setAnswer((prev) => (prev.trim() ? `${prev.trim()} ${text}` : text));
    voiceAnswerUsed.current = true;
    // Keep each utterance's word timings separately — the backend needs them per-turn to
    // measure pauses within speech without counting the silence between utterances.
    // Previously only a wall-clock duration was sent, which left the backend with no
    // pause data at all and made every spoken answer look perfectly fluent.
    const timings = features?.word_timings;
    if (Array.isArray(timings) && timings.length > 0) {
      voiceTurns.current.push({
        transcript: text,
        duration_seconds: features?.duration_seconds ?? 0,
        word_timings: timings,
      });
    }
  });
  const { gate, runWithVoiceReadiness } = useVoiceReadinessGate({
    featureName: "Baseline Assessment",
  });

  async function handleStart() {
    setError(null);
    setIsSubmitting(true);
    try {
      const result = await startAssessment();
      // A previous attempt may have had every answer saved but never finished scoring;
      // the server retries it and returns a status instead of a question. Hand those to
      // the analyzing flow (which already polls/retries) rather than rendering an
      // undefined question.
      if (!isAssessmentQuestion(result)) {
        await fetchResultsWithAnalysisStep(result.assessment_id);
        return;
      }
      setStep({
        name: "question",
        assessmentId: result.assessment_id,
        questionIndex: result.question_index,
        totalQuestions: result.total_questions,
        question: result.current_question,
        questionMode: result.question_mode,
      });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setIsSubmitting(false);
    }
  }

  /** Escape hatch when an attempt can never finish scoring: throw the unfinished
   *  attempt away and begin a clean one, so the account can't stay locked forever. */
  async function handleRestart() {
    setError(null);
    setIsSubmitting(true);
    try {
      if (analysisTimerRef.current) clearInterval(analysisTimerRef.current);
      localStorage.removeItem("speeky_pending_baseline_id");
      const result = await restartAssessment();
      setStep({
        name: "question",
        assessmentId: result.assessment_id,
        questionIndex: result.question_index,
        totalQuestions: result.total_questions,
        question: result.current_question,
        questionMode: result.question_mode,
      });
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Couldn't restart the assessment.",
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleSkipRequest() {
    setError(null);
    setIsSubmitting(true);
    try {
      const result = await attemptSkipAssessment();
      setStep({ name: "skip-confirm", result });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleConfirmSkip() {
    setError(null);
    setIsSubmitting(true);
    try {
      await confirmSkipAssessment();
      await refresh();
      router.push("/dashboard");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setIsSubmitting(false);
    }
  }

  async function fetchResultsWithAnalysisStep(assessmentId: string) {
    setStep({ name: "analyzing", assessmentId });
    setAnalysisDuration(0);

    // Track duration for >10s reassurance indicator
    analysisTimerRef.current = setInterval(() => {
      setAnalysisDuration((prev) => prev + 1);
    }, 1000);

    try {
      // Save pending ID to localStorage for force-close restoration
      localStorage.setItem("speeky_pending_baseline_id", assessmentId);

      const summary = await getResultsSummary(assessmentId);
      if ("status" in summary) {
        // BAS-US-01 E-02: scoring failed server-side but responses are safe — keep the
        // pending ID (so a force-close still recovers) and retry automatically instead
        // of surfacing this as a dead-end error.
        if (analysisTimerRef.current) clearInterval(analysisTimerRef.current);
        setError(summary.message);
        setTimeout(() => fetchResultsWithAnalysisStep(assessmentId), 4000);
        return;
      }
      if (analysisTimerRef.current) clearInterval(analysisTimerRef.current);
      localStorage.removeItem("speeky_pending_baseline_id");
      await refresh();
      setStep({ name: "results", summary });
    } catch (err) {
      if (analysisTimerRef.current) clearInterval(analysisTimerRef.current);
      // BAS-US-01 Exception: Scoring engine failure / retry
      setError(
        "Scoring engine is still finalizing your results. Please retry or refresh.",
      );
    }
  }

  async function handleSubmitAnswer() {
    if (step.name !== "question" || !answer.trim()) return;
    setError(null);
    setIsSubmitting(true);
    try {
      const result = await submitAssessmentResponse(step.assessmentId, {
        text_data: answer.trim(),
        audio_features:
          step.questionMode === "audio" && voiceAnswerUsed.current
            ? {
                // Wall-clock stays as the fallback for the case where no utterance
                // carried timings; `turns` is what the scorer actually prefers.
                duration_seconds: voiceStartedAt.current
                  ? Math.max(
                      0,
                      (performance.now() - voiceStartedAt.current) / 1000,
                    )
                  : 0,
                turns: voiceTurns.current,
              }
            : undefined,
      });
      setAnswer("");
      voiceStartedAt.current = null;
      voiceAnswerUsed.current = false;
      voiceTurns.current = [];
      if (isVoiceActive) void stopVoice();
      if (result.status === "completed") {
        await fetchResultsWithAnalysisStep(step.assessmentId);
      } else if (result.status === "processing") {
        // BAS-US-01 E-02: scoring failed on this final submission — reuse the same
        // analyzing/auto-retry flow the polling path already handles correctly,
        // instead of falling through to the in-progress branch below with no
        // next_question/question_index to show.
        await fetchResultsWithAnalysisStep(step.assessmentId);
      } else {
        setStep({
          ...step,
          questionIndex: result.question_index,
          question: result.next_question ?? "",
          questionMode: result.next_question_mode ?? "text",
        });
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleStartVoice() {
    if (
      step.name !== "question" ||
      step.questionMode !== "audio" ||
      isVoiceActive
    )
      return;

    // Wall-clock start for the audio_features.duration_seconds sent on submit (routes the
    // answer through the backend AUDIO scoring pipeline). Marked used the moment a
    // transcript lands (see the onTranscript callback above).
    voiceStartedAt.current = performance.now();
    voiceTurns.current = [];
    await startVoice();
  }

  function handleStopVoice() {
    void stopVoice();
  }

  if (step.name === "loading") {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  if (step.name === "analyzing") {
    return (
      <div className="mx-auto flex max-w-lg flex-col items-center gap-6 rounded-2xl border border-border bg-surface-elevated p-10 text-center shadow-sm">
        <div className="relative flex h-16 w-16 items-center justify-center rounded-full bg-primary/10 text-primary">
          <Loader2 className="h-8 w-8 animate-spin" />
        </div>
        <div className="flex flex-col gap-2">
          <h1 className="font-serif text-h2 font-semibold text-foreground">
            Analyzing your responses...
          </h1>
          <p className="text-sm text-muted-foreground">
            Evaluating fluency, confidence, vocabulary diversity, and speech
            articulation.
          </p>
        </div>

        {/* BAS-US-01: Reassuring animated indicator after 10+ seconds */}
        {analysisDuration >= 10 && (
          <div className="flex items-center gap-2.5 rounded-xl border border-primary/20 bg-primary/5 px-4 py-3 text-xs font-medium text-primary animate-fade-in">
            <Clock className="h-4 w-4 shrink-0 animate-pulse" />
            <span>
              Taking a bit longer than usual — finalizing your personalized
              skill profile...
            </span>
          </div>
        )}

        {error && (
          <div className="flex flex-col gap-3 rounded-xl border border-warning/30 bg-warning/10 p-4 text-sm text-foreground">
            <p>{error}</p>
            <div className="flex flex-wrap justify-center gap-2">
              <Button
                size="sm"
                variant="outline"
                onClick={() => fetchResultsWithAnalysisStep(step.assessmentId)}
              >
                <RefreshCw className="mr-1.5 h-3.5 w-3.5" />
                Retry Fetching Results
              </Button>
              {/* Last resort if scoring can never finish — otherwise the account would
                  stay locked behind an assessment that cannot complete. */}
              <Button
                size="sm"
                variant="ghost"
                onClick={handleRestart}
                loading={isSubmitting}
              >
                Start the assessment over
              </Button>
            </div>
          </div>
        )}
      </div>
    );
  }

  if (step.name === "already-assessed") {
    return (
      <div className="mx-auto flex max-w-lg flex-col items-center gap-4 rounded-2xl border border-border bg-surface-elevated p-8 text-center shadow-sm">
        <span className="flex h-12 w-12 items-center justify-center rounded-full bg-secondary text-primary">
          <CheckCircle2 className="h-6 w-6" aria-hidden="true" />
        </span>
        <h1 className="font-serif text-h2 font-semibold text-foreground">
          You&apos;ve already completed your baseline assessment
        </h1>
        <p className="text-sm text-muted-foreground">
          Head to your Profile to see your results or request a re-assessment.
        </p>
        <Button href="/dashboard/profile" size="sm">
          Go to Profile
        </Button>
      </div>
    );
  }

  if (step.name === "intro") {
    return (
      <div className="mx-auto flex max-w-lg flex-col items-center gap-5 rounded-2xl border border-border bg-surface-elevated p-8 text-center shadow-sm">
        {gate}
        <span className="flex h-12 w-12 items-center justify-center rounded-full bg-secondary text-primary">
          <ClipboardList className="h-6 w-6" aria-hidden="true" />
        </span>
        <div className="flex flex-col gap-2">
          <h1 className="font-serif text-h2 font-semibold text-foreground">
            Baseline Communication Assessment
          </h1>
          <p className="text-sm text-muted-foreground">
            A short check-in sets your starting confidence score and
            personalizes AI Conversation Practice, Interview Coach, and
            Scenario-Based Learning for you.
          </p>
        </div>
        {error ? <p className="text-sm text-danger">{error}</p> : null}
        <div className="flex flex-col items-center gap-3">
          <Button
            size="lg"
            loading={isSubmitting}
            onClick={() => void runWithVoiceReadiness(handleStart)}
          >
            Start Assessment
          </Button>
          <button
            type="button"
            onClick={handleSkipRequest}
            disabled={isSubmitting}
            className="text-sm font-medium text-muted-foreground hover:text-foreground disabled:opacity-50"
          >
            Skip for now
          </button>
        </div>
      </div>
    );
  }

  if (step.name === "skip-confirm") {
    return (
      <div className="mx-auto flex max-w-lg flex-col items-center gap-5 rounded-2xl border border-warning/30 bg-warning/10 p-8 text-center shadow-sm">
        <span className="flex h-12 w-12 items-center justify-center rounded-full bg-warning/20 text-warning">
          <TriangleAlert className="h-6 w-6" aria-hidden="true" />
        </span>
        <div className="flex flex-col gap-2">
          <h1 className="font-serif text-xl font-semibold text-foreground">
            Skip the baseline assessment?
          </h1>
          <p className="text-sm text-foreground">{step.result.message}</p>
        </div>
        {error ? <p className="text-sm text-danger">{error}</p> : null}
        <div className="flex flex-col items-center gap-3 sm:flex-row">
          <Button size="md" onClick={() => setStep({ name: "intro" })}>
            Return to Assessment
          </Button>
          {step.result.can_skip ? (
            <Button
              size="md"
              variant="outline"
              loading={isSubmitting}
              onClick={handleConfirmSkip}
            >
              Skip Anyway
            </Button>
          ) : null}
        </div>
      </div>
    );
  }

  if (step.name === "question") {
    // Keep the token-fetch closure pointed at the live assessment (room name == id).
    assessmentIdRef.current = step.assessmentId;
    const progress = Math.round(
      (step.questionIndex / step.totalQuestions) * 100,
    );
    return (
      <div className="mx-auto flex max-w-xl flex-col gap-6">
        {gate}
        <div>
          <div className="flex items-center justify-between text-xs font-medium text-muted-foreground">
            <span>
              Question {step.questionIndex + 1} of {step.totalQuestions}
            </span>
            <span>{progress}%</span>
          </div>
          <div className="mt-2 h-1.5 w-full rounded-full bg-muted">
            <div
              className="h-1.5 rounded-full bg-primary transition-all"
              style={{ width: `${progress}%` }}
            />
          </div>
        </div>

        <div className="rounded-2xl border border-border bg-surface-elevated p-6 shadow-sm sm:p-8">
          <p className="font-serif text-lg leading-relaxed text-foreground">
            {step.question}
          </p>
          <div className="mt-6">
            <Textarea
              label="Your answer"
              value={answer}
              onChange={(event) => setAnswer(event.target.value)}
              rows={5}
              placeholder="Type your response here..."
            />
          </div>
          {step.questionMode === "audio" ? (
            <div className="mt-3 flex items-center gap-2">
              <Button
                size="sm"
                variant="outline"
                className={isVoiceActive ? "voice-listening-button" : undefined}
                loading={isConnectingVoice || isStoppingVoice}
                disabled={isConnectingVoice || isStoppingVoice}
                onClick={
                  isVoiceActive
                    ? handleStopVoice
                    : () => void runWithVoiceReadiness(handleStartVoice)
                }
              >
                {isConnectingVoice
                  ? "Connecting..."
                  : isVoiceActive
                    ? "Stop Voice"
                    : "Speak Answer"}
              </Button>
              <p className="text-xs text-muted-foreground">
                Speak your answer — we transcribe it for you to review before
                you continue.
              </p>
            </div>
          ) : null}
          {voiceError ? (
            <p className="mt-2 text-sm text-danger">{voiceError}</p>
          ) : null}
          {voiceStatus ? (
            <p className="mt-2 text-sm text-muted-foreground">{voiceStatus}</p>
          ) : null}
          {error ? <p className="mt-3 text-sm text-danger">{error}</p> : null}
          <Button
            size="lg"
            className="mt-4"
            loading={isSubmitting}
            disabled={!answer.trim()}
            onClick={handleSubmitAnswer}
          >
            Continue
          </Button>
        </div>
      </div>
    );
  }

  // step.name === "results"
  const { summary } = step;
  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-6">
      <div className="animate-fade-up rounded-2xl border border-border bg-gradient-to-br from-primary to-primary-hover p-8 text-center text-primary-foreground shadow-sm">
        <Sparkles
          className="mx-auto h-6 w-6 animate-fade-in"
          aria-hidden="true"
        />
        <h1 className="mt-3 font-serif text-h2 font-semibold">
          {summary.positive_framing.title}
        </h1>
        <p className="mt-2 text-sm text-primary-foreground/85">
          {summary.positive_framing.subtitle}
        </p>
        <p className="mx-auto mt-4 max-w-md text-3xl font-bold tracking-tight">
          {summary.confidence_score.display}
        </p>
        <p className="mt-1 text-sm text-primary-foreground/85">
          {summary.confidence_score.message}
        </p>
      </div>

      <div
        className="animate-fade-up rounded-2xl border border-border bg-surface-elevated p-6 shadow-sm"
        style={{ animationDelay: "120ms" }}
      >
        <h2 className="font-serif text-lg font-semibold text-foreground">
          Skill Breakdown
        </h2>
        <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-3">
          {Object.values(summary.skill_breakdown).map((skill) => (
            <div
              key={skill.label}
              className="rounded-xl border border-border bg-surface p-4"
            >
              <div className="flex items-center justify-between text-xs font-medium text-muted-foreground">
                <span>{skill.label}</span>
                <span className="text-foreground">{skill.display}</span>
              </div>
              <p className="mt-2 text-xs text-muted-foreground">
                {skill.description}
              </p>
            </div>
          ))}
        </div>
        <p className="mt-4 text-sm text-muted-foreground">
          {summary.positive_framing.highlight}
        </p>
      </div>

      <div
        className="animate-fade-up rounded-2xl border border-border bg-surface-elevated p-6 shadow-sm"
        style={{ animationDelay: "220ms" }}
      >
        <h2 className="font-serif text-lg font-semibold text-foreground">
          Next Steps
        </h2>
        <ul className="mt-3 flex flex-col gap-2">
          {summary.next_steps.map((step_, i) => (
            <li
              key={i}
              className="flex items-start gap-2.5 text-sm text-muted-foreground"
            >
              <CheckCircle2
                className="mt-0.5 h-4 w-4 shrink-0 text-success"
                aria-hidden="true"
              />
              {step_}
            </li>
          ))}
        </ul>
      </div>

      <Button href="/dashboard" size="lg" className="self-center">
        Start Learning
      </Button>
    </div>
  );
}
