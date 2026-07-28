import os
import uuid
from io import BytesIO
from typing import Optional

import bcrypt
from fastapi import Depends, HTTPException, Response, File, UploadFile
from fastapi.responses import JSONResponse
from PIL import Image, ImageOps, UnidentifiedImageError
from PIL.Image import DecompressionBombError
from starlette.concurrency import run_in_threadpool

from lib.prisma_client import db
from middlewares.auth_middleware import require_admin, require_auth, require_super_admin
from prisma.enums import Role
from schemas.user_schemas import (
    DeleteAccountSchema,
    RequestEmailChangeSchema,
    AccentPreferenceSchema,
    UpdateProfileSchema,
    UpdateAccentPreferenceSchema,
    UpdateRoleSchema,
    VerifyEmailChangeSchema,
)
from services import otp_service
from services.accent_calibration_service import get_user_accent_preference, update_user_accent_preference
from utils.email_utils import send_email_change_otp
from utils.jwt_utils import get_access_cookie_options, get_refresh_cookie_options

AVATAR_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads", "avatars")
AVATAR_MAX_BYTES = 5 * 1024 * 1024  # 5MB
AVATAR_ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
AVATAR_SIZE = 512
AVATAR_QUALITY = 85
AVATAR_MAX_PIXELS = 40_000_000  # 40Mpx guards decompression-bomb style images before resize work

def _serialize(user) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "avatarUrl": user.avatarUrl,
        "role": user.role,
        "createdAt": user.createdAt.isoformat(),
    }


# ── Self-service profile ─────────────────────────────────────────────────────
async def get_profile(user_id: str = Depends(require_auth)):
    user = await db.user.find_unique(where={"id": user_id})
    if not user:
        return JSONResponse(status_code=404, content={"error": "User not found"})
    return {"user": _serialize(user)}

async def update_profile(payload: UpdateProfileSchema, user_id: str = Depends(require_auth)):
    user = await db.user.update(where={"id": user_id}, data={"name": payload.name})
    return {"user": _serialize(user)}


# ── Email change (OTP-gated) ─────────────────────────────────────────────────
async def request_email_change(
    payload: RequestEmailChangeSchema, user_id: str = Depends(require_auth)
):
    user = await db.user.find_unique(where={"id": user_id})
    if not user:
        return JSONResponse(status_code=404, content={"error": "User not found"})
    if payload.email == user.email:
        return JSONResponse(
            status_code=400, content={"error": "That's already your email address"}
        )

    existing = await db.user.find_unique(where={"email": payload.email})
    if existing:
        return JSONResponse(status_code=409, content={"error": "Email already registered"})

    code = await otp_service.create_pending_email_change(user_id, payload.email)
    await send_email_change_otp(payload.email, code)
    return {"message": "A verification code has been sent to your new email address."}


async def verify_email_change(
    payload: VerifyEmailChangeSchema, user_id: str = Depends(require_auth)
):
    new_email = await otp_service.verify_pending_email_change(user_id, payload.code)
    if not new_email:
        return JSONResponse(
            status_code=400, content={"error": "Invalid or expired verification code"}
        )

    # Re-check: the address may have been claimed elsewhere while this code was pending
    existing = await db.user.find_unique(where={"email": new_email})
    if existing and existing.id != user_id:
        return JSONResponse(status_code=409, content={"error": "Email already registered"})

    user = await db.user.update(where={"id": user_id}, data={"email": new_email})
    await otp_service.clear_pending_email_change(user_id)
    return {"user": _serialize(user)}

async def get_accent_preference(user_id: str = Depends(require_auth)):
    pref, sub_dialect, notice = await get_user_accent_preference(user_id)
    return AccentPreferenceSchema(
        accent_model_preference=pref,
        sub_dialect_preference=sub_dialect,
        notice=notice,
    )

