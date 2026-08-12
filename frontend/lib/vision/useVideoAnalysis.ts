"use client";

/**
 * Camera capture + in-browser landmark analysis, shaped to mirror `lib/useVoiceSocket.ts`.
 *
 * Same contract as the voice hook: nothing is auto-submitted. The caller reads
 * `getVideoFeatures()` once, when it submits the turn, exactly as it reads
 * `getLastAudioFeatures()`.
 *
 * Deliberately runs its own `getUserMedia({ video: true })` rather than sharing the voice
 * hook's stream. Coupling the two lifecycles would mean stopping voice kills the camera (and
 * vice versa), and the camera is an optional add-on that the user can decline while still
 * speaking. Two getUserMedia calls is the cheaper problem.
 *
 * All three landmarkers run on the adaptive tier ladder (see frameScheduler.ts), at most one
 * per frame callback. Gaze calibration is supported but optional — pass one in and the payload
 * reports it, omit it and the payload says so, which makes the backend fall back to its robust
 * metric and discount the session rather than quoting a misleading percentage.
 */

import * as React from "react";

import { createAggregator, type FaceSample } from "./aggregator";
import {
  createFrameScheduler,
  type DegradationTier,
  type FrameScheduler,
  type ModelKind,
} from "./frameScheduler";
import {
  classifyGaze,
  gazeAngles,
  isScorableCalibration,
  type GazeBucket,
  type GazeCalibration,
} from "./gaze";
import { anglesFromMatrix, irisOffset } from "./headPose";
import { readHandShape } from "./metrics/hands";
import { readPoseFrame } from "./metrics/posture";
import { VisionLoadError, ensureLandmarkers, type Landmarkers } from "./mediapipeLoader";
import { evaluateFraming, FACE, distancePx, type Landmark } from "./normalize";
import { loadCalibration } from "../cameraReadiness";
import type { FramingState, VideoFeatures } from "./types";

/** Models loaded for a session. The scheduler's tier table decides their cadences. */
const SESSION_MODELS: ModelKind[] = ["face", "pose", "hand"];

/** Dwell before a live framing/gaze reading reaches the UI. Matches the away-episode dwell
 *  (`GazeMetrics` doc, aggregator.ts) so a brief glance away isn't flagged as a live issue any
 *  sooner than it would count as one in the aggregate. */
const LIVE_DWELL_MS = 700;

interface DwellState<T> {
  value: T;
  candidate: T;
  since: number;
}

/** Only commits `next` once it has been the steady reading for `LIVE_DWELL_MS` — otherwise a
 *  face sample flickering between two framing/gaze buckets would flash the live overlay at
 *  face-model cadence (up to 15Hz). */
function commitWithDwell<T>(
  state: DwellState<T>,
  next: T,
  atMs: number,
  setState: (value: T) => void,
): void {
  if (next === state.value) {
    state.candidate = next;
    return;
  }
  if (next !== state.candidate) {
    state.candidate = next;
    state.since = atMs;
    return;
  }
  if (atMs - state.since >= LIVE_DWELL_MS) {
    state.value = next;
    setState(next);
  }
}

const CAPTURE_CONSTRAINTS: MediaStreamConstraints = {
  video: {
    width: { ideal: 640 },
    height: { ideal: 480 },
    frameRate: { ideal: 30 },
    facingMode: "user",
  },
  audio: false, // the voice hook owns the microphone
};

/** Blendshape names we read. Resolved to indices once per session — `.find()` per frame at
 *  10Hz+ is pure waste. */
const BLENDSHAPES = {
  smileLeft: "mouthSmileLeft",
  smileRight: "mouthSmileRight",
  blinkLeft: "eyeBlinkLeft",
  blinkRight: "eyeBlinkRight",
  browInnerUp: "browInnerUp",
  jawOpen: "jawOpen",
  neutral: "_neutral",
} as const;

type BlendshapeIndices = Partial<Record<keyof typeof BLENDSHAPES, number>>;

