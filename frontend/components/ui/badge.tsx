import * as React from "react";
import { cn } from "@/lib/utils";

type BadgeTone =
  | "neutral"
  | "brand"
  | "accent"
  | "success"
  | "warning"
  | "danger";
type BadgeSize = "sm" | "md";

interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  tone?: BadgeTone;
  size?: BadgeSize;
  /** Small leading dot — useful for live/status badges. */
  dot?: boolean;
}

/**
 * Status/label chip. Tones map to semantic meaning, never to a raw colour, so a
 * "degraded" score and a "failed" check look the same everywhere in the product.
 *
 * All tones use a tinted background with a same-hue foreground rather than a solid
 * fill, which keeps text contrast comfortably above 4.5:1 in both themes.
 */
const toneClasses: Record<BadgeTone, string> = {
  neutral: "bg-muted text-muted-foreground",
  brand: "bg-primary/10 text-primary",
  accent: "bg-accent/10 text-accent",
  success: "bg-success/10 text-success",
  warning: "bg-warning/10 text-warning",
  danger: "bg-danger/10 text-danger",
};

const dotClasses: Record<BadgeTone, string> = {
  neutral: "bg-muted-foreground",
  brand: "bg-primary",
  accent: "bg-accent",
  success: "bg-success",
  warning: "bg-warning",
  danger: "bg-danger",
};

const sizeClasses: Record<BadgeSize, string> = {
  sm: "px-2 py-0.5 text-[0.6875rem] gap-1",
  md: "px-2.5 py-1 text-xs gap-1.5",
};

export function Badge({
  tone = "neutral",
  size = "sm",
  dot = false,
  className,
  children,
  ...props
}: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center rounded-full font-medium leading-none",
        toneClasses[tone],
        sizeClasses[size],
        className,
      )}
      {...props}
    >
      {dot ? (
        <span
          className={cn("h-1.5 w-1.5 rounded-full", dotClasses[tone])}
          aria-hidden="true"
        />
      ) : null}
      {children}
    </span>
  );
}
