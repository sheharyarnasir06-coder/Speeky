"""
Background scheduler (GAP-03 / GAP-04). This is new infrastructure for this
repo — no cron/Celery/APScheduler existed anywhere before (see
services/scenario_service.py's "no cron/scheduler exists anywhere in this
repo" comment). APScheduler's AsyncIOScheduler runs in-process inside the
same event loop uvicorn already runs, started/stopped from main.py's
lifespan — no extra worker process or broker needed.

A KvEntry-backed lock (lib/kv_store.py) guards each tick so that if this app
ever runs as multiple processes/replicas, only one of them executes a given
tick — cheap safety net reusing infra that already exists rather than adding
a distributed-lock dependency.
"""

import logging
import os
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from lib import kv_store

logger = logging.getLogger(__name__)

LOCK_NAMESPACE = "scheduler_locks"
LOCK_STALE_SECONDS = 300  # a lock older than this is assumed abandoned (crashed worker)

_scheduler: AsyncIOScheduler | None = None


async def _try_acquire_lock(job_name: str) -> bool:
    now = datetime.now(timezone.utc)
    existing = await kv_store.store.get(LOCK_NAMESPACE, job_name)
    if existing:
        held_at = existing.get("acquired_at")
        if held_at and (now - held_at).total_seconds() < LOCK_STALE_SECONDS:
            return False
        await kv_store.store.update(LOCK_NAMESPACE, job_name, {"job_name": job_name, "acquired_at": now})
        return True
    await kv_store.store.create(LOCK_NAMESPACE, job_name, {"job_name": job_name, "acquired_at": now})
    return True


async def _run_anomaly_monitor() -> None:
    if not await _try_acquire_lock("anomaly_monitor"):
        return
    try:
        from services.anomaly_detection_service import run_detection_cycle

        result = await run_detection_cycle()
        logger.info(f"Anomaly monitor tick: {result}")
    except Exception as exc:
        logger.error(f"Anomaly monitor tick failed: {exc}")


async def _run_report_dispatch() -> None:
    if not await _try_acquire_lock("report_dispatch"):
        return
    try:
        from services.report_service import dispatch_due_reports

        result = await dispatch_due_reports()
        logger.info(f"Report dispatch tick: {result}")
    except Exception as exc:
        logger.error(f"Report dispatch tick failed: {exc}")


def start_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    anomaly_interval = int(os.environ.get("ANOMALY_CHECK_INTERVAL_MINUTES", "15"))
    report_interval = int(os.environ.get("REPORT_DISPATCH_INTERVAL_MINUTES", "5"))

    _scheduler = AsyncIOScheduler(timezone="UTC")
    _scheduler.add_job(_run_anomaly_monitor, "interval", minutes=anomaly_interval, id="anomaly_monitor", max_instances=1)
    _scheduler.add_job(_run_report_dispatch, "interval", minutes=report_interval, id="report_dispatch", max_instances=1)
    _scheduler.start()
    logger.info(f"Scheduler started (anomaly every {anomaly_interval}m, reports every {report_interval}m)")
    return _scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
