"use client";

/**
 * A single timeline channel, drawn as an inline SVG sparkline.
 *
 * The one rule that matters: **a gap is drawn as a gap.** Null bins mean nothing was measured
 * there — the face was lost, the tab was hidden, the pose stream dropped — and joining across
 * them would draw a confident straight line through a period we know nothing about. Since the
 * whole feature turns on not confusing "absent" with "zero", the chart must not reintroduce
 * that confusion visually. Each run of consecutive real values becomes its own path.
 */

import * as React from "react";

import { cn } from "@/lib/utils";

interface DeliverySparklineProps {
  label: string;
  /** 0..1 per bin; null where nothing was measured. */
  values: (number | null)[];
  binSeconds: number;
  /** Tailwind stroke class, e.g. "stroke-primary". */
  className?: string;
  /** Formats the summary shown beside the label. */
  format?: (mean: number) => string;
}

const WIDTH = 320;
const HEIGHT = 40;
const PAD = 2;

export function DeliverySparkline({
  label,
  values,
  binSeconds,
  className,
  format = (mean) => `${Math.round(mean * 100)}% avg`,
}: DeliverySparklineProps) {
  const measured = values.filter((value): value is number => value !== null);
  if (measured.length < 2) return null;

  const mean = measured.reduce((sum, value) => sum + value, 0) / measured.length;
  const stepX = values.length > 1 ? (WIDTH - PAD * 2) / (values.length - 1) : 0;
  const toY = (value: number) => PAD + (1 - Math.max(0, Math.min(1, value))) * (HEIGHT - PAD * 2);

  // Split into runs of consecutive measured bins — see the note above on gaps.
  const runs: string[] = [];
  let current: string[] = [];
  values.forEach((value, index) => {
    if (value === null) {
      if (current.length > 1) runs.push(current.join(" "));
      current = [];
      return;
    }
    current.push(`${current.length === 0 ? "M" : "L"}${(PAD + index * stepX).toFixed(1)},${toY(value).toFixed(1)}`);
  });
  if (current.length > 1) runs.push(current.join(" "));

  const gapCount = values.filter((value) => value === null).length;
  const durationLabel = formatDuration(values.length * binSeconds);

  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-baseline justify-between text-xs">
        <span className="font-medium text-foreground">{label}</span>
        <span className="text-muted-foreground">{format(mean)}</span>
      </div>
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        className="h-10 w-full"
        preserveAspectRatio="none"
        role="img"
        aria-label={`${label} over ${durationLabel}, averaging ${format(mean)}${
          gapCount ? `, with ${gapCount} unmeasured intervals` : ""
        }`}
      >
        {runs.map((path, index) => (
          <path
            key={index}
            d={path}
            fill="none"
            strokeWidth={1.5}
            strokeLinejoin="round"
            strokeLinecap="round"
            className={cn("stroke-primary", className)}
            vectorEffect="non-scaling-stroke"
          />
        ))}
      </svg>
      <div className="flex justify-between text-[10px] text-muted-foreground">
        <span>0:00</span>
        {gapCount > 0 ? <span>gaps = not measured</span> : null}
        <span>{durationLabel}</span>
      </div>
    </div>
  );
}

function formatDuration(seconds: number): string {
  const whole = Math.round(seconds);
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}
