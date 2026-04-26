"""FastAPI application entry point.

Run with:
    uvicorn api.main:app --reload --port 8000

v1.0.0 changes
--------------
* Added async ``lifespan`` context manager that:
    1. Initialises the PostgreSQL DB (gracefully skipped if DATABASE_URL
       is not set — file-only mode is preserved).
    2. Loads any previously persisted jobs from the DB so that GET /jobs
       shows history that survived a process restart.  Jobs that were
       mid-flight when the process died are marked "interrupted" so
       operators know they need attention.
    3. Disposes the DB engine cleanly on shutdown.

v1.1.0 changes (GuardrailsLayer)
---------------------------------
* Added slowapi rate limiting (10/min on auth, 60/min on job creation).
* DEV_MODE startup warning logged at WARNING level when SECRET_KEY unset.
* /healthz returns ``dev_mode: true`` when authentication is disabled.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from .rate_limit import limiter
from .routes.auth import router as auth_router
from .routes.jobs import router as jobs_router
from .routes.stream import router as stream_router
from .routes.approvals import router as approvals_router
from .routes.interview import router as interview_router
from .routes.settings import router as settings_router
from .routes.mcp import router as mcp_router

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifespan: DB initialisation + crash recovery
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown hooks."""

    # ── Startup ──────────────────────────────────────────────────────────

    # Security: warn loudly when authentication is disabled
    from .auth import DEV_MODE
    if DEV_MODE:
        logger.warning(
            "[SECURITY] DEV_MODE=True — authentication is DISABLED. "
            "Set SECRET_KEY before deploying to production."
        )

    db_ok = await _init_db()
    if db_ok:
        logger.info("[DB] PostgreSQL connection established — persistence enabled")
        await _recover_jobs_from_db()
    else:
        logger.info("[DB] No DATABASE_URL — running in file-only mode")

    yield   # ← application runs here

    # ── Shutdown ─────────────────────────────────────────────────────────
    await _close_db()


async def _init_db() -> bool:
    """Initialise the DB engine. Returns False on any failure."""
    try:
        from db.connection import init_db
        return await init_db()
    except Exception as exc:   # noqa: BLE001
        logger.warning("[DB] init_db failed: %s", exc)
        return False


async def _close_db() -> None:
    try:
        from db.connection import close_db
        await close_db()
    except Exception:   # noqa: BLE001
        pass


async def _recover_jobs_from_db() -> None:
    """Reload persisted jobs into the in-memory store on startup.

    Jobs that were running when the process died are marked 'interrupted'
    so the operator knows they need to be re-submitted.  Completed,
    failed, and rejected jobs are restored read-only so they still appear
    in GET /jobs without requiring any action.
    """
    try:
        from db.connection import get_session
        from db.repository import load_all_jobs, update_job_status
        from .job_store import get_job, import_job

        async with get_session() as session:
            jobs_data = await load_all_jobs(session)

        recovered = 0
        interrupted = 0
        for job_data in jobs_data:
            if get_job(job_data["id"]):
                continue    # already in memory (e.g. in-process restart)

            # Mark in-flight jobs as interrupted
            if job_data["status"] in ("running", "pending", "waiting_approval"):
                job_data = dict(job_data)   # don't mutate the original
                job_data["status"] = "interrupted"
                try:
                    async with get_session() as session:
                        await update_job_status(session, job_data["id"], "interrupted")
                except Exception:   # noqa: BLE001
                    pass
                interrupted += 1

            import_job(job_data)
            recovered += 1

        if recovered:
            logger.info(
                "[DB] Recovered %d job(s) from DB (%d interrupted)",
                recovered,
                interrupted,
            )

    except Exception as exc:   # noqa: BLE001
        logger.warning("[DB] Job recovery failed: %s", exc)


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="AegisHarness API",
    description="REST + SSE backend for the AegisHarness multi-agent orchestration platform",
    version="0.0.1",
    lifespan=lifespan,
)

# ── Rate limiting ────────────────────────────────────────────────────────────
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Allow Next.js dev server (port 3000) and production origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(jobs_router)
app.include_router(stream_router)
app.include_router(approvals_router)
app.include_router(interview_router)
app.include_router(settings_router)
app.include_router(mcp_router)


@app.get("/healthz")
async def health():
    from .auth import DEV_MODE
    try:
        from db.connection import is_db_available
        db_status = "connected" if is_db_available() else "file-only"
    except Exception:   # noqa: BLE001
        db_status = "unavailable"

    response: dict = {"status": "ok", "version": "0.0.1", "db": db_status}
    if DEV_MODE:
        response["dev_mode"] = True
    return response
