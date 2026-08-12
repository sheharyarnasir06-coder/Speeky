"use client";

import * as React from "react";
import Link from "next/link";
import {
  ArrowRight,
  Briefcase,
  FileText,
  Lock,
  MessagesSquare,
  Mic,
  Search,
  UserSquare2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { EXPLORE_STATIC_SCENARIOS, type ExploreScenario } from "@/lib/dashboard-data";
import { getScenarios, type ScenarioListItem } from "@/lib/scenario";
import { listCategories, type Category } from "@/lib/categories";
import { resolveIcon } from "@/lib/icon-map";
import { useAssessmentAccess } from "@/contexts/AssessmentContext";
import { ExploreResumeBanner } from "@/components/dashboard/ExploreResumeBanner";
import { AiScenarioCardArt } from "@/components/common/AiScenarioThumbnail";

function toExploreScenario(scenario: ScenarioListItem, categories: Category[]): ExploreScenario {
  const match = categories.find((c) => c.name === scenario.category);
  return {
    id: scenario.key,
    category: scenario.category,
    icon: resolveIcon(match?.icon ?? "folder"),
    title: scenario.label,
    description: scenario.intent,
    difficulty:
      scenario.goal_type === "negotiation" ? "Negotiation" : "Roleplay",
    showAiAvatar: true,
    href: `/dashboard/scenarios/${scenario.key}`,
  };
}

export default function ExplorePage() {
  const { access } = useAssessmentAccess();
  const [query, setQuery] = React.useState("");
  const [category, setCategory] = React.useState<string>("All");
  const [categories, setCategories] = React.useState<Category[]>([]);
  const [liveScenarios, setLiveScenarios] = React.useState<ExploreScenario[]>(
    [],
  );

  const isUnlocked = access?.access_level === "full_access";

  React.useEffect(() => {
    if (!isUnlocked) return;
    listCategories()
      .then((data) => setCategories(data.categories))
      .catch(() => {
        // Non-fatal — category filter chips just fall back to whatever scenarios carry.
      });
  }, [isUnlocked]);

  React.useEffect(() => {
    if (!isUnlocked) return;
    getScenarios()
      .then((data) => setLiveScenarios(data.scenarios.map((s) => toExploreScenario(s, categories))))
      .catch(() => {
        // Non-fatal — the static cards above (Interview Coach, etc.) still render.
      });
  }, [isUnlocked, categories]);

  const categoryNames = React.useMemo(() => {
    const names = new Set(categories.map((c) => c.name));
    [...EXPLORE_STATIC_SCENARIOS, ...liveScenarios].forEach((s) => names.add(s.category));
    return Array.from(names);
  }, [categories, liveScenarios]);

  // Keep 1st appearance of each scenario.
  const seen = new Set();
  const allScenarios = [...EXPLORE_STATIC_SCENARIOS, ...liveScenarios].filter(
    (scenario) => {
      if (seen.has(scenario.id)) return false;
      seen.add(scenario.id);
      return true;
    },
  );

  const scenarios = allScenarios.filter((scenario) => {
    const matchesCategory =
      category === "All" || scenario.category === category;
    const matchesQuery = scenario.title
      .toLowerCase()
      .includes(query.trim().toLowerCase());
    return matchesCategory && matchesQuery;
  });

  return (
    <div className="flex flex-col gap-8">
      <div>
        <h1 className="font-serif text-h1 font-semibold text-foreground">
          Select Your Scenario
        </h1>
        <p className="mt-2 max-w-xl text-sm text-muted-foreground">
          Choose a real-world situation to practice your English with Speeky.
        </p>
      </div>

      <ExploreResumeBanner />

      {!isUnlocked ? (
        <div className="flex items-start gap-2.5 rounded-xl border border-warning/30 bg-warning/10 px-4 py-3 text-sm text-foreground">
          <Lock
            className="mt-0.5 h-4 w-4 shrink-0 text-warning"
            aria-hidden="true"
          />
          {access?.locked_message ??
            "Complete your baseline assessment to unlock scenario practice."}
        </div>
      ) : null}

      <div>
        <h2 className="font-serif text-xl font-semibold text-foreground">
          AI Coach
        </h2>
        <div className="mt-4 grid grid-cols-1 gap-6 sm:grid-cols-2">
          {[
            {
              href: "/dashboard/conversation",
              icon: MessagesSquare,
              title: "AI Conversation Practice",
              description:
                "Open-ended conversation practice on any topic, with your AI coach.",
              gated: true,
              showAiAvatar: true,
            },
            {
              href: "/dashboard/pronunciation",
              icon: Mic,
              title: "Pronunciation Coach",
              description: "Practice phoneme-targeted sentences and retry the words you miss.",
              gated: true,
              showAiAvatar: false,
            },
            {
              href: "/dashboard/coaching",
              icon: Briefcase,
              title: "Workplace English Coach",
              description:
                "Emails, client calls, meetings, and presentations — graded for tone and clarity.",
              gated: true,
              showAiAvatar: true,
            },
            {
              href: "/dashboard/interview-coach",
              icon: UserSquare2,
              title: "Interview Coach",
              description:
                "Standard, panel, case-study, and multi-round mock interviews.",
              gated: false,
              showAiAvatar: true,
            },
            {
              href: "/dashboard/resume-jd",
              icon: FileText,
              title: "Resume & Job Description",
              description:
                "Upload your resume and a JD to tailor your interview practice.",
              gated: false,
              showAiAvatar: false,
            },
          ].map((item) => {
            const Icon = item.icon;
            const itemUnlocked = item.gated ? isUnlocked : true;
            const card = (
              <div
                className={cn(
                  "group relative flex h-full overflow-hidden rounded-2xl border border-border bg-surface-elevated p-6 shadow-sm transition-all duration-200",
                  item.showAiAvatar ? "min-h-[230px] flex-col justify-between sm:pr-[46%]" : "flex-col justify-between",
                  itemUnlocked &&
                    "cursor-pointer hover:-translate-y-1 hover:shadow-md",
                  // Locked state is conveyed by the dashed border and the
                  // "Locked" copy below — NOT by dimming the card, which dragged
                  // body text to 2.83:1 in dark mode (WCAG AA needs 4.5:1).
                  !itemUnlocked && "border-dashed bg-surface",
                )}
              >
                {item.showAiAvatar ? (
                  <AiScenarioCardArt title={item.title} locked={!itemUnlocked} />
                ) : null}
                <div className="relative z-10">
                  <span className={cn(
                    "flex h-11 w-11 items-center justify-center rounded-xl bg-secondary text-primary transition-transform duration-300 group-hover:scale-110",
                    !itemUnlocked && "opacity-70",
                  )}>
                    <Icon className="h-5 w-5" aria-hidden="true" />
                  </span>
                  <h3 className="mt-4 font-serif text-lg font-semibold text-foreground">
                    {item.title}
                  </h3>
                  <p className="mt-2 text-sm text-muted-foreground">
                    {item.description}
                  </p>
                </div>
                <div className="relative z-10 mt-6 flex items-center gap-2 text-sm font-medium text-primary">
                  {itemUnlocked ? (
                    <>
                      Start
                      <ArrowRight
                        className="h-4 w-4 transition-transform group-hover:translate-x-1"
                        aria-hidden="true"
                      />
                    </>
                  ) : (
                    <span className="text-muted-foreground">
                      Complete assessment to unlock
                    </span>
                  )}
                </div>
              </div>
            );
            return itemUnlocked ? (
              <Link key={item.href} href={item.href}>
                {card}
              </Link>
            ) : (
              <div key={item.href}>{card}</div>
            );
          })}
        </div>
      </div>

      <div>
        <h2 className="font-serif text-xl font-semibold text-foreground">
          Choose Your Mission
        </h2>
      </div>

      <div className="flex flex-col gap-4 sm:flex-row sm:items-center">
        <div className="relative flex-1">
          <Search
            className="absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
            aria-hidden="true"
          />
          <input
            type="text"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search scenarios..."
            className="h-11 w-full rounded-xl border border-input bg-surface pl-11 pr-4 text-sm text-foreground placeholder:text-muted-foreground focus:border-primary focus:outline-none focus:ring-2 focus:ring-ring/40"
          />
        </div>
        <div className="flex items-center gap-2 overflow-x-auto pb-1">
          {["All", ...categoryNames].map((c) => (
            <button
              key={c}
              type="button"
              onClick={() => setCategory(c)}
              className={cn(
                "shrink-0 rounded-full px-4 py-2 text-sm font-medium transition-colors",
                category === c
                  ? "bg-primary text-primary-foreground"
                  : "bg-surface text-muted-foreground hover:bg-muted",
              )}
            >
              {c}
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
        {scenarios.map((scenario, index) => {
          const Icon = scenario.icon;
          const locked = !isUnlocked;
          const clickable = isUnlocked && Boolean(scenario.href);

          const card = (
            <div
              className={cn(
                "group relative flex h-full overflow-hidden rounded-2xl border border-border bg-surface-elevated p-6 shadow-sm transition-all duration-200",
                scenario.showAiAvatar ? "min-h-[230px] flex-col justify-between sm:pr-[46%]" : "flex-col justify-between",
                clickable &&
                  "cursor-pointer hover:-translate-y-1 hover:shadow-md",
                // See the note on the card above: container opacity fails AA.
                locked && "border-dashed bg-surface",
              )}
            >
              {scenario.showAiAvatar ? (
                <AiScenarioCardArt title={scenario.title} locked={locked} />
              ) : null}
              <div className="relative z-10">
                <div className="mb-6 flex items-start justify-between">
                  <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-secondary text-primary transition-transform duration-300 group-hover:scale-110">
                    <Icon className="h-5 w-5" aria-hidden="true" />
                  </span>
                  <span className="flex items-center gap-1 rounded-full bg-muted px-3 py-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    {locked ? (
                      <Lock className="h-3 w-3" aria-hidden="true" />
                    ) : null}
                    {locked ? "Locked" : scenario.difficulty}
                  </span>
                </div>
                <h3 className="font-serif text-lg font-semibold text-foreground">
                  {scenario.title}
                </h3>
                <p className="mt-2 max-w-md text-sm text-muted-foreground">
                  {scenario.description}
                </p>
              </div>
              <div className="relative z-10 mt-6 flex items-center gap-2 text-sm font-medium text-primary">
                {locked ? (
                  <span className="text-muted-foreground">
                    Complete assessment to unlock
                  </span>
                ) : (
                  <>
                    {scenario.href ? "Start Practicing" : "Preview"}
                    <ArrowRight
                      className="h-4 w-4 transition-transform group-hover:translate-x-1"
                      aria-hidden="true"
                    />
                  </>
                )}
              </div>
            </div>
          );

          const wrapperStyle = { animationDelay: `${index * 70}ms` };

          if (clickable && scenario.href) {
            return (
              <Link
                key={scenario.id}
                href={scenario.href}
                className={cn(
                  "animate-fade-up",
                  scenario.featured && "lg:col-span-2",
                )}
                style={wrapperStyle}
              >
                {card}
              </Link>
            );
          }

          return (
            <div
              key={scenario.id}
              className={cn(
                "animate-fade-up",
                scenario.featured && "lg:col-span-2",
              )}
              style={wrapperStyle}
            >
              {card}
            </div>
          );
        })}
      </div>
    </div>
  );
}
