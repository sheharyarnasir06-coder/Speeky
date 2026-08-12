"""
Video (physical delivery) scoring — the VIDEO sibling of lib/session_scorer.py.

lib/session_scorer.py turns audio signal into fluency/pronunciation. This module turns the
browser's video_features aggregate into presence sub-scores plus the qualitative issues and
highlights the coaching layer surfaces. The two are parallel and independent: nothing here
touches an existing score.

Three properties matter more than the arithmetic:

**It re-derives every coverage gate itself.** `quality.*` is computed on a client we do not
control, so a payload claiming 100% eye contact over 3% face detection is rejected here rather
than believed. This is the same posture as `_calculate_wpm` recomputing WPM from the transcript
instead of trusting a client-supplied number.

**`None` propagates.** Every metric in video_features is optional, and a missing family must
produce a missing sub-score, never a zero. `ScoredVideo.gesture_score is None` means "we could
not see the hands"; `0.0` would mean "the speaker did not move", and the difference is the
whole point.

**`confidence_weight` is the safety valve.** It answers "how much should anything downstream
trust this?" — 1.0 for a calibrated, well-framed, full-coverage session, tapering to 0.0 for an
unusable one. The prompt builder refuses to mention video below 0.5, because an LLM handed
"eye contact 12%" will coach the user about it confidently no matter how the number is hedged.

Deliberately dependency-light: this module imports nothing from services/. That single rule is
what lets the Interview Coach reuse it unchanged.
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Gating thresholds ─────────────────────────────────────────────────────────
# Below this fraction of expected detections, a family's metrics are not reported at all.
# 0.6 is deliberately lenient: MediaPipe drops frames during natural head turns, and gating at
# a stricter value nulls out normal speakers.
_FAMILY_COVERAGE_MIN_PCT = 60.0

# Session-level floors. Under either, nothing is scored.
_SESSION_FACE_MIN_PCT = 50.0
_MIN_DURATION_S = 20.0
_MIN_FRAMES_ANALYZED = 100

# Blink rate is undersampled below this; the client sets blink_rate_reliable from it too, but we
# re-check rather than trust.
_BLINK_RELIABLE_MIN_HZ = 12.0

# Weight multipliers applied to the final confidence, worst-case wins.
_CALIBRATION_WEIGHTS = {"good": 1.0, "weak": 0.5, "failed": 0.35}
_CALIBRATION_METHOD_WEIGHTS = {"on_screen_target": 1.0, "session_baseline": 0.6, "none": 0.35}
_TIER_WEIGHTS = {"high": 1.0, "medium": 0.9, "low": 0.75, "minimal": 0.55}

# Ceiling on the classroom gaze-scan bonus. A bonus, never enough to carry a poor delivery.
_GAZE_SCAN_MAX_BONUS = 8.0


class VideoRejectionReason(str, Enum):
    """Canonical capture-quality reason codes.

    Named "rejection" historically, when hitting one meant the session went unscored. It no
    longer does — see `_session_warnings`. These now qualify a score rather than replace it, and
    the UI renders each alongside the numbers so the user knows which measurement to distrust.
    The vocabulary is unchanged so stored scorecards stay readable.
    """

    NO_FACE_DETECTED = "no_face_detected"
    FACE_COVERAGE_TOO_LOW = "face_coverage_too_low"
    TOO_DARK = "too_dark"
    CLIP_TOO_SHORT = "clip_too_short"
    FRAMING_UNUSABLE = "framing_unusable"
    DEVICE_TOO_SLOW = "device_too_slow"
    CAMERA_STOPPED_EARLY = "camera_stopped_early"


@dataclass
class ScoredVideo:
    """Result of the VIDEO pipeline. Every sub-score is None when unmeasurable."""

    eye_contact_score: Optional[float] = None
    posture_score: Optional[float] = None
    gesture_score: Optional[float] = None
    expression_score: Optional[float] = None
    stillness_score: Optional[float] = None

    visual_presence: Optional[float] = None
    confidence_weight: float = 0.0

    #: The worst capture-quality problem, or None. Retained for stored-scorecard compatibility;
    #: it no longer suppresses the scores, it only labels them.
    rejection: Optional[VideoRejectionReason] = None
    #: Every capture-quality problem, worst first. The UI names each one next to the numbers.
    warnings: List[VideoRejectionReason] = field(default_factory=list)
    issues: List[Dict] = field(default_factory=list)
    highlights: List[Dict] = field(default_factory=list)
    detail: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        """Shape stored on the scorecard and rendered by VideoPresenceScorecardSection."""
        return {
            "eye_contact": self.eye_contact_score,
            "posture": self.posture_score,
            "gestures": self.gesture_score,
            "expression": self.expression_score,
            "stillness": self.stillness_score,
            "visual_presence": self.visual_presence,
            "confidence_weight": round(self.confidence_weight, 3),
            "rejection": self.rejection.value if self.rejection else None,
            "warnings": [w.value for w in self.warnings],
            "issues": self.issues,
            "highlights": self.highlights,
            "detail": self.detail,
        }


# ── Small helpers ─────────────────────────────────────────────────────────────
def _num(source: Optional[Dict], key: str) -> Optional[float]:
    """Read a numeric leaf, treating absent / null / non-numeric alike as 'not measured'.

    Bools are excluded explicitly: `isinstance(True, int)` is True in Python, and a stray
    boolean silently scoring as 1.0 is exactly the kind of bug that survives review.
    """
    if not source:
        return None
    value = source.get(key)
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _band(value: Optional[float], ideal_low: float, ideal_high: float, span: float) -> Optional[float]:
    """Score how close `value` sits to an ideal *range* rather than a single target.

    Inside the band scores 100; outside it falls off linearly, reaching 0 at `span` beyond the
    edge. Used for metrics with a healthy middle — too few gestures reads as stiff, too many as
    frantic, and both deserve to lose points.
    """
    if value is None:
        return None
    if ideal_low <= value <= ideal_high:
        return 100.0
    distance = ideal_low - value if value < ideal_low else value - ideal_high
    return _clamp(100.0 - (distance / span) * 100.0)


def _mean(values: List[Optional[float]]) -> Optional[float]:
    present = [v for v in values if v is not None]
    if not present:
        return None
    return sum(present) / len(present)


# ── Coverage gating ───────────────────────────────────────────────────────────
def _session_warnings(features: Dict) -> List[VideoRejectionReason]:
    """Every capture-quality problem this session hit, worst first.

    These used to be *rejections*: the first match short-circuited scoring and the user was told
    "Delivery not measured" with no numbers at all. That was the wrong trade. A speaker who turned
    their camera on wants to see what was measured, and a caveated number they can interpret beats
    a blank panel they cannot — especially since a single failing check (body out of frame, say)
    usually leaves the other families perfectly measurable.

    So every check still runs, but the result is now advisory. Scoring continues; each violated
    metric is named to the user, and `_confidence_weight` already discounts the figures. The one
    thing that never happens is inventing a number: a family with no data still scores None,
    because the warning explains an absence rather than papering over one.

    Derived from `quality` rather than the client's `status`, which is advisory — a client bug,
    an old client, or a hand-crafted payload must not be able to talk its way into a clean read.
    """
    quality = features.get("quality") or {}
    warnings: List[VideoRejectionReason] = []

    face_pct = _num(quality, "face_detected_pct")
    if face_pct is None or face_pct <= 1.0:
        warnings.append(VideoRejectionReason.NO_FACE_DETECTED)
    elif face_pct < _SESSION_FACE_MIN_PCT:
        warnings.append(VideoRejectionReason.FACE_COVERAGE_TOO_LOW)

    if quality.get("brightness_ok") is False:
        warnings.append(VideoRejectionReason.TOO_DARK)

    duration = _num(features, "duration_seconds") or 0.0
    if duration < _MIN_DURATION_S:
        warnings.append(VideoRejectionReason.CLIP_TOO_SHORT)

    frames = _num(quality, "frames_analyzed") or 0.0
    if frames < _MIN_FRAMES_ANALYZED:
        warnings.append(VideoRejectionReason.DEVICE_TOO_SLOW)

    # framing_override means the user was warned and chose to continue; respect that rather
    # than flagging a session they deliberately started.
    if quality.get("framing") == "unknown" and not quality.get("framing_override"):
        warnings.append(VideoRejectionReason.FRAMING_UNUSABLE)

    if features.get("status") == "partial" or "camera_stopped_early" in (
        features.get("unavailable_reasons") or []
    ):
        warnings.append(VideoRejectionReason.CAMERA_STOPPED_EARLY)

    return warnings


def _family_available(quality: Dict, coverage_key: str) -> bool:
    coverage = _num(quality, coverage_key)
    return coverage is not None and coverage >= _FAMILY_COVERAGE_MIN_PCT


# ── Sub-scores ────────────────────────────────────────────────────────────────
def _gaze_scan_bonus(features: Dict, speech_config: Dict) -> float:
    """Small bonus for sweeping the room, for formats where holding one spot is the failure.

    Only `classroom` sets `reward_gaze_scan`. Everywhere else a high shift rate is neutral at
    best — a pitch delivered while scanning the room reads as shifty, not attentive — so this
    stays opt-in rather than becoming a general term.
    """
    if not speech_config.get("reward_gaze_scan"):
        return 0.0

    rate = _num(features.get("gaze") or {}, "gaze_shift_rate_per_min")
    if rate is None:
        return 0.0

    # Below ~4 shifts/min the speaker is fixed on one point; above ~20 they are darting.
    band = _band(rate, 4.0, 20.0, 10.0)
    if band is None:
        return 0.0

    # Capped at 8 points: a bonus, never enough to carry an otherwise poor delivery.
    return _clamp(band / 100.0 * _GAZE_SCAN_MAX_BONUS, 0.0, _GAZE_SCAN_MAX_BONUS)


def _score_eye_contact(features: Dict) -> tuple[Optional[float], Dict]:
    """Eye contact, using the honest metric for the calibration we actually have.

    With a proper two-target calibration, `on_camera_pct` means what it says and is used
    directly. Without one, the camera-relative baseline is guesswork, so we fall back to
    `100 - down - offscreen` — "not buried in my notes", which survives an uncalibrated
    baseline and is closer to what a speaker is judged on anyway.
    """
    gaze = features.get("gaze") or {}
    calibration = features.get("calibration") or {}

    calibrated = (
        calibration.get("method") == "on_screen_target"
        and calibration.get("quality") == "good"
    )

    on_camera = _num(gaze, "on_camera_pct")
    if calibrated and on_camera is not None:
        return _clamp(on_camera), {"basis": "on_camera_pct", "calibrated": True}

    down = _num(gaze, "down_pct")
    offscreen = _num(gaze, "offscreen_pct")
    if down is None and offscreen is None:
        # Last resort: an uncalibrated on_camera_pct is better than nothing, but it is a weak
        # signal and confidence_weight already reflects that.
        if on_camera is None:
            return None, {"basis": None, "calibrated": False}
        return _clamp(on_camera), {"basis": "on_camera_pct_uncalibrated", "calibrated": False}

    away = (down or 0.0) + (offscreen or 0.0)
    return _clamp(100.0 - away), {"basis": "not_looking_down", "calibrated": False}


def _score_posture(features: Dict, quality: Dict) -> Optional[float]:
    """Posture needs visible shoulders. Head position alone is not posture."""
    if not _family_available(quality, "pose_detected_pct"):
        return None

    posture = features.get("posture") or {}
    torso_visible = _num(posture, "torso_visible_pct")
    if torso_visible is not None and torso_visible < _FAMILY_COVERAGE_MIN_PCT:
        return None

    # Prefer the client's composite when present — it has per-frame detail we do not — but
    # rebuild it from parts when absent so a partial payload still scores.
    score = _num(posture, "score")
    if score is not None:
        return _clamp(score)

    upright = _num(posture, "upright_pct")
    slouch = _num(posture, "slouch_pct")
    if upright is None and slouch is None:
        return None
    if upright is None:
        upright = 100.0 - (slouch or 0.0)

    # Some sway is natural presence; a rigid speaker is not the goal. Only heavy sway
    # (>0.35 shoulder-widths) costs points.
    sway = _num(posture, "sway_amplitude")
    sway_penalty = 0.0 if sway is None else _clamp((sway - 0.35) * 100.0, 0.0, 25.0)

    return _clamp(upright - sway_penalty)


def _score_gestures(features: Dict, quality: Dict, speech_config: Dict) -> Optional[float]:
    """Gesture quality across the two tiers, whichever is available."""
    gesture = features.get("gesture") or {}

    hands_visible = _num(gesture, "hands_visible_pct")
    if hands_visible is None or hands_visible < 25.0:
        # A speaker gesturing below the laptop lid must not be scored "no gestures".
        return None

    rate = _num(gesture, "rate_per_min")
    # Energetic formats want more hand movement; a still motivational speaker reads as flat.
    if speech_config.get("prioritize_energy"):
        rate_score = _band(rate, 8.0, 20.0, 12.0)
    else:
        rate_score = _band(rate, 5.0, 15.0, 12.0)

    symmetry = _num(gesture, "symmetry")
    symmetry_score = None if symmetry is None else _clamp(symmetry * 100.0)

    fidget = _num(gesture, "fidget_score")
    fidget_score = None if fidget is None else _clamp(100.0 - fidget)

    return _mean([rate_score, symmetry_score, fidget_score])


def _score_expression(features: Dict, quality: Dict, speech_config: Dict) -> Optional[float]:
    """Expressiveness, with the neutral target depending on the format.

    A wedding toast delivered deadpan is a failure; a business pitch does not need the same
    warmth. `prioritize_warmth` shifts the ideal smile band rather than applying a flat penalty.
    """
    if not _family_available(quality, "face_detected_pct"):
        return None

    expression = features.get("expression") or {}

    if speech_config.get("prioritize_warmth"):
        smile_score = _band(_num(expression, "smile_pct"), 20.0, 60.0, 30.0)
    else:
        smile_score = _band(_num(expression, "smile_pct"), 8.0, 40.0, 30.0)

    expressiveness = _num(expression, "expressiveness")
    expressiveness_score = None if expressiveness is None else _clamp(expressiveness)

    return _mean([smile_score, expressiveness_score])


def _score_stillness(features: Dict, quality: Dict) -> Optional[float]:
    """Composure: steady head, no restless drift. Not the same as being motionless."""
    head = features.get("head") or {}
    movement = features.get("movement") or {}

    stability = _num(head, "stability")
    restlessness = _num(movement, "restlessness_pct")
    restless_score = None if restlessness is None else _clamp(100.0 - restlessness)

    return _mean([stability, restless_score])


# ── Confidence weighting ──────────────────────────────────────────────────────
def _confidence_weight(features: Dict) -> float:
    """How much anything downstream should trust these numbers, in [0, 1].

    Multiplicative rather than additive: several mild problems compound, which is right —
    a weakly-calibrated session on a struggling device at partial coverage really is much
    less trustworthy than one with any single one of those issues.
    """
    quality = features.get("quality") or {}
    calibration = features.get("calibration") or {}

    weight = 1.0
    weight *= _CALIBRATION_WEIGHTS.get(str(calibration.get("quality")), 0.35)
    weight *= _CALIBRATION_METHOD_WEIGHTS.get(str(calibration.get("method")), 0.35)
    weight *= _TIER_WEIGHTS.get(str(quality.get("degradation_tier")), 0.55)

    face_pct = _num(quality, "face_detected_pct")
    if face_pct is not None:
        # Full credit at >=90% coverage, tapering to 0 at the session floor.
        span = 90.0 - _SESSION_FACE_MIN_PCT
        weight *= _clamp((face_pct - _SESSION_FACE_MIN_PCT) / span, 0.0, 1.0) if face_pct < 90 else 1.0

    duration = _num(features, "duration_seconds") or 0.0
    if duration < 60.0:
        # Short clips are noisy regardless of how clean the capture was.
        weight *= _clamp(duration / 60.0, 0.3, 1.0)

    if features.get("status") == "partial":
        weight *= 0.8

    if quality.get("framing_override"):
        weight *= 0.85

    return round(_clamp(weight, 0.0, 1.0), 3)


# ── Issues and highlights ─────────────────────────────────────────────────────
def _build_issues(features: Dict, scores: Dict[str, Optional[float]]) -> List[Dict]:
    """Deterministic, LLM-free findings — same {type,message,suggestion} shape as
    public_speaking_service._generate_flags, so they merge into the existing flags list.

    These exist so the feature still delivers value with no GROQ_API_KEY configured.
    """
    issues: List[Dict] = []
    gaze = features.get("gaze") or {}
    posture = features.get("posture") or {}
    gesture = features.get("gesture") or {}

    # Every block below is gated on its family's sub-score being present, NOT on the raw metric
    # being non-null. The raw numbers survive even when the family was gated out — a session
    # with the hands out of frame still carries rate_per_min: 0.0 — and reading them directly
    # is how "we couldn't see your hands" turns into "you never gestured".
    eye_contact = scores.get("eye_contact")
    posture_available = scores.get("posture") is not None
    gesture_available = scores.get("gestures") is not None

    if eye_contact is not None and eye_contact < 50:
        down = _num(gaze, "down_pct")
        where = f" You looked down {down:.0f}% of the time." if down is not None else ""
        issues.append({
            "type": "low_eye_contact",
            "message": f"Eye contact was held about {eye_contact:.0f}% of the session.{where}",
            "suggestion": "Try glancing at your notes between points rather than reading from them.",
        })

    longest_away = _num(gaze, "longest_away_seconds")
    if eye_contact is not None and longest_away is not None and longest_away >= 8.0:
        issues.append({
            "type": "long_look_away",
            "message": f"Your longest stretch looking away lasted {longest_away:.1f} seconds.",
            "suggestion": "Break long passages into shorter chunks so you can look up between them.",
        })

    slouch = _num(posture, "slouch_pct")
    if posture_available and slouch is not None and slouch >= 30:
        issues.append({
            "type": "slouched_posture",
            "message": f"Your shoulders were slouched for {slouch:.0f}% of the session.",
            "suggestion": "Reset your shoulders back and down before you begin, and again at each new point.",
        })

    sway = _num(posture, "sway_amplitude")
    if posture_available and sway is not None and sway >= 0.5:
        issues.append({
            "type": "excessive_sway",
            "message": "You swayed noticeably while speaking.",
            "suggestion": "Plant both feet and let your hands carry the movement instead.",
        })

    gesture_rate = _num(gesture, "rate_per_min")
    if gesture_available and gesture_rate is not None and gesture_rate < 3.0:
        issues.append({
            "type": "few_gestures",
            "message": f"You gestured about {gesture_rate:.1f} times per minute.",
            "suggestion": "Let your hands mark structure — one gesture per key point is enough.",
        })

    arms_crossed = _num(gesture, "arms_crossed_pct")
    if gesture_available and arms_crossed is not None and arms_crossed >= 25:
        issues.append({
            "type": "closed_body_language",
            "message": f"Your arms were crossed for {arms_crossed:.0f}% of the time your hands were visible.",
            "suggestion": "Keep your hands apart and open — it reads as more receptive.",
        })

    face_touch = _num(gesture, "face_touch_count")
    if gesture_available and face_touch is not None and face_touch >= 5:
        issues.append({
            "type": "face_touching",
            "message": f"You touched your face {face_touch:.0f} times.",
            "suggestion": "This usually signals nerves; try resting your hands ready to gesture instead.",
        })

    return issues


def _build_highlights(features: Dict, scores: Dict[str, Optional[float]]) -> List[Dict]:
    highlights: List[Dict] = []

    eye_contact = scores.get("eye_contact")
    if eye_contact is not None and eye_contact >= 75:
        highlights.append({
            "kind": "strong_eye_contact",
            "message": f"You held eye contact about {eye_contact:.0f}% of the session — that reads as confident.",
        })

    posture_score = scores.get("posture")
    if posture_score is not None and posture_score >= 75:
        highlights.append({
            "kind": "strong_posture",
            "message": "Your posture stayed open and upright throughout.",
        })

    # Reads scores rather than raw metrics for the same reason _build_issues does: praising
    # "balanced gestures" for a session where the hands were never visible is its own kind of
    # wrong.
    gesture_score = scores.get("gestures")
    symmetry = _num(features.get("gesture") or {}, "symmetry")
    if gesture_score is not None and gesture_score >= 70 and (symmetry is None or symmetry >= 0.7):
        highlights.append({
            "kind": "natural_gestures",
            "message": "Your gestures were well-paced and balanced across both hands.",
        })

    return highlights


# ── Entry point ───────────────────────────────────────────────────────────────
def score_video_session(features: Optional[Dict], speech_config: Optional[Dict] = None) -> ScoredVideo:
    """Score a browser-supplied video_features payload.

    `speech_config` is the same per-format switch dict the audio path already uses
    (public_speaking_service.SPEECH_TYPES), passed in rather than imported so this module stays
    free of any dependency on services/ — that is what makes it reusable by the Interview Coach.

    Always scores whatever was measurable. A capture-quality problem produces a `warnings` entry
    and a lower `confidence_weight`, never a blank panel — see `_session_warnings`. Sub-scores
    are still None where a family genuinely had no data; a warning explains an absence rather
    than filling it in.

    Never raises on malformed input: a broken camera must not fail a submission the user already
    completed.
    """
    if not features:
        return ScoredVideo()

    config = speech_config or {}
    quality = features.get("quality") or {}

    warnings = _session_warnings(features)

    eye_contact_score, eye_contact_detail = _score_eye_contact(features)
    scores: Dict[str, Optional[float]] = {
        "eye_contact": eye_contact_score,
        "posture": _score_posture(features, quality),
        "gestures": _score_gestures(features, quality, config),
        "expression": _score_expression(features, quality, config),
        "stillness": _score_stillness(features, quality),
    }

    weights = _presence_weights(config)
    visual_presence = _weighted_presence(scores, weights)
    if visual_presence is not None:
        visual_presence = _clamp(visual_presence + _gaze_scan_bonus(features, config))

    blink_hz = _num(quality, "achieved_face_hz")
    blink_reliable = bool(
        features.get("expression", {}).get("blink_rate_reliable")
        and blink_hz is not None
        and blink_hz >= _BLINK_RELIABLE_MIN_HZ
    )

    return ScoredVideo(
        eye_contact_score=_round(scores["eye_contact"]),
        posture_score=_round(scores["posture"]),
        gesture_score=_round(scores["gestures"]),
        expression_score=_round(scores["expression"]),
        stillness_score=_round(scores["stillness"]),
        visual_presence=_round(visual_presence),
        confidence_weight=_confidence_weight(features),
        # Kept populated so anything reading the old field still sees the headline problem; it no
        # longer gates rendering.
        rejection=warnings[0] if warnings else None,
        warnings=warnings,
        issues=_build_issues(features, scores),
        highlights=_build_highlights(features, scores),
        detail={
            "status": features.get("status"),
            "unavailable_reasons": features.get("unavailable_reasons") or [],
            "duration_seconds": _num(features, "duration_seconds"),
            "eye_contact_basis": eye_contact_detail.get("basis"),
            "calibrated": eye_contact_detail.get("calibrated"),
            "degradation_tier": quality.get("degradation_tier"),
            "face_detected_pct": _num(quality, "face_detected_pct"),
            "blink_rate_reliable": blink_reliable,
            "weights": weights,
        },
    )


def _presence_weights(speech_config: Dict) -> Dict[str, float]:
    """Per-format emphasis, driven by the switches SPEECH_TYPES already declares.

    Reusing those switches rather than adding a parallel table means a new speech type gets
    sensible video weighting for free, and the two pipelines can't drift apart.
    """
    weights = {
        "eye_contact": 0.30,
        "posture": 0.20,
        "gestures": 0.20,
        "expression": 0.15,
        "stillness": 0.15,
    }

    if speech_config.get("prioritize_energy"):
        weights.update({"gestures": 0.28, "expression": 0.22, "stillness": 0.05})
    if speech_config.get("prioritize_storytelling") or speech_config.get("prioritize_engagement"):
        weights.update({"eye_contact": 0.38, "expression": 0.20, "posture": 0.15})
    if speech_config.get("prioritize_structure"):
        # Fidgeting during a pitch reads as under-prepared, so composure carries more here.
        weights.update({"posture": 0.26, "stillness": 0.22, "expression": 0.10})
    if speech_config.get("prioritize_warmth") or speech_config.get("disable_corporate_tone"):
        weights.update({"expression": 0.28, "posture": 0.12})

    total = sum(weights.values())
    return {key: round(value / total, 4) for key, value in weights.items()}


def _weighted_presence(scores: Dict[str, Optional[float]], weights: Dict[str, float]) -> Optional[float]:
    """Weighted mean over whichever sub-scores exist, renormalised across those.

    Renormalising rather than treating a missing family as zero is the difference between
    "we couldn't see your hands" and "you have no stage presence".
    """
    present = [(weights.get(key, 0.0), value) for key, value in scores.items() if value is not None]
    total_weight = sum(weight for weight, _ in present)
    if not present or total_weight <= 0:
        return None
    return sum(weight * value for weight, value in present) / total_weight


def _round(value: Optional[float]) -> Optional[float]:
    return None if value is None else round(value, 1)
