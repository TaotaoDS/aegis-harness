"""In-memory job store with optional DB write-through.

The in-memory dict (_store) remains the source-of-truth for live
request handling and SSE streaming.  When a PostgreSQL database is
available, every mutation is mirrored asynchronously so that the full
job history survives a process restart.

Crash-recovery entry point
---------------------------
``import_job()`` reconstructs a ``JobRecord`` from a plain dict (e.g.
loaded from the DB) and inserts it into the in-memory store.  Called
from ``api.main`` at startup.
"""

import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid


class JobRecord:
    """Mutable job state. Fields updated in-place by job_runner."""

    __slots__ = (
        "id", "type", "workspace_id", "requirement",
        "status", "created_at", "bus", "hitl_manager", "interview_manager",
        "user_profile",   # Optional[dict] — pre-loaded UserProfile dict
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
        self.user_profile = None      # dict | None — loaded from settings at job creation


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


def import_job(job_data: Dict[str, Any]) -> JobRecord:
    """Reconstruct a ``JobRecord`` from a persisted dict.

    Used during startup crash-recovery to reload jobs from the database.
    If a job with the same id already exists in the in-memory store, the
    existing record is returned unchanged (idempotent).
    """
    job_id = job_data["id"]
    with _lock:
        if job_id in _store:
            return _store[job_id]

        job = JobRecord(
            job_id       = job_id,
            job_type     = job_data.get("type", "build"),
            workspace_id = job_data.get("workspace_id", "default"),
            requirement  = job_data.get("requirement", ""),
        )
        job.status     = job_data.get("status", "interrupted")
        job.created_at = job_data.get(
            "created_at", datetime.now(timezone.utc).isoformat()
        )
        _store[job_id] = job

    return job
