/**
 * Run with: npm run test:unit
 *
 * The pose half of the aggregator: posture, sway, pose-tier gesture, movement, framing.
 *
 * Nearly every test here turns on one question — does an unmeasurable body produce `null`, or a
 * confident zero? A cropped torso, wrists below the laptop lid, a lost detection: each has an
 * obvious wrong answer that looks entirely plausible in the UI.
 */

import test from "node:test";
import assert from "node:assert/strict";

import { createAggregator, type FaceSample } from "./aggregator";
import { calibrateFromTargets, type CalibrationSample } from "./gaze";
import type { HeadPose, IrisOffset } from "./headPose";
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
  modelVersions: { face: "face_landmarker/float16/1", pose: "pose_landmarker_lite/float16/1" },
  userAgentHint: "chrome-desktop",
  calibration: calibrateFromTargets(hold(0, 0, 0), hold(0, -4, 0.24)),
};

const FACE_STEP_MS = 100; // 10Hz
const POSE_STEP_MS = 167; // ~6Hz, matching the tier table

function faceSample(atMs: number, overrides: Partial<FaceSample> = {}): FaceSample {
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
    ...overrides,
  };
}

function feedFace(
  aggregator: ReturnType<typeof createAggregator>,
  fromMs: number,
  seconds: number,
): number {
  let atMs = fromMs;
  for (const end = fromMs + seconds * 1000; atMs < end; atMs += FACE_STEP_MS) {
    aggregator.addFaceSample(faceSample(atMs));
  }
  return atMs;
}

/** Shoulder width 150px against a 640px frame is ~0.23 — inside the healthy framing band. */
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

function feedPose(
  aggregator: ReturnType<typeof createAggregator>,
  fromMs: number,
  seconds: number,
  overrides: Partial<PoseFrame> | ((atMs: number) => Partial<PoseFrame>) = {},
): number {
  let atMs = fromMs;
  for (const end = fromMs + seconds * 1000; atMs < end; atMs += POSE_STEP_MS) {
    const patch = typeof overrides === "function" ? overrides(atMs) : overrides;
    aggregator.addPoseSample({ atMs, detected: true, frame: poseFrame(patch) });
  }
  return atMs;
}

function build(aggregator: ReturnType<typeof createAggregator>, seconds: number, extra = {}) {
  const faceAttempts = Math.round((seconds * 1000) / FACE_STEP_MS);
  return aggregator.build({
    activeSeconds: seconds,
    framesSeen: faceAttempts,
    framesAnalyzed: faceAttempts,
    faceAttempts,
    poseAttempts: Math.round((seconds * 1000) / POSE_STEP_MS),
    ...extra,
  });
}

/** A session with both streams running steadily for `seconds`. */
function steadySession(seconds = 60) {
  const aggregator = createAggregator(OPTIONS);
  feedFace(aggregator, 0, seconds);
  feedPose(aggregator, 0, seconds);
  return aggregator;
}

// ── Happy path ────────────────────────────────────────────────────────────────

test("a steady upright body scores posture and reports good framing", () => {
  const features = build(steadySession(), 60);

  assert.ok(features.posture.score !== null);
  assert.ok(features.posture.upright_pct! > 90, `got ${features.posture.upright_pct}`);
  assert.equal(features.quality.framing, "good");
  assert.ok(features.quality.pose_detected_pct! > 90);
  assert.ok(features.quality.achieved_pose_hz! > 5);
});

test("the posture baseline is frozen after the opening window", () => {
  // Upright while the baseline is fitted, slouched thereafter. If the baseline kept adapting,
  // the slouch would quietly become "normal" and disappear from the metrics entirely.
  const aggregator = createAggregator(OPTIONS);
  feedFace(aggregator, 0, 60);
  const at = feedPose(aggregator, 0, 12, { headLift: 0.55 });
  feedPose(aggregator, at, 48, { headLift: 0.4 });

  const features = build(aggregator, 60);
  assert.ok(
    features.posture.slouch_pct! > 50,
    `slouch should dominate, got ${features.posture.slouch_pct}`,
  );
});

// ── Absent is not zero ────────────────────────────────────────────────────────

