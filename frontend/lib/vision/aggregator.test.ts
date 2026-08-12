/**
 * Run with: npm run test:unit
 *
 * End-to-end over the pure path: synthetic face samples in, a full `video_features` payload out.
 * The assertions concentrate on the two invariants that make the whole feature trustworthy —
 * absent never reads as zero, and percentages stay frame-weighted while events stay dwell-gated.
 */

import test from "node:test";
import assert from "node:assert/strict";

import { createAggregator, type FaceSample } from "./aggregator";
import type { PoseFrame } from "./metrics/posture";
import { calibrateFromTargets, type CalibrationSample } from "./gaze";
import type { HeadPose, IrisOffset } from "./headPose";

const pose = (yaw: number, pitch: number, roll = 0): HeadPose => ({ yaw, pitch, roll });
const iris = (dx = 0, dy = 0): IrisOffset => ({ dx, dy, disagreement: 0 });

function hold(yaw: number, pitch: number, dy: number, count = 20): CalibrationSample[] {
  return Array.from({ length: count }, (_, i) => {
    const wobble = ((i % 5) - 2) * 0.6;
    return { pose: pose(yaw + wobble * 0.5, pitch + wobble), iris: iris(0, dy) };
  });
}

const CALIBRATION = calibrateFromTargets(hold(0, 0, 0), hold(0, -4, 0.24));

const OPTIONS = {
  videoWidth: 640,
  videoHeight: 480,
  modelVersions: { face: "face_landmarker/float16/1" },
  userAgentHint: "chrome-desktop",
  calibration: CALIBRATION,
};

/** 10Hz sampling, matching the scheduler's phase-1 cadence. */
const STEP_MS = 100;

function sample(atMs: number, overrides: Partial<FaceSample> = {}): FaceSample {
  return {
    atMs,
    detected: true,
    pose: pose(0, 0),
    iris: iris(),
    smile: 0,
    blink: 0,
    browRaise: 0,
    jawOpen: 0,
    neutral: 0.9,
    ...overrides,
  };
}

/** Feed a steady state for `seconds`, returning the timestamp reached. */
function feed(
  aggregator: ReturnType<typeof createAggregator>,
  fromMs: number,
  seconds: number,
  overrides: Partial<FaceSample> | ((atMs: number) => Partial<FaceSample>) = {},
): number {
  let atMs = fromMs;
  const end = fromMs + seconds * 1000;
  for (; atMs < end; atMs += STEP_MS) {
    const patch = typeof overrides === "function" ? overrides(atMs) : overrides;
    aggregator.addFaceSample(sample(atMs, patch));
  }
  return atMs;
}

function buildAfter(aggregator: ReturnType<typeof createAggregator>, seconds: number, extra = {}) {
  const attempts = Math.round((seconds * 1000) / STEP_MS);
  return aggregator.build({
    activeSeconds: seconds,
    framesSeen: attempts,
    framesAnalyzed: attempts,
    faceAttempts: attempts,
    ...extra,
  });
}

// ── Happy path ────────────────────────────────────────────────────────────────

test("a clean 60s session of eye contact scores high and is marked ok", () => {
  const aggregator = createAggregator(OPTIONS);
  feed(aggregator, 0, 60);
  const features = buildAfter(aggregator, 60);

  assert.equal(features.status, "ok");
  assert.ok(features.gaze.on_camera_pct! > 90, `got ${features.gaze.on_camera_pct}`);
  assert.equal(features.gaze.away_episodes, 0);
  assert.equal(features.calibration.method, "on_screen_target");
  assert.equal(features.schema_version, 1);
});

