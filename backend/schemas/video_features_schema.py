"""Video (physical delivery) feature contract — the VIDEO sibling of `audio_features`.

The backend never receives video, frames, or per-frame landmarks. MediaPipe runs entirely in
the browser (frontend/lib/vision/); what arrives here is this aggregate plus a downsampled
per-second timeline. That mirrors the existing audio contract, where the client streams PCM to
the voice socket and the backend only ever stores derived `AudioFeatures`.

Four rules hold this together, and every consumer depends on them:

1. **Every metric is `Optional[float]`, and `None` means "not measured" — never `0`.**
   A speaker gesturing below the laptop lid has *unmeasurable* gesture count, not zero
   gestures. Collapsing those two states is the single most damaging bug this feature can
   have, because it produces confident, specific, wrong coaching.
2. **Every family carries its own coverage**, so the scorer downweights per family rather than
   discarding a whole session. A cropped torso kills posture; it says nothing about gaze.
3. **`schema_version` is on the root.** Clients compute these values, browsers cache
   aggressively, and old clients will keep POSTing old shapes long after a deploy.
4. **Nothing here is trusted.** `lib/video_scorer.py` re-derives the coverage gates from
   `quality.*` before scoring, exactly as `_calculate_wpm` recomputes WPM rather than
   believing a client-supplied number.

`extra="ignore"` is set on every model below (via `_VideoModel`) for the same reason as (3):
a newer client that adds a field must not 422 against an older backend.
"""

from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from schemas.limits import MAX_VIDEO_TIMELINE_BINS

VIDEO_FEATURES_SCHEMA_VERSION = 1

# Timeline channels are declared once, here, because three separate things must agree on them:
# the equal-length validator below, the sparkline UI, and any future retention job that strips
# timelines from old sessions.
TIMELINE_CHANNELS = (
    "eye_contact",
    "posture",
    "gesture_activity",
    "smile",
    "movement",
    "face_present",
)


class _VideoModel(BaseModel):
    """Forward-compatible base: unknown fields from a newer client are dropped, not rejected."""

    model_config = ConfigDict(extra="ignore")


class VideoQuality(_VideoModel):
    """How much of the session was actually measurable, and how hard the device was working.

    This block is the evidence for every `None` elsewhere in the payload. The scorer reads it
    first and may null out families the client happily filled in.
    """

    frames_seen: int = 0
    frames_analyzed: int = 0

    # Per-model attempt counts. Models run at different cadences (face 15Hz / pose 6Hz /
    # hands 8Hz), so each family's coverage must be a fraction of its OWN attempts.
    face_frames: int = 0
    pose_frames: int = 0
    hand_frames: int = 0

    face_detected_pct: Optional[float] = Field(None, ge=0, le=100)
    pose_detected_pct: Optional[float] = Field(None, ge=0, le=100)
    hands_visible_pct: Optional[float] = Field(None, ge=0, le=100)

    mean_face_confidence: Optional[float] = Field(None, ge=0, le=1)
    mean_pose_visibility: Optional[float] = Field(
        None, ge=0, le=1, description="Mean visibility of the shoulder landmarks (11, 12)"
    )

    # Achieved, not target. The gap between these and the tier's nominal rate is what triggers
    # degradation — and blink rate is only trustworthy above ~12Hz face sampling.
    achieved_face_hz: Optional[float] = Field(None, ge=0)
    achieved_pose_hz: Optional[float] = Field(None, ge=0)
    achieved_hand_hz: Optional[float] = Field(None, ge=0)

    video_width: Optional[int] = Field(None, gt=0)
    video_height: Optional[int] = Field(None, gt=0)

    degradation_tier: Literal["high", "medium", "low", "minimal"] = "high"
    tier_changes: int = 0

    framing: Literal[
        "good", "too_close", "too_far", "off_center", "shoulders_cropped", "unknown"
    ] = "unknown"
    framing_override: bool = Field(
        False, description="User dismissed the framing warning with 'continue anyway'"
    )
    brightness_ok: Optional[bool] = None

    model_versions: dict = Field(
        default_factory=dict,
        description="{face,pose,hand} -> pinned model revision, from public/mediapipe/manifest.json. "
        "Stored because these aggregates are longitudinal and blendshape behaviour shifts "
        "between model revisions.",
    )
    user_agent_hint: Optional[str] = Field(
        None, max_length=64, description="Coarse bucket, e.g. 'chrome-desktop'. Not a full UA string."
    )