export interface UseVideoAnalysisResult {
  isVideoActive: boolean;
  isStartingVideo: boolean;
  isStoppingVideo: boolean;
  videoStatus: string;
  error: string | null;
  /** 0..1 while the ~16MB of wasm and models download, else null. */
  loadProgress: number | null;
  startVideo: () => Promise<void>;
  stopVideo: () => Promise<void>;
  /** Attach to a muted, playsInline <video> for the self-view. */
  videoRef: React.RefObject<HTMLVideoElement>;
  /** Consume-once, mirroring useVoiceSocket.getLastAudioFeatures(). */
  getVideoFeatures: () => VideoFeatures | null;
  /** Live framing reading, dwell-debounced. "unknown" when the camera is off or no face has
   *  been seen yet — never shown as an issue. */
  liveFraming: FramingState;
  /** Live gaze bucket, dwell-debounced. Null when the camera is off, no face is visible, or the
   *  session has no usable calibration — an uncalibrated gaze reading is not shown live for the
   *  same reason it is not shown in the results tile (see invariant 3, video-analysis-handoff). */
  liveGazeBucket: GazeBucket | null;
  /** Whether this session's calibration is good enough for eye contact to be scored at all.
   *  False is worth saying out loud while the camera is still running: everything else on screen
   *  looks identical either way, so the first sign used to be an empty tile in the results. */
  gazeScorable: boolean;
}

const FAILURE_COPY: Record<string, string> = {
  unsupported_browser:
    "This browser can't run the delivery analysis. Your speech will still be scored on voice.",
  assets_missing:
    "The analysis models are missing on the server. Your speech will still be scored on voice.",
  load_failed: "Couldn't start the camera analysis. Your speech will still be scored on voice.",
  NotAllowedError: "Camera permission was denied. You can still practise with voice only.",
  NotFoundError: "No camera was found. You can still practise with voice only.",
  NotReadableError: "Your camera is already in use by another app. Close it and try again.",
};

