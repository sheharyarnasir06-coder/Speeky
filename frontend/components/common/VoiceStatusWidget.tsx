"use client";

import * as React from "react";
import { Mic } from "lucide-react";
import { MicrophoneCheckModal } from "@/components/dashboard/progress/MicrophoneCheckModal";
import { cn } from "@/lib/utils";
import {
  getVoiceReadinessEventName,
  getVoiceReadinessStatus,
  markVoiceReady,
  type VoiceReadinessStatus,
} from "@/lib/voiceReadiness";

const STATUS_COPY: Record<
  VoiceReadinessStatus,
  { label: string; detail: string; dotClass: string }
> = {
  ready: {
    label: "Mic ready",
    detail: "Voice checked",
    dotClass: "bg-success voice-status-dot-ready",
  },
  needs_check: {
    label: "Check mic",
    detail: "Voice not checked",
    dotClass: "bg-warning",
  },
  permission_denied: {
    label: "Mic blocked",
    detail: "Allow access",
    dotClass: "bg-danger",
  },
  unsupported: {
    label: "No mic",
    detail: "Unsupported",
    dotClass: "bg-muted-foreground",
  },
};

export function VoiceStatusWidget() {
  const [status, setStatus] = React.useState<VoiceReadinessStatus>("needs_check");
  const [open, setOpen] = React.useState(false);

  const refreshStatus = React.useCallback(() => {
    getVoiceReadinessStatus().then(setStatus);
  }, []);

  React.useEffect(() => {
    refreshStatus();

    const eventName = getVoiceReadinessEventName();
    const handleVisibilityChange = () => {
      if (document.visibilityState === "visible") refreshStatus();
    };

    window.addEventListener("focus", refreshStatus);
    window.addEventListener(eventName, refreshStatus);
    document.addEventListener("visibilitychange", handleVisibilityChange);
    const interval = window.setInterval(refreshStatus, 30_000);

    return () => {
      window.removeEventListener("focus", refreshStatus);
      window.removeEventListener(eventName, refreshStatus);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      window.clearInterval(interval);
    };
  }, [refreshStatus]);

  const copy = STATUS_COPY[status];

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="group flex h-10 min-w-[11.25rem] items-center gap-2 rounded-xl border border-border bg-surface px-2 text-left text-muted-foreground transition-colors duration-200 hover:bg-surface-elevated hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40 max-sm:min-w-0 max-sm:px-1"
        aria-label={`${copy.label}: ${copy.detail}`}
      >
        <span className="relative flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-transparent text-muted-foreground transition-colors group-hover:text-foreground">
          <Mic className="h-4 w-4" aria-hidden="true" />
          <span
            className={cn(
              "absolute -right-0.5 -top-0.5 h-2.5 w-2.5 rounded-full ring-2 ring-surface-elevated",
              copy.dotClass,
            )}
            aria-hidden="true"
          />
        </span>
        <span className="min-w-0 max-sm:hidden">
          <span className="block truncate text-sm font-semibold leading-4 text-foreground">
            {copy.label}
          </span>
          <span className="block truncate text-xs leading-4 text-muted-foreground">
            {copy.detail}
          </span>
        </span>
      </button>

      <MicrophoneCheckModal
        open={open}
        featureName="voice practice"
        onClose={() => setOpen(false)}
        onPassed={() => {
          markVoiceReady();
          setOpen(false);
          refreshStatus();
        }}
      />
    </>
  );
}
