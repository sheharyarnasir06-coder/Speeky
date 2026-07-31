from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, model_validator


# ── US-205 Audit Log Schemas ──────────────────────────────────────────────────
class AuditLogEntry(BaseModel):
    id: str
    actor_id: str
    actor_role: str
    timestamp: datetime
    action_type: str
    module: str
    scope: Dict[str, Any] = Field(default_factory=dict)
    prev_hash: str
    entry_hash: str


class AuditLogFilterRequest(BaseModel):
    actor_id: Optional[str] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    action_type: Optional[str] = None


class AuditLogListResponse(BaseModel):
    entries: List[AuditLogEntry]
    total: int
    tamper_detected: bool = False


class ExportDataRequest(BaseModel):
    module: str
    filters: Dict[str, Any] = Field(default_factory=dict)
    export_format: str = "csv"


class ExportDataResponse(BaseModel):
    export_id: str
    module: str
    scope: Dict[str, Any]
    content: str
    audit_entry_id: str
    timestamp: datetime


# ── US-206 Custom Dashboard Schemas ───────────────────────────────────────────
class DashboardWidgetConfig(BaseModel):
    id: str
    position: Optional[int] = None
    settings: Optional[Dict[str, Any]] = None


class SavedViewCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    widgets: List[DashboardWidgetConfig]
    filters: Dict[str, Any] = Field(default_factory=dict)
    is_shared: bool = False
    overwrite: bool = False


class SavedViewUpdateRequest(BaseModel):
    name: Optional[str] = None
    widgets: Optional[List[DashboardWidgetConfig]] = None
    filters: Optional[Dict[str, Any]] = None
    is_shared: Optional[bool] = None


class SavedViewResponse(BaseModel):
    id: str
    user_id: str
    name: str
    widgets: List[Dict[str, Any]]
    filters: Dict[str, Any]
    is_shared: bool
    warnings: List[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class SavedViewListResponse(BaseModel):
    views: List[SavedViewResponse]


# ── US-207 Reconciliation Schemas ─────────────────────────────────────────────
class ReconciliationProviderResult(BaseModel):
    provider: str
    internal_count: int
    internal_revenue: float
    provider_count: int
    provider_revenue: float
    variance_pct: float
    status: str
    grace_applied_count: int = 0
    mismatched_items: List[Dict[str, Any]] = Field(default_factory=list)


class ReconciliationSummaryResponse(BaseModel):
    status: str
    computed_at: datetime
    tolerance_pct: float
    providers: Dict[str, ReconciliationProviderResult]
    pending: bool = False
    retry_count: int = 0
    message: Optional[str] = None


class TargetedResyncRequest(BaseModel):
    user_id: str
    transaction_id: str
    provider: str
    reason: str = Field("unsynced_refund_or_chargeback")


class TargetedResyncResponse(BaseModel):
    resynced: bool
    user_id: str
    transaction_id: str
    provider: str
    updated_internal_revenue: float
    message: str
