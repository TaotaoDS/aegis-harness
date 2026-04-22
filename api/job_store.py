"""In-memory job store (no persistence needed for development/demo)."""

import threading
from datetime import datetime, timezone
from typing import Dict, List, Optional
import uuid


class JobRecord:
    """Mutable job state. Fields updated in-place by job_runner."""

    __slots__ = (
        "id", "type", "workspace_id", "requirement",
        "status", "created_at", "bus", "hitl_manager", "interview_manager",
    )

    def __init__(
        self,
        job_id: str,
        job_type: str,
        workspace_id: str,
        requirement: str,
    ):
        self.id = job_id
        self.type = job_type
        self.workspace_id = workspace_id
        self.requirement = requirement
        self.status = "pending"
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.bus = None               # AsyncQueueBus, attached before start()
        self.hitl_manager = None      # HITLManager, attached before start()
        self.interview_manager = None # InterviewManager, attached before start()


_store: Dict[str, JobRecord] = {}
_lock = threading.Lock()


def create_job(job_type: str, workspace_id: str, requirement: str) -> JobRecord:
    job_id = str(uuid.uuid4())[:8]
    job = JobRecord(
        job_id=job_id,
        job_type=job_type,
        workspace_id=workspace_id,
        requirement=requirement,
    )
    with _lock:
        _store[job_id] = job
    return job


def get_job(job_id: str) -> Optional[JobRecord]:
    return _store.get(job_id)


def list_jobs() -> List[JobRecord]:
    with _lock:
        return sorted(_store.values(), key=lambda j: j.created_at, reverse=True)


def update_status(job_id: str, status: str) -> None:
    job = _store.get(job_id)
    if job:
        job.status = status
