"""
Generic Audit Log (GAP-03 / GAP-04). One reusable primitive — threshold changes,
alert acknowledgements/false-positive marks, and report template edits/sends all
call `record_event` here instead of each feature building its own log.
"""

from typing import Any, Dict, List, Optional

from prisma import Json

from lib.prisma_client import db


async def record_event(
    action: str,
    target_type: str,
    target_id: Optional[str] = None,
    actor_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Best-effort: a logging failure must never break the caller's actual operation."""
    try:
        await db.auditlogentry.create(
            data={
                "actorId": actor_id,
                "action": action,
                "targetType": target_type,
                "targetId": target_id,
                "metadata": Json(metadata or {}),
            }
        )
    except Exception as exc:
        import logging

        logging.getLogger(__name__).warning(f"audit_log_service.record_event failed ({action}): {exc}")


async def list_events(target_type: Optional[str] = None, target_id: Optional[str] = None, limit: int = 100) -> List[Dict]:
    where: Dict[str, Any] = {}
    if target_type:
        where["targetType"] = target_type
    if target_id:
        where["targetId"] = target_id
    rows = await db.auditlogentry.find_many(where=where, order={"createdAt": "desc"}, take=min(limit, 500))
    return [
        {
            "id": r.id,
            "actor_id": r.actorId,
            "action": r.action,
            "target_type": r.targetType,
            "target_id": r.targetId,
            "metadata": r.metadata,
            "created_at": r.createdAt.isoformat(),
        }
        for r in rows
    ]
