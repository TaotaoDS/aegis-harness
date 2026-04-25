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

from .models import (
    CheckpointModel,
    EventModel,
    JobModel,
    RefreshTokenModel,
    SettingModel,
    SolutionModel,
    TenantModel,
    UserModel,
    WorkspaceModel,
)


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

# Bootstrap tenant UUID — pre-existing rows are backfilled to this in migration 005.
_BOOTSTRAP_TENANT = "00000000-0000-0000-0000-000000000001"


async def get_setting(
    session: AsyncSession, key: str, tenant_id: str = _BOOTSTRAP_TENANT
) -> Optional[Any]:
    """Return the parsed JSON value for ``(tenant_id, key)``, or ``None``.

    Falls back to the bootstrap tenant when the exact tenant has no matching
    row, so settings configured before multi-tenancy was enabled are still
    visible to all tenants until they override them explicitly.
    """
    result = await session.execute(
        select(SettingModel).where(
            SettingModel.key       == key,
            SettingModel.tenant_id == tenant_id,
        )
    )
    row = result.scalar_one_or_none()
    if row is None and tenant_id != _BOOTSTRAP_TENANT:
        # Transparent fall-through to bootstrap (global) settings
        result = await session.execute(
            select(SettingModel).where(
                SettingModel.key       == key,
                SettingModel.tenant_id == _BOOTSTRAP_TENANT,
            )
        )
        row = result.scalar_one_or_none()
    return row.value if row else None


async def set_setting(
    session: AsyncSession, key: str, value: Any, tenant_id: str = _BOOTSTRAP_TENANT
) -> None:
    """Upsert a ``(tenant_id, key)`` settings row."""
    payload = {
        "tenant_id":  tenant_id,
        "key":        key,
        "value":      value,
        "updated_at": _now(),
    }
    stmt = pg_insert(SettingModel).values(**payload)
    stmt = stmt.on_conflict_do_update(
        index_elements=["tenant_id", "key"],
        set_={"value": value, "updated_at": _now()},
    )
    await session.execute(stmt)


async def get_all_settings_by_tenant(
    session: AsyncSession, tenant_id: str = _BOOTSTRAP_TENANT
) -> dict[str, Any]:
    """Return all settings for a tenant as a plain ``{key: value}`` dict."""
    result = await session.execute(
        select(SettingModel).where(SettingModel.tenant_id == tenant_id)
    )
    return {row.key: row.value for row in result.scalars().all()}


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


# ===========================================================================
# v0.1.0 — Tenant-scoped repository helpers
# ===========================================================================

# ---------------------------------------------------------------------------
# Tenant
# ---------------------------------------------------------------------------

