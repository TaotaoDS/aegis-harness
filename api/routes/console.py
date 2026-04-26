"""Console dashboard endpoints (admin/owner only).

Routes
------
GET /console/stats          — System KPIs + tenant list
GET /console/trends         — API call trend data (query: range=1h|6h|24h|7d)
"""

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query

from ..deps import CurrentUser, require_admin

router = APIRouter(prefix="/console", tags=["console"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


async def _query_stats() -> dict[str, Any]:
    """Pull live stats from the DB. Falls back to zeros on any error."""
    try:
        from db.connection import get_session
        from sqlalchemy import func, select, text
        from db.models import JobModel, TenantModel, UserModel

        async with get_session() as session:
            # Total jobs
            total_jobs = (await session.execute(select(func.count()).select_from(JobModel))).scalar() or 0

            # Jobs by status
            status_rows = (await session.execute(
                select(JobModel.status, func.count()).group_by(JobModel.status)
            )).all()
            status_map: dict[str, int] = {r[0]: r[1] for r in status_rows}

            # Total tenants
            total_tenants = (await session.execute(select(func.count()).select_from(TenantModel))).scalar() or 0

            # Active tenants (is_active = true)
            active_tenants = (await session.execute(
                select(func.count()).select_from(TenantModel).where(TenantModel.is_active == True)  # noqa: E712
            )).scalar() or 0

            # Total users
            total_users = (await session.execute(select(func.count()).select_from(UserModel))).scalar() or 0

            # Active users
            active_users = (await session.execute(
                select(func.count()).select_from(UserModel).where(UserModel.is_active == True)  # noqa: E712
            )).scalar() or 0

            # Tenants with job counts (top 10)
            tenant_rows = (await session.execute(
                select(TenantModel.id, TenantModel.name, TenantModel.plan, TenantModel.created_at)
                .where(TenantModel.is_active == True)  # noqa: E712
                .order_by(TenantModel.created_at.desc())
                .limit(20)
            )).all()

            # Per-tenant job count
            tenant_job_rows = (await session.execute(
                select(JobModel.tenant_id, func.count()).group_by(JobModel.tenant_id)
            )).all()
            tenant_job_map: dict[str, int] = {r[0]: r[1] for r in tenant_job_rows if r[0]}

        tenants = [
            {
                "id": r[0],
                "name": r[1],
                "plan": r[2],
                "created_at": r[3],
                "job_count": tenant_job_map.get(r[0], 0),
            }
            for r in tenant_rows
        ]

        return {
            "jobs": {
                "total": total_jobs,
                "running": status_map.get("running", 0),
                "completed": status_map.get("completed", 0),
                "failed": status_map.get("failed", 0),
                "pending": status_map.get("pending", 0),
            },
            "tenants": {
                "total": total_tenants,
                "active": active_tenants,
                "list": tenants,
            },
            "users": {
                "total": total_users,
                "active": active_users,
            },
        }
    except Exception:
        return {
            "jobs": {"total": 0, "running": 0, "completed": 0, "failed": 0, "pending": 0},
            "tenants": {"total": 0, "active": 0, "list": []},
            "users": {"total": 0, "active": 0},
        }


_RANGE_DELTA = {
    "1h":  timedelta(hours=1),
    "6h":  timedelta(hours=6),
    "24h": timedelta(hours=24),
    "7d":  timedelta(days=7),
}

_RANGE_BUCKET = {
    "1h":  "minute",
    "6h":  "10min",
    "24h": "hour",
    "7d":  "day",
}

_RANGE_POINTS = {
    "1h":  60,
    "6h":  36,
    "24h": 24,
    "7d":  28,
}


def _bucket_floor(dt: datetime, bucket: str) -> datetime:
    if bucket == "minute":
        return dt.replace(second=0, microsecond=0)
    if bucket == "10min":
        return dt.replace(minute=(dt.minute // 10) * 10, second=0, microsecond=0)
    if bucket == "hour":
        return dt.replace(minute=0, second=0, microsecond=0)
    if bucket == "day":
        return dt.replace(hour=0, minute=0, second=0, microsecond=0)
    return dt


def _bucket_step(bucket: str) -> timedelta:
    return {
        "minute": timedelta(minutes=1),
        "10min":  timedelta(minutes=10),
        "hour":   timedelta(hours=1),
        "day":    timedelta(days=1),
    }[bucket]


async def _query_trends(range_key: str) -> list[dict[str, Any]]:
    """Return time-series data bucketed by range_key."""
    delta  = _RANGE_DELTA.get(range_key, timedelta(hours=24))
    bucket = _RANGE_BUCKET.get(range_key, "hour")
    now    = _now_utc()
    since  = now - delta

    try:
        from db.connection import get_session
        from sqlalchemy import func, select
        from db.models import JobModel

        async with get_session() as session:
            rows = (await session.execute(
                select(JobModel.created_at, JobModel.status)
                .where(JobModel.created_at >= _iso(since))
            )).all()

        # Build bucket map
        buckets: dict[datetime, dict[str, int]] = {}
        step = _bucket_step(bucket)
        cur  = _bucket_floor(since, bucket)
        while cur <= now:
            buckets[cur] = {"jobs": 0, "completed": 0, "failed": 0}
            cur += step

        for created_at_str, status in rows:
            try:
                dt = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
                b  = _bucket_floor(dt.astimezone(timezone.utc), bucket)
                if b in buckets:
                    buckets[b]["jobs"] += 1
                    if status == "completed":
                        buckets[b]["completed"] += 1
                    elif status == "failed":
                        buckets[b]["failed"] += 1
            except Exception:
                continue

        return [
            {"time": _iso(k), "jobs": v["jobs"], "completed": v["completed"], "failed": v["failed"]}
            for k, v in sorted(buckets.items())
        ]

    except Exception:
        return []


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/stats")
async def get_console_stats(
    _current_user: CurrentUser = Depends(require_admin),
) -> dict[str, Any]:
    """System-wide KPIs for the admin console dashboard."""
    stats = await _query_stats()
    stats["generated_at"] = _iso(_now_utc())
    return stats


@router.get("/trends")
async def get_console_trends(
    range: str = Query(default="24h", pattern="^(1h|6h|24h|7d)$"),
    _current_user: CurrentUser = Depends(require_admin),
) -> dict[str, Any]:
    """Time-series job counts for the trend chart."""
    data = await _query_trends(range)
    return {"range": range, "data": data, "generated_at": _iso(_now_utc())}
