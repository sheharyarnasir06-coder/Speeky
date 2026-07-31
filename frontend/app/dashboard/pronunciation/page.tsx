"use client";

import * as React from "react";
import { toast } from "react-toastify";
import {
  CheckCircle2,
  Lock,
  Mic,
  Sparkles,
  Square,
  TriangleAlert,
  Volume2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { useVoiceReadinessGate } from "@/components/common/VoiceReadinessGate";
import { WordByWordDisplay } from "@/components/dashboard/WordByWordDisplay";
import { ApiError } from "@/lib/api";
import { useAssessmentAccess } from "@/contexts/AssessmentContext";
import { useAudioRecorder } from "@/lib/useAudioRecorder";
import { cn } from "@/lib/utils";
import {
  checkResumableSession,
  endSession,
  fetchPronunciationTts,
  interruptSession,
  resumeSession,
  retryWord,
  startPronunciationSession,
  submitAttempt,
  type AttemptResult,
  type PronunciationSession,
  type ResumeCheck,
  type RetryResult,
  type SessionSummary,
} from "@/lib/pronunciation";
import { useActiveSessions } from "@/contexts/ActiveSessionsContext";

type Step =
  | { name: "loading" }
  | { name: "error"; message: string }
  | { name: "resume-prompt"; check: ResumeCheck }
  | { name: "practice"; session: PronunciationSession }
  | {
      name: "attempt-result";
      session: PronunciationSession;
      result: AttemptResult;
    }
  | { name: "summary"; summary: SessionSummary };

// Only a fully correct read of the whole sentence advances (message_key "scored_ok").
// Everything else — silence, off-script, partial, code-switch, or a word wrong within
// an otherwise-scored attempt ("needs_retry") — asks for the same sentence again.
const NEGATIVE_MESSAGE_KEYS = new Set([
  "no_speech_detected",
  "mic_troubleshoot",
  "too_quiet",
  "off_script",
  "off_script_repeated",
  "needs_retry",
]);

export default function PronunciationCoachPage() {
  const { access } = useAssessmentAccess();
  const isUnlocked = access?.access_level === "full_access";
  const { refresh: refreshActiveSessions } = useActiveSessions();

  const [step, setStep] = React.useState<Step>({ name: "loading" });
  const [isSubmitting, setIsSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const recorder = useAudioRecorder();
  const { gate, runWithVoiceReadiness } = useVoiceReadinessGate({
    featureName: "Pronunciation Coach",
  });

  // 3-strikes "hear pronunciation": tracks how many consecutive attempts of the
  // current sentence a given word has come back non-correct on. Purely a frontend
  // concern (see get_word_pronunciation_audio's docstring) — the backend endpoint
  // already exists and needed no changes. Resets whenever the sentence changes.
  const wrongStreakRef = React.useRef<Record<string, number>>({});
  const lastSentenceRef = React.useRef<string | null>(null);
  const [stuckWords, setStuckWords] = React.useState<string[]>([]);
  // One-time attention arrow — set the instant a word first crosses into "stuck",
  // cleared as soon as the user interacts with any word so it never lingers/repeats.
  const [arrowWord, setArrowWord] = React.useState<string | null>(null);
  const [playingWord, setPlayingWord] = React.useState<string | null>(null);

  function updateWrongStreaks(sentence: string, words: AttemptResult["words"]) {
    if (lastSentenceRef.current !== sentence) {
      wrongStreakRef.current = {};
      lastSentenceRef.current = sentence;
    }
    let newlyStuck: string | null = null;
    for (const w of words) {
      const prev = wrongStreakRef.current[w.word] ?? 0;
      if (w.status === "correct") {
        if (prev >= 3)
          toast.success(`Nice! You got "${w.word}" right — keep going!`);
        wrongStreakRef.current[w.word] = 0;
      } else {
        const next = prev + 1;
        wrongStreakRef.current[w.word] = next;
        if (next === 3) newlyStuck = w.word; // exactly the first crossing, not every attempt after
      }
    }
    setStuckWords(
      Object.keys(wrongStreakRef.current).filter(
        (w) => wrongStreakRef.current[w] >= 3,
      ),
    );
    if (newlyStuck) setArrowWord(newlyStuck);
  }

  async function handleHearPronunciation(word: string) {
    setPlayingWord(word);
    try {
      const blob = await fetchPronunciationTts(word);
      const audio = new Audio(URL.createObjectURL(blob));
      await new Promise<void>((resolve) => {
        audio.onended = () => resolve();
        audio.onerror = () => resolve();
        void audio.play();
      });
    } catch {
      // Best-effort — a failed playback isn't worth surfacing an error for.
    } finally {
      setPlayingWord(null);
    }
  }

  // ── Retry-a-single-word state (US-89) ───────────────────────────────────
  const [retryTarget, setRetryTarget] = React.useState<string | null>(null);
  const [retryResult, setRetryResult] = React.useState<RetryResult | null>(
    null,
  );
  const [retrySubmitting, setRetrySubmitting] = React.useState(false);
  const [retryError, setRetryError] = React.useState<string | null>(null);
  const retryRecorder = useAudioRecorder();

  const activeSessionRef = React.useRef<{
    sessionId: string;
    completed: boolean;
  } | null>(null);

  React.useEffect(() => {
    if (!isUnlocked) {
      setStep({ name: "loading" });
      return;
    }
    let cancelled = false;
    checkResumableSession()
      .then((check) => {
        if (cancelled) return;
        if (check.found) {
          setStep({ name: "resume-prompt", check });
        } else {
          return startPronunciationSession().then((session) => {
            if (cancelled) return;
            activeSessionRef.current = {
              sessionId: session.session_id,
              completed: false,
            };
            setStep({ name: "practice", session });
          });
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setStep({
            name: "error",
            message:
              err instanceof ApiError
                ? err.message
                : "Couldn't load Pronunciation Coach.",
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [isUnlocked]);

  // GAP-09: best-effort interruption signal — a real call/backgrounding/connectivity
  // drop looks like the tab going hidden or unloading mid-session.
  React.useEffect(() => {
    function handleHidden() {
      const active = activeSessionRef.current;
      if (
        document.visibilityState === "hidden" &&
        active &&
        !active.completed
      ) {
        interruptSession(active.sessionId).catch(() => {});
      }
    }
    document.addEventListener("visibilitychange", handleHidden);
    return () => document.removeEventListener("visibilitychange", handleHidden);
  }, []);

  async function handleResume(check: ResumeCheck) {
    if (!check.session_id) return;
    setIsSubmitting(true);
    setError(null);
    try {
      const resumed = await resumeSession(check.session_id);
      activeSessionRef.current = {
        sessionId: resumed.session_id,
        completed: false,
      };
      setStep({
        name: "practice",
        session: {
          session_id: resumed.session_id,
          status: resumed.status,
          phoneme: resumed.phoneme,
          phoneme_tag: resumed.phoneme_tag,
          sentence: resumed.sentence,
          message: resumed.message,
        },
      });
      // Sidebar dot reflects resumed (still active) session — refresh to sync.
      refreshActiveSessions().catch(() => {});
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Couldn't resume that session.",
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleDiscard() {
    setIsSubmitting(true);
    setError(null);
    try {
      const session = await startPronunciationSession();
      activeSessionRef.current = {
        sessionId: session.session_id,
        completed: false,
      };
      setStep({ name: "practice", session });
      // Old session superseded — sidebar dot should clear (new session has no attempts yet).
      refreshActiveSessions().catch(() => {});
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Couldn't start a new session.",
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleSubmitAttempt(audio: Blob) {
    if (step.name !== "practice") return;
    setError(null);
    setIsSubmitting(true);
    try {
      const result = await submitAttempt(step.session.session_id, audio);
      updateWrongStreaks(step.session.sentence, result.words);
      setRetryTarget(null);
      setRetryResult(null);
      setRetryError(null);
      setStep({ name: "attempt-result", session: step.session, result });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleAttemptRecordToggle() {
    if (recorder.isRecording) {
      const audio = await recorder.stop();
      if (audio) await handleSubmitAttempt(audio);
    } else {
      await recorder.start();
    }
  }

  // ── Retry-a-single-word handlers (US-89) ────────────────────────────────
  function handleSelectRetryWord(word: string) {
    setRetryTarget(word);
    setRetryResult(null);
    setRetryError(null);
    setArrowWord(null); // guided them once — clear the pointer now that they've engaged
  }

  async function handleSubmitRetry() {
    if (step.name !== "attempt-result" || !retryTarget) return;
    setRetryError(null);
    setRetrySubmitting(true);
    try {
      const audio = await retryRecorder.stop();
      if (!audio) return;
      const result = await retryWord(
        step.session.session_id,
        retryTarget,
        audio,
      );
      setRetryResult(result);
    } catch (err) {
      setRetryError(
        err instanceof ApiError ? err.message : "Couldn't score that retry.",
      );
    } finally {
      setRetrySubmitting(false);
    }
  }

  async function handleRetryRecordToggle() {
    if (retryRecorder.isRecording) {
      await handleSubmitRetry();
    } else {
      setRetryResult(null);
      setRetryError(null);
      await retryRecorder.start();
    }
  }

  function handleContinue() {
    if (step.name !== "attempt-result") return;
    const { session, result } = step;
    const nextSession: PronunciationSession = {
      ...session,
      sentence: result.next_sentence ?? session.sentence,
      phoneme: result.next_phoneme ?? session.phoneme,
      phoneme_tag: result.next_phoneme_tag ?? session.phoneme_tag,
      message: undefined,
    };
    setRetryTarget(null);
    setRetryResult(null);
    setRetryError(null);
    setStep({ name: "practice", session: nextSession });
  }

  async function handleEndSession(sessionId: string) {
    setIsSubmitting(true);
    setError(null);
    try {
      const summary = await endSession(sessionId);
      if (activeSessionRef.current) activeSessionRef.current.completed = true;
      setStep({ name: "summary", summary });
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Couldn't end the session.",
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  if (!isUnlocked) {
    return (
      <div className="flex items-start gap-2.5 rounded-xl border border-warning/30 bg-warning/10 px-4 py-3 text-sm text-foreground">
        <Lock
          className="mt-0.5 h-4 w-4 shrink-0 text-warning"
          aria-hidden="true"
        />
        {access?.locked_message ??
          "Complete your baseline assessment to unlock Pronunciation Coach."}
      </div>
    );
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
        <Button href="/dashboard/explore" size="sm">
          Back to Explore
        </Button>
      </div>
    );
  }

  if (step.name === "resume-prompt") {
    return (
      <div className="mx-auto flex max-w-lg flex-col gap-4">
        {gate}
        <div className="flex flex-col items-start gap-3 rounded-xl border border-warning/30 bg-warning/10 px-4 py-3 text-sm sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-start gap-2.5">
            <TriangleAlert
              className="mt-0.5 h-4 w-4 shrink-0 text-warning"
              aria-hidden="true"
            />
            <p className="text-foreground">{step.check.message}</p>
          </div>
          <div className="flex shrink-0 gap-2">
            <Button
              size="sm"
              variant="outline"
              loading={isSubmitting}
              onClick={handleDiscard}
            >
              Start Fresh
            </Button>
            <Button
              size="sm"
              loading={isSubmitting}
              onClick={() => handleResume(step.check)}
            >
              Resume
            </Button>
          </div>
        </div>
        {error ? <p className="text-sm text-danger">{error}</p> : null}
      </div>
    );
  }

  if (step.name === "practice") {
    const { session } = step;
    return (
      <div className="mx-auto flex max-w-2xl flex-col gap-6">
        {gate}
        <div>
          <h1 className="font-serif text-h2 font-semibold text-foreground">
            Pronunciation Coach
          </h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Read the sentence aloud, then record yourself saying it.
          </p>
        </div>
        <div className="rounded-2xl border border-border bg-surface-elevated p-6 shadow-sm">
          <span className="inline-flex items-center rounded-full bg-secondary px-3 py-1 text-xs font-medium text-primary">
            {session.phoneme_tag}
          </span>
          <p className="mt-4 font-serif text-xl font-semibold text-foreground">
            {session.sentence}
          </p>

          {recorder.error ? (
            <p className="mt-3 text-sm text-danger">{recorder.error}</p>
          ) : null}
          {error ? <p className="mt-3 text-sm text-danger">{error}</p> : null}

          <div className="mt-5 flex items-center gap-3">
            <button
              type="button"
              disabled={
                !recorder.isSupported ||
                isSubmitting ||
                recorder.state === "stopping"
              }
              onClick={
                recorder.isRecording
                  ? handleAttemptRecordToggle
                  : () => void runWithVoiceReadiness(handleAttemptRecordToggle)
              }
              aria-pressed={recorder.isRecording}
              className={cn(
                "flex h-16 w-16 shrink-0 items-center justify-center rounded-full text-primary-foreground shadow-md transition-all duration-200 hover:scale-105 disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:scale-100",
                recorder.isRecording
                  ? "animate-pulse bg-danger"
                  : "bg-primary hover:bg-primary-hover",
              )}
              aria-label={
                recorder.isRecording
                  ? "Stop recording and submit"
                  : "Record your attempt"
              }
            >
              {recorder.isRecording ? (
                <Square className="h-5 w-5" aria-hidden="true" />
              ) : (
                <Mic className="h-6 w-6" aria-hidden="true" />
              )}
            </button>
            <p className="text-sm text-muted-foreground">
              {recorder.state === "stopping"
                ? "Processing..."
                : recorder.isRecording
                  ? "Recording — tap to stop and submit."
                  : "Tap the mic and read the sentence aloud."}
            </p>
          </div>

          <div className="mt-4 flex items-center gap-3">
            <Button
              size="lg"
              variant="outline"
              loading={isSubmitting}
              onClick={() => handleEndSession(session.session_id)}
            >
              End Session
            </Button>
          </div>
        </div>
      </div>
    );
  }

  if (step.name === "attempt-result") {
    const { session, result } = step;
    const isNegative = NEGATIVE_MESSAGE_KEYS.has(result.message_key);
    const canAdvance = Boolean(result.next_sentence);
    return (
      <div className="mx-auto flex max-w-2xl flex-col gap-6">
        {gate}
        <div
          className={cn(
            "flex items-start gap-2.5 rounded-2xl border p-4 text-sm",
            isNegative
              ? "border-warning/30 bg-warning/10 text-foreground"
              : "border-success/30 bg-success/10 text-success",
          )}
        >
          {isNegative ? (
            <TriangleAlert
              className="mt-0.5 h-4 w-4 shrink-0 text-warning"
              aria-hidden="true"
            />
          ) : (
            <CheckCircle2
              className="mt-0.5 h-4 w-4 shrink-0"
              aria-hidden="true"
            />
          )}
          <div>
            <p>{result.message}</p>
            {result.transcript ? (
              <p className="mt-1 text-xs text-muted-foreground">
                We heard: &quot;{result.transcript}&quot;
              </p>
            ) : null}
          </div>
        </div>

        {result.words.length > 0 ? (
          <div className="rounded-2xl border border-border bg-surface-elevated p-6 shadow-sm">
            <h2 className="font-serif text-lg font-semibold text-foreground">
              Word by word
            </h2>
            <p className="mt-1 text-xs text-muted-foreground">
              Tap a red or amber word to practice just that word.
              {stuckWords.length > 0
                ? " Glowing words have been wrong 3+ times — worth a listen first."
                : ""}
            </p>
            <WordByWordDisplay
              className="mt-4"
              words={result.words.map((w) => ({
                word: w.word,
                status: w.status,
                stuck: stuckWords.includes(w.word),
              }))}
              onWordClick={handleSelectRetryWord}
              selectedWord={retryTarget}
              pointedWord={arrowWord}
            />

            {retryTarget ? (
              <div className="mt-5 rounded-xl border border-border bg-surface p-4">
                <div className="flex items-center justify-between gap-3">
                  <p className="text-sm font-medium text-foreground">
                    Retry word:{" "}
                    <span className="text-primary">{retryTarget}</span>
                  </p>
                  <button
                    type="button"
                    disabled={playingWord === retryTarget}
                    onClick={() => handleHearPronunciation(retryTarget)}
                    className="inline-flex shrink-0 items-center gap-1.5 rounded-full bg-secondary px-3 py-1.5 text-xs font-medium text-primary transition-colors hover:bg-secondary/70 disabled:opacity-60"
                  >
                    <Volume2 className="h-3.5 w-3.5" aria-hidden="true" />
                    {playingWord === retryTarget ? "Playing…" : "Hear it"}
                  </button>
                </div>
                {retryRecorder.error ? (
                  <p className="mt-2 text-sm text-danger">
                    {retryRecorder.error}
                  </p>
                ) : null}
                {retryError ? (
                  <p className="mt-2 text-sm text-danger">{retryError}</p>
                ) : null}

                <div className="mt-3 flex items-center gap-3">
                  <button
                    type="button"
                    disabled={
                      !retryRecorder.isSupported ||
                      retrySubmitting ||
                      retryRecorder.state === "stopping"
                    }
                    onClick={handleRetryRecordToggle}
                    aria-pressed={retryRecorder.isRecording}
                    className={cn(
                      "flex h-12 w-12 shrink-0 items-center justify-center rounded-full text-primary-foreground shadow-md transition-all duration-200 hover:scale-105 disabled:cursor-not-allowed disabled:opacity-50",
                      retryRecorder.isRecording
                        ? "animate-pulse bg-danger"
                        : "bg-primary hover:bg-primary-hover",
                    )}
                    aria-label={
                      retryRecorder.isRecording
                        ? "Stop and submit retry"
                        : `Record retry for ${retryTarget}`
                    }
                  >
                    {retryRecorder.isRecording ? (
                      <Square className="h-4 w-4" aria-hidden="true" />
                    ) : (
                      <Mic className="h-5 w-5" aria-hidden="true" />
                    )}
                  </button>
                  <p className="text-sm text-muted-foreground">
                    {retryRecorder.state === "stopping"
                      ? "Scoring..."
                      : retryRecorder.isRecording
                        ? "Recording — tap to stop and submit."
                        : `Tap the mic and say "${retryTarget}".`}
                  </p>
                </div>

                {retryResult ? (
                  <div
                    className={cn(
                      "mt-3 rounded-lg p-3 text-sm",
                      retryResult.frustration_breakdown
                        ? "bg-warning/10 text-foreground"
                        : "bg-success/10 text-success",
                    )}
                  >
                    <p>{retryResult.message}</p>
                    {retryResult.transcript ? (
                      <p className="mt-1 text-xs text-muted-foreground">
                        We heard: &quot;{retryResult.transcript}&quot;
                      </p>
                    ) : null}
                  </div>
                ) : null}
              </div>
            ) : null}
          </div>
        ) : null}

        {error ? <p className="text-sm text-danger">{error}</p> : null}

        <div className="flex items-center gap-3">
          <Button size="lg" onClick={handleContinue}>
            {canAdvance ? "Next Sentence" : "Try Again"}
          </Button>
          <Button
            size="lg"
            variant="outline"
            loading={isSubmitting}
            onClick={() => handleEndSession(session.session_id)}
          >
            End Session
          </Button>
        </div>
      </div>
    );
  }

  // step.name === "summary"
  const { summary } = step;
  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-6">
      {gate}
      <div className="animate-fade-up rounded-2xl border border-border bg-gradient-to-br from-primary to-primary-hover p-8 text-center text-primary-foreground shadow-sm">
        <Sparkles className="mx-auto h-6 w-6" aria-hidden="true" />
        <h1 className="mt-3 font-serif text-h2 font-semibold">
          Session Complete
        </h1>
        <p className="mt-2 text-sm text-primary-foreground/85">
          {summary.attempt_count} sentence
          {summary.attempt_count === 1 ? "" : "s"} practiced.
        </p>
      </div>

      {summary.phoneme_accuracy.length > 0 ? (
        <div className="rounded-2xl border border-border bg-surface-elevated p-6 shadow-sm">
          <h2 className="font-serif text-lg font-semibold text-foreground">
            Accuracy by sound
          </h2>
          <div className="mt-4 grid grid-cols-2 gap-4 sm:grid-cols-3">
            {summary.phoneme_accuracy.map((p) => (
              <div
                key={p.phoneme}
                className="rounded-xl border border-border bg-surface p-4"
              >
                <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  &quot;{p.phoneme}&quot; sound
                </p>
                <p className="mt-1 text-xl font-semibold text-foreground">
                  {p.total_words === 0
                    ? "—"
                    : `${Math.round((p.correct_words / p.total_words) * 100)}%`}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {p.attempts} attempt{p.attempts === 1 ? "" : "s"}
                </p>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      <Button
        size="lg"
        variant="outline"
        className="self-center"
        href="/dashboard/explore"
      >
        Back to Explore
      </Button>
    </div>
  );
}
