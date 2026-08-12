"use client";

/**
 * Accumulates per-frame observations into the `video_features` payload.
 *
 * Pure and synchronous: everything enters through `addFaceSample` and leaves through `build`.
 * No React, no DOM, no timers — which is what makes it testable against synthetic samples and
 * lets a future move into a Web Worker be a transport change only.
 *
 * Two rules govern everything here:
 *
 * 1. **A metric is written only when it was actually measured.** Coverage below the family
 *    threshold nulls the family and records a reason. Absent is not zero, and once the two are
 *    conflated no consumer can recover the difference.
 * 2. **Percentages are frame-weighted; events are dwell-gated.** A 300ms glance lowers
 *    `on_camera_pct` but is not an `away_episode`. Both answer real questions, and the
 *    smoothing layer (smoothing.ts) is what keeps them distinct.
 *
 * Pose, gesture and movement stay null until phases 3 and 4 wire the other two landmarkers.
 */

import {
  IRIS_DISAGREEMENT_LIMIT,
  NO_CALIBRATION,
  classifyGaze,
  gazeAngles,
  type GazeBucket,
  type GazeCalibration,
} from "./gaze";
import type { HeadPose, IrisOffset } from "./headPose";
import { areHandsClasped, isNearFace, type HandShape } from "./metrics/hands";
import {
  BASELINE_WINDOW_MS,
  fitBaseline,
  gestureSymmetry,
  readHandActivity,
  readPosture,
  type PoseFrame,
  type PostureBaseline,
} from "./metrics/posture";
import { Ema, EpisodeDetector, ExcursionDetector, SchmittTrigger, dominantAxis } from "./smoothing";
import {
  MAX_VIDEO_TIMELINE_BINS,
  emptyVideoFeatures,
  type VideoFeatures,
  type VideoStatus,
} from "./types";

/** Below this fraction of its own attempts, a family reports nothing. Matches
 *  _FAMILY_COVERAGE_MIN_PCT in backend/lib/video_scorer.py. */
const FAMILY_COVERAGE_MIN_PCT = 60;

/** Session floors, mirroring the backend's. Checked here so the UI can explain itself without a
 *  round trip — but the backend re-derives them regardless, and its verdict wins. */
const SESSION_FACE_MIN_PCT = 50;
const MIN_DURATION_S = 20;
const MIN_FRAMES_ANALYZED = 100;

/** Blinks last 100-400ms; below this the rate is undersampled and must not be quoted. */
const BLINK_RELIABLE_MIN_HZ = 12;

const TARGET_BIN_SECONDS = 1;

/** Time constants, in ms. Gaze is damped hardest because iris landmarks are the noisiest input. */
const TAU_GAZE_MS = 150;
const TAU_BLENDSHAPE_MS = 80;

/** A look-away shorter than this is a glance, not a lapse. */
const AWAY_MIN_DWELL_MS = 700;
const SMILE_MIN_DWELL_MS = 600;
const SMILE_REFRACTORY_MS = 1000;

/** Gesture stroke geometry, in shoulder widths. A stroke must travel this far from rest and
 *  complete inside the window, which excludes both fidget and a slow arm reposition. */
const GESTURE_MIN_AMPLITUDE = 0.25;
const GESTURE_MIN_MS = 250;
const GESTURE_MAX_MS = 4000;
const GESTURE_REFRACTORY_MS = 400;

/** Arms must stay crossed this long before the time accrues — a hand passing across the body
 *  mid-gesture briefly satisfies the geometry. */
const ARMS_CROSSED_DWELL_MS = 1500;

/** Sway is meaningful only above this amplitude (shoulder widths); below it is breathing. */
const SWAY_FLOOR = 0.02;

/** A posture change held this long is a shift rather than a wobble. */
const POSTURE_SHIFT_DWELL_MS = 2000;

/** A hand must stay near the face this long to count as a touch — a gesture sweeping past the
 *  chin is not face-touching. */
const FACE_TOUCH_DWELL_MS = 500;
const FACE_TOUCH_REFRACTORY_MS = 1000;

/** Fidget is judged over windows this long — long enough to contain a full gesture stroke, so
 *  a stroke registers as travel-with-range rather than being chopped into fidget-sized pieces. */
const FIDGET_WINDOW_MS = 1000;
/** Total travel within a window, as a fraction of frame width, above which the hand is "busy". */
const FIDGET_MIN_PATH_RATIO = 0.08;
/** Extent covered within the window. Below this the hand went nowhere. */
const FIDGET_MAX_RANGE_RATIO = 0.12;

/** Hands clasped must hold, for the same reason crossed arms must. */
const HANDS_CLASPED_DWELL_MS = 1500;

/** Nod geometry: a there-and-back pitch excursion, fast enough not to be a postural drift. */
const NOD_MIN_AMPLITUDE_DEG = 6;
const NOD_MIN_MS = 250;
const NOD_MAX_MS = 900;
const NOD_REFRACTORY_MS = 400;

/** Consistency is measured over windows this long — long enough to be meaningful, short enough
 *  that a single lapse does not dominate. */
const CONSISTENCY_WINDOW_S = 10;

export interface FaceSample {
  /** Milliseconds since capture started. */
  atMs: number;
  detected: boolean;
  pose: HeadPose | null;
  iris: IrisOffset | null;
  /** Selected blendshape activations, 0..1. */
  smile: number | null;
  blink: number | null;
  browRaise: number | null;
  jawOpen: number | null;
  neutral: number | null;
  /** Face centre in normalised coordinates, and its scale in pixels. Carried so the hand tier
   *  can test proximity without a second landmark lookup — the two models run at different
   *  cadences, so the hand stream uses the most recent face position it has. */
  centre?: { x: number; y: number } | null;
  scalePx?: number | null;
}

