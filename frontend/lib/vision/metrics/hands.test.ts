/**
 * Run with: npm run test:unit
 *
 * Finger-level geometry. Two things get particular attention:
 *
 *  - the **image/user handedness swap**, because MediaPipe labels hands from the camera's
 *    perspective and getting it backwards leaves every count correct while every left/right
 *    sentence of coaching is wrong; and
 *  - **scale invariance**, since a hand near the lens and one at arm's length must classify the
 *    same way.
 */

import test from "node:test";
import assert from "node:assert/strict";

import {
  HAND,
  areHandsClasped,
  isNearFace,
  readHandShape,
  userHandFromImage,
  type HandShape,
} from "./hands";
import type { Landmark } from "../normalize";

const FRAME = { width: 640, height: 480 };

/**
 * Build a hand pointing "up" the frame, with each finger either extended or curled.
 *
 * The wrist sits at the bottom; MCP joints above it; PIP above those. An extended finger puts
 * its tip beyond the PIP, a curled one folds the tip back toward the wrist.
 */
function hand({
  extended = { index: true, middle: true, ring: true, pinky: true },
  x = 0.5,
  wristY = 0.8,
  scale = 1,
}: {
  extended?: Partial<Record<"index" | "middle" | "ring" | "pinky", boolean>>;
  x?: number;
  wristY?: number;
  scale?: number;
} = {}): Landmark[] {
  const landmarks: Landmark[] = new Array(21).fill(null).map(() => ({ x, y: wristY }));
  const up = (units: number) => wristY - units * 0.05 * scale;

  landmarks[HAND.wrist] = { x, y: wristY };
  landmarks[HAND.middleMcp] = { x, y: up(1) };
  landmarks[HAND.thumbTip] = { x: x - 0.04 * scale, y: up(1.2) };

  const fingers = [
    { name: "index", mcp: HAND.indexMcp, pip: HAND.indexPip, tip: HAND.indexTip, dx: -0.03 },
    { name: "middle", mcp: HAND.middleMcp, pip: HAND.middlePip, tip: HAND.middleTip, dx: -0.01 },
    { name: "ring", mcp: HAND.ringMcp, pip: HAND.ringPip, tip: HAND.ringTip, dx: 0.01 },
    { name: "pinky", mcp: HAND.pinkyMcp, pip: HAND.pinkyPip, tip: HAND.pinkyTip, dx: 0.03 },
  ] as const;

  for (const finger of fingers) {
    const fx = x + finger.dx * scale;
    landmarks[finger.mcp] = { x: fx, y: up(1) };
    landmarks[finger.pip] = { x: fx, y: up(1.8) };
    // Extended: tip continues past the PIP. Curled: tip folds back toward the wrist.
    landmarks[finger.tip] = extended[finger.name] ? { x: fx, y: up(2.8) } : { x: fx, y: up(1.1) };
  }

  return landmarks;
}

// ── Handedness ────────────────────────────────────────────────────────────────

test("image handedness is swapped to the user's own", () => {
  // MediaPipe's "Left" is the hand on the image's left, which is the user's RIGHT.
  assert.equal(userHandFromImage("Left"), "right");
  assert.equal(userHandFromImage("Right"), "left");
  assert.equal(userHandFromImage("left"), "right", "case must not matter");
});

test("readHandShape reports the user's side, not the image's", () => {
  assert.equal(readHandShape(hand(), "Left", FRAME)!.side, "right");
  assert.equal(readHandShape(hand(), "Right", FRAME)!.side, "left");
});

// ── Finger extension ──────────────────────────────────────────────────────────

test("an open palm has all four fingers extended", () => {
  const shape = readHandShape(hand(), "Right", FRAME)!;
  assert.equal(shape.extendedCount, 4);
  assert.equal(shape.openPalm, true);
  assert.equal(shape.pointing, false);
  assert.equal(shape.fist, false);
});

test("a fist has none extended", () => {
  const shape = readHandShape(
    hand({ extended: { index: false, middle: false, ring: false, pinky: false } }),
    "Right",
    FRAME,
  )!;
  assert.equal(shape.fist, true);
  assert.equal(shape.openPalm, false);
});

test("pointing requires the index alone", () => {
  const pointing = readHandShape(
    hand({ extended: { index: true, middle: false, ring: false, pinky: false } }),
    "Right",
    FRAME,
  )!;
  assert.equal(pointing.pointing, true);

  // Index AND middle is a different gesture entirely, and must not read as pointing.
  const two = readHandShape(
    hand({ extended: { index: true, middle: true, ring: false, pinky: false } }),
    "Right",
    FRAME,
  )!;
  assert.equal(two.pointing, false);

  // A raised open hand is not a point either.
  assert.equal(readHandShape(hand(), "Right", FRAME)!.pointing, false);
});

