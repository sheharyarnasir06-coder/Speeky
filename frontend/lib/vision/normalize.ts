/**
 * The only place landmark arithmetic is allowed to happen.
 *
 * MediaPipe returns normalised coordinates where **x is a fraction of frame width and y is a
 * fraction of frame height**. Subtracting them directly is wrong on any non-square frame, and
 * capture runs at 640x480 (4:3). Get this wrong and every tilt, distance and amplitude metric
 * is skewed by 33% in one axis — silently, and in a way that looks like plausible data.
 *
 * So: no module outside this one may do raw coordinate maths. Everything is expressed in one of
 * two intrinsic units, both aspect-corrected, so that a user sitting closer, a camera mounted
 * higher, or a different capture resolution do not change the numbers:
 *
 *   - **face-scale**  = outer eye-corner distance (33 <-> 263)
 *   - **body-scale**  = shoulder width (pose 11 <-> 12), added in phase 3
 *
 * Pure and synchronous — no React, no DOM.
 */

import type { FramingState } from "./types";

/** The subset of MediaPipe's NormalizedLandmark this module needs. */
export interface Landmark {
  x: number;
  y: number;
  z?: number;
  visibility?: number;
}

export interface FrameSize {
  width: number;
  height: number;
}

/**
 * Canonical MediaPipe face-mesh indices used across the vision layer.
 *
 * "Left" and "right" here are **image-space**, i.e. the frame as MediaPipe sees it. The
 * self-view is CSS-mirrored for the user's comfort but the frames fed to the model are not, so
 * image-left is the user's *right* side. Anything that surfaces left/right in coaching copy
 * must swap; anything symmetric (a mean, a distance) must not.
 */
export const FACE = {
  /** Lateral (outer) corner of the image-left eye. */
  leftEyeOuter: 33,
  /** Medial (inner) corner of the image-left eye. */
  leftEyeInner: 133,
  leftEyeUpper: 159,
  leftEyeLower: 145,

  rightEyeOuter: 263,
  rightEyeInner: 362,
  rightEyeUpper: 386,
  rightEyeLower: 374,

  /** Iris centres. Present only on the refined-iris (478-landmark) model, which is the one
   *  shipped in public/mediapipe/models/face_landmarker.task. */
  leftIris: 468,
  rightIris: 473,

  noseTip: 1,
} as const;

/**
 * MediaPipe pose landmark indices. Same image-space left/right caveat as FACE above.
 *
 * Only the upper body is listed, and that is deliberate: laptop webcams crop below the chest,
 * so hip and leg landmarks are absent or low-confidence in the overwhelming majority of
 * sessions. Nothing in the posture metrics may depend on them — see metrics/posture.ts.
 */
export const POSE = {
  nose: 0,
  leftShoulder: 11,
  rightShoulder: 12,
  leftElbow: 13,
  rightElbow: 14,
  leftWrist: 15,
  rightWrist: 16,
  leftHip: 23,
  rightHip: 24,
} as const;

/** Healthy head-and-shoulders webcam framing, as a fraction of frame width. Shared between the
 *  pre-session check modal and the live in-session overlay so the two never disagree. */
const FACE_RATIO_MIN = 0.055;
const FACE_RATIO_MAX = 0.13;
/** Nose outside this horizontal band means the user is sitting off to one side. */
const CENTRE_MIN = 0.25;
const CENTRE_MAX = 0.75;

/**
 * Classify webcam framing from face landmarks alone.
 *
 * Used both by the calibration modal (via requestAnimationFrame) and by the live session
 * overlay (via the face model's own cadence) — kept here rather than duplicated so the two
 * thresholds can never drift apart.
 */
export function evaluateFraming(
  landmarks: Landmark[] | undefined,
  frame: FrameSize,
): FramingState {
  if (!landmarks) return "unknown";

  const ratio = faceWidthRatio(landmarks, frame);
  if (ratio === null) return "unknown";

  if (ratio < FACE_RATIO_MIN) return "too_far";
  if (ratio > FACE_RATIO_MAX) return "too_close";

  const nose = landmarks[FACE.noseTip];
  if (nose && (nose.x < CENTRE_MIN || nose.x > CENTRE_MAX)) return "off_center";

  return "good";
}

/** Landmarks below this `visibility` are MediaPipe's guesses, not observations. */
export const MIN_VISIBILITY = 0.6;

export function isVisible(landmark: Landmark | undefined): landmark is Landmark {
  return !!landmark && (landmark.visibility ?? 1) >= MIN_VISIBILITY;
}

/**
 * Shoulder-to-shoulder distance in pixels — the body-scale unit.
 *
 * Every body-relative metric divides by this so that sitting closer to the camera does not
 * register as bigger gestures and worse sway. Returns null when either shoulder is not
 * confidently visible, which nulls the whole posture family rather than producing numbers from
 * an inferred skeleton.
 */
