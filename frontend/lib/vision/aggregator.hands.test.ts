/**
 * Run with: npm run test:unit
 *
 * The hand tier through the aggregator.
 *
 * The property this file mostly guards is the **two-tier split**: when the hand model is off or
 * blind, finger-level metrics go null while the pose-tier gesture numbers carry on unchanged.
 * That split is what makes the degradation ladder viable, and it is easy to break by adding a
 * gate in the wrong place.
 */

import test from "node:test";
import assert from "node:assert/strict";

import { createAggregator, type FaceSample } from "./aggregator";
import { calibrateFromTargets, type CalibrationSample } from "./gaze";
import type { HeadPose, IrisOffset } from "./headPose";
import type { HandShape } from "./metrics/hands";
import type { PoseFrame } from "./metrics/posture";

const headPose = (yaw: number, pitch: number, roll = 0): HeadPose => ({ yaw, pitch, roll });
const iris = (dx = 0, dy = 0): IrisOffset => ({ dx, dy, disagreement: 0 });

function hold(yaw: number, pitch: number, dy: number, count = 20): CalibrationSample[] {
  return Array.from({ length: count }, (_, i) => {
    const wobble = ((i % 5) - 2) * 0.6;
    return { pose: headPose(yaw + wobble * 0.5, pitch + wobble), iris: iris(0, dy) };
  });
}

const OPTIONS = {
  videoWidth: 640,
  videoHeight: 480,
  modelVersions: {},
  userAgentHint: "chrome-desktop",
  calibration: calibrateFromTargets(hold(0, 0, 0), hold(0, -4, 0.24)),
};

const FACE_STEP_MS = 100; // 10Hz
const POSE_STEP_MS = 167; // ~6Hz
const HAND_STEP_MS = 125; // 8Hz

/** Face at the top-middle of the frame, so hand proximity is testable. */
const FACE_CENTRE = { x: 0.5, y: 0.3 };
const FACE_SCALE_PX = 60;

function faceSample(atMs: number): FaceSample {
  return {
    atMs,
    detected: true,
    pose: headPose(0, 0),
    iris: iris(),
    smile: 0,
    blink: 0,
    browRaise: 0,
    jawOpen: 0,
    neutral: 0.9,
    centre: FACE_CENTRE,
    scalePx: FACE_SCALE_PX,
  };
}

function poseFrame(overrides: Partial<PoseFrame> = {}): PoseFrame {
  return {
    tiltDeg: 0,
    shoulderWidthPx: 150,
    midpoint: { x: 0.5, y: 0.6 },
    headLift: 0.55,
    leftWrist: { dx: -0.6, dy: 1.0 },
    rightWrist: { dx: 0.6, dy: 1.0 },
    wristsVisible: 2,
    handsBelowFrame: false,
    armsCrossed: false,
    ...overrides,
  };
}

function handShape(overrides: Partial<HandShape> = {}): HandShape {
  return {
    side: "right",
    extended: { index: true, middle: true, ring: true, pinky: true },
    extendedCount: 4,
    openPalm: true,
    pointing: false,
    fist: false,
    centre: { x: 0.6, y: 0.75 },
    scalePx: 40,
    ...overrides,
  };
}

interface SessionOptions {
  seconds?: number;
  hands?: (atMs: number) => HandShape[];
  /** Omit to run with the hand model disabled entirely. */
  handAttempts?: number | null;
}

