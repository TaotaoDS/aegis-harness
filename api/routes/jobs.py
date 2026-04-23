"""Job CRUD + launch endpoints.

DB persistence
--------------
Every ``POST /jobs`` call mirrors the new job to PostgreSQL via
``_db_persist_job()``.  Every status update is mirrored by
``_db_update_status()`` which is wired into the ``update_status``
wrapper below.  Both helpers are no-ops when the DB is not available
(file-only mode).
"""

import asyncio

from fastapi import APIRouter, HTTPException

from ..event_bridge import AsyncQueueBus
from ..hitl_manager import HITLManager
from ..interview_manager import InterviewManager
from ..job_runner import start_job
from ..job_store import create_job, get_job, list_jobs, update_status
from ..models import JobCreate, JobOut

router = APIRouter(prefix="/jobs", tags=["jobs"])


# ---------------------------------------------------------------------------
# DB helpers (all no-ops when DB is unavailable)
# ---------------------------------------------------------------------------

async def _db_persist_job(job) -> None:
    """Mirror a newly created job to the DB."""
    try:
        from db.connection import get_session, is_db_available
        from db.repository import upsert_job
        if not is_db_available():
            return
        async with get_session() as session:
            await upsert_job(session, {
                "id":           job.id,
                "type":         job.type,
                "workspace_id": job.workspace_id,
                "requirement":  job.requirement,
                "status":       job.status,
                "created_at":   job.created_at,
            })
    except Exception:   # noqa: BLE001
        pass            # never let DB errors prevent job creation


async def _db_update_status(job_id: str, status: str) -> None:
    """Mirror a status change to the DB."""
    try:
        from db.connection import get_session, is_db_available
        from db.repository import update_job_status
        if not is_db_available():
            return
        async with get_session() as session:
            await update_job_status(session, job_id, status)
    except Exception:   # noqa: BLE001
        pass


@router.get("", response_model=list[JobOut])
async def get_jobs():
    jobs = list_jobs()
    return [_to_out(j) for j in jobs]


@router.post("", response_model=JobOut, status_code=201)
async def create_and_start_job(body: JobCreate):
    job = create_job(
        job_type=body.type,
        workspace_id=body.workspace_id,
        requirement=body.requirement,
    )

    loop = asyncio.get_event_loop()

    # Wire up AsyncQueueBus, HITLManager, and InterviewManager before starting
    job.bus = AsyncQueueBus(job_id=job.id, loop=loop)
    job.hitl_manager = HITLManager(
        job_id=job.id,
        bus=job.bus,
        on_status_change=update_status,
    )
    job.interview_manager = InterviewManager(job_id=job.id, bus=job.bus)

    # Pre-load user profile so the pipeline thread has it without async calls
    from ..settings_service import load_user_profile_dict
    job.user_profile = await load_user_profile_dict()

    # Mirror to DB (no-op if DB unavailable)
    await _db_persist_job(job)

    start_job(job, loop)
    return _to_out(job)


@router.get("/{job_id}", response_model=JobOut)
async def get_job_detail(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return _to_out(job)


def _to_out(job) -> JobOut:
    pending_approval  = job.hitl_manager.pending_approval if job.hitl_manager else None
    pending_question  = job.interview_manager.pending_question if job.interview_manager else None
    return JobOut(
        id=job.id,
        type=job.type,
        workspace_id=job.workspace_id,
        requirement=job.requirement,
        status=job.status,
        created_at=job.created_at,
        event_count=len(job.bus.events_log) if job.bus else 0,
        pending_approval=pending_approval,
        pending_question=pending_question,
    )
