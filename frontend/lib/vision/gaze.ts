/**
 * Turning head pose + iris offset into "where is this person looking".
 *
 * This is the highest-risk metric in the whole feature, for a reason that is geometric rather
 * than technical: **the camera is not where the content is.** A webcam sits above the screen,
 * so a user attentively watching the on-screen panel is physically pitched 6-18 degrees below
 * the lens, and reading notes on the desk is 30-45 degrees below it. A naive
 * "pitch < -10 means looking away" rule scores an engaged user at near-zero eye contact — a
 * confident, specific, wrong number that users immediately (and correctly) stop trusting.
 *
 * The fix is calibration: measure where *this* user's head sits when they look at the lens,
 * and again when they look at the panel, and derive the geometry from those two points instead
 * of assuming it. Everything below exists to support that.
 *
 * Two further points that are easy to lose:
 *
 *   - **Iris is not optional.** People hold their head still and move their eyes. Head-pose-only
 *     gaze marks someone reading notes off to the side as attentive. The iris term is what
 *     separates them, so `irisGain` is fitted during calibration rather than assumed.
 *   - **An uncalibrated session must say so**, not silently guess. `calibrationQuality` and
 *     `method` flow into the payload, and backend/lib/video_scorer.py refuses to quote
 *     `on_camera_pct` unless calibration was real.
 *
 * Pure and synchronous — no React, no DOM.
 */

import type { HeadPose, IrisOffset } from "./headPose";
import { clamp, median, medianAbsoluteDeviation } from "./normalize";

export type GazeBucket = "on_camera" | "on_screen" | "down" | "up" | "side" | "offscreen";

export type CalibrationMethod = "on_screen_target" | "session_baseline" | "none";
export type CalibrationQuality = "good" | "weak" | "failed";

export interface GazeCalibration {
  performed: boolean;
  method: CalibrationMethod;
  /** Head pose when looking directly at the lens. */
  baselineYawDeg: number | null;
  baselinePitchDeg: number | null;
  /** Iris offset at that same moment, so the iris term measures *change* from neutral. */
  baselineIrisDx: number | null;
  baselineIrisDy: number | null;
  /** Half-width of the "on camera" cone. */
  yawToleranceDeg: number | null;
  pitchToleranceDeg: number | null;
  /** Pitch delta between looking at the lens and looking at the app panel. Negative, since the
   *  panel sits below the camera. This is what distinguishes "watching the AI" from "reading
   *  my notes" — without it both are simply "down". */
  screenOffsetPitchDeg: number | null;
  /** Fitted k in `gaze = head + k * iris`. Null means the iris was unusable and gaze falls back
   *  to head pose alone. */
  irisGainDegPerUnit: number | null;
  quality: CalibrationQuality;
}

/** Whether a calibration is good enough for its gaze readings to be worth quoting.
 *
 *  This is the frontend's mirror of what the backend's weight table works out to: anything short
 *  of an on-screen-target fit of "good" quality lands under the confidence_weight the results
 *  tile requires before it shows a number (_CALIBRATION_METHOD_WEIGHTS x _CALIBRATION_WEIGHTS in
 *  lib/video_scorer.py). Live coaching uses it too, so the session cannot promise eye-contact
 *  feedback it will then decline to score. */
export function isScorableCalibration(calibration: GazeCalibration): boolean {
  return calibration.method === "on_screen_target" && calibration.quality === "good";
}

export const NO_CALIBRATION: GazeCalibration = {
  performed: false,
  method: "none",
  baselineYawDeg: null,
  baselinePitchDeg: null,
  baselineIrisDx: null,
  baselineIrisDy: null,
  yawToleranceDeg: null,
  pitchToleranceDeg: null,
  screenOffsetPitchDeg: null,
  irisGainDegPerUnit: null,
  quality: "failed",
};

/** Tolerance bounds. Too tight punishes anyone who cannot sit perfectly still; too loose makes
 *  "eye contact" meaningless. */
const MIN_TOLERANCE_DEG = 6;
const MAX_TOLERANCE_DEG = 15;
/**
 * MAD above this means the user never held still enough for the sample to mean anything.
 *
 * Loosened from 10 after real-camera testing: normal people are not statues, and a MAD in the
 * 10-14 degree range still produces a perfectly usable median — it just widens the tolerance
 * cone, which is the intended, proportionate penalty. Failing outright instead was costing
 * calibrations that would have been fine.
 */
