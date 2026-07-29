"""
Anomaly Detection & Proactive Alerting orchestration (GAP-03 / US-201).

Ties together the pure math in lib/anomaly_math.py, the shared metrics
pipeline in services/platform_metrics_service.py, and delivery in
services/notification_delivery_service.py. The scheduler (lib/scheduler.py)
calls `run_detection_cycle` on a timer; everything else here is the CRUD/
query surface the alert_routes.py router exposes to admins.
"""

import logging
import os
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional

from fastapi import Depends
from fastapi.responses import JSONResponse

from lib import anomaly_math
from lib.prisma_client import db
from middlewares.auth_middleware import require_admin, require_super_admin
from schemas.alert_schemas import AssignOwnerRequest, ThresholdUpsertRequest
from services import audit_log_service, notification_delivery_service, platform_metrics_service
from utils import email_utils

logger = logging.getLogger(__name__)

BASELINE_LOOKBACK_DAYS = 28
DEFAULT_THRESHOLD_TYPE = "stddev_multiplier"
DEFAULT_THRESHOLD_VALUE = 2.0
DEFAULT_DIRECTION = "any"

DASHBOARD_BASE_URL = "/dashboard/admin/analytics"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _deep_link(metric_key: str, window_start: date, window_end: date) -> str:
    """Acceptance criterion: every alert deep-links to the filtered dashboard,
    never the generic homepage."""
    return f"{DASHBOARD_BASE_URL}?metric={metric_key}&from={window_start.isoformat()}&to={window_end.isoformat()}"


async def _active_thresholds(metric_key: str) -> List:
    return await db.metricthreshold.find_many(where={"metricKey": metric_key, "isActive": True})


async def _latest_alert_for_incident(incident_key: str):
    rows = await db.anomalyalert.find_many(
        where={"incidentKey": incident_key}, order={"createdAt": "desc"}, take=1
    )
    return rows[0] if rows else None


async def _latest_ongoing_alert_for_metric(metric_key: str):
    rows = await db.anomalyalert.find_many(
        where={"metricKey": metric_key, "status": {"in": list(anomaly_math.ONGOING_STATUSES)}},
        order={"createdAt": "desc"},
        take=1,
    )
    return rows[0] if rows else None


async def _super_admin_ids() -> List[str]:
    rows = await db.user.find_many(where={"role": "SUPER_ADMIN"})
    return [r.id for r in rows]


async def _user_email(user_id: str) -> Optional[str]:
    user = await db.user.find_unique(where={"id": user_id})
    return user.email if user else None


async def _resolve_metric_for_detection(metric_key: str):
    """Detection itself must not depend on ownership existing (E-04 requires a
    breach to still be logged with zero owners) — so this falls back to a
    default sensitivity when no admin has configured one yet."""
    thresholds = await _active_thresholds(metric_key)
    if thresholds:
        primary = thresholds[0]
        return primary.thresholdType, primary.thresholdValue, primary.direction, thresholds
    return DEFAULT_THRESHOLD_TYPE, DEFAULT_THRESHOLD_VALUE, DEFAULT_DIRECTION, []


async def _resolve_ongoing(metric_key: str, window_start: date, window_end: date, deep_link: str) -> None:
    """No breach this cycle — if there was an open incident for this metric,
    resolve it and send exactly one resolution notice (E-05)."""
    latest = await _latest_ongoing_alert_for_metric(metric_key)
    if not latest or not anomaly_math.is_resolution(latest.status, breached_now=False):
        return

    await db.anomalyalert.update(
        where={"id": latest.id}, data={"status": "resolved", "resolvedAt": _now()}
    )
    await audit_log_service.record_event(
        action="alert.resolve", target_type="AnomalyAlert", target_id=latest.id,
        metadata={"metric_key": metric_key},
    )
    thresholds = await _active_thresholds(metric_key)
    label = platform_metrics_service.METRIC_LABELS.get(metric_key, metric_key)
    for t in thresholds:
        recipient_email = await _user_email(t.ownerAdminId)
        if not recipient_email:
            continue
        await notification_delivery_service.deliver(
            recipient_admin_id=t.ownerAdminId,
            channels=t.channels,
            slack_webhook_url=t.slackWebhookUrl,
            slack_text=f"✅ {label} has returned to its normal range.",
            send_email=lambda e=recipient_email: email_utils.send_alert_resolved_email(e, label, deep_link),
            push_message=f"{label} back to normal.",
            alert_id=latest.id,
        )


