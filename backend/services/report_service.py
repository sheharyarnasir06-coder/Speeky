"""
Scheduled Report Generation & Distribution (GAP-04 / US-202).

Report figures come from the SAME platform_metrics_service pipeline the
anomaly monitor and (eventually) the interactive dashboard use — this module
only resolves a date range, calls get_dashboard_snapshot, renders, and
delivers. It never computes its own numbers (acceptance criterion: a report
can't diverge from the dashboard).
"""

import logging
import os
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional

from fastapi import Depends
from fastapi.responses import JSONResponse
from prisma import Json

from lib import recurrence, report_render
from lib.prisma_client import db
from middlewares.auth_middleware import require_admin
from schemas.report_schemas import ReportTemplateCreateRequest, ReportTemplateUpdateRequest
from services import audit_log_service, notification_service, platform_metrics_service
from utils import email_utils

logger = logging.getLogger(__name__)

MAX_GENERATION_ATTEMPTS = 3  # initial attempt + 2 retries (E-01)
REPORTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads", "reports")
DASHBOARD_URL = "/dashboard/admin/analytics"

os.makedirs(REPORTS_DIR, exist_ok=True)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def requires_external_confirmation(metrics: List[str], recipients: List[Dict]) -> bool:
    """E-04: Revenue data addressed to an external (non-employee) recipient
    needs an explicit confirmation before the template can be saved."""
    return "revenue" in metrics and any(r["type"] == "external" for r in recipients)


def resolve_date_range(date_range_type: str, today: date) -> tuple:
    if date_range_type == "last_7_days":
        return today - timedelta(days=6), today
    if date_range_type == "last_30_days":
        return today - timedelta(days=29), today
    if date_range_type == "month_to_date":
        return today.replace(day=1), today
    # No stored explicit start/end for a "custom" range in this pass — falls
    # back to last_30_days rather than erroring. Flagged for a future
    # date-picker addition to ReportTemplate.
    return today - timedelta(days=29), today


def _template_to_dict(r) -> Dict:
    return {
        "id": r.id,
        "name": r.name,
        "owner_admin_id": r.ownerAdminId,
        "metrics": r.metrics,
        "date_range_type": r.dateRangeType,
        "recurrence": r.recurrence,
        "recurrence_day": r.recurrenceDay,
        "recurrence_hour": r.recurrenceHour,
        "recurrence_minute": r.recurrenceMinute,
        "timezone": r.timezone,
        "recipients": r.recipients,
        "format": r.format,
        "is_active": r.isActive,
        "next_run_at": r.nextRunAt.isoformat() if r.nextRunAt else None,
        "currently_generating": r.currentlyGenerating,
        "pending_schedule_update": r.pendingScheduleUpdate,
    }


def _run_to_dict(r) -> Dict:
    return {
        "id": r.id,
        "template_id": r.templateId,
        "status": r.status,
        "attempt": r.attempt,
        "triggered_by": r.triggeredBy,
        "file_url": r.fileUrl,
        "format": r.format,
        "delivery_log": r.deliveryLog,
        "error_message": r.errorMessage,
        "started_at": r.startedAt.isoformat(),
        "completed_at": r.completedAt.isoformat() if r.completedAt else None,
    }


# ── Template CRUD ─────────────────────────────────────────────────────────
async def create_template(admin_id: str, payload: ReportTemplateCreateRequest):
    recipients = [r.model_dump() for r in payload.recipients]
    if requires_external_confirmation(payload.metrics, recipients) and not payload.confirmed_external_send:
        return None, "external_revenue_confirmation_required"

    next_run = recurrence.compute_next_run(
        recurrence=payload.recurrence, recurrence_day=payload.recurrence_day,
        recurrence_hour=payload.recurrence_hour, recurrence_minute=payload.recurrence_minute,
        timezone_name=payload.timezone, now_utc=_now(),
    )
    row = await db.reporttemplate.create(data={
        "name": payload.name, "ownerAdminId": admin_id, "metrics": payload.metrics,
        "dateRangeType": payload.date_range_type, "recurrence": payload.recurrence,
        "recurrenceDay": payload.recurrence_day, "recurrenceHour": payload.recurrence_hour,
        "recurrenceMinute": payload.recurrence_minute, "timezone": payload.timezone,
        "recipients": Json(recipients), "format": payload.format,
        "nextRunAt": next_run,
    })
    await audit_log_service.record_event(
        action="report_template.create", target_type="ReportTemplate", target_id=row.id, actor_id=admin_id,
        metadata={"name": payload.name, "recurrence": payload.recurrence},
    )
    return _template_to_dict(row), None


