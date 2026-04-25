"""Interview answer endpoint — unblocks the CEO interview phase.

POST /jobs/{job_id}/answer
  Body: {"answer": "user's response to the pending CEO question"}

Auth
----
Requires authenticated user.  Members can only answer questions in their
own jobs.  Admins/Owners can answer on any job in the tenant.
"""

from fastapi import APIRouter, Depends, HTTPException

from ..deps import CurrentUser, get_current_user
from ..job_store import get_job
from ..models import AnswerRequest
from ..routes.jobs import _assert_job_access

router = APIRouter(prefix="/jobs", tags=["interview"])


@router.post("/{job_id}/answer")
async def submit_answer(
    job_id: str,
    body: AnswerRequest,
    current_user: CurrentUser = Depends(get_current_user),
):
    """Submit the user's answer to the CEO's current interview question."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    _assert_job_access(job, current_user)

    if not job.interview_manager:
        raise HTTPException(
            status_code=409,
            detail="No interview in progress for this job",
        )

    resolved = job.interview_manager.submit_answer(body.answer)
    if not resolved:
        raise HTTPException(
            status_code=409,
            detail="No pending question — interview may already be complete",
        )

    return {
        "ok": True,
        "answers_given": job.interview_manager.answers_given,
    }
