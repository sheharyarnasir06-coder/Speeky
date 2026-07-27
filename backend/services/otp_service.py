"""Signup OTP gate: no user row is created until the emailed code is verified.
Pending signups (hashed password included, never plaintext) live in their own
SignupOtp table, keyed by email so a re-signup/resend just upserts the row."""

import os
import secrets
import string
from datetime import datetime, timedelta, timezone
from typing import Optional

from lib.prisma_client import db
from utils.jwt_utils import hash_token

_CODE_ALPHABET = string.ascii_uppercase + string.digits


def _ttl_minutes() -> int:
    return int(os.environ.get("OTP_TTL_MINUTES", 10))


def _generate_code() -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(6))


async def create_pending_signup(email: str, name: str, hashed_password: str) -> str:
    """Upserts the pending signup and returns the fresh OTP code to email."""
    code = _generate_code()
    fields = {
        "name": name,
        "password": hashed_password,
        "codeHash": hash_token(code),
        "expiresAt": datetime.now(timezone.utc) + timedelta(minutes=_ttl_minutes()),
    }
    await db.signupotp.upsert(
        where={"email": email},
        data={"create": {"email": email, **fields}, "update": fields},
    )
    return code


async def resend_code(email: str) -> Optional[str]:
    """Regenerates a code for an already-pending signup. None if nothing is pending."""
    pending = await db.signupotp.find_unique(where={"email": email})
    if not pending:
        return None
    return await create_pending_signup(email, pending.name, pending.password)


async def verify_pending_signup(email: str, code: str) -> Optional[dict]:
    pending = await db.signupotp.find_unique(where={"email": email})
    if not pending:
        return None
    if pending.expiresAt < datetime.now(timezone.utc) or pending.codeHash != hash_token(code):
        return None
    return {"email": pending.email, "name": pending.name, "password": pending.password}


async def clear_pending_signup(email: str) -> None:
    await db.signupotp.delete(where={"email": email})


"""Email-change OTP gate: mirrors the signup flow above, but keyed by the
logged-in user's id (not the email) since the account already exists — the
code is emailed to the NEW address, and the user's real email column isn't
touched until it's verified."""


async def create_pending_email_change(user_id: str, new_email: str) -> str:
    """Upserts the pending change and returns the fresh OTP code to email."""
    code = _generate_code()
    fields = {
        "newEmail": new_email,
        "codeHash": hash_token(code),
        "expiresAt": datetime.now(timezone.utc) + timedelta(minutes=_ttl_minutes()),
    }
    await db.emailchangeotp.upsert(
        where={"userId": user_id},
        data={"create": {"userId": user_id, **fields}, "update": fields},
    )
    return code


async def verify_pending_email_change(user_id: str, code: str) -> Optional[str]:
    """Returns the verified new email, or None if no/expired/mismatched code."""
    pending = await db.emailchangeotp.find_unique(where={"userId": user_id})
    if not pending:
        return None
    if pending.expiresAt < datetime.now(timezone.utc) or pending.codeHash != hash_token(code):
        return None
    return pending.newEmail


async def clear_pending_email_change(user_id: str) -> None:
    await db.emailchangeotp.delete(where={"userId": user_id})
