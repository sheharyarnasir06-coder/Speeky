from datetime import datetime, timezone

from fastapi import Depends, Request, Response

from lib.prisma_client import db
from middlewares.error_handler import AuthError
from utils.jwt_utils import (
    get_access_cookie_options,
    hash_token,
    sign_access_token,
    verify_access_token,
    verify_refresh_token,
)


async def require_auth(request: Request, response: Response) -> str:
    # Fast path: a valid, unexpired access token.
    access = request.cookies.get("access_token")
    if access:
        try:
            return verify_access_token(access)["sub"]
        except Exception:
            pass  # expired/invalid — fall through and try a silent renew

    refresh = request.cookies.get("refresh_token")
    if not refresh:
        raise AuthError("Not authenticated")
    try:
        payload = verify_refresh_token(refresh)
    except Exception:
        raise AuthError("Invalid or expired refresh token")

    stored = await db.refreshtoken.find_unique(where={"tokenHash": hash_token(refresh)})
    if not stored or stored.revoked or stored.expiresAt < datetime.now(timezone.utc):
        raise AuthError("Refresh token revoked or expired")

    user_id = payload["sub"]
    response.set_cookie(
        "access_token", sign_access_token({"sub": user_id}), **get_access_cookie_options()
    )
    return user_id


async def require_admin(user_id: str = Depends(require_auth)) -> str:
    """Admin-OR-Super-Admin dependency — use as `user_id: str = Depends(require_admin)`.
    Gates the shared Admin gateway (content management, custom scenarios): a Super
    Admin can do everything a regular Admin can, so both roles pass here. Checks role
    from DB (not the JWT) so a role downgrade takes effect immediately instead of
    waiting for the access token to expire."""
    user = await db.user.find_unique(where={"id": user_id})
    if not user or user.role not in ("ADMIN", "SUPER_ADMIN"):
        raise AuthError("Admin access required", 403)
    return user_id


async def require_super_admin(user_id: str = Depends(require_auth)) -> str:
    """Super-Admin-only dependency — gates the exclusively-Super-Admin surface
    (user management: viewing all accounts, promoting/revoking, ownership transfer).
    Regular Admins are deliberately excluded here."""
    user = await db.user.find_unique(where={"id": user_id})
    if not user or user.role != "SUPER_ADMIN":
        raise AuthError("Super Admin access required", 403)
    return user_id