const MAX_USABLE_MAD_DEG = 14;
/**
 * Below this many usable samples the medians are not trustworthy.
 *
 * Also loosened (was 8). Since collection moved into the rAF loop a healthy hold now yields
 * well over a hundred samples rather than a dozen, so this floor only fires when detection is
 * genuinely failing — which is exactly when it should.
 */
const MIN_SAMPLES = 5;
/** Iris travel between the two targets must exceed this for the gain fit to be meaningful;
 *  otherwise we are dividing by noise. */
const MIN_IRIS_TRAVEL = 0.04;
/** Fallback gain when the fit is not possible. Roughly the observed eye-rotation-per-unit for
 *  a typical viewing distance — good enough to beat head-pose-only, not good enough to trust. */
const DEFAULT_IRIS_GAIN = 25;

/** Beyond this yaw the user has turned away from the screen entirely. */
const OFFSCREEN_YAW_DEG = 45;

export interface CalibrationSample {
  pose: HeadPose;
  iris: IrisOffset | null;
}

function axisStats(values: number[]) {
  return {
    centre: median(values),
    spread: medianAbsoluteDeviation(values),
  };
}

/**
 * Fit a calibration from the two on-screen targets.
 *
 * `cameraSamples` are captured while the user looks at a dot beside the lens; `screenSamples`
 * while they look at a dot in the middle of the speaking panel. Callers should already have
 * dropped the first second of each hold, since users take a moment to settle.
 *
 * Degrades rather than fails: too few samples or too much jitter downgrades `quality` to
 * "weak", and an unusable iris drops the gain term while keeping the head-pose baseline. Only a
 * complete absence of usable camera samples produces "failed".
 */
