"use client";

import * as React from "react";
import { Sparkles, Wand2, TriangleAlert, Info, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { ApiError } from "@/lib/api";
import {
  generateRewrite,
  scoreRewrite,
  explainRewrite,
  DIFFICULTY_LABELS,
  DIMENSION_LABELS,
  CATEGORY_LABELS,
  CHECK_LABELS,
  type DifficultyLevel,
  type GenerateRewriteResult,
  type ScoreRewriteResult,
  type ExplainRewriteResult,
} from "@/lib/rewrite";
import { introduceVocab } from "@/lib/rewriteVocab";
import { ScriptPracticePanel } from "@/components/dashboard/ScriptPracticePanel";
import { RewriteVocabPanel } from "@/components/dashboard/RewriteVocabPanel";
import { cn } from "@/lib/utils";

const DIFFICULTY_OPTIONS: { value: "" | DifficultyLevel; label: string }[] = [
  { value: "", label: "Auto (my level)" },
  { value: "beginner", label: DIFFICULTY_LABELS.beginner },
  { value: "intermediate", label: DIFFICULTY_LABELS.intermediate },
  { value: "advanced", label: DIFFICULTY_LABELS.advanced },
  { value: "executive", label: DIFFICULTY_LABELS.executive },
];

// A 0-100 improvement score where 50 = "no change". Colour by which side of neutral.
function scoreTone(score: number): { bar: string; text: string } {
  if (score >= 55) return { bar: "bg-primary", text: "text-primary" };
  if (score <= 45) return { bar: "bg-danger", text: "text-danger" };
  return { bar: "bg-muted-foreground/50", text: "text-muted-foreground" };
}

export default function RewriteLabPage() {
  const [original, setOriginal] = React.useState("");
  const [context, setContext] = React.useState("");
  const [difficulty, setDifficulty] = React.useState<"" | DifficultyLevel>("");

  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [gen, setGen] = React.useState<GenerateRewriteResult | null>(null);
  const [score, setScore] = React.useState<ScoreRewriteResult | null>(null);
  const [explain, setExplain] = React.useState<ExplainRewriteResult | null>(null);

  // US-160: bump to tell the (self-fetching, paginated) vocab panel to refetch.
  const [vocabSignal, setVocabSignal] = React.useState(0);

  async function handleRun() {
    if (!original.trim() || loading) return;
    setLoading(true);
    setError(null);
    setGen(null);
    setScore(null);
    setExplain(null);
    try {
      // US-158 (+ US-161 quality gate): generate the personalized rewrite first.
      const g = await generateRewrite(original.trim(), {
        difficulty: difficulty || undefined,
        context: context.trim() || undefined,
      });
      setGen(g);
      // US-156 + US-159: score and explain the same {original, rewrite} pair.
      // US-160: seed the advanced words this rewrite introduced, then signal the panel.
      const [s, e] = await Promise.all([
        scoreRewrite(g.original, g.rewrite),
        explainRewrite(g.original, g.rewrite),
        introduceVocab(g.original, g.rewrite, context.trim() || undefined)
          .then(() => setVocabSignal((n) => n + 1))
          .catch(() => {}),
      ]);
      setScore(s);
      setExplain(e);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex animate-fade-up flex-col gap-8">
      <div>
        <h1 className="font-serif text-h1 font-semibold text-foreground">
          Rewrite Lab
        </h1>
        <p className="mt-2 max-w-2xl text-sm text-muted-foreground">
          Paste something you said or wrote — an interview answer, an email line, a meeting point.
          Speeky rewrites it at your level, scores how much it improved, and explains every change so
          you learn to do it yourself.
        </p>
      </div>

      {/* ── Input ─────────────────────────────────────────────────────────── */}
      <div className="flex flex-col gap-4 rounded-2xl border border-border bg-surface-elevated p-6 shadow-sm">
        <Textarea
          label="Your original wording"
          placeholder="e.g. i think i am a good fit for this job because i work hard"
          rows={4}
          value={original}
          onChange={(e) => setOriginal(e.target.value)}
        />
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="flex flex-col gap-1.5">
            <label htmlFor="rw-context" className="text-sm font-medium text-foreground">
              Context <span className="text-muted-foreground">(optional)</span>
            </label>
            <input
              id="rw-context"
              type="text"
              placeholder="e.g. HR interview answer"
              value={context}
              onChange={(e) => setContext(e.target.value)}
              className="h-11 w-full rounded-xl border border-input bg-surface px-4 text-sm text-foreground placeholder:text-muted-foreground transition-colors focus:border-primary focus:outline-none focus:ring-2 focus:ring-ring/40"
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <label htmlFor="rw-difficulty" className="text-sm font-medium text-foreground">
              Rewrite level
            </label>
            <select
              id="rw-difficulty"
              value={difficulty}
              onChange={(e) => setDifficulty(e.target.value as "" | DifficultyLevel)}
              className="h-11 w-full rounded-xl border border-input bg-surface px-4 text-sm text-foreground transition-colors focus:border-primary focus:outline-none focus:ring-2 focus:ring-ring/40"
            >
              {DIFFICULTY_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>
        </div>
        <div className="flex items-center justify-between gap-3">
          <span className="text-xs text-muted-foreground">
            Your facts are preserved — the rewrite never invents new details.
          </span>
          <Button className="h-auto md:h-10" onClick={handleRun} loading={loading} disabled={!original.trim()}>
            <Wand2 className="h-4 w-4" aria-hidden="true" />
            Rewrite &amp; Analyze
          </Button>
        </div>
      </div>

      {!gen && !loading ? (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <div className="flex items-start gap-3 rounded-2xl border border-border bg-surface-elevated/75 p-4 shadow-sm">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-secondary text-primary">
              <ShieldCheck className="h-4 w-4" aria-hidden="true" />
            </span>
            <div>
              <p className="text-sm font-semibold text-foreground">Preserves your meaning</p>
              <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                Your facts and intent stay intact.
              </p>
            </div>
          </div>
          <div className="flex items-start gap-3 rounded-2xl border border-border bg-surface-elevated/75 p-4 shadow-sm">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-secondary text-primary">
              <Sparkles className="h-4 w-4" aria-hidden="true" />
            </span>
            <div>
              <p className="text-sm font-semibold text-foreground">Adapts to your level</p>
              <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                The wording matches your learning stage.
              </p>
            </div>
          </div>
          <div className="flex items-start gap-3 rounded-2xl border border-border bg-surface-elevated/75 p-4 shadow-sm">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-secondary text-primary">
              <Info className="h-4 w-4" aria-hidden="true" />
            </span>
            <div>
              <p className="text-sm font-semibold text-foreground">Explains every change</p>
              <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                Learn why the revised version works better.
              </p>
            </div>
          </div>
        </div>
      ) : null}

      {error ? (
        <div className="flex items-start gap-2.5 rounded-xl border border-danger/30 bg-danger/5 px-4 py-3 text-sm text-foreground">
          <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0 text-danger" aria-hidden="true" />
          {error}
        </div>
      ) : null}

      {/* ── US-158: the rewrite ───────────────────────────────────────────── */}
      {gen ? (
        <div className="flex flex-col gap-4 rounded-2xl border border-border bg-surface-elevated p-6 shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="flex items-center gap-2 font-serif text-lg font-semibold text-foreground">
              <Sparkles className="h-4 w-4 text-primary" aria-hidden="true" />
              Your rewrite
            </h2>
            <span className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              <span className="rounded-full bg-secondary px-3 py-1 font-medium text-primary">
                {DIFFICULTY_LABELS[gen.difficulty_used]} level
                {gen.auto_detected ? " · auto" : ""}
              </span>
              {/* US-161: quality gate outcome */}
              {gen.validation?.validated ? (
                gen.validation.passed ? (
                  <span className="flex items-center gap-1 rounded-full bg-primary/10 px-3 py-1 font-medium text-primary">
                    <ShieldCheck className="h-3 w-3" aria-hidden="true" />
                    Quality-checked
                    {gen.attempts && gen.attempts > 1 ? ` · ${gen.attempts} tries` : ""}
                  </span>
                ) : (
                  <span className="flex items-center gap-1 rounded-full bg-warning/10 px-3 py-1 font-medium text-warning">
                    <TriangleAlert className="h-3 w-3" aria-hidden="true" />
                    Needs review
                  </span>
                )
              ) : null}
              {gen.generated_by === "offline" ? (
                <span className="rounded-full bg-muted px-3 py-1">offline mode</span>
              ) : null}
            </span>
          </div>
          {gen.generated_by === "offline" ? (
            <div className="flex items-start gap-2.5 rounded-xl border border-warning/40 bg-warning/10 px-4 py-3 text-sm text-foreground">
              <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0 text-warning" aria-hidden="true" />
              <span>
                The AI rewriter is temporarily unavailable (usage limit reached). This is only a basic
                cleanup, not a full rewrite — please try again shortly.
              </span>
            </div>
          ) : null}
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <div className="rounded-xl border border-border bg-surface p-4">
              <p className="mb-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Original
              </p>
              <p className="text-sm text-foreground">{gen.original}</p>
            </div>
            <div className="rounded-xl border border-primary/30 bg-primary/5 p-4">
              <p className="mb-1.5 text-xs font-medium uppercase tracking-wide text-primary">
                Rewrite
              </p>
              <p className="text-sm text-foreground">{gen.rewrite}</p>
            </div>
          </div>
          {/* US-161: which checks the rewrite passed, and any unresolved issues */}
          {gen.validation?.validated ? (
            <div className="flex flex-col gap-2">
              <div className="flex flex-wrap gap-1.5">
                {Object.entries(gen.validation.checks).map(([key, ok]) => (
                  <span
                    key={key}
                    className={cn(
                      "rounded-full px-2.5 py-0.5 text-xs font-medium",
                      ok
                        ? "bg-primary/10 text-primary"
                        : "bg-danger/10 text-danger",
                    )}
                  >
                    {ok ? "✓" : "✕"} {CHECK_LABELS[key] ?? key}
                  </span>
                ))}
              </div>
              {gen.validation.issues.length > 0 ? (
                <ul className="list-inside list-disc text-xs text-muted-foreground">
                  {gen.validation.issues.map((issue, i) => (
                    <li key={i}>{issue}</li>
                  ))}
                </ul>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : null}

      {/* ── US-157: practice the rewrite aloud ────────────────────────────── */}
      {gen ? (
        <ScriptPracticePanel
          key={gen.rewrite}
          script={gen.rewrite}
          context={context.trim() || undefined}
        />
      ) : null}

      {/* ── US-156: improvement score ─────────────────────────────────────── */}
      {score ? (
        <div className="flex flex-col gap-4 rounded-2xl border border-border bg-surface-elevated p-6 shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="font-serif text-lg font-semibold text-foreground">
              Improvement Score
            </h2>
            <span className={cn("text-h2 font-semibold", scoreTone(score.overall_score).text)}>
              {score.overall_score}
              <span className="text-sm text-muted-foreground">/100</span>
            </span>
          </div>
          <p className="text-sm text-muted-foreground">{score.summary}</p>
          {!score.significant_improvement ? (
            <div className="flex items-start gap-2.5 rounded-xl border border-border bg-surface px-4 py-3 text-sm text-foreground">
              <Info className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
              Your original was already strong — only minor polish was needed.
            </div>
          ) : null}
          <ul className="flex flex-col gap-3">
            {score.dimensions.map((d) => {
              const tone = scoreTone(d.score);
              return (
                <li key={d.name} className="flex flex-col gap-1.5">
                  <div className="flex items-center justify-between text-sm">
                    <span className="font-medium text-foreground">
                      {DIMENSION_LABELS[d.name] ?? d.name}
                    </span>
                    <span className={cn("font-semibold", tone.text)}>{d.score}</span>
                  </div>
                  <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
                    <div
                      className={cn("h-full rounded-full transition-all", tone.bar)}
                      style={{ width: `${d.score}%` }}
                    />
                  </div>
                  <p className="text-xs text-muted-foreground">{d.explanation}</p>
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}

      {/* ── US-159: explainability ────────────────────────────────────────── */}
      {explain ? (
        <div className="flex flex-col gap-4 rounded-2xl border border-border bg-surface-elevated p-6 shadow-sm">
          <h2 className="font-serif text-lg font-semibold text-foreground">
            Why was this changed?
          </h2>
          <p className="text-sm text-muted-foreground">{explain.summary}</p>
          {!explain.has_meaningful_changes ? (
            <div className="flex items-start gap-2.5 rounded-xl border border-border bg-surface px-4 py-3 text-sm text-foreground">
              <Info className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
              Your original wording was already effective.
            </div>
          ) : (
            <ul className="flex flex-col gap-3">
              {explain.changes.map((c, i) => (
                <li key={i} className="rounded-xl border border-border bg-surface p-4">
                  <span className="mb-2 inline-block rounded-full bg-secondary px-2.5 py-0.5 text-xs font-medium text-primary">
                    {CATEGORY_LABELS[c.category] ?? c.category}
                  </span>
                  <p className="text-sm text-foreground">
                    <span className="text-muted-foreground line-through">{c.before}</span>
                    {c.before && c.after ? " → " : ""}
                    <span className="font-medium">{c.after}</span>
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground">{c.explanation}</p>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}

      {/* ── US-160: vocabulary mastery (self-fetching, paginated) ─────────── */}
      <RewriteVocabPanel refreshSignal={vocabSignal} />
    </div>
  );
}