export interface HandSample {
  /** Milliseconds since capture started. */
  atMs: number;
  /** Both hands, already resolved to the USER's left/right. Empty when none were detected. */
  hands: HandShape[];
}

export interface PoseSample {
  /** Milliseconds since capture started. */
  atMs: number;
  detected: boolean;
  frame: PoseFrame | null;
}

interface Bin {
  faceSeen: number;
  faceDetected: number;
  smileTotal: number;
  smileCount: number;
  onCamera: number;
  postureSeen: number;
  postureUpright: number;
  gestureActivity: number;
  gestureSamples: number;
  movement: number;
  movementSamples: number;
}

export interface AggregatorOptions {
  videoWidth: number;
  videoHeight: number;
  modelVersions: Partial<Record<"face" | "pose" | "hand", string>>;
  userAgentHint: string;
  /** Fitted by the camera-check flow. Absent means gaze is uncalibrated and the payload says so,
   *  which makes the backend fall back to its robust metric and discount the session. */
  calibration?: GazeCalibration;
}

export interface BuildInput {
  /** Analysis-active seconds from the scheduler — NOT wall clock. */
  activeSeconds: number;
  framesSeen: number;
  framesAnalyzed: number;
  faceAttempts: number;
  /** Hand inference attempts. 0 means the model was never enabled — distinct from enabled but
   *  never detecting a hand. */
  handAttempts?: number;
  /** Pose inference attempts. 0 means the model was never enabled — distinct from "enabled but
   *  never detected a body", which is a coverage failure rather than an absent family. */
  poseAttempts?: number;
  /** Set when capture ended abnormally (camera revoked, track ended). */
  earlyStop?: boolean;
  brightnessOk?: boolean | null;
  degradationTier?: VideoFeatures["quality"]["degradation_tier"];
  tierChanges?: number;
  framing?: VideoFeatures["quality"]["framing"];
  framingOverride?: boolean;
}

