"""Repository layer — structured async DB read/write operations.

All functions accept an open ``AsyncSession`` so callers control the
transaction boundary.  None of these functions call ``session.commit()``
— that is the responsibility of the ``get_session()`` context manager
(or the caller when batching multiple writes).

Upsert strategy
---------------
We use PostgreSQL's ``INSERT … ON CONFLICT DO UPDATE`` via SQLAlchemy's
PostgreSQL dialect helper.  This is safe because we always target
PostgreSQL ≥ 14 in production.  The ``db.connection`` layer already
rejects non-PostgreSQL DATABASE_URLs, so dialect-specific SQL is fine here.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from .models import CheckpointModel, EventModel, JobModel, SettingModel, SolutionModel


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ===========================================================================
# Job repository
# ===========================================================================

async def upsert_job(session: AsyncSession, job_data: Dict[str, Any]) -> None:
    """Insert or update a job row (keyed on ``id``)."""
    stmt = pg_insert(JobModel).values(**job_data)
    stmt = stmt.on_conflict_do_update(
        index_elements=["id"],
        set_={k: v for k, v in job_data.items() if k != "id"},
    )
    await session.execute(stmt)


async def update_job_status(
    session: AsyncSession, job_id: str, status: str
) -> None:
    """Update a job's status and set updated_at."""
    stmt = (
        update(JobModel)
        .where(JobModel.id == job_id)
        .values(status=status, updated_at=_now())
    )
    await session.execute(stmt)


async def load_all_jobs(session: AsyncSession) -> List[Dict[str, Any]]:
    """Return all job rows as plain dicts (used for crash recovery)."""
    result = await session.execute(select(JobModel))
    rows = result.scalars().all()
    return [
        {
            "id":           row.id,
            "type":         row.type,
            "workspace_id": row.workspace_id,
            "requirement":  row.requirement,
            "status":       row.status,
            "created_at":   row.created_at,
        }
        for row in rows
    ]


# ===========================================================================
# Event repository
# ===========================================================================

async def append_event(
    session: AsyncSession,
    job_id: str,
    seq: int,
    event: Dict[str, Any],
) -> None:
    """Append a single SSE event to the events table."""
    row = EventModel(
        job_id    = job_id,
        seq       = seq,
        type      = event.get("type", ""),
        label     = event.get("label", ""),
        data      = event.get("data", {}),
        timestamp = event.get("timestamp", _now()),
    )
    session.add(row)


async def load_events_by_job(
    session: AsyncSession, job_id: str
) -> List[Dict[str, Any]]:
    """Return all events for a job ordered by sequence number."""
    result = await session.execute(
        select(EventModel)
        .where(EventModel.job_id == job_id)
        .order_by(EventModel.seq)
    )
    rows = result.scalars().all()
    return [
        {
            "type":      row.type,
            "label":     row.label or "",
            "data":      row.data or {},
            "timestamp": row.timestamp,
            "job_id":    row.job_id,
        }
        for row in rows
    ]


# ===========================================================================
# Checkpoint repository
# ===========================================================================

async def save_checkpoint(
    session: AsyncSession,
    job_id: str,
    phase: str,
    completed_tasks: Optional[List[str]] = None,
    current_task_index: int = 0,
    data: Optional[Dict[str, Any]] = None,
) -> None:
    """Upsert a checkpoint row for the given job."""
    payload = {
        "job_id":               job_id,
        "phase":                phase,
        "completed_tasks":      completed_tasks or [],
        "current_task_index":   current_task_index,
        "data":                 data or {},
        "updated_at":           _now(),
    }
    stmt = pg_insert(CheckpointModel).values(**payload)
    stmt = stmt.on_conflict_do_update(
        index_elements=["job_id"],
        set_={k: v for k, v in payload.items() if k != "job_id"},
    )
    await session.execute(stmt)


async def load_checkpoint(
    session: AsyncSession, job_id: str
) -> Optional[Dict[str, Any]]:
    """Return the checkpoint for a job, or None if no checkpoint exists."""
    result = await session.execute(
        select(CheckpointModel).where(CheckpointModel.job_id == job_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return None
    return {
        "phase":                row.phase,
        "completed_tasks":      row.completed_tasks or [],
        "current_task_index":   row.current_task_index or 0,
        "data":                 row.data or {},
        "updated_at":           row.updated_at,
    }


# ===========================================================================
# Settings repository
# ===========================================================================

async def get_setting(session: AsyncSession, key: str) -> Optional[Any]:
    """Return the parsed JSON value for a settings key, or None."""
    result = await session.execute(
        select(SettingModel).where(SettingModel.key == key)
    )
    row = result.scalar_one_or_none()
    return row.value if row else None


async def set_setting(session: AsyncSession, key: str, value: Any) -> None:
    """Upsert a settings key."""
    payload = {"key": key, "value": value, "updated_at": _now()}
    stmt = pg_insert(SettingModel).values(**payload)
    stmt = stmt.on_conflict_do_update(
        index_elements=["key"],
        set_={"value": value, "updated_at": _now()},
    )
    await session.execute(stmt)


# ===========================================================================
# Solution repository  (Week 4 — pgvector semantic search to be added)
# ===========================================================================

async def upsert_solution(
    session: AsyncSession, solution_data: Dict[str, Any]
) -> None:
    """Insert or update a solution row (keyed on ``id``)."""
    stmt = pg_insert(SolutionModel).values(**solution_data)
    stmt = stmt.on_conflict_do_update(
        index_elements=["id"],
        set_={k: v for k, v in solution_data.items() if k != "id"},
    )
    await session.execute(stmt)


async def load_solutions_by_workspace(
    session: AsyncSession, workspace_id: str
) -> List[Dict[str, Any]]:
    """Return all solutions for a workspace."""
    result = await session.execute(
        select(SolutionModel)
        .where(SolutionModel.workspace_id == workspace_id)
        .order_by(SolutionModel.timestamp)
    )
    rows = result.scalars().all()
    return [
        {
            "id":          row.id,
            "type":        row.type,
            "problem":     row.problem,
            "solution":    row.solution,
            "context":     row.context or "",
            "tags":        row.tags or [],
            "job_id":      row.job_id or "",
            "timestamp":   row.timestamp or "",
        }
        for row in rows
    ]
