"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { Plus, Sparkles, Trash2, Users } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { ApiError } from "@/lib/api";
import {
  startInterviewSession,
  type InterviewMode,
  type Panelist,
  type PersonaTone,
} from "@/lib/interviewCoach";
import { getPersonalizedOpening } from "@/lib/sessionMemory";

const MODES: { id: InterviewMode; label: string; description: string }[] = [
  { id: "standard", label: "Standard", description: "One-on-one behavioral interview." },
  { id: "panel", label: "Panel", description: "Up to 3 interviewers, each with their own focus." },
  { id: "case_study", label: "Case Study", description: "Market sizing, brainteasers, or business cases." },
  { id: "multi_round", label: "Interview Day", description: "Multiple rounds back to back." },
];

const TONES: { id: PersonaTone; label: string }[] = [
  { id: "neutral", label: "Neutral" },
  { id: "strict_corporate", label: "Strict Corporate" },
  { id: "friendly_startup", label: "Friendly Startup" },
  { id: "formal_panel", label: "Formal Panel" },
];

const CASE_TYPES = [
  { id: "market_sizing", label: "Market Sizing" },
  { id: "brainteaser", label: "Brainteaser" },
  { id: "business_case", label: "Business Case" },
];

export default function InterviewCoachSetupPage() {
  const router = useRouter();
  const [greeting, setGreeting] = React.useState<string | null>(null);

  const [mode, setMode] = React.useState<InterviewMode>("standard");
  const [roleOrMajor, setRoleOrMajor] = React.useState("");
  const [personaTone, setPersonaTone] = React.useState<PersonaTone>("neutral");
  const [panelists, setPanelists] = React.useState<Panelist[]>([
    { name: "", persona_tone: "formal_panel", focus_area: "" },
  ]);
  const [caseType, setCaseType] = React.useState("market_sizing");
  const [caseDifficulty, setCaseDifficulty] = React.useState("medium");
  const [rounds, setRounds] = React.useState<InterviewMode[]>(["standard", "panel", "case_study"]);

  const [isStarting, setIsStarting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    getPersonalizedOpening()
      .then((data) => setGreeting(data.opening_message))
      .catch(() => {});
  }, []);

  function addPanelist() {
    if (panelists.length >= 3) return;
    setPanelists((prev) => [...prev, { name: "", persona_tone: "formal_panel", focus_area: "" }]);
  }

  function updatePanelist(index: number, patch: Partial<Panelist>) {
    setPanelists((prev) => prev.map((p, i) => (i === index ? { ...p, ...patch } : p)));
  }

  function removePanelist(index: number) {
    setPanelists((prev) => prev.filter((_, i) => i !== index));
  }

  function toggleRound(roundMode: InterviewMode) {
    setRounds((prev) =>
      prev.includes(roundMode) ? prev.filter((r) => r !== roundMode) : [...prev, roundMode].slice(0, 4)
    );
  }

  async function handleStart() {
    setError(null);

    if (mode === "panel" && panelists.some((p) => !p.name.trim() || !p.focus_area.trim())) {
      setError("Fill in a name and focus area for every panelist.");
      return;
    }
    if (mode === "multi_round" && rounds.length === 0) {
      setError("Select at least one round.");
      return;
    }

    setIsStarting(true);
    try {
      const session = await startInterviewSession({
        mode,
        role_or_major: roleOrMajor.trim() || undefined,
        persona_tone: personaTone,
        panelists: mode === "panel" ? panelists : undefined,
        case_type: mode === "case_study" ? caseType : undefined,
        case_difficulty: mode === "case_study" ? caseDifficulty : undefined,
        rounds: mode === "multi_round" ? rounds : undefined,
      });

      sessionStorage.setItem(
        `interview-session-${session.session_id}`,
        JSON.stringify({
          mode: session.mode,
          turns: [{ speaker: mode === "panel" ? panelists[0]?.name || "AI" : "AI", question: session.opening_question, answer: null, flags: [] }],
        })
      );
      router.push(`/dashboard/interview-coach/${session.session_id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
      setIsStarting(false);
    }
  }

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-6">
      <div>
        <h1 className="font-serif text-h1 font-semibold text-foreground">
          Interview Coach
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Practice behavioral, panel, and case-study interviews with an AI interviewer.
        </p>
      </div>

      {greeting ? (
        <div className="flex items-start gap-2.5 rounded-xl border border-border bg-secondary px-4 py-3 text-sm text-secondary-foreground">
          <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
          {greeting}
        </div>
      ) : null}

      <div className="rounded-2xl border border-border bg-surface-elevated p-6 shadow-sm">
        <p className="text-sm font-medium text-foreground">Interview format</p>
        <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
          {MODES.map((m) => (
            <button
              key={m.id}
              type="button"
              onClick={() => setMode(m.id)}
              className={cn(
                "rounded-xl border p-4 text-left transition-colors",
                mode === m.id ? "border-primary bg-secondary" : "border-border hover:bg-surface",
              )}
            >
              <p className="text-sm font-semibold text-foreground">{m.label}</p>
              <p className="mt-1 text-xs text-muted-foreground">{m.description}</p>
            </button>
          ))}
        </div>

        <div className="mt-5 flex flex-col gap-4">
          <Input
            label="Target role or major (optional)"
            value={roleOrMajor}
            onChange={(event) => setRoleOrMajor(event.target.value)}
            placeholder="e.g. Software Engineer"
          />

          {mode !== "panel" ? (
            <div>
              <p className="text-sm font-medium text-foreground">Interviewer tone</p>
              <div className="mt-2 flex flex-wrap gap-2">
                {TONES.map((t) => (
                  <button
                    key={t.id}
                    type="button"
                    onClick={() => setPersonaTone(t.id)}
                    className={cn(
                      "rounded-full px-3 py-1.5 text-xs font-medium transition-colors",
                      personaTone === t.id
                        ? "bg-primary text-primary-foreground"
                        : "bg-surface text-muted-foreground hover:bg-muted",
                    )}
                  >
                    {t.label}
                  </button>
                ))}
              </div>
            </div>
          ) : null}

          {mode === "panel" ? (
            <div>
              <div className="flex items-center justify-between">
                <p className="text-sm font-medium text-foreground">Panelists</p>
                <button
                  type="button"
                  onClick={addPanelist}
                  disabled={panelists.length >= 3}
                  className="flex items-center gap-1 text-xs font-medium text-primary hover:text-primary-hover disabled:opacity-50"
                >
                  <Plus className="h-3.5 w-3.5" aria-hidden="true" />
                  Add panelist
                </button>
              </div>
              <div className="mt-2 flex flex-col gap-3">
                {panelists.map((p, i) => (
                  <div key={i} className="flex items-start gap-2 rounded-xl border border-border p-3">
                    <Users className="mt-2.5 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                    <div className="grid flex-1 grid-cols-2 gap-2">
                      <Input
                        label="Name"
                        value={p.name}
                        onChange={(event) => updatePanelist(i, { name: event.target.value })}
                      />
                      <Input
                        label="Focus area"
                        value={p.focus_area}
                        onChange={(event) => updatePanelist(i, { focus_area: event.target.value })}
                        placeholder="e.g. technical depth"
                      />
                    </div>
                    {panelists.length > 1 ? (
                      <button
                        type="button"
                        onClick={() => removePanelist(i)}
                        className="mt-6 text-muted-foreground hover:text-danger"
                        aria-label="Remove panelist"
                      >
                        <Trash2 className="h-4 w-4" aria-hidden="true" />
                      </button>
                    ) : null}
                  </div>
                ))}
              </div>
            </div>
          ) : null}

          {mode === "case_study" ? (
            <div className="grid grid-cols-2 gap-4">
              <div>
                <p className="text-sm font-medium text-foreground">Case type</p>
                <div className="mt-2 flex flex-col gap-1.5">
                  {CASE_TYPES.map((c) => (
                    <button
                      key={c.id}
                      type="button"
                      onClick={() => setCaseType(c.id)}
                      className={cn(
                        "rounded-lg px-3 py-1.5 text-left text-xs font-medium transition-colors",
                        caseType === c.id
                          ? "bg-primary text-primary-foreground"
                          : "bg-surface text-muted-foreground hover:bg-muted",
                      )}
                    >
                      {c.label}
                    </button>
                  ))}
                </div>
              </div>
              <div>
                <p className="text-sm font-medium text-foreground">Difficulty</p>
                <div className="mt-2 flex flex-col gap-1.5">
                  {["easy", "medium", "hard"].map((d) => (
                    <button
                      key={d}
                      type="button"
                      onClick={() => setCaseDifficulty(d)}
                      className={cn(
                        "rounded-lg px-3 py-1.5 text-left text-xs font-medium capitalize transition-colors",
                        caseDifficulty === d
                          ? "bg-primary text-primary-foreground"
                          : "bg-surface text-muted-foreground hover:bg-muted",
                      )}
                    >
                      {d}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          ) : null}

          {mode === "multi_round" ? (
            <div>
              <p className="text-sm font-medium text-foreground">Rounds (in order, up to 4)</p>
              <div className="mt-2 flex flex-wrap gap-2">
                {MODES.filter((m) => m.id !== "multi_round").map((m) => {
                  const position = rounds.indexOf(m.id);
                  return (
                    <button
                      key={m.id}
                      type="button"
                      onClick={() => toggleRound(m.id)}
                      className={cn(
                        "rounded-full px-3 py-1.5 text-xs font-medium transition-colors",
                        position >= 0
                          ? "bg-primary text-primary-foreground"
                          : "bg-surface text-muted-foreground hover:bg-muted",
                      )}
                    >
                      {position >= 0 ? `${position + 1}. ` : ""}
                      {m.label}
                    </button>
                  );
                })}
              </div>
            </div>
          ) : null}
        </div>

        {error ? <p className="mt-4 text-sm text-danger">{error}</p> : null}

        <Button size="lg" className="mt-5" loading={isStarting} onClick={handleStart}>
          Start Interview
        </Button>
      </div>

      <Button href="/dashboard/resume-jd" variant="outline" size="sm" className="self-start">
        Prep with your resume &amp; a job description
      </Button>
    </div>
  );
}