export function shoulderWidthPx(landmarks: Landmark[], frame: FrameSize): number | null {
  const left = landmarks[POSE.leftShoulder];
  const right = landmarks[POSE.rightShoulder];
  if (!isVisible(left) || !isVisible(right)) return null;

  const distance = distancePx(left, right, frame);
  return distance > 0 ? distance : null;
}

/** Midpoint of the shoulder line — the torso reference point for lean and sway. */
export function shoulderMidpoint(landmarks: Landmark[]): Landmark | null {
  const left = landmarks[POSE.leftShoulder];
  const right = landmarks[POSE.rightShoulder];
  if (!isVisible(left) || !isVisible(right)) return null;

  return {
    x: (left.x + right.x) / 2,
    y: (left.y + right.y) / 2,
    z: ((left.z ?? 0) + (right.z ?? 0)) / 2,
  };
}

/**
 * Shoulder line angle in degrees, aspect-corrected. Positive means the image-left shoulder
 * sits lower.
 *
 * Callers must subtract the user's own baseline before interpreting this: a tilted laptop lid
 * rotates the entire scene by a constant, and reading raw tilt would report every user on a
 * slightly angled screen as permanently lopsided.
 */
export function shoulderTiltDeg(landmarks: Landmark[], frame: FrameSize): number | null {
  const left = landmarks[POSE.leftShoulder];
  const right = landmarks[POSE.rightShoulder];
  if (!isVisible(left) || !isVisible(right)) return null;

  // left -> right, so a level pose is ~0 rather than ~180. Baseline subtraction would survive
  // either convention right up until the angle wrapped across +/-180, at which point a tiny
  // real movement would register as a 360-degree lurch.
  return angleDeg(left, right, frame);
}

/**
 * Euclidean distance in **pixels**, correcting for the frame's aspect ratio.
 *
 * This is the function that exists so nobody writes `Math.hypot(a.x - b.x, a.y - b.y)` on
 * normalised coordinates, which is the single easiest way to corrupt every downstream metric.
 */
export function distancePx(a: Landmark, b: Landmark, frame: FrameSize): number {
  const dx = (a.x - b.x) * frame.width;
  const dy = (a.y - b.y) * frame.height;
  return Math.hypot(dx, dy);
}

/** Signed angle of the a->b vector from horizontal, in degrees, aspect-corrected. */
export function angleDeg(a: Landmark, b: Landmark, frame: FrameSize): number {
  const dx = (b.x - a.x) * frame.width;
  const dy = (b.y - a.y) * frame.height;
  return (Math.atan2(dy, dx) * 180) / Math.PI;
}

/**
 * Outer eye-corner distance in pixels — the face-scale unit.
 *
 * Everything face-relative (face-touch proximity, framing distance) divides by this, so that
 * "close to the face" means the same thing whether the user is 40cm or 90cm from the camera.
 */
export function interocularPx(landmarks: Landmark[], frame: FrameSize): number | null {
  const outerLeft = landmarks[FACE.leftEyeOuter];
  const outerRight = landmarks[FACE.rightEyeOuter];
  if (!outerLeft || !outerRight) return null;
  const distance = distancePx(outerLeft, outerRight, frame);
  return distance > 0 ? distance : null;
}

/**
 * Face width as a fraction of frame width — the framing signal.
 *
 * Roughly 0.055-0.13 is a healthy head-and-shoulders webcam framing. Below that the user is too
 * far for reliable iris landmarks; above it they are cropped too tight for shoulders to ever
 * be visible.
 */
export function faceWidthRatio(landmarks: Landmark[], frame: FrameSize): number | null {
  const interocular = interocularPx(landmarks, frame);
  if (interocular === null || !frame.width) return null;
  return interocular / frame.width;
}

/** Convert a pixel distance into face-scale units. Null-safe by design: a missing scale must
 *  produce "not measured", never a raw pixel value that looks like a ratio. */
export function inFaceUnits(px: number, interocular: number | null): number | null {
  if (interocular === null || interocular <= 0) return null;
  return px / interocular;
}

export function clamp(value: number, low: number, high: number): number {
  return Math.max(low, Math.min(high, value));
}

/** Median, used instead of a mean wherever a user might jitter or a landmark might spike. */
export function median(values: number[]): number | null {
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 0 ? (sorted[mid - 1] + sorted[mid]) / 2 : sorted[mid];
}

/**
 * Median absolute deviation — a spread measure that ignores outliers.
 *
 * Used to size the calibration tolerance cone. A standard deviation would be inflated by the
 * one moment the user glanced away mid-calibration; MAD is not, so a fidgety user gets a
 * slightly wider cone rather than a cone centred on the wrong place.
 */
export function medianAbsoluteDeviation(values: number[]): number | null {
  const centre = median(values);
  if (centre === null) return null;
  return median(values.map((value) => Math.abs(value - centre)));
}