async def update_template(template_id: str, admin_id: str, payload: ReportTemplateUpdateRequest):
    existing = await db.reporttemplate.find_unique(where={"id": template_id})
    if not existing:
        return None, "not_found"

    fields = {k: v for k, v in payload.model_dump(exclude={"confirmed_external_send"}).items() if v is not None}

    metrics = fields.get("metrics", existing.metrics)
    recipients = fields.get("recipients", existing.recipients)
    if requires_external_confirmation(metrics, recipients) and not payload.confirmed_external_send:
        return None, "external_revenue_confirmation_required"

    # E-03: a run is in progress — queue the edit instead of applying it now.
    if recurrence.should_defer_edit(existing.currentlyGenerating):
        row = await db.reporttemplate.update(
            where={"id": template_id}, data={"pendingScheduleUpdate": Json(fields)}
        )
        await audit_log_service.record_event(
            action="report_template.edit_queued", target_type="ReportTemplate", target_id=template_id,
            actor_id=admin_id, metadata={"fields": list(fields.keys())},
        )
        return _template_to_dict(row), "queued"

    data = dict(fields)
    if any(k in fields for k in ("recurrence", "recurrence_day", "recurrence_hour", "recurrence_minute", "timezone")):
        data["nextRunAt"] = recurrence.compute_next_run(
            recurrence=fields.get("recurrence", existing.recurrence),
            recurrence_day=fields.get("recurrence_day", existing.recurrenceDay),
            recurrence_hour=fields.get("recurrence_hour", existing.recurrenceHour),
            recurrence_minute=fields.get("recurrence_minute", existing.recurrenceMinute),
            timezone_name=fields.get("timezone", existing.timezone),
            now_utc=_now(),
        )
    if "recipients" in data:
        data["recipients"] = Json(data["recipients"])

    row = await db.reporttemplate.update(where={"id": template_id}, data=data)
    await audit_log_service.record_event(
        action="report_template.update", target_type="ReportTemplate", target_id=template_id, actor_id=admin_id,
        metadata={"fields": list(fields.keys())},
    )
    return _template_to_dict(row), None


async def delete_template(template_id: str, admin_id: str) -> bool:
    existing = await db.reporttemplate.find_unique(where={"id": template_id})
    if not existing:
        return False
    await db.reporttemplate.delete(where={"id": template_id})
    await audit_log_service.record_event(
        action="report_template.delete", target_type="ReportTemplate", target_id=template_id, actor_id=admin_id, metadata={},
    )
    return True


async def list_templates() -> List[Dict]:
    rows = await db.reporttemplate.find_many(order={"createdAt": "desc"})
    return [_template_to_dict(r) for r in rows]


async def list_history(template_id: Optional[str] = None, limit: int = 50) -> List[Dict]:
    where = {"templateId": template_id} if template_id else {}
    rows = await db.reportrun.find_many(where=where, order={"createdAt": "desc"}, take=min(limit, 200))
    return [_run_to_dict(r) for r in rows]


# ── Generation + delivery ────────────────────────────────────────────────
async def _resolve_recipient_email(recipient: Dict) -> Optional[str]:
    if recipient["type"] == "external":
        return recipient["value"]
    user = await db.user.find_unique(where={"id": recipient["value"]})
    return user.email if user else None


