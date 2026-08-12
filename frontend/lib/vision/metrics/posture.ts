/**
 * Posture and pose-derived gesture, from the upper-body landmarks.
 *
 * Two constraints shape everything here.
 *
 * **Nothing may depend on the lower body.** Laptop webcams crop below the chest, so hips and
 * legs are absent or inferred in most sessions. Approximating posture from what remains — or
 * worse, from the head alone when the shoulders are gone too — is exactly the confident-garbage
 * failure the whole feature is built to avoid. When the shoulders are not visible, posture is
 * null. Full stop.
 *
 * **Everything is relative to the user's own baseline**, established over their first seconds
 * on camera and expressed in shoulder-width units. A tilted laptop lid rotates the scene by a
 * constant; sitting closer widens the shoulders; a taller person occupies more frame. None of
 * those are posture, and absolute thresholds would read all three as one.
 *
 * Pure and synchronous — no React, no DOM.
 */

import {
  POSE,
  distancePx,
  inFaceUnits,
  isVisible,
  median,
  shoulderMidpoint,
  shoulderTiltDeg,
  shoulderWidthPx,
  type FrameSize,
  type Landmark,
} from "../normalize";

/** One frame's worth of body geometry, all in intrinsic units. Null fields were not visible. */
export interface PoseFrame {
  /** Shoulder line angle in degrees, before baseline subtraction. */
  tiltDeg: number | null;
  /** Shoulder width in pixels — the scale reference, and the depth proxy for lean. */
  shoulderWidthPx: number | null;
  /** Torso midpoint, normalised image coordinates. */
  midpoint: Landmark | null;
  /** Vertical nose-to-shoulder-line distance in shoulder-width units. Shrinks as the head sinks
   *  toward the shoulders, which is what slouching looks like from the front. */
  headLift: number | null;
  /** Wrist positions relative to the shoulder midpoint, in shoulder-width units. */
  leftWrist: { dx: number; dy: number } | null;
  rightWrist: { dx: number; dy: number } | null;
  wristsVisible: number;
  /** True when a wrist is below the frame edge — hands gesturing under a laptop lid. */
  handsBelowFrame: boolean;
  /** Wrists crossed past the torso midline and close together. */
  armsCrossed: boolean;
}

export function readPoseFrame(landmarks: Landmark[], frame: FrameSize): PoseFrame {
  const width = shoulderWidthPx(landmarks, frame);
  const midpoint = shoulderMidpoint(landmarks);
  const tiltDeg = shoulderTiltDeg(landmarks, frame);

  const empty: PoseFrame = {
    tiltDeg,
    shoulderWidthPx: width,
    midpoint,
    headLift: null,
    leftWrist: null,
    rightWrist: null,
    wristsVisible: 0,
    handsBelowFrame: false,
    armsCrossed: false,
  };

  if (width === null || midpoint === null) return empty;

  // Head lift: how far the nose sits above the shoulder line, in shoulder widths. Using the
  // vertical component only, because a head turn changes the direct distance without changing
  // posture at all.
  const nose = landmarks[POSE.nose];
  const headLift = isVisible(nose)
    ? inFaceUnits((midpoint.y - nose.y) * frame.height, width)
    : null;

  const wristOffset = (index: number) => {
    const wrist = landmarks[index];
    if (!isVisible(wrist)) return null;
    return {
      dx: ((wrist.x - midpoint.x) * frame.width) / width,
      dy: ((wrist.y - midpoint.y) * frame.height) / width,
    };
  };

  const leftWrist = wristOffset(POSE.leftWrist);
  const rightWrist = wristOffset(POSE.rightWrist);

  // A wrist at or past the bottom edge is out of view, not at rest. Tracked separately so a
  // speaker gesturing below the lid is reported as unmeasurable rather than motionless.
  const belowFrame = [POSE.leftWrist, POSE.rightWrist].some((index) => {
    const wrist = landmarks[index];
    return !!wrist && wrist.y > 0.98;
  });

  // Crossed arms: each wrist has travelled past the midline toward the opposite side, and the
  // two are close together. Requiring both conditions avoids catching a wide two-handed gesture.
  let armsCrossed = false;
  if (leftWrist && rightWrist) {
    // FACE/POSE "left" is image-left, i.e. the SMALLER x, so a resting left wrist has negative
    // dx. Crossed means each wrist has travelled past the midline to the opposite sign.
    const crossedMidline = leftWrist.dx > 0 && rightWrist.dx < 0;
    const wristSeparation = distancePx(
      landmarks[POSE.leftWrist],
      landmarks[POSE.rightWrist],
      frame,
    );
    armsCrossed = crossedMidline && wristSeparation / width < 0.9;
  }

  return {
    tiltDeg,
    shoulderWidthPx: width,
    midpoint,
    headLift,
    leftWrist,
    rightWrist,
    wristsVisible: (leftWrist ? 1 : 0) + (rightWrist ? 1 : 0),
    handsBelowFrame: belowFrame,
    armsCrossed,
  };
}

/**
 * The user's own resting geometry, taken from their first seconds on camera.
 *
 * Medians rather than means, because the baseline window inevitably contains the moment they
 * settled into their chair.
 */
export interface PostureBaseline {
  tiltDeg: number;
  shoulderWidthPx: number;
  midpointX: number;
  headLift: number | null;
}

