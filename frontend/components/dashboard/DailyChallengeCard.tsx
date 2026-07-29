"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { Flame } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/contexts/AuthContext";
import { ApiError } from "@/lib/api";
import { localDate, getDailyChallengeStatus, type DailyChallengeStatus } from "@/lib/dailyChallenge";
import { startDailyChallenge } from "@/lib/daily-challenge";

/**
 * Daily Challenge card (PDG-US-11): redirects into a real AI Conversation session on
 * the topic matching the user's signup learning goal. Completion (5 minutes from the
 * first prompt in that conversation) is tracked server-side and surfaced back here via
 * /daily-challenge/status, refreshed on mount and whenever a "speeky:streak-updated"
 * event fires (dispatched by the conversation page the moment the challenge completes).
 */
export function DailyChallengeCard() {
  const { user } = useAuth();
  const router = useRouter();
  const [status, setStatus] = React.useState<DailyChallengeStatus | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const refreshStatus = React.useCallback(() => {
    getDailyChallengeStatus()
      .then(setStatus)
      .catch(() => setStatus(null));
  }, []);

  React.useEffect(() => {
    if (!user) return;
    refreshStatus();
  }, [user, refreshStatus]);

  React.useEffect(() => {
    window.addEventListener("speeky:streak-updated", refreshStatus);
    return () => window.removeEventListener("speeky:streak-updated", refreshStatus);
  }, [refreshStatus]);

  if (!user) return null;

  async function handleStart() {
    setBusy(true);
    setError(null);
    try {
      const res = await startDailyChallenge(localDate());
      router.push(`/dashboard/conversation/${res.session_id}?daily=1`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
      setBusy(false);
    }
  }

  const done = status?.completed_today ?? false;

  return (
    <div className="flex animate-fade-up flex-col justify-between gap-6 rounded-2xl bg-gradient-to-br from-accent to-accent/80 p-6 text-accent-foreground shadow-sm transition-transform duration-200 hover:-translate-y-0.5">
      <div>
        <span className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-accent-foreground/80">
          <Flame className={done ? "h-4 w-4 fill-current" : "h-4 w-4"} aria-hidden="true" />
          Daily Streak
        </span>
        <p className="mt-3 flex items-baseline gap-2">
          <span className="text-5xl font-bold tracking-tight">{status?.current_streak ?? "–"}</span>
          <span className="text-lg text-accent-foreground/80">Days</span>
        </p>
      </div>

      <div>
        <p className="text-sm text-accent-foreground/90">
          {done
            ? "Today's challenge is complete — nice work!"
            : `Talk with your AI coach for ${status?.required_minutes ?? 5} minutes to keep your streak alive.`}
        </p>
        {error ? <p className="mt-2 text-xs text-danger">{error}</p> : null}
        <Button
          type="button"
          size="sm"
          variant="secondary"
          className="mt-4"
          loading={busy}
          onClick={handleStart}
        >
          {done ? "Keep Practicing" : "Start Today's Challenge"}
        </Button>
      </div>
    </div>
  );
}