async def run_detection_cycle(now: Optional[datetime] = None) -> Dict:
    now = now or _now()
    today = now.date()
    window_start = today - timedelta(days=13)
    run_id = uuid.uuid4().hex

    breaches: List[Dict] = []

    for metric_key in platform_metrics_service.METRIC_KEYS:
        if not platform_metrics_service.is_metric_available(metric_key):
            continue
        try:
            history_points = await platform_metrics_service.get_metric_timeseries(
                metric_key, today - timedelta(days=BASELINE_LOOKBACK_DAYS + 7), today - timedelta(days=1)
            )
            history = [(date.fromisoformat(p["date"]), p["value"]) for p in history_points]
            current_value = await platform_metrics_service.get_current_value(metric_key)
            baseline = anomaly_math.rolling_baseline(history, today, lookback_days=BASELINE_LOOKBACK_DAYS)

            threshold_type, threshold_value, direction, thresholds = await _resolve_metric_for_detection(metric_key)
            deviation = anomaly_math.is_breach(current_value, baseline, threshold_type, threshold_value, direction)
            deep_link = _deep_link(metric_key, window_start, today)

            if deviation is None:
                await _resolve_ongoing(metric_key, window_start, today, deep_link)
                continue

            incident_key = anomaly_math.resolve_incident_key(metric_key, deviation)
            latest = await _latest_alert_for_incident(incident_key)
            if anomaly_math.should_suppress_repeat(latest.status if latest else None):
                continue  # E-05: same ongoing incident, don't re-notify

            breaches.append({
                "metric_key": metric_key,
                "value": current_value,
                "baseline": baseline.mean,
                "deviation": deviation,
                "incident_key": incident_key,
                "thresholds": thresholds,
                "deep_link": deep_link,
            })
        except Exception as exc:
            logger.error(f"Anomaly detection failed for {metric_key}: {exc}")

    if not breaches:
        return {"run_id": run_id, "breaches": 0}

    digest_group_id = anomaly_math.group_into_digest([b["metric_key"] for b in breaches], run_id)

    # Create AnomalyAlert rows first (need ids for delivery logging).
    created = []
    for b in breaches:
        is_unassigned = len(b["thresholds"]) == 0
        alert = await db.anomalyalert.create(
            data={
                "metricKey": b["metric_key"],
                "value": b["value"],
                "baselineValue": b["baseline"],
                "deviation": b["deviation"],
                "windowStart": datetime.combine(window_start, datetime.min.time(), tzinfo=timezone.utc),
                "windowEnd": datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc),
                "digestGroupId": digest_group_id,
                "isUnassigned": is_unassigned,
                "incidentKey": b["incident_key"],
                "deepLinkPath": b["deep_link"],
            }
        )
        created.append({**b, "alert": alert})
        await audit_log_service.record_event(
            action="alert.create", target_type="AnomalyAlert", target_id=alert.id,
            metadata={"metric_key": b["metric_key"], "deviation": b["deviation"], "unassigned": is_unassigned},
        )

    await _deliver_breaches(created, digest_group_id)
    return {"run_id": run_id, "breaches": len(breaches), "digest_group_id": digest_group_id}