test("timeline channels are all the same length and face_present is populated", () => {
  const aggregator = createAggregator(OPTIONS);
  feed(aggregator, 0, 30);
  const { timeline } = buildAfter(aggregator, 30);

  const lengths = [
    timeline.eye_contact,
    timeline.posture,
    timeline.gesture_activity,
    timeline.smile,
    timeline.movement,
    timeline.face_present,
  ].map((channel) => channel.length);

  assert.equal(new Set(lengths).size, 1, `channels disagree: ${lengths}`);
  assert.equal(lengths[0], timeline.length);
  assert.ok(timeline.face_present.every((v) => v === 1));
});

// ── Frame-weighted vs dwell-gated ─────────────────────────────────────────────

test("a brief glance away lowers the percentage but is not an episode", () => {
  const aggregator = createAggregator(OPTIONS);
  let at = feed(aggregator, 0, 30);
  // 300ms looking at the desk — a glance, not a lapse.
  at = feed(aggregator, at, 0.3, { pose: pose(0, -32), iris: iris(0, 0.42) });
  feed(aggregator, at, 29.7);

  const features = buildAfter(aggregator, 60);

  assert.equal(features.gaze.away_episodes, 0, "300ms must not be an episode");
  assert.ok(features.gaze.on_camera_pct! < 100, "but it must still cost percentage");
  assert.ok(features.gaze.down_pct! > 0);
});

test("a sustained look away is an episode and its length is reported", () => {
  const aggregator = createAggregator(OPTIONS);
  let at = feed(aggregator, 0, 20);
  at = feed(aggregator, at, 5, { pose: pose(0, -32), iris: iris(0, 0.42) });
  feed(aggregator, at, 35);

  const features = buildAfter(aggregator, 60);

  assert.equal(features.gaze.away_episodes, 1);
  assert.ok(
    features.gaze.longest_away_seconds! >= 4.5 && features.gaze.longest_away_seconds! <= 5.5,
    `expected ~5s, got ${features.gaze.longest_away_seconds}`,
  );
});

// ── Absent is not zero ────────────────────────────────────────────────────────

test("poor face coverage nulls the metrics rather than reporting zeros", () => {
  const aggregator = createAggregator(OPTIONS);
  // Detected only one frame in five.
  feed(aggregator, 0, 60, (atMs) => (atMs % 500 === 0 ? {} : { detected: false, pose: null }));

  const features = buildAfter(aggregator, 60);

  assert.ok(features.quality.face_detected_pct! < 60);
  assert.equal(features.gaze.on_camera_pct, null, "must be null, not 0");
  assert.equal(features.expression.smile_pct, null);
  assert.ok(features.unavailable_reasons.some((r) => r.startsWith("face_coverage_")));
});

test("pose and gesture blocks stay null until their models are wired", () => {
  const aggregator = createAggregator(OPTIONS);
  feed(aggregator, 0, 60);
  const features = buildAfter(aggregator, 60);

  assert.equal(features.posture.score, null);
  assert.equal(features.gesture.count, null, "must be null — nobody measured the hands");
  assert.equal(features.movement.energy, null);
  assert.ok(features.unavailable_reasons.includes("pose_not_enabled"));
  assert.ok(features.unavailable_reasons.includes("hands_not_enabled"));
});

test("a session that is too short is insufficient_data", () => {
  const aggregator = createAggregator(OPTIONS);
  feed(aggregator, 0, 10);
  assert.equal(buildAfter(aggregator, 10).status, "insufficient_data");
});

test("an empty session does not throw and reports nothing", () => {
  const aggregator = createAggregator(OPTIONS);
  const features = aggregator.build({
    activeSeconds: 0,
    framesSeen: 0,
    framesAnalyzed: 0,
    faceAttempts: 0,
  });

  assert.equal(features.status, "insufficient_data");
  assert.equal(features.gaze.on_camera_pct, null);
  assert.equal(features.timeline.length, 0);
});

test("an early stop is reported as partial, keeping what was measured", () => {
  const aggregator = createAggregator(OPTIONS);
  feed(aggregator, 0, 40);
  const features = buildAfter(aggregator, 40, { earlyStop: true });

  assert.equal(features.status, "partial");
  assert.ok(features.gaze.on_camera_pct !== null, "partial data is still data");
  assert.ok(features.unavailable_reasons.includes("camera_stopped_early"));
});

