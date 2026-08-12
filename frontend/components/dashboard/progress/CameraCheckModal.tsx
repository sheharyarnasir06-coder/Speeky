"use client";

/**
 * Three-step camera check: permission/device, framing, calibration.
 *
 * Mirrors MicrophoneCheckModal's state machine and copy conventions, but with a step machine on
 * top because the camera needs three things confirmed rather than one.
 *
 * The calibration step is the reason this modal exists at all. A webcam sits above the screen,
 * so "looking at the camera" and "looking at the content" are different head positions, and how
 * different depends on the user's monitor, their distance, and where their camera is mounted.
 * Measuring both is the only way `on_camera_pct` means anything. Skipping is allowed — the
 * session then runs on a weaker session-baseline fallback and is discounted downstream — but it
 * is not the default, because a skipped calibration produces numbers users will not trust.
 */

import * as React from "react";
import { AlertTriangle, CheckCircle2, Camera, Settings, Video } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import { cn } from "@/lib/utils";
import { saveCalibration } from "@/lib/cameraReadiness";
import { useCameraCheck, type CameraCheckFailureReason } from "@/lib/vision/useCameraCheck";
import type { FramingState } from "@/lib/vision/types";

interface CameraCheckModalProps {
  open: boolean;
  onClose: () => void;
  onPassed: () => void;
  featureName?: string;
}

type Step = "device" | "framing" | "calibrate" | "done";

const FAILURE_COPY: Record<CameraCheckFailureReason, { title: string; detail: string }> = {
  unsupported: {
    title: "This browser can't run delivery analysis.",
    detail:
      "It lacks WebAssembly SIMD. Use the latest Chrome, Edge, or Safari — or continue with voice only.",
  },
  permission_denied: {
    title: "Camera access is blocked.",
    detail:
      "Open your browser site settings, allow camera access for Speeky, then retry the check.",
  },
  no_camera: {
    title: "No camera was found.",
    detail: "Connect a webcam and retry, or continue with voice only.",
  },
  camera_busy: {
    title: "Your camera is in use by another app.",
    detail: "Close any video call or recording app that might be holding it, then retry.",
  },
  assets_missing: {
    title: "The analysis models aren't available.",
    detail:
      "This is a server-side setup problem, not something you can fix. Continue with voice only.",
  },
  too_dark: {
    title: "The room is too dark to analyse.",
    detail: "Add a light source in front of you — ideally behind your screen — then retry.",
  },
  unknown: {
    title: "The camera check could not finish.",
    detail: "Refresh the page and try again. If it keeps happening, continue with voice only.",
  },
};

const FRAMING_COPY: Record<FramingState, string> = {
  good: "Framing looks good — hold still.",
  too_far: "Move a little closer to the camera.",
  too_close: "Move back slightly so your shoulders are in frame.",
  off_center: "Shift so you're centred in the frame.",
  shoulders_cropped: "Tilt your screen back so your shoulders are visible.",
  unknown: "Position yourself in front of the camera.",
};

