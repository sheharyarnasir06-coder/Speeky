"""
Custom Dashboard Layout & Saved Views Service (US-206).

Allows individual admins to pin frequently used widgets and save
filter combinations as reusable, named views. Views are personal/private
by default, and shared views respect role-based widget filtering.
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import Depends

from lib import kv_store
from lib.admin_constants import (
    AVAILABLE_SEGMENTS,
    AVAILABLE_WIDGETS,
    DASHBOARD_VIEW_NS,
    DEPRECATED_WIDGETS,
    WIDGET_REQUIRED_ROLES,
)
from lib.role_gate import has_role
from middlewares.auth_middleware import require_admin
from schemas.admin_analytics_schemas import (
    DashboardWidgetConfig,
    SavedViewCreateRequest,
    SavedViewListResponse,
    SavedViewResponse,
    SavedViewUpdateRequest,
)
from utils.app_error import AppError

PLACEHOLDER_LABEL = "This widget is no longer available"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id(prefix: str = "view") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _resolve_widgets_for_user(
    widgets: List[Dict[str, Any]], requesting_user: Any
) -> tuple[List[Dict[str, Any]], List[str]]:
    """
    E-01: Replace deprecated/unknown widgets with placeholder.
    E-03: Hidden restricted widgets for lower-permission admins.
    Returns (resolved_widgets, warnings).
    """
    resolved: List[Dict[str, Any]] = []
    warnings: List[str] = []

    for w in widgets:
        widget_id = w.get("id", "")

        # E-01: Deprecated widget — show placeholder instead of removing
        if widget_id in DEPRECATED_WIDGETS:
            resolved.append({
                **w,
                "deprecated": True,
                "placeholder_label": PLACEHOLDER_LABEL,
            })
            warnings.append(f"Widget '{widget_id}' is deprecated: {PLACEHOLDER_LABEL}")
            continue

        # E-01: Unknown widget (was removed from available set)
        if widget_id not in AVAILABLE_WIDGETS:
            resolved.append({
                **w,
                "deprecated": True,
                "placeholder_label": PLACEHOLDER_LABEL,
            })
            warnings.append(f"Widget '{widget_id}' is no longer available.")
            continue

        # E-03: Widget requires a role the viewer doesn't have — hide it entirely
        required_roles = WIDGET_REQUIRED_ROLES.get(widget_id)
        if required_roles and not has_role(requesting_user, required_roles):
            # Hidden: not included in returned list; no elevated access granted
            warnings.append(f"Widget '{widget_id}' hidden: insufficient role.")
            continue

        resolved.append(w)

    return resolved, warnings


def _resolve_filters_for_segments(
    filters: Dict[str, Any],
) -> tuple[Dict[str, Any], List[str]]:
    """
    E-02: Saved filter references a deleted segment →
    fall back to 'All' for that dimension and attach a warning.
    """
    warnings: List[str] = []
    resolved = dict(filters)

    segment_val = resolved.get("segment")
    if segment_val and segment_val != "all" and segment_val not in AVAILABLE_SEGMENTS:
        warnings.append(
            f"Filter segment '{segment_val}' no longer exists — reset to 'all'."
        )
        resolved["segment"] = "all"

    return resolved, warnings


def _raw_to_response(
    raw: Dict[str, Any],
    requesting_user: Any,
    apply_rbac: bool = True,
) -> SavedViewResponse:
    """Converts raw KV blob into a SavedViewResponse, resolving widget/segment issues."""
    widgets_raw = raw.get("widgets", [])
    filters_raw = raw.get("filters", {})

    if apply_rbac:
        resolved_widgets, widget_warnings = _resolve_widgets_for_user(widgets_raw, requesting_user)
    else:
        resolved_widgets, widget_warnings = widgets_raw, []

    resolved_filters, filter_warnings = _resolve_filters_for_segments(filters_raw)
    all_warnings = widget_warnings + filter_warnings

    return SavedViewResponse(
        id=raw["id"],
        user_id=raw["user_id"],
        name=raw["name"],
        widgets=resolved_widgets,
        filters=resolved_filters,
        is_shared=raw.get("is_shared", False),
        warnings=all_warnings,
        created_at=datetime.fromisoformat(raw["created_at"])
        if isinstance(raw["created_at"], str)
        else raw["created_at"],
        updated_at=datetime.fromisoformat(raw["updated_at"])
        if isinstance(raw["updated_at"], str)
        else raw["updated_at"],
    )


async def _find_view_by_name_for_user(
    user_id: str, name: str
) -> Optional[Dict[str, Any]]:
    all_views = await kv_store.store.list_values(DASHBOARD_VIEW_NS)
    for v in all_views:
        if v.get("_deleted"):
            continue
        if v.get("user_id") == user_id and v.get("name") == name:
            return v
    return None


async def save_view(
    user_id: str,
    user_role: str,
    request: SavedViewCreateRequest,
) -> SavedViewResponse:
    """
    Save a named dashboard view.
    E-04 Naming collision: raises if name already exists and overwrite=False.
    """
    existing = await _find_view_by_name_for_user(user_id, request.name)

    if existing and not request.overwrite:
        raise AppError(
            f"A view named '{request.name}' already exists. "
            "Set overwrite=true to replace it, or choose a different name.",
            409,
        )

    now = _now()
    widgets_data = [w.model_dump() for w in request.widgets]

    # If overwriting, update; otherwise create new
    if existing:
        existing.update({
            "name": request.name,
            "widgets": widgets_data,
            "filters": request.filters,
            "is_shared": request.is_shared,
            "updated_at": now.isoformat(),
        })
        await kv_store.store.update(DASHBOARD_VIEW_NS, existing["id"], existing)
        raw = existing
    else:
        view_id = _new_id()
        raw = {
            "id": view_id,
            "user_id": user_id,
            "name": request.name,
            "widgets": widgets_data,
            "filters": request.filters,
            "is_shared": request.is_shared,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }
        await kv_store.store.create(DASHBOARD_VIEW_NS, view_id, raw)

    # The creator gets full visibility (no role filtering on save)
    user_obj = {"role": user_role}
    return _raw_to_response(raw, requesting_user=user_obj, apply_rbac=True)


async def get_view(
    view_id: str,
    requesting_user_id: str,
    requesting_user_role: str,
) -> SavedViewResponse:
    """
    Retrieve a saved view by ID.
    E-03: Role-filtered widget resolution applied when viewing a shared view.
    """
    raw = await kv_store.store.get(DASHBOARD_VIEW_NS, view_id)
    if not raw or raw.get("_deleted"):
        raise AppError(f"View '{view_id}' not found.", 404)

    # Access control: own views or shared views only
    is_owner = raw["user_id"] == requesting_user_id
    if not is_owner and not raw.get("is_shared", False):
        raise AppError("Access denied: this view is private.", 403)

    user_obj = {"role": requesting_user_role}
    return _raw_to_response(raw, requesting_user=user_obj, apply_rbac=True)


async def list_views(
    user_id: str,
    requesting_user_role: str,
) -> SavedViewListResponse:
    """
    List all views visible to the requesting admin:
    - Their own views (private + shared)
    - Views shared by others
    """
    all_views = await kv_store.store.list_values(DASHBOARD_VIEW_NS)
    user_obj = {"role": requesting_user_role}

    responses: List[SavedViewResponse] = []
    for raw in all_views:
        if raw.get("_deleted"):
            continue
            
        is_owner = raw.get("user_id") == user_id
        if not is_owner and not raw.get("is_shared", False):
            continue
        responses.append(_raw_to_response(raw, requesting_user=user_obj, apply_rbac=True))

    return SavedViewListResponse(views=responses)


async def delete_view(view_id: str, requesting_user_id: str) -> bool:
    """Delete a saved view. Only the owner can delete their own views."""
    raw = await kv_store.store.get(DASHBOARD_VIEW_NS, view_id)
    if not raw or raw.get("_deleted"):
        raise AppError(f"View '{view_id}' not found.", 404)
    if raw["user_id"] != requesting_user_id:
        raise AppError("Access denied: only the view owner can delete it.", 403)
    # Mark as deleted by overwriting with a tombstone (kv_store has no delete)
    raw["_deleted"] = True
    raw["updated_at"] = _now().isoformat()
    await kv_store.store.update(DASHBOARD_VIEW_NS, view_id, raw)
    return True


# ── HTTP controllers (auth-gated, wired to router) ─────────────────────────────

async def http_list_views(admin_id: str = Depends(require_admin)) -> SavedViewListResponse:
    """GET /analytics/views — list all views visible to this admin."""
    from lib.prisma_client import db
    user = await db.user.find_unique(where={"id": admin_id})
    role = getattr(user, "role", "ADMIN")
    if hasattr(role, "value"):
        role = role.value
    return await list_views(user_id=admin_id, requesting_user_role=role)


async def http_create_view(
    payload: SavedViewCreateRequest,
    admin_id: str = Depends(require_admin),
) -> SavedViewResponse:
    """POST /analytics/views — create or overwrite a named saved view."""
    from lib.prisma_client import db
    user = await db.user.find_unique(where={"id": admin_id})
    role = getattr(user, "role", "ADMIN")
    if hasattr(role, "value"):
        role = role.value
    return await save_view(user_id=admin_id, user_role=role, request=payload)


async def http_get_view(
    view_id: str,
    admin_id: str = Depends(require_admin),
) -> SavedViewResponse:
    """GET /analytics/views/{view_id} — retrieve a single saved view (RBAC-filtered)."""
    from lib.prisma_client import db
    user = await db.user.find_unique(where={"id": admin_id})
    role = getattr(user, "role", "ADMIN")
    if hasattr(role, "value"):
        role = role.value
    return await get_view(
        view_id=view_id,
        requesting_user_id=admin_id,
        requesting_user_role=role,
    )


async def http_delete_view(
    view_id: str,
    admin_id: str = Depends(require_admin),
) -> dict:
    """DELETE /analytics/views/{view_id} — owner-only soft-delete."""
    await delete_view(view_id=view_id, requesting_user_id=admin_id)
    return {"deleted": True, "view_id": view_id}