export function calibrateFromTargets(
  cameraSamples: CalibrationSample[],
  screenSamples: CalibrationSample[] = [],
): GazeCalibration {
  if (cameraSamples.length === 0) return { ...NO_CALIBRATION };

  const yaw = axisStats(cameraSamples.map((s) => s.pose.yaw));
  const pitch = axisStats(cameraSamples.map((s) => s.pose.pitch));
  if (yaw.centre === null || pitch.centre === null) return { ...NO_CALIBRATION };

  const cameraIris = cameraSamples.map((s) => s.iris).filter((i): i is IrisOffset => i !== null);
  const baselineIrisDx = median(cameraIris.map((i) => i.dx));
  const baselineIrisDy = median(cameraIris.map((i) => i.dy));

  // A jittery user gets a WIDER cone, not a false negative — the cost of restlessness should be
  // precision, not an accusation.
  const toleranceFrom = (spread: number | null) =>
    clamp(2.5 * (spread ?? MIN_TOLERANCE_DEG / 2.5), MIN_TOLERANCE_DEG, MAX_TOLERANCE_DEG);

  const tooFewSamples = cameraSamples.length < MIN_SAMPLES;
  const tooJittery =
    (yaw.spread ?? 0) > MAX_USABLE_MAD_DEG || (pitch.spread ?? 0) > MAX_USABLE_MAD_DEG;

  // Screen target: the pitch delta between the two holds.
  let screenOffsetPitchDeg: number | null = null;
  let irisGainDegPerUnit: number | null = null;

  if (screenSamples.length >= MIN_SAMPLES) {
    const screenPitch = median(screenSamples.map((s) => s.pose.pitch));
    if (screenPitch !== null) screenOffsetPitchDeg = screenPitch - pitch.centre;

    const screenIris = screenSamples.map((s) => s.iris).filter((i): i is IrisOffset => i !== null);
    const screenIrisDy = median(screenIris.map((i) => i.dy));

    // Fit the iris gain from how much the eyes moved versus how much the head did. Most people
    // barely move their head between two nearby targets but their iris travels a lot, which is
    // exactly the signal head-pose-only gaze misses.
    if (
      screenOffsetPitchDeg !== null &&
      screenIrisDy !== null &&
      baselineIrisDy !== null &&
      Math.abs(screenIrisDy - baselineIrisDy) >= MIN_IRIS_TRAVEL
    ) {
      const gain = -screenOffsetPitchDeg / (screenIrisDy - baselineIrisDy);
      // Reject an implausible fit rather than propagating a wild multiplier.
      if (Number.isFinite(gain) && gain > 2 && gain < 120) irisGainDegPerUnit = gain;
    }
  }

  if (irisGainDegPerUnit === null && cameraIris.length >= MIN_SAMPLES) {
    irisGainDegPerUnit = DEFAULT_IRIS_GAIN;
  }

  /**
   * Re-express the screen offset in GAZE space, not head space.
   *
   * `screenOffsetPitchDeg` above is a pure head-pitch delta, but `classifyGaze` compares it
   * against the output of `gazeAngles`, which is head pitch *plus* the iris term. Those are
   * different units, and the mismatch is real: most people barely move their head between two
   * nearby targets and do almost all of the travel with their eyes, so the head-only delta
   * badly understates the gap — by more than half in typical testing.
   *
   * Recomputing it with the same transform the classifier uses keeps both sides in one space,
   * and is what makes the separation cap below meaningful rather than arbitrary.
   */
  if (screenOffsetPitchDeg !== null && irisGainDegPerUnit !== null && baselineIrisDy !== null) {
    const screenIris = screenSamples.map((s) => s.iris).filter((i): i is IrisOffset => i !== null);
    const screenIrisDy = median(screenIris.map((i) => i.dy));
    if (screenIrisDy !== null) {
      screenOffsetPitchDeg -= irisGainDegPerUnit * (screenIrisDy - baselineIrisDy);
    }
  }

  let pitchToleranceDeg = toleranceFrom(pitch.spread);

  /**
   * The cone must never be wide enough to swallow the screen offset.
   *
   * A restless user gets a wider cone, which is the right penalty — but taken far enough it
   * absorbs the very gap the second calibration target measured, and then "looking at the app
   * panel" classifies as "looking at the lens". That inflates `on_camera_pct` for exactly the
   * users whose data is least reliable, which is the worst possible direction for the error.
   *
   * So cap the cone below the measured offset. If the floor (MIN_TOLERANCE_DEG) is already too
   * wide to keep them apart — a very short screen offset, e.g. a laptop with the camera almost
   * in line with the panel — then we genuinely cannot distinguish the two, and the honest move
   * is to drop the screen target rather than report a separation we can't make.
   */
  if (screenOffsetPitchDeg !== null) {
    // Panel gaze lands at exactly `screenOffsetPitchDeg`, and classifyGaze calls anything within
    // `pitchToleranceDeg` of zero "on camera" — so the cone has to stay strictly inside the
    // offset. 0.9 keeps a small margin without narrowing the cone more than necessary.
    const separable = Math.abs(screenOffsetPitchDeg) * 0.9;
    if (separable >= MIN_TOLERANCE_DEG) {
      pitchToleranceDeg = Math.min(pitchToleranceDeg, separable);
    } else {
      screenOffsetPitchDeg = null;
    }
  }

  const hasScreenTarget = screenOffsetPitchDeg !== null;
  const quality: CalibrationQuality = tooJittery || tooFewSamples ? "weak" : hasScreenTarget ? "good" : "weak";

  return {
    performed: true,
    // "on_screen_target" is the only method the backend will quote on_camera_pct for, so it is
    // claimed only when both targets actually produced a usable fit.
    method: hasScreenTarget && quality === "good" ? "on_screen_target" : "session_baseline",
    baselineYawDeg: yaw.centre,
    baselinePitchDeg: pitch.centre,
    baselineIrisDx,
    baselineIrisDy,
    yawToleranceDeg: toleranceFrom(yaw.spread),
    pitchToleranceDeg,
    screenOffsetPitchDeg,
    irisGainDegPerUnit,
    quality,
  };
}

/**
 * Fallback for a user who skipped calibration: take the modal head orientation over the whole
 * session as their neutral.
 *
 * This removes *static* bias only — an off-centre camera, an external monitor, a user sitting
 * at an angle. It is emphatically **not** evidence they looked at the lens; the mode is just
 * wherever they most often pointed their head. Hence `method: "session_baseline"` and
 * `quality: "weak"`, which the backend downweights.
 */