export function CameraCheckModal({
  open,
  onClose,
  onPassed,
  featureName = "delivery analysis",
}: CameraCheckModalProps) {
  const check = useCameraCheck();
  const [step, setStep] = React.useState<Step>("device");
  const [holdTarget, setHoldTarget] = React.useState<null | "camera" | "screen">(null);
  const [calibrationWarning, setCalibrationWarning] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (open) {
      setStep("device");
      setHoldTarget(null);
      setCalibrationWarning(null);
      check.reset();
    } else {
      check.stop();
    }
    // `check` is a stable bag of callbacks; re-running this on its identity would restart the
    // camera on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const isBusy = check.isPreparing || holdTarget !== null;

  async function handleStartDevice() {
    await check.start();
    setStep((current) => (current === "device" ? "framing" : current));
  }

  async function runHold(target: "camera" | "screen") {
    setHoldTarget(target);
    const captured = await check.captureHold(target);
    setHoldTarget(null);
    return captured;
  }

  /** Below this a hold clearly failed to see the face — distinct from a merely unsteady one. */
  const MIN_USABLE_SAMPLES = 5;

  /**
   * Run both holds once. Returns null when the attempt is not usable.
   *
   * Split out from handleCalibrate so a failure can be retried transparently rather than
   * bounced back to the user as a warning plus a button press.
   */
  async function attemptCalibration() {
    const atCamera = await runHold("camera");
    if (atCamera < MIN_USABLE_SAMPLES) return null;

    await runHold("screen");

    const calibration = check.fitCalibration();
    if (!calibration || calibration.quality === "failed") return null;
    return calibration;
  }

  async function handleCalibrate() {
    setCalibrationWarning(null);

    // Retry once, silently. A first attempt can fail for entirely transient reasons — the user
    // blinked through the hold, glanced away, or the tab lost a second of frames — and making
    // them read a warning and press a button for that is the complaint this flow generated.
    // Only a second consecutive failure is worth telling them about.
    let calibration = await attemptCalibration();
    if (!calibration) calibration = await attemptCalibration();

    if (!calibration) {
      setCalibrationWarning(
        "We couldn't get a clear read on your eyes. More light on your face usually fixes it — " +
          "or skip for now and we'll record your body language without scoring it.",
      );
      return;
    }

    const { width, height } = check.captureDimensions();
    saveCalibration(calibration, width, height);

    // "weak" is a usable calibration with a wider tolerance cone, not a problem to report — the
    // reduced confidence_weight already flows through to how prominently the numbers are shown.
    setStep("done");
  }

  /**
   * Skipping proceeds without a calibration.
   *
   * Be clear about what that costs: with no calibration the payload reports `method: "none"`,
   * the backend scores it at a confidence too low to display, and the results tile shows the
   * "captured but not scored" card instead of numbers. That is the honest outcome — an
   * uncalibrated eye-contact percentage is off by an unmodelled camera offset — so the copy
   * below says so rather than implying degraded-but-useful scoring.
   *
   * No calibration is saved, so `hasRecentWorkingCameraCheck()` stays false and the user is
   * offered the check again next session. Deliberate: skipping is a "not now", not a "never".
   */
  function handleSkipCalibration() {
    setStep("done");
  }

  const failure = check.failureReason ? FAILURE_COPY[check.failureReason] : null;
  // Must mount before check.start() calls getUserMedia — start() reads videoRef.current right
  // after the camera opens, and a null ref there throws, tearing the just-opened stream back
  // down (camera light on, then immediately off).
  const showPreview = step !== "device" || check.isStreaming || check.isPreparing;

  return (
    <Modal
      open={open}
      onClose={isBusy ? () => {} : onClose}
      title="Camera Check"
      description={`Speeky needs a quick camera setup before starting ${featureName}.`}
    >
      <div className="flex flex-col gap-5">
        <StepIndicator step={step} />

        {showPreview ? (
          <div className="relative self-center overflow-hidden rounded-xl border border-border bg-black">
            {/* Mirrored for comfort. The frames fed to MediaPipe are NOT mirrored — see
                normalize.ts on why left/right must be swapped before it reaches coaching copy. */}
            <video
              ref={check.videoRef}
              muted
              playsInline
              className="h-[200px] w-[266px] -scale-x-100 object-cover"
            />
            {holdTarget ? (
              <HoldOverlay target={holdTarget} countdown={check.countdown} />
            ) : null}
          </div>
        ) : null}

        {step === "device" ? (
          <InfoCard
            icon={<Camera className="h-4 w-4" aria-hidden="true" />}
            title="We'll check your camera, framing, and where you're looking."
            body="Everything runs on your device. No video, images, or frame data are ever uploaded or stored — only a summary of your delivery."
          />
        ) : null}

        {step === "framing" ? (
          <div
            className={cn(
              "rounded-xl border px-4 py-3 text-sm",
              check.framing === "good"
                ? "border-success/30 bg-success/10 text-foreground"
                : "border-border bg-surface text-foreground",
            )}
          >
            <p className="font-medium">{FRAMING_COPY[check.framing]}</p>
            <p className="mt-1 text-muted-foreground">
              Aim for head and shoulders in frame, roughly centred.
            </p>
            {check.brightnessOk === false ? (
              <p className="mt-2 text-warning">
                It's quite dark — add a light in front of you for better accuracy.
              </p>
            ) : null}
          </div>
        ) : null}

        {step === "calibrate" ? (
          <InfoCard
            icon={<Video className="h-4 w-4" aria-hidden="true" />}
            title="Two quick looks, three seconds each."
            body="Your camera sits above your screen, so looking at the lens and looking at the app are different positions. Measuring both is what makes the eye-contact score meaningful — without it we'll record your body language but won't score it."
          />
        ) : null}

        {calibrationWarning ? (
          <div className="flex items-start gap-3 rounded-xl border border-warning/30 bg-warning/10 px-4 py-3 text-sm text-foreground">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" aria-hidden="true" />
            {calibrationWarning}
          </div>
        ) : null}

        {step === "done" ? (
          <div className="flex items-start gap-3 rounded-xl border border-success/30 bg-success/10 px-4 py-3 text-sm text-foreground">
            <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" aria-hidden="true" />
            Camera is ready. You can continue to {featureName}.
          </div>
        ) : null}

        {failure ? (
          <div className="flex items-start gap-3 rounded-xl border border-warning/30 bg-warning/10 px-4 py-3 text-sm text-foreground">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" aria-hidden="true" />
            <div>
              <p className="font-medium">{failure.title}</p>
              <p className="mt-1 text-muted-foreground">{failure.detail}</p>
              {check.failureReason === "permission_denied" ? (
                <div className="mt-3 flex items-start gap-2 text-xs text-muted-foreground">
                  <Settings className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                  In Chrome or Edge, click the lock icon beside the address bar, set Camera to
                  Allow, then reload.
                </div>
              ) : null}
            </div>
          </div>
        ) : null}

        <div className="flex flex-wrap gap-3">
          {step === "device" ? (
            <Button
              type="button"
              loading={check.isPreparing}
              onClick={handleStartDevice}
            >
              {check.loadProgress !== null
                ? `Preparing... ${Math.round(check.loadProgress * 100)}%`
                : "Allow Camera"}
            </Button>
          ) : null}

          {step === "framing" ? (
            <>
              <Button
                type="button"
                disabled={!check.framingSettled}
                onClick={() => setStep("calibrate")}
              >
                {check.framingSettled ? "Looks Good" : "Waiting for framing..."}
              </Button>
              {/* Escape hatch: an unusual setup shouldn't be a dead end. The payload records
                  framing_override so the backend knows the check was bypassed. */}
              <Button type="button" variant="outline" onClick={() => setStep("calibrate")}>
                Continue Anyway
              </Button>
            </>
          ) : null}

          {step === "calibrate" ? (
            <>
              <Button type="button" loading={holdTarget !== null} onClick={handleCalibrate}>
                {check.countdown !== null
                  ? `Get ready... ${check.countdown}`
                  : holdTarget
                    ? "Hold still..."
                    : "Start Calibration"}
              </Button>
              <Button
                type="button"
                variant="outline"
                disabled={holdTarget !== null}
                onClick={handleSkipCalibration}
                title="We'll record your body language but won't score it"
              >
                Skip for now
              </Button>
            </>
          ) : null}

          {step === "done" ? (
            <Button
              type="button"
              onClick={() => {
                check.stop();
                onPassed();
              }}
            >
              Continue
            </Button>
          ) : null}

          {step !== "done" ? (
            <Button type="button" variant="ghost" disabled={isBusy} onClick={onClose}>
              Use Voice Only
            </Button>
          ) : null}
        </div>
      </div>
    </Modal>
  );
}