test("a cropped torso nulls posture without touching the face metrics", () => {
  const aggregator = createAggregator(OPTIONS);
  feedFace(aggregator, 0, 60);
  feedPose(aggregator, 0, 60, { shoulderWidthPx: null, midpoint: null });

  const features = build(aggregator, 60);

  assert.equal(features.posture.score, null, "must be null, never 0");
  assert.equal(features.posture.upright_pct, null);
  assert.ok(features.gaze.on_camera_pct !== null, "gaze is unaffected by a cropped torso");
  assert.equal(features.quality.framing, "shoulders_cropped");
});

test("hands out of frame null the gesture family rather than reporting zero gestures", () => {
  const aggregator = createAggregator(OPTIONS);
  feedFace(aggregator, 0, 60);
  feedPose(aggregator, 0, 60, {
    leftWrist: null,
    rightWrist: null,
    wristsVisible: 0,
    handsBelowFrame: true,
  });

  const features = build(aggregator, 60);

  assert.equal(features.gesture.count, null, "the whole point: not 0");
  assert.equal(features.gesture.rate_per_min, null);
  assert.ok(features.unavailable_reasons.includes("hands_out_of_frame"));
  assert.ok(features.posture.score !== null, "the torso was visible; posture survives");
});

test("a motionless speaker scores zero gestures, because the hands WERE visible", () => {
  // The mirror image of the test above. Here 0 is the correct answer and must not be
  // suppressed into null by an over-eager gate — that would hide a real coaching point.
  const features = build(steadySession(), 60);

  assert.equal(features.gesture.count, 0);
  assert.ok(features.gesture.hands_visible_pct! > 90);
});

test("pose never enabled is distinct from pose that never detected", () => {
  const neverEnabled = createAggregator(OPTIONS);
  feedFace(neverEnabled, 0, 60);
  const a = neverEnabled.build({
    activeSeconds: 60,
    framesSeen: 600,
    framesAnalyzed: 600,
    faceAttempts: 600,
    poseAttempts: 0,
  });
  assert.ok(a.unavailable_reasons.includes("pose_not_enabled"));
  assert.equal(a.quality.pose_detected_pct, null, "never enabled means unmeasured, not 0%");

  const neverDetected = createAggregator(OPTIONS);
  feedFace(neverDetected, 0, 60);
  for (let at = 0; at < 60_000; at += POSE_STEP_MS) {
    neverDetected.addPoseSample({ atMs: at, detected: false, frame: null });
  }
  const b = build(neverDetected, 60);
  assert.equal(b.quality.pose_detected_pct, 0, "enabled but never detected IS 0%");
  assert.ok(b.unavailable_reasons.some((r) => r.startsWith("pose_coverage_")));
});

test("a pose gap does not fabricate stillness in the timeline", () => {
  const aggregator = createAggregator(OPTIONS);
  feedFace(aggregator, 0, 60);
  let at = feedPose(aggregator, 0, 20);
  for (; at < 40_000; at += POSE_STEP_MS) {
    aggregator.addPoseSample({ atMs: at, detected: false, frame: null });
  }
  feedPose(aggregator, at, 20);

  const { timeline } = build(aggregator, 60);
  const middle = timeline.posture.slice(25, 35);
  assert.ok(
    middle.every((v) => v === null),
    "bins with no pose data must be null, not a posture score",
  );
});

// ── Movement ──────────────────────────────────────────────────────────────────

test("gesture strokes are detected and reported in shoulder widths", () => {
  const aggregator = createAggregator(OPTIONS);
  feedFace(aggregator, 0, 60);
  const at = feedPose(aggregator, 0, 12);
  // ~0.5Hz raise-and-lower of the right hand, well above the stroke threshold.
  feedPose(aggregator, at, 48, (atMs) => ({
    rightWrist: { dx: 0.6, dy: 1.0 - Math.max(0, Math.sin((atMs / 1000) * Math.PI)) * 0.8 },
  }));

  const features = build(aggregator, 60);

  assert.ok(features.gesture.count! > 0, "strokes should be detected");
  assert.ok(features.gesture.mean_amplitude !== null);
  assert.ok(features.gesture.symmetry !== null);
});

