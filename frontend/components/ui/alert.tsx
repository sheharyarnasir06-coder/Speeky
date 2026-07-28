import * as React from "react";
import { AlertTriangle, CheckCircle2, Info, Lock, XCircle } from "lucide-react";
import { cn } from "@/lib/utils";

type AlertTone = "info" | "success" | "warning" | "danger" | "locked";

interface AlertProps extends React.HTMLAttributes<HTMLDivElement> {
  tone?: AlertTone;
  title?: string;
  icon?: React.ComponentType<{ className?: string }>;
}

/**
 * Inline status message — the error / success / locked / info banners that were
 * previously re-written by hand on nearly every page, each with slightly different
 * padding, border opacity and icon size.
 *
 * Accessibility: danger and warning render as role="alert" (assertive) so a screen
 * reader announces a failure immediately; informational tones use role="status"
 * (polite) so they don't interrupt what the user is doing.
 */
const toneConfig: Record<
  AlertTone,
  { wrap: string; icon: string; Icon: React.ComponentType<{ className?: string }> }
> = {
  info: {
    wrap: "border-border bg-surface",
    icon: "text-muted-foreground",
    Icon: Info,
  },
  success: {
    wrap: "border-success/30 bg-success/5",
    icon: "text-success",
    Icon: CheckCircle2,
  },
  warning: {
    wrap: "border-warning/30 bg-warning/10",
    icon: "text-warning",
    Icon: AlertTriangle,
  },
  danger: {
    wrap: "border-danger/30 bg-danger/5",
    icon: "text-danger",
    Icon: XCircle,
  },
  locked: {
    wrap: "border-warning/30 bg-warning/10",
    icon: "text-warning",
    Icon: Lock,
  },
};

export function Alert({
  tone = "info",
  title,
  icon,
  className,
  children,
  ...props
}: AlertProps) {
  const config = toneConfig[tone];
  const Icon = icon ?? config.Icon;
  const assertive = tone === "danger" || tone === "warning";

  return (
    <div
      role={assertive ? "alert" : "status"}
      aria-live={assertive ? "assertive" : "polite"}
      className={cn(
        "flex items-start gap-2.5 rounded-xl border px-4 py-3 text-sm text-foreground",
        config.wrap,
        className,
      )}
      {...props}
    >
      <Icon className={cn("mt-0.5 h-4 w-4 shrink-0", config.icon)} aria-hidden="true" />
      <div className="flex min-w-0 flex-col gap-1">
        {title ? <p className="font-medium leading-tight">{title}</p> : null}
        <div className="min-w-0 [&_p]:leading-relaxed">{children}</div>
      </div>
    </div>
  );
}