export function calibrateFromSessionMode(samples: CalibrationSample[]): GazeCalibration {
  if (samples.length < MIN_SAMPLES) return { ...NO_CALIBRATION };

  // 2-degree histogram bins; the mode is more robust than a mean against long look-aways.
  const bin = (value: number) => Math.round(value / 2) * 2;
  const counts = new Map<string, { yaw: number; pitch: number; n: number }>();
  for (const sample of samples) {
    const key = `${bin(sample.pose.yaw)}:${bin(sample.pose.pitch)}`;
    const entry = counts.get(key) ?? { yaw: bin(sample.pose.yaw), pitch: bin(sample.pose.pitch), n: 0 };
    entry.n += 1;
    counts.set(key, entry);
  }

  let mode = { yaw: 0, pitch: 0, n: 0 };
  for (const entry of counts.values()) if (entry.n > mode.n) mode = entry;

  const iris = samples.map((s) => s.iris).filter((i): i is IrisOffset => i !== null);

  return {
    performed: false,
    method: "session_baseline",
    baselineYawDeg: mode.yaw,
    baselinePitchDeg: mode.pitch,
    baselineIrisDx: median(iris.map((i) => i.dx)),
    baselineIrisDy: median(iris.map((i) => i.dy)),
    yawToleranceDeg: MAX_TOLERANCE_DEG,
    pitchToleranceDeg: MAX_TOLERANCE_DEG,
    screenOffsetPitchDeg: null,
    irisGainDegPerUnit: iris.length >= MIN_SAMPLES ? DEFAULT_IRIS_GAIN : null,
    quality: "weak",
  };
}

export interface GazeAngles {
  /** Degrees from the calibrated "at the lens" direction. Positive pitch = above the lens. */
  yaw: number;
  pitch: number;
}

/**
 * Combine head pose and iris into a gaze direction relative to the lens.
 *
 * `gaze = head + gain * iris_displacement_from_neutral`. When calibration is absent the raw
 * head angles are used, which is wrong by exactly the unmodelled camera offset — the reason an
 * uncalibrated session is never quoted directly.
 */
export function gazeAngles(
  pose: HeadPose,
  iris: IrisOffset | null,
  calibration: GazeCalibration,
  /** Set when the iris landmarks proved unreliable across the session (reflective glasses). */
  irisUsable = true,
): GazeAngles {
  const yaw = pose.yaw - (calibration.baselineYawDeg ?? 0);
  const pitch = pose.pitch - (calibration.baselinePitchDeg ?? 0);

  const gain = calibration.irisGainDegPerUnit;
  if (!irisUsable || iris === null || gain === null) return { yaw, pitch };

  const dx = iris.dx - (calibration.baselineIrisDx ?? 0);
  const dy = iris.dy - (calibration.baselineIrisDy ?? 0);

  // dy is positive toward the lower lid, i.e. looking down, which lowers pitch — hence the
  // subtraction. dx is positive toward image-right, matching the yaw sign convention.
  return { yaw: yaw + gain * dx, pitch: pitch - gain * dy };
}

/**
 * Bucket a gaze direction.
 *
 * The `on_screen` band only exists once the screen target has been calibrated. Without it,
 * looking at the app panel is indistinguishable from looking at the desk, and both land in
 * `down` — which is honest, and is why the uncalibrated path scores on
 * `100 - down - offscreen` rather than on `on_camera` alone.
 */
export function classifyGaze(angles: GazeAngles, calibration: GazeCalibration): GazeBucket {
  const yawTolerance = calibration.yawToleranceDeg ?? MAX_TOLERANCE_DEG;
  const pitchTolerance = calibration.pitchToleranceDeg ?? MAX_TOLERANCE_DEG;

  if (Math.abs(angles.yaw) > OFFSCREEN_YAW_DEG) return "offscreen";

  if (Math.abs(angles.yaw) <= yawTolerance && Math.abs(angles.pitch) <= pitchTolerance) {
    return "on_camera";
  }

  const screenOffset = calibration.screenOffsetPitchDeg;
  if (screenOffset !== null && Math.abs(angles.yaw) <= yawTolerance * 2) {
    // The panel occupies a band around the calibrated offset, widened a little because a screen
    // is an area rather than a point.
    const band = pitchTolerance * 1.5;
    if (Math.abs(angles.pitch - screenOffset) <= band) return "on_screen";
  }

  if (angles.pitch < -pitchTolerance) return "down";
  if (angles.pitch > pitchTolerance) return "up";
  return "side";
}

/** Iris disagreement above this across a session means the landmarks cannot be trusted —
 *  reflective lenses are the usual cause — and gaze should fall back to head pose alone. */
export const IRIS_DISAGREEMENT_LIMIT = 0.18;
