"use client";

import * as React from "react";
import { ArrowDown, ArrowRight, ArrowUp, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";

interface DeltaIndicatorProps {
  direction: "up" | "down" | "flat" | "new";
  pctChange: number | null;
  /** When true (e.g. churn), an "up" delta is bad news — flips the color mapping. */
  upIsBad?: boolean;
  className?: string;
}

/**
 * Icon + numeric value, never color alone (US-204 acceptance criterion) —
 * the arrow direction and the sign on the number both carry the meaning
 * independently of the tone color.
 */
export function DeltaIndicator({ direction, pctChange, upIsBad = false, className }: DeltaIndicatorProps) {
  if (direction === "new") {
    return (
      <span className={cn("inline-flex items-center gap-1 rounded-full bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary", className)}>
        <Sparkles className="h-3 w-3" aria-hidden="true" />
        New
      </span>
    );
  }

  const isGood = direction === "flat" ? null : upIsBad ? direction === "down" : direction === "up";
  const toneClass = isGood === null ? "text-muted-foreground" : isGood ? "text-success" : "text-danger";
  const Icon = direction === "up" ? ArrowUp : direction === "down" ? ArrowDown : ArrowRight;
  const sign = direction === "up" ? "+" : direction === "down" ? "" : "±";

  return (
    <span className={cn("inline-flex items-center gap-1 text-xs font-medium", toneClass, className)}>
      <Icon className="h-3.5 w-3.5" aria-hidden="true" />
      {pctChange !== null ? `${sign}${Math.abs(pctChange).toFixed(1)}%` : "—"}
    </span>
  );
}