class VideoCalibration(_VideoModel):
    """Where "looking at the camera" was established to be, in head-pose terms.

    Without this, gaze is meaningless. The webcam sits above the screen, so a user attentively
    watching the on-screen panel reads as 6-18 degrees "down" and a naive threshold scores them
    near 0% eye contact. `method` is what the scorer keys off when deciding whether
    `gaze.on_camera_pct` is quotable or whether it must fall back to the robust
    `1 - down_pct - offscreen_pct`.
    """

    performed: bool = False
    method: Literal["on_screen_target", "session_baseline", "none"] = "none"

    baseline_yaw_deg: Optional[float] = None
    baseline_pitch_deg: Optional[float] = None

    # Half-width of the "on camera" cone, widened for users who cannot hold still so that
    # restlessness costs precision rather than producing a false negative.
    yaw_tolerance_deg: Optional[float] = Field(None, ge=0, le=90)
    pitch_tolerance_deg: Optional[float] = Field(None, ge=0, le=90)

    screen_offset_pitch_deg: Optional[float] = Field(
        None, description="Angular delta between 'at the lens' and 'at the app panel'. "
        "This is what separates looking at the AI from reading notes on the desk."
    )
    iris_gain_deg_per_unit: Optional[float] = Field(
        None, description="Fitted k in gaze = head_angle + k * iris_offset. None => head-pose only "
        "(e.g. reflective glasses made the iris landmarks unusable)."
    )

    quality: Literal["good", "weak", "failed"] = "failed"


class GazeMetrics(_VideoModel):
    """Percentages are frame-weighted; *episodes* are dwell-gated (>=700ms).

    A 300ms glance away therefore lowers `on_camera_pct` but contributes zero to
    `away_episodes`. Both are correct; they answer different questions.
    """

    on_camera_pct: Optional[float] = Field(None, ge=0, le=100)
    on_screen_pct: Optional[float] = Field(None, ge=0, le=100)
    down_pct: Optional[float] = Field(None, ge=0, le=100)
    side_pct: Optional[float] = Field(None, ge=0, le=100)
    up_pct: Optional[float] = Field(None, ge=0, le=100)
    offscreen_pct: Optional[float] = Field(None, ge=0, le=100)

    longest_away_seconds: Optional[float] = Field(None, ge=0)
    away_episodes: Optional[int] = Field(None, ge=0)
    mean_away_seconds: Optional[float] = Field(None, ge=0)
    gaze_shift_rate_per_min: Optional[float] = Field(None, ge=0)
    eye_contact_consistency: Optional[float] = Field(
        None, ge=0, le=1, description="1 - normalised stddev of per-10s on_camera fraction. "
        "Distinguishes steady contact from one long stare plus one long lapse."
    )


class HeadMetrics(_VideoModel):
    stability: Optional[float] = Field(None, ge=0, le=100, description="Derived from angular velocity")
    mean_angular_speed_deg_s: Optional[float] = Field(None, ge=0)
    nod_count: Optional[int] = Field(None, ge=0)
    nod_rate_per_min: Optional[float] = Field(None, ge=0)
    shake_count: Optional[int] = Field(None, ge=0)
    tilt_mean_deg: Optional[float] = Field(None, description="Signed roll, baseline-subtracted")
    tilt_abs_mean_deg: Optional[float] = Field(None, ge=0)