function runSession({ seconds = 60, hands, handAttempts }: SessionOptions = {}) {
  const aggregator = createAggregator(OPTIONS);

  for (let at = 0; at < seconds * 1000; at += FACE_STEP_MS) {
    aggregator.addFaceSample(faceSample(at));
  }
  for (let at = 0; at < seconds * 1000; at += POSE_STEP_MS) {
    aggregator.addPoseSample({ atMs: at, detected: true, frame: poseFrame() });
  }

  let handSamples = 0;
  if (hands) {
    for (let at = 0; at < seconds * 1000; at += HAND_STEP_MS) {
      aggregator.addHandSample({ atMs: at, hands: hands(at) });
      handSamples += 1;
    }
  }

  return aggregator.build({
    activeSeconds: seconds,
    framesSeen: Math.round((seconds * 1000) / FACE_STEP_MS),
    framesAnalyzed: Math.round((seconds * 1000) / FACE_STEP_MS),
    faceAttempts: Math.round((seconds * 1000) / FACE_STEP_MS),
    poseAttempts: Math.round((seconds * 1000) / POSE_STEP_MS),
    handAttempts: handAttempts === null ? 0 : (handAttempts ?? handSamples),
  });
}

// ── The two-tier split ────────────────────────────────────────────────────────

test("with the hand model off, finger metrics are null but pose gesture survives", () => {
  const features = runSession({ handAttempts: null });

  assert.equal(features.gesture.open_palm_pct, null);
  assert.equal(features.gesture.pointing_count, null);
  assert.equal(features.gesture.fidget_score, null);
  assert.ok(features.unavailable_reasons.includes("hands_not_enabled"));

  // The pose tier is untouched — this is the whole point of the split.
  assert.equal(features.gesture.count, 0);
  assert.ok(features.gesture.hands_visible_pct! > 90);
});

test("a hand model that rarely sees a hand nulls only the finger tier", () => {
  // Model running at 8Hz but detecting nothing: coverage 0%.
  const features = runSession({ hands: () => [] });

  assert.equal(features.gesture.open_palm_pct, null);
  assert.ok(features.unavailable_reasons.some((r) => r.startsWith("hand_coverage_")));
  assert.equal(features.gesture.count, 0, "pose-tier gesture is unaffected");
  assert.ok(features.quality.achieved_hand_hz! > 7);
});

// ── Finger-level signals ──────────────────────────────────────────────────────

test("an open palm held throughout is reported as such", () => {
  const features = runSession({ hands: () => [handShape()] });
  assert.ok(features.gesture.open_palm_pct! > 95, `got ${features.gesture.open_palm_pct}`);
});

test("pointing is counted on the rising edge, not per frame", () => {
  // Three separate points, each held for two seconds. Counting frames would report ~48.
  const features = runSession({
    hands: (atMs) => {
      const second = Math.floor(atMs / 1000);
      const pointing = second % 10 < 2 && second < 30;
      return [handShape({ pointing, openPalm: !pointing })];
    },
  });

  assert.equal(features.gesture.pointing_count, 3);
});

test("a hand resting at the face is counted once, and a passing gesture is not", () => {
  const features = runSession({
    hands: (atMs) => {
      // Held at the face for 3s...
      if (atMs >= 10_000 && atMs < 13_000) {
        return [handShape({ centre: { x: 0.5, y: 0.32 } })];
      }
      // ...then a single fast sweep past it, well under the dwell.
      if (atMs >= 30_000 && atMs < 30_200) {
        return [handShape({ centre: { x: 0.5, y: 0.32 } })];
      }
      return [handShape({ centre: { x: 0.6, y: 0.75 } })];
    },
  });

  assert.equal(features.gesture.face_touch_count, 1, "the sweep must not count as a touch");
});

test("clasped hands accrue time only once held", () => {
  const clasped = runSession({
    hands: () => [
      handShape({ side: "left", centre: { x: 0.49, y: 0.7 } }),
      handShape({ side: "right", centre: { x: 0.51, y: 0.7 } }),
    ],
  });
  assert.ok(clasped.gesture.hands_clasped_pct! > 80, `got ${clasped.gesture.hands_clasped_pct}`);

  const apart = runSession({
    hands: () => [
      handShape({ side: "left", centre: { x: 0.2, y: 0.7 } }),
      handShape({ side: "right", centre: { x: 0.8, y: 0.7 } }),
    ],
  });
  assert.equal(apart.gesture.hands_clasped_pct, 0);
});

