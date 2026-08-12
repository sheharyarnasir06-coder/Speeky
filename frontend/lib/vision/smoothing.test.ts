/**
 * Run with: npm run test:unit
 *
 * The filtering layer is where "percentages are frame-weighted, events are dwell-gated" is
 * actually implemented, and it is easy to collapse the two by accident. Most of these tests
 * exist to keep that distinction from eroding.
 */

import test from "node:test";
import assert from "node:assert/strict";

import {
  Ema,
  EpisodeDetector,
  ExcursionDetector,
  SchmittTrigger,
  dominantAxis,
} from "./smoothing";

// ── EMA ───────────────────────────────────────────────────────────────────────

test("first sample passes through unchanged", () => {
  assert.equal(new Ema(200).push(7, 0), 7);
});

test("EMA converges toward a step without overshooting", () => {
  const ema = new Ema(100);
  ema.push(0, 0);
  let value = 0;
  for (let t = 20; t <= 1000; t += 20) value = ema.push(10, t);
  assert.ok(value > 9.9 && value <= 10, `expected convergence to 10, got ${value}`);
});

test("smoothing is frame-rate independent", () => {
  // The same elapsed time at different sample rates must land in the same place — otherwise a
  // slow laptop and a fast one score identical head movement differently.
  const fast = new Ema(100);
  fast.push(0, 0);
  let fastValue = 0;
  for (let t = 10; t <= 500; t += 10) fastValue = fast.push(10, t);

  const slow = new Ema(100);
  slow.push(0, 0);
  let slowValue = 0;
  for (let t = 50; t <= 500; t += 50) slowValue = slow.push(10, t);

  assert.ok(
    Math.abs(fastValue - slowValue) < 0.05,
    `rate-dependent smoothing: fast=${fastValue} slow=${slowValue}`,
  );
});

test("a long gap resets rather than interpolating across it", () => {
  // A hidden tab or lost detection must not produce invented motion when sampling resumes.
  const ema = new Ema(100);
  ema.push(0, 0);
  const afterGap = ema.push(10, 10_000);
  assert.equal(afterGap, 10);
});

test("reset clears history", () => {
  const ema = new Ema(100);
  ema.push(5, 0);
  ema.reset();
  assert.equal(ema.current, null);
  assert.equal(ema.push(99, 10), 99);
});

// ── Schmitt trigger ───────────────────────────────────────────────────────────

test("trigger enters high and exits low", () => {
  const trigger = new SchmittTrigger(0.35, 0.2);
  assert.equal(trigger.push(0.3), false);
  assert.equal(trigger.push(0.4), true);
  assert.equal(trigger.push(0.25), true, "must stay active between the two thresholds");
  assert.equal(trigger.push(0.15), false);
});

test("a signal sitting on the threshold does not chatter", () => {
  const trigger = new SchmittTrigger(0.35, 0.2);
  let flips = 0;
  let previous = false;
  // Dither around the enter threshold, as a real noisy landmark signal does.
  for (let i = 0; i < 200; i += 1) {
    const state = trigger.push(0.35 + (i % 2 === 0 ? 0.01 : -0.01));
    if (state !== previous) flips += 1;
    previous = state;
  }
  assert.equal(flips, 1, `expected one transition, got ${flips}`);
});

test("an inverted trigger is rejected at construction", () => {
  assert.throws(() => new SchmittTrigger(0.2, 0.5), /must not exceed/);
});

// ── Episode detection ─────────────────────────────────────────────────────────

/** Feed a state across a span, sampling every 50ms. */
function feed(detector: EpisodeDetector, active: boolean, fromMs: number, toMs: number) {
  for (let t = fromMs; t < toMs; t += 50) detector.push(active, t);
  detector.push(active, toMs);
}

test("a brief glance is not an episode but still accrues time", () => {
  // THE distinction: 300ms away lowers the percentage, but is not a "look away".
  const detector = new EpisodeDetector(700);
  feed(detector, true, 0, 300);
  feed(detector, false, 300, 1000);

  const summary = detector.summary();
  assert.equal(summary.count, 0, "300ms must not count as an episode");
  assert.ok(summary.totalMs >= 300, "but the time must still be counted");
});