async def _generate_file(template) -> tuple:
    """Renders the report and writes it under uploads/reports/. Raises on
    failure so the caller's retry loop can catch it (E-01)."""
    today = _now().date()
    start, end = resolve_date_range(template.dateRangeType, today)
    snapshot = await platform_metrics_service.get_dashboard_snapshot(template.metrics, start, end)
    date_label = f"{start.isoformat()} to {end.isoformat()}"

    fmt = template.format if template.format != "both" else "pdf"
    run_file_id = uuid.uuid4().hex
    if fmt == "csv":
        content = report_render.render_csv(platform_metrics_service.METRIC_LABELS, snapshot)
        filename = f"{run_file_id}.csv"
    else:
        content = report_render.render_pdf(template.name, date_label, platform_metrics_service.METRIC_LABELS, snapshot)
        filename = f"{run_file_id}.pdf"

    path = os.path.join(REPORTS_DIR, filename)
    with open(path, "wb") as f:
        f.write(content)

    return filename, content, fmt


async def run_report(template_id: str, triggered_by: str = "schedule") -> Optional[Dict]:
    template = await db.reporttemplate.find_unique(where={"id": template_id})
    if not template:
        return None
    if template.currentlyGenerating:
        logger.info(f"Report {template_id} already generating — skipping duplicate trigger")
        return None

    await db.reporttemplate.update(where={"id": template_id}, data={"currentlyGenerating": True})
    run = await db.reportrun.create(data={"templateId": template_id, "status": "generating", "triggeredBy": triggered_by})

    filename = content = fmt = None
    error_message = None
    attempt = 0

    for attempt in range(1, MAX_GENERATION_ATTEMPTS + 1):  # E-01: initial try + 2 retries
        try:
            filename, content, fmt = await _generate_file(template)
            break
        except Exception as exc:
            error_message = str(exc)
            logger.warning(f"Report generation attempt {attempt} failed for {template_id}: {exc}")

    delivery_log: List[Dict] = []

    if filename is None:
        # E-01: exhausted retries — notify the owner instead of failing silently.
        run = await db.reportrun.update(
            where={"id": run.id},
            data={"status": "failed_permanently", "attempt": attempt, "errorMessage": error_message, "completedAt": _now()},
        )
        owner_email = await _resolve_recipient_email({"type": "internal", "value": template.ownerAdminId})
        if owner_email:
            await email_utils.send_report_generation_failed_email(owner_email, template.name, DASHBOARD_URL)
        await notification_service.send_admin_push(
            template.ownerAdminId, f"Report '{template.name}' failed to generate — view the dashboard directly."
        )
    else:
        file_url = f"/uploads/reports/{filename}"
        for recipient in template.recipients:
            email = await _resolve_recipient_email(recipient)
            if not email:
                delivery_log.append({"recipient": recipient["value"], "type": recipient["type"], "status": "failed", "error": "No email on file"})
                continue
            try:
                await email_utils.send_report_email(email, template.name, filename, content, fmt)
                delivery_log.append({"recipient": email, "type": recipient["type"], "status": "sent", "error": None})
            except Exception as exc:
                # E-02: one bad/bounced address is logged but never blocks the rest.
                logger.warning(f"Report delivery failed for {email}: {exc}")
                delivery_log.append({"recipient": email, "type": recipient["type"], "status": "bounced", "error": str(exc)})

        run = await db.reportrun.update(
            where={"id": run.id},
            data={
                "status": "success", "attempt": attempt, "fileUrl": file_url, "format": fmt,
                "deliveryLog": Json(delivery_log), "completedAt": _now(),
            },
        )
        failures = [d for d in delivery_log if d["status"] != "sent"]
        if failures:
            await notification_service.send_admin_push(
                template.ownerAdminId,
                f"Report '{template.name}': {len(failures)} of {len(delivery_log)} recipient(s) failed delivery.",
            )

    await audit_log_service.record_event(
        action="report_template.send", target_type="ReportTemplate", target_id=template_id,
        metadata={"run_id": run.id, "status": run.status, "triggered_by": triggered_by},
    )

    # E-03: apply any edit queued while this run was in progress, THEN clear the flag.
    fresh = await db.reporttemplate.find_unique(where={"id": template_id})
    update_data: Dict = {"currentlyGenerating": False}
    if fresh and fresh.pendingScheduleUpdate:
        pending = fresh.pendingScheduleUpdate
        update_data.update(pending)
        update_data["pendingScheduleUpdate"] = None
        if "recipients" in pending:
            update_data["recipients"] = Json(pending["recipients"])
        if any(k in pending for k in ("recurrence", "recurrence_day", "recurrence_hour", "recurrence_minute", "timezone")):
            update_data["nextRunAt"] = recurrence.compute_next_run(
                recurrence=pending.get("recurrence", fresh.recurrence),
                recurrence_day=pending.get("recurrence_day", fresh.recurrenceDay),
                recurrence_hour=pending.get("recurrence_hour", fresh.recurrenceHour),
                recurrence_minute=pending.get("recurrence_minute", fresh.recurrenceMinute),
                timezone_name=pending.get("timezone", fresh.timezone),
                now_utc=_now(),
            )
        else:
            update_data["nextRunAt"] = recurrence.compute_next_run(
                recurrence=fresh.recurrence, recurrence_day=fresh.recurrenceDay,
                recurrence_hour=fresh.recurrenceHour, recurrence_minute=fresh.recurrenceMinute,
                timezone_name=fresh.timezone, now_utc=_now(),
            )
    elif fresh and fresh.recurrence != "none":
        update_data["nextRunAt"] = recurrence.compute_next_run(
            recurrence=fresh.recurrence, recurrence_day=fresh.recurrenceDay,
            recurrence_hour=fresh.recurrenceHour, recurrence_minute=fresh.recurrenceMinute,
            timezone_name=fresh.timezone, now_utc=_now(),
        )
    await db.reporttemplate.update(where={"id": template_id}, data=update_data)

    return _run_to_dict(run)