function StepIndicator({ step }: { step: Step }) {
  const steps: { key: Step; label: string }[] = [
    { key: "device", label: "Camera" },
    { key: "framing", label: "Framing" },
    { key: "calibrate", label: "Calibration" },
  ];
  const activeIndex = steps.findIndex((s) => s.key === step);
  const currentIndex = step === "done" ? steps.length : activeIndex;

  return (
    <ol className="flex items-center gap-2 text-xs">
      {steps.map((s, index) => (
        <li key={s.key} className="flex flex-1 items-center gap-2">
          <span
            className={cn(
              "flex h-6 w-6 shrink-0 items-center justify-center rounded-full border text-xs font-medium",
              index < currentIndex
                ? "border-success bg-success/15 text-success"
                : index === currentIndex
                  ? "border-primary bg-primary/10 text-primary"
                  : "border-border text-muted-foreground",
            )}
          >
            {index < currentIndex ? "✓" : index + 1}
          </span>
          <span
            className={cn(
              index === currentIndex ? "font-medium text-foreground" : "text-muted-foreground",
            )}
          >
            {s.label}
          </span>
        </li>
      ))}
    </ol>
  );
}

/**
 * The target the user looks at during a hold.
 *
 * The camera target is pinned to the top centre of the preview because that is where a built-in
 * webcam physically is; the screen target sits at the middle, standing in for the speaking
 * panel. Their separation is exactly what `screen_offset_pitch_deg` measures.
 */
function HoldOverlay({
  target,
  countdown,
}: {
  target: "camera" | "screen";
  countdown: number | null;
}) {
  return (
    <div className="absolute inset-0 flex flex-col bg-black/55 text-white">
      <div
        className={cn(
          "flex flex-1 flex-col items-center",
          target === "camera" ? "justify-start pt-2" : "justify-center",
        )}
      >
        <span className="flex h-5 w-5 animate-pulse items-center justify-center rounded-full bg-primary ring-4 ring-primary/30" />
        <span className="mt-2 px-4 text-center text-xs font-medium">
          {target === "camera" ? "Look at your camera lens" : "Look here, at the middle of the screen"}
        </span>
        {/* The dot above is already rendered while this counts down — that is what gets the
            user's eyes onto the target before the first sample is taken. */}
        {countdown !== null ? (
          <span className="mt-1 text-3xl font-bold tabular-nums">{countdown}</span>
        ) : (
          <span className="mt-1 text-xs opacity-80">Recording — hold still</span>
        )}
      </div>
    </div>
  );
}

function InfoCard({
  icon,
  title,
  body,
}: {
  icon: React.ReactNode;
  title: string;
  body: string;
}) {
  return (
    <div className="rounded-xl border border-border bg-surface p-4">
      <div className="flex items-start gap-3">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-secondary text-primary">
          {icon}
        </span>
        <div>
          <p className="text-sm font-medium text-foreground">{title}</p>
          <p className="mt-1 text-sm text-muted-foreground">{body}</p>
        </div>
      </div>
    </div>
  );
}
