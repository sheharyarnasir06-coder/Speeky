"use client";

import * as React from "react";
import {
  Briefcase,
  Lock,
  Mail,
  MessageSquare,
  Mic,
  Presentation,
  Users,
} from "lucide-react";
import { ApiError } from "@/lib/api";
import { getCoachingScenarios, type CoachingScenarioMeta } from "@/lib/coaching";
import { useAssessmentAccess } from "@/contexts/AssessmentContext";
import { CodeSwitchWordsCard } from "@/components/dashboard/CodeSwitchWordsCard";
import { ExploreResumeBanner } from "@/components/dashboard/ExploreResumeBanner";
import { cn } from "@/lib/utils";

const SCENARIO_ICONS: Record<string, typeof Mail> = {
  email_writing: Mail,
  client_communication: Users,
  meeting_communication: MessageSquare,
  presentation_prep: Presentation,
  general_workplace: Briefcase,
};

export default function CoachingPage() {
  const { access } = useAssessmentAccess();
  const [scenarios, setScenarios] = React.useState<CoachingScenarioMeta[] | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const isUnlocked = access?.access_level === "full_access";

  React.useEffect(() => {
    if (!isUnlocked) return;
    getCoachingScenarios()
      .then((data) => setScenarios(data.scenarios))
      .catch((err) => setError(err instanceof ApiError ? err.message : "Something went wrong."));
  }, [isUnlocked]);

  return (
    <div className="flex flex-col gap-8">
      <div>
        <h1 className="font-serif text-h1 font-semibold text-foreground">
          Workplace English Coach
        </h1>
        <p className="mt-2 max-w-xl text-sm text-muted-foreground">
          Practice professional communication — emails, client calls, meetings,
          presentations — and get feedback on tone, clarity, and effectiveness.
        </p>
      </div>

      <ExploreResumeBanner />

      {!isUnlocked ? (
        <div className="flex items-start gap-2.5 rounded-xl border border-warning/30 bg-warning/10 px-4 py-3 text-sm text-foreground">
          <Lock className="mt-0.5 h-4 w-4 shrink-0 text-warning" aria-hidden="true" />
          {access?.locked_message ??
            "Complete your baseline assessment to unlock the Workplace English Coach."}
        </div>
      ) : null}

      {error ? <p className="text-sm text-danger">{error}</p> : null}

      <div className="grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-3">
        {(scenarios ?? PLACEHOLDER_SCENARIOS).map((scenario, index) => {
          const Icon = SCENARIO_ICONS[scenario.key] ?? Briefcase;
          const locked = !isUnlocked;
          const card = (
            <div
              className={cn(
                "group flex h-full animate-fade-up flex-col justify-between rounded-2xl border border-border bg-surface-elevated p-6 shadow-sm transition-all duration-200",
                !locked && "cursor-pointer hover:-translate-y-1 hover:shadow-md",
                locked && "opacity-60",
              )}
              style={{ animationDelay: `${index * 70}ms` }}
            >
              <div>
                <div className="mb-6 flex items-start justify-between">
                  <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-secondary text-primary transition-transform duration-300 group-hover:scale-110">
                    <Icon className="h-5 w-5" aria-hidden="true" />
                  </span>
                  {scenario.default_input_mode === "audio" ? (
                    <span className="flex items-center gap-1 rounded-full bg-muted px-3 py-1 text-xs font-medium text-muted-foreground">
                      <Mic className="h-3 w-3" aria-hidden="true" />
                      Voice
                    </span>
                  ) : null}
                </div>
                <h3 className="font-serif text-lg font-semibold text-foreground">
                  {scenario.label}
                </h3>
                <p className="mt-2 text-sm text-muted-foreground">
                  {scenario.roleplay
                    ? "Interactive roleplay — respond turn by turn."
                    : "Write your response and get graded feedback."}
                </p>
              </div>
              <div className="mt-6 text-sm font-medium text-primary">
                {locked ? (
                  <span className="text-muted-foreground">Complete assessment to unlock</span>
                ) : (
                  "Start Practicing"
                )}
              </div>
            </div>
          );

          return locked ? (
            <div key={scenario.key}>{card}</div>
          ) : (
            <a key={scenario.key} href={`/dashboard/coaching/${scenario.key}`}>
              {card}
            </a>
          );
        })}
      </div>

      {isUnlocked ? <CodeSwitchWordsCard /> : null}
    </div>
  );
}

// Shown briefly while the real list loads (same 5 scenarios, static labels only).
const PLACEHOLDER_SCENARIOS: CoachingScenarioMeta[] = [
  { key: "email_writing", label: "Email Writing", story: "", default_input_mode: "text", roleplay: false, example_prompts: [] },
  { key: "client_communication", label: "Client Communication", story: "", default_input_mode: "audio", roleplay: true, example_prompts: [] },
  { key: "meeting_communication", label: "Meeting Communication", story: "", default_input_mode: "audio", roleplay: true, example_prompts: [] },
  { key: "presentation_prep", label: "Presentation Preparation", story: "", default_input_mode: "audio", roleplay: false, example_prompts: [] },
  { key: "general_workplace", label: "Workplace English Practice", story: "", default_input_mode: "text", roleplay: false, example_prompts: [] },
];
