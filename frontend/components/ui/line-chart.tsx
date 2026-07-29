"use client";

import * as React from "react";
import { cn } from "@/lib/utils";

export interface LineChartPoint {
  date: string; // YYYY-MM-DD
  value: number;
}

interface LineChartProps {
  points: LineChartPoint[];
  /** Sentence-case, used for the aria-label and the "View as table" caption. */
  label: string;
  unit?: string; // e.g. "%" — appended to the value in labels/tooltip
  formatValue?: (value: number) => string;
  /** Shades an inclusive date range — the anomalous window a deep-linked alert points at. */
  highlightRange?: { from: string; to: string } | null;
  className?: string;
}

const WIDTH = 640;
const HEIGHT = 200;
const PADDING = { top: 16, right: 16, bottom: 24, left: 44 };

function defaultFormat(value: number, unit?: string): string {
  const rounded = Number.isInteger(value) ? value : Math.round(value * 100) / 100;
  return unit ? `${rounded}${unit}` : `${rounded}`;
}

function niceTicks(min: number, max: number, count = 4): number[] {
  if (min === max) return [min];
  const step = (max - min) / (count - 1);
  return Array.from({ length: count }, (_, i) => Math.round((min + step * i) * 100) / 100);
}

/**
 * Small-multiple time-series line — one metric, one hue (--primary), so no
 * legend is needed (single-series exemption). 2px line / round caps, an
 * end-dot direct label, hairline horizontal gridlines, a hover crosshair +
 * tooltip, and an optional shaded band for the alert window a deep-link
 * points at. A "View as table" toggle keeps the same data reachable without
 * color (accessibility non-negotiable: a table view always exists).
 */
