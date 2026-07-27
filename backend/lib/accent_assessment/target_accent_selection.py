"""
Target Accent / English Variant Selection (ACC-US-03).

Lets a user choose a target reference accent (e.g. General American,
British RP, Neutral International) that pronunciation/intonation are
scored against, since "clarity" targets differ by variant.

Persistence: reuses lib/kv_store.py (real, Prisma-backed KvEntry table),
the same namespace+key+JSON-value pattern already used by
interview_coach_service.py, conversation_service.py, and
session_memory_service.py - not confidence.py's in-memory/caller-replays
pattern, since this needs a durable per-user log that survives across
requests, not a value reconstructed fresh each call. See __init__.py for
why confidence_engine.py/session_scorer.py didn't fit instead.

Integration note: this module does NOT import from lib/pronunciation_coach/ -
the dependency runs the other way. lib/pronunciation_coach/pronunciation_pipeline.py's
PronunciationPipeline.resolve_config_for_user()/score_sentence_for_user()
call this service's get_preference(user_id).current_accent_id to pick the
right accent-specific scoring config (see that module's
AccentPronunciationConfigRegistry). This file itself needed no changes to
support that - it already exposed exactly the read-path required.
"""

import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

NAMESPACE = "accent_target_selection"

# E-01: how many days of prior tracked history (caller-supplied
# tracking_started_at) count as "mid-history" enough to flag a switch for
# prominent trend-line annotation, vs. an early/inconsequential switch.
# Every switch is ALWAYS logged either way (see select_target_accent) -
# this only gates the is_mid_history_switch flag. "3 months" in the
# story's example, expressed as a named, overridable default.
DEFAULT_MID_HISTORY_THRESHOLD_DAYS = 90

# Named templates so no message is built ad-hoc at a call site.
MID_HISTORY_MARKER_TEMPLATE = "Target accent changed on {date}"

UNSUPPORTED_ACCENT_MESSAGE_TEMPLATE = (
    "{requested_label} isn't supported yet - coming soon. "
    "We've kept your target accent set to {fallback_label} for now."
)

SCORING_SHIFT_CONFIRMATION_TEMPLATE = "Scoring will now target {label}. {scoring_note}"

COMBINED_GUIDANCE_TEMPLATE = (
    "Target Accent ({accent_label}) sets the pronunciation reference point your speech "
    "is scored against. Local Calibration ({calibration_state}) separately controls how "
    "much regional consonant/vowel variance is tolerated as acceptable. Both settings "
    "are independent and can be active together - changing one does not change the other."
)


@dataclass(frozen=True)
class TargetAccentOption:
    """One selectable target-accent reference."""

    id: str
    label: str
    description: str
    scoring_note: str = ""  # happy-path step 2: how scoring shifts for this variant


# --- Defaults, all overridable via TargetAccentRegistry(...) below -------
# Acceptance criteria: "must support at least 2 distinct target-accent
# references at launch... but the list must not be hardcoded as only
# these two." Three are shipped by default; none of this is a fixed enum
# - it's a plain dict a caller can replace/extend wholesale.
DEFAULT_TARGET_ACCENT_ID = "general_american"

DEFAULT_TARGET_ACCENTS: Dict[str, TargetAccentOption] = {
    "general_american": TargetAccentOption(
        id="general_american",
        label="General American",
        description="The reference accent used in most US broadcast/business English.",
        scoring_note="Rhotic /r/ expected in all positions; flapped intervocalic /t/ (e.g. 'water') is standard, not an error.",
    ),
    "british_rp": TargetAccentOption(
        id="british_rp",
        label="British RP (Received Pronunciation)",
        description="The traditional standard-British reference accent.",
        scoring_note="Non-rhotic - /r/ is not expected after vowels (e.g. 'car'); vowel length distinctions are scored more strictly than in General American.",
    ),
    "neutral_international": TargetAccentOption(
        id="neutral_international",
        label="Neutral International",
        description="A wider-tolerance reference for learners not targeting a specific national accent.",
        scoring_note="Wider acceptable range across vowel/consonant realizations - no single national norm is enforced.",
    ),
}

