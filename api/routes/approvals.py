"""Human-in-the-Loop approval endpoints."""

from fastapi import APIRouter, HTTPException

from ..job_store import get_job
from ..models import ApprovalRequest

router = APIRouter(prefix="/jobs", tags=["approvals"])


@router.post("/{job_id}/approve")
async def approve(job_id: str, body: ApprovalRequest):
    """Approve or reject a pending HITL gate."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if not job.hitl_manager:
        raise HTTPException(status_code=409, detail="No HITL manager for this job")

    resolved = job.hitl_manager.resolve(approved=body.approved, note=body.note)
    if not resolved:
        raise HTTPException(status_code=409, detail="No pending approval gate")

    return {
        "ok": True,
        "job_id": job_id,
        "approved": body.approved,
        "note": body.note,
    }
