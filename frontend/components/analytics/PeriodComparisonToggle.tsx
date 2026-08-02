"use client";

import * as React from "react";
import { AlertTriangle, Info } from "lucide-react";
import { cn } from "@/lib/utils";
import type { MetricKey } from "@/lib/adminAlerts";
import {
  BASIS_LABELS,
  getAvailableBases,
  getComparison,
  type AvailableBasesResponse,
  type ComparisonBasis,
  type ComparisonResponse,
} from "@/lib/periodComparison";
import { DeltaIndicator } from "./DeltaIndicator";

const ALL_BASES: ComparisonBasis[] = ["WoW", "MoM", "YoY"];

interface PeriodComparisonToggleProps {
  metric: MetricKey;
  /** True for metrics where "up" is bad news (e.g. churn_rate) — flips DeltaIndicator's color. */
  upIsBad?: boolean;
  className?: string;
}

/**
 * Self-contained "Compare to previous period" control for a stat tile —
 * manages its own enabled/basis/data state so it can be dropped onto any
 * metric card without the parent page wiring comparison state per-card.
 */
export function PeriodComparisonToggle({ metric, upIsBad = false, className }: PeriodComparisonToggleProps) {
  const [enabled, setEnabled] = React.useState(false);
  const [basis, setBasis] = React.useState<ComparisonBasis>("WoW");
  const [available, setAvailable] = React.useState<AvailableBasesResponse | null>(null);
  const [data, setData] = React.useState<ComparisonResponse | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!enabled || available) return;
    getAvailableBases()
      .then((r) => {
        setAvailable(r);
        if (!r.available.includes(basis) && r.available.length > 0) {
          setBasis(r.available[0]);
        }
      })
      .catch(() => setError("Couldn't check comparison availability."));
  }, [enabled, available, basis]);

  React.useEffect(() => {
    if (!enabled || !available?.available.includes(basis)) {
      setData(null);
      return;
    }
    setError(null);
    getComparison(metric, basis)
      .then(setData)
      .catch(() => setError("Couldn't load comparison."));
  }, [enabled, available, basis, metric]);

  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <button
        type="button"
        onClick={() => setEnabled((v) => !v)}
        className="self-start text-xs font-medium text-primary hover:underline"
      >
        {enabled ? "Hide comparison" : "Compare to previous period"}
      </button>

      {enabled ? (
        <div className="flex flex-col gap-1.5">
          <div className="flex flex-wrap items-center gap-1.5">
            {ALL_BASES.map((b) => {
              const isAvailable = available ? available.available.includes(b) : true;
              return (
                <button
                  key={b}
                  type="button"
                  disabled={!isAvailable}
                  title={!isAvailable ? "Not enough historical data yet" : undefined}
                  onClick={() => setBasis(b)}
                  className={cn(
                    "rounded-full border px-2 py-0.5 text-[11px] font-medium transition-colors",
                    basis === b && isAvailable
                      ? "border-primary bg-primary text-primary-foreground"
                      : "border-border bg-surface text-muted-foreground",
                    !isAvailable && "cursor-not-allowed opacity-50",
                  )}
                >
                  {b}
                </button>
              );
            })}
          </div>

          {error ? <p className="text-xs text-danger">{error}</p> : null}

          {available && !available.available.includes(basis) ? (
            <p className="flex items-center gap-1 text-xs text-muted-foreground">
              <Info className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
              Not enough historical data for {BASIS_LABELS[basis]} yet ({available.days_of_history} day
              {available.days_of_history === 1 ? "" : "s"} since launch).
            </p>
          ) : null}

          {data ? (
            <div className="flex flex-col gap-1">
              <div className="flex items-center gap-2">
                <DeltaIndicator direction={data.direction} pctChange={data.pct_change} upIsBad={upIsBad} />
                <span className="text-xs text-muted-foreground">vs {BASIS_LABELS[data.basis]}</span>
              </div>
              {data.day_count_mismatch ? (
                <p className="flex items-center gap-1 text-[11px] text-warning">
                  <AlertTriangle className="h-3 w-3 shrink-0" aria-hidden="true" />
                  Periods have different day counts — treat this delta as directional, not exact.
                </p>
              ) : null}
              {data.outage_flagged ? (
                <p className="flex items-center gap-1 text-[11px] text-warning">
                  <AlertTriangle className="h-3 w-3 shrink-0" aria-hidden="true" />
                  {data.outage_note}
                </p>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
