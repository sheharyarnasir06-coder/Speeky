/**
 * Run with: npm run test:unit
 *
 * The centrepiece is `staring at the lens separates cleanly from reading desk notes` — the
 * plan's phase 2 go/no-go, simulated. It cannot replace the real check with a human and a
 * webcam (calibration is inherently about a specific person at a specific camera position), but
 * it does prove the geometry is right: given plausible head poses and iris offsets for the two
 * behaviours, the classifier must put them in different buckets by a wide margin.
 *
 * The rest guard the failure this metric is famous for: scoring an attentive user as absent
 * because the camera sits above the screen.
 */

import test from "node:test";
import assert from "node:assert/strict";

import {
  NO_CALIBRATION,
  calibrateFromSessionMode,
  calibrateFromTargets,
  classifyGaze,
  gazeAngles,
  type CalibrationSample,
  type GazeBucket,
} from "./gaze";
import type { HeadPose, IrisOffset } from "./headPose";

const pose = (yaw: number, pitch: number, roll = 0): HeadPose => ({ yaw, pitch, roll });
const iris = (dx: number, dy: number): IrisOffset => ({ dx, dy, disagreement: 0 });

/** Jittery repeats of one head/eye position, as a real hold produces. */
function hold(
  yaw: number,
  pitch: number,
  irisDx: number,
  irisDy: number,
  count = 20,
  jitter = 0.6,
): CalibrationSample[] {
  return Array.from({ length: count }, (_, i) => {
    const wobble = ((i % 5) - 2) * jitter;
    return {
      pose: pose(yaw + wobble * 0.5, pitch + wobble),
      iris: iris(irisDx, irisDy + wobble * 0.002),
    };
  });
}

/**
 * A realistic setup: webcam above the screen. Looking at the lens is the user's neutral
 * (0 pitch). Looking at the on-screen panel is ~10 degrees below it, mostly with the eyes.
 */
const AT_LENS = hold(0, 0, 0, 0);
const AT_PANEL = hold(0, -4, 0, 0.24);

function bucketsFor(samples: CalibrationSample[], calibration = calibrateFromTargets(AT_LENS, AT_PANEL)) {
  return samples.map((s) => classifyGaze(gazeAngles(s.pose, s.iris, calibration), calibration));
}

function share(buckets: GazeBucket[], target: GazeBucket): number {
  return (buckets.filter((b) => b === target).length / buckets.length) * 100;
}

// ── The go/no-go ──────────────────────────────────────────────────────────────

test("staring at the lens separates cleanly from reading desk notes", () => {
  const calibration = calibrateFromTargets(AT_LENS, AT_PANEL);
  assert.equal(calibration.method, "on_screen_target");
  assert.equal(calibration.quality, "good");

  // Desk notes: head clearly dropped AND eyes clearly down.
  const atNotes = hold(0, -32, 0, 0.42);

  const lensBuckets = bucketsFor(AT_LENS, calibration);
  const notesBuckets = bucketsFor(atNotes, calibration);

  const onCamera = share(lensBuckets, "on_camera");
  const down = share(notesBuckets, "down");

  assert.ok(onCamera > 85, `staring at the lens should read as on-camera, got ${onCamera}%`);
  assert.ok(down > 70, `reading desk notes should read as down, got ${down}%`);
  assert.equal(share(notesBuckets, "on_camera"), 0, "desk notes must never read as eye contact");
});

test("watching the on-screen panel is not counted as reading notes", () => {
  // The whole reason the second calibration target exists. Without it these two collapse.
  const buckets = bucketsFor(AT_PANEL);
  const onScreen = share(buckets, "on_screen");
  assert.ok(onScreen > 70, `panel gaze should read as on-screen, got ${onScreen}%`);
  assert.equal(share(buckets, "down"), 0, "panel gaze must not be reported as looking down");
});

// ── The failure this metric is famous for ────────────────────────────────────

test("an attentive user is not scored as absent because the camera sits high", () => {
  // Camera mounted well above the screen: the user's neutral head pose is 14 degrees below it.
  const highCamera = hold(0, 0, 0, 0);
  const calibration = calibrateFromTargets(
    highCamera.map((s) => ({ pose: pose(s.pose.yaw, s.pose.pitch + 14), iris: s.iris })),
    AT_PANEL.map((s) => ({ pose: pose(s.pose.yaw, s.pose.pitch + 14), iris: s.iris })),
  );

  // Now the user looks at the lens again. In raw terms that is pitch 14 — which an uncalibrated
  // threshold would call "looking up and away".
  const buckets = hold(0, 14, 0, 0).map((s) =>
    classifyGaze(gazeAngles(s.pose, s.iris, calibration), calibration),
  );
  assert.ok(share(buckets, "on_camera") > 85, "calibration must absorb the camera offset");
});