test("one-handed gesturing is detected while the other hand rests", () => {
  /**
   * Regression guard. Detection originally ran on `max(left, right)` amplitude, which meant a
   * hand resting at a constant distance pinned the signal at its own value and hid every stroke
   * the other hand made. Most gesturing is one-handed, so this failed on the common case while
   * passing on the rare symmetric one.
   */
  const aggregator = createAggregator(OPTIONS);
  feedFace(aggregator, 0, 60);
  const at = feedPose(aggregator, 0, 12);
  feedPose(aggregator, at, 48, (atMs) => ({
    // Left hand dead still at its resting position; right hand strokes.
    leftWrist: { dx: -0.6, dy: 1.0 },
    rightWrist: { dx: 0.6, dy: 1.0 - Math.max(0, Math.sin((atMs / 1000) * Math.PI)) * 0.8 },
  }));

  const features = build(aggregator, 60);

  assert.ok(features.gesture.count! > 5, `expected repeated strokes, got ${features.gesture.count}`);
  // ...and the imbalance should show up as low symmetry rather than being averaged away.
  assert.ok(
    features.gesture.symmetry! < 0.5,
    `one-handed gesturing should read as asymmetric, got ${features.gesture.symmetry}`,
  );
});

test("hand percentages are not diluted by the baseline window", () => {
  // Hand counters only accrue after the baseline closes, so dividing by every detected pose
  // frame understates visibility — badly on a short session, where the baseline is most of it.
  const aggregator = createAggregator(OPTIONS);
  feedFace(aggregator, 0, 30);
  feedPose(aggregator, 0, 30);

  const features = build(aggregator, 30);
  assert.ok(
    features.gesture.hands_visible_pct! > 95,
    `hands were visible throughout, got ${features.gesture.hands_visible_pct}`,
  );
});

test("sway is measured in shoulder widths and reversals are counted", () => {
  const aggregator = createAggregator(OPTIONS);
  feedFace(aggregator, 0, 60);
  const at = feedPose(aggregator, 0, 12);
  feedPose(aggregator, at, 48, (atMs) => ({
    midpoint: { x: 0.5 + Math.sin((atMs / 1000) * Math.PI) * 0.05, y: 0.6 },
  }));

  const features = build(aggregator, 60);
  assert.ok(features.posture.sway_amplitude! > 0);
  assert.ok(features.posture.sway_rate_per_min! > 0, "direction reversals should be counted");
});

test("a still speaker is not reported as swaying", () => {
  const features = build(steadySession(), 60);
  assert.ok(
    (features.posture.sway_amplitude ?? 0) < 0.05,
    `a motionless torso should barely sway, got ${features.posture.sway_amplitude}`,
  );
});

// ── Framing ───────────────────────────────────────────────────────────────────

test("sitting far off to one side is reported as off-centre", () => {
  const aggregator = createAggregator(OPTIONS);
  feedFace(aggregator, 0, 60);
  feedPose(aggregator, 0, 60, { midpoint: { x: 0.12, y: 0.6 } });

  assert.equal(build(aggregator, 60).quality.framing, "off_center");
});

test("filling the frame is reported as too close", () => {
  const aggregator = createAggregator(OPTIONS);
  feedFace(aggregator, 0, 60);
  feedPose(aggregator, 0, 60, { shoulderWidthPx: 400 });

  assert.equal(build(aggregator, 60).quality.framing, "too_close");
});

test("a brief lean out of shot does not condemn the whole session's framing", () => {
  const aggregator = createAggregator(OPTIONS);
  feedFace(aggregator, 0, 60);
  const at = feedPose(aggregator, 0, 55);
  feedPose(aggregator, at, 5, { midpoint: { x: 0.1, y: 0.6 } });

  assert.equal(build(aggregator, 60).quality.framing, "good");
});

test("framing_override is only waived when the check genuinely could not run", () => {
  // With pose running, "unknown" means the body was never seen — a real failure, not an
  // un-runnable check, so the session must not be silently waived through.
  const withPose = build(steadySession(), 60);
  assert.equal(withPose.quality.framing_override, false);

  const noPose = createAggregator(OPTIONS);
  feedFace(noPose, 0, 60);
  const features = noPose.build({
    activeSeconds: 60,
    framesSeen: 600,
    framesAnalyzed: 600,
    faceAttempts: 600,
    poseAttempts: 0,
  });
  assert.equal(features.quality.framing_override, true);
});

// ── Tier passthrough ──────────────────────────────────────────────────────────

test("the degradation tier is carried through to the payload", () => {
  const features = build(steadySession(), 60, { degradationTier: "low", tierChanges: 2 });
  assert.equal(features.quality.degradation_tier, "low");
  assert.equal(features.quality.tier_changes, 2);
});
