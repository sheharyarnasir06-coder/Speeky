import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * Content-shaped loading placeholder.
 *
 * Replaces the bare "Loading your progress…" text that several panels showed: a
 * skeleton preserves the final layout, so the page doesn't jump when data lands
 * (avoiding layout shift) and the wait feels shorter because the shape is already
 * legible.
 *
 * The shimmer is a transform-only animation on a child overlay — it never animates
 * layout properties, so it stays off the main thread's layout path, and it is
 * suppressed automatically under prefers-reduced-motion by the global guard.
 */
export function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("relative overflow-hidden rounded-lg bg-muted", className)}
      aria-hidden="true"
      {...props}
    >
      <div className="absolute inset-0 -translate-x-full animate-shimmer bg-gradient-to-r from-transparent via-foreground/[0.06] to-transparent motion-reduce:animate-none" />
    </div>
  );
}

/** Multi-line text placeholder. Last line is shortened so it reads as prose. */
export function SkeletonText({
  lines = 3,
  className,
}: {
  lines?: number;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col gap-2", className)}>
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton
          key={i}
          className={cn("h-3.5", i === lines - 1 && lines > 1 ? "w-2/3" : "w-full")}
        />
      ))}
    </div>
  );
}

/** Placeholder matching the Card + stat-tile layout used across the dashboards. */
export function SkeletonCard({ className }: { className?: string }) {
  return (
    <div
      className={cn("rounded-2xl border border-border bg-surface-elevated p-6", className)}
      role="status"
      aria-busy="true"
      aria-live="polite"
    >
      <span className="sr-only">Loading…</span>
      <Skeleton className="h-4 w-32" />
      <div className="mt-6 grid grid-cols-2 gap-4 sm:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="flex flex-col gap-2 rounded-xl border border-border bg-surface p-4">
            <Skeleton className="h-3 w-16" />
            <Skeleton className="h-7 w-20" />
          </div>
        ))}
      </div>
    </div>
  );
}
