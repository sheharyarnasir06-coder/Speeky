/**
 * Finger-level gesture geometry, from the 21-landmark hand model.
 *
 * This is the *hand tier*, and it is strictly additive over the pose tier in
 * metrics/posture.ts. Gesture count, rate, amplitude and symmetry all come from pose wrists and
 * survive when the degradation ladder switches this model off; only the signals below are lost.
 * Keeping that split is what makes the ladder viable on weak devices.
 *
 * Everything is derived geometrically rather than classified. MediaPipe ships a
 * `GestureRecognizer` with a canned eight-class head (Thumb_Up, Victory, Open_Palm...), but it
 * is built for emblematic gestures — nobody delivers a talk in thumbs-ups — and it costs an
 * extra model download for a label we would ignore. Extension and curl are simple to compute
 * from the landmarks we already have, and simple to explain back to a user.
 *
 * Pure and synchronous — no React, no DOM.
 */

import { distancePx, type FrameSize, type Landmark } from "../normalize";

/**
 * Hand landmark indices. Each finger runs base -> tip.
 *
 * MediaPipe reports handedness from the *image's* perspective, so its "Left" is the user's
 * right hand. Anything that surfaces left/right in coaching copy must swap; anything symmetric
 * (a count, a mean) must not. See `userHandFromImage`.
 */
export const HAND = {
  wrist: 0,
  thumbMcp: 2,
  thumbIp: 3,
  thumbTip: 4,
  indexMcp: 5,
  indexPip: 6,
  indexTip: 8,
  middleMcp: 9,
  middlePip: 10,
  middleTip: 12,
  ringMcp: 13,
  ringPip: 14,
  ringTip: 16,
  pinkyMcp: 17,
  pinkyPip: 18,
  pinkyTip: 20,
} as const;

export type FingerName = "index" | "middle" | "ring" | "pinky";

const FINGERS: Record<FingerName, { mcp: number; pip: number; tip: number }> = {
  index: { mcp: HAND.indexMcp, pip: HAND.indexPip, tip: HAND.indexTip },
  middle: { mcp: HAND.middleMcp, pip: HAND.middlePip, tip: HAND.middleTip },
  ring: { mcp: HAND.ringMcp, pip: HAND.ringPip, tip: HAND.ringTip },
  pinky: { mcp: HAND.pinkyMcp, pip: HAND.pinkyPip, tip: HAND.pinkyTip },
};

/** Image-space handedness to the user's own. Call this once, at the boundary. */
export function userHandFromImage(imageLabel: string): "left" | "right" {
  return imageLabel.toLowerCase().startsWith("l") ? "right" : "left";
}

export interface HandShape {
  /** Which of the user's hands this is, already swapped from image space. */
  side: "left" | "right";
  extended: Record<FingerName, boolean>;
  extendedCount: number;
  /** All four fingers extended and spread — the open, receptive gesture. */
  openPalm: boolean;
  /** Index extended with the rest curled. */
  pointing: boolean;
  /** Every finger curled. */
  fist: boolean;
  /** Palm centre in normalised coordinates, for proximity tests. */
  centre: Landmark;
  /** Hand size in pixels (wrist to middle MCP), the scale reference for this hand. */
  scalePx: number;
}

/**
 * Is a finger extended?
 *
 * Compares tip-to-wrist against pip-to-wrist distance rather than using absolute angles, which
 * makes it invariant to hand size, camera distance, and how the hand is rotated toward the
 * lens. A curled finger brings its tip back toward the wrist, so the ratio drops below 1.
 */
function isExtended(landmarks: Landmark[], finger: { pip: number; tip: number }, frame: FrameSize) {
  const wrist = landmarks[HAND.wrist];
  const pip = landmarks[finger.pip];
  const tip = landmarks[finger.tip];
  if (!wrist || !pip || !tip) return false;

  const tipDistance = distancePx(tip, wrist, frame);
  const pipDistance = distancePx(pip, wrist, frame);
  if (pipDistance <= 0) return false;

  // 1.15 rather than 1.0: a relaxed, slightly-curved finger still reads as extended, which
  // matches what a viewer would call an open hand.
  return tipDistance / pipDistance > 1.15;
}

export function readHandShape(
  landmarks: Landmark[],
  imageHandedness: string,
  frame: FrameSize,
): HandShape | null {
  const wrist = landmarks[HAND.wrist];
  const middleMcp = landmarks[HAND.middleMcp];
  if (!wrist || !middleMcp) return null;

  const scalePx = distancePx(wrist, middleMcp, frame);
  if (scalePx <= 0) return null;

  const extended = {
    index: isExtended(landmarks, FINGERS.index, frame),
    middle: isExtended(landmarks, FINGERS.middle, frame),
    ring: isExtended(landmarks, FINGERS.ring, frame),
    pinky: isExtended(landmarks, FINGERS.pinky, frame),
  };
  const extendedCount = Object.values(extended).filter(Boolean).length;

  return {
    side: userHandFromImage(imageHandedness),
    extended,
    extendedCount,
    openPalm: extendedCount === 4,
    // Pointing is index-only. Requiring the others curled is what separates it from a raised
    // open hand, which is a completely different signal.
    pointing: extended.index && !extended.middle && !extended.ring && !extended.pinky,
    fist: extendedCount === 0,
    centre: { x: (wrist.x + middleMcp.x) / 2, y: (wrist.y + middleMcp.y) / 2 },
    scalePx,
  };
}

/**
 * Is this hand touching or near the face?
 *
 * Threshold is in face-scale units (outer eye-corner distance), so it means the same thing at
 * any camera distance. 1.2 inter-ocular widths from the face centre is close enough to read as
 * touching without firing every time a gesture passes in front of the chest.
 */
export function isNearFace(
  hand: HandShape,
  faceCentre: Landmark | null,
  faceScalePx: number | null,
  frame: FrameSize,
): boolean {
  if (!faceCentre || faceScalePx === null || faceScalePx <= 0) return false;
  return distancePx(hand.centre, faceCentre, frame) / faceScalePx < 1.2;
}

/**
 * Are the two hands clasped together?
 *
 * Distinct from crossed arms: clasping holds the hands close in front of the body, which reads
 * as closed or nervous, whereas crossed arms puts each wrist past the opposite side of the
 * torso. Both are measured, and conflating them would produce contradictory coaching.
 */
export function areHandsClasped(
  left: HandShape | null,
  right: HandShape | null,
  frame: FrameSize,
): boolean {
  if (!left || !right) return false;
  const separation = distancePx(left.centre, right.centre, frame);
  const scale = (left.scalePx + right.scalePx) / 2;
  return scale > 0 && separation / scale < 1.5;
}