async def _deliver_breaches(created: List[Dict], digest_group_id: Optional[str]) -> None:
    # Group by recipient admin so someone who owns >1 breaching metric gets ONE
    # digest message, not N separate ones (E-01).
    by_recipient: Dict[str, List[Dict]] = {}
    unassigned: List[Dict] = []

    for item in created:
        if not item["thresholds"]:
            unassigned.append(item)
            continue
        for t in item["thresholds"]:
            by_recipient.setdefault(t.ownerAdminId, []).append({**item, "threshold": t})

    for admin_id, items in by_recipient.items():
        recipient_email = await _user_email(admin_id)
        if not recipient_email:
            continue
        channels = items[0]["threshold"].channels
        slack_webhook_url = items[0]["threshold"].slackWebhookUrl
        if len(items) > 1:
            breach_payload = [
                {"metric_label": platform_metrics_service.METRIC_LABELS.get(i["metric_key"], i["metric_key"]), "value": i["value"], "baseline": i["baseline"]}
                for i in items
            ]
            dashboard_url = items[0]["deep_link"]
            slack_text = f"🚨 {len(items)} metrics affected around the same time — possible shared cause: " + ", ".join(p["metric_label"] for p in breach_payload)
            await notification_delivery_service.deliver(
                recipient_admin_id=admin_id,
                channels=channels,
                slack_webhook_url=slack_webhook_url,
                slack_text=slack_text,
                send_email=lambda e=recipient_email, p=breach_payload, u=dashboard_url: email_utils.send_alert_digest_email(e, p, u),
                push_message=slack_text,
                digest_group_id=digest_group_id,
            )
        else:
            i = items[0]
            label = platform_metrics_service.METRIC_LABELS.get(i["metric_key"], i["metric_key"])
            slack_text = f"⚠️ Anomaly in {label}: value={i['value']}, baseline={round(i['baseline'], 2)}"
            await notification_delivery_service.deliver(
                recipient_admin_id=admin_id,
                channels=channels,
                slack_webhook_url=slack_webhook_url,
                slack_text=slack_text,
                send_email=lambda e=recipient_email, lbl=label, i=i: email_utils.send_anomaly_alert_email(e, lbl, i["value"], i["baseline"], i["deviation"], i["deep_link"]),
                push_message=slack_text,
                alert_id=i["alert"].id,
            )

    # E-04: unassigned metric — log (already done via isUnassigned on the row) + notify Super Admins.
    if unassigned:
        super_admin_ids = await _super_admin_ids()
        for item in unassigned:
            label = platform_metrics_service.METRIC_LABELS.get(item["metric_key"], item["metric_key"])
            for admin_id in super_admin_ids:
                email = await _user_email(admin_id)
                if not email:
                    continue
                await notification_delivery_service.deliver(
                    recipient_admin_id=admin_id,
                    channels=["email", "push"],
                    slack_webhook_url=None,
                    slack_text=f"⚠️ Unassigned anomaly: {label} has no owner configured.",
                    send_email=lambda e=email, lbl=label, u=item["deep_link"]: email_utils.send_unassigned_alert_email(e, lbl, u),
                    push_message=f"Unassigned anomaly: {label}",
                    alert_id=item["alert"].id,
                )


# ── Admin-facing CRUD/query surface (called by routers/alert_routes.py) ─────
async def list_thresholds(metric_key: Optional[str] = None) -> List[Dict]:
    where = {"metricKey": metric_key} if metric_key else {}
    rows = await db.metricthreshold.find_many(where=where, order={"metricKey": "asc"})
    return [_threshold_to_dict(r) for r in rows]


def _threshold_to_dict(r) -> Dict:
    return {
        "id": r.id,
        "metric_key": r.metricKey,
        "owner_admin_id": r.ownerAdminId,
        "threshold_type": r.thresholdType,
        "threshold_value": r.thresholdValue,
        "direction": r.direction,
        "channels": r.channels,
        "slack_webhook_url": r.slackWebhookUrl,
        "is_active": r.isActive,
    }


