"use client";

import * as React from "react";
import { MicrophoneCheckModal } from "@/components/dashboard/progress/MicrophoneCheckModal";
import { hasRecentWorkingMicCheck, markVoiceReady } from "@/lib/voiceReadiness";

interface VoiceReadinessGateOptions {
  featureName: string;
}

export function useVoiceReadinessGate({ featureName }: VoiceReadinessGateOptions) {
  const [open, setOpen] = React.useState(false);
  const pendingActionRef = React.useRef<(() => void | Promise<void>) | null>(null);

  const runWithVoiceReadiness = React.useCallback(
    async (action: () => void | Promise<void>) => {
      if (await hasRecentWorkingMicCheck()) {
        await action();
        return;
      }

      pendingActionRef.current = action;
      setOpen(true);
    },
    [],
  );

  const handlePassed = React.useCallback(async () => {
    markVoiceReady();
    setOpen(false);

    const pendingAction = pendingActionRef.current;
    pendingActionRef.current = null;

    if (pendingAction) {
      await pendingAction();
    }
  }, []);

  const gate = (
    <MicrophoneCheckModal
      open={open}
      featureName={featureName}
      onClose={() => {
        pendingActionRef.current = null;
        setOpen(false);
      }}
      onPassed={handlePassed}
    />
  );

  return { gate, runWithVoiceReadiness };
}
