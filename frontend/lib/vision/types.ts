/**
 * The `video_features` contract — TypeScript mirror of backend/schemas/video_features_schema.py.
 *
 * MediaPipe runs entirely in this browser. Nothing leaves the device except the object below:
 * no video, no frames, no per-frame landmarks. That mirrors the existing audio contract, where
 * the voice socket streams PCM and the backend only ever stores derived features.
 *
 * Four rules hold this together. They are not stylistic:
 *
 * 1. Every metric is `number | null`, and **`null` means "not measured", never `0`.** A speaker
 *    gesturing below the laptop lid has an unmeasurable gesture count, not zero gestures.
 *    Collapsing those two states produces confident, specific, wrong coaching — the single most
 *    damaging bug this feature can have.
 * 2. Every family carries its own coverage, so the backend can null out one family without
 *    discarding the session. A cropped torso kills posture and says nothing about gaze.
 * 3. `schema_version` is on the root, because browsers cache aggressively and old clients will
 *    keep POSTing old shapes long after a deploy.
 * 4. None of this is trusted server-side. `lib/video_scorer.py` re-derives every coverage gate
 *    from `quality` before scoring, so inflating a number here achieves nothing.
 *
 * When changing anything in this file, change the Pydantic model in the same commit. The
 * backend ignores unknown fields (so a newer client is safe against an older server), but a
 * field that exists here and not there is silently dropped.
 */

export const VIDEO_FEATURES_SCHEMA_VERSION = 1;

/** Keep in sync with TIMELINE_CHANNELS in the Python schema — the equal-length validator, the
 *  sparkline UI, and any future retention job all key off this list. */
export const TIMELINE_CHANNELS = [
  "eye_contact",
  "posture",
  "gesture_activity",
  "smile",
  "movement",
  "face_present",
] as const;

export type TimelineChannel = (typeof TIMELINE_CHANNELS)[number];

/** Cap enforced server-side (MAX_VIDEO_TIMELINE_BINS). Past this the client must downsample to
 *  a larger `bin_seconds` rather than send a longer array. */
export const MAX_VIDEO_TIMELINE_BINS = 1800;

export type VideoStatus = "ok" | "partial" | "insufficient_data";

/** Set by the degradation ladder from measured inference cost — never from device sniffing. */
export type DegradationTier = "high" | "medium" | "low" | "minimal";

export type FramingState =
  | "good"
  | "too_close"
  | "too_far"
  | "off_center"
  | "shoulders_cropped"
  | "unknown";

/** How "looking at the camera" was established. The backend only quotes `on_camera_pct`
 *  verbatim for `on_screen_target`; anything else falls back to the robust
 *  `100 - down - offscreen`. */
export type CalibrationMethod = "on_screen_target" | "session_baseline" | "none";

export type CalibrationQuality = "good" | "weak" | "failed";

/** Mirrors VideoRejectionReason in lib/video_scorer.py — a capture-quality problem that
 *  qualifies the delivery numbers rather than replacing them.
 *
 *  Two members were previously wrong (`face_lost_too_often` and `too_short`, against the
 *  backend's `face_coverage_too_low` and `clip_too_short`), which meant a genuine duration
 *  warning fell through the copy map and rendered as "we couldn't see your face". */
export type VideoRejectionReason =
  | "no_face_detected"
  | "face_coverage_too_low"
  | "too_dark"
  | "clip_too_short"
  | "framing_unusable"
  | "device_too_slow"
  | "camera_stopped_early";

export interface VideoQuality {
  frames_seen: number;
  frames_analyzed: number;

  /** Per-model attempt counts. The three models run at different cadences, so each family's
   *  coverage must be a fraction of its OWN attempts, not of total frames. */
  face_frames: number;
  pose_frames: number;
  hand_frames: number;

  face_detected_pct: number | null;
  pose_detected_pct: number | null;
  hands_visible_pct: number | null;

  mean_face_confidence: number | null;
  /** Mean visibility of the shoulder landmarks (11, 12) — the gate for every posture metric. */
  mean_pose_visibility: number | null;

