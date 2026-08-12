/**
 * Run with: npm run test:unit
 *
 * The recurring theme is that **posture is relative**. A tilted laptop lid, a user sitting
 * closer, a taller person — all change the raw geometry without changing anyone's posture. Every
 * test here exists to keep an absolute threshold from creeping back in, and to keep the
 * shoulders-or-nothing rule intact.
 */

import test from "node:test";
import assert from "node:assert/strict";

import {
  fitBaseline,
  gestureSymmetry,
  readHandActivity,
  readPosture,
  readPoseFrame,
  type PoseFrame,
} from "./posture";
import { POSE, type Landmark } from "../normalize";

const FRAME = { width: 640, height: 480 };

interface BodyOptions {
  /** Shoulder half-width in normalised x. Bigger = closer to the camera. */
  halfWidth?: number;
  /** Shoulder line vertical centre. */
  shoulderY?: number;
  /** Horizontal centre of the torso. */
  centreX?: number;
  /** Shoulder line tilt, as a vertical offset between the two shoulders. */
  tilt?: number;
  /** Nose height above the shoulder line. Smaller = head sunk = slouching. */
  headLift?: number;
  leftWrist?: { x: number; y: number } | null;
  rightWrist?: { x: number; y: number } | null;
  visibility?: number;
}

function body({
  halfWidth = 0.12,
  shoulderY = 0.6,
  centreX = 0.5,
  tilt = 0,
  headLift = 0.18,
  leftWrist = { x: 0.35, y: 0.85 },
  rightWrist = { x: 0.65, y: 0.85 },
  visibility = 0.95,
}: BodyOptions = {}): Landmark[] {
  const landmarks: Landmark[] = new Array(33).fill(null).map(() => ({ x: 0, y: 0, visibility: 0 }));

  landmarks[POSE.nose] = { x: centreX, y: shoulderY - headLift, visibility };
  landmarks[POSE.leftShoulder] = { x: centreX - halfWidth, y: shoulderY + tilt, visibility };
  landmarks[POSE.rightShoulder] = { x: centreX + halfWidth, y: shoulderY - tilt, visibility };
  if (leftWrist) landmarks[POSE.leftWrist] = { ...leftWrist, visibility };
  if (rightWrist) landmarks[POSE.rightWrist] = { ...rightWrist, visibility };

  return landmarks;
}

/** A baseline fitted from a steady neutral pose. */
function neutralBaseline(options: BodyOptions = {}) {
  const frames = Array.from({ length: 20 }, () => readPoseFrame(body(options), FRAME));
  return fitBaseline(frames)!;
}

// ── Shoulders or nothing ──────────────────────────────────────────────────────

test("no visible shoulders means no posture at all", () => {
  const invisible = body({ visibility: 0.1 });
  const frame = readPoseFrame(invisible, FRAME);

  assert.equal(frame.shoulderWidthPx, null);
  assert.equal(frame.midpoint, null);

  // And a reading against a valid baseline still refuses to guess.
  const reading = readPosture(frame, neutralBaseline(), FRAME);
  assert.equal(reading.tiltDeg, null);
  assert.equal(reading.upright, false, "unmeasurable must not read as upright");
  assert.equal(reading.slouching, false, "nor as slouching");
});

test("a baseline cannot be fitted from too few usable frames", () => {
  assert.equal(fitBaseline([]), null);
  assert.equal(fitBaseline([readPoseFrame(body(), FRAME)]), null);
  assert.equal(
    fitBaseline(Array.from({ length: 20 }, () => readPoseFrame(body({ visibility: 0.1 }), FRAME))),
    null,
    "invisible shoulders can never produce a baseline",
  );
});

test("lower-body landmarks are never required", () => {
  // Hips and legs left at visibility 0, as a laptop webcam always leaves them.
  const frame = readPoseFrame(body(), FRAME);
  assert.ok(frame.shoulderWidthPx !== null);
  const reading = readPosture(frame, neutralBaseline(), FRAME);
  assert.ok(reading.upright, "upper body alone must be enough");
});

// ── Everything is baseline-relative ───────────────────────────────────────────

test("a constant tilt from an angled screen is not reported as lopsided", () => {
  // The user's whole scene is rotated: their baseline is tilted too.
  const tilted = { tilt: 0.05 };
  const baseline = neutralBaseline(tilted);
  const reading = readPosture(readPoseFrame(body(tilted), FRAME), baseline, FRAME);

  assert.ok(Math.abs(reading.tiltDeg ?? 99) < 1, `expected ~0 relative tilt, got ${reading.tiltDeg}`);
  assert.ok(reading.upright);
});

test("a tilt away from the user's own baseline is detected", () => {
  const baseline = neutralBaseline();
  const reading = readPosture(readPoseFrame(body({ tilt: 0.06 }), FRAME), baseline, FRAME);

  assert.ok(Math.abs(reading.tiltDeg ?? 0) > 8, `expected a real tilt, got ${reading.tiltDeg}`);
  assert.equal(reading.upright, false);
});

