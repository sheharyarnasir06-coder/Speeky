"""
Content Management — Category Taxonomy (CM-US-05).

Category is a plain name/icon registry, not a DB foreign key on CustomScenario:
the 9 built-in lib/prompts.SBL_SCENARIOS already hardcode category strings
("Work", "Social", "Travel", "Daily Life") with no row of their own, so
membership/count checks here match by name string against both sources.
"""

import re
from typing import Dict, List
from collections import Counter

from fastapi import Depends
from fastapi.responses import JSONResponse

from lib import prompts
from lib.prisma_client import db
from middlewares.auth_middleware import require_admin, require_auth
from schemas.category_schemas import CategorySchema


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "category"


def _builtin_counts() -> Counter:
    return Counter(meta["category"] for meta in prompts.SBL_SCENARIOS.values())


def _serialize(row, count: int) -> Dict:
    return {
        "id": row.id,
        "name": row.name,
        "slug": row.slug,
        "icon": row.icon,
        "order": row.order,
        "protected": row.protected,
        "scenario_count": count,
    }


async def _counts_by_category() -> Counter:
    counts = _builtin_counts()
    active = await db.customscenario.find_many(where={"status": "ACTIVE"})
    counts.update(row.category for row in active)
    return counts


# ── Learner-facing: only non-empty categories (CM-US-05 E-01) ──────────────────
async def list_categories(_user_id: str = Depends(require_auth)) -> Dict:
    counts = await _counts_by_category()
    rows = await db.category.find_many(order={"order": "asc"})
    visible = [_serialize(r, counts.get(r.name, 0)) for r in rows if counts.get(r.name, 0) > 0]
    return {"categories": visible}


# ── Admin: full list incl. empty categories, so they can be populated ──────────
async def admin_list_categories(_admin_id: str = Depends(require_admin)) -> Dict:
    counts = await _counts_by_category()
    rows = await db.category.find_many(order={"order": "asc"})
    return {"categories": [_serialize(r, counts.get(r.name, 0)) for r in rows]}


async def admin_create_category(payload: CategorySchema, _admin_id: str = Depends(require_admin)):
    existing = await db.category.find_unique(where={"name": payload.name})
    if existing:
        return JSONResponse(status_code=409, content={"error": "A category with this name already exists"})
    row = await db.category.create(
        data={"name": payload.name, "slug": _slugify(payload.name), "icon": payload.icon, "order": payload.order}
    )
    return _serialize(row, 0)


async def admin_update_category(category_id: str, payload: CategorySchema, _admin_id: str = Depends(require_admin)):
    row = await db.category.find_unique(where={"id": category_id})
    if not row:
        return JSONResponse(status_code=404, content={"error": "Category not found"})
    collision = await db.category.find_unique(where={"name": payload.name})
    if collision and collision.id != category_id:
        return JSONResponse(status_code=409, content={"error": "A category with this name already exists"})

    # Protected (built-in) categories keep their name/slug — built-in scenarios'
    # `category` strings are hardcoded in lib/prompts.py and would silently stop
    # matching if renamed here. Icon/order are still editable.
    data = {"icon": payload.icon, "order": payload.order}
    if not row.protected:
        data["name"] = payload.name
        data["slug"] = _slugify(payload.name)

    updated = await db.category.update(where={"id": category_id}, data=data)
    counts = await _counts_by_category()
    return _serialize(updated, counts.get(updated.name, 0))


async def admin_delete_category(category_id: str, _admin_id: str = Depends(require_admin)):
    row = await db.category.find_unique(where={"id": category_id})
    if not row:
        return JSONResponse(status_code=404, content={"error": "Category not found"})
    if row.protected:
        return JSONResponse(status_code=409, content={"error": "This category is built-in and can't be deleted"})

    in_use = await db.customscenario.count(where={"category": row.name})
    if in_use > 0:
        return JSONResponse(
            status_code=409,
            content={"error": f"{in_use} scenario(s) use this category — reassign or delete them first"},
        )

    await db.category.delete(where={"id": category_id})
    return {"deleted": True}


async def valid_category_names() -> List[str]:
    rows = await db.category.find_many()
    return [r.name for r in rows]
