import hashlib
import os
from datetime import datetime, timedelta, timezone

import jwt

# ── env accessors (read at call-time, after dotenv has run) ──────────────────


def _get_access_secret() -> str:
    s = os.environ.get("JWT_ACCESS_SECRET")
    if not s:
        raise RuntimeError("JWT_ACCESS_SECRET not set")
    return s


def _get_refresh_secret() -> str:
    s = os.environ.get("JWT_REFRESH_SECRET")
    if not s:
        raise RuntimeError("JWT_REFRESH_SECRET not set")
    return s


def _get_reset_secret() -> str:
    return os.environ.get("JWT_RESET_SECRET") or _get_access_secret()


def _get_access_ttl_minutes() -> int:
    return int(os.environ.get("ACCESS_TOKEN_TTL", 30))


def _get_refresh_ttl_days() -> int:
    return int(os.environ.get("REFRESH_TOKEN_TTL_DAYS", 7))


def _get_reset_ttl_minutes() -> int:
    return int(os.environ.get("RESET_TOKEN_TTL_MINUTES", 15))


# ── token helpers ────────────────────────────────────────────────────────────


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def sign_access_token(payload: dict) -> str:
    exp = datetime.now(timezone.utc) + timedelta(minutes=_get_access_ttl_minutes())
    return jwt.encode({**payload, "exp": exp}, _get_access_secret(), algorithm="HS256")


def verify_access_token(token: str) -> dict:
    return jwt.decode(token, _get_access_secret(), algorithms=["HS256"])


def sign_refresh_token(payload: dict) -> str:
    exp = datetime.now(timezone.utc) + timedelta(days=_get_refresh_ttl_days())
    return jwt.encode({**payload, "exp": exp}, _get_refresh_secret(), algorithm="HS256")


def verify_refresh_token(token: str) -> dict:
    return jwt.decode(token, _get_refresh_secret(), algorithms=["HS256"])


def sign_reset_token(payload: dict) -> str:
    exp = datetime.now(timezone.utc) + timedelta(minutes=_get_reset_ttl_minutes())
    return jwt.encode({**payload, "exp": exp}, _get_reset_secret(), algorithm="HS256")


def verify_reset_token(token: str) -> dict:
    return jwt.decode(token, _get_reset_secret(), algorithms=["HS256"])


def refresh_expiry_date() -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=_get_refresh_ttl_days())


def reset_expiry_date() -> datetime:
    return datetime.now(timezone.utc) + timedelta(minutes=_get_reset_ttl_minutes())


# ── cookie options (lazy functions — evaluated after dotenv loads) ────────────


def get_access_cookie_options() -> dict:
    is_prod = os.environ.get("APP_ENV") == "production"
    return dict(
        httponly=True,
        secure=is_prod,
        samesite="none" if is_prod else "lax",
        max_age=_get_access_ttl_minutes() * 60,
        path="/",
    )


def get_refresh_cookie_options() -> dict:
    is_prod = os.environ.get("APP_ENV") == "production"
    return dict(
        httponly=True,
        secure=is_prod,
        samesite="none" if is_prod else "lax",
        max_age=_get_refresh_ttl_days() * 24 * 60 * 60,
        # path="/" (not "/api/auth"): require_auth on protected routes needs the
        # refresh cookie to silently mint a new access token. Tradeoff — the
        # refresh token is now sent on every request, so it's httponly (no JS
        # read) and stays revocable server-side to limit the wider exposure.
        path="/api/",
    )