test("eyes moving without the head is detected", () => {
  // Head dead still, eyes far to the side — head-pose-only gaze would call this eye contact.
  const calibration = calibrateFromTargets(AT_LENS, AT_PANEL);
  const headStillEyesAway = classifyGaze(
    gazeAngles(pose(0, 0), iris(0.42, 0), calibration),
    calibration,
  );
  assert.notEqual(headStillEyesAway, "on_camera", "iris displacement must break eye contact");
});

test("without the iris term the same sample is wrongly scored", () => {
  // Documents exactly what the iris buys, and fails if the term is ever dropped.
  const calibration = calibrateFromTargets(AT_LENS, AT_PANEL);
  const withoutIris = classifyGaze(
    gazeAngles(pose(0, 0), iris(0.42, 0), calibration, /* irisUsable */ false),
    calibration,
  );
  assert.equal(withoutIris, "on_camera");
});

// ── Tolerance behaviour ───────────────────────────────────────────────────────

test("a fidgety user gets a wider cone, not a false negative", () => {
  const steady = calibrateFromTargets(hold(0, 0, 0, 0, 20, 0.2), AT_PANEL);
  const fidgety = calibrateFromTargets(hold(0, 0, 0, 0, 20, 3), AT_PANEL);

  assert.ok(
    (fidgety.pitchToleranceDeg ?? 0) > (steady.pitchToleranceDeg ?? 0),
    "jitter should widen the tolerance",
  );
  assert.ok((fidgety.pitchToleranceDeg ?? 0) <= 15, "but never without bound");
  assert.ok((steady.pitchToleranceDeg ?? 0) >= 6, "and never tighter than the floor");
});

test("excessive jitter downgrades quality rather than producing a confident cone", () => {
  const unusable = calibrateFromTargets(hold(0, 0, 0, 0, 20, 20), AT_PANEL);
  assert.equal(unusable.quality, "weak");
  assert.notEqual(unusable.method, "on_screen_target");
});

test("too few samples cannot claim a good calibration", () => {
  const thin = calibrateFromTargets(hold(0, 0, 0, 0, 3), AT_PANEL);
  assert.equal(thin.quality, "weak");
});

/**
 * The acceptance floors were loosened after real-camera testing, where calibration failed far
 * too readily and forced a manual retry. These two pin the new behaviour so a future tidy-up
 * doesn't quietly tighten it back and reintroduce the complaint.
 */
test("an ordinary, slightly restless hold still calibrates", () => {
  // ~12 degrees of wobble: a normal person holding still, not a statue. This used to fail.
  const restless = calibrateFromTargets(hold(0, 0, 0, 0, 40, 5), AT_PANEL);

  assert.equal(restless.quality, "good", "a normal hold must not be downgraded");
  assert.equal(restless.method, "on_screen_target");
  // The proportionate penalty is a wider cone, not a rejection.
  assert.ok((restless.pitchToleranceDeg ?? 0) > 6);
});

test("a restless user's wider cone never swallows the screen offset", () => {
  /**
   * The failure this guards: widening the cone for a fidgety user is correct, but taken far
   * enough it absorbs the measured lens-to-panel gap, and then watching the on-screen panel
   * scores as full eye contact. That inflates on_camera_pct for precisely the users whose data
   * deserves the least confidence.
   */
  // A realistic screen offset (~12 degrees below the lens) with a very restless user.
  const panel = hold(0, -12, 0, 0.24, 40, 5);
  const calibration = calibrateFromTargets(hold(0, 0, 0, 0, 40, 5), panel);

  assert.ok(calibration.screenOffsetPitchDeg !== null);
  assert.ok(
    (calibration.pitchToleranceDeg ?? 99) < Math.abs(calibration.screenOffsetPitchDeg!),
    `cone ${calibration.pitchToleranceDeg} must stay inside the ${calibration.screenOffsetPitchDeg} offset`,
  );

  // ...and the two must still land in different buckets.
  const atLens = bucketsFor(hold(0, 0, 0, 0), calibration);
  const atPanel = bucketsFor(panel, calibration);
  assert.ok(share(atLens, "on_camera") > 80, `lens: ${share(atLens, "on_camera")}%`);
  assert.equal(share(atPanel, "on_camera"), 0, "panel gaze must never read as lens contact");
});

