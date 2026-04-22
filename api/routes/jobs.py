"""Job CRUD + launch endpoints."""

import asyncio

from fastapi import APIRouter, HTTPException

from ..event_bridge import AsyncQueueBus
from ..hitl_manager import HITLManager
from ..job_runner import start_job
from ..job_store import create_job, get_job, list_jobs, update_status
from ..models import JobCreate, JobOut

router = APIRouter(prefix="/jobs", tags=["jobs"])


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

    # Wire up AsyncQueueBus and HITLManager before starting the thread
    job.bus = AsyncQueueBus(job_id=job.id, loop=loop)
    job.hitl_manager = HITLManager(
        job_id=job.id,
        bus=job.bus,
        on_status_change=update_status,
    )

    start_job(job, loop)
    return _to_out(job)


@router.get("/{job_id}", response_model=JobOut)
async def get_job_detail(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return _to_out(job)


def _to_out(job) -> JobOut:
    pending = job.hitl_manager.pending_approval if job.hitl_manager else None
    return JobOut(
        id=job.id,
        type=job.type,
        workspace_id=job.workspace_id,
        requirement=job.requirement,
        status=job.status,
        created_at=job.created_at,
        event_count=len(job.bus.events_log) if job.bus else 0,
        pending_approval=pending,
    )