# E-03 "closest supported variant" fallback for unsupported requests.
# Configurable mapping, not a fixed if/else - a request not present here
# (or mapped to an id that isn't currently supported) falls through to
# TargetAccentRegistry.default_id instead.
DEFAULT_CLOSEST_FALLBACK: Dict[str, str] = {
    "australian_english": "british_rp",
    "new_zealand_english": "british_rp",
    "indian_english": "neutral_international",
    "canadian_english": "general_american",
}


@dataclass
class TargetAccentRegistry:
    """
    Injectable/overridable registry of supported target accents and their
    closest-supported-variant fallback mapping. Construct with your own
    `options`/`closest_fallback`/`default_id` to change what's supported
    without touching any logic in this file.
    """

    options: Dict[str, TargetAccentOption] = field(default_factory=lambda: dict(DEFAULT_TARGET_ACCENTS))
    closest_fallback: Dict[str, str] = field(default_factory=lambda: dict(DEFAULT_CLOSEST_FALLBACK))
    default_id: str = DEFAULT_TARGET_ACCENT_ID

    def __post_init__(self):
        if not self.options:
            raise ValueError("TargetAccentRegistry needs at least one supported option")
        if self.default_id not in self.options:
            raise ValueError(f"default_id {self.default_id!r} is not in options")

    def is_supported(self, accent_id: str) -> bool:
        return accent_id in self.options

    def get(self, accent_id: str) -> Optional[TargetAccentOption]:
        return self.options.get(accent_id)

    def list_options(self) -> List[TargetAccentOption]:
        return list(self.options.values())

    def closest_supported(self, requested_id: str) -> TargetAccentOption:
        """E-03: resolve an unsupported request to a supported option - never returns an unsupported id."""
        if requested_id in self.options:
            return self.options[requested_id]
        mapped_id = self.closest_fallback.get(requested_id)
        if mapped_id and mapped_id in self.options:
            return self.options[mapped_id]
        return self.options[self.default_id]


@dataclass
class AccentChangeLogEntry:
    """One immutable history entry - switching accents appends one of these, never edits/removes prior entries."""

    accent_id: str
    changed_at: datetime
    previous_accent_id: Optional[str] = None
    is_mid_history_switch: bool = False
    note: Optional[str] = None  # e.g. the MID_HISTORY_MARKER_TEMPLATE text, or an E-03 fallback note


@dataclass
class UserAccentPreference:
    user_id: str
    current_accent_id: str
    history: List[AccentChangeLogEntry] = field(default_factory=list)


@dataclass
class TargetAccentSelectionResult:
    """Everything the happy path's steps 1-2 (select + confirm) need to show the user."""

    accent: TargetAccentOption  # the accent actually applied - may differ from requested_accent_id (E-03)
    requested_accent_id: str
    was_unsupported_request: bool
    fallback_message: Optional[str]  # set only when was_unsupported_request
    confirmation_message: str  # happy-path step 2: how scoring will shift
    is_mid_history_switch: bool
    history_entry: AccentChangeLogEntry


def describe_scoring_shift(accent: TargetAccentOption) -> str:
    """Happy-path step 2: explain how scoring will shift for the newly selected accent."""
    return SCORING_SHIFT_CONFIRMATION_TEMPLATE.format(label=accent.label, scoring_note=accent.scoring_note)


def describe_combined_guidance(accent: TargetAccentOption, local_calibration_active: bool) -> str:
    """E-02: Target Accent and Local Calibration are independent and can both be active."""
    return COMBINED_GUIDANCE_TEMPLATE.format(
        accent_label=accent.label,
        calibration_state="on" if local_calibration_active else "off",
    )


def _entry_to_dict(entry: AccentChangeLogEntry) -> Dict[str, Any]:
    return asdict(entry)


def _entry_from_dict(data: Dict[str, Any]) -> AccentChangeLogEntry:
    return AccentChangeLogEntry(**data)


def _preference_to_dict(pref: UserAccentPreference) -> Dict[str, Any]:
    return {
        "user_id": pref.user_id,
        "current_accent_id": pref.current_accent_id,
        "history": [_entry_to_dict(e) for e in pref.history],
    }


def _preference_from_dict(data: Dict[str, Any]) -> UserAccentPreference:
    return UserAccentPreference(
        user_id=data["user_id"],
        current_accent_id=data["current_accent_id"],
        history=[_entry_from_dict(e) for e in data.get("history", [])],
    )


