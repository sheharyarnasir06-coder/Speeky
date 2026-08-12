"""
Emotional register — does the delivery match the register this scenario calls for?

A wedding toast delivered deadpan and a business pitch delivered deadpan currently score
identically. They should not: the same flat delivery is a failure in one and unremarkable in the
other. This module scores the *match* between how someone delivered and what the occasion asks
for, per speech type.

**It never emits an emotion label**, and that constraint is doing real work rather than being
cautious for its own sake:

  - Vocal **arousal** — energy, pitch movement, dynamic range — is reliably measurable from
    acoustics, and `prosody_engine` already computes everything needed.
  - Vocal **valence** — happy versus sad from voice alone — is not reliably measurable, by this
    pipeline or by considerably heavier ones. So valence is inferred from the face and the
    words, and never claimed from the voice.

This is the same doctrine already written into `schemas/video_features_schema.py`: *"These are
measurements, not emotion labels… 'you looked sad' is not [defensible]."* Extended here to
sound. The output is "your delivery stayed flat for a toast", never "you seemed unhappy".

Three independent channels, each `None` when its source is absent:

  voice  — arousal, from pitch range + dynamic range + level        (voice sessions only)
  face   — warmth, from smile and expressiveness                    (camera sessions only)
  words  — formality, from a lexicon over the transcript            (always)

Deliberately dependency-light: imports nothing from `services/`, exactly like
`lib/video_scorer.py`, so the Interview Coach can reuse it unchanged.
"""

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# ── Arousal calibration ───────────────────────────────────────────────────────
# Bands are in the units the pipeline actually reports, so they are checkable against a real
# session rather than being abstract 0-100 knobs.

# Pitch range, semitones. Below ~3 is the monotone threshold lib/speech_config.py already uses
# for intonation; ~12 is an animated speaker. Mirrors intonation_ideal_range_*_semitones.
_PITCH_RANGE_FLAT = 3.0
_PITCH_RANGE_ANIMATED = 12.0

# Intensity spread, dB. A near-constant level sits under ~2dB; a speaker working the dynamics
# runs ~8dB or more.
_INTENSITY_FLAT_DB = 2.0
_INTENSITY_ANIMATED_DB = 8.0

# Level, dBFS. Reuses the same quiet threshold as public_speaking_service.MIC_QUIET_DB so a
# quiet mic doesn't read as a subdued speaker.
_LEVEL_QUIET_DBFS = -45.0
_LEVEL_STRONG_DBFS = -18.0

# ── Formality lexicon ─────────────────────────────────────────────────────────
# A deliberately small, transparent word list rather than a model. It extends the
# `emotional_peak` keyword pattern already in _evaluate_structure, and a reader can audit
# exactly why a session was called warm or formal — which matters when the score is shown back
# to the user as coaching.

_WARM_MARKERS = (
    r"\bthank you\b", r"\bgrateful\b", r"\bproud\b", r"\blove\b", r"\bfriend",
    r"\bhonou?r(ed)?\b", r"\bjoy", r"\bcelebrat", r"\bwonderful\b", r"\bdear\b",
    r"\bheart", r"\bfamily\b", r"\btogether\b", r"\bcherish",
)
_HUMOUR_MARKERS = (
    r"\blaugh", r"\bjoke", r"\bfunny\b", r"\bhilarious\b", r"\bha ha\b", r"\bhaha\b",
)
_FORMAL_MARKERS = (
    r"\btherefore\b", r"\bfurthermore\b", r"\bconsequently\b", r"\bmoreover\b",
    r"\bwe propose\b", r"\bin conclusion\b", r"\brevenue\b", r"\bstrateg", r"\bobjective",
    r"\bdeliverable", r"\bstakeholder", r"\broadmap\b", r"\bmarket\b", r"\bquarter",
)
_INFORMAL_MARKERS = (
    r"\bgonna\b", r"\bkinda\b", r"\byeah\b", r"\bguys\b", r"\bstuff\b", r"\bawesome\b",
    r"\bcool\b", r"\bhey\b", r"\bok(ay)?\b",
)


