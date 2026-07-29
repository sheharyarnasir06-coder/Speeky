import os
from contextlib import asynccontextmanager
from dotenv import load_dotenv

load_dotenv(override=True)  # must run before any os.environ reads below; override so a
# `--reload` restart picks up .env edits (e.g. GROQ_MODEL) instead of keeping stale values.

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from lib.prisma_client import db
from lib.scheduler import start_scheduler, stop_scheduler
from middlewares.error_handler import (
    AuthError,
    app_error_handler,
    auth_error_handler,
    unhandled_exception_handler,
    validation_error_handler,
)
from routers.accent_progress_routes import router as accent_progress_router
from routers.active_session_routes import router as active_session_router
from routers.alert_routes import router as alert_router
from routers.analytics_routes import router as analytics_router
from routers.auth_routes import router as auth_router
from routers.category_routes import router as category_router
from routers.user_routes import router as user_router
from routers.assessment_routes import router as assessment_router
from routers.coaching_routes import router as coaching_router
from routers.conversation_routes import router as conversation_router
from routers.interview_coach_routes import router as interview_coach_router
from routers.pronunciation_routes import router as pronunciation_router
from routers.pronunciation_coach_routes import router as pronunciation_coach_router
from routers.accent_routes import router as accent_router
from routers.accent_assessment_routes import router as accent_assessment_router
from routers.notification_routes import router as notification_router
from routers.overuse_routes import router as overuse_router
from routers.practice_time_routes import router as practice_time_router
from routers.progress_dashboard_routes import router as progress_dashboard_router
from routers.resume_jd_routes import router as resume_jd_router
from routers.scenario_routes import router as scenario_router
from routers.session_memory_routes import router as session_memory_router
from routers.daily_challenge_routes import router as daily_challenge_router
from routers.vocabulary_progress_routes import router as vocabulary_progress_router
from routers.public_speaking_routes import router as public_speaking_router
from routers.code_switch_routes import router as code_switch_router
from routers.rewrite_routes import router as rewrite_router
from routers.rewrite_vocab_routes import router as rewrite_vocab_router
from routers.script_practice_routes import router as script_practice_router
from routers.report_routes import router as report_router
from utils.app_error import AppError


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await db.connect()
    start_scheduler()
    yield
    stop_scheduler()
    await db.disconnect()

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["100/minute"],  # Global limit
)

app = FastAPI(lifespan=lifespan)
app.state.limiter = limiter


app.add_middleware(SlowAPIMiddleware)
app.add_middleware(
    CORSMiddleware,
    # allow_origins=[os.environ.get("CLIENT_ORIGIN", "http://localhost:3000")],
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST","PATCH", "DELETE", "OPTIONS"],
)

app.add_exception_handler(AppError, app_error_handler)
app.add_exception_handler(AuthError, auth_error_handler)
app.add_exception_handler(
    RateLimitExceeded,
    _rate_limit_exceeded_handler,  # type: ignore[arg-type]
)
app.add_exception_handler(RequestValidationError, validation_error_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)


@app.get("/health")
async def health():
    return HTMLResponse("<h1>Speeky API is running!</h1>")

app.include_router(auth_router, prefix="/api/auth")
app.include_router(user_router, prefix="/api/users")
app.include_router(category_router, prefix="/api/categories")
app.include_router(analytics_router, prefix="/api/analytics")
app.include_router(active_session_router, prefix="/api/active-sessions")
app.include_router(assessment_router, prefix="/api/assessment")
app.include_router(coaching_router, prefix="/api/coaching")
app.include_router(conversation_router, prefix="/api/conversation")
app.include_router(interview_coach_router, prefix="/api/interview-coach")
app.include_router(session_memory_router, prefix="/api/session-memory")
app.include_router(resume_jd_router, prefix="/api/resume-jd-intake")
app.include_router(scenario_router, prefix="/api/scenarios")
app.include_router(progress_dashboard_router, prefix="/api/progress-dashboard")
app.include_router(accent_progress_router, prefix="/api/accent-progress")
app.include_router(pronunciation_coach_router, prefix="/api/pronunciation-coach")
app.include_router(pronunciation_router, prefix="/api/pronunciation-coach")
app.include_router(accent_assessment_router, prefix="/api/accent-assessment")
app.include_router(accent_router, prefix="/api/accent-assessment")
app.include_router(notification_router, prefix="/api/notifications")
app.include_router(overuse_router, prefix="/api/overuse")
app.include_router(vocabulary_progress_router, prefix="/api/vocabulary-progress")
app.include_router(practice_time_router, prefix="/api/practice-time")
app.include_router(public_speaking_router, prefix="/api/public-speaking")
app.include_router(daily_challenge_router, prefix="/api/daily-challenge")
app.include_router(code_switch_router, prefix="/api/code-switch")
app.include_router(rewrite_router, prefix="/api/rewrite")
app.include_router(rewrite_vocab_router, prefix="/api/rewrite-vocab")
app.include_router(script_practice_router, prefix="/api/script-practice")
app.include_router(alert_router, prefix="/api/alerts")
app.include_router(report_router, prefix="/api/reports")

# Local-folder avatar storage, exposed to frontend as static files
_uploads_dir = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(os.path.join(_uploads_dir, "avatars"), exist_ok=True)
app.mount("/uploads", StaticFiles(directory=_uploads_dir), name="uploads")


@app.api_route("/{full_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def not_found(full_path: str, request: Request):
    if request.url.path == "/favicon.ico":
        return Response(status_code=204)
    
    raise AppError(f"Route not found: {request.url.path}", 404)


if __name__ == "__main__":
    import uvicorn

    # ponytail: no uncaughtException/unhandledRejection handlers — uvicorn's worker
    # process model already exits/logs on unhandled errors; Node needed those
    # explicitly, Python's asyncio + uvicorn combo doesn't need the same guard.
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8000)),
        reload=os.environ.get("APP_ENV") != "production",
    )
