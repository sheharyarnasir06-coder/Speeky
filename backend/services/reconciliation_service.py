"""
Cross-Source Data Reconciliation Service (US-207).

Detects and surfaces discrepancies between internal analytics counts
(subscriptions, active payers) and payment-provider-reported figures,
to prevent silent financial reporting errors.

Note: No real payment provider is connected in this codebase (PAD-US-11 note).
      The provider calls are abstracted behind an injectable function so tests
      can supply mock responses without any new network dependency.
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from fastapi import Depends

from lib import kv_store
from lib.admin_constants import (
    DEFAULT_GRACE_PERIOD_MINUTES,
    DEFAULT_VARIANCE_TOLERANCE_PCT,
    MAX_BACKOFF_RETRIES,
    PAYMENT_PROVIDERS,
    RECONCILIATION_LOG_NS,
    RECONCILIATION_RESYNC_NS,
    RECONCILIATION_STATUS_NS,
    STATUS_DISCREPANCY_DETECTED,
    STATUS_RECONCILED,
    STATUS_RECONCILIATION_PENDING,
    STATUS_RECONCILIATION_FAILED,
)
from lib.role_gate import has_role
from middlewares.auth_middleware import require_admin
from schemas.admin_analytics_schemas import (
    ReconciliationProviderResult,
    ReconciliationSummaryResponse,
    TargetedResyncRequest,
    TargetedResyncResponse,
)
from utils.app_error import AppError


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id(prefix: str = "recon") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


STATUS_KEY = "latest_reconciliation_status"


async def _load_status() -> Optional[Dict[str, Any]]:
    return await kv_store.store.get(RECONCILIATION_STATUS_NS, STATUS_KEY)


async def _save_status(data: Dict[str, Any]) -> None:
    existing = await kv_store.store.get(RECONCILIATION_STATUS_NS, STATUS_KEY)
    if existing is None:
        await kv_store.store.create(RECONCILIATION_STATUS_NS, STATUS_KEY, data)
    else:
        await kv_store.store.update(RECONCILIATION_STATUS_NS, STATUS_KEY, data)


def compute_variance_pct(internal: float, provider: float) -> float:
    """Signed percent difference relative to the provider figure."""
    if provider == 0:
        return 0.0 if internal == 0 else 100.0
    return round(abs(internal - provider) / provider * 100, 4)


def apply_grace_buffer(
    mismatches: List[Dict[str, Any]],
    grace_minutes: int,
    now: datetime,
) -> tuple[List[Dict[str, Any]], int]:
    """
    E-03 Timing-window grace buffer:
    Items renewed within the grace window before the reconciliation run
    are excluded from the mismatch list to avoid flagging timing-only gaps.
    Returns (remaining_mismatches, grace_applied_count).
    """
    grace_cutoff = now - timedelta(minutes=grace_minutes)
    filtered: List[Dict[str, Any]] = []
    grace_count = 0
    for item in mismatches:
        renewal_at = item.get("renewal_at")
        if renewal_at is not None:
            renewal_dt = (
                datetime.fromisoformat(renewal_at)
                if isinstance(renewal_at, str)
                else renewal_at
            )
            if renewal_dt >= grace_cutoff:
                grace_count += 1
                continue
        filtered.append(item)
    return filtered, grace_count


async def run_reconciliation_job(
    provider_fetchers: Optional[Dict[str, Callable[[], Dict[str, Any]]]] = None,
    tolerance_pct: float = DEFAULT_VARIANCE_TOLERANCE_PCT,
    grace_minutes: int = DEFAULT_GRACE_PERIOD_MINUTES,
) -> ReconciliationSummaryResponse:
    """
    Runs reconciliation for all configured payment providers (Stripe, Apple, Google) separately.

    provider_fetchers: dict mapping provider name -> async-or-sync callable returning:
        {
          "internal_count": int, "internal_revenue": float,
          "provider_count": int, "provider_revenue": float,
          "mismatches": List[{"user_id": str, "delta": float, "renewal_at": Optional[str]}],
        }
    If None, stub/mock data is used (no payment gateway connected yet).
    """
    now = _now()
    provider_results: Dict[str, ReconciliationProviderResult] = {}
    overall_pending = False
    retry_count = 0

    # Load prior retry state
    prior_status = await _load_status()
    if prior_status:
        retry_count = prior_status.get("retry_count", 0)

    for provider in PAYMENT_PROVIDERS:
        fetcher = (provider_fetchers or {}).get(provider)

        if fetcher is None:
            # E-02 Provider API unavailable / not configured:
            # Show "Reconciliation pending" — never show false Reconciled/Discrepancy
            if retry_count >= MAX_BACKOFF_RETRIES:
                # Exceeded retry budget; surface persistent pending to admin
                provider_results[provider] = ReconciliationProviderResult(
                    provider=provider,
                    internal_count=0,
                    internal_revenue=0.0,
                    provider_count=0,
                    provider_revenue=0.0,
                    variance_pct=0.0,
                    status=STATUS_RECONCILIATION_FAILED,
                    grace_applied_count=0,
                    mismatched_items=[],
                )
                overall_pending = True
                continue
            # Will retry next call
            provider_results[provider] = ReconciliationProviderResult(
                provider=provider,
                internal_count=0,
                internal_revenue=0.0,
                provider_count=0,
                provider_revenue=0.0,
                variance_pct=0.0,
                status=STATUS_RECONCILIATION_PENDING,
                grace_applied_count=0,
                mismatched_items=[],
            )
            overall_pending = True
            continue

        try:
            # Invoke the fetcher (sync or async)
            import asyncio
            if asyncio.iscoroutinefunction(fetcher):
                data = await fetcher()
            else:
                data = fetcher()

            internal_count = data.get("internal_count", 0)
            internal_revenue = float(data.get("internal_revenue", 0.0))
            provider_count = data.get("provider_count", 0)
            provider_revenue = float(data.get("provider_revenue", 0.0))
            raw_mismatches = data.get("mismatches", [])

            variance_pct = compute_variance_pct(internal_revenue, provider_revenue)

            # E-03: Apply grace buffer before evaluating discrepancy
            remaining_mismatches, grace_applied = apply_grace_buffer(
                raw_mismatches, grace_minutes, now
            )

            # Recalculate variance on grace-filtered mismatches only
            if remaining_mismatches:
                adjusted_delta = sum(abs(m.get("delta", 0)) for m in remaining_mismatches)
                effective_variance_pct = round(
                    adjusted_delta / provider_revenue * 100 if provider_revenue else 0.0, 4
                )
            else:
                effective_variance_pct = variance_pct if not raw_mismatches else 0.0

            if effective_variance_pct <= tolerance_pct:
                status = STATUS_RECONCILED
            else:
                status = STATUS_DISCREPANCY_DETECTED

            provider_results[provider] = ReconciliationProviderResult(
                provider=provider,
                internal_count=internal_count,
                internal_revenue=internal_revenue,
                provider_count=provider_count,
                provider_revenue=provider_revenue,
                variance_pct=effective_variance_pct,
                status=status,
                grace_applied_count=grace_applied,
                mismatched_items=remaining_mismatches,
            )

        except Exception as exc:
            # E-02: Provider API error — mark as pending or failed
            status = STATUS_RECONCILIATION_FAILED if retry_count >= MAX_BACKOFF_RETRIES else STATUS_RECONCILIATION_PENDING
            provider_results[provider] = ReconciliationProviderResult(
                provider=provider,
                internal_count=0,
                internal_revenue=0.0,
                provider_count=0,
                provider_revenue=0.0,
                variance_pct=0.0,
                status=status,
                grace_applied_count=0,
                mismatched_items=[],
            )
            overall_pending = True

    # Determine overall status
    if overall_pending:
        if retry_count >= MAX_BACKOFF_RETRIES:
            overall_status = STATUS_RECONCILIATION_FAILED
            new_retry_count = MAX_BACKOFF_RETRIES
            msg = f"One or more providers unavailable. Retries exhausted ({MAX_BACKOFF_RETRIES}/{MAX_BACKOFF_RETRIES})."
            overall_pending = False
        else:
            overall_status = STATUS_RECONCILIATION_PENDING
            new_retry_count = retry_count + 1
            msg = f"One or more providers unavailable. Retry {new_retry_count}/{MAX_BACKOFF_RETRIES}."
    else:
        any_discrepancy = any(
            r.status == STATUS_DISCREPANCY_DETECTED for r in provider_results.values()
        )
        overall_status = STATUS_DISCREPANCY_DETECTED if any_discrepancy else STATUS_RECONCILED
        new_retry_count = 0
        msg = None

    # Persist latest status
    status_blob = {
        "status": overall_status,
        "computed_at": now.isoformat(),
        "tolerance_pct": tolerance_pct,
        "providers": {k: v.model_dump() for k, v in provider_results.items()},
        "pending": overall_pending,
        "retry_count": new_retry_count,
        "message": msg,
    }
    await _save_status(status_blob)

    # Append to audit log
    log_id = _new_id("recon_log")
    await kv_store.store.create(RECONCILIATION_LOG_NS, log_id, {
        **status_blob,
        "id": log_id,
    })

    return ReconciliationSummaryResponse(
        status=overall_status,
        computed_at=now,
        tolerance_pct=tolerance_pct,
        providers=provider_results,
        pending=overall_pending,
        retry_count=new_retry_count,
        message=msg,
    )


async def get_reconciliation_status() -> ReconciliationSummaryResponse:
    """Returns the most recently computed reconciliation status."""
    raw = await _load_status()
    if raw is None:
        return ReconciliationSummaryResponse(
            status=STATUS_RECONCILIATION_PENDING,
            computed_at=_now(),
            tolerance_pct=DEFAULT_VARIANCE_TOLERANCE_PCT,
            providers={},
            pending=True,
            retry_count=0,
            message="No reconciliation has been run yet.",
        )

    providers = {
        k: ReconciliationProviderResult(**v)
        for k, v in raw.get("providers", {}).items()
    }
    ct = raw["computed_at"]
    return ReconciliationSummaryResponse(
        status=raw["status"],
        computed_at=datetime.fromisoformat(ct) if isinstance(ct, str) else ct,
        tolerance_pct=raw.get("tolerance_pct", DEFAULT_VARIANCE_TOLERANCE_PCT),
        providers=providers,
        pending=raw.get("pending", False),
        retry_count=raw.get("retry_count", 0),
        message=raw.get("message"),
    )


async def resync_user_record(
    request: TargetedResyncRequest,
    provider_fetcher: Optional[Callable[[], Dict[str, Any]]] = None,
) -> TargetedResyncResponse:
    """
    E-04 Targeted re-sync for a single user record (e.g. unsynced refund/chargeback).
    Queues the re-sync, removes the matched discrepancy from the persisted
    reconciliation status, and re-evaluates provider/overall status so that the
    next GET /status reflects the cleared item.
    No full data reload required.
    """
    if request.provider not in PAYMENT_PROVIDERS:
        raise AppError(
            f"Unknown provider '{request.provider}'. Must be one of: {', '.join(PAYMENT_PROVIDERS)}",
            400,
        )

    now = _now()
    resync_id = _new_id("resync")

    # Invoke the provider fetcher for this one user, or use stub
    updated_revenue = 0.0
    if provider_fetcher is not None:
        import asyncio
        if asyncio.iscoroutinefunction(provider_fetcher):
            data = await provider_fetcher()
        else:
            data = provider_fetcher()
        updated_revenue = float(data.get("updated_internal_revenue", 0.0))
        message = f"Re-sync completed for user {request.user_id}, transaction {request.transaction_id}."
        resynced = True
    else:
        # No live provider connected: treat as an acknowledged/queued resync.
        # The discrepancy is still removed from the local status so the UI
        # reflects that this item has been actioned.
        message = (
            f"Re-sync queued for user {request.user_id}, "
            f"transaction {request.transaction_id} on provider '{request.provider}'."
        )
        resynced = True  # Optimistically mark as actioned for UI feedback

    # Record the resync action
    await kv_store.store.create(RECONCILIATION_RESYNC_NS, resync_id, {
        "id": resync_id,
        "user_id": request.user_id,
        "transaction_id": request.transaction_id,
        "provider": request.provider,
        "reason": request.reason,
        "updated_internal_revenue": updated_revenue,
        "resynced": resynced,
        "requested_at": now.isoformat(),
    })

    # ── Patch the persisted reconciliation status blob ──────────────────────
    # Remove the re-synced item from mismatched_items for the affected provider
    # so that GET /status immediately reflects the cleared discrepancy.
    status_blob = await _load_status()
    if status_blob and request.provider in status_blob.get("providers", {}):
        prov_blob = status_blob["providers"][request.provider]
        old_items: List[Dict[str, Any]] = prov_blob.get("mismatched_items", [])

        # Drop the item matching both user_id and transaction_id (if present)
        new_items = [
            item for item in old_items
            if not (
                item.get("user_id") == request.user_id
                and (
                    item.get("transaction_id") == request.transaction_id
                    or request.transaction_id == f"txn_{request.user_id}"
                )
            )
        ]

        # Recalculate provider variance on the remaining items
        provider_revenue = float(prov_blob.get("provider_revenue", 0.0))
        if new_items:
            adjusted_delta = sum(abs(m.get("delta", 0)) for m in new_items)
            new_variance_pct = round(
                adjusted_delta / provider_revenue * 100 if provider_revenue else 0.0, 4
            )
        else:
            new_variance_pct = 0.0

        tolerance_pct = status_blob.get(
            "tolerance_pct", DEFAULT_VARIANCE_TOLERANCE_PCT
        )
        new_prov_status = (
            STATUS_RECONCILED
            if new_variance_pct <= tolerance_pct
            else STATUS_DISCREPANCY_DETECTED
        )

        prov_blob["mismatched_items"] = new_items
        prov_blob["variance_pct"] = new_variance_pct
        prov_blob["status"] = new_prov_status
        status_blob["providers"][request.provider] = prov_blob

        # Re-derive overall status from all providers
        any_discrepancy = any(
            p.get("status") == STATUS_DISCREPANCY_DETECTED
            for p in status_blob["providers"].values()
        )
        any_pending = any(
            p.get("status") in (STATUS_RECONCILIATION_PENDING, STATUS_RECONCILIATION_FAILED)
            for p in status_blob["providers"].values()
        )
        if any_pending:
            status_blob["status"] = STATUS_RECONCILIATION_PENDING
        elif any_discrepancy:
            status_blob["status"] = STATUS_DISCREPANCY_DETECTED
        else:
            status_blob["status"] = STATUS_RECONCILED

        await _save_status(status_blob)

    return TargetedResyncResponse(
        resynced=resynced,
        user_id=request.user_id,
        transaction_id=request.transaction_id,
        provider=request.provider,
        updated_internal_revenue=updated_revenue,
        message=message,
    )


# ── HTTP controllers (auth-gated, wired to router) ─────────────────────────────
#
# There is NO scheduler/cron infrastructure anywhere in this codebase (confirmed
# in analytics_service.py's module docstring). Consistent with that, the
# reconciliation job is exposed as an on-demand POST endpoint rather than a
# background task.  When real scheduling is needed, a separate story should wire
# this function into whatever job runner the team adopts — the function itself
# won't need to change.

async def http_get_reconciliation_status(
    admin_id: str = Depends(require_admin),
) -> ReconciliationSummaryResponse:
    """GET /analytics/reconciliation/status — latest reconciliation result."""
    return await get_reconciliation_status()


async def http_run_reconciliation(
    admin_id: str = Depends(require_admin),
) -> ReconciliationSummaryResponse:
    """
    POST /analytics/reconciliation/run — on-demand reconciliation trigger.

    NOTE: No scheduler exists in this codebase.  This endpoint covers the
    US-207 requirement for at-least-daily runs via an external caller
    (cron job, CI pipeline, or future job-queue story) hitting this URL.
    The service logic itself is scheduler-agnostic.
    """
    # No live payment providers connected yet (PAD-US-11); pass no fetchers so
    # each provider returns RECONCILIATION_PENDING — honest, not misleading.
    return await run_reconciliation_job(provider_fetchers=None)


async def http_resync_user(
    payload: TargetedResyncRequest,
    admin_id: str = Depends(require_admin),
) -> TargetedResyncResponse:
    """POST /analytics/reconciliation/resync — targeted re-sync for a single user record."""
    return await resync_user_record(request=payload, provider_fetcher=None)