async def upsert_threshold(metric_key: str, owner_admin_id: str, threshold_type: str, threshold_value: float, direction: str, channels: List[str], slack_webhook_url: Optional[str], actor_id: str) -> Dict:
    existing = await db.metricthreshold.find_unique(where={"metricKey_ownerAdminId": {"metricKey": metric_key, "ownerAdminId": owner_admin_id}})
    data = {
        "thresholdType": threshold_type,
        "thresholdValue": threshold_value,
        "direction": direction,
        "channels": channels,
        "slackWebhookUrl": slack_webhook_url,
        "isActive": True,
    }
    if existing:
        row = await db.metricthreshold.update(where={"id": existing.id}, data=data)
    else:
        row = await db.metricthreshold.create(data={"metricKey": metric_key, "ownerAdminId": owner_admin_id, **data})
    await audit_log_service.record_event(
        action="threshold.update", target_type="MetricThreshold", target_id=row.id, actor_id=actor_id,
        metadata={"metric_key": metric_key, "threshold_value": threshold_value},
    )
    return _threshold_to_dict(row)


async def deactivate_threshold(threshold_id: str, actor_id: str) -> None:
    await db.metricthreshold.update(where={"id": threshold_id}, data={"isActive": False})
    await audit_log_service.record_event(
        action="threshold.deactivate", target_type="MetricThreshold", target_id=threshold_id, actor_id=actor_id, metadata={},
    )


def _alert_to_dict(r) -> Dict:
    return {
        "id": r.id,
        "metric_key": r.metricKey,
        "metric_label": platform_metrics_service.METRIC_LABELS.get(r.metricKey, r.metricKey),
        "value": r.value,
        "baseline_value": r.baselineValue,
        "deviation": r.deviation,
        "status": r.status,
        "digest_group_id": r.digestGroupId,
        "is_unassigned": r.isUnassigned,
        "incident_key": r.incidentKey,
        "deep_link_path": r.deepLinkPath,
        "acknowledged_by": r.acknowledgedBy,
        "acknowledged_at": r.acknowledgedAt.isoformat() if r.acknowledgedAt else None,
        "resolved_at": r.resolvedAt.isoformat() if r.resolvedAt else None,
        "created_at": r.createdAt.isoformat(),
    }


async def list_alerts(status: Optional[str] = None, metric_key: Optional[str] = None, limit: int = 100) -> List[Dict]:
    where: Dict = {}
    if status:
        where["status"] = status
    if metric_key:
        where["metricKey"] = metric_key
    rows = await db.anomalyalert.find_many(where=where, order={"createdAt": "desc"}, take=min(limit, 500))
    return [_alert_to_dict(r) for r in rows]


async def list_unassigned_alerts() -> List[Dict]:
    rows = await db.anomalyalert.find_many(where={"isUnassigned": True, "status": "open"}, order={"createdAt": "desc"})
    return [_alert_to_dict(r) for r in rows]


async def acknowledge_alert(alert_id: str, actor_id: str) -> Dict:
    row = await db.anomalyalert.update(
        where={"id": alert_id}, data={"status": "acknowledged", "acknowledgedBy": actor_id, "acknowledgedAt": _now()}
    )
    await audit_log_service.record_event(action="alert.acknowledge", target_type="AnomalyAlert", target_id=alert_id, actor_id=actor_id, metadata={})
    return _alert_to_dict(row)


async def mark_false_positive(alert_id: str, actor_id: str) -> Dict:
    """E-02: admin correction on a seasonal/expected dip that still slipped
    through. Flags the alert; a future detection pass can weight this incident's
    day-of-week baseline more heavily (retraining hook — the flag is captured
    now, no separate retraining job exists yet in this codebase)."""
    row = await db.anomalyalert.update(
        where={"id": alert_id}, data={"status": "false_positive", "falsePositiveMarkedBy": actor_id, "resolvedAt": _now()}
    )
    await audit_log_service.record_event(action="alert.false_positive", target_type="AnomalyAlert", target_id=alert_id, actor_id=actor_id, metadata={})
    return _alert_to_dict(row)