test("sitting closer reads as leaning forward, not as a bigger person", () => {
  const baseline = neutralBaseline({ halfWidth: 0.12 });
  const closer = readPosture(readPoseFrame(body({ halfWidth: 0.14 }), FRAME), baseline, FRAME);
  assert.equal(closer.lean, "forward");

  const further = readPosture(readPoseFrame(body({ halfWidth: 0.10 }), FRAME), baseline, FRAME);
  assert.equal(further.lean, "back");
});

test("a user who simply sits far from the camera is still neutral", () => {
  // Small in frame throughout — their own baseline is small too.
  const distant = { halfWidth: 0.06 };
  const reading = readPosture(readPoseFrame(body(distant), FRAME), neutralBaseline(distant), FRAME);
  assert.equal(reading.lean, "neutral");
  assert.ok(reading.upright);
});

test("lateral displacement reads as leaning to one side", () => {
  const baseline = neutralBaseline();
  const reading = readPosture(readPoseFrame(body({ centreX: 0.62 }), FRAME), baseline, FRAME);
  assert.equal(reading.lean, "side");
  assert.equal(reading.upright, false);
});

test("slouching is the head sinking toward the shoulders", () => {
  const baseline = neutralBaseline({ headLift: 0.18 });
  const slouched = readPosture(readPoseFrame(body({ headLift: 0.13 }), FRAME), baseline, FRAME);
  assert.equal(slouched.slouching, true);
  assert.equal(slouched.upright, false);

  const held = readPosture(readPoseFrame(body({ headLift: 0.175 }), FRAME), baseline, FRAME);
  assert.equal(held.slouching, false, "normal breathing movement is not a slouch");
});

test("a naturally low head carriage is not permanently slouching", () => {
  const low = { headLift: 0.12 };
  const reading = readPosture(readPoseFrame(body(low), FRAME), neutralBaseline(low), FRAME);
  assert.equal(reading.slouching, false);
});

// ── Aspect correction ─────────────────────────────────────────────────────────

test("shoulder tilt is aspect-corrected", () => {
  // The same landmark geometry on a 4:3 and a square frame must not yield the same angle,
  // because y is a fraction of a different number of pixels. If these matched, the aspect
  // correction would have been dropped.
  const landmarks = body({ tilt: 0.04 });
  const wide = readPoseFrame(landmarks, { width: 640, height: 480 });
  const square = readPoseFrame(landmarks, { width: 480, height: 480 });

  assert.notEqual(Math.round(wide.tiltDeg!), Math.round(square.tiltDeg!));
});

test("wrist offsets are expressed in shoulder widths, not pixels", () => {
  // Two users, one twice as close. Same gesture relative to their body => same amplitude.
  const near = readHandActivity(
    readPoseFrame(body({ halfWidth: 0.2, leftWrist: { x: 0.2, y: 0.6 }, rightWrist: null }), FRAME),
  );
  const far = readHandActivity(
    readPoseFrame(body({ halfWidth: 0.1, leftWrist: { x: 0.35, y: 0.6 }, rightWrist: null }), FRAME),
  );

  assert.ok(
    Math.abs(near.amplitude! - far.amplitude!) < 0.05,
    `scale leaked in: near=${near.amplitude} far=${far.amplitude}`,
  );
});

// ── Hands ─────────────────────────────────────────────────────────────────────

test("wrists below the frame edge are flagged, not treated as at rest", () => {
  const below = readPoseFrame(
    body({ leftWrist: { x: 0.35, y: 0.995 }, rightWrist: { x: 0.65, y: 0.995 } }),
    FRAME,
  );
  assert.equal(below.handsBelowFrame, true);
});

test("crossed arms need both the midline crossing and closeness", () => {
  const crossed = readPoseFrame(
    body({ leftWrist: { x: 0.53, y: 0.7 }, rightWrist: { x: 0.47, y: 0.7 } }),
    FRAME,
  );
  assert.equal(crossed.armsCrossed, true);

  // A wide two-handed gesture crosses nothing and must not be mistaken for it.
  const openGesture = readPoseFrame(
    body({ leftWrist: { x: 0.2, y: 0.7 }, rightWrist: { x: 0.8, y: 0.7 } }),
    FRAME,
  );
  assert.equal(openGesture.armsCrossed, false);
});

test("hand activity reports per-side values and survives one missing wrist", () => {
  const oneHand = readHandActivity(
    readPoseFrame(body({ leftWrist: { x: 0.3, y: 0.7 }, rightWrist: null }), FRAME),
  );
  assert.ok(oneHand.left !== null);
  assert.equal(oneHand.right, null);
  assert.equal(oneHand.amplitude, oneHand.left, "amplitude follows the visible hand");

  const noHands: PoseFrame = readPoseFrame(body({ leftWrist: null, rightWrist: null }), FRAME);
  assert.equal(readHandActivity(noHands).amplitude, null, "no hands means null, not 0");
});

// ── Symmetry ──────────────────────────────────────────────────────────────────

test("symmetry is 1 for balanced travel and 0 for one-sided", () => {
  assert.equal(gestureSymmetry(10, 10), 1);
  assert.equal(gestureSymmetry(10, 0), 0);
  assert.equal(gestureSymmetry(0, 0), null, "no movement at all is unmeasurable, not asymmetric");
  assert.ok(Math.abs(gestureSymmetry(7, 3)! - 0.6) < 1e-9);
});
