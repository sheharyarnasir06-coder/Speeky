import os
from datetime import datetime, timezone

import bcrypt
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from lib.prisma_client import db
from schemas.auth_schemas import (
    ForgotSchema,
    LoginSchema,
    ResendOtpSchema,
    ResetSchema,
    SignupSchema,
    VerifyOtpSchema,
)
from services import otp_service
from utils.email_utils import send_otp_email, send_password_reset_email
from utils.jwt_utils import (
    get_access_cookie_options,
    get_refresh_cookie_options,
    hash_token,
    refresh_expiry_date,
    reset_expiry_date,
    sign_access_token,
    sign_refresh_token,
    sign_reset_token,
    verify_refresh_token,
    verify_reset_token,
)

# Constant-time dummy hash for login timing-attack prevention.
# Generated a real one with the same cost factor (12) so the security property — constant-time
_DUMMY_HASH = b"$2b$12$Oz3oZryYML3JJdklScxs9.ngNgsByHP1HsIhF8M/JFNtX1rHt2JWO"

BCRYPT_COST = 12


# ── Helpers ───────────────────────────────────────────────────────────────────
def _auth_user(user) -> dict:
    """Shape returned to the client on signup-verify / login / refresh. Includes
    learningGoal so the app has the user's focus area without a second call."""
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "avatarUrl": user.avatarUrl,
        "role": user.role,
        "learningGoal": user.learningGoal,
        "learningGoalSet": user.learningGoalSet,
        "isConsented": user.isConsented,
        "consentVersion": user.consentVersion,
        "consentAcceptedAt": user.consentAcceptedAt.isoformat() if user.consentAcceptedAt else None,
    }


async def _issue_tokens(response: Response, user_id: str) -> None:
    access_token = sign_access_token({"sub": user_id})
    refresh_token = sign_refresh_token({"sub": user_id})

    await db.refreshtoken.create(
        data={
            "tokenHash": hash_token(refresh_token),
            "userId": user_id,
            "expiresAt": refresh_expiry_date(),
        }
    )

    response.set_cookie("access_token", access_token, **get_access_cookie_options())
    response.set_cookie("refresh_token", refresh_token, **get_refresh_cookie_options())


# ── Controllers ───────────────────────────────────────────────────────────────
async def signup(payload: SignupSchema):
    # No user row yet — account is only created once the emailed OTP is verified.
    existing = await db.user.find_unique(where={"email": payload.email})
    if existing:
        return JSONResponse(status_code=409, content={"error": "Email already registered"})

    hashed = await run_in_threadpool(
        lambda: bcrypt.hashpw(payload.password.encode(), bcrypt.gensalt(BCRYPT_COST)).decode()
    )
    code = await otp_service.create_pending_signup(payload.email, payload.name, hashed)
    await send_otp_email(payload.email, code)

    return {"message": "A verification code has been sent to your email."}


async def verify_signup_otp(payload: VerifyOtpSchema, response: Response):
    pending = await otp_service.verify_pending_signup(payload.email, payload.code)
    if not pending:
        return JSONResponse(status_code=400, content={"error": "Invalid or expired verification code"})

    # Re-check: pending signup may have gone stale if the account was created elsewhere meanwhile
    existing = await db.user.find_unique(where={"email": payload.email})
    if existing:
        return JSONResponse(status_code=409, content={"error": "Email already registered"})

    user = await db.user.create(
        data={"email": pending["email"], "password": pending["password"], "name": pending["name"]}
    )
    await otp_service.clear_pending_signup(payload.email)

    await _issue_tokens(response, user.id)
    response.status_code = 201
    return {"user": _auth_user(user)}


async def resend_signup_otp(payload: ResendOtpSchema):
    # Always same response — don't reveal whether a signup is pending for this email
    code = await otp_service.resend_code(payload.email)
    if code:
        await send_otp_email(payload.email, code)
    return {"message": "If a signup is pending for that email, a new verification code has been sent."}


async def login(payload: LoginSchema, response: Response):
    user = await db.user.find_unique(where={"email": payload.email})

    # Constant-time: dummy hash prevents timing attack
    if user:
        valid = await run_in_threadpool(
            bcrypt.checkpw, payload.password.encode(), user.password.encode()
        )
    else:
        await run_in_threadpool(bcrypt.checkpw, payload.password.encode(), _DUMMY_HASH)
        valid = False

    if not user or not valid:
        return JSONResponse(status_code=401, content={"error": "Invalid credentials"})

    await _issue_tokens(response, user.id)
    return {"user": _auth_user(user)}


