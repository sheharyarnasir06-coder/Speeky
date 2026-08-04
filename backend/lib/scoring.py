"""Shared primitives for services that turn LLM output into scores.

Every scoring service was carrying its own byte-identical copy of these three
helpers. They are pure, dependency-free, and used across four services, so a
single definition is the right home for them.

Deliberately NOT included: `rewrite_service._clamp_score`. It looks the same but
returns a caller-supplied default (50) instead of the lower bound (0) when the
value is unparseable, which is a different failure policy — folding it in here
would silently change how a failed rewrite scores.
"""

from datetime import datetime, timezone
from typing import Any, Iterable, List


def clamp(value: Any, lo: int = 0, hi: int = 100) -> int:
    """Coerce an LLM-supplied value into an integer inside [lo, hi].

    Returns `lo` for anything unparseable — a model that emits "high" or null for
    a score must not be able to crash a request or inject a wild number into a
    weighted average.
    """
    try:
        # round() without ndigits already returns an int; wrapping it in int()
        # adds nothing.
        return max(lo, min(hi, round(float(value))))
    except (TypeError, ValueError):
        return lo


def clean_str_list(raw: Any, limit: int) -> List[str]:
    """Normalise a model-supplied list of strings: stringify, trim, drop blanks,
    and cap the length so one verbose response cannot flood a UI panel."""
    if not isinstance(raw, Iterable) or isinstance(raw, (str, bytes)):
        # A model that returns a bare string where a list was asked for would
        # otherwise be iterated character by character.
        return []
    cleaned = []
    for item in raw:
        # `str(None)` is "None", which is truthy — without this guard a model
        # emitting [null] renders a literal "None" bullet in the admin UI.
        if item is None:
            continue
        text = str(item).strip()
        if text:
            cleaned.append(text)
    return cleaned[:limit]


def as_utc(value: datetime) -> datetime:
    """Attach UTC to a naive datetime.

    Prisma hands back naive datetimes for `timestamp without time zone` columns
    depending on driver and column type. Subtracting a naive from an aware
    datetime raises TypeError, so every time-window comparison normalises first.
    """
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