async def set_accent_preference(payload: UpdateAccentPreferenceSchema, user_id: str = Depends(require_auth)):
    pref, sub_dialect, notice = await update_user_accent_preference(
        user_id, payload.accent_model_preference, payload.sub_dialect_preference
    )
    return AccentPreferenceSchema(
        accent_model_preference=pref,
        sub_dialect_preference=sub_dialect,
        notice=notice,
    )



def _process_avatar(contents: bytes) -> bytes:
    """
    verify() alone is not enough: it only checks the container isn't corrupt, and
    it leaves the Image object unusable for anything else afterwards — reusing it
    to crop/resize raises. So we verify a throwaway handle, then re-open a second
    handle from the same bytes to actually decode and process pixels.
    """
    try:
        with Image.open(BytesIO(contents)) as img:
            img.verify()

        with Image.open(BytesIO(contents)) as source:
            if source.format not in AVATAR_ALLOWED_FORMATS:
                raise HTTPException(status_code=400, detail="Avatar must be JPEG, PNG, or WEBP")
            elif source.width * source.height > AVATAR_MAX_PIXELS:
                raise HTTPException(status_code=400, detail="Image resolution too large")
            source.load()
    
            img = ImageOps.exif_transpose(source)  # respect camera/phone rotation before cropping

            # Center-crop to square, then downscale — avoids stretching non-square uploads
            w, h = img.size
            side = min(w, h)
            left, top = (w - side) // 2, (h - side) // 2
            img = img.crop((left, top, left + side, top + side))
            img = img.resize((AVATAR_SIZE, AVATAR_SIZE), Image.Resampling.LANCZOS)

            # WEBP so alpha (logos/transparent PNGs) survives without a JPEG flatten-to-white
            if img.mode != "RGBA":
                img = img.convert("RGBA")

            out = BytesIO()
            img.save(out, format="WEBP", quality=AVATAR_QUALITY, method=6)
            return out.getvalue()
    except (UnidentifiedImageError, DecompressionBombError, OSError, SyntaxError, ValueError):
        raise HTTPException(status_code=400, detail="File is not a valid image")


async def upload_avatar(file: UploadFile = File(..., alias="avatar"), user_id: str = Depends(require_auth)):
    # if (file.content_type or "") not in AVATAR_CONTENT_TYPES:
    #     raise HTTPException(status_code=400, detail="Avatar must be JPEG, PNG, or WEBP")

    contents = await file.read()
    if not contents or len(contents) > AVATAR_MAX_BYTES:
        raise HTTPException(status_code=400, detail="Avatar must be under 5MB")

    processed = await run_in_threadpool(_process_avatar, contents)

    os.makedirs(AVATAR_DIR, exist_ok=True)
    filename = f"{user_id}-{uuid.uuid4().hex[:8]}.webp"
    filepath = os.path.join(AVATAR_DIR, filename)

    # Clear old avatar file (any extension) before writing the new one
    for existing in os.listdir(AVATAR_DIR):
        if existing.startswith(f"{user_id}-"):
            try:
                os.remove(os.path.join(AVATAR_DIR, existing))
            except FileNotFoundError:
                pass

    with open(filepath, "wb") as f:
        f.write(processed)

    # avatar_url = f"{AVATAR_URL_PREFIX}/{filename}"
    user = await db.user.update(where={"id": user_id}, data={"avatarUrl": filename})
    return {"user": _serialize(user)}


async def delete_account(
    payload: DeleteAccountSchema, response: Response, user_id: str = Depends(require_auth)
):
    user = await db.user.find_unique(where={"id": user_id})
    if not user:
        return JSONResponse(status_code=404, content={"error": "User not found"})
    elif user.role in (Role.ADMIN, Role.SUPER_ADMIN):
        return JSONResponse(status_code=403, content={"error": "Cannot delete admin account"})
    
    valid = await run_in_threadpool(
        bcrypt.checkpw, payload.password.encode(), user.password.encode()
    )
    if not valid:
        return JSONResponse(status_code=401, content={"error": "Incorrect password"})

    # RefreshToken/PasswordResetToken rows cascade-delete via the FK in schema.prisma
    await db.user.delete(where={"id": user_id})

    access_opts = get_access_cookie_options()
    refresh_opts = get_refresh_cookie_options()
    response.delete_cookie("access_token", path=access_opts["path"], samesite=access_opts["samesite"])
    response.delete_cookie("refresh_token", path=refresh_opts["path"], samesite=refresh_opts["samesite"])
    response.status_code = 204
    return response


