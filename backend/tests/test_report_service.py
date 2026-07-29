"""Scheduled Report Generation & Distribution (GAP-04 / US-202).

No live DB — services/report_service.db is monkeypatched with lightweight
in-memory stand-ins that mimic the handful of Prisma calls run_report()
makes, same spirit as this repo's _memory_store conftest fixture swapping
the KV store for tests. Generation/delivery are stubbed via monkeypatch so
each test isolates exactly the retry/bounce/confirmation behavior it targets."""

import types
from datetime import datetime, timezone

from prisma import Json

from services import report_service as rs


def _unwrap(data: dict) -> dict:
    """Prisma's Json() wrapper only makes sense against a real client — the
    fakes below store plain values instead."""
    return {k: (v.data if isinstance(v, Json) else v) for k, v in data.items()}


class FakeTemplateTable:
    def __init__(self, template):
        self.template = template

    async def find_unique(self, where):
        return self.template if where.get("id") == self.template.id else None

    async def update(self, where, data):
        for k, v in _unwrap(data).items():
            setattr(self.template, k, v)
        return self.template


class FakeRunTable:
    def __init__(self):
        self.runs = {}
        self._counter = 0

    async def create(self, data):
        self._counter += 1
        defaults = dict(
            attempt=0, fileUrl=None, format=None, deliveryLog=[], errorMessage=None,
            startedAt=datetime.now(timezone.utc), completedAt=None,
        )
        run = types.SimpleNamespace(id=f"run_{self._counter}", **{**defaults, **_unwrap(data)})
        self.runs[run.id] = run
        return run

    async def update(self, where, data):
        run = self.runs[where["id"]]
        for k, v in _unwrap(data).items():
            setattr(run, k, v)
        return run


class FakeUserTable:
    def __init__(self, users_by_id):
        self.users_by_id = users_by_id

    async def find_unique(self, where):
        return self.users_by_id.get(where.get("id"))


class FakeDB:
    def __init__(self, template, users_by_id):
        self.reporttemplate = FakeTemplateTable(template)
        self.reportrun = FakeRunTable()
        self.user = FakeUserTable(users_by_id)


def _make_template(**overrides):
    base = dict(
        id="tmpl_1", name="Weekly Digest", ownerAdminId="admin_1", metrics=["daily_signups"],
        dateRangeType="last_7_days", recurrence="weekly", recurrenceDay=0, recurrenceHour=9,
        recurrenceMinute=0, timezone="UTC", recipients=[], format="pdf", isActive=True,
        nextRunAt=None, currentlyGenerating=False, pendingScheduleUpdate=None,
    )
    base.update(overrides)
    return types.SimpleNamespace(**base)


# ── TC-02: generation fails -> retries twice, then notifies the owner ──────
async def test_generation_failure_retries_twice_then_notifies_owner(monkeypatch):
    template = _make_template(recipients=[{"type": "external", "value": "stakeholder@example.com"}])
    fake_db = FakeDB(template, {"admin_1": types.SimpleNamespace(email="owner@speeky.ai")})
    monkeypatch.setattr(rs, "db", fake_db)

    attempts = []

    async def always_fails(_template):
        attempts.append(1)
        raise RuntimeError("data pipeline error")

    monkeypatch.setattr(rs, "_generate_file", always_fails)

    failure_emails = []

    async def fake_failure_email(to, _name, _url):
        failure_emails.append(to)

    monkeypatch.setattr(rs.email_utils, "send_report_generation_failed_email", fake_failure_email)

    pushes = []

    async def fake_push(user_id, message):
        pushes.append((user_id, message))
        return {"sent": True}

    monkeypatch.setattr(rs.notification_service, "send_admin_push", fake_push)

    run = await rs.run_report("tmpl_1", triggered_by="schedule")

    assert len(attempts) == rs.MAX_GENERATION_ATTEMPTS  # initial try + 2 retries, not silently skipped
    assert run["status"] == "failed_permanently"
    assert failure_emails == ["owner@speeky.ai"]
    assert pushes and pushes[0][0] == "admin_1"
    assert template.currentlyGenerating is False  # flag cleared even after failure


# ── TC-03: one recipient bounces, others still receive the report ──────────
async def test_one_recipient_bounce_does_not_block_others(monkeypatch):
    template = _make_template(recipients=[
        {"type": "external", "value": "good@example.com"},
        {"type": "external", "value": "bad@example.com"},
    ])
    fake_db = FakeDB(template, {"admin_1": types.SimpleNamespace(email="owner@speeky.ai")})
    monkeypatch.setattr(rs, "db", fake_db)

    async def fake_generate(_template):
        return "report.pdf", b"%PDF-fake", "pdf"

    monkeypatch.setattr(rs, "_generate_file", fake_generate)

    sent_to = []

    async def fake_send_report_email(to, _name, _filename, _content, _fmt):
        if to == "bad@example.com":
            raise RuntimeError("mailbox does not exist")
        sent_to.append(to)

    monkeypatch.setattr(rs.email_utils, "send_report_email", fake_send_report_email)

    pushes = []

    async def fake_push(user_id, message):
        pushes.append((user_id, message))
        return {"sent": True}

    monkeypatch.setattr(rs.notification_service, "send_admin_push", fake_push)

    run = await rs.run_report("tmpl_1", triggered_by="manual")

    assert run["status"] == "success"
    assert sent_to == ["good@example.com"]
    statuses = {d["recipient"]: d["status"] for d in run["delivery_log"]}
    assert statuses["good@example.com"] == "sent"
    assert statuses["bad@example.com"] == "bounced"
    assert pushes  # E-02: owner notified about the partial failure


# ── TC-04: Revenue + external recipient requires confirmation ──────────────
def test_external_revenue_report_requires_confirmation():
    recipients = [{"type": "external", "value": "cfo@partner.com"}]
    assert rs.requires_external_confirmation(["revenue"], recipients) is True


def test_internal_only_revenue_report_does_not_require_confirmation():
    recipients = [{"type": "internal", "value": "admin_1"}]
    assert rs.requires_external_confirmation(["revenue"], recipients) is False


def test_external_non_revenue_report_does_not_require_confirmation():
    recipients = [{"type": "external", "value": "stakeholder@example.com"}]
    assert rs.requires_external_confirmation(["daily_signups"], recipients) is False