  /** Achieved, not target. Blink rate is only trustworthy above ~12Hz face sampling. */
  achieved_face_hz: number | null;
  achieved_pose_hz: number | null;
  achieved_hand_hz: number | null;

  video_width: number | null;
  video_height: number | null;

  degradation_tier: DegradationTier;
  tier_changes: number;

  framing: FramingState;
  /** User dismissed the framing warning with "continue anyway". */
  framing_override: boolean;
  brightness_ok: boolean | null;

  /** From public/mediapipe/manifest.json. Stored because these aggregates are longitudinal and
   *  blendshape behaviour shifts between model revisions. */
  model_versions: Partial<Record<"face" | "pose" | "hand", string>>;
  /** Coarse bucket such as "chrome-desktop". Never a full UA string. */
  user_agent_hint: string | null;
}

export interface VideoCalibration {
  performed: boolean;
  method: CalibrationMethod;

  baseline_yaw_deg: number | null;
  baseline_pitch_deg: number | null;

  /** Half-width of the "on camera" cone. Widened for users who cannot hold still, so
   *  restlessness costs precision rather than producing a false negative. */
  yaw_tolerance_deg: number | null;
  pitch_tolerance_deg: number | null;

  /** Angular delta between "at the lens" and "at the app panel". This is what separates
   *  looking at the AI from reading notes on the desk. */
  screen_offset_pitch_deg: number | null;
  /** Fitted k in `gaze = head_angle + k * iris_offset`. Null means head-pose only, e.g.
   *  reflective glasses made the iris landmarks unusable. */
  iris_gain_deg_per_unit: number | null;

  quality: CalibrationQuality;
}

/**
 * Percentages are frame-weighted; *episodes* are dwell-gated (>= 700ms).
 *
 * A 300ms glance away therefore lowers `on_camera_pct` but contributes zero to `away_episodes`.
 * Both are correct — they answer different questions — and the distinction must survive any
 * refactor of the smoothing layer.
 */
export interface GazeMetrics {
  on_camera_pct: number | null;
  on_screen_pct: number | null;
  down_pct: number | null;
  side_pct: number | null;
  up_pct: number | null;
  offscreen_pct: number | null;

  longest_away_seconds: number | null;
  away_episodes: number | null;
  mean_away_seconds: number | null;
  gaze_shift_rate_per_min: number | null;
  /** 1 - normalised stddev of per-10s on-camera fraction. Distinguishes steady contact from
   *  one long stare plus one long lapse. */
  eye_contact_consistency: number | null;
}

export interface HeadMetrics {
  /** 0-100, derived from angular velocity rather than positional jitter (scale-free). */
  stability: number | null;
  mean_angular_speed_deg_s: number | null;
  nod_count: number | null;
  nod_rate_per_min: number | null;
  shake_count: number | null;
  /** Signed roll, baseline-subtracted — a tilted laptop lid rotates everything by a constant. */
  tilt_mean_deg: number | null;
  tilt_abs_mean_deg: number | null;
}

/**
 * Derived from the 52 ARKit blendshapes the face model already emits, so no separate emotion
 * model is needed.
 *
 * These are measurements, not emotion labels, and must never be rendered as one. "Your face
 * stayed neutral 78% of the time" is defensible; "you looked sad" is not, and no blendshape
 * supports it.
 */
export interface ExpressionMetrics {
  smile_pct: number | null;
  smile_events: number | null;
  smile_mean_intensity: number | null;
  smile_peak_intensity: number | null;
  neutral_pct: number | null;
  brow_raise_pct: number | null;
  /** Speaking proxy — cross-checks the audio transcript. */
  mouth_open_pct: number | null;
  blink_count: number | null;
  blink_rate_per_min: number | null;
  /** False when achieved_face_hz < 12. Blinks last 100-400ms and are undersampled below that,
   *  so the rate must not be quoted. */
  blink_rate_reliable: boolean;
  expressiveness: number | null;
}

/**
 * All of this requires visible shoulders. When the torso is cropped every field here is null —
 * head position alone is not posture, and approximating it is exactly the confident-garbage
 * failure rule 1 exists to prevent.
 */
