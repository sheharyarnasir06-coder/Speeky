"use client";

import * as React from "react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

type Trend = "improved" | "stagnated" | "degraded" | null;

interface StatTileProps {
  label: string;
  value: string;
  icon?: LucideIcon;
  /** Optional 0-100 meter under the value — the SOW's confidence/fluency scores. */
  meter?: number | null;
  trend?: Trend;
  hint?: string;
  onClick?: () => void;
  className?: string;
}

const trendClasses: Record<Exclude<Trend, null>, string> = {
  improved: "text-success",
  stagnated: "text-muted-foreground",
  degraded: "text-warning",
};

/**
 * The product's metric tile — Practice Time, Confidence, Fluency, Vocabulary.
 *
 * These four numbers ARE the SOW's promise ("track progress through confidence,
 * fluency and pronunciation scores"), so they get one deliberate treatment instead
 * of the four slightly-different hand-built tiles that existed before.
 *
 * Design intent: the value is the loudest thing in the tile (tabular figures so
 * digits don't jitter as they update), the label is quiet, and the optional meter
 * gives instant "where am I on the scale" without the user reading the number.
 */
export function StatTile({
  label,
  value,
  icon: Icon,
  meter = null,
  trend = null,
  hint,
  onClick,
  className,
}: StatTileProps) {
  const interactive = typeof onClick === "function";
  const Wrapper = interactive ? "button" : "div";

  return (
    <Wrapper
      type={interactive ? "button" : undefined}
      onClick={onClick}
      title={hint}
      className={cn(
        "group flex flex-col gap-2 rounded-xl border border-border bg-surface p-4 text-left",
        interactive &&
          "transition-[transform,border-color,box-shadow] duration-fast ease-out-expo " +
            "hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-md " +
            "motion-reduce:hover:translate-y-0",
        className,
      )}
    >
      <span className="flex items-center gap-1.5 text-overline uppercase text-muted-foreground">
        {Icon ? <Icon className="h-3.5 w-3.5" aria-hidden="true" /> : null}
        {label}
      </span>

      <span
        className={cn(
          "font-serif text-h2 font-semibold tabular-nums text-foreground",
          trend ? trendClasses[trend] : undefined,
        )}
      >
        {value}
      </span>

      {meter !== null && Number.isFinite(meter) ? (
        <div
          className="h-1.5 w-full overflow-hidden rounded-full bg-muted"
          role="progressbar"
          aria-valuenow={Math.round(meter)}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label={`${label} score`}
        >
          <div
            className="h-full origin-left rounded-full bg-primary animate-grow-x motion-reduce:animate-none"
            style={{ width: `${Math.max(0, Math.min(100, meter))}%` }}
          />
        </div>
      ) : null}
    </Wrapper>
  );
}
