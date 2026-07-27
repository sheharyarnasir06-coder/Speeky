"use client";

import * as React from "react";
import { AlertTriangle, CheckCircle2, Mic, Settings, Volume2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import {
  getMicrophonePermissionState,
  requestAndTestMicrophoneInput,
  type MicrophoneCheckFailureReason,
  type MicrophonePermissionState,
} from "@/lib/microphoneCheck";

interface MicrophoneCheckModalProps {
  open: boolean;
  onClose: () => void;
  onPassed: () => void;
  featureName?: string;
}

const FAILURE_COPY: Record<MicrophoneCheckFailureReason, { title: string; detail: string }> = {
  unsupported: {
    title: "This browser or device is not supported.",
    detail: "Use the latest version of Chrome, Edge, Safari, or Firefox with a working microphone.",
  },
  permission_denied: {
    title: "Microphone access is blocked.",
    detail: "Open your browser site settings, allow microphone access for Speeky, then retry the check.",
  },
  no_audio: {
    title: "We can't hear you.",
    detail: "Check your microphone, headset mute switch, and system input device, then say a word again.",
  },
  unknown: {
    title: "The microphone check could not finish.",
    detail: "Refresh the page and try again. If it keeps happening, use a supported browser.",
  },
};

export function MicrophoneCheckModal({
  open,
  onClose,
  onPassed,
  featureName = "voice practice",
}: MicrophoneCheckModalProps) {
  const [permissionState, setPermissionState] = React.useState<MicrophonePermissionState>("unknown");
  const [isChecking, setIsChecking] = React.useState(false);
  const [hasPassed, setHasPassed] = React.useState(false);
  const [failureReason, setFailureReason] = React.useState<MicrophoneCheckFailureReason | null>(null);

  React.useEffect(() => {
    if (!open) return;

    setHasPassed(false);
    setFailureReason(null);
    getMicrophonePermissionState().then(setPermissionState);
  }, [open]);

  async function handleRunCheck() {
    setIsChecking(true);
    setFailureReason(null);

    const result = await requestAndTestMicrophoneInput();
    const nextPermissionState = await getMicrophonePermissionState();
    setPermissionState(nextPermissionState);

    if (result.ok) {
      setHasPassed(true);
    } else {
      setFailureReason(result.reason ?? "unknown");
    }

    setIsChecking(false);
  }

  const failure = failureReason ? FAILURE_COPY[failureReason] : null;
  const primaryLabel =
    permissionState === "granted" ? "Test Microphone" : "Allow Microphone";

  return (
    <Modal
      open={open}
      onClose={isChecking ? () => {} : onClose}
      title="Microphone Check"
      description={`Speeky needs a live microphone before starting ${featureName}.`}
    >
      <div className="flex flex-col gap-5">
        <div className="rounded-xl border border-border bg-surface p-4">
          <div className="flex items-start gap-3">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-secondary text-primary">
              <Mic className="h-4 w-4" aria-hidden="true" />
            </span>
            <div>
              <p className="text-sm font-medium text-foreground">Say one short word when prompted.</p>
              <p className="mt-1 text-sm text-muted-foreground">
                This quick test confirms your browser can capture audio before any voice session begins.
              </p>
            </div>
          </div>
        </div>

        {isChecking ? (
          <div className="flex items-center gap-3 rounded-xl border border-primary/30 bg-secondary px-4 py-3 text-sm text-foreground">
            <Volume2 className="h-4 w-4 text-primary" aria-hidden="true" />
            Listening now. Say a word like "hello".
          </div>
        ) : null}

        {hasPassed ? (
          <div className="flex items-start gap-3 rounded-xl border border-success/30 bg-success/10 px-4 py-3 text-sm text-foreground">
            <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" aria-hidden="true" />
            Your microphone is working. You can continue to {featureName}.
          </div>
        ) : null}

        {failure ? (
          <div className="flex items-start gap-3 rounded-xl border border-warning/30 bg-warning/10 px-4 py-3 text-sm text-foreground">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" aria-hidden="true" />
            <div>
              <p className="font-medium">{failure.title}</p>
              <p className="mt-1 text-muted-foreground">{failure.detail}</p>
              {failureReason === "permission_denied" ? (
                <div className="mt-3 flex items-start gap-2 text-xs text-muted-foreground">
                  <Settings className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                  In Chrome or Edge, click the lock icon beside the address bar, set Microphone to Allow, then reload.
                </div>
              ) : null}
            </div>
          </div>
        ) : null}

        <div className="flex flex-wrap gap-3">
          {hasPassed ? (
            <Button type="button" onClick={onPassed}>
              Continue
            </Button>
          ) : (
            <Button type="button" loading={isChecking} onClick={handleRunCheck}>
              {primaryLabel}
            </Button>
          )}
          <Button type="button" variant="outline" disabled={isChecking} onClick={handleRunCheck}>
            Retry
          </Button>
          <Button href="/dashboard/explore" variant="ghost">
            Use Non-Voice Modules
          </Button>
        </div>
      </div>
    </Modal>
  );
}
