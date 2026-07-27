"use client";

import * as React from "react";
import { usePathname } from "next/navigation";
import { Flame, X } from "lucide-react";
import { getStreakNotification } from "@/lib/dailyChallenge";

// PDG-US-13 (in-app fallback, no OS push): a prominent Streak-Warning banner shown on app
// launch when the learner hasn't done today's challenge, it's past 6 PM local, and a live
// streak is at risk. The backend makes the decision (E-03 pre-validation + dynamic copy);
// this just renders it. Dismissible for the session so it doesn't nag on every navigation.
export function StreakWarningBanner() {
  const pathname = usePathname();
  const [message, setMessage] = React.useState<string | null>(null);
  const [dismissed, setDismissed] = React.useState(false);

  React.useEffect(() => {
    getStreakNotification()
      .then((n) => setMessage(n.show_streak_warning ? n.message : null))
      .catch(() => setMessage(null));
  }, []);

  // Don't cover the challenge entry point itself.
  if (dismissed || !message || pathname.startsWith("/dashboard/conversation")) {
    return null;
  }

  return (
    <div className="mb-6 flex items-start gap-3 rounded-xl border border-warning/30 bg-warning/10 px-4 py-3">
      <Flame className="mt-0.5 h-5 w-5 shrink-0 text-warning" aria-hidden="true" />
      <div className="flex-1 text-sm text-foreground">
        <span className="font-medium">{message}</span>{" "}
        <a
          href="/dashboard/conversation"
          className="font-medium text-primary underline-offset-2 hover:underline"
        >
          Start now
        </a>
      </div>
      <button
        type="button"
        onClick={() => setDismissed(true)}
        aria-label="Dismiss"
        className="text-muted-foreground transition-colors hover:text-foreground"
      >
        <X className="h-4 w-4" aria-hidden="true" />
      </button>
    </div>
  );
}