# ── Super Admin: user directory + role management ──────────────────────────────
# PAD-US-01-style scoping, minus the full analytics dashboard (out of scope for this
# pass) — only the account-privilege surface the user explicitly asked for: view
# every user/admin, promote/revoke, and a safe single-Super-Admin ownership transfer.
USERS_PAGE_SIZE_DEFAULT = 10
USERS_PAGE_SIZE_MAX = 50


async def list_users(
    page: int = 1,
    page_size: int = USERS_PAGE_SIZE_DEFAULT,
    role: Optional[str] = None,
    search: Optional[str] = None,
    _super_admin_id: str = Depends(require_super_admin),
):
    page = max(1, page)
    page_size = max(1, min(USERS_PAGE_SIZE_MAX, page_size))

    where: dict = {}
    if role:
        if role not in ("USER", "ADMIN", "SUPER_ADMIN"):
            return JSONResponse(status_code=400, content={"error": "Invalid role filter"})
        where["role"] = role
    if search:
        where["OR"] = [
            {"name": {"contains": search, "mode": "insensitive"}},
            {"email": {"contains": search, "mode": "insensitive"}},
        ]

    total = await db.user.count(where=where)
    users = await db.user.find_many(
        where=where, order={"createdAt": "desc"}, skip=(page - 1) * page_size, take=page_size,
    )
    return {
        "users": [_serialize(u) for u in users],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


async def update_user_role(
    target_user_id: str, payload: UpdateRoleSchema, _super_admin_id: str = Depends(require_super_admin)
):
    """Promote USER<->ADMIN only. SUPER_ADMIN is never a valid target role here —
    ownership only moves via transfer_super_admin's atomic swap — and a SUPER_ADMIN
    can't be revoked through this generic endpoint either (E-05: would zero out the
    role with no successor already assigned; use transfer instead, which always
    leaves exactly one Super Admin standing)."""
    user = await db.user.find_unique(where={"id": target_user_id})
    if not user:
        return JSONResponse(status_code=404, content={"error": "User not found"})
    if user.role == Role.SUPER_ADMIN:
        return JSONResponse(
            status_code=409,
            content={"error": "Use the transfer action to move Super Admin ownership, not a direct role change."},
        )

    updated = await db.user.update(
        where={"id": target_user_id}, data={"role": Role(payload.role)}
    )
    return {"user": _serialize(updated)}


async def transfer_super_admin(target_user_id: str, super_admin_id: str = Depends(require_super_admin)):
    """Atomically hands Super Admin ownership to another account: the acting Super
    Admin is demoted to ADMIN and the target is promoted to SUPER_ADMIN in one
    transaction, so the invariant "exactly one Super Admin at all times" (E-05)
    never has a gap — no intermediate state with zero or two."""
    if target_user_id == super_admin_id:
        return JSONResponse(status_code=400, content={"error": "You already are the Super Admin"})

    target = await db.user.find_unique(where={"id": target_user_id})
    if not target:
        return JSONResponse(status_code=404, content={"error": "User not found"})
    if target.role == Role.SUPER_ADMIN:
        return JSONResponse(status_code=409, content={"error": "That account already is the Super Admin"})

    async with db.tx() as transaction:
        await transaction.user.update(where={"id": super_admin_id}, data={"role": Role.ADMIN})
        new_super_admin = await transaction.user.update(
            where={"id": target_user_id}, data={"role": Role.SUPER_ADMIN}
        )

    return {"user": _serialize(new_super_admin)}