export interface PostureMetrics {
  score: number | null;
  upright_pct: number | null;
  slouch_pct: number | null;
  /** Baseline-subtracted. */
  shoulder_tilt_mean_deg: number | null;
  lean_forward_pct: number | null;
  lean_back_pct: number | null;
  lean_side_pct: number | null;
  /** In shoulder-width units, never pixels. */
  sway_amplitude: number | null;
  /** Direction reversals per minute. */
  sway_rate_per_min: number | null;
  /** Sustained (>2s) baseline changes. */
  posture_shifts: number | null;
  torso_visible_pct: number | null;
}

/**
 * Two tiers with different availability.
 *
 * Pose-derived (count, rate, amplitude, symmetry, two-handed) needs only the wrists, which come
 * free with the pose model. Hand-derived (open palm, pointing, clasped, precise face touch)
 * needs the hand model, which the degradation ladder switches off first — so the pose tier
 * survives on weak devices while the finger-level tier goes null.
 *
 * `arms_crossed_pct` and `hands_clasped_pct` are percentages of HAND-VISIBLE frames, not of the
 * session. Read against `hands_visible_pct` or they overstate.
 */
export interface GestureMetrics {
  count: number | null;
  rate_per_min: number | null;
  /** Shoulder-width units. */
  mean_amplitude: number | null;
  peak_amplitude: number | null;
  /** 0-1, where 1 is balanced left/right. */
  symmetry: number | null;
  two_handed_pct: number | null;

  hands_visible_pct: number | null;
  hands_below_frame_pct: number | null;

  arms_crossed_pct: number | null;
  hands_clasped_pct: number | null;
  face_touch_count: number | null;
  pocket_or_still_pct: number | null;

  open_palm_pct: number | null;
  pointing_count: number | null;
  fidget_score: number | null;
}

export interface MovementMetrics {
  /** Head + torso + hand composite. */
  energy: number | null;
  stillness_pct: number | null;
  restlessness_pct: number | null;
}

/**
 * Fixed-channel parallel arrays, not an array of objects — six channels over 300 bins is ~9KB
 * this way and several times that as objects.
 *
 * `face_present` is not optional in spirit: without it a reader cannot tell "eye contact
 * dropped" from "we lost the face", which is the distinction this whole feature rests on.
 */
export interface VideoTimeline {
  /** 1 normally; the client downsamples to 2 rather than exceed MAX_VIDEO_TIMELINE_BINS. */
  bin_seconds: number;
  start_offset_seconds: number;
  length: number;

  /** All arrays are exactly `length` long. `null` marks a bin with no data — never interpolate
   *  across one, since a gap means the tab was hidden or the filter state was reset. */
  eye_contact: (number | null)[];
  posture: (number | null)[];
  gesture_activity: (number | null)[];
  smile: (number | null)[];
  movement: (number | null)[];
  face_present: (number | null)[];
}

export interface VideoFeatures {
  schema_version: typeof VIDEO_FEATURES_SCHEMA_VERSION;

  /** Analysis-ACTIVE seconds. Excludes time with the tab hidden, so it is neither wall clock
   *  nor necessarily the audio duration. */
  duration_seconds: number;
  status: VideoStatus;
  /** Machine-readable codes such as "face_coverage_0.41" or "hands_disabled_by_degradation".
   *  Surfaced to the user as the reason a results tile shows a dash. */
  unavailable_reasons: string[];

  quality: VideoQuality;
  calibration: VideoCalibration;

  gaze: GazeMetrics;
  head: HeadMetrics;
  expression: ExpressionMetrics;
  posture: PostureMetrics;
  gesture: GestureMetrics;
  movement: MovementMetrics;

  timeline: VideoTimeline;
}

/** Shape of the `video` block the backend returns on the scorecard
 *  (video_scorer.ScoredVideo.to_dict()). Sub-scores are null when that family was unmeasurable,
 *  and the UI must render a dash with the reason rather than a zero. */