test("an unseparable screen offset is dropped rather than faked", () => {
  // Camera almost in line with the panel: the cone floor is wider than the gap, so the two
  // genuinely cannot be told apart. Claiming otherwise would be a fabricated distinction.
  const calibration = calibrateFromTargets(AT_LENS, hold(0, -2, 0, 0.05));

  assert.equal(calibration.screenOffsetPitchDeg, null);
  assert.notEqual(calibration.method, "on_screen_target");
});

test("a short hold still calibrates as long as the samples are clean", () => {
  // Detection dropouts can leave a hold thin even when what survived is perfectly good.
  const short = calibrateFromTargets(hold(0, 0, 0, 0, 6, 0.4), AT_PANEL);

  assert.equal(short.performed, true);
  assert.notEqual(short.quality, "failed");
  assert.ok(short.baselinePitchDeg !== null);
});

test("no samples at all is a failure, not a guess", () => {
  const failed = calibrateFromTargets([], []);
  assert.equal(failed.performed, false);
  assert.equal(failed.method, "none");
  assert.equal(failed.quality, "failed");
});

test("a camera-only calibration cannot claim the screen target", () => {
  const cameraOnly = calibrateFromTargets(AT_LENS, []);
  assert.equal(cameraOnly.method, "session_baseline");
  assert.equal(cameraOnly.screenOffsetPitchDeg, null);
  assert.notEqual(cameraOnly.quality, "good");
});

// ── Iris gain fitting ─────────────────────────────────────────────────────────

test("iris gain is fitted from the two targets when the eyes actually moved", () => {
  const calibration = calibrateFromTargets(AT_LENS, AT_PANEL);
  assert.ok(calibration.irisGainDegPerUnit !== null);
  assert.ok(
    calibration.irisGainDegPerUnit! > 2 && calibration.irisGainDegPerUnit! < 120,
    `implausible fitted gain: ${calibration.irisGainDegPerUnit}`,
  );
});

test("a degenerate fit falls back instead of dividing by noise", () => {
  // Eyes did not move between the targets — the user turned their whole head.
  const headOnly = hold(0, -12, 0, 0);
  const calibration = calibrateFromTargets(AT_LENS, headOnly);
  assert.equal(calibration.irisGainDegPerUnit, 25, "should fall back to the default gain");
});

// ── Session-mode fallback ─────────────────────────────────────────────────────

test("session-mode calibration removes static bias but stays weak", () => {
  // User sitting consistently off-axis, with occasional look-aways.
  const samples = [...hold(12, -6, 0, 0, 60), ...hold(40, -30, 0, 0, 10)];
  const calibration = calibrateFromSessionMode(samples);

  assert.equal(calibration.method, "session_baseline");
  assert.equal(calibration.quality, "weak");
  assert.equal(calibration.performed, false, "an inferred baseline is not a performed calibration");
  assert.ok(Math.abs((calibration.baselineYawDeg ?? 0) - 12) <= 2, "mode should find the habitual pose");
  assert.ok(Math.abs((calibration.baselinePitchDeg ?? 0) + 6) <= 2);
});

test("session-mode is not fooled by a long look-away", () => {
  // More time spent away than at any single other pose, but the mode is still the habitual one.
  const samples = [...hold(0, 0, 0, 0, 40), ...hold(30, -25, 0, 0, 30)];
  const calibration = calibrateFromSessionMode(samples);
  assert.ok(Math.abs(calibration.baselineYawDeg ?? 99) <= 2);
});

test("too few samples cannot produce a session baseline", () => {
  assert.equal(calibrateFromSessionMode(hold(0, 0, 0, 0, 3)).method, "none");
});

// ── Bucketing edges ───────────────────────────────────────────────────────────

test("a large yaw is offscreen, not merely sideways", () => {
  const calibration = calibrateFromTargets(AT_LENS, AT_PANEL);
  assert.equal(classifyGaze({ yaw: 60, pitch: 0 }, calibration), "offscreen");
  assert.equal(classifyGaze({ yaw: 25, pitch: 0 }, calibration), "side");
});

test("with no calibration at all, classification still returns a bucket", () => {
  // Must degrade, not throw — an uncalibrated session is still recorded, just discounted.
  const bucket = classifyGaze(gazeAngles(pose(3, 2), iris(0, 0), NO_CALIBRATION), NO_CALIBRATION);
  assert.equal(bucket, "on_camera");
});

test("up and down are distinguished", () => {
  const calibration = calibrateFromTargets(AT_LENS, AT_PANEL);
  assert.equal(classifyGaze({ yaw: 0, pitch: 30 }, calibration), "up");
  assert.equal(classifyGaze({ yaw: 0, pitch: -30 }, calibration), "down");
});
