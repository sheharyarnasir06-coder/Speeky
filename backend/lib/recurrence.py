"""
Pure recurrence-scheduling math (GAP-04 / US-202). No DB — everything here is
directly unit-testable (backend/tests/test_recurrence.py).
"""

import calendar
from datetime import datetime, time as dtime, timedelta, timezone
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

VALID_RECURRENCES = ("weekly", "monthly", "none")


def _safe_local_datetime(year: int, month: int, day: int, hour: int, minute: int, tz: ZoneInfo) -> datetime:
    """Clamps day-of-month to the last real day (e.g. recurrenceDay=31 in
    February) instead of raising."""
    last_day = calendar.monthrange(year, month)[1]
    return datetime(year, month, min(day, last_day), hour, minute, tzinfo=tz)


def compute_next_run(
    *,
    recurrence: str,
    recurrence_day: Optional[int],
    recurrence_hour: int,
    recurrence_minute: int,
    timezone_name: str,
    now_utc: datetime,
) -> Optional[datetime]:
    """E-05: the schedule always runs in the admin-selected IANA timezone
    (`timezone_name`), not server-local or UTC-implied — the caller stores and
    displays that same string so there's no silent mismatch. Returns the next
    UTC instant to fire, or None for "none" (manual/on-demand only)."""
    if recurrence == "none":
        return None
    if recurrence not in VALID_RECURRENCES:
        raise ValueError(f"Unknown recurrence: {recurrence}")

    tz = ZoneInfo(timezone_name)
    now_local = now_utc.astimezone(tz)

    if recurrence == "weekly":
        target_weekday = recurrence_day if recurrence_day is not None else 0  # 0 = Monday
        days_ahead = (target_weekday - now_local.weekday()) % 7
        candidate = datetime.combine(
            now_local.date() + timedelta(days=days_ahead),
            dtime(hour=recurrence_hour, minute=recurrence_minute),
            tzinfo=tz,
        )
        if candidate <= now_local:
            candidate += timedelta(days=7)
    else:  # monthly
        day = recurrence_day if recurrence_day else 1
        candidate = _safe_local_datetime(now_local.year, now_local.month, day, recurrence_hour, recurrence_minute, tz)
        if candidate <= now_local:
            month = now_local.month + 1
            year = now_local.year + (month - 1) // 12
            month = ((month - 1) % 12) + 1
            candidate = _safe_local_datetime(year, month, day, recurrence_hour, recurrence_minute, tz)

    return candidate.astimezone(timezone.utc)


def should_defer_edit(currently_generating: bool) -> bool:
    """E-03: an edit made while a run is in progress is queued, not applied
    immediately — avoids mutating recurrence/recipients mid-render."""
    return currently_generating


def merge_pending_update(template_fields: Dict[str, Any], pending_update: Dict[str, Any]) -> Dict[str, Any]:
    """Applies a queued E-03 edit on top of the current template fields once
    the in-flight run has completed."""
    return {**template_fields, **pending_update}