async def dispatch_due_reports(now: Optional[datetime] = None) -> Dict:
    """Scheduler entry point — runs every REPORT_DISPATCH_INTERVAL_MINUTES."""
    now = now or _now()
    due = await db.reporttemplate.find_many(where={"isActive": True, "nextRunAt": {"lte": now}, "currentlyGenerating": False})
    results = []
    for template in due:
        result = await run_report(template.id, triggered_by="schedule")
        if result:
            results.append(result["id"])
    return {"dispatched": len(results), "run_ids": results}


# ── HTTP handlers (wired by routers/report_routes.py) ───────────────────────
async def admin_list_templates(_admin_id: str = Depends(require_admin)):
    return {"templates": await list_templates()}


async def admin_create_template(payload: ReportTemplateCreateRequest, admin_id: str = Depends(require_admin)):
    row, err = await create_template(admin_id, payload)
    if err == "external_revenue_confirmation_required":
        return JSONResponse(status_code=400, content={"error": "confirmation_required", "message": "Revenue data addressed to an external recipient needs confirmation."})
    return {"template": row}


async def admin_update_template(template_id: str, payload: ReportTemplateUpdateRequest, admin_id: str = Depends(require_admin)):
    row, err = await update_template(template_id, admin_id, payload)
    if err == "not_found":
        return JSONResponse(status_code=404, content={"error": "Report template not found"})
    if err == "external_revenue_confirmation_required":
        return JSONResponse(status_code=400, content={"error": "confirmation_required", "message": "Revenue data addressed to an external recipient needs confirmation."})
    return {"template": row, "queued": err == "queued"}


async def admin_delete_template(template_id: str, admin_id: str = Depends(require_admin)):
    ok = await delete_template(template_id, admin_id)
    if not ok:
        return JSONResponse(status_code=404, content={"error": "Report template not found"})
    return {"deleted": True}


async def admin_list_history(template_id: Optional[str] = None, _admin_id: str = Depends(require_admin)):
    return {"runs": await list_history(template_id)}


async def admin_send_now(template_id: str, admin_id: str = Depends(require_admin)):
    template = await db.reporttemplate.find_unique(where={"id": template_id})
    if not template:
        return JSONResponse(status_code=404, content={"error": "Report template not found"})
    run = await run_report(template_id, triggered_by="manual")
    if run is None:
        return JSONResponse(status_code=409, content={"error": "Report is already generating"})
    return {"run": run}