/** How long to observe before fixing the baseline. Long enough to average out settling, short
 *  enough that most of a session is scored against it. */
export const BASELINE_WINDOW_MS = 10_000;
/** Fewer than this and the medians are noise. */
const MIN_BASELINE_SAMPLES = 10;

export function fitBaseline(frames: PoseFrame[]): PostureBaseline | null {
  const usable = frames.filter((f) => f.shoulderWidthPx !== null && f.midpoint !== null);
  if (usable.length < MIN_BASELINE_SAMPLES) return null;

  const tilt = median(usable.map((f) => f.tiltDeg).filter((v): v is number => v !== null));
  const width = median(usable.map((f) => f.shoulderWidthPx as number));
  const midpointX = median(usable.map((f) => (f.midpoint as Landmark).x));
  const headLift = median(usable.map((f) => f.headLift).filter((v): v is number => v !== null));

  if (width === null || midpointX === null) return null;

  return { tiltDeg: tilt ?? 0, shoulderWidthPx: width, midpointX, headLift };
}

export type LeanState = "neutral" | "forward" | "back" | "side";

export interface PostureReading {
  /** Baseline-subtracted shoulder tilt, degrees. */
  tiltDeg: number | null;
  lean: LeanState;
  /** Lateral displacement of the torso from baseline, in shoulder widths. */
  lateralOffset: number | null;
  slouching: boolean;
  upright: boolean;
}

/** Shoulder width this much above or below baseline reads as moving toward or away from the
 *  camera. 8% is roughly a visible lean without catching normal fidget. */
const LEAN_DEPTH_RATIO = 0.08;
/** Lateral torso displacement, in shoulder widths, that counts as leaning to one side. */
const LEAN_SIDE_UNITS = 0.18;
/** Head lift this much below baseline means the head has sunk toward the shoulders. */
const SLOUCH_DROP_RATIO = 0.12;
/** Baseline-relative tilt beyond this is a lopsided posture rather than natural asymmetry. */
const TILT_LIMIT_DEG = 8;

export function readPosture(
  frame: PoseFrame,
  baseline: PostureBaseline | null,
  size: FrameSize,
): PostureReading {
  const idle: PostureReading = {
    tiltDeg: null,
    lean: "neutral",
    lateralOffset: null,
    slouching: false,
    upright: false,
  };

  if (!baseline || frame.shoulderWidthPx === null || frame.midpoint === null) return idle;

  const tiltDeg = frame.tiltDeg === null ? null : frame.tiltDeg - baseline.tiltDeg;

  // Depth from apparent shoulder width: moving closer widens, moving away narrows. Crude, but
  // it needs no depth sensor and no absolute calibration.
  const widthRatio = frame.shoulderWidthPx / baseline.shoulderWidthPx - 1;

  // Normalised-x delta -> pixels -> shoulder widths. Skipping the pixel step leaves this as a
  // raw fraction-of-frame-width, which is ~4x smaller and silently swallows every real lean.
  const lateralOffset =
    ((frame.midpoint.x - baseline.midpointX) * size.width) / baseline.shoulderWidthPx;

  let lean: LeanState = "neutral";
  if (widthRatio > LEAN_DEPTH_RATIO) lean = "forward";
  else if (widthRatio < -LEAN_DEPTH_RATIO) lean = "back";
  else if (Math.abs(lateralOffset) > LEAN_SIDE_UNITS) lean = "side";

  const slouching =
    baseline.headLift !== null &&
    frame.headLift !== null &&
    frame.headLift < baseline.headLift * (1 - SLOUCH_DROP_RATIO);

  const upright =
    !slouching && lean !== "side" && (tiltDeg === null || Math.abs(tiltDeg) <= TILT_LIMIT_DEG);

  return { tiltDeg, lean, lateralOffset, slouching, upright };
}

/**
 * Combined hand activity for one frame, in shoulder widths from the torso midpoint.
 *
 * This is the *pose* gesture tier: amplitude, rate and symmetry, all derivable from the wrists
 * alone. It survives when the degradation ladder switches the hand model off, which is what
 * keeps gesture counts available on weak devices. Finger-level detail (open palm, pointing)
 * belongs to the hand tier and arrives in phase 4.
 */
export interface HandActivity {
  /** Distance of the more active wrist from the torso midpoint. */
  amplitude: number | null;
  /** Per-side amplitudes, for symmetry. */
  left: number | null;
  right: number | null;
}

export function readHandActivity(frame: PoseFrame): HandActivity {
  const left = frame.leftWrist ? Math.hypot(frame.leftWrist.dx, frame.leftWrist.dy) : null;
  const right = frame.rightWrist ? Math.hypot(frame.rightWrist.dx, frame.rightWrist.dy) : null;

  const present = [left, right].filter((v): v is number => v !== null);
  return { amplitude: present.length ? Math.max(...present) : null, left, right };
}

/**
 * Left/right balance of hand movement, 0..1.
 *
 * 1 means both hands contributed equally. Uses total travel rather than mean position, since a
 * speaker resting one hand while gesturing with the other has balanced *positions* and very
 * unbalanced *movement*.
 */
export function gestureSymmetry(leftTravel: number, rightTravel: number): number | null {
  const total = leftTravel + rightTravel;
  if (total <= 0) return null;
  return 1 - Math.abs(leftTravel - rightTravel) / total;
}
