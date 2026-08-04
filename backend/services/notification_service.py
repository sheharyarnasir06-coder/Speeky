"""
Notification frequency controls & quiet hours (US-169 / GAP-08).

No push channel (FCM/APNs/...) exists in this codebase yet, so "sending" a push here
means appending to a per-user sent-log — the integration point a real push provider
would replace. Quiet hours + cadence are checked before ANY gamification push, not
just daily streak reminders, per the AC.

Preferences are stored account-level (one KvEntry per user_id, not per device) so the
most-recently-set value always wins across devices (E-04) without extra merge logic.
"""

import uuid
from datetime import datetime, time, timezone
from typing import Dict, List, Optional

from fastapi import Depends

from lib import kv_store
from lib.prompts import (
    DEFAULT_NOTIFICATION_CADENCE,
    DEFAULT_QUIET_HOURS_END,
    DEFAULT_QUIET_HOURS_START,
    STREAK_BREAK_IN_APP_SUMMARY,
    STREAK_REMINDER_PUSH_MESSAGE,
    build_milestone_message,
)
from middlewares.auth_middleware import require_auth
from schemas.notification_schemas import (
    AckPendingRequest,
    PendingInAppItem,
    PendingInAppResponse,
    PreferencesResponse,
    UpdatePreferencesRequest,
)

PREFS_NS = "notification_preferences"
SENT_LOG_NS = "notification_sent_log"
DEFERRED_NS = "notification_deferred"
PENDING_INAPP_NS = "notification_pending_inapp"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _parse_hhmm(value: str) -> time:
    hh, mm = value.split(":")
    return time(hour=int(hh), minute=int(mm))


def is_within_quiet_hours(check_time: time, start: time, end: time) -> bool:
    """Pure wraparound-aware check. Handles the overnight case (start > end, e.g.
    22:00-08:00) as well as the same-day case (start < end). start == end is treated
    as "no quiet hours configured" rather than a full-day window."""
    if start == end:
        return False
    if start < end:
        return start <= check_time < end
    return check_time >= start or check_time < end  # wraps midnight


# ── preferences ──────────────────────────────────────────────────────────────
async def _get_preferences(user_id: str) -> PreferencesResponse:
    raw = await kv_store.store.get(PREFS_NS, user_id)
    if raw is None:
        return PreferencesResponse(
            user_id=user_id,
            quiet_hours_start=DEFAULT_QUIET_HOURS_START,
            quiet_hours_end=DEFAULT_QUIET_HOURS_END,
            cadence=DEFAULT_NOTIFICATION_CADENCE,
            updated_at=_now(),
            device_id=None,
        )
    return PreferencesResponse(**raw)


async def _update_preferences(user_id: str, req: UpdatePreferencesRequest, now: Optional[datetime] = None) -> PreferencesResponse:
    now = now or _now()
    value = {
        "user_id": user_id,
        "quiet_hours_start": req.quiet_hours_start,
        "quiet_hours_end": req.quiet_hours_end,
        "cadence": req.cadence,
        "updated_at": now,
        "device_id": req.device_id,
    }
    if await kv_store.store.get(PREFS_NS, user_id) is None:
        await kv_store.store.create(PREFS_NS, user_id, value)
    else:
        await kv_store.store.update(PREFS_NS, user_id, value)
    return PreferencesResponse(**value)


async def _is_now_quiet(user_id: str, now: datetime) -> bool:
    prefs = await _get_preferences(user_id)
    return is_within_quiet_hours(now.time(), _parse_hhmm(prefs.quiet_hours_start), _parse_hhmm(prefs.quiet_hours_end))


# ── sent log / deferred / pending in-app (append-only lists per user) ────────
async def _append_list(namespace: str, user_id: str, item: Dict) -> List[Dict]:
    raw = await kv_store.store.get(namespace, user_id)
    items = raw["items"] if raw else []
    items.append(item)
    value = {"user_id": user_id, "items": items}
    if raw is None:
        await kv_store.store.create(namespace, user_id, value)
    else:
        await kv_store.store.update(namespace, user_id, value)
    return items


async def _get_list(namespace: str, user_id: str) -> List[Dict]:
    raw = await kv_store.store.get(namespace, user_id)
    return raw["items"] if raw else []


async def _set_list(namespace: str, user_id: str, items: List[Dict]) -> None:
    raw = await kv_store.store.get(namespace, user_id)
    value = {"user_id": user_id, "items": items}
    if raw is None:
        await kv_store.store.create(namespace, user_id, value)
    else:
        await kv_store.store.update(namespace, user_id, value)


async def _get_sent_log(user_id: str) -> List[Dict]:
    return await _get_list(SENT_LOG_NS, user_id)