@dataclass
class ScoredRegister:
    """Per-channel match scores plus a combined figure. `None` means the channel had no source."""

    voice_arousal: Optional[float] = None
    face_warmth: Optional[float] = None
    word_formality: Optional[float] = None

    emotional_register: Optional[float] = None
    confidence_weight: float = 0.0

    issues: List[Dict] = field(default_factory=list)
    highlights: List[Dict] = field(default_factory=list)
    detail: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "voice_arousal": self.voice_arousal,
            "face_warmth": self.face_warmth,
            "word_formality": self.word_formality,
            "emotional_register": self.emotional_register,
            "confidence_weight": round(self.confidence_weight, 3),
            "issues": self.issues,
            "highlights": self.highlights,
            "detail": self.detail,
        }


# ── Helpers ───────────────────────────────────────────────────────────────────
def _num(source: Optional[Dict], key: str) -> Optional[float]:
    """Read a numeric leaf; absent, null, or a stray bool all mean 'not measured'.

    Bools are excluded explicitly — `isinstance(True, int)` is True in Python, and a boolean
    silently scoring as 1.0 is the kind of bug that survives review.
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


def _scale(value: Optional[float], low: float, high: float) -> Optional[float]:
    """Map a raw measurement onto 0-100 between two calibrated anchors."""
    if value is None or high <= low:
        return None
    return _clamp((value - low) / (high - low) * 100.0)


def _band_match(value: Optional[float], band: Optional[Tuple[float, float]]) -> Optional[float]:
    """How well a 0-100 value sits inside an expected band.

    Inside scores 100. Outside, the score falls linearly to 0 at the nearest extreme — 0 for a
    value below the band, 100 for one above.

    Deliberately NOT scaled by band width. Scaling the falloff that way makes a wide band
    lenient in both directions, which is backwards: a toast's wide acceptable-warmth range
    (20-65) then forgave a face measured at 9, scoring it 75/100 when it was plainly deadpan.
    Falling off toward the extreme instead asks the honest question — how far through the wrong
    region did this land — and gives the same answer regardless of how generous the band is.
    """
    if value is None or not band:
        return None
    low, high = band
    if low <= value <= high:
        return 100.0
    if value < low:
        return _clamp((value / low) * 100.0) if low > 0 else 0.0
    return _clamp(((100.0 - value) / max(100.0 - high, 1.0)) * 100.0)


# ── Channels ──────────────────────────────────────────────────────────────────
def _measure_arousal(audio: Optional[Dict]) -> Optional[float]:
    """Vocal energy, 0-100, from pitch movement, dynamic range and level.

    Averaged over whichever components are present rather than requiring all three, so an older
    client that only sends `pitch_range_semitones` still produces a usable (if coarser) reading
    instead of nothing.
    """
    if not audio:
        return None

    parts = [
        _scale(_num(audio, "pitch_range_semitones"), _PITCH_RANGE_FLAT, _PITCH_RANGE_ANIMATED),
        _scale(_num(audio, "intensity_variation_db"), _INTENSITY_FLAT_DB, _INTENSITY_ANIMATED_DB),
        _scale(_num(audio, "avg_db"), _LEVEL_QUIET_DBFS, _LEVEL_STRONG_DBFS),
    ]
    present = [p for p in parts if p is not None]
    return sum(present) / len(present) if present else None


def _measure_warmth(video: Optional[Dict]) -> Optional[float]:
    """Facial warmth, 0-100, from the video scorer's expression block.

    Reads `smile_pct` and `expressiveness` — measurements, not an emotion label. Returns None
    when the camera was off or the face was never measurable, never 0.
    """
    if not video:
        return None

    expression = video.get("expression") or {}
    smile = _num(expression, "smile_pct")
    expressiveness = _num(expression, "expressiveness")

    present = [p for p in (smile, expressiveness) if p is not None]
    if not present:
        return None
    # Smile carries the warmth signal; expressiveness only supports it, so it is weighted less.
    if smile is not None and expressiveness is not None:
        return _clamp(smile * 0.65 + expressiveness * 0.35)
    return _clamp(present[0])


def _measure_formality(text: str) -> Optional[float]:
    """Lexical register, 0-100, where 100 is formal and 0 is casual.

    Returns None for text too short to judge — a two-sentence transcript has no register worth
    reading, and guessing from it would be noise dressed as a measurement.
    """
    if not text or len(text.split()) < 20:
        return None

    lowered = text.lower()
    formal = sum(len(re.findall(pattern, lowered)) for pattern in _FORMAL_MARKERS)
    informal = sum(len(re.findall(pattern, lowered)) for pattern in _INFORMAL_MARKERS)

    total = formal + informal
    if total == 0:
        return 50.0  # neutral register — neither markedly formal nor casual
    return _clamp((formal / total) * 100.0)


def count_warmth_markers(text: str) -> Dict[str, int]:
    """Warmth and humour marker counts, surfaced for feedback copy rather than scoring."""
    lowered = (text or "").lower()
    return {
        "warmth": sum(len(re.findall(p, lowered)) for p in _WARM_MARKERS),
        "humour": sum(len(re.findall(p, lowered)) for p in _HUMOUR_MARKERS),
    }


# ── Entry point ───────────────────────────────────────────────────────────────
def score_register(
    text: str,
    audio_features: Optional[Dict],
    video: Optional[Dict],
    speech_config: Optional[Dict] = None,
) -> ScoredRegister:
    """Score how well the delivery matched this scenario's expected register.

    `speech_config` is the same per-format dict the audio and video paths already use
    (`public_speaking_service.SPEECH_TYPES`), passed in rather than imported so this module
    stays free of any dependency on `services/`.

    `video` is `video_scorer`'s *input* payload (the raw `video_features`), not its output —
    warmth comes from the measured `expression` block rather than a derived score.

    Never raises on malformed input: a register reading is a nice-to-have, and must not be able
    to fail a submission the user already completed.
    """
    config = speech_config or {}
    register = config.get("register") or {}

    voice_arousal_raw = _measure_arousal(audio_features)
    face_warmth_raw = _measure_warmth(video)
    formality_raw = _measure_formality(text)

    scored = ScoredRegister(
        voice_arousal=_band_match(voice_arousal_raw, register.get("arousal_band")),
        face_warmth=_band_match(face_warmth_raw, register.get("smile_band")),
        word_formality=_formality_match(formality_raw, register.get("formality")),
    )

    # Voice leads: this is a speaking exercise, and the voice channel is the only one present in
    # every scored session. Face and words support it.
    weights = {"voice_arousal": 0.5, "face_warmth": 0.3, "word_formality": 0.2}
    present = [
        (weights[name], value)
        for name, value in (
            ("voice_arousal", scored.voice_arousal),
            ("face_warmth", scored.face_warmth),
            ("word_formality", scored.word_formality),
        )
        if value is not None
    ]
    total_weight = sum(w for w, _ in present)
    if present and total_weight > 0:
        # Renormalised over the channels that exist, so a text-only session is not punished for
        # having no voice, and a camera-off session is not punished for having no face.
        scored.emotional_register = round(sum(w * v for w, v in present) / total_weight, 1)

    scored.confidence_weight = _confidence(present, total_weight, video)
    scored.detail = {
        "arousal_raw": None if voice_arousal_raw is None else round(voice_arousal_raw, 1),
        "warmth_raw": None if face_warmth_raw is None else round(face_warmth_raw, 1),
        "formality_raw": None if formality_raw is None else round(formality_raw, 1),
        "expected": {
            "arousal_band": register.get("arousal_band"),
            "smile_band": register.get("smile_band"),
            "formality": register.get("formality"),
        },
        "markers": count_warmth_markers(text),
        "channels_measured": [name for name, v in (
            ("voice", scored.voice_arousal),
            ("face", scored.face_warmth),
            ("words", scored.word_formality),
        ) if v is not None],
    }

    scored.issues = _build_issues(scored, register, voice_arousal_raw, face_warmth_raw)
    scored.highlights = _build_highlights(scored)
    return scored


def _formality_match(measured: Optional[float], expected: Optional[str]) -> Optional[float]:
    """Match a measured formality (0 casual .. 100 formal) against the expected register.

    Asymmetric on purpose: being *more* formal than a casual occasion asks for is a real miss —
    a stiff wedding toast lands badly — while being slightly less formal than a pitch expects is
    usually just a relaxed presenter, so it costs less.
    """
    if measured is None or not expected:
        return None
    if expected == "formal":
        return _clamp(50 + (measured - 50) * 1.4)
    if expected == "informal":
        return _clamp(50 + (50 - measured) * 1.4)
    return 100.0 - abs(measured - 50.0)  # "neutral": either extreme is a miss


def _confidence(present: List[Tuple[float, float]], total_weight: float, video: Optional[Dict]) -> float:
    """How much to trust the combined figure.

    Falls with the number of channels available, and is dragged down further when the video that
    *was* supplied turned out to be unmeasurable — a camera session whose face was never seen
    should not read as confidently as one where it was.
    """
    if not present:
        return 0.0
    weight = _clamp(total_weight, 0.0, 1.0)
    if video and (video.get("status") not in (None, "ok")):
        weight *= 0.7
    return round(weight, 3)


# ── Deterministic feedback ────────────────────────────────────────────────────
def _build_issues(
    scored: ScoredRegister,
    register: Dict,
    arousal_raw: Optional[float],
    warmth_raw: Optional[float],
) -> List[Dict]:
    """Same `{type, message, suggestion}` shape as `_generate_flags`, so these merge straight
    into the existing flags list. Fully deterministic — no LLM needed, and none available on
    the Public Speaking path."""
    issues: List[Dict] = []
    band = register.get("arousal_band")
    label = register.get("label", "this kind of speech")

    if scored.voice_arousal is not None and scored.voice_arousal < 55 and band and arousal_raw is not None:
        if arousal_raw < band[0]:
            issues.append({
                "type": "register_too_flat",
                "message": f"Your vocal energy stayed low for {label}.",
                "suggestion": "Vary your pitch and volume across key lines — let the important words land louder.",
            })
        elif arousal_raw > band[1]:
            issues.append({
                "type": "register_too_intense",
                "message": f"Your delivery ran hotter than {label} usually calls for.",
                "suggestion": "Bring the energy down a notch and let a few measured lines carry the weight.",
            })

    smile_band = register.get("smile_band")
    if scored.face_warmth is not None and scored.face_warmth < 55 and smile_band and warmth_raw is not None:
        if warmth_raw < smile_band[0]:
            issues.append({
                "type": "register_too_stoic",
                "message": f"Your expression stayed neutral throughout — {label} usually wants more warmth.",
                "suggestion": "Let yourself smile on the lines you actually feel; the audience mirrors it.",
            })
        elif warmth_raw > smile_band[1]:
            issues.append({
                "type": "register_too_casual_face",
                "message": f"You smiled almost continuously, which reads as less serious than {label} needs.",
                "suggestion": "Save the smile for the moments that earn it so it carries meaning.",
            })

    if scored.word_formality is not None and scored.word_formality < 50:
        expected = register.get("formality")
        if expected == "formal":
            issues.append({
                "type": "register_too_informal_wording",
                "message": "Your wording was noticeably casual for this format.",
                "suggestion": "Swap filler phrasing like 'gonna' and 'stuff' for concrete, specific terms.",
            })
        elif expected == "informal":
            issues.append({
                "type": "register_too_formal_wording",
                "message": "Your wording stayed formal for what should feel personal.",
                "suggestion": "Speak as you would to the room — names, specifics, and a short story beat corporate phrasing here.",
            })

    return issues


def _build_highlights(scored: ScoredRegister) -> List[Dict]:
    highlights: List[Dict] = []
    if scored.voice_arousal is not None and scored.voice_arousal >= 80:
        highlights.append({
            "kind": "register_energy_matched",
            "message": "Your vocal energy suited the occasion well.",
        })
    if scored.face_warmth is not None and scored.face_warmth >= 80:
        highlights.append({
            "kind": "register_warmth_matched",
            "message": "Your expression matched the tone the moment called for.",
        })
    return highlights