async def refresh(request: Request, response: Response):
    token = request.cookies.get("refresh_token")
    if not token:
        return JSONResponse(status_code=401, content={"error": "No refresh token"})

    try:
        payload = verify_refresh_token(token)
    except Exception:
        return JSONResponse(status_code=401, content={"error": "Invalid or expired refresh token"})

    token_hash = hash_token(token)
    stored = await db.refreshtoken.find_unique(where={"tokenHash": token_hash})

    if not stored or stored.revoked or stored.expiresAt < datetime.now(timezone.utc):
        # Possible token reuse — revoke all tokens for this user
        if stored:
            await db.refreshtoken.update_many(
                where={"userId": stored.userId}, data={"revoked": True}
            )
        return JSONResponse(status_code=401, content={"error": "Refresh token revoked or expired"})

    user = await db.user.find_unique(where={"id": payload["sub"]})
    if not user:
        return JSONResponse(status_code=401, content={"error": "User not found"})

    # Rotate: revoke old, issue new
    await db.refreshtoken.update(where={"id": stored.id}, data={"revoked": True})

    await _issue_tokens(response, user.id)
    return {"user": _auth_user(user)}


async def logout(request: Request):
    token = request.cookies.get("refresh_token")
    if token:
        token_hash = hash_token(token)
        try:
            stored = await db.refreshtoken.find_unique(where={"tokenHash": token_hash})
            await db.refreshtoken.update_many(where={"tokenHash": token_hash}, data={"revoked": True})
            # Housekeeping: drop this user's dead refresh tokens (revoked — including
            # the one just revoked above — or expired) so the table doesn't grow
            # across repeated login/logout cycles. Other devices' still-active
            # tokens are left intact (this is a single-device logout).
            if stored:
                await db.refreshtoken.delete_many(
                    where={
                        "userId": stored.userId,
                        "OR": [
                            {"revoked": True},
                            {"expiresAt": {"lt": datetime.now(timezone.utc)}},
                        ],
                    }
                )
        except Exception:
            pass

    access_opts = get_access_cookie_options()
    refresh_opts = get_refresh_cookie_options()

    resp = Response(status_code=204)
    resp.delete_cookie("access_token", path=access_opts["path"], samesite=access_opts["samesite"])
    resp.delete_cookie("refresh_token", path=refresh_opts["path"], samesite=refresh_opts["samesite"])
    return resp


async def forgot_password(payload: ForgotSchema):
    # Always respond 200 — never reveal whether email exists (prevents enumeration)
    user = await db.user.find_unique(where={"email": payload.email})
    if not user:
        return {"message": "If that email is registered, a reset link has been sent."}

    # Invalidate any existing reset tokens for this user
    await db.passwordresettoken.update_many(
        where={"userId": user.id, "usedAt": None}, data={"usedAt": datetime.now(timezone.utc)}
    )

    raw_token = sign_reset_token({"sub": user.id})
    await db.passwordresettoken.create(
        data={
            "tokenHash": hash_token(raw_token),
            "userId": user.id,
            "expiresAt": reset_expiry_date(),
        }
    )

    client_origin = os.environ.get("CLIENT_ORIGIN", "http://localhost:5173")
    reset_url = f"{client_origin}/reset-password?token={raw_token}"

    # await send_password_reset_email(user.email, reset_url)
    try:
        await send_password_reset_email(user.email, reset_url)
    except Exception as e:
        print("EMAIL ERROR:", repr(e))
        raise

    return {"message": "If that email is registered, a reset link has been sent."}


async def reset_password(payload: ResetSchema):
    try:
        token_payload = verify_reset_token(payload.token)
    except Exception:
        return JSONResponse(status_code=400, content={"error": "Invalid or expired reset token"})

    token_hash = hash_token(payload.token)
    stored = await db.passwordresettoken.find_unique(where={"tokenHash": token_hash})

    if (
        not stored
        or stored.userId != token_payload["sub"]
        or stored.usedAt
        or stored.expiresAt < datetime.now(timezone.utc)
    ):
        return JSONResponse(
            status_code=400, content={"error": "Reset token is invalid or has already been used"}
        )

    hashed = await run_in_threadpool(
        lambda: bcrypt.hashpw(payload.password.encode(), bcrypt.gensalt(BCRYPT_COST)).decode()
    )

    # Transaction: mark token used + update password + revoke all refresh tokens
    async with db.tx() as transaction:
        await transaction.passwordresettoken.update(
            where={"id": stored.id}, data={"usedAt": datetime.now(timezone.utc)}
        )
        await transaction.user.update(
            where={"id": token_payload["sub"]}, data={"password": hashed}
        )
        await transaction.refreshtoken.update_many(
            where={"userId": token_payload["sub"]}, data={"revoked": True}
        )

    return {"message": "Password reset successful. Please log in."}
