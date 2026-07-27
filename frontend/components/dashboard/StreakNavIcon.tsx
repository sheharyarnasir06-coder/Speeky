"use client";

import * as React from "react";
import { Flame } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  getDailyChallengeStatus,
  type DailyChallengeStatus,
} from "@/lib/dailyChallenge";

// Navbar daily-streak indicator (PDG-US-11). Filled/colored flame once today's challenge
// is complete, grayed outline while it's still pending; the streak-day count sits to the
// left of the flame. Links to the daily challenge (a conversation session).
export function StreakNavIcon() {
  const [status, setStatus] = React.useState<DailyChallengeStatus | null>(null);

  React.useEffect(() => {
    getDailyChallengeStatus()
      .then(setStatus)
      .catch(() => setStatus(null));
  }, []);

  if (!status) return null;

  const done = status.completed_today;

  return (
    <a
      href="/dashboard/conversation"
      title={
        done
          ? `Daily Challenge complete — ${status.current_streak}-day streak`
          : `Daily Challenge pending — ${status.current_streak}-day streak`
      }
      aria-label={
        done
          ? `Daily streak ${status.current_streak} days, today complete`
          : `Daily streak ${status.current_streak} days, today incomplete`
      }
      className="flex items-center gap-1 rounded-lg px-2 py-1 text-sm font-semibold transition-colors hover:bg-surface"
    >
      {status.current_streak > 0 ? (
        <span className={done ? "text-warning" : "text-muted-foreground"}>
          {status.current_streak}
        </span>
      ) : null}
      <Flame
        className={cn(
          "h-5 w-5",
          done ? "fill-warning text-warning" : "text-muted-foreground",
        )}
        aria-hidden="true"
      />
    </a>
  );
}