class TargetAccentSelectionService:
    """
    Reads/writes a user's target-accent preference + change history via
    lib/kv_store.py. `store` defaults to the real kv_store.store
    (Prisma-backed) lazily, so importing this module doesn't require a
    DB connection - inject kv_store.InMemoryKvStore() (or any object with
    the same get/create/update async interface) for tests.
    """

    def __init__(
        self,
        registry: Optional[TargetAccentRegistry] = None,
        mid_history_threshold_days: int = DEFAULT_MID_HISTORY_THRESHOLD_DAYS,
        store: Optional[Any] = None,
    ):
        self.registry = registry or TargetAccentRegistry()
        self.mid_history_threshold_days = mid_history_threshold_days
        self._store = store

    @property
    def store(self) -> Any:
        if self._store is None:
            from lib import kv_store

            self._store = kv_store.store
        return self._store

    async def get_preference(self, user_id: str) -> Optional[UserAccentPreference]:
        """Read-path a future scoring integration (or a settings screen) would call. None if never set."""
        raw = await self.store.get(NAMESPACE, user_id)
        return _preference_from_dict(raw) if raw is not None else None

    async def get_history(self, user_id: str) -> List[AccentChangeLogEntry]:
        pref = await self.get_preference(user_id)
        return pref.history if pref else []

    async def select_target_accent(
        self,
        user_id: str,
        requested_accent_id: str,
        local_calibration_active: bool = False,
        tracking_started_at: Optional[datetime] = None,
        now: Optional[datetime] = None,
    ) -> TargetAccentSelectionResult:
        """
        Happy path steps 1-3 + all three exceptions.

        Args:
            requested_accent_id: what the user picked. If unsupported,
                E-03 resolves to the closest supported option instead -
                never applied silently, always surfaced via
                was_unsupported_request/fallback_message.
            local_calibration_active: current state of the separate
                Local Calibration toggle (owned elsewhere, e.g.
                pronunciation_coach's accent_calibration flag) - used
                only to produce the E-02 combined-guidance message, no
                coupling to that toggle's implementation.
            tracking_started_at: when this user's tracked progress began,
                if known to the caller (this module has no access to
                assessment/session history itself). Drives E-01's
                is_mid_history_switch flag; omit if unknown - the switch
                is still always logged, just never flagged as mid-history.
            now: injectable clock for tests; defaults to current UTC time.
        """
        now = now or datetime.now(timezone.utc)
        was_unsupported = not self.registry.is_supported(requested_accent_id)
        accent = self.registry.closest_supported(requested_accent_id)

        fallback_message = None
        if was_unsupported:
            fallback_message = UNSUPPORTED_ACCENT_MESSAGE_TEMPLATE.format(
                requested_label=requested_accent_id,
                fallback_label=accent.label,
            )
            logger.info(
                "Unsupported target accent '%s' requested by %s; falling back to '%s'",
                requested_accent_id, user_id, accent.id,
            )

        existing = await self.get_preference(user_id)
        previous_accent_id = existing.current_accent_id if existing else None
        history = list(existing.history) if existing else []

        is_mid_history_switch = False
        note = None
        if previous_accent_id is not None:
            # An actual switch away from a prior selection (not a first-time pick).
            if tracking_started_at is not None:
                is_mid_history_switch = (now - tracking_started_at) >= timedelta(days=self.mid_history_threshold_days)
            note = MID_HISTORY_MARKER_TEMPLATE.format(date=now.date().isoformat())

        entry = AccentChangeLogEntry(
            accent_id=accent.id,
            changed_at=now,
            previous_accent_id=previous_accent_id,
            is_mid_history_switch=is_mid_history_switch,
            note=note,
        )
        history.append(entry)  # never overwrite/remove prior entries

        new_pref = UserAccentPreference(user_id=user_id, current_accent_id=accent.id, history=history)
        value = _preference_to_dict(new_pref)
        if existing is None:
            await self.store.create(NAMESPACE, user_id, value)
        else:
            await self.store.update(NAMESPACE, user_id, value)

        return TargetAccentSelectionResult(
            accent=accent,
            requested_accent_id=requested_accent_id,
            was_unsupported_request=was_unsupported,
            fallback_message=fallback_message,
            confirmation_message=describe_scoring_shift(accent),
            is_mid_history_switch=is_mid_history_switch,
            history_entry=entry,
        )
