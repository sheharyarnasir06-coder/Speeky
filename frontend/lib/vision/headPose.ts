/**
 * Head orientation and iris offset — the two inputs to gaze.
 *
 * Both come free from the face landmarker, which is why no separate head-pose or gaze model is
 * needed: `outputFacialTransformationMatrixes` gives the rigid head transform, and the shipped
 * model is the refined-iris (478-landmark) variant, so iris centres are already there.
 *
 * Pure and synchronous — no React, no DOM, no MediaPipe imports. Tested against hand-computed
 * matrices in headPose.test.ts.
 */

import { FACE, clamp, type Landmark } from "./normalize";

export interface HeadPose {
  /** Degrees. Positive = turning to image-right. */
  yaw: number;
  /** Degrees. Positive = looking up. */
  pitch: number;
  /** Degrees. Positive = head tilted clockwise in the image. */
  roll: number;
}

/**
 * Decode yaw/pitch/roll from MediaPipe's 4x4 facial transformation matrix.
 *
 * **The matrix is column-major.** Element (row r, column c) lives at `data[c * 4 + r]`, so the
 * rotation submatrix occupies indices 0,1,2 / 4,5,6 / 8,9,10. Reading it row-major transposes
 * the rotation, which swaps yaw and pitch — and because both are plausible small angles, the
 * output still *looks* like real head motion. Nothing downstream can detect it. This is why
 * headPose.test.ts builds matrices from known angles and asserts they round-trip: it is the
 * only place the convention is actually pinned.
 *
 * Returns null rather than throwing on a short or absent matrix; a dropped frame is normal.
 */
export function anglesFromMatrix(data: ArrayLike<number> | null | undefined): HeadPose | null {
  if (!data || data.length < 12) return null;

  const m = (row: number, col: number) => data[col * 4 + row];
  const toDeg = 180 / Math.PI;

  // Standard ZYX (yaw-pitch-roll) extraction. `sy` is the cosine of the pitch-equivalent term;
  // near zero the decomposition is degenerate (gimbal lock).
  const sy = Math.hypot(m(0, 0), m(1, 0));

  if (sy < 1e-6) {
    // Looking almost straight up or down: yaw and roll collapse onto the same axis and cannot
    // be separated. Report roll as 0 rather than emitting the noise that falls out of the
    // formula, which would otherwise show up as a phantom head tilt.
    return {
      pitch: Math.atan2(-m(1, 2), m(1, 1)) * toDeg,
      yaw: Math.atan2(-m(2, 0), sy) * toDeg,
      roll: 0,
    };
  }

  return {
    pitch: Math.atan2(m(2, 1), m(2, 2)) * toDeg,
    yaw: Math.atan2(-m(2, 0), sy) * toDeg,
    roll: Math.atan2(m(1, 0), m(0, 0)) * toDeg,
  };
}

/**
 * Build a column-major 4x4 rotation matrix from angles.
 *
 * Exists so the tests can construct a known rotation and assert `anglesFromMatrix` recovers it.
 * Keeping the inverse next to the forward transform is what makes the convention checkable
 * rather than a comment nobody can verify.
 */
export function matrixFromAngles({ yaw, pitch, roll }: HeadPose): number[] {
  const toRad = Math.PI / 180;
  const [cy, sy] = [Math.cos(yaw * toRad), Math.sin(yaw * toRad)];
  const [cp, sp] = [Math.cos(pitch * toRad), Math.sin(pitch * toRad)];
  const [cr, sr] = [Math.cos(roll * toRad), Math.sin(roll * toRad)];

  // Row-major rotation R = Rz(roll) * Ry(yaw) * Rx(pitch), matching the extraction above.
  const r = [
    [cr * cy, cr * sy * sp - sr * cp, cr * sy * cp + sr * sp],
    [sr * cy, sr * sy * sp + cr * cp, sr * sy * cp - cr * sp],
    [-sy, cy * sp, cy * cp],
  ];

  // Emit column-major, as MediaPipe does.
  const out = new Array(16).fill(0);
  for (let row = 0; row < 3; row += 1) {
    for (let col = 0; col < 3; col += 1) {
      out[col * 4 + row] = r[row][col];
    }
  }
  out[15] = 1;
  return out;
}

export interface IrisOffset {
  /** -0.5..0.5 within the eye opening. Positive = iris toward image-right. */
  dx: number;
  /** -0.5..0.5. Positive = iris toward the lower lid, i.e. looking down. */
  dy: number;
  /** How much the two eyes disagree. High values mean unreliable landmarks — reflective
   *  glasses are the usual cause — and the caller should fall back to head pose alone. */
  disagreement: number;
}

function eyeOffset(
  landmarks: Landmark[],
  outerIndex: number,
  innerIndex: number,
  upperIndex: number,
  lowerIndex: number,
  irisIndex: number,
): { dx: number; dy: number } | null {
  const outer = landmarks[outerIndex];
  const inner = landmarks[innerIndex];
  const upper = landmarks[upperIndex];
  const lower = landmarks[lowerIndex];
  const iris = landmarks[irisIndex];
  if (!outer || !inner || !upper || !lower || !iris) return null;

  const width = outer.x - inner.x;
  const height = lower.y - upper.y;
  // A squint or a blink collapses the eye opening; the ratio explodes and means nothing.
  if (Math.abs(width) < 1e-6 || Math.abs(height) < 1e-6) return null;

  // Ratios are taken within a single axis of a single eye, so they are already scale-free and
  // aspect-free — no frame size needed here.
  return {
    dx: clamp((iris.x - inner.x) / width - 0.5, -0.5, 0.5),
    dy: clamp((iris.y - upper.y) / height - 0.5, -0.5, 0.5),
  };
}

/**
 * Mean iris displacement across both eyes, as a fraction of the eye opening.
 *
 * This is what makes gaze more than head pose. People hold their head still and move their eyes
 * — head-pose-only gaze scores them as attentive while they read notes off to the side, which
 * is the classic failure of naive eye-contact metrics.
 *
 * Returns null when either eye is unusable, and reports `disagreement` so the caller can
 * decide the landmarks are untrustworthy over a whole session.
 */
export function irisOffset(landmarks: Landmark[] | null | undefined): IrisOffset | null {
  if (!landmarks || landmarks.length <= FACE.rightIris) return null;

  const left = eyeOffset(
    landmarks,
    FACE.leftEyeOuter,
    FACE.leftEyeInner,
    FACE.leftEyeUpper,
    FACE.leftEyeLower,
    FACE.leftIris,
  );
  const right = eyeOffset(
    landmarks,
    FACE.rightEyeOuter,
    FACE.rightEyeInner,
    FACE.rightEyeUpper,
    FACE.rightEyeLower,
    FACE.rightIris,
  );
  if (!left || !right) return null;

  return {
    dx: (left.dx + right.dx) / 2,
    dy: (left.dy + right.dy) / 2,
    disagreement: Math.hypot(left.dx - right.dx, left.dy - right.dy),
  };
}
