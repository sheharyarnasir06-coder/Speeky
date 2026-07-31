"""
Admin Action Audit Trail Service (US-205).

Maintains a tamper-evident, append-only audit log of who viewed sensitive
analytics data, applied filters, or exported reports — for compliance and post-incident investigation.
"""

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import Depends, Query

from lib import kv_store
from lib.admin_constants import (
    ACTION_EXPORT,
    ACTION_FILTER,
    ACTION_VIEW_RESTRICTED,
    AUDIT_LOG_NS,
    GENESIS_HASH,
    RESTRICTED_ANALYTICS_MODULES,
    ROLE_ADMIN,
    ROLE_COMPLIANCE,
    ROLE_SUPER_ADMIN,
)
from lib.prisma_client import db
from lib.role_gate import has_role
from middlewares.auth_middleware import require_admin
from schemas.admin_analytics_schemas import (
    AuditLogEntry,
    AuditLogFilterRequest,
    AuditLogListResponse,
    ExportDataRequest,
    ExportDataResponse,
)
from utils.app_error import AppError


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id(prefix: str = "audit") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _canonical_json(data: Dict[str, Any]) -> str:
    """Serializes scope dict deterministically for hashing."""
    return json.dumps(data, sort_keys=True, default=str)


def compute_entry_hash(
    prev_hash: str,
    entry_id: str,
    actor_id: str,
    actor_role: str,
    timestamp_str: str,
    action_type: str,
    module: str,
    scope: Dict[str, Any],
) -> str:
    """Computes SHA-256 hash over chained fields for tamper detection."""
    scope_str = _canonical_json(scope)
    payload = f"{prev_hash}|{entry_id}|{actor_id}|{actor_role}|{timestamp_str}|{action_type}|{module}|{scope_str}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def _get_all_raw_entries() -> List[Dict[str, Any]]:
    entries = await kv_store.store.list_values(AUDIT_LOG_NS)
    # Sort chronologically by sequence number and timestamp
    entries.sort(key=lambda e: (e.get("seq", 0), e.get("timestamp", "")))
    return entries


async def verify_audit_log_integrity() -> bool:
    """
    E-03 Tampering resistance verification.
    Re-calculates hash chain for all stored entries.
    Returns True if chain is intact, False if any entry was modified or missing.
    """
    entries = await _get_all_raw_entries()
    if not entries:
        return True

    expected_prev_hash = GENESIS_HASH
    for entry in entries:
        if entry.get("prev_hash") != expected_prev_hash:
            return False

        calculated_hash = compute_entry_hash(
            prev_hash=entry.get("prev_hash", ""),
            entry_id=entry.get("id", ""),
            actor_id=entry.get("actor_id", ""),
            actor_role=entry.get("actor_role", ""),
            timestamp_str=entry.get("timestamp", ""),
            action_type=entry.get("action_type", ""),
            module=entry.get("module", ""),
            scope=entry.get("scope", {}),
        )

        if calculated_hash != entry.get("entry_hash"):
            return False

        expected_prev_hash = entry.get("entry_hash", "")

    return True


async def log_action(
    actor_id: str,
    actor_role: str,
    action_type: str,
    module: str,
    scope: Optional[Dict[str, Any]] = None,
) -> AuditLogEntry:
    """
    Appends an immutable audit log entry using hash-chaining.
    
    E-02 Debounce/batch routine view-only filter changes:
    Only log meaningful actions (exports, restricted-module access) in full detail.
    """
    scope_data = scope or {}
    
    # E-02 Routine filter change debouncing check
    if action_type == ACTION_FILTER and module not in RESTRICTED_ANALYTICS_MODULES:
        # Check if routine filter with no restricted data
        if scope_data.get("routine_filter") is True or scope_data.get("is_minor") is True:
            # Skip routine non-sensitive filter entries to reduce log clutter
            existing_entries = await _get_all_raw_entries()
            last_entry = existing_entries[-1] if existing_entries else None
            if last_entry and last_entry.get("module") == module and last_entry.get("action_type") == ACTION_FILTER:
                # Debounced: skip duplicate minor filter write
                return AuditLogEntry(**last_entry)

    entries = await _get_all_raw_entries()
    prev_hash = entries[-1]["entry_hash"] if entries else GENESIS_HASH
    seq = (entries[-1].get("seq", 0) + 1) if entries else 1

    entry_id = _new_id()
    now_dt = _now()
    timestamp_str = now_dt.isoformat()

    entry_hash = compute_entry_hash(
        prev_hash=prev_hash,
        entry_id=entry_id,
        actor_id=actor_id,
        actor_role=actor_role,
        timestamp_str=timestamp_str,
        action_type=action_type,
        module=module,
        scope=scope_data,
    )

    entry_data = {
        "id": entry_id,
        "seq": seq,
        "actor_id": actor_id,
        "actor_role": actor_role,
        "timestamp": timestamp_str,
        "action_type": action_type,
        "module": module,
        "scope": scope_data,
        "prev_hash": prev_hash,
        "entry_hash": entry_hash,
    }

    # Write to append-only kv store
    await kv_store.store.create(AUDIT_LOG_NS, entry_id, entry_data)

    return AuditLogEntry(
        id=entry_id,
        actor_id=actor_id,
        actor_role=actor_role,
        timestamp=now_dt,
        action_type=action_type,
        module=module,
        scope=scope_data,
        prev_hash=prev_hash,
        entry_hash=entry_hash,
    )


