"use client";

/**
 * Camera counterpart to VoiceReadinessGate.
 *
 * Composes with it rather than replacing it. On the public-speaking page the call site is:
 *
 *     runWithVoiceReadiness(() => runWithCameraReadiness(startSession))
 *
 * Voice first because it is the required modality; camera second because it is an opt-in
 * add-on. Callers must only invoke the camera gate when the user actually enabled the camera —
 * prompting for a webcam during a voice-only session would be an unpleasant surprise.
 *
 * Unlike the voice gate, this one also surfaces the fitted calibration, since the gate is where
 * calibration is produced and the session hook needs it.
 */

import * as React from "react";

import { CameraCheckModal } from "@/components/dashboard/progress/CameraCheckModal";
import {
  hasRecentWorkingCameraCheck,
  loadCalibration,
  markCameraReady,
} from "@/lib/cameraReadiness";
import type { GazeCalibration } from "@/lib/vision/gaze";

interface CameraReadinessGateOptions {
  featureName: string;
}

export function useCameraReadinessGate({ featureName }: CameraReadinessGateOptions) {
  const [open, setOpen] = React.useState(false);
  const [calibration, setCalibration] = React.useState<GazeCalibration | null>(() =>
    typeof window === "undefined" ? null : loadCalibration(),
  );
  const pendingActionRef = React.useRef<(() => void | Promise<void>) | null>(null);

  const runWithCameraReadiness = React.useCallback(
    async (action: () => void | Promise<void>) => {
      if (await hasRecentWorkingCameraCheck()) {
        // Refresh from storage: a calibration fitted in another tab is still valid here.
        setCalibration(loadCalibration());
        await action();
        return;
      }

      pendingActionRef.current = action;
      setOpen(true);
    },
    [],
  );

  const handlePassed = React.useCallback(async () => {
    markCameraReady();
    setCalibration(loadCalibration());
    setOpen(false);

    const pendingAction = pendingActionRef.current;
    pendingActionRef.current = null;

    if (pendingAction) await pendingAction();
  }, []);

  const gate = (
    <CameraCheckModal
      open={open}
      featureName={featureName}
      onClose={() => {
        pendingActionRef.current = null;
        setOpen(false);
      }}
      onPassed={handlePassed}
    />
  );

  return { gate, runWithCameraReadiness, calibration };
}
