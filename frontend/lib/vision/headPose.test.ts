/**
 * Run with: npm run test:unit
 *
 * These exist because the matrix convention is otherwise unverifiable. Reading MediaPipe's
 * column-major transform as row-major transposes the rotation and swaps yaw with pitch — and
 * the result still looks like plausible head motion, so no amount of eyeballing a live preview
 * catches it. Constructing a rotation from known angles and asserting it round-trips is the
 * only check that actually pins it.
 */

import test from "node:test";
import assert from "node:assert/strict";

import { anglesFromMatrix, irisOffset, matrixFromAngles } from "./headPose";
import { FACE, type Landmark } from "./normalize";

const closeTo = (actual: number, expected: number, tolerance = 1e-6) =>
  assert.ok(
    Math.abs(actual - expected) < tolerance,
    `expected ${actual} to be within ${tolerance} of ${expected}`,
  );

test("identity matrix decodes to a level, forward-facing head", () => {
  const pose = anglesFromMatrix(matrixFromAngles({ yaw: 0, pitch: 0, roll: 0 }));
  assert.ok(pose);
  closeTo(pose.yaw, 0);
  closeTo(pose.pitch, 0);
  closeTo(pose.roll, 0);
});

test("each axis round-trips independently", () => {
  for (const angle of [-30, -12, -1, 1, 12, 30]) {
    const yawOnly = anglesFromMatrix(matrixFromAngles({ yaw: angle, pitch: 0, roll: 0 }))!;
    closeTo(yawOnly.yaw, angle, 1e-4);
    closeTo(yawOnly.pitch, 0, 1e-4);

    const pitchOnly = anglesFromMatrix(matrixFromAngles({ yaw: 0, pitch: angle, roll: 0 }))!;
    closeTo(pitchOnly.pitch, angle, 1e-4);
    closeTo(pitchOnly.yaw, 0, 1e-4);

    const rollOnly = anglesFromMatrix(matrixFromAngles({ yaw: 0, pitch: 0, roll: angle }))!;
    closeTo(rollOnly.roll, angle, 1e-4);
    closeTo(rollOnly.yaw, 0, 1e-4);
  }
});

test("combined rotations round-trip", () => {
  const original = { yaw: 17, pitch: -23, roll: 8 };
  const pose = anglesFromMatrix(matrixFromAngles(original))!;
  closeTo(pose.yaw, original.yaw, 1e-4);
  closeTo(pose.pitch, original.pitch, 1e-4);
  closeTo(pose.roll, original.roll, 1e-4);
});

/**
 * The decisive one. A transposed read swaps these two, and every "you looked down" message
 * silently becomes "you looked sideways".
 */
test("a nod is pitch and a head shake is yaw, not the reverse", () => {
  const nod = anglesFromMatrix(matrixFromAngles({ yaw: 0, pitch: -25, roll: 0 }))!;
  assert.ok(Math.abs(nod.pitch) > 20, `nod should register as pitch, got ${nod.pitch}`);
  assert.ok(Math.abs(nod.yaw) < 1, `nod must not register as yaw, got ${nod.yaw}`);

  const shake = anglesFromMatrix(matrixFromAngles({ yaw: 25, pitch: 0, roll: 0 }))!;
  assert.ok(Math.abs(shake.yaw) > 20, `shake should register as yaw, got ${shake.yaw}`);
  assert.ok(Math.abs(shake.pitch) < 1, `shake must not register as pitch, got ${shake.pitch}`);
});

test("reading the matrix row-major would be caught", () => {
  // Transpose the rotation submatrix — exactly the bug this file guards against.
  const correct = matrixFromAngles({ yaw: 20, pitch: -15, roll: 0 });
  const transposed = [...correct];
  for (let row = 0; row < 3; row += 1) {
    for (let col = row + 1; col < 3; col += 1) {
      const a = col * 4 + row;
      const b = row * 4 + col;
      [transposed[a], transposed[b]] = [transposed[b], transposed[a]];
    }
  }

  const good = anglesFromMatrix(correct)!;
  const bad = anglesFromMatrix(transposed)!;
  assert.notEqual(
    Math.round(good.yaw),
    Math.round(bad.yaw),
    "a transposed matrix must not decode to the same angles, or this test proves nothing",
  );
});

test("sign conventions match the documented ones", () => {
  // Positive pitch = looking up. The aggregator's gaze bucketing depends on this.
  const lookingUp = anglesFromMatrix(matrixFromAngles({ yaw: 0, pitch: 20, roll: 0 }))!;
  assert.ok(lookingUp.pitch > 0);

  const lookingDown = anglesFromMatrix(matrixFromAngles({ yaw: 0, pitch: -20, roll: 0 }))!;
  assert.ok(lookingDown.pitch < 0);
});