export function useVideoAnalysis(
  options: {
    /** Fitted by the camera-check flow. Without it gaze is uncalibrated, the payload says so,
     *  and the backend discounts the session rather than quoting a misleading percentage. */
    calibration?: GazeCalibration;
  } = {},
): UseVideoAnalysisResult {
  const [isVideoActive, setIsVideoActive] = React.useState(false);
  const [isStartingVideo, setIsStartingVideo] = React.useState(false);
  const [isStoppingVideo, setIsStoppingVideo] = React.useState(false);
  const [videoStatus, setVideoStatus] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [loadProgress, setLoadProgress] = React.useState<number | null>(null);
  const [liveFraming, setLiveFraming] = React.useState<FramingState>("unknown");
  const [liveGazeBucket, setLiveGazeBucket] = React.useState<GazeBucket | null>(null);
  const [gazeScorable, setGazeScorable] = React.useState(false);

  const videoRef = React.useRef<HTMLVideoElement>(null);
  const liveFramingDwellRef = React.useRef<DwellState<FramingState>>({
    value: "unknown",
    candidate: "unknown",
    since: 0,
  });
  const liveGazeDwellRef = React.useRef<DwellState<GazeBucket | null>>({
    value: null,
    candidate: null,
    since: 0,
  });
  const streamRef = React.useRef<MediaStream | null>(null);
  const schedulerRef = React.useRef<FrameScheduler | null>(null);
  const aggregatorRef = React.useRef<ReturnType<typeof createAggregator> | null>(null);
  const startedAtRef = React.useRef<number>(0);
  const earlyStopRef = React.useRef(false);
  const blendshapeIndicesRef = React.useRef<BlendshapeIndices>({});
  // Holds the built payload until the caller consumes it on submit.
  const featuresRef = React.useRef<VideoFeatures | null>(null);
  const tierRef = React.useRef<DegradationTier>("high");
  const unviableRef = React.useRef(false);
  const calibrationRef = React.useRef(options.calibration);
  calibrationRef.current = options.calibration;
  // The above is re-assigned on every render, so the resolution-checked value startVideo settles
  // on needs somewhere of its own to live for the length of the session.
  const sessionCalibrationRef = React.useRef<GazeCalibration | undefined>(undefined);

  const teardownCapture = React.useCallback(() => {
    schedulerRef.current?.stop();
    schedulerRef.current = null;

    // Stop tracks before anything else: a camera indicator left on after a session reads as a
    // privacy breach regardless of what the code is actually doing.
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;

    const video = videoRef.current;
    if (video) video.srcObject = null;

    // The overlay must not show a stale reading once the camera is off, and dwell state must
    // not carry a half-committed candidate into the next session.
    liveFramingDwellRef.current = { value: "unknown", candidate: "unknown", since: 0 };
    liveGazeDwellRef.current = { value: null, candidate: null, since: 0 };
    setLiveFraming("unknown");
    setLiveGazeBucket(null);
  }, []);

  const startVideo = React.useCallback(async () => {
    if (streamRef.current) return;

    setError(null);
    setIsStartingVideo(true);
    setVideoStatus("Preparing analysis...");
    earlyStopRef.current = false;
    unviableRef.current = false;
    tierRef.current = "high";

    let landmarkers: Landmarkers;
    let stream: MediaStream | null = null;

    try {
      landmarkers = await ensureLandmarkers({
        models: SESSION_MODELS,
        onProgress: (fraction, label) => {
          setLoadProgress(fraction);
          setVideoStatus(fraction >= 1 ? "Starting camera..." : `${label}...`);
        },
      });
      setLoadProgress(null);

      stream = await navigator.mediaDevices.getUserMedia(CAPTURE_CONSTRAINTS);
      streamRef.current = stream;

      const video = videoRef.current;
      if (!video) throw new Error("Self-view element is not mounted");

      video.srcObject = stream;
      video.muted = true;
      video.playsInline = true;
      await video.play();

      // Dimensions are only known once metadata lands, and every normalisation depends on them.
      if (!video.videoWidth) {
        await new Promise<void>((resolve) => {
          video.onloadedmetadata = () => resolve();
        });
      }

      // The camera-check gate loads the stored calibration before this stream exists, so it
      // cannot check it against the resolution actually in use. Now that the dimensions are
      // known, re-load with them: a calibration fitted at a different capture size describes a
      // different field of view, and loadCalibration drops it rather than hand back angles that
      // no longer correspond. Falling through to no calibration is the correct outcome — the
      // aggregate reports method "none" and the backend discounts it, which beats confident
      // numbers built on the wrong baseline.
      const sessionCalibration = calibrationRef.current
        ? loadCalibration(video.videoWidth, video.videoHeight) ?? undefined
        : undefined;
      sessionCalibrationRef.current = sessionCalibration;
      setGazeScorable(!!sessionCalibration && isScorableCalibration(sessionCalibration));

      const aggregator = createAggregator({
        videoWidth: video.videoWidth,
        videoHeight: video.videoHeight,
        modelVersions: landmarkers.versions,
        userAgentHint: coarseUserAgent(),
        calibration: sessionCalibration,
      });
      aggregatorRef.current = aggregator;
      startedAtRef.current = performance.now();
      blendshapeIndicesRef.current = {};

      const frameSize = { width: video.videoWidth, height: video.videoHeight };

      // What actually built, not what was asked for. A browser can manage the face graph and
      // fail on pose or hands (mediapipeLoader degrades rather than throwing), and scheduling a
      // model that does not exist would burn frame slots on a no-op while still counting the
      // attempt — inflating that family's denominator so it reads as "never detected" rather
      // than "never ran".
      const availableModels = SESSION_MODELS.filter(
        (kind) =>
          kind === "face" ||
          (kind === "pose" && landmarkers.pose) ||
          (kind === "hand" && landmarkers.hand),
      );

      const scheduler = createFrameScheduler({
        video,
        available: availableModels,
        // `track` is deliberately NOT passed, which keeps the ladder cadence-only (the option is
        // documented as optional for exactly this). With a track the ladder calls
        // track.applyConstraints() on every tier change, including the one allowed promotion
        // after PROMOTE_DWELL_MS = 30s — a live capture-resolution renegotiation ~36-40s into a
        // session. On Windows UVC webcams that restarts the device: a stall fires "mute" (frozen
        // preview), a failure fires "ended" and takes the whole session down.
        //
        // Little is lost. Cadence throttling is what actually reduces load; MediaPipe rescales
        // its input to a fixed model resolution internally, so shrinking the capture barely
        // moves inference cost.
        onInference: (kind, timestampMs) => {
          const atMs = performance.now() - startedAtRef.current;

          if (kind === "face") {
            const result = landmarkers.face.detectForVideo(video, timestampMs);
            const sample = toFaceSample(result, atMs, blendshapeIndicesRef, frameSize);
            aggregator.addFaceSample(sample);

            const landmarks = result.faceLandmarks?.[0] as Landmark[] | undefined;
            commitWithDwell(
              liveFramingDwellRef.current,
              evaluateFraming(landmarks, frameSize),
              atMs,
              setLiveFraming,
            );

            // Uncalibrated gaze is not shown live for the same reason it is not shown in the
            // results tile (invariant 3) — a raw head-pose reading is wrong by exactly the
            // unmodelled camera offset. The bar is the same one the results tile uses, not a
            // softer one: coaching a user's eye contact live and then declining to score it is
            // how a session ends up feeling like it worked when it did not.
            const calibration = sessionCalibrationRef.current;
            const nextGaze =
              calibration && isScorableCalibration(calibration) && sample.pose
                ? classifyGaze(gazeAngles(sample.pose, sample.iris, calibration), calibration)
                : null;
            commitWithDwell(liveGazeDwellRef.current, nextGaze, atMs, setLiveGazeBucket);
            return;
          }

          if (kind === "hand" && landmarkers.hand) {
            const result = landmarkers.hand.detectForVideo(video, timestampMs);
            const hands = (result.landmarks ?? [])
              .map((landmarks, index) =>
                readHandShape(
                  landmarks as Landmark[],
                  // Handedness is reported from the IMAGE's perspective; readHandShape swaps it
                  // to the user's own. `handednesses` is deprecated in favour of `handedness`,
                  // but both ship today — prefer the current one and fall back, so this keeps
                  // working whichever is dropped first. Default to "Right" so a missing label
                  // degrades to a consistent side rather than throwing.
                  result.handedness?.[index]?.[0]?.categoryName ??
                    result.handednesses?.[index]?.[0]?.categoryName ??
                    "Right",
                  frameSize,
                ),
              )
              .filter((hand): hand is NonNullable<typeof hand> => hand !== null);
            aggregator.addHandSample({ atMs, hands });
            return;
          }

          if (kind === "pose" && landmarkers.pose) {
            const result = landmarkers.pose.detectForVideo(video, timestampMs);
            const landmarks = result.landmarks?.[0] as Landmark[] | undefined;
            aggregator.addPoseSample({
              atMs,
              detected: !!landmarks,
              frame: landmarks ? readPoseFrame(landmarks, frameSize) : null,
            });
          }
        },
        onTierChange: (next) => {
          tierRef.current = next;
          setVideoStatus(
            next === "high"
              ? "Camera on. Delivery is being analysed on your device."
              : "Camera on. Analysis quality reduced to keep up with your device.",
          );
        },
        onUnviable: () => {
          // Flag, do NOT stop. This used to call stopVideo(), which is why the camera died
          // 40-60s into every speech: the ladder can reach "unviable" as early as 29s on an
          // ordinary machine (see frameScheduler.evaluateLoad), and it did so silently.
          //
          // Killing capture buys nothing. The aggregate already reports insufficient_data from
          // its own coverage counts and the backend re-derives the verdict from frames_analyzed,
          // so the payload is labelled either way — while a camera that switches itself off
          // mid-sentence reads as a crash. Rates also recover often, once whatever was stealing
          // the CPU stops.
          unviableRef.current = true;
          console.warn(
            "[vision] analysis rate unviable — continuing capture, payload flagged as partial",
          );
        },
      });
      schedulerRef.current = scheduler;
      scheduler.start();

      // The OS or the user can revoke the camera mid-session. Keep what we have and label it
      // partial rather than losing the session.
      stream.getVideoTracks().forEach((track) => {
        track.addEventListener("ended", () => {
          // Logged because this and the ladder are the only two ways capture ends by itself, and
          // without a line here they are indistinguishable from a debugger.
          console.warn("[vision] camera track ended — stopping analysis early");
          earlyStopRef.current = true;
          void stopVideoRef.current?.();
        });

        // "ended" is the permanent case. A track can also go *mute* — another application takes
        // the camera, the driver stalls, the device sleeps — which stops the frames without
        // ending anything. Nothing downstream notices: the scheduler simply sees no new frame,
        // so it neither analyses nor complains, and the preview sits frozen while the session
        // records on. These recover on their own, so hold the session open and say so; the
        // aggregate already discounts itself by the coverage it actually got.
        track.addEventListener("mute", () => {
          console.warn("[vision] camera track muted — frames paused, session held open");
          setVideoStatus("Camera interrupted — your speech is still recording.");
        });
        track.addEventListener("unmute", () => {
          setVideoStatus("Camera on. Delivery is being analysed on your device.");
        });
      });

      setIsVideoActive(true);
      setVideoStatus("Camera on. Delivery is being analysed on your device.");
    } catch (err) {
      teardownCapture();
      setLoadProgress(null);
      setIsVideoActive(false);
      setVideoStatus("");

      const key =
        err instanceof VisionLoadError ? err.reason : (err as { name?: string })?.name ?? "";
      setError(FAILURE_COPY[key] ?? FAILURE_COPY.load_failed);
      console.warn("[vision] failed to start video analysis:", err);
    } finally {
      setIsStartingVideo(false);
    }
  }, [teardownCapture]);

  const stopVideo = React.useCallback(async () => {
    if (!streamRef.current && !schedulerRef.current) return;

    setIsStoppingVideo(true);
    try {
      const stats = schedulerRef.current?.stats();
      // Release the camera before aggregating — the maths takes a few ms and the indicator
      // light should not outlive the session by even that much.
      teardownCapture();

      const aggregator = aggregatorRef.current;
      if (aggregator && stats) {
        featuresRef.current = aggregator.build({
          activeSeconds: stats.activeSeconds,
          framesSeen: stats.framesSeen,
          framesAnalyzed: stats.framesAnalyzed,
          faceAttempts: stats.attempts.face,
          poseAttempts: stats.attempts.pose,
          handAttempts: stats.attempts.hand,
          degradationTier: stats.tier,
          tierChanges: stats.tierChanges,
          // A device that never kept up produces a partial read, labelled as such.
          earlyStop: earlyStopRef.current || unviableRef.current,
        });
      }
      aggregatorRef.current = null;
    } finally {
      setIsStoppingVideo(false);
      setIsVideoActive(false);
      setVideoStatus("Camera off.");
    }
  }, [teardownCapture]);

  // The track "ended" handler above needs the latest stopVideo without re-registering.
  const stopVideoRef = React.useRef<typeof stopVideo>();
  stopVideoRef.current = stopVideo;

  React.useEffect(() => {
    // Mirrors useVoiceSocket's pagehide + unmount pair: React's async unmount cleanup is
    // skipped on a hard reload, which would leave the camera live.
    function releaseNow() {
      teardownCapture();
    }
    window.addEventListener("pagehide", releaseNow);
    return () => {
      window.removeEventListener("pagehide", releaseNow);
      releaseNow();
    };
  }, [teardownCapture]);

  const getVideoFeatures = React.useCallback((): VideoFeatures | null => {
    const features = featuresRef.current;
    featuresRef.current = null; // consume once
    return features;
  }, []);

  return {
    isVideoActive,
    isStartingVideo,
    isStoppingVideo,
    videoStatus,
    error,
    loadProgress,
    startVideo,
    stopVideo,
    videoRef,
    getVideoFeatures,
    liveFraming,
    liveGazeBucket,
    gazeScorable,
  };
}