async def assign_unassigned_alert(alert_id: str, owner_admin_id: str, actor_id: str) -> Dict:
    """Super Admin resolving E-04 from the Unassigned queue: creates a threshold
    ownership row (default sensitivity) and clears the unassigned flag."""
    alert = await db.anomalyalert.find_unique(where={"id": alert_id})
    if alert:
        await upsert_threshold(
            metric_key=alert.metricKey, owner_admin_id=owner_admin_id,
            threshold_type=DEFAULT_THRESHOLD_TYPE, threshold_value=DEFAULT_THRESHOLD_VALUE,
            direction=DEFAULT_DIRECTION, channels=["email"], slack_webhook_url=None, actor_id=actor_id,
        )
    row = await db.anomalyalert.update(where={"id": alert_id}, data={"isUnassigned": False})
    await audit_log_service.record_event(
        action="alert.assign_owner", target_type="AnomalyAlert", target_id=alert_id, actor_id=actor_id,
        metadata={"owner_admin_id": owner_admin_id},
    )
    return _alert_to_dict(row)


# ── HTTP handlers (wired by routers/alert_routes.py) — Depends() lives on the
# handler itself, matching services/category_service.py's admin_* convention ──
async def admin_list_thresholds(metric_key: Optional[str] = None, _admin_id: str = Depends(require_admin)):
    return {"thresholds": await list_thresholds(metric_key)}


async def admin_upsert_threshold(payload: ThresholdUpsertRequest, admin_id: str = Depends(require_admin)):
    owner_id = payload.owner_admin_id or admin_id
    row = await upsert_threshold(
        metric_key=payload.metric_key, owner_admin_id=owner_id, threshold_type=payload.threshold_type,
        threshold_value=payload.threshold_value, direction=payload.direction, channels=payload.channels,
        slack_webhook_url=payload.slack_webhook_url, actor_id=admin_id,
    )
    return {"threshold": row}


async def admin_deactivate_threshold(threshold_id: str, admin_id: str = Depends(require_admin)):
    await deactivate_threshold(threshold_id, admin_id)
    return {"deactivated": True}


async def admin_list_alerts(status: Optional[str] = None, metric_key: Optional[str] = None, _admin_id: str = Depends(require_admin)):
    return {"alerts": await list_alerts(status=status, metric_key=metric_key)}


async def admin_acknowledge_alert(alert_id: str, admin_id: str = Depends(require_admin)):
    existing = await db.anomalyalert.find_unique(where={"id": alert_id})
    if not existing:
        return JSONResponse(status_code=404, content={"error": "Alert not found"})
    return {"alert": await acknowledge_alert(alert_id, admin_id)}


async def admin_mark_false_positive(alert_id: str, admin_id: str = Depends(require_admin)):
    existing = await db.anomalyalert.find_unique(where={"id": alert_id})
    if not existing:
        return JSONResponse(status_code=404, content={"error": "Alert not found"})
    return {"alert": await mark_false_positive(alert_id, admin_id)}


async def super_admin_list_unassigned(_super_admin_id: str = Depends(require_super_admin)):
    return {"alerts": await list_unassigned_alerts()}


async def super_admin_assign_unassigned(alert_id: str, payload: AssignOwnerRequest, super_admin_id: str = Depends(require_super_admin)):
    existing = await db.anomalyalert.find_unique(where={"id": alert_id})
    if not existing:
        return JSONResponse(status_code=404, content={"error": "Alert not found"})
    return {"alert": await assign_unassigned_alert(alert_id, payload.owner_admin_id, super_admin_id)}


async def admin_trigger_detection_now(_admin_id: str = Depends(require_admin)):
    """Manual trigger for local/dev testing — the scheduler already runs this on
    a timer (lib/scheduler.py); this just lets an admin fire a cycle on demand
    instead of waiting for the next tick. Disabled in production."""
    if os.environ.get("APP_ENV") == "production":
        return JSONResponse(status_code=403, content={"error": "Not available in production"})
    return await run_detection_cycle()