test("gimbal lock reports no phantom roll", () => {
  const pose = anglesFromMatrix(matrixFromAngles({ yaw: 90, pitch: 0, roll: 0 }))!;
  assert.equal(pose.roll, 0);
});

test("short or missing matrices return null rather than throwing", () => {
  assert.equal(anglesFromMatrix(null), null);
  assert.equal(anglesFromMatrix(undefined), null);
  assert.equal(anglesFromMatrix([]), null);
  assert.equal(anglesFromMatrix([1, 2, 3]), null);
});

// ── Iris ──────────────────────────────────────────────────────────────────────

/** Minimal landmark array with both eyes present and the iris placeable within each. */
function faceWithIris(irisFractionX: number, irisFractionY: number): Landmark[] {
  const landmarks: Landmark[] = new Array(478).fill(null).map(() => ({ x: 0, y: 0 }));

  // Image-left eye spans x 0.30..0.40, y 0.45..0.49 (inner at 0.30, outer at 0.40).
  landmarks[FACE.leftEyeInner] = { x: 0.3, y: 0.47 };
  landmarks[FACE.leftEyeOuter] = { x: 0.4, y: 0.47 };
  landmarks[FACE.leftEyeUpper] = { x: 0.35, y: 0.45 };
  landmarks[FACE.leftEyeLower] = { x: 0.35, y: 0.49 };
  landmarks[FACE.leftIris] = {
    x: 0.3 + 0.1 * irisFractionX,
    y: 0.45 + 0.04 * irisFractionY,
  };

  landmarks[FACE.rightEyeInner] = { x: 0.6, y: 0.47 };
  landmarks[FACE.rightEyeOuter] = { x: 0.7, y: 0.47 };
  landmarks[FACE.rightEyeUpper] = { x: 0.65, y: 0.45 };
  landmarks[FACE.rightEyeLower] = { x: 0.65, y: 0.49 };
  landmarks[FACE.rightIris] = {
    x: 0.6 + 0.1 * irisFractionX,
    y: 0.45 + 0.04 * irisFractionY,
  };

  return landmarks;
}

test("a centred iris reads as zero offset", () => {
  const offset = irisOffset(faceWithIris(0.5, 0.5))!;
  closeTo(offset.dx, 0, 1e-9);
  closeTo(offset.dy, 0, 1e-9);
  closeTo(offset.disagreement, 0, 1e-9);
});

test("iris displacement is signed the documented way", () => {
  // Toward the outer corner (larger x) => positive dx.
  assert.ok(irisOffset(faceWithIris(0.8, 0.5))!.dx > 0);
  assert.ok(irisOffset(faceWithIris(0.2, 0.5))!.dx < 0);
  // Toward the lower lid (larger y) => positive dy, i.e. looking down.
  assert.ok(irisOffset(faceWithIris(0.5, 0.9))!.dy > 0);
  assert.ok(irisOffset(faceWithIris(0.5, 0.1))!.dy < 0);
});

test("iris offset is scale-free", () => {
  // Same relative iris position, eye twice as wide: the ratio must not move.
  const small = irisOffset(faceWithIris(0.75, 0.5))!;
  const scaled = faceWithIris(0.75, 0.5);
  scaled[FACE.leftEyeOuter] = { x: 0.5, y: 0.47 };
  scaled[FACE.leftIris] = { x: 0.3 + 0.2 * 0.75, y: 0.47 };
  const large = irisOffset(scaled)!;
  closeTo(large.dx, small.dx, 1e-9);
});

test("disagreement rises when the two eyes report different offsets", () => {
  const landmarks = faceWithIris(0.5, 0.5);
  landmarks[FACE.leftIris] = { x: 0.3 + 0.1 * 0.9, y: 0.47 };
  const offset = irisOffset(landmarks)!;
  assert.ok(offset.disagreement > 0.1, `expected disagreement, got ${offset.disagreement}`);
});

test("a closed or missing eye yields null rather than a huge ratio", () => {
  const blinking = faceWithIris(0.5, 0.5);
  blinking[FACE.leftEyeUpper] = { x: 0.35, y: 0.47 };
  blinking[FACE.leftEyeLower] = { x: 0.35, y: 0.47 }; // zero opening
  assert.equal(irisOffset(blinking), null);

  assert.equal(irisOffset(null), null);
  assert.equal(irisOffset([]), null);
});