/**
 * Turn one MediaPipe face result into the sample the aggregator consumes.
 *
 * All the maths lives in headPose.ts so it can be unit-tested without a browser; this function
 * only does extraction and null-handling.
 */
function toFaceSample(
  result: {
    faceBlendshapes?: unknown[];
    facialTransformationMatrixes?: unknown[];
    faceLandmarks?: unknown[];
  },
  atMs: number,
  indicesRef: React.MutableRefObject<BlendshapeIndices>,
  frame?: { width: number; height: number },
): FaceSample {
  const blendshapes = result.faceBlendshapes?.[0] as
    | { categories: { categoryName: string; score: number }[] }
    | undefined;
  const matrix = result.facialTransformationMatrixes?.[0] as { data: number[] } | undefined;
  const landmarks = result.faceLandmarks?.[0] as Landmark[] | undefined;

  const missed: FaceSample = {
    atMs,
    detected: false,
    pose: null,
    iris: null,
    smile: null,
    blink: null,
    browRaise: null,
    jawOpen: null,
    neutral: null,
  };

  // No head transform means no gaze, and gaze is the point — treat it as a missed frame rather
  // than emitting a sample the aggregator would count as detected.
  const pose = anglesFromMatrix(matrix?.data);
  if (!pose) return missed;

  // Resolve blendshape names to indices once, then index by integer. `.find()` per frame at
  // 10Hz+ across 52 categories is pure waste.
  if (blendshapes && Object.keys(indicesRef.current).length === 0) {
    const lookup: BlendshapeIndices = {};
    blendshapes.categories.forEach((category, index) => {
      for (const [key, name] of Object.entries(BLENDSHAPES)) {
        if (category.categoryName === name) lookup[key as keyof typeof BLENDSHAPES] = index;
      }
    });
    indicesRef.current = lookup;
  }

  const score = (key: keyof typeof BLENDSHAPES): number | null => {
    const index = indicesRef.current[key];
    if (index === undefined || !blendshapes) return null;
    return blendshapes.categories[index]?.score ?? null;
  };

  // Face centre and scale, so the hand tier can test proximity across the cadence gap.
  const outerLeft = landmarks?.[FACE.leftEyeOuter];
  const outerRight = landmarks?.[FACE.rightEyeOuter];
  const centre =
    outerLeft && outerRight
      ? { x: (outerLeft.x + outerRight.x) / 2, y: (outerLeft.y + outerRight.y) / 2 }
      : null;
  const scalePx =
    outerLeft && outerRight && frame ? distancePx(outerLeft, outerRight, frame) : null;

  return {
    atMs,
    detected: true,
    pose,
    iris: irisOffset(landmarks),
    centre,
    scalePx,
    smile: mean(score("smileLeft"), score("smileRight")),
    blink: mean(score("blinkLeft"), score("blinkRight")),
    browRaise: score("browInnerUp"),
    jawOpen: score("jawOpen"),
    neutral: score("neutral"),
  };
}

function mean(a: number | null, b: number | null): number | null {
  if (a === null && b === null) return null;
  if (a === null) return b;
  if (b === null) return a;
  return (a + b) / 2;
}

function coarseUserAgent(): string {
  if (typeof navigator === "undefined") return "unknown";
  const ua = navigator.userAgent;
  const engine = /Edg\//.test(ua)
    ? "edge"
    : /Chrome\//.test(ua)
      ? "chrome"
      : /Firefox\//.test(ua)
        ? "firefox"
        : /Safari\//.test(ua)
          ? "safari"
          : "other";
  const form = /Mobi|Android|iPhone|iPad/.test(ua) ? "mobile" : "desktop";
  return `${engine}-${form}`;
}