export function LineChart({ points, label, unit, formatValue, highlightRange, className }: LineChartProps) {
  const [hoverIndex, setHoverIndex] = React.useState<number | null>(null);
  const [showTable, setShowTable] = React.useState(false);
  const svgRef = React.useRef<SVGSVGElement>(null);
  const fmt = formatValue ?? ((v: number) => defaultFormat(v, unit));

  const hasData = points.length > 0;
  const values = points.map((p) => p.value);
  const minValue = hasData ? Math.min(0, ...values) : 0;
  const maxValue = hasData ? Math.max(...values, minValue + 1) : 1;

  const innerWidth = WIDTH - PADDING.left - PADDING.right;
  const innerHeight = HEIGHT - PADDING.top - PADDING.bottom;

  const xFor = (i: number) => PADDING.left + (points.length <= 1 ? innerWidth / 2 : (i / (points.length - 1)) * innerWidth);
  const yFor = (v: number) => PADDING.top + innerHeight - ((v - minValue) / (maxValue - minValue || 1)) * innerHeight;

  const linePath = points.map((p, i) => `${i === 0 ? "M" : "L"} ${xFor(i).toFixed(2)} ${yFor(p.value).toFixed(2)}`).join(" ");
  const yTicks = niceTicks(minValue, maxValue);

  const highlightX = React.useMemo(() => {
    if (!highlightRange || !hasData) return null;
    const startIdx = points.findIndex((p) => p.date >= highlightRange.from);
    const endIdx = [...points].reverse().findIndex((p) => p.date <= highlightRange.to);
    if (startIdx === -1) return null;
    const endIndexFromEnd = endIdx === -1 ? points.length - 1 : points.length - 1 - endIdx;
    return { x1: xFor(startIdx), x2: xFor(Math.max(startIdx, endIndexFromEnd)) };
  }, [highlightRange, points, hasData]); // eslint-disable-line react-hooks/exhaustive-deps

  function handleMove(e: React.MouseEvent<SVGSVGElement>) {
    if (!hasData || !svgRef.current) return;
    const rect = svgRef.current.getBoundingClientRect();
    const px = ((e.clientX - rect.left) / rect.width) * WIDTH;
    let nearest = 0;
    let nearestDist = Infinity;
    points.forEach((_, i) => {
      const dist = Math.abs(xFor(i) - px);
      if (dist < nearestDist) {
        nearestDist = dist;
        nearest = i;
      }
    });
    setHoverIndex(nearest);
  }

  const latest = hasData ? points[points.length - 1] : null;
  const hovered = hoverIndex !== null ? points[hoverIndex] : null;

  return (
    <div className={cn("flex flex-col gap-2", className)}>
      <div className="relative">
        <svg
          ref={svgRef}
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          className="w-full"
          role="img"
          aria-label={`${label} over time, latest value ${latest ? fmt(latest.value) : "no data"}`}
          onMouseMove={handleMove}
          onMouseLeave={() => setHoverIndex(null)}
        >
          {/* gridlines — hairline, recessive */}
          {yTicks.map((t) => (
            <g key={t}>
              <line
                x1={PADDING.left}
                x2={WIDTH - PADDING.right}
                y1={yFor(t)}
                y2={yFor(t)}
                stroke="hsl(var(--border))"
                strokeWidth={1}
              />
              <text x={PADDING.left - 8} y={yFor(t)} textAnchor="end" dominantBaseline="middle" className="fill-muted-foreground text-[10px]">
                {fmt(t)}
              </text>
            </g>
          ))}

          {/* alert window band — status wash, never the only cue (also shown via the "Anomalous window" badge) */}
          {highlightX ? (
            <rect
              x={highlightX.x1}
              y={PADDING.top}
              width={Math.max(2, highlightX.x2 - highlightX.x1)}
              height={innerHeight}
              fill="hsl(var(--danger) / 0.1)"
            />
          ) : null}

          {hasData ? (
            <path d={linePath} fill="none" stroke="hsl(var(--primary))" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
          ) : null}

          {/* end-dot direct label — sparing: only the endpoint is labeled */}
          {latest ? (
            <>
              <circle cx={xFor(points.length - 1)} cy={yFor(latest.value)} r={4} fill="hsl(var(--primary))" stroke="hsl(var(--surface))" strokeWidth={2} />
              <text x={xFor(points.length - 1)} y={yFor(latest.value) - 10} textAnchor="end" className="fill-foreground text-[11px] font-medium">
                {fmt(latest.value)}
              </text>
            </>
          ) : (
            <text x={WIDTH / 2} y={HEIGHT / 2} textAnchor="middle" className="fill-muted-foreground text-xs">
              No data for this range
            </text>
          )}

          {/* hover crosshair */}
          {hovered ? (
            <line x1={xFor(hoverIndex!)} x2={xFor(hoverIndex!)} y1={PADDING.top} y2={HEIGHT - PADDING.bottom} stroke="hsl(var(--muted-foreground))" strokeWidth={1} strokeDasharray="2 2" />
          ) : null}
          {hovered ? <circle cx={xFor(hoverIndex!)} cy={yFor(hovered.value)} r={4} fill="hsl(var(--primary))" stroke="hsl(var(--surface))" strokeWidth={2} /> : null}
        </svg>

        {hovered ? (
          <div
            className="pointer-events-none absolute top-0 z-10 -translate-x-1/2 rounded-lg border border-border bg-surface-elevated px-2.5 py-1.5 text-xs shadow-md"
            style={{ left: `${(xFor(hoverIndex!) / WIDTH) * 100}%` }}
          >
            <div className="font-medium text-foreground">{fmt(hovered.value)}</div>
            <div className="text-muted-foreground">{hovered.date}</div>
          </div>
        ) : null}
      </div>

      <button
        type="button"
        onClick={() => setShowTable((v) => !v)}
        className="self-start text-xs font-medium text-primary hover:underline"
      >
        {showTable ? "Hide table" : "View as table"}
      </button>

      {showTable ? (
        <div className="max-h-40 overflow-y-auto rounded-lg border border-border">
          <table className="w-full text-left text-xs">
            <thead className="sticky top-0 bg-surface text-muted-foreground">
              <tr>
                <th className="px-3 py-1.5">Date</th>
                <th className="px-3 py-1.5">{label}</th>
              </tr>
            </thead>
            <tbody>
              {points.map((p) => (
                <tr key={p.date} className="border-t border-border">
                  <td className="px-3 py-1 tabular-nums text-muted-foreground">{p.date}</td>
                  <td className="px-3 py-1 tabular-nums text-foreground">{fmt(p.value)}</td>
                </tr>
              ))}
              {!hasData ? (
                <tr>
                  <td colSpan={2} className="px-3 py-2 text-center text-muted-foreground">No data</td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}