// ── Detection gaps ────────────────────────────────────────────────────────────

test("a detection gap does not fabricate an away episode", () => {
  const aggregator = createAggregator(OPTIONS);
  let at = feed(aggregator, 0, 25, { pose: pose(0, -32), iris: iris(0, 0.42) });
  // Face lost mid-look-away: the end of that span is unknowable, so it must not be recorded.
  at = feed(aggregator, at, 5, { detected: false, pose: null });
  feed(aggregator, at, 30);

  const features = buildAfter(aggregator, 60);
  assert.equal(features.gaze.away_episodes, 0, "an unterminated span must be discarded");
});

// ── Expression ────────────────────────────────────────────────────────────────

test("smiles are counted as events, not as frames", () => {
  const aggregator = createAggregator(OPTIONS);
  let at = feed(aggregator, 0, 10);
  at = feed(aggregator, at, 3, { smile: 0.8 }); // one sustained smile
  at = feed(aggregator, at, 10);
  at = feed(aggregator, at, 0.2, { smile: 0.8 }); // a flicker, below the dwell
  feed(aggregator, at, 36.8);

  const features = buildAfter(aggregator, 60);
  assert.equal(features.expression.smile_events, 1);
  assert.ok(features.expression.smile_pct! > 0);
});

test("blink rate is withheld when the sampling rate is too low to measure it", () => {
  const aggregator = createAggregator(OPTIONS);
  feed(aggregator, 0, 60, (atMs) => ({ blink: Math.floor(atMs / 300) % 2 === 0 ? 0.9 : 0 }));

  // 10Hz is under the 12Hz floor.
  const features = buildAfter(aggregator, 60);
  assert.equal(features.expression.blink_rate_reliable, false);
  assert.equal(features.expression.blink_rate_per_min, null, "unreliable rate must not be quoted");
  assert.ok(features.expression.blink_count! > 0, "the raw count is still recorded");
});

// ── Calibration passthrough ───────────────────────────────────────────────────

test("an uncalibrated session says so instead of guessing", () => {
  const aggregator = createAggregator({ ...OPTIONS, calibration: undefined });
  feed(aggregator, 0, 60);
  const features = buildAfter(aggregator, 60);

  assert.equal(features.calibration.method, "none");
  assert.equal(features.calibration.quality, "failed");
  assert.ok(features.unavailable_reasons.includes("gaze_uncalibrated"));
});

test("unreliable iris landmarks disable the gain rather than corrupting gaze", () => {
  const aggregator = createAggregator(OPTIONS);
  // Reflective glasses: the two eyes disagree wildly and consistently.
  feed(aggregator, 0, 60, { iris: { dx: 0.3, dy: 0.1, disagreement: 0.4 } });

  const features = buildAfter(aggregator, 60);
  assert.equal(features.calibration.iris_gain_deg_per_unit, null);
  assert.ok(features.unavailable_reasons.includes("iris_unreliable"));
});

// ── Consistency ───────────────────────────────────────────────────────────────

test("steady contact scores higher consistency than one stare plus one lapse", () => {
  const steady = createAggregator(OPTIONS);
  feed(steady, 0, 60);
  const steadyScore = buildAfter(steady, 60).gaze.eye_contact_consistency!;

  const lumpy = createAggregator(OPTIONS);
  let at = feed(lumpy, 0, 30);
  feed(lumpy, at, 30, { pose: pose(0, -32), iris: iris(0, 0.42) });
  const lumpyScore = buildAfter(lumpy, 60).gaze.eye_contact_consistency!;

  assert.ok(
    steadyScore > lumpyScore,
    `steady (${steadyScore}) should beat lumpy (${lumpyScore}) at equal-ish means`,
  );
});