// ── Fidget ────────────────────────────────────────────────────────────────────

test("constant small movement reads as fidgeting, stillness does not", () => {
  const still = runSession({ hands: () => [handShape()] });
  assert.equal(still.gesture.fidget_score, 0, "a motionless hand is not fidgeting");

  const jittery = runSession({
    hands: (atMs) => [
      // ~3% of frame width per sample: too small for a gesture, too constant to be nothing.
      handShape({ centre: { x: 0.6 + (Math.floor(atMs / HAND_STEP_MS) % 2) * 0.03, y: 0.75 } }),
    ],
  });
  assert.ok(jittery.gesture.fidget_score! > 80, `got ${jittery.gesture.fidget_score}`);
});

test("large purposeful strokes are not counted as fidgeting", () => {
  const gesturing = runSession({
    hands: (atMs) => [
      handShape({ centre: { x: 0.5 + Math.sin((atMs / 1000) * Math.PI) * 0.25, y: 0.7 } }),
    ],
  });

  assert.ok(
    (gesturing.gesture.fidget_score ?? 100) < 50,
    `broad strokes should not read as fidget, got ${gesturing.gesture.fidget_score}`,
  );
});

test("fidget is judged on path versus range, not on instantaneous speed", () => {
  /**
   * Regression guard. The first implementation classified each sample by how far the hand moved
   * since the last one, which cannot work: a broad sweeping gesture slows near its turning
   * points and spends roughly half its samples at the same speed as a jitter. It scored a
   * deliberate two-handed sweep at 50% fidget.
   *
   * The distinguishing property is that a gesture *travels*. Both patterns below cover a similar
   * total path; only one of them goes anywhere.
   */
  const jitterInPlace = runSession({
    hands: (atMs) => [
      handShape({ centre: { x: 0.6 + (Math.floor(atMs / HAND_STEP_MS) % 2) * 0.03, y: 0.75 } }),
    ],
  });

  const travellingSlowly = runSession({
    hands: (atMs) => [
      handShape({ centre: { x: 0.5 + Math.sin((atMs / 1000) * Math.PI) * 0.25, y: 0.7 } }),
    ],
  });

  assert.ok(
    jitterInPlace.gesture.fidget_score! > 80,
    `busy-but-static should read as fidget, got ${jitterInPlace.gesture.fidget_score}`,
  );
  assert.ok(
    travellingSlowly.gesture.fidget_score! < 25,
    `a travelling stroke must not, got ${travellingSlowly.gesture.fidget_score}`,
  );
});

// ── Expressiveness ────────────────────────────────────────────────────────────

test("a face that changes scores higher expressiveness than a frozen one", () => {
  const frozen = createAggregator(OPTIONS);
  for (let at = 0; at < 60_000; at += FACE_STEP_MS) {
    frozen.addFaceSample({ ...faceSample(at), neutral: 0.9 });
  }
  const frozenScore = frozen.build({
    activeSeconds: 60,
    framesSeen: 600,
    framesAnalyzed: 600,
    faceAttempts: 600,
  }).expression.expressiveness!;

  const animated = createAggregator(OPTIONS);
  for (let at = 0; at < 60_000; at += FACE_STEP_MS) {
    // Neutral drifting between blank and highly active.
    animated.addFaceSample({
      ...faceSample(at),
      neutral: 0.5 + Math.sin((at / 1000) * Math.PI) * 0.4,
    });
  }
  const animatedScore = animated.build({
    activeSeconds: 60,
    framesSeen: 600,
    framesAnalyzed: 600,
    faceAttempts: 600,
  }).expression.expressiveness!;

  assert.ok(
    animatedScore > frozenScore,
    `animated (${animatedScore}) should beat frozen (${frozenScore})`,
  );
  // A permanently animated face is not the same as an expressive one — variance, not mean.
  assert.ok(frozenScore < 10, `a constant face should score near zero, got ${frozenScore}`);
});
