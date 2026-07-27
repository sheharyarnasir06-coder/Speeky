"""
Shared formality-tier system.

WEC-US-03's own acceptance criteria requires reusing "the same context
tiers already defined for grammar tone adjustment (BAS-US-11)" so that
formality doesn't fragment into separate systems per feature. This module
is that single source of truth — both confidence.py (BAS-US-11) and
code_switch_tolerance.py (WEC-US-03) import FormalityTier from here
rather than each defining their own.

No thresholds are hardcoded here — callers supply their own
tier -> threshold/behavior mapping (see each module's constructor).
"""

from enum import Enum


class FormalityTier(str, Enum):
    """
    Three tiers, per WEC-US-03's own wording: "a casual roleplay
    differently from a formal Interview Coach or Workplace Email
    scenario." Exact tier count/names aren't given numerically anywhere
    in the spec beyond these three named examples.
    """

    CASUAL = "casual"
    PROFESSIONAL = "professional"
    FORMAL_HIGH_STAKES = "formal_high_stakes"


# WEC-US-03 E-01: "A newly added practice feature has not yet been tagged
# with a formality tier... Default to 'Professional' strictness until
# explicitly configured, erring toward the stricter standard." This is
# the ONLY default mandated by the spec text itself, not an invented one.
DEFAULT_TIER_WHEN_UNTAGGED = FormalityTier.PROFESSIONAL