class ExpressionMetrics(_VideoModel):
    """Derived from the 52 ARKit blendshapes the face model already emits.

    These are measurements, not emotion labels, and must never be rendered as one. "Your face
    stayed neutral 78% of the time" is defensible; "you looked sad" is not, and no blendshape
    supports it.
    """

    smile_pct: Optional[float] = Field(None, ge=0, le=100)
    smile_events: Optional[int] = Field(None, ge=0)
    smile_mean_intensity: Optional[float] = Field(None, ge=0, le=1)
    smile_peak_intensity: Optional[float] = Field(None, ge=0, le=1)
    neutral_pct: Optional[float] = Field(None, ge=0, le=100)
    brow_raise_pct: Optional[float] = Field(None, ge=0, le=100)
    mouth_open_pct: Optional[float] = Field(
        None, ge=0, le=100, description="Speaking proxy — cross-checks the audio transcript"
    )
    blink_count: Optional[int] = Field(None, ge=0)
    blink_rate_per_min: Optional[float] = Field(None, ge=0)
    blink_rate_reliable: bool = Field(
        False, description="False when achieved_face_hz < 12 — blinks last 100-400ms and are "
        "undersampled below that, so the rate must not be quoted."
    )
    expressiveness: Optional[float] = Field(
        None, ge=0, le=100, description="Variance of blendshape activation over the session"
    )


class PostureMetrics(_VideoModel):
    """All of this requires visible shoulders. When the torso is cropped every field here is
    None — head position alone is not posture, and approximating it produces exactly the kind
    of confident nonsense rule 1 exists to prevent."""

    score: Optional[float] = Field(None, ge=0, le=100)
    upright_pct: Optional[float] = Field(None, ge=0, le=100)
    slouch_pct: Optional[float] = Field(None, ge=0, le=100)
    shoulder_tilt_mean_deg: Optional[float] = Field(
        None, description="Baseline-subtracted — a tilted laptop lid rotates everything by a constant"
    )
    lean_forward_pct: Optional[float] = Field(None, ge=0, le=100)
    lean_back_pct: Optional[float] = Field(None, ge=0, le=100)
    lean_side_pct: Optional[float] = Field(None, ge=0, le=100)
    sway_amplitude: Optional[float] = Field(
        None, ge=0, description="In shoulder-width units, never pixels"
    )
    sway_rate_per_min: Optional[float] = Field(None, ge=0, description="Direction reversals/min")
    posture_shifts: Optional[int] = Field(None, ge=0, description="Sustained (>2s) baseline changes")
    torso_visible_pct: Optional[float] = Field(None, ge=0, le=100)


class GestureMetrics(_VideoModel):
    """Two tiers with different availability.

    Pose-derived (count, rate, amplitude, symmetry, two-handed) needs only the wrists, which
    come free with the pose model. Hand-derived (open palm, pointing, clasped, precise face
    touch) needs the hand model, which the degradation ladder switches off first. So the
    pose tier survives on weak devices while the finger-level tier goes None.

    `arms_crossed_pct` and `hands_clasped_pct` are percentages of HAND-VISIBLE frames, not of
    the session. Read against `hands_visible_pct` or they overstate.
    """

    count: Optional[int] = Field(None, ge=0)
    rate_per_min: Optional[float] = Field(None, ge=0)
    mean_amplitude: Optional[float] = Field(None, ge=0, description="Shoulder-width units")
    peak_amplitude: Optional[float] = Field(None, ge=0)
    symmetry: Optional[float] = Field(None, ge=0, le=1, description="1 = balanced left/right")
    two_handed_pct: Optional[float] = Field(None, ge=0, le=100)

    hands_visible_pct: Optional[float] = Field(None, ge=0, le=100)
    hands_below_frame_pct: Optional[float] = Field(None, ge=0, le=100)

    arms_crossed_pct: Optional[float] = Field(None, ge=0, le=100)
    hands_clasped_pct: Optional[float] = Field(None, ge=0, le=100)
    face_touch_count: Optional[int] = Field(None, ge=0)
    pocket_or_still_pct: Optional[float] = Field(None, ge=0, le=100)

    open_palm_pct: Optional[float] = Field(None, ge=0, le=100)
    pointing_count: Optional[int] = Field(None, ge=0)
    fidget_score: Optional[float] = Field(None, ge=0, le=100)