async def get_tenant_by_id(
    session: AsyncSession, tenant_id: str
) -> Optional[Dict[str, Any]]:
    result = await session.execute(
        select(TenantModel).where(TenantModel.id == tenant_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return None
    return {"id": row.id, "slug": row.slug, "name": row.name,
            "plan": row.plan, "is_active": row.is_active}


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------

async def get_user_by_id(
    session: AsyncSession, user_id: str
) -> Optional[Dict[str, Any]]:
    result = await session.execute(
        select(UserModel).where(UserModel.id == str(user_id))
    )
    row = result.scalar_one_or_none()
    return _user_row_to_dict(row)


async def get_user_by_email(
    session: AsyncSession, email: str
) -> Optional[Dict[str, Any]]:
    result = await session.execute(
        select(UserModel).where(UserModel.email == email.lower())
    )
    row = result.scalar_one_or_none()
    return _user_row_to_dict(row)


async def list_users_by_tenant(
    session: AsyncSession, tenant_id: str
) -> List[Dict[str, Any]]:
    result = await session.execute(
        select(UserModel)
        .where(UserModel.tenant_id == tenant_id, UserModel.is_active.is_(True))
        .order_by(UserModel.created_at)
    )
    return [_user_row_to_dict(row) for row in result.scalars().all() if row]


def _user_row_to_dict(row: Optional[UserModel]) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    return {
        "id":              row.id,
        "tenant_id":       row.tenant_id,
        "email":           row.email,
        "display_name":    row.display_name or "",
        "hashed_password": row.hashed_password,
        "role":            row.role,
        "is_active":       row.is_active,
        "created_at":      row.created_at,
        "last_login_at":   row.last_login_at or "",
    }


# ---------------------------------------------------------------------------
# Refresh tokens
# ---------------------------------------------------------------------------

async def get_valid_refresh_token(
    session: AsyncSession, token_hash: str
) -> Optional[Dict[str, Any]]:
    """Return a non-revoked, non-expired refresh_token row as a dict."""
    now = datetime.now(timezone.utc).isoformat()
    result = await session.execute(
        select(RefreshTokenModel).where(
            RefreshTokenModel.token_hash == token_hash,
            RefreshTokenModel.revoked_at.is_(None),
            RefreshTokenModel.expires_at > now,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        return None
    return {
        "id":         row.id,
        "user_id":    row.user_id,
        "token_hash": row.token_hash,
        "expires_at": row.expires_at,
        "revoked_at": row.revoked_at,
        "meta":       row.meta,
    }


async def revoke_refresh_token(session: AsyncSession, token_id: str) -> None:
    from sqlalchemy import update as sa_update
    await session.execute(
        sa_update(RefreshTokenModel)
        .where(RefreshTokenModel.id == token_id)
        .values(revoked_at=_now())
    )


# ---------------------------------------------------------------------------
# Workspace
# ---------------------------------------------------------------------------

async def get_workspace_by_slug(
    session: AsyncSession, tenant_id: str, slug: str
) -> Optional[Dict[str, Any]]:
    result = await session.execute(
        select(WorkspaceModel).where(
            WorkspaceModel.tenant_id == tenant_id,
            WorkspaceModel.slug == slug,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        return None
    return {
        "id": row.id, "tenant_id": row.tenant_id,
        "slug": row.slug, "name": row.name,
        "created_by": row.created_by, "is_active": row.is_active,
    }


async def list_workspaces_by_tenant(
    session: AsyncSession, tenant_id: str
) -> List[Dict[str, Any]]:
    result = await session.execute(
        select(WorkspaceModel)
        .where(WorkspaceModel.tenant_id == tenant_id, WorkspaceModel.is_active.is_(True))
        .order_by(WorkspaceModel.created_at)
    )
    return [
        {"id": row.id, "tenant_id": row.tenant_id, "slug": row.slug, "name": row.name}
        for row in result.scalars().all()
    ]


# ---------------------------------------------------------------------------
# Tenant-scoped job list (used after Sprint C route protection)
# ---------------------------------------------------------------------------

async def load_jobs_by_tenant(
    session: AsyncSession,
    tenant_id: str,
    user_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return jobs for a tenant.

    When ``user_id`` is provided only that user's jobs are returned
    (member-level visibility).  Pass ``user_id=None`` for admin/owner view.

    Jobs created before migration 005 (no tenant_id column yet) have
    ``tenant_id = None`` and are included only when ``tenant_id`` matches
    the bootstrap constant, preserving backward compatibility.
    """
    stmt = select(JobModel).where(JobModel.tenant_id == tenant_id)
    if user_id:
        stmt = stmt.where(JobModel.created_by == user_id)
    stmt = stmt.order_by(JobModel.created_at.desc())

    result = await session.execute(stmt)
    rows = result.scalars().all()
    return [
        {
            "id":           row.id,
            "type":         row.type,
            "workspace_id": row.workspace_id,
            "requirement":  row.requirement,
            "status":       row.status,
            "created_at":   row.created_at,
            "tenant_id":    row.tenant_id,
            "created_by":   row.created_by,
        }
        for row in rows
    ]
