"""Mint the QA session used by the frontend Playwright UI audit.

The dashboard routes are auth-gated, so the audit needs a real session or every
page renders an empty shell and the assertions become meaningless. This creates
(or reuses) a dedicated QA user and writes a signed token to
``frontend/e2e/.auth.json``, which the spec injects as a cookie.

Run from ``backend/``::

    PYTHONPATH=. ./.venv/Scripts/python.exe scripts/make_qa_auth.py

The token is deliberately long-lived (30 days by default) so the suite is not
re-authenticated every 30 minutes, which is the app's real session TTL. That
makes the file a genuine credential -- it is gitignored, and never reuse this
user for anything but the audit.

Tear the QA user back down with::

    PYTHONPATH=. ./.venv/Scripts/python.exe scripts/make_qa_auth.py --cleanup
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

# Allow running as `python scripts/make_qa_auth.py` from backend/ without PYTHONPATH.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

QA_EMAIL = "qa.ui.speeky@gmail.com"
QA_NAME = "QA UI"
QA_PASSWORD = b"QaUi!2026x"
TOKEN_TTL_MINUTES = 43_200  # 30 days
AUTH_FILE = Path(__file__).resolve().parents[2] / "frontend" / "e2e" / ".auth.json"


async def _provision() -> None:
    # sign_access_token reads the TTL from the environment on every call, so
    # overriding it here affects only this token -- not the app's session policy.
    os.environ["ACCESS_TOKEN_TTL"] = str(TOKEN_TTL_MINUTES)

    import bcrypt

    from lib.prisma_client import db
    from utils.jwt_utils import sign_access_token

    await db.connect()
    try:
        user = await db.user.find_unique(where={"email": QA_EMAIL})
        if user is None:
            user = await db.user.create(
                data={
                    "email": QA_EMAIL,
                    "name": QA_NAME,
                    "password": bcrypt.hashpw(QA_PASSWORD, bcrypt.gensalt()).decode(),
                }
            )
            print(f"created QA user {user.id}")
        else:
            print(f"reusing QA user {user.id}")

        AUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
        AUTH_FILE.write_text(
            json.dumps({"token": sign_access_token({"sub": user.id})}), encoding="utf-8"
        )
        print(f"wrote {AUTH_FILE} (valid ~{TOKEN_TTL_MINUTES // 1440} days)")
    finally:
        await db.disconnect()


async def _cleanup() -> None:
    from lib.prisma_client import db

    await db.connect()
    try:
        user = await db.user.find_unique(where={"email": QA_EMAIL})
        if user is None:
            print("no QA user to remove")
        else:
            # KV rows are keyed both ways depending on the feature that wrote them.
            await db.kventry.delete_many(where={"userId": user.id})
            await db.kventry.delete_many(where={"key": user.id})
            await db.user.delete(where={"id": user.id})
            print(f"removed QA user {user.id}")
    finally:
        await db.disconnect()

    AUTH_FILE.unlink(missing_ok=True)
    print(f"removed {AUTH_FILE}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="delete the QA user and .auth.json instead of creating them",
    )
    args = parser.parse_args()
    asyncio.run(_cleanup() if args.cleanup else _provision())


if __name__ == "__main__":
    main()
