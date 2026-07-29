"""
Channel delivery + fallback chain for anomaly alerts (GAP-03 / US-201 E-03).

Slack delivery is real (httpx POST to a configured incoming-webhook URL — httpx
is already a dependency used elsewhere in this codebase). There is no webhook
configured out of the box, so until one is wired up in MetricThreshold rows,
every "slack" channel send exercises the failure -> email-fallback path below,
which is exactly what E-03 asks for. Push reuses the existing simulated-log
mechanism in services/notification_service.py (no real push provider exists
anywhere in this codebase yet).
"""

import logging
from typing import Awaitable, Callable, List, Optional

import httpx

from lib.prisma_client import db

logger = logging.getLogger(__name__)

SLACK_TIMEOUT_SECONDS = 5.0


async def _log_delivery(alert_id: Optional[str], digest_group_id: Optional[str], channel: str, status: str, error: Optional[str]) -> None:
    try:
        await db.alertdeliverylog.create(
            data={
                "alertId": alert_id,
                "digestGroupId": digest_group_id,
                "channel": channel,
                "status": status,
                "error": error,
            }
        )
    except Exception as exc:
        logger.warning(f"Failed to write AlertDeliveryLog ({channel}/{status}): {exc}")


async def _post_slack(webhook_url: str, text: str) -> None:
    async with httpx.AsyncClient(timeout=SLACK_TIMEOUT_SECONDS) as client:
        response = await client.post(webhook_url, json={"text": text})
        response.raise_for_status()


async def deliver(
    *,
    recipient_admin_id: str,
    channels: List[str],
    slack_webhook_url: Optional[str],
    slack_text: str,
    send_email: Callable[[], Awaitable[None]],
    push_message: Optional[str] = None,
    alert_id: Optional[str] = None,
    digest_group_id: Optional[str] = None,
) -> None:
    """Tries every configured channel; Slack failures fall back to email
    automatically (E-03), and every attempt — success or failure — is logged
    to AlertDeliveryLog for the Super Admin's channel-health review."""
    slack_delivered = False

    if "slack" in channels:
        if not slack_webhook_url:
            await _log_delivery(alert_id, digest_group_id, "slack", "failed", "No Slack webhook configured")
        else:
            try:
                await _post_slack(slack_webhook_url, slack_text)
                await _log_delivery(alert_id, digest_group_id, "slack", "sent", None)
                slack_delivered = True
            except Exception as exc:
                logger.warning(f"Slack delivery failed, falling back to email: {exc}")
                await _log_delivery(alert_id, digest_group_id, "slack", "failed", str(exc))

    # E-03: email is sent whenever it's explicitly configured, OR as the
    # fallback for a Slack channel that was configured but failed.
    slack_needs_fallback = "slack" in channels and not slack_delivered
    if "email" in channels or slack_needs_fallback:
        try:
            await send_email()
            await _log_delivery(alert_id, digest_group_id, "email", "fallback" if slack_needs_fallback and "email" not in channels else "sent", None)
        except Exception as exc:
            logger.error(f"Email delivery failed for alert {alert_id or digest_group_id}: {exc}")
            await _log_delivery(alert_id, digest_group_id, "email", "failed", str(exc))

    if "push" in channels and push_message:
        try:
            from services.notification_service import send_admin_push

            await send_admin_push(recipient_admin_id, push_message)
            await _log_delivery(alert_id, digest_group_id, "push", "sent", None)
        except Exception as exc:
            logger.warning(f"Push delivery failed: {exc}")
            await _log_delivery(alert_id, digest_group_id, "push", "failed", str(exc))
