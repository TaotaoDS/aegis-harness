"""Interview answer endpoint — unblocks the CEO interview phase.

POST /jobs/{job_id}/answer
  Body: {"answer": "user's response to the pending CEO question"}

The CEO pipeline thread is blocked in InterviewManager.wait_for_answer()
until this endpoint is called.  It sets the threading.Event and returns
the pipeline to the CEO to process the answer and (optionally) ask the
next question.
"""

from fastapi import APIRouter, HTTPException

from ..job_store import get_job
from ..models import AnswerRequest

router = APIRouter(prefix="/jobs", tags=["interview"])


@router.post("/{job_id}/answer")
async def submit_answer(job_id: str, body: AnswerRequest):
    """Submit the user's answer to the CEO's current interview question."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

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