async def export_with_audit_fail_closed(
    actor_id: str,
    actor_role: str,
    module: str,
    filters: Dict[str, Any],
    export_format: str,
    content_generator_func: Any,
) -> ExportDataResponse:
    """
    E-01 Logging service failure during export ("fail closed"):
    If the audit-write fails, the export itself MUST be blocked.
    """
    scope = {
        "filters": filters,
        "export_format": export_format,
        "exported_at": _now().isoformat(),
    }

    # Step 1: Write audit log. If this throws/fails, export is blocked (fail closed).
    audit_entry = await log_action(
        actor_id=actor_id,
        actor_role=actor_role,
        action_type=ACTION_EXPORT,
        module=module,
        scope=scope,
    )

    # Step 2: Generate content after audit log write succeeds
    content = content_generator_func()

    export_id = f"exp_{uuid.uuid4().hex[:12]}"
    return ExportDataResponse(
        export_id=export_id,
        module=module,
        scope=scope,
        content=content,
        audit_entry_id=audit_entry.id,
        timestamp=audit_entry.timestamp,
    )


async def get_audit_logs(
    requesting_user: Any,
    filter_req: Optional[AuditLogFilterRequest] = None,
) -> AuditLogListResponse:
    """
    E-04 Unauthorized access to the log itself:
    Viewing the audit log is restricted to Compliance/Super Admin role.
    """
    if not has_role(requesting_user, [ROLE_COMPLIANCE, ROLE_SUPER_ADMIN]):
        raise AppError("Access denied: Compliance or Super Admin role required to view audit logs.", 403)

    is_intact = await verify_audit_log_integrity()
    raw_entries = await _get_all_raw_entries()

    filtered: List[AuditLogEntry] = []
    for raw in raw_entries:
        # Parse fields
        ts_val = raw.get("timestamp")
        dt_obj = datetime.fromisoformat(ts_val) if isinstance(ts_val, str) else ts_val

        entry = AuditLogEntry(
            id=raw["id"],
            actor_id=raw["actor_id"],
            actor_role=raw.get("actor_role", ROLE_ADMIN),
            timestamp=dt_obj,
            action_type=raw["action_type"],
            module=raw["module"],
            scope=raw.get("scope", {}),
            prev_hash=raw.get("prev_hash", GENESIS_HASH),
            entry_hash=raw.get("entry_hash", ""),
        )

        if filter_req:
            if filter_req.actor_id and entry.actor_id != filter_req.actor_id:
                continue
            if filter_req.action_type and entry.action_type != filter_req.action_type:
                continue
            if filter_req.date_from and entry.timestamp < filter_req.date_from:
                continue
            if filter_req.date_to and entry.timestamp > filter_req.date_to:
                continue

        filtered.append(entry)

    return AuditLogListResponse(
        entries=filtered,
        total=len(filtered),
        tamper_detected=not is_intact,
    )


async def attempt_edit_or_delete_audit_entry(entry_id: str) -> None:
    """
    Acceptance Criteria & E-03:
    Audit log entries are immutable and append-only. Reject all modification/deletion requests.
    """
    raise AppError("Audit log entries are immutable and cannot be edited or deleted.", 403)


# ── HTTP controllers (auth-gated, wired to router) ─────────────────────────────

async def http_list_audit_logs(
    actor_id: Optional[str] = Query(None, description="Filter by actor user ID"),
    action_type: Optional[str] = Query(None, description="Filter by action type, e.g. EXPORT"),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    admin_id: str = Depends(require_admin),
) -> AuditLogListResponse:
    """GET /analytics/audit-logs — E-04: only Compliance or Super Admin can view."""
    user = await db.user.find_unique(where={"id": admin_id})
    filter_req = AuditLogFilterRequest(
        actor_id=actor_id,
        action_type=action_type,
        date_from=date_from,
        date_to=date_to,
    )
    return await get_audit_logs(requesting_user=user, filter_req=filter_req)


async def http_verify_audit_log(admin_id: str = Depends(require_admin)) -> dict:
    """GET /analytics/audit-logs/verify — returns whether the hash chain is intact."""
    user = await db.user.find_unique(where={"id": admin_id})
    if not has_role(user, [ROLE_COMPLIANCE, ROLE_SUPER_ADMIN]):
        raise AppError("Access denied: Compliance or Super Admin role required.", 403)
    intact = await verify_audit_log_integrity()
    return {"chain_intact": intact, "checked_at": _now().isoformat()}


async def http_export_data(
    payload: ExportDataRequest,
    admin_id: str = Depends(require_admin),
) -> ExportDataResponse:
    """
    POST /analytics/export — fail-closed: audit log is written before export is returned.
    Callers POST {module, filters, export_format} and receive a CSV blob + audit_entry_id.
    """
    user = await db.user.find_unique(where={"id": admin_id})
    actor_role = getattr(user, "role", ROLE_ADMIN)
    if hasattr(actor_role, "value"):
        actor_role = actor_role.value

    def _generate() -> str:
        # Stub: real implementation would call the appropriate analytics function.
        # The important contract is that this runs AFTER the audit log write succeeds.
        return f"module={payload.module},filters={payload.filters},format={payload.export_format}\n"

    return await export_with_audit_fail_closed(
        actor_id=admin_id,
        actor_role=actor_role,
        module=payload.module,
        filters=payload.filters,
        export_format=payload.export_format,
        content_generator_func=_generate,
    )