test("classification is scale-invariant", () => {
  // The same hand shape near the lens and at arm's length must classify identically.
  const near = readHandShape(hand({ scale: 2 }), "Right", FRAME)!;
  const far = readHandShape(hand({ scale: 0.5 }), "Right", FRAME)!;

  assert.equal(near.openPalm, far.openPalm);
  assert.equal(near.extendedCount, far.extendedCount);
  assert.ok(near.scalePx > far.scalePx, "but the reported scale should differ");
});

test("a malformed hand yields null rather than a bogus shape", () => {
  assert.equal(readHandShape([], "Right", FRAME), null);

  const degenerate = hand();
  degenerate[HAND.middleMcp] = { x: 0.5, y: 0.8 }; // zero-length hand
  assert.equal(readHandShape(degenerate, "Right", FRAME), null);
});

// ── Proximity ─────────────────────────────────────────────────────────────────

test("a hand at the face is detected, and one at the chest is not", () => {
  const faceCentre = { x: 0.5, y: 0.3 };
  const faceScale = 60; // px between outer eye corners

  const atFace = readHandShape(hand({ x: 0.5, wristY: 0.34 }), "Right", FRAME)!;
  assert.equal(isNearFace(atFace, faceCentre, faceScale, FRAME), true);

  const atChest = readHandShape(hand({ x: 0.5, wristY: 0.8 }), "Right", FRAME)!;
  assert.equal(isNearFace(atChest, faceCentre, faceScale, FRAME), false);
});

test("proximity means the same thing at any camera distance", () => {
  // Doubling the face scale doubles the allowed distance, so the same relative position holds.
  const near = readHandShape(hand({ x: 0.5, wristY: 0.34 }), "Right", FRAME)!;
  assert.equal(isNearFace(near, { x: 0.5, y: 0.3 }, 60, FRAME), true);

  const far = readHandShape(hand({ x: 0.5, wristY: 0.32 }), "Right", FRAME)!;
  assert.equal(isNearFace(far, { x: 0.5, y: 0.3 }, 30, FRAME), true);
});

test("no face position means no face-touch claim", () => {
  const shape = readHandShape(hand(), "Right", FRAME)!;
  assert.equal(isNearFace(shape, null, 60, FRAME), false);
  assert.equal(isNearFace(shape, { x: 0.5, y: 0.3 }, null, FRAME), false);
  assert.equal(isNearFace(shape, { x: 0.5, y: 0.3 }, 0, FRAME), false);
});

// ── Clasping ──────────────────────────────────────────────────────────────────

test("hands held together are clasped; hands apart are not", () => {
  const left = readHandShape(hand({ x: 0.48 }), "Right", FRAME)!;
  const right = readHandShape(hand({ x: 0.52 }), "Left", FRAME)!;
  assert.equal(areHandsClasped(left, right, FRAME), true);

  const spread = readHandShape(hand({ x: 0.85 }), "Left", FRAME)!;
  assert.equal(areHandsClasped(left, spread, FRAME), false);
});

test("clasping needs both hands", () => {
  const one = readHandShape(hand(), "Right", FRAME);
  assert.equal(areHandsClasped(one, null, FRAME), false);
  assert.equal(areHandsClasped(null, null, FRAME), false);
});

test("clasped and crossed are different signals", () => {
  /**
   * Clasping holds the hands close in front of the body; crossed arms (measured on the pose
   * tier, in metrics/posture.ts) puts each wrist past the opposite side of the torso. Both read
   * as closed, but conflating them would let one session report contradictory coaching.
   */
  // Named for the perspective they come from, because naming them "left"/"right" is exactly how
  // the swap gets lost — the label MediaPipe gives is the opposite of the user's own hand.
  const fromImageRight: HandShape = readHandShape(hand({ x: 0.49 }), "Right", FRAME)!;
  const fromImageLeft: HandShape = readHandShape(hand({ x: 0.51 }), "Left", FRAME)!;

  assert.equal(areHandsClasped(fromImageRight, fromImageLeft, FRAME), true);
  assert.equal(fromImageRight.side, "left", "image-right is the USER's left hand");
  assert.equal(fromImageLeft.side, "right");
});