export interface ScoredVideo {
  eye_contact: number | null;
  posture: number | null;
  gestures: number | null;
  expression: number | null;
  stillness: number | null;
  visual_presence: number | null;
  /** 0-1. Below 0.5 the backend withholds these numbers from the LLM entirely. */
  confidence_weight: number;
  /** The worst entry in `warnings`, or null. Kept for stored scorecards; it no longer
   *  suppresses the scores. */
  rejection: VideoRejectionReason | null;
  /** Every capture-quality problem, worst first. Rendered beside the numbers so the user knows
   *  which measurement to distrust. Absent on scorecards stored before this existed. */
  warnings?: VideoRejectionReason[];
  issues: { type: string; message: string; suggestion: string }[];
  highlights: { kind: string; message: string }[];
  detail: Record<string, unknown>;
}

// ── Constructors ──────────────────────────────────────────────────────────────
// Everything starts null. A partially-filled payload must describe "we know nothing yet", never
// "everything was fine" — the aggregator fills in only what it actually measured.

export function emptyTimeline(): VideoTimeline {
  return {
    bin_seconds: 1,
    start_offset_seconds: 0,
    length: 0,
    eye_contact: [],
    posture: [],
    gesture_activity: [],
    smile: [],
    movement: [],
    face_present: [],
  };
}

export function emptyVideoFeatures(): VideoFeatures {
  return {
    schema_version: VIDEO_FEATURES_SCHEMA_VERSION,
    duration_seconds: 0,
    status: "insufficient_data",
    unavailable_reasons: [],
    quality: {
      frames_seen: 0,
      frames_analyzed: 0,
      face_frames: 0,
      pose_frames: 0,
      hand_frames: 0,
      face_detected_pct: null,
      pose_detected_pct: null,
      hands_visible_pct: null,
      mean_face_confidence: null,
      mean_pose_visibility: null,
      achieved_face_hz: null,
      achieved_pose_hz: null,
      achieved_hand_hz: null,
      video_width: null,
      video_height: null,
      degradation_tier: "high",
      tier_changes: 0,
      framing: "unknown",
      framing_override: false,
      brightness_ok: null,
      model_versions: {},
      user_agent_hint: null,
    },
    calibration: {
      performed: false,
      method: "none",
      baseline_yaw_deg: null,
      baseline_pitch_deg: null,
      yaw_tolerance_deg: null,
      pitch_tolerance_deg: null,
      screen_offset_pitch_deg: null,
      iris_gain_deg_per_unit: null,
      quality: "failed",
    },
    gaze: {
      on_camera_pct: null,
      on_screen_pct: null,
      down_pct: null,
      side_pct: null,
      up_pct: null,
      offscreen_pct: null,
      longest_away_seconds: null,
      away_episodes: null,
      mean_away_seconds: null,
      gaze_shift_rate_per_min: null,
      eye_contact_consistency: null,
    },
    head: {
      stability: null,
      mean_angular_speed_deg_s: null,
      nod_count: null,
      nod_rate_per_min: null,
      shake_count: null,
      tilt_mean_deg: null,
      tilt_abs_mean_deg: null,
    },
    expression: {
      smile_pct: null,
      smile_events: null,
      smile_mean_intensity: null,
      smile_peak_intensity: null,
      neutral_pct: null,
      brow_raise_pct: null,
      mouth_open_pct: null,
      blink_count: null,
      blink_rate_per_min: null,
      blink_rate_reliable: false,
      expressiveness: null,
    },
    posture: {
      score: null,
      upright_pct: null,
      slouch_pct: null,
      shoulder_tilt_mean_deg: null,
      lean_forward_pct: null,
      lean_back_pct: null,
      lean_side_pct: null,
      sway_amplitude: null,
      sway_rate_per_min: null,
      posture_shifts: null,
      torso_visible_pct: null,
    },
    gesture: {
      count: null,
      rate_per_min: null,
      mean_amplitude: null,
      peak_amplitude: null,
      symmetry: null,
      two_handed_pct: null,
      hands_visible_pct: null,
      hands_below_frame_pct: null,
      arms_crossed_pct: null,
      hands_clasped_pct: null,
      face_touch_count: null,
      pocket_or_still_pct: null,
      open_palm_pct: null,
      pointing_count: null,
      fidget_score: null,
    },
    movement: {
      energy: null,
      stillness_pct: null,
      restlessness_pct: null,
    },
    timeline: emptyTimeline(),
  };
}