# ── dispatch (called by other features, e.g. daily_challenge_service) ────────
async def notify_streak_reminder(user_id: str, now: Optional[datetime] = None) -> Dict:
    now = now or _now()
    prefs = await _get_preferences(user_id)
    if prefs.cadence == "off":
        return {"sent": False, "reason": "cadence_off"}
    if await _is_now_quiet(user_id, now):
        return {"sent": False, "reason": "quiet_hours"}
    await _append_list(SENT_LOG_NS, user_id, {
        "type": "streak_reminder", "message": STREAK_REMINDER_PUSH_MESSAGE, "sent_at": now,
    })
    return {"sent": True}


async def notify_streak_break(user_id: str, streak_length: int, broken_date: str, now: Optional[datetime] = None) -> Dict:
    """E-02: reminders-off users get no push warning, but always get an in-app summary
    on next open explaining the miss (proactive nudging was declined, not the summary)."""
    now = now or _now()
    summary = STREAK_BREAK_IN_APP_SUMMARY.format(streak_length=streak_length, broken_date=broken_date)
    await _append_list(PENDING_INAPP_NS, user_id, {
        "id": _new_id("inapp"), "type": "streak_break_summary", "message": summary, "created_at": now,
    })
    prefs = await _get_preferences(user_id)
    push_sent = False
    if prefs.cadence != "off" and not await _is_now_quiet(user_id, now):
        await _append_list(SENT_LOG_NS, user_id, {"type": "streak_break", "message": summary, "sent_at": now})
        push_sent = True
    return {"push_sent": push_sent, "in_app_queued": True}


async def notify_milestone(user_id: str, days: int, live_session: bool, now: Optional[datetime] = None) -> Dict:
    """E-03: milestone push is deferred to the next allowed window if hit during quiet
    hours, but the in-app celebration still shows immediately if the user is actively
    in-session."""
    now = now or _now()
    message = build_milestone_message(days)
    in_quiet = await _is_now_quiet(user_id, now)

    if in_quiet:
        await _append_list(DEFERRED_NS, user_id, {"type": "milestone", "message": message, "days": days, "created_at": now})
        push_status = "deferred"
    else:
        await _append_list(SENT_LOG_NS, user_id, {"type": "milestone", "message": message, "sent_at": now})
        push_status = "sent"

    return {"in_app_immediate": live_session, "push_status": push_status, "message": message}


async def flush_deferred_notifications(user_id: str, now: Optional[datetime] = None) -> List[Dict]:
    """Release any deferred pushes once we're outside quiet hours. Call on app-open /
    next allowed-window check — there's no background scheduler in this codebase."""
    now = now or _now()
    if await _is_now_quiet(user_id, now):
        return []
    deferred = await _get_list(DEFERRED_NS, user_id)
    if not deferred:
        return []
    for item in deferred:
        await _append_list(SENT_LOG_NS, user_id, {**item, "sent_at": now, "was_deferred": True})
    await _set_list(DEFERRED_NS, user_id, [])
    return deferred


# ── pending in-app queue ──────────────────────────────────────────────────────
async def _get_pending_inapp(user_id: str) -> PendingInAppResponse:
    items = await _get_list(PENDING_INAPP_NS, user_id)
    return PendingInAppResponse(items=[PendingInAppItem(**i) for i in items])


async def _ack_pending_inapp(user_id: str, item_id: str) -> PendingInAppResponse:
    items = await _get_list(PENDING_INAPP_NS, user_id)
    items = [i for i in items if i["id"] != item_id]
    await _set_list(PENDING_INAPP_NS, user_id, items)
    return PendingInAppResponse(items=[PendingInAppItem(**i) for i in items])


# ── GAP-03 (US-201): admin "push" channel for anomaly alerts ────────────────
async def send_admin_push(user_id: str, message: str, now: Optional[datetime] = None) -> Dict:
    """Same simulated-log mechanism as the rest of this file (no real push
    provider exists in this codebase yet) — reused here so the alert delivery
    layer's "push" channel isn't a second, parallel implementation."""
    now = now or _now()
    await _append_list(SENT_LOG_NS, user_id, {"type": "anomaly_alert", "message": message, "sent_at": now})
    return {"sent": True}


# ── controllers (auth-gated) ────────────────────────────────────────────────
async def get_preferences(user_id: str = Depends(require_auth)):
    return await _get_preferences(user_id)


async def update_preferences(payload: UpdatePreferencesRequest, user_id: str = Depends(require_auth)):
    return await _update_preferences(user_id, payload)


async def get_pending_inapp(user_id: str = Depends(require_auth)):
    await flush_deferred_notifications(user_id)
    return await _get_pending_inapp(user_id)


async def ack_pending_inapp(payload: AckPendingRequest, user_id: str = Depends(require_auth)):
    return await _ack_pending_inapp(user_id, payload.item_id)
