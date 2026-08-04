"use client";

import * as React from "react";
import { Star } from "lucide-react";

import { rateScenarioSession } from "@/lib/scenario";
import { cn } from "@/lib/utils";

/**
 * Post-session satisfaction rating (1-5).
 *
 * Feeds "Learner satisfaction" on the Template Performance Dashboard (CM-US-09 /
 * US-193) and the "user feedback" drift signal (CM-US-12 / US-196).
 *
 * Rating is always optional and there is no skip button to dismiss — a learner
 * who ignores it simply leaves it unrated, and every consumer treats unrated as
 * "no data" rather than as a low score. A failed submit is swallowed on purpose:
 * losing an optional rating must never interrupt the results screen.
 */

const RATINGS = [1, 2, 3, 4, 5] as const;
const LABELS: Record<number, string> = {
  1: "Not useful",
  2: "Slightly useful",
  3: "Useful",
  4: "Very useful",
  5: "Extremely useful",
};

export function SessionRating({ sessionId }: { sessionId: string }) {
  const [rating, setRating] = React.useState<number | null>(null);
  const [hovered, setHovered] = React.useState<number | null>(null);
  const [saved, setSaved] = React.useState(false);
  const [failed, setFailed] = React.useState(false);

  async function submit(value: number) {
    setRating(value);
    setFailed(false);
    try {
      await rateScenarioSession(sessionId, value);
      setSaved(true);
    } catch {
      setFailed(true);
    }
  }

  const active = hovered ?? rating;

  return (
    <div className="rounded-2xl border border-border bg-surface-elevated p-6 shadow-sm">
      <h2 className="font-serif text-lg font-semibold text-foreground">
        How useful was this practice?
      </h2>
      <p className="mt-1 text-sm text-muted-foreground">
        Optional — it helps us spot scenarios that have stopped working well.
      </p>

      {/* radiogroup rather than buttons: a rating is one choice from a set, and
          this gives arrow-key navigation for free in assistive tech. */}
      <div
        role="radiogroup"
        aria-label="Rate this practice session"
        className="mt-4 flex items-center gap-1"
        onMouseLeave={() => setHovered(null)}
      >
        {RATINGS.map((value) => {
          const filled = active !== null && value <= active;
          return (
            <button
              key={value}
              type="button"
              role="radio"
              aria-checked={rating === value}
              aria-label={`${value} out of 5 — ${LABELS[value]}`}
              disabled={saved}
              onClick={() => submit(value)}
              onMouseEnter={() => setHovered(value)}
              onFocus={() => setHovered(value)}
              onBlur={() => setHovered(null)}
              className={cn(
                "rounded-lg p-1.5 transition-transform duration-fast",
                !saved && "hover:scale-110",
                saved && "cursor-default",
              )}
            >
              <Star
                className={cn(
                  "h-6 w-6 transition-colors duration-fast",
                  filled ? "fill-warning text-warning" : "text-muted-foreground",
                )}
                aria-hidden="true"
              />
            </button>
          );
        })}
        {active !== null ? (
          <span className="ml-2 text-sm text-muted-foreground">{LABELS[active]}</span>
        ) : null}
      </div>

      <p role="status" className="mt-2 min-h-[1.25rem] text-sm">
        {saved ? (
          <span className="text-success">Thanks — your rating was saved.</span>
        ) : failed ? (
          <span className="text-muted-foreground">
            Couldn&apos;t save that rating, but your session results are unaffected.
          </span>
        ) : null}
      </p>
    </div>
  );
}