test("a sustained span is an episode", () => {
  const detector = new EpisodeDetector(700);
  feed(detector, true, 0, 2000);
  feed(detector, false, 2000, 2500);

  const summary = detector.summary();
  assert.equal(summary.count, 1);
  assert.ok(summary.longestMs >= 2000);
});

test("refractory prevents one event being counted twice", () => {
  const detector = new EpisodeDetector(300, 1000);
  feed(detector, true, 0, 800);
  feed(detector, false, 800, 900); // brief dip mid-event
  feed(detector, true, 900, 1700);
  feed(detector, false, 1700, 2000);

  assert.equal(detector.summary().count, 1, "the dip must not split one event into two");
});

test("episodes separated by more than the refractory window both count", () => {
  const detector = new EpisodeDetector(300, 500);
  feed(detector, true, 0, 800);
  feed(detector, false, 800, 3000);
  feed(detector, true, 3000, 3800);
  feed(detector, false, 3800, 4000);

  assert.equal(detector.summary().count, 2);
});

test("mean episode length ignores sub-dwell spans", () => {
  const detector = new EpisodeDetector(500);
  feed(detector, true, 0, 1000); // counts
  feed(detector, false, 1000, 2000);
  feed(detector, true, 2000, 2100); // too short
  feed(detector, false, 2100, 3000);

  const summary = detector.summary();
  assert.equal(summary.count, 1);
  assert.ok(summary.meanMs !== null && summary.meanMs >= 1000);
});

test("summary with no activity is zero, not null", () => {
  const summary = new EpisodeDetector(500).summary();
  assert.equal(summary.count, 0);
  assert.equal(summary.totalMs, 0);
  assert.equal(summary.meanMs, null, "mean of nothing is null, not 0");
});

test("reset discards an open span without recording it", () => {
  const detector = new EpisodeDetector(300);
  feed(detector, true, 0, 2000);
  detector.reset(); // detection lost — the end time is unknown
  detector.push(false, 2500);
  assert.equal(detector.summary().count, 0);
});

// ── Excursion detection (nods, shakes, gesture strokes) ───────────────────────

/** Simulate a there-and-back excursion of `amplitude` over `durationMs`. */
function excursion(
  detector: ExcursionDetector,
  amplitude: number,
  durationMs: number,
  startMs: number,
): number {
  let fired = 0;
  const steps = Math.max(4, Math.round(durationMs / 25));
  for (let i = 0; i <= steps; i += 1) {
    const phase = (i / steps) * Math.PI;
    const value = amplitude * Math.sin(phase);
    if (detector.push(value, startMs + (i / steps) * durationMs)) fired += 1;
  }
  return fired;
}

test("a well-formed excursion fires once", () => {
  const detector = new ExcursionDetector(6, 250, 900);
  detector.push(0, 0);
  assert.equal(excursion(detector, 12, 500, 100), 1);
});

test("a too-shallow movement does not fire", () => {
  const detector = new ExcursionDetector(6, 250, 900);
  detector.push(0, 0);
  assert.equal(excursion(detector, 2, 500, 100), 0);
});

test("a slow postural drift is not an excursion", () => {
  // Same amplitude as a nod, but over 4 seconds — this is leaning, not nodding.
  const detector = new ExcursionDetector(6, 250, 900);
  detector.push(0, 0);
  assert.equal(excursion(detector, 12, 4000, 100), 0);
});

test("refractory suppresses an immediate repeat", () => {
  const detector = new ExcursionDetector(6, 250, 900, 1000);
  detector.push(0, 0);
  excursion(detector, 12, 400, 100);
  excursion(detector, 12, 400, 600); // inside the refractory window
  assert.equal(detector.total, 1);
});

// ── Axis dominance ────────────────────────────────────────────────────────────

test("a nod is pitch-dominant and a lean is not", () => {
  assert.equal(dominantAxis({ yaw: 1, pitch: 12, roll: 2 }), "pitch");
  // A lean moves roll at least as much as pitch — this is what rejects it as a nod.
  assert.equal(dominantAxis({ yaw: 2, pitch: 8, roll: 14 }), "roll");
  assert.equal(dominantAxis({ yaw: 20, pitch: 3, roll: 1 }), "yaw");
});
