"use client";

import * as React from "react";
import { Flame, Mic, Square } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useVoiceReadinessGate } from "@/components/common/VoiceReadinessGate";
import { useAuth } from "@/contexts/AuthContext";
import { useAudioRecorder } from "@/lib/useAudioRecorder";
import { cn } from "@/lib/utils";
import {
  addChallengeTurn,
  completeDailyChallenge,
  disputeChallengeSession,
  getDailyChallengeStreak,
  startDailyChallenge,
  type CompleteChallengeResponse,
} from "@/lib/daily-challenge";

const MIN_TURNS = 3;

type Phase = "idle" | "active" | "result";

/**
 * Daily Challenge card (US-168 / GAP-07): replaces the old static "Daily Streak"
 * mock with the real streak + anti-gaming completion flow. The check-in below is a
 * self-contained turn recorder (real mic audio via useAudioRecorder) — it does not
 * read from Chat or Pronunciation Coach (neither module is touched by this feature),
 * so it stands in for the duration/turn/content signal a fuller integration would
 * pull from those modules.
 */
export function DailyChallengeCard() {
  const { user } = useAuth();
  const [streak, setStreak] = React.useState<{ current: number; longest: number } | null>(null);
  const [phase, setPhase] = React.useState<Phase>("idle");
  const [sessionId, setSessionId] = React.useState<string | null>(null);
  const [turnCount, setTurnCount] = React.useState(0);
  const [busy, setBusy] = React.useState(false);
  const [result, setResult] = React.useState<CompleteChallengeResponse | null>(null);
  const [disputeStatus, setDisputeStatus] = React.useState<"none" | "pending" | "resolved">("none");
  const recorder = useAudioRecorder();
  const { gate, runWithVoiceReadiness } = useVoiceReadinessGate({
    featureName: "Daily Challenge",
  });

  const refreshStreak = React.useCallback(() => {
    getDailyChallengeStreak()
      .then((res) => setStreak({ current: res.current_streak, longest: res.longest_streak }))
      .catch(() => {});
  }, []);

  React.useEffect(() => {
    if (!user) return;
    refreshStreak();
  }, [user, refreshStreak]);

  if (!user) return null;

  async function handleStart() {
    setBusy(true);
    try {
      const res = await startDailyChallenge();
      setSessionId(res.session_id);
      setTurnCount(0);
      setResult(null);
      setDisputeStatus("none");
      setPhase("active");
    } finally {
      setBusy(false);
    }
  }

  async function handleAddTurn(audio: Blob) {
    if (!sessionId) return;
    setBusy(true);
    try {
      const res = await addChallengeTurn(sessionId, audio);
      setTurnCount(res.turn_count);
    } finally {
      setBusy(false);
    }
  }

  async function handleRecordToggle() {
    if (recorder.isRecording) {
      const audio = await recorder.stop();
      if (audio) await handleAddTurn(audio);
    } else {
      await recorder.start();
    }
  }

  async function handleFinish() {
    if (!sessionId) return;
    setBusy(true);
    try {
      const res = await completeDailyChallenge(sessionId);
      setResult(res);
      setStreak({ current: res.current_streak, longest: res.longest_streak });
      setPhase("result");
    } finally {
      setBusy(false);
    }
  }

  async function handleDispute() {
    if (!sessionId) return;
    setBusy(true);
    try {
      await disputeChallengeSession(sessionId);
      setDisputeStatus("pending");
    } finally {
      setBusy(false);
    }
  }

  function handleReset() {
    setPhase("idle");
    setSessionId(null);
    setTurnCount(0);
    setResult(null);
    setDisputeStatus("none");
  }

  return (
    <div className="flex animate-fade-up flex-col justify-between gap-6 rounded-2xl bg-gradient-to-br from-accent to-accent/80 p-6 text-accent-foreground shadow-sm transition-transform duration-200 hover:-translate-y-0.5">
      {gate}
      <div>
        <span className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-accent-foreground/80">
          <Flame className="h-4 w-4" aria-hidden="true" />
          Daily Streak
        </span>
        <p className="mt-3 flex items-baseline gap-2">
          <span className="text-5xl font-bold tracking-tight">{streak?.current ?? "–"}</span>
          <span className="text-lg text-accent-foreground/80">Days</span>
        </p>
      </div>

      {phase === "idle" ? (
        <div>
          <p className="text-sm text-accent-foreground/90">
            Complete today&apos;s check-in to keep your streak alive.
          </p>
          <Button type="button" size="sm" variant="secondary" className="mt-4" loading={busy} onClick={handleStart}>
            Start Today&apos;s Challenge
          </Button>
        </div>
      ) : null}

      {phase === "active" ? (
        <div className="flex flex-col gap-3">
          <p className="text-sm text-accent-foreground/90">
            {turnCount}/{MIN_TURNS}+ responses recorded
          </p>
          {recorder.error ? <p className="text-xs text-danger">{recorder.error}</p> : null}
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={
                recorder.isRecording
                  ? handleRecordToggle
                  : () => void runWithVoiceReadiness(handleRecordToggle)
              }
              disabled={!recorder.isSupported || busy || recorder.state === "stopping"}
              aria-pressed={recorder.isRecording}
              aria-label={recorder.isRecording ? "Stop recording and submit" : "Record a response"}
              className={cn(
                "flex h-11 w-11 shrink-0 items-center justify-center rounded-full text-accent shadow-md transition-all duration-200 hover:scale-105 disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:scale-100",
                recorder.isRecording ? "animate-pulse bg-danger text-danger-foreground" : "bg-accent-foreground",
              )}
            >
              {recorder.isRecording ? (
                <Square className="h-4 w-4" aria-hidden="true" />
              ) : (
                <Mic className="h-5 w-5" aria-hidden="true" />
              )}
            </button>
            <p className="text-xs text-accent-foreground/80">
              {recorder.state === "stopping"
                ? "Processing..."
                : recorder.isRecording
                  ? "Recording — tap to stop and submit."
                  : "Tap the mic and say what you'd say."}
            </p>
          </div>
          <Button
            type="button"
            size="sm"
            variant="secondary"
            loading={busy}
            disabled={turnCount < MIN_TURNS}
            onClick={handleFinish}
          >
            Finish Check-In
          </Button>
        </div>
      ) : null}

      {phase === "result" && result ? (
        <div className="flex flex-col gap-2">
          {result.status === "qualified" || result.status === "qualified_retroactive" ? (
            <p className="text-sm text-accent-foreground/90">
              Nice work — streak is now {result.current_streak} day
              {result.current_streak === 1 ? "" : "s"}.
              {result.milestone_message ? ` ${result.milestone_message}` : ""}
            </p>
          ) : null}

          {/* E-04: milestone celebration (above) always renders before the wellbeing
              nudge (below) when both fire from the same completion. */}
          {result.overuse_nudge ? (
            <p className="text-xs text-accent-foreground/80">{result.overuse_nudge.message}</p>
          ) : null}

          {result.status === "incomplete_low_engagement" ? (
            <div className="flex flex-col gap-2">
              <p className="text-sm text-accent-foreground/90">{result.message}</p>
              {disputeStatus === "none" ? (
                <button
                  type="button"
                  onClick={handleDispute}
                  disabled={busy}
                  className="self-start text-xs font-medium text-accent-foreground underline underline-offset-2 disabled:opacity-50"
                >
                  This doesn&apos;t look right — flag for review
                </button>
              ) : (
                <p className="text-xs text-accent-foreground/80">
                  Flagged — a reviewer will confirm and, if genuine, your streak will be
                  credited retroactively.
                </p>
              )}
            </div>
          ) : null}

          {result.status === "rejected_non_interactive" ? (
            <p className="text-sm text-accent-foreground/90">{result.message}</p>
          ) : null}

          <button
            type="button"
            onClick={handleReset}
            className="mt-1 self-start text-xs font-medium text-accent-foreground underline underline-offset-2"
          >
            Done
          </button>
        </div>
      ) : null}
    </div>
  );
}
