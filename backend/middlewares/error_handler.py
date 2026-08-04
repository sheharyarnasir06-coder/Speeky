import traceback
from typing import cast
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from utils.app_error import AppError


class AuthError(Exception):
    """401 shape used by require_auth — original requireAuth returns res.json({error})
    directly, bypassing errorHandler.js entirely. Kept as its own exception/shape
    for that reason (see middlewares/auth_middleware.py)."""

    def __init__(self, message: str, status_code: int = 401):
        self.message = message
        self.status_code = status_code
        super().__init__(message)

async def app_error_handler(
    _request: Request,
    exc: Exception,
) -> JSONResponse:
    exc = cast(AppError, exc)
    # Errors raised as AppError (currently just the 404 catch-all in main.py).

    print({"message": exc.message, "stack": traceback.format_exc()})
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "status": exc.status,
            "message": exc.message,
        },
    )

async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    print({"message": str(exc), "stack": traceback.format_exc()})
    response = JSONResponse(
        status_code=500,
        content={"status": "error", "message": "Something went wrong!"},
    )
    # Starlette runs the Exception handler in ServerErrorMiddleware, which sits
    # OUTSIDE CORSMiddleware — so a 500 reached the browser with no CORS headers
    # and was reported as "blocked by CORS policy" instead of as a server error.
    # That actively misdirects debugging: the real fault was a missing DB column,
    # but every dashboard page just showed a CORS message. Mirror the CORS
    # response headers here so a 500 reads as a 500.
    origin = request.headers.get("origin")
    if origin:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Vary"] = "Origin"
    return response


async def validation_error_handler(
    _request: Request,
    exc: Exception,
) -> JSONResponse:
    exc = cast(RequestValidationError, exc)

    field_errors: dict[str, list[str]] = {}

    for err in exc.errors():
        field = str(err["loc"][-1]) if err["loc"] else "_"
        field_errors.setdefault(field, []).append(err["msg"])

    return JSONResponse(
        status_code=400,
        content={
            "error": {
                "formErrors": [],
                "fieldErrors": field_errors,
            }
        },
    )

async def auth_error_handler(
    _request: Request,
    exc: Exception,
) -> JSONResponse:
    exc = cast(AuthError, exc)

    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.message},
    )


# ── Malformed request paths ──────────────────────────────────────────────────
# A NUL byte in a path parameter reaches Postgres as an unrepresentable string
# and raises `22021 invalid byte sequence`, which surfaced as a generic 500 on
# EVERY endpoint taking an id (`/api/coaching/%00`, `/api/scenarios/sessions/%00`,
# and so on). A NUL is never a legitimate URL path character, so it is rejected
# before any database work happens.
#
# Registered as middleware rather than a per-route guard: the problem is
# transport-level and applies to every current and future id route.
_NUL = chr(0)


async def reject_null_bytes(request: Request, call_next):
    if _NUL in request.url.path or "%00" in request.url.path:
        return JSONResponse(
            status_code=400,
            content={"status": "fail", "message": "Malformed request path."},
        )
    return await call_next(request)
