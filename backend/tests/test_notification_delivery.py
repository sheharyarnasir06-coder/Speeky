"""GAP-03 (US-201) E-03: Slack webhook failure falls back to email, and every
attempt (success or failure) is logged. No live DB — db.alertdeliverylog is
monkeypatched with an in-memory stand-in, same spirit as this repo's
_memory_store conftest fixture swapping the KV store."""

from services import notification_delivery_service as nds


class _FakeAlertDeliveryLogTable:
    def __init__(self):
        self.records = []

    async def create(self, data):
        self.records.append(data)


class _FakeDB:
    def __init__(self):
        self.alertdeliverylog = _FakeAlertDeliveryLogTable()


def _statuses_by_channel(records):
    return {r["channel"]: r["status"] for r in records}


# ── TC-04: Slack webhook unreachable -> falls back to email, failure logged ──
async def test_slack_failure_falls_back_to_email_and_logs_both(monkeypatch):
    fake_db = _FakeDB()
    monkeypatch.setattr(nds, "db", fake_db)

    async def failing_slack(url, text):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(nds, "_post_slack", failing_slack)

    email_calls = []

    async def fake_send_email():
        email_calls.append(True)

    await nds.deliver(
        recipient_admin_id="admin_1",
        channels=["slack", "email"],
        slack_webhook_url="https://hooks.slack.test/broken",
        slack_text="Anomaly detected",
        send_email=fake_send_email,
        alert_id="alert_1",
    )

    assert email_calls == [True]
    statuses = _statuses_by_channel(fake_db.alertdeliverylog.records)
    assert statuses["slack"] == "failed"
    assert statuses["email"] == "sent"


async def test_slack_only_channel_still_falls_back_to_email_on_failure(monkeypatch):
    """Admin only selected 'slack', but a broken webhook must still reach them
    somehow — E-03 says fall back to email, not fail silently."""
    fake_db = _FakeDB()
    monkeypatch.setattr(nds, "db", fake_db)

    async def failing_slack(url, text):
        raise RuntimeError("timeout")

    monkeypatch.setattr(nds, "_post_slack", failing_slack)

    email_calls = []

    async def fake_send_email():
        email_calls.append(True)

    await nds.deliver(
        recipient_admin_id="admin_1",
        channels=["slack"],
        slack_webhook_url="https://hooks.slack.test/broken",
        slack_text="Anomaly detected",
        send_email=fake_send_email,
        alert_id="alert_1",
    )

    assert email_calls == [True]
    statuses = _statuses_by_channel(fake_db.alertdeliverylog.records)
    assert statuses["slack"] == "failed"
    assert statuses["email"] == "fallback"


async def test_missing_webhook_url_logs_failure_and_falls_back(monkeypatch):
    fake_db = _FakeDB()
    monkeypatch.setattr(nds, "db", fake_db)
    email_calls = []

    async def fake_send_email():
        email_calls.append(True)

    await nds.deliver(
        recipient_admin_id="admin_1",
        channels=["slack", "email"],
        slack_webhook_url=None,
        slack_text="Anomaly detected",
        send_email=fake_send_email,
        alert_id="alert_1",
    )

    assert email_calls == [True]
    statuses = _statuses_by_channel(fake_db.alertdeliverylog.records)
    assert statuses["slack"] == "failed"


async def test_successful_slack_delivery_does_not_trigger_email_fallback(monkeypatch):
    fake_db = _FakeDB()
    monkeypatch.setattr(nds, "db", fake_db)

    async def ok_slack(url, text):
        return None

    monkeypatch.setattr(nds, "_post_slack", ok_slack)
    email_calls = []

    async def fake_send_email():
        email_calls.append(True)

    await nds.deliver(
        recipient_admin_id="admin_1",
        channels=["slack"],
        slack_webhook_url="https://hooks.slack.test/ok",
        slack_text="Anomaly detected",
        send_email=fake_send_email,
        alert_id="alert_1",
    )

    assert email_calls == []  # no fallback needed
    statuses = _statuses_by_channel(fake_db.alertdeliverylog.records)
    assert statuses["slack"] == "sent"
    assert "email" not in statuses