class MovementMetrics(_VideoModel):
    energy: Optional[float] = Field(None, ge=0, le=100, description="Head + torso + hand composite")
    stillness_pct: Optional[float] = Field(None, ge=0, le=100)
    restlessness_pct: Optional[float] = Field(None, ge=0, le=100)


class VideoTimeline(_VideoModel):
    """Fixed-channel parallel arrays, not an array of objects — six channels over 300 bins is
    ~9KB this way and several times that as objects.

    `face_present` is not optional in spirit: without it a reader cannot tell "eye contact
    dropped" from "we lost the face", which is the whole distinction this feature is built on.
    """

    bin_seconds: float = Field(1.0, gt=0, le=60)
    start_offset_seconds: float = Field(0.0, ge=0)
    length: int = Field(0, ge=0, le=MAX_VIDEO_TIMELINE_BINS)

    eye_contact: List[Optional[float]] = Field(default_factory=list)
    posture: List[Optional[float]] = Field(default_factory=list)
    gesture_activity: List[Optional[float]] = Field(default_factory=list)
    smile: List[Optional[float]] = Field(default_factory=list)
    movement: List[Optional[float]] = Field(default_factory=list)
    face_present: List[Optional[float]] = Field(default_factory=list)

    @model_validator(mode="after")
    def _channels_agree(self):
        """Every channel must be exactly `length` long.

        Enforced rather than tolerated because the sparkline renders channels against a shared
        x-axis: a short array silently misaligns every later bin, which looks like real data.
        """
        for name in TIMELINE_CHANNELS:
            channel = getattr(self, name)
            if len(channel) > MAX_VIDEO_TIMELINE_BINS:
                raise ValueError(
                    f"timeline.{name} has {len(channel)} bins, over the "
                    f"{MAX_VIDEO_TIMELINE_BINS} cap; the client should downsample to a larger "
                    f"bin_seconds instead"
                )
            if len(channel) != self.length:
                raise ValueError(
                    f"timeline.{name} has {len(channel)} bins but length is {self.length}; "
                    f"all channels share one x-axis and must agree"
                )
        return self


class VideoFeaturesSchema(_VideoModel):
    """The full payload a browser session POSTs alongside its transcript."""

    schema_version: int = Field(VIDEO_FEATURES_SCHEMA_VERSION, ge=1)

    duration_seconds: float = Field(
        0.0, ge=0, description="Analysis-ACTIVE seconds. Excludes time with the tab hidden, so "
        "it is not wall clock and not necessarily the audio duration."
    )
    status: Literal["ok", "partial", "insufficient_data"] = "insufficient_data"
    unavailable_reasons: List[str] = Field(
        default_factory=list,
        max_length=32,
        description="Machine-readable codes, e.g. 'face_coverage_0.41', "
        "'hands_disabled_by_degradation'. Surfaced to the user as the reason a tile shows a dash.",
    )

    quality: VideoQuality = Field(default_factory=VideoQuality)
    calibration: VideoCalibration = Field(default_factory=VideoCalibration)

    gaze: GazeMetrics = Field(default_factory=GazeMetrics)
    head: HeadMetrics = Field(default_factory=HeadMetrics)
    expression: ExpressionMetrics = Field(default_factory=ExpressionMetrics)
    posture: PostureMetrics = Field(default_factory=PostureMetrics)
    gesture: GestureMetrics = Field(default_factory=GestureMetrics)
    movement: MovementMetrics = Field(default_factory=MovementMetrics)

    timeline: VideoTimeline = Field(default_factory=VideoTimeline)
