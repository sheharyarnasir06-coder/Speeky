"""Scheduled Report Generation (GAP-04 / US-202) — pure recurrence math in
lib/recurrence.py. No DB, no network."""

import datetime as dt
from datetime import timezone as tzutc
from zoneinfo import ZoneInfo

from lib import recurrence as rec


# ── TC-01: weekly trigger fires at the correct UTC instant ─────────────────
def test_weekly_recurrence_lands_on_correct_local_time():
    now_utc = dt.datetime(2026, 7, 26, 10, 0, tzinfo=tzutc.utc)  # a Sunday
    next_run = rec.compute_next_run(
        recurrence="weekly", recurrence_day=0, recurrence_hour=9, recurrence_minute=0,
        timezone_name="America/New_York", now_utc=now_utc,
    )
    local = next_run.astimezone(ZoneInfo("America/New_York"))
    assert local.weekday() == 0  # Monday
    assert (local.hour, local.minute) == (9, 0)


def test_same_wall_clock_different_timezone_yields_different_utc_instant():  # E-05
    now_utc = dt.datetime(2026, 7, 26, 10, 0, tzinfo=tzutc.utc)
    ny_run = rec.compute_next_run(
        recurrence="weekly", recurrence_day=0, recurrence_hour=9, recurrence_minute=0,
        timezone_name="America/New_York", now_utc=now_utc,
    )
    tokyo_run = rec.compute_next_run(
        recurrence="weekly", recurrence_day=0, recurrence_hour=9, recurrence_minute=0,
        timezone_name="Asia/Tokyo", now_utc=now_utc,
    )
    assert ny_run != tokyo_run


def test_weekly_recurrence_rolls_to_next_week_once_todays_time_has_passed():
    now_utc = dt.datetime(2026, 7, 27, 15, 0, tzinfo=tzutc.utc)  # Monday afternoon UTC
    next_run = rec.compute_next_run(
        recurrence="weekly", recurrence_day=0, recurrence_hour=9, recurrence_minute=0,
        timezone_name="UTC", now_utc=now_utc,
    )
    assert next_run > now_utc
    assert (next_run - now_utc).days >= 6


def test_monthly_recurrence_clamps_to_last_real_day_of_month():
    now_utc = dt.datetime(2026, 1, 15, 0, 0, tzinfo=tzutc.utc)
    jan_run = rec.compute_next_run(
        recurrence="monthly", recurrence_day=31, recurrence_hour=9, recurrence_minute=0,
        timezone_name="UTC", now_utc=now_utc,
    )
    assert jan_run.day == 31

    feb_run = rec.compute_next_run(
        recurrence="monthly", recurrence_day=31, recurrence_hour=9, recurrence_minute=0,
        timezone_name="UTC", now_utc=jan_run + dt.timedelta(days=1),
    )
    assert (feb_run.month, feb_run.day) == (2, 28)  # 2026 is not a leap year


def test_recurrence_none_means_manual_only():
    assert rec.compute_next_run(
        recurrence="none", recurrence_day=None, recurrence_hour=9, recurrence_minute=0,
        timezone_name="UTC", now_utc=dt.datetime.now(tzutc.utc),
    ) is None


# ── TC-05: an edit made mid-run is queued, applied only after that run completes ──
def test_edit_deferred_while_a_run_is_in_progress():
    assert rec.should_defer_edit(currently_generating=True) is True
    assert rec.should_defer_edit(currently_generating=False) is False


def test_pending_update_merges_over_existing_fields_once_applied():
    merged = rec.merge_pending_update({"name": "Weekly", "recurrenceHour": 9}, {"recurrenceHour": 14})
    assert merged == {"name": "Weekly", "recurrenceHour": 14}
