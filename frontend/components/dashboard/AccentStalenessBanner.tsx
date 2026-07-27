"use client";

import * as React from "react";
import { CalendarClock } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import {
  checkAccentStaleness,
  dismissStalenessPrompt,
  rebaselineFromSession,
  type StalenessDetails,
} from "@/lib/accentAssessment";
import { listConversationSessions } from "@/lib/conversation";

/**
 * US-84 (ACC-US-05): Accent Profile Staleness & Re-Baseline Prompt.
 * Same visual pattern as AssessmentReminderBanner.tsx, rendered on the
 * dashboard home page specifically (per the story's placement), not the
 * shared layout.
 *
 * "Retake a quick baseline" reuses the user's most recently COMPLETED
 * conversation session's real scores (see
 * accent_assessment_service.rebaseline) rather than fabricating one — if
 * no completed session exists yet, it says so instead of pretending to work.
 */
export function AccentStalenessBanner() {
  const [details, setDetails] = React.useState<StalenessDetails | null>(null);
  const [dismissed, setDismissed] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [notice, setNotice] = React.useState<string | null>(null);

  React.useEffect(() => {
    checkAccentStaleness()
      .then(setDetails)
      .catch(() => setDetails(null)); // non-critical banner — fail silently
  }, []);

  if (!details || dismissed || !details.should_prompt) {
    return null;
  }

  async function handleDismiss() {
    setDismissed(true);
    try {
      await dismissStalenessPrompt();
    } catch {
      // best-effort — the banner is already hidden client-side either way
    }
  }

  async function handleRebaseline() {
    setBusy(true);
    setNotice(null);
    try {
      const { sessions } = await listConversationSessions();
      const lastCompleted = sessions.find((s) => s.status === "completed");
      if (!lastCompleted) {
        setNotice("Complete a conversation practice session first, then come back to set your baseline.");
        return;
      }
      await rebaselineFromSession(lastCompleted.session_id);
      setDismissed(true);
    } catch (err) {
      setNotice(err instanceof ApiError ? err.message : "Couldn't refresh your baseline.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mb-6 flex flex-col items-start gap-3 rounded-xl border border-warning/30 bg-warning/10 px-4 py-3 text-sm sm:flex-row sm:items-center sm:justify-between">
      <div className="flex items-start gap-2.5">
        <CalendarClock className="mt-0.5 h-4 w-4 shrink-0 text-warning" aria-hidden="true" />
        <div>
          <p className="text-foreground">{details.prompt_message}</p>
          {details.notice ? <p className="mt-1 text-xs text-muted-foreground">{details.notice}</p> : null}
          {notice ? <p className="mt-1 text-xs text-muted-foreground">{notice}</p> : null}
        </div>
      </div>
      <div className="flex shrink-0 gap-2">
        <Button size="sm" variant="outline" onClick={handleDismiss} disabled={busy}>
          Not now
        </Button>
        <Button size="sm" loading={busy} onClick={handleRebaseline}>
          Retake baseline
        </Button>
      </div>
    </div>
  );
}