export function createAggregator(options: AggregatorOptions) {
  const calibration: GazeCalibration = options.calibration ?? NO_CALIBRATION;

  const bins: Bin[] = [];
  let binSeconds = TARGET_BIN_SECONDS;

  let faceSeen = 0;
  let faceDetected = 0;

  // Frame-weighted gaze buckets.
  const bucketCounts: Record<GazeBucket, number> = {
    on_camera: 0,
    on_screen: 0,
    down: 0,
    up: 0,
    side: 0,
    offscreen: 0,
  };

  // Dwell-gated away episodes, kept strictly separate from the counts above.
  const awayDetector = new EpisodeDetector(AWAY_MIN_DWELL_MS);
  let lastBucket: GazeBucket | null = null;
  let gazeShifts = 0;

  const yawEma = new Ema(TAU_GAZE_MS);
  const pitchEma = new Ema(TAU_GAZE_MS);
  const smileEma = new Ema(TAU_BLENDSHAPE_MS);

  const smileTrigger = new SchmittTrigger(0.35, 0.2);
  const smileDetector = new EpisodeDetector(SMILE_MIN_DWELL_MS, SMILE_REFRACTORY_MS);
  const blinkTrigger = new SchmittTrigger(0.5, 0.3);
  const nodDetector = new ExcursionDetector(
    NOD_MIN_AMPLITUDE_DEG,
    NOD_MIN_MS,
    NOD_MAX_MS,
    NOD_REFRACTORY_MS,
  );

  let smileFrames = 0;
  let smileTotal = 0;
  let smilePeak = 0;
  let neutralFrames = 0;
  let browRaiseFrames = 0;
  let mouthOpenFrames = 0;
  let blinkCount = 0;

  let nodCount = 0;
  let shakeCount = 0;

  // Iris reliability is a whole-session judgement: reflective lenses corrupt the landmarks
  // consistently, and one bad frame should not disable the iris term for the rest of a talk.
  let irisSamples = 0;
  let irisBadSamples = 0;

  let angularDeltaTotal = 0;
  let angularDeltaCount = 0;
  let lastPose: HeadPose | null = null;
  let lastSampleMs: number | null = null;

  let rollTotal = 0;
  let rollAbsTotal = 0;
  let rollCount = 0;

  // ── Pose state ──────────────────────────────────────────────────────────
  let poseSeen = 0;
  let poseDetected = 0;
  let torsoVisible = 0;
  // Frames that actually reached the scoring section — i.e. after the baseline window closed.
  // Hand percentages accrue here, so they must be divided by this and not by poseDetected,
  // which also counts the baseline window and would understate visibility by ~17% on a
  // one-minute session and far more on a short one.
  let scoredFrames = 0;

  // Continuous framing, derived from the pose stream rather than the one-off modal check —
  // people drift out of frame mid-session, and the payload should describe what actually
  // happened rather than what was true at setup.
  let framingOffCentre = 0;
  let framingTooClose = 0;
  let framingTooFar = 0;

  // The baseline is fitted once, from the opening window, then frozen. Continuously re-fitting
  // would let a slouch become "normal" and disappear from the metrics.
  const baselineFrames: PoseFrame[] = [];
  let baseline: PostureBaseline | null = null;

  let uprightFrames = 0;
  let slouchFrames = 0;
  const leanCounts = { forward: 0, back: 0, side: 0, neutral: 0 };
  let tiltTotal = 0;
  let tiltCount = 0;

  // Sway: lateral torso travel and direction reversals, in shoulder widths.
  let swayMin = Infinity;
  let swayMax = -Infinity;
  let swayReversals = 0;
  let swayDirection = 0;
  let lastLateral: number | null = null;

  const uprightTrigger = new SchmittTrigger(0.5, 0.5);
  const postureShiftDetector = new EpisodeDetector(POSTURE_SHIFT_DWELL_MS);
  const armsCrossedDetector = new EpisodeDetector(ARMS_CROSSED_DWELL_MS);

  // Gesture, pose tier (wrists only) — survives the hand model being switched off.
  const newGestureDetector = () =>
    new ExcursionDetector(
      GESTURE_MIN_AMPLITUDE,
      GESTURE_MIN_MS,
      GESTURE_MAX_MS,
      GESTURE_REFRACTORY_MS,
    );
  // One detector per hand. Feeding a combined max() signal instead would let a resting hand
  // pin the amplitude at its own constant value and hide every one-handed gesture — which is
  // most gesturing.
  const gestureDetectors = { left: newGestureDetector(), right: newGestureDetector() };
  let gestureCount = 0;
  let amplitudeTotal = 0;
  let amplitudeCount = 0;
  let amplitudePeak = 0;
  let leftTravel = 0;
  let rightTravel = 0;
  let twoHandedFrames = 0;
  let handsVisibleFrames = 0;
  let handsBelowFrameCount = 0;
  let lastWrists: { left: number | null; right: number | null } | null = null;

  // ── Hand tier (finger-level) ────────────────────────────────────────────
  let handSeen = 0;
  let handDetected = 0;
  let openPalmFrames = 0;
  let pointingEvents = 0;
  let wasPointing = false;
  let handShapeFrames = 0;
  const faceTouchDetector = new EpisodeDetector(FACE_TOUCH_DWELL_MS, FACE_TOUCH_REFRACTORY_MS);
  const claspedDetector = new EpisodeDetector(HANDS_CLASPED_DWELL_MS);

  /**
   * Fidget: movement that goes nowhere.
   *
   * Judged per one-second window on **path length versus range**, not on per-sample amplitude.
   * Amplitude alone cannot separate the two cases, because a broad sweeping gesture moves
   * slowly near its turning points and spends much of its time in the same instantaneous speed
   * band as a jitter. What actually distinguishes them is that a gesture *travels* — high path
   * length AND high range — while a fidget covers the same small patch over and over.
   */
  let fidgetWindows = 0;
  let fidgetActiveWindows = 0;
  let windowPath = 0;
  let windowMin = Infinity;
  let windowMax = -Infinity;
  let windowStartedMs: number | null = null;
  let lastHandCentres: { left: number | null; right: number | null } = { left: null, right: null };

  // Most recent face position, for hand-to-face proximity across the cadence gap.
  let lastFaceCentre: { x: number; y: number } | null = null;
  let lastFaceScalePx: number | null = null;

  // Expressiveness: how much the face moved away from neutral over the session. Variance
  // rather than mean, because a permanently animated face and a permanently blank one are both
  // low-information; it is the *changes* that read as expressive.
  let nonNeutralTotal = 0;
  let nonNeutralSquareTotal = 0;
  let nonNeutralCount = 0;

  // Movement energy: combined torso and wrist travel per second.
  let movementTotal = 0;
  let movementCount = 0;
  let lastMidpointX: number | null = null;
  let lastPoseAtMs: number | null = null;

  // Per-window on-camera fractions, for eye_contact_consistency.
  const consistencyWindows: { onCamera: number; total: number }[] = [];

  function windowFor(atMs: number) {
    const index = Math.floor(atMs / 1000 / CONSISTENCY_WINDOW_S);
    while (consistencyWindows.length <= index) consistencyWindows.push({ onCamera: 0, total: 0 });
    return consistencyWindows[index];
  }

  function binFor(atMs: number): Bin {
    let index = Math.floor(atMs / 1000 / binSeconds);

    // Long sessions halve their resolution rather than exceed the server-side cap.
    while (index >= MAX_VIDEO_TIMELINE_BINS) {
      for (let i = 0; i < Math.ceil(bins.length / 2); i += 1) {
        const a = bins[i * 2];
        const b = bins[i * 2 + 1];
        bins[i] = {
          faceSeen: a.faceSeen + (b?.faceSeen ?? 0),
          faceDetected: a.faceDetected + (b?.faceDetected ?? 0),
          smileTotal: a.smileTotal + (b?.smileTotal ?? 0),
          smileCount: a.smileCount + (b?.smileCount ?? 0),
          onCamera: a.onCamera + (b?.onCamera ?? 0),
          postureSeen: a.postureSeen + (b?.postureSeen ?? 0),
          postureUpright: a.postureUpright + (b?.postureUpright ?? 0),
          gestureActivity: a.gestureActivity + (b?.gestureActivity ?? 0),
          gestureSamples: a.gestureSamples + (b?.gestureSamples ?? 0),
          movement: a.movement + (b?.movement ?? 0),
          movementSamples: a.movementSamples + (b?.movementSamples ?? 0),
        };
      }
      bins.length = Math.ceil(bins.length / 2);
      binSeconds *= 2;
      index = Math.floor(atMs / 1000 / binSeconds);
    }

    while (bins.length <= index) {
      bins.push({
        faceSeen: 0,
        faceDetected: 0,
        smileTotal: 0,
        smileCount: 0,
        onCamera: 0,
        postureSeen: 0,
        postureUpright: 0,
        gestureActivity: 0,
        gestureSamples: 0,
        movement: 0,
        movementSamples: 0,
      });
    }
    return bins[index];
  }

  /** Detection lost: drop filter state so nothing is interpolated across the gap. */
  function onDetectionLost(atMs: number) {
    yawEma.reset();
    pitchEma.reset();
    smileEma.reset();
    smileTrigger.reset();
    blinkTrigger.reset();
    nodDetector.reset();
    // The end of an open away-span is unknown, so discard it rather than inventing a duration.
    awayDetector.reset();
    smileDetector.reset();
    lastPose = null;
    lastSampleMs = null;
    lastBucket = null;
    void atMs;
  }

  function addFaceSample(sample: FaceSample) {
    faceSeen += 1;
    const bin = binFor(sample.atMs);
    const window = windowFor(sample.atMs);
    bin.faceSeen += 1;

    if (!sample.detected || !sample.pose) {
      onDetectionLost(sample.atMs);
      return;
    }

    faceDetected += 1;
    bin.faceDetected += 1;
    window.total += 1;

    if (sample.iris) {
      irisSamples += 1;
      if (sample.iris.disagreement > IRIS_DISAGREEMENT_LIMIT) irisBadSamples += 1;
    }

    // ── Gaze ────────────────────────────────────────────────────────────────
    const angles = gazeAngles(sample.pose, sample.iris, calibration, irisCurrentlyUsable());
    const smoothed = {
      yaw: yawEma.push(angles.yaw, sample.atMs),
      pitch: pitchEma.push(angles.pitch, sample.atMs),
    };
    const bucket = classifyGaze(smoothed, calibration);
    bucketCounts[bucket] += 1;

    if (bucket === "on_camera") {
      bin.onCamera += 1;
      window.onCamera += 1;
    }

    // "Away" means not engaged with camera or screen. Frame-weighted percentages come from
    // bucketCounts above; this detector only produces the dwell-gated episode stats.
    const away = bucket !== "on_camera" && bucket !== "on_screen";
    awayDetector.push(away, sample.atMs);

    if (lastBucket !== null && bucket !== lastBucket) gazeShifts += 1;
    lastBucket = bucket;

    // ── Head ────────────────────────────────────────────────────────────────
    const { yaw, pitch, roll } = sample.pose;
    if (lastPose && lastSampleMs !== null) {
      const dt = (sample.atMs - lastSampleMs) / 1000;
      if (dt > 0 && dt < 1) {
        const deltas = {
          yaw: yaw - lastPose.yaw,
          pitch: pitch - lastPose.pitch,
          roll: roll - lastPose.roll,
        };
        angularDeltaTotal +=
          (Math.abs(deltas.yaw) + Math.abs(deltas.pitch) + Math.abs(deltas.roll)) / dt;
        angularDeltaCount += 1;

        // A nod is a pitch excursion that is *pitch-dominant*. A lean moves pitch too, but moves
        // roll or yaw at least as much — the axis check is what keeps them apart.
        if (nodDetector.push(pitch, sample.atMs)) {
          if (dominantAxis(deltas) === "pitch") nodCount += 1;
          else shakeCount += 1;
        }
      }
    }
    lastPose = sample.pose;
    lastSampleMs = sample.atMs;

    rollTotal += roll;
    rollAbsTotal += Math.abs(roll);
    rollCount += 1;

    // ── Expression ──────────────────────────────────────────────────────────
    if (sample.smile !== null) {
      const smoothedSmile = smileEma.push(sample.smile, sample.atMs);
      const smiling = smileTrigger.push(smoothedSmile);
      smileDetector.push(smiling, sample.atMs);
      if (smiling) {
        smileFrames += 1;
        smileTotal += smoothedSmile;
        bin.smileTotal += smoothedSmile;
        bin.smileCount += 1;
      }
      smilePeak = Math.max(smilePeak, sample.smile);
    }

    if (sample.centre) lastFaceCentre = sample.centre;
    if (sample.scalePx != null) lastFaceScalePx = sample.scalePx;

    if (sample.neutral !== null) {
      const nonNeutral = 1 - sample.neutral;
      nonNeutralTotal += nonNeutral;
      nonNeutralSquareTotal += nonNeutral * nonNeutral;
      nonNeutralCount += 1;
      if (sample.neutral >= 0.5) neutralFrames += 1;
    }
    if (sample.browRaise !== null && sample.browRaise >= 0.3) browRaiseFrames += 1;
    if (sample.jawOpen !== null && sample.jawOpen >= 0.15) mouthOpenFrames += 1;

    if (sample.blink !== null) {
      const wasClosed = blinkTrigger.state;
      const closed = blinkTrigger.push(sample.blink);
      if (closed && !wasClosed) blinkCount += 1;
    }
  }

  /**
   * Feed one pose observation. Runs at a lower cadence than the face model (6Hz vs 15Hz), which
   * is why every rate here is derived from the elapsed time between samples rather than assumed.
   */
  function addPoseSample(sample: PoseSample) {
    poseSeen += 1;
    const bin = binFor(sample.atMs);

    if (!sample.detected || !sample.frame) {
      // Drop open spans: the end of a posture or crossed-arms span is unknowable once the body
      // is lost, and inventing a duration is worse than losing the span.
      postureShiftDetector.reset();
      armsCrossedDetector.reset();
      gestureDetectors.left.reset();
      gestureDetectors.right.reset();
      lastMidpointX = null;
      lastWrists = null;
      lastPoseAtMs = null;
      return;
    }

    poseDetected += 1;
    const frame = sample.frame;

    // Shoulders are the gate for the entire posture family — see metrics/posture.ts.
    const torsoOk = frame.shoulderWidthPx !== null && frame.midpoint !== null;
    if (torsoOk) torsoVisible += 1;

    // Shoulder width as a fraction of frame width is the distance proxy. ~0.18-0.45 is a
    // healthy head-and-shoulders framing; outside it the landmarks degrade.
    if (torsoOk && options.videoWidth > 0) {
      const widthRatio = (frame.shoulderWidthPx as number) / options.videoWidth;
      if (widthRatio > 0.45) framingTooClose += 1;
      else if (widthRatio < 0.18) framingTooFar += 1;
      const centreX = (frame.midpoint as { x: number }).x;
      if (centreX < 0.25 || centreX > 0.75) framingOffCentre += 1;
    }

    // Collect the opening window, then freeze the baseline.
    if (baseline === null) {
      if (sample.atMs <= BASELINE_WINDOW_MS) {
        if (torsoOk) baselineFrames.push(frame);
        return;
      }
      baseline = fitBaseline(baselineFrames);
      if (baseline === null) return; // never saw enough body to establish "normal"
    }

    if (!torsoOk) return;
    scoredFrames += 1;

    // ── Posture ───────────────────────────────────────────────────────────
    const posture = readPosture(frame, baseline, {
      width: options.videoWidth,
      height: options.videoHeight,
    });
    bin.postureSeen += 1;

    if (posture.upright) {
      uprightFrames += 1;
      bin.postureUpright += 1;
    }
    if (posture.slouching) slouchFrames += 1;
    leanCounts[posture.lean] += 1;

    if (posture.tiltDeg !== null) {
      tiltTotal += posture.tiltDeg;
      tiltCount += 1;
    }

    // A sustained departure from upright is a posture shift; a wobble is not.
    postureShiftDetector.push(!uprightTrigger.push(posture.upright ? 0 : 1), sample.atMs);

    // ── Sway ──────────────────────────────────────────────────────────────
    if (posture.lateralOffset !== null) {
      swayMin = Math.min(swayMin, posture.lateralOffset);
      swayMax = Math.max(swayMax, posture.lateralOffset);

      if (lastLateral !== null) {
        const delta = posture.lateralOffset - lastLateral;
        if (Math.abs(delta) > SWAY_FLOOR) {
          const direction = Math.sign(delta);
          if (swayDirection !== 0 && direction !== swayDirection) swayReversals += 1;
          swayDirection = direction;
        }
      }
      lastLateral = posture.lateralOffset;
    }

    // ── Gesture (pose tier) ───────────────────────────────────────────────
    const hands = readHandActivity(frame);
    if (frame.handsBelowFrame) handsBelowFrameCount += 1;
    if (frame.wristsVisible > 0) handsVisibleFrames += 1;
    if (frame.wristsVisible === 2) twoHandedFrames += 1;

    armsCrossedDetector.push(frame.armsCrossed, sample.atMs);

    if (hands.amplitude !== null) {
      amplitudeTotal += hands.amplitude;
      amplitudeCount += 1;
      amplitudePeak = Math.max(amplitudePeak, hands.amplitude);
      bin.gestureActivity += hands.amplitude;
      bin.gestureSamples += 1;
    }

    // Both hands moving together in one stroke is one gesture, not two, so a simultaneous
    // firing is collapsed.
    const leftFired = hands.left !== null && gestureDetectors.left.push(hands.left, sample.atMs);
    const rightFired =
      hands.right !== null && gestureDetectors.right.push(hands.right, sample.atMs);
    if (leftFired || rightFired) gestureCount += 1;

    // Travel, not position: a speaker resting one hand and gesturing with the other has
    // balanced positions and very unbalanced movement, and it is the movement that matters.
    if (lastWrists) {
      if (hands.left !== null && lastWrists.left !== null) {
        leftTravel += Math.abs(hands.left - lastWrists.left);
      }
      if (hands.right !== null && lastWrists.right !== null) {
        rightTravel += Math.abs(hands.right - lastWrists.right);
      }
    }
    lastWrists = { left: hands.left, right: hands.right };

    // ── Movement energy ───────────────────────────────────────────────────
    if (lastMidpointX !== null && lastPoseAtMs !== null) {
      const dt = (sample.atMs - lastPoseAtMs) / 1000;
      if (dt > 0 && dt < 2) {
        const torsoTravel = Math.abs((posture.lateralOffset ?? 0) - lastMidpointX);
        const handTravel =
          hands.amplitude !== null && lastWrists ? Math.abs(hands.amplitude) * 0.5 : 0;
        movementTotal += (torsoTravel + handTravel) / dt;
        movementCount += 1;
        bin.movement += (torsoTravel + handTravel) / dt;
        bin.movementSamples += 1;
      }
    }
    lastMidpointX = posture.lateralOffset ?? 0;
    lastPoseAtMs = sample.atMs;
  }

  /**
   * Feed one hand observation.
   *
   * Everything here is finger-level and therefore optional: the ladder drops this model first,
   * and when it does these metrics go null while the pose-tier gesture numbers carry on.
   */
  function addHandSample(sample: HandSample) {
    handSeen += 1;
    const size = { width: options.videoWidth, height: options.videoHeight };

    if (sample.hands.length === 0) {
      faceTouchDetector.push(false, sample.atMs);
      claspedDetector.push(false, sample.atMs);
      lastHandCentres = { left: null, right: null };
      return;
    }

    handDetected += 1;
    handShapeFrames += 1;

    const left = sample.hands.find((hand) => hand.side === "left") ?? null;
    const right = sample.hands.find((hand) => hand.side === "right") ?? null;

    if (sample.hands.some((hand) => hand.openPalm)) openPalmFrames += 1;

    // Pointing is counted as an event on its rising edge — holding a point for three seconds is
    // one point, not thirty frames of pointing.
    const pointing = sample.hands.some((hand) => hand.pointing);
    if (pointing && !wasPointing) pointingEvents += 1;
    wasPointing = pointing;

    const nearFace = sample.hands.some((hand) =>
      isNearFace(hand, lastFaceCentre, lastFaceScalePx, size),
    );
    faceTouchDetector.push(nearFace, sample.atMs);
    claspedDetector.push(areHandsClasped(left, right, size), sample.atMs);

    // Fidget: movement that is present but too small to be a gesture. A hand that is either
    // still or making real strokes is not fidgeting; one that never settles is.
    const centres = {
      left: left ? left.centre.x * size.width : null,
      right: right ? right.centre.x * size.width : null,
    };

    // Follow whichever hand is currently visible; a single track is enough to characterise
    // fidgeting, and switching hands mid-window simply closes it.
    const current = centres.right ?? centres.left;
    const previous = lastHandCentres.right ?? lastHandCentres.left;

    if (current !== null) {
      if (windowStartedMs === null) windowStartedMs = sample.atMs;
      if (previous !== null) windowPath += Math.abs(current - previous);
      windowMin = Math.min(windowMin, current);
      windowMax = Math.max(windowMax, current);

      if (sample.atMs - windowStartedMs >= FIDGET_WINDOW_MS) {
        const range = windowMax - windowMin;
        fidgetWindows += 1;
        // Busy but going nowhere: plenty of travel confined to a small patch.
        if (
          windowPath > size.width * FIDGET_MIN_PATH_RATIO &&
          range < size.width * FIDGET_MAX_RANGE_RATIO
        ) {
          fidgetActiveWindows += 1;
        }
        windowPath = 0;
        windowMin = Infinity;
        windowMax = -Infinity;
        windowStartedMs = sample.atMs;
      }
    }

    lastHandCentres = centres;
  }

  function irisCurrentlyUsable(): boolean {
    if (irisSamples < 20) return true; // not enough evidence to disable it yet
    return irisBadSamples / irisSamples < 0.3;
  }

  function build(input: BuildInput): VideoFeatures {
    const features = emptyVideoFeatures();
    const reasons: string[] = [];

    const {
      activeSeconds,
      framesSeen,
      framesAnalyzed,
      faceAttempts,
      poseAttempts = 0,
      handAttempts = 0,
      earlyStop,
      brightnessOk = null,
      degradationTier = "high",
      tierChanges = 0,
      framing = "unknown",
      framingOverride,
    } = input;

    // Close any span still open at the end of capture.
    const endMs = activeSeconds * 1000;
    awayDetector.close(endMs);
    smileDetector.close(endMs);
    postureShiftDetector.close(endMs);
    armsCrossedDetector.close(endMs);
    faceTouchDetector.close(endMs);
    claspedDetector.close(endMs);

    features.duration_seconds = Math.round(activeSeconds * 10) / 10;

    const facePct = faceAttempts > 0 ? (faceDetected / faceAttempts) * 100 : null;
    const achievedFaceHz = activeSeconds > 0 ? faceAttempts / activeSeconds : null;

    features.quality = {
      ...features.quality,
      frames_seen: framesSeen,
      frames_analyzed: framesAnalyzed,
      face_frames: faceAttempts,
      pose_frames: poseAttempts,
      hand_frames: handAttempts,
      face_detected_pct: round(facePct),
      pose_detected_pct: poseAttempts > 0 ? round((poseDetected / poseAttempts) * 100) : null,
      hands_visible_pct:
        scoredFrames > 0 ? round((handsVisibleFrames / scoredFrames) * 100) : null,
      mean_pose_visibility: null, // per-landmark visibility is consumed, not aggregated
      achieved_pose_hz: activeSeconds > 0 && poseAttempts > 0 ? round(poseAttempts / activeSeconds) : null,
      achieved_hand_hz: activeSeconds > 0 && handAttempts > 0 ? round(handAttempts / activeSeconds) : null,
      mean_face_confidence: null, // MediaPipe exposes no per-face score in VIDEO mode.
      achieved_face_hz: round(achievedFaceHz),
      video_width: options.videoWidth || null,
      video_height: options.videoHeight || null,
      degradation_tier: degradationTier,
      tier_changes: tierChanges,
      framing: observedFraming(framing),
      // Only waive the framing gate when we genuinely could not run the check — with the pose
      // model on, "unknown" means the body was never seen, which is a real failure.
      framing_override: framingOverride ?? (poseAttempts === 0 && framing === "unknown"),
      brightness_ok: brightnessOk,
      model_versions: options.modelVersions,
      user_agent_hint: options.userAgentHint,
    };

    features.calibration = {
      performed: calibration.performed,
      method: calibration.method,
      baseline_yaw_deg: round(calibration.baselineYawDeg),
      baseline_pitch_deg: round(calibration.baselinePitchDeg),
      yaw_tolerance_deg: round(calibration.yawToleranceDeg),
      pitch_tolerance_deg: round(calibration.pitchToleranceDeg),
      screen_offset_pitch_deg: round(calibration.screenOffsetPitchDeg),
      iris_gain_deg_per_unit: irisCurrentlyUsable() ? round(calibration.irisGainDegPerUnit) : null,
      quality: calibration.quality,
    };
    if (calibration.method === "none") reasons.push("gaze_uncalibrated");
    else if (calibration.method === "session_baseline") reasons.push("gaze_baseline_only");
    if (irisSamples >= 20 && !irisCurrentlyUsable()) reasons.push("iris_unreliable");

    const faceCoverageOk = facePct !== null && facePct >= FAMILY_COVERAGE_MIN_PCT;
    if (!faceCoverageOk) {
      reasons.push(`face_coverage_${facePct === null ? "none" : (facePct / 100).toFixed(2)}`);
    }

    if (faceCoverageOk && faceDetected > 0) {
      const gazeTotal = Object.values(bucketCounts).reduce((sum, n) => sum + n, 0);
      if (gazeTotal > 0) {
        const pct = (n: number) => round((n / gazeTotal) * 100);
        const away = awayDetector.summary();

        features.gaze = {
          on_camera_pct: pct(bucketCounts.on_camera),
          // Engaged with the display at all: the camera cone plus the calibrated screen band.
          on_screen_pct: pct(bucketCounts.on_camera + bucketCounts.on_screen),
          down_pct: pct(bucketCounts.down),
          side_pct: pct(bucketCounts.side),
          up_pct: pct(bucketCounts.up),
          offscreen_pct: pct(bucketCounts.offscreen),
          longest_away_seconds: away.longestMs > 0 ? round(away.longestMs / 1000) : null,
          away_episodes: away.count,
          mean_away_seconds: away.meanMs !== null ? round(away.meanMs / 1000) : null,
          gaze_shift_rate_per_min:
            activeSeconds > 0 ? round((gazeShifts / activeSeconds) * 60) : null,
          eye_contact_consistency: consistency(),
        };
      }

      if (angularDeltaCount > 0) {
        const meanSpeed = angularDeltaTotal / angularDeltaCount;
        features.head = {
          ...features.head,
          mean_angular_speed_deg_s: round(meanSpeed),
          // 0 deg/s reads as perfectly steady; 60+ as constant motion.
          stability: round(clamp(100 - (meanSpeed / 60) * 100)),
          nod_count: nodCount,
          nod_rate_per_min: activeSeconds > 0 ? round((nodCount / activeSeconds) * 60) : null,
          shake_count: shakeCount,
        };
      }
      if (rollCount > 0) {
        features.head.tilt_mean_deg = round(rollTotal / rollCount);
        features.head.tilt_abs_mean_deg = round(rollAbsTotal / rollCount);
      }

      const blinkReliable = achievedFaceHz !== null && achievedFaceHz >= BLINK_RELIABLE_MIN_HZ;
      features.expression = {
        ...features.expression,
        smile_pct: round((smileFrames / faceDetected) * 100),
        smile_events: smileDetector.summary().count,
        smile_mean_intensity: smileFrames > 0 ? round(smileTotal / smileFrames) : null,
        smile_peak_intensity: round(smilePeak),
        neutral_pct: round((neutralFrames / faceDetected) * 100),
        brow_raise_pct: round((browRaiseFrames / faceDetected) * 100),
        mouth_open_pct: round((mouthOpenFrames / faceDetected) * 100),
        blink_count: blinkCount,
        blink_rate_per_min:
          blinkReliable && activeSeconds > 0 ? round((blinkCount / activeSeconds) * 60) : null,
        blink_rate_reliable: blinkReliable,
        expressiveness: expressiveness(),
      };
      if (!blinkReliable) reasons.push("blink_rate_undersampled");
    }

    // ── Posture, gesture, movement ────────────────────────────────────────
    if (poseAttempts === 0) {
      reasons.push("pose_not_enabled");
    } else {
      const posePct = poseDetected > 0 ? (poseDetected / poseAttempts) * 100 : 0;
      const torsoPct = poseDetected > 0 ? (torsoVisible / poseDetected) * 100 : 0;
      const poseCoverageOk = posePct >= FAMILY_COVERAGE_MIN_PCT;
      const torsoCoverageOk = torsoPct >= FAMILY_COVERAGE_MIN_PCT;

      if (!poseCoverageOk) reasons.push(`pose_coverage_${(posePct / 100).toFixed(2)}`);
      else if (!torsoCoverageOk) reasons.push(`torso_cropped_${(torsoPct / 100).toFixed(2)}`);
      else if (baseline === null) reasons.push("posture_baseline_not_established");

      const postureFrames = uprightFrames + slouchFrames + leanCounts.forward +
        leanCounts.back + leanCounts.side + leanCounts.neutral;

      // Posture needs shoulders AND a baseline. Without either it is null, never approximated
      // from the head — see metrics/posture.ts.
      if (poseCoverageOk && torsoCoverageOk && baseline !== null && postureFrames > 0) {
        const scored = leanCounts.forward + leanCounts.back + leanCounts.side + leanCounts.neutral;
        const pct = (n: number) => round((n / scored) * 100);
        const swaySpan = swayMax > swayMin ? swayMax - swayMin : 0;

        features.posture = {
          score: round(
            clamp((uprightFrames / scored) * 100 - clamp((swaySpan - 0.35) * 100, 0, 25)),
          ),
          upright_pct: pct(uprightFrames),
          slouch_pct: pct(slouchFrames),
          shoulder_tilt_mean_deg: tiltCount > 0 ? round(tiltTotal / tiltCount) : null,
          lean_forward_pct: pct(leanCounts.forward),
          lean_back_pct: pct(leanCounts.back),
          lean_side_pct: pct(leanCounts.side),
          sway_amplitude: round(swaySpan),
          sway_rate_per_min: activeSeconds > 0 ? round((swayReversals / activeSeconds) * 60) : null,
          posture_shifts: postureShiftDetector.summary().count,
          torso_visible_pct: round(torsoPct),
        };
      }

      // Gesture, pose tier. Gated on the wrists actually being in shot: a speaker gesturing
      // below the laptop lid must read as unmeasurable, never as motionless.
      const handsPct = scoredFrames > 0 ? (handsVisibleFrames / scoredFrames) * 100 : 0;
      if (poseCoverageOk && handsPct >= 25 && baseline !== null) {
        const crossed = armsCrossedDetector.summary();
        features.gesture = {
          ...features.gesture,
          count: gestureCount,
          rate_per_min: activeSeconds > 0 ? round((gestureCount / activeSeconds) * 60) : null,
          mean_amplitude: amplitudeCount > 0 ? round(amplitudeTotal / amplitudeCount) : null,
          peak_amplitude: round(amplitudePeak),
          symmetry: round(gestureSymmetry(leftTravel, rightTravel)),
          two_handed_pct: round((twoHandedFrames / scoredFrames) * 100),
          hands_visible_pct: round(handsPct),
          hands_below_frame_pct: round((handsBelowFrameCount / scoredFrames) * 100),
          // Percentage of HAND-VISIBLE time, not of the session — carry the denominator.
          arms_crossed_pct:
            handsVisibleFrames > 0
              ? round(clamp((crossed.totalMs / 1000 / Math.max(activeSeconds, 1)) * 100))
              : null,
        };
      } else if (poseCoverageOk) {
        reasons.push("hands_out_of_frame");
      }

      if (movementCount > 0 && baseline !== null) {
        const meanMovement = movementTotal / movementCount;
        // 0.6 shoulder-widths/sec of combined travel reads as a fully animated speaker.
        const energy = clamp((meanMovement / 0.6) * 100);
        features.movement = {
          energy: round(energy),
          stillness_pct: round(clamp(100 - energy)),
          restlessness_pct: round(clamp((meanMovement - 0.6) / 0.6 * 100)),
        };
      }
    }

    // ── Hand tier (finger-level) ──────────────────────────────────────────
    if (handAttempts === 0) {
      reasons.push("hands_not_enabled");
    } else {
      const handPct = (handDetected / handAttempts) * 100;
      if (handPct < FAMILY_COVERAGE_MIN_PCT) {
        // The model ran but rarely saw a hand. Finger-level metrics go null; the pose-tier
        // gesture numbers written above are untouched, which is the point of the two tiers.
        reasons.push(`hand_coverage_${(handPct / 100).toFixed(2)}`);
      } else if (handShapeFrames > 0) {
        features.gesture = {
          ...features.gesture,
          open_palm_pct: round((openPalmFrames / handShapeFrames) * 100),
          pointing_count: pointingEvents,
          face_touch_count: faceTouchDetector.summary().count,
          hands_clasped_pct: round(
            clamp((claspedDetector.summary().totalMs / 1000 / Math.max(activeSeconds, 1)) * 100),
          ),
          fidget_score:
            fidgetWindows > 0
              ? round(clamp((fidgetActiveWindows / fidgetWindows) * 100))
              : null,
        };
      }
    }

    features.timeline = buildTimeline();

    const unusable =
      facePct === null ||
      facePct < SESSION_FACE_MIN_PCT ||
      activeSeconds < MIN_DURATION_S ||
      framesAnalyzed < MIN_FRAMES_ANALYZED;

    let status: VideoStatus = "ok";
    if (unusable) status = "insufficient_data";
    else if (earlyStop) status = "partial";
    if (earlyStop) reasons.push("camera_stopped_early");

    features.status = status;
    features.unavailable_reasons = reasons;
    return features;
  }

  /**
   * Expressiveness, 0-100, from the spread of non-neutral facial activation.
   *
   * Standard deviation rather than mean on purpose: a permanently animated face and a
   * permanently blank one are both low-information, and it is the *variation* that a viewer
   * reads as expressive. A speaker whose face changes with what they are saying scores high
   * even if their average activation is modest.
   */
  function expressiveness(): number | null {
    if (nonNeutralCount < 10) return null;
    const mean = nonNeutralTotal / nonNeutralCount;
    const variance = nonNeutralSquareTotal / nonNeutralCount - mean * mean;
    if (variance < 0) return 0;
    // sd of a 0..1 signal rarely exceeds 0.25 in practice, so scale by 4 to use the range.
    return round(clamp(Math.sqrt(variance) * 4 * 100));
  }

  /**
   * Framing verdict for the session as a whole.
   *
   * Reports the dominant problem rather than the last frame's state: a user who spent most of
   * the session correctly framed and briefly leaned out of shot is well framed. Falls back to
   * whatever the caller observed (the modal's check) when there is no pose stream to judge from.
   */
  function observedFraming(fallback: VideoFeatures["quality"]["framing"]) {
    if (poseDetected === 0) return fallback;

    const torsoPct = (torsoVisible / poseDetected) * 100;
    if (torsoPct < FAMILY_COVERAGE_MIN_PCT) return "shoulders_cropped" as const;

    const worst = [
      ["too_close", framingTooClose],
      ["too_far", framingTooFar],
      ["off_center", framingOffCentre],
    ] as const;

    for (const [state, count] of worst) {
      if (count / poseDetected > 0.4) return state;
    }
    return "good" as const;
  }

  /** 1 minus the normalised spread of per-window on-camera fraction. Distinguishes steady
   *  contact from one long stare plus one long lapse, which share a mean. */
  function consistency(): number | null {
    const fractions = consistencyWindows
      .filter((w) => w.total > 0)
      .map((w) => w.onCamera / w.total);
    if (fractions.length < 2) return null;

    const mean = fractions.reduce((sum, f) => sum + f, 0) / fractions.length;
    const variance =
      fractions.reduce((sum, f) => sum + (f - mean) ** 2, 0) / fractions.length;
    // Standard deviation of a 0..1 quantity maxes out around 0.5, so scale by 2 before
    // inverting to land in 0..1.
    return round(clamp(1 - Math.sqrt(variance) * 2, 0, 1));
  }

  function buildTimeline() {
    const length = bins.length;
    const timeline = {
      bin_seconds: binSeconds,
      start_offset_seconds: 0,
      length,
      eye_contact: [] as (number | null)[],
      posture: [] as (number | null)[],
      gesture_activity: [] as (number | null)[],
      smile: [] as (number | null)[],
      movement: [] as (number | null)[],
      face_present: [] as (number | null)[],
    };

    for (const bin of bins) {
      const present = bin.faceSeen > 0 ? bin.faceDetected / bin.faceSeen : null;
      timeline.face_present.push(round(present));
      timeline.eye_contact.push(
        bin.faceDetected > 0 ? round(bin.onCamera / bin.faceDetected) : null,
      );
      timeline.smile.push(bin.smileCount > 0 ? round(bin.smileTotal / bin.smileCount) : null);
      // Null when that bin saw no pose sample at all — a gap in the pose stream must not read
      // as a bin in which the speaker was perfectly still.
      timeline.posture.push(
        bin.postureSeen > 0 ? round((bin.postureUpright / bin.postureSeen) * 100) : null,
      );
      timeline.gesture_activity.push(
        bin.gestureSamples > 0 ? round(clamp(bin.gestureActivity / bin.gestureSamples, 0, 1)) : null,
      );
      timeline.movement.push(
        bin.movementSamples > 0 ? round(clamp(bin.movement / bin.movementSamples / 0.6, 0, 1)) : null,
      );
    }

    return timeline;
  }

  return { addFaceSample, addPoseSample, addHandSample, build };
}

function round(value: number | null | undefined): number | null {
  return value === null || value === undefined || Number.isNaN(value)
    ? null
    : Math.round(value * 100) / 100;
}

function clamp(value: number, low = 0, high = 100): number {
  return Math.max(low, Math.min(high, value));
}
