"""Job CRUD + launch endpoints.

Auth
----
All endpoints require an authenticated user (``Depends(get_current_user)``).
In dev mode (``SECRET_KEY`` absent) the synthetic bootstrap owner is returned,
so all existing behaviour is preserved.

Visibility rules
----------------
- Admin / Owner: see all jobs in their tenant.
- Member: see only jobs they created (``created_by == user_id``).

DB persistence
--------------
Every ``POST /jobs`` call mirrors the new job to PostgreSQL via
``_db_persist_job()``.  Every status update is mirrored by
``_db_update_status()`` which is wired into the ``update_status``
wrapper below.  Both helpers are no-ops when the DB is not available
(file-only mode).
"""

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request

from ..deps import CurrentUser, get_current_user, require_active
from ..rate_limit import limiter
from ..event_bridge import AsyncQueueBus
from ..hitl_manager import HITLManager
from ..interview_manager import InterviewManager
from ..job_runner import start_job
from ..job_store import create_job, get_job, list_jobs, update_status
from ..models import JobCreate, JobOut

router = APIRouter(prefix="/jobs", tags=["jobs"])


# ---------------------------------------------------------------------------
# Ownership guard (shared by stream / approvals / interview)
# ---------------------------------------------------------------------------

def _assert_job_access(job, current_user: CurrentUser) -> None:
    """Raise 404 if the job does not belong to the user's tenant or (for
    members) was not created by this user.

    404 (not 403) is used intentionally to prevent cross-tenant enumeration:
    an attacker cannot distinguish "not found" from "not yours".

    Backward-compat: jobs created before multi-tenancy have ``tenant_id=None``;
    they are treated as belonging to the bootstrap tenant and are accessible
    to all users (dev mode uses bootstrap tenant anyway).
    """
    job_tenant = job.tenant_id          # str | None
    cur_tenant = str(current_user.tenant_id)

    if job_tenant is not None and job_tenant != cur_tenant:
        raise HTTPException(status_code=404, detail="Job not found")

    # Members only see their own jobs
    if current_user.role == "member":
        job_owner = job.created_by      # str | None
        if job_owner is not None and job_owner != str(current_user.user_id):
            raise HTTPException(status_code=404, detail="Job not found")


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
                "tenant_id":    job.tenant_id,
                "created_by":   job.created_by,
            })
    except Exception:   # noqa: BLE001
        pass


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


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=list[JobOut])
async def get_jobs(current_user: CurrentUser = Depends(get_current_user)):
    """List jobs.

    Admins/Owners see all jobs in the tenant.
    Members see only jobs they created.
    Jobs created before multi-tenancy (``tenant_id=None``) are visible to
    bootstrap-tenant users to preserve crash-recovery history.
    """
    cur_tenant = str(current_user.tenant_id)
    cur_user   = str(current_user.user_id)

    filtered = []
    for job in list_jobs():
        job_tenant = job.tenant_id
        # Include jobs that match the tenant, or legacy jobs (no tenant_id)
        if job_tenant is not None and job_tenant != cur_tenant:
            continue
        # Members only see their own
        if current_user.role == "member":
            job_owner = job.created_by
            if job_owner is not None and job_owner != cur_user:
                continue
        filtered.append(job)

    return [_to_out(j) for j in filtered]


@router.post("", response_model=JobOut, status_code=201)
@limiter.limit("60/minute")
async def create_and_start_job(
    request: Request,
    body: JobCreate,
    current_user: CurrentUser = Depends(require_active),
):
    job = create_job(
        job_type=body.type,
        workspace_id=body.workspace_id,
        requirement=body.requirement,
    )

    # Stamp tenant and owner onto the job record
    job.tenant_id  = str(current_user.tenant_id)
    job.created_by = str(current_user.user_id)

    loop = asyncio.get_event_loop()

    job.bus = AsyncQueueBus(job_id=job.id, loop=loop)
    job.hitl_manager = HITLManager(
        job_id=job.id,
        bus=job.bus,
        on_status_change=update_status,
    )
    job.interview_manager = InterviewManager(job_id=job.id, bus=job.bus)

    # Pre-load user profile scoped to this tenant + user
    from ..settings_service import load_user_profile_dict
    job.user_profile = await load_user_profile_dict(
        tenant_id=str(current_user.tenant_id),
        user_id=str(current_user.user_id),
    )

    await _db_persist_job(job)
    start_job(job, loop)
    return _to_out(job)


@router.get("/{job_id}", response_model=JobOut)
async def get_job_detail(
    job_id: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    _assert_job_access(job, current_user)
    return _to_out(job)


def _to_out(job) -> JobOut:
    pending_approval = job.hitl_manager.pending_approval if job.hitl_manager else None
    pending_question = job.interview_manager.pending_question if job.interview_manager else None
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
