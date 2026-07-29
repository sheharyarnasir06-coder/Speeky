"use client";

import * as React from "react";
import { History, X } from "lucide-react";
import { toast } from "react-toastify";
import { Button } from "@/components/ui/button";
import { useActiveSessions } from "@/contexts/ActiveSessionsContext";
import { getScenarioDetail } from "@/lib/scenario";
import { getCoachingScenarios } from "@/lib/coaching";
import { dismissOpenExploreSession } from "@/lib/activeSessions";
import { ApiError } from "@/lib/api";

const FEATURE_NAMES: Record<string, string> = {
  conversation: "AI Conversation",
  scenario: "Scenario",
  coaching: "Workplace Coaching session",
  interview_coach: "Interview Coach session",
};

/**
 * Explore bundles four session types (Conversation, Scenario-Based Learning,
 * Workplace Coaching, Interview Coach) that all supersede each other on the
 * backend (lib/explore_sessions.py) — this is the one place that surfaces
 * "you left one unfinished" before the picker below lets you start a different
 * one, so leaving mid-session never *silently* orphans it.
 */
export function ExploreResumeBanner() {
  const { explore, isLoading, refresh } = useActiveSessions();
  const [label, setLabel] = React.useState<string | null>(null);
  const [dismissed, setDismissed] = React.useState(false);
  const [dismissing, setDismissing] = React.useState(false);

  React.useEffect(() => {
    setDismissed(false);
    if (!explore?.active) return;
    if (explore.label) {
      setLabel(explore.label);
      return;
    }
    if (explore.feature === "scenario" && explore.scenario_key) {
      getScenarioDetail(explore.scenario_key).then((d) => setLabel(d.label)).catch(() => setLabel(explore.scenario_key ?? null));
    } else if (explore.feature === "coaching" && explore.scenario_key) {
      getCoachingScenarios()
        .then((data) => setLabel(data.scenarios.find((s) => s.key === explore.scenario_key)?.label ?? explore.scenario_key ?? null))
        .catch(() => setLabel(explore.scenario_key ?? null));
    }
  }, [explore]);

  async function handleDismiss() {
    setDismissing(true);
    try {
      await dismissOpenExploreSession();
      setDismissed(true);
      await refresh();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Couldn't dismiss this session.");
    } finally {
      setDismissing(false);
    }
  }

  if (isLoading || !explore?.active || dismissed) return null;

  const featureName = FEATURE_NAMES[explore.feature ?? ""] ?? "session";

  return (
    <div className="mb-6 flex flex-col gap-3 rounded-2xl border border-primary/30 bg-primary/5 p-5 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex items-start gap-3">
        <History className="mt-0.5 h-5 w-5 shrink-0 text-primary" aria-hidden="true" />
        <div>
          <p className="text-sm font-medium text-foreground">
            You have an unfinished {featureName}{label ? `: ${label}` : ""}
          </p>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Starting something else here will end it — resume first, or dismiss to start fresh.
          </p>
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <Button size="sm" href={explore.resume_path ?? "/dashboard/explore"}>
          Resume
        </Button>
        <button
          type="button"
          onClick={handleDismiss}
          disabled={dismissing}
          aria-label="Dismiss — ends the unfinished session"
          className="rounded-lg p-2 text-muted-foreground hover:bg-surface hover:text-foreground disabled:opacity-50"
        >
          <X className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>
    </div>
  );
}
