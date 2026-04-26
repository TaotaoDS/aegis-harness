"""Super-admin management endpoints.

Routes
------
GET  /admin/users/pending          — List all users with status='pending'
POST /admin/users/{user_id}/approve — Approve a pending user + optionally grant credits
GET  /admin/tenants                — List all tenants (for workspace switcher)
"""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from api.deps import CurrentUser, require_super_admin

router = APIRouter(prefix="/admin", tags=["admin"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ApproveRequest(BaseModel):
    credit_amount: Optional[float] = None   # USD credit to grant; None = unlimited


# ---------------------------------------------------------------------------
# GET /admin/users/pending
# ---------------------------------------------------------------------------

@router.get("/users/pending")
async def list_pending_users(
    _current_user: CurrentUser = Depends(require_super_admin),
):
    """Return all users awaiting approval."""
    from db.connection import get_session, is_db_available
    from db.models import TenantModel, UserModel
    from sqlalchemy import select

    if not is_db_available():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database unavailable")

    async with get_session() as session:
        rows = (await session.execute(
            select(UserModel, TenantModel)
            .join(TenantModel, UserModel.tenant_id == TenantModel.id, isouter=True)
            .where(UserModel.status == "pending")
            .order_by(UserModel.created_at.desc())
        )).all()

    return [
        {
            "id":           u.id,
            "email":        u.email,
            "display_name": u.display_name,
            "role":         u.role,
            "status":       getattr(u, "status", "pending"),
            "created_at":   u.created_at,
            "tenant": {
                "id":   t.id,
                "name": t.name,
                "slug": t.slug,
                "plan": t.plan,
            } if t else None,
        }
        for u, t in rows
    ]


# ---------------------------------------------------------------------------
# POST /admin/users/{user_id}/approve
# ---------------------------------------------------------------------------

@router.post("/users/{user_id}/approve")
async def approve_user(
    user_id: str,
    body: ApproveRequest,
    _current_user: CurrentUser = Depends(require_super_admin),
):
    """Activate a pending user account and optionally assign a credit balance."""
    from db.connection import get_session, is_db_available
    from db.models import TenantModel, UserModel
    from sqlalchemy import select, update as sa_update

    if not is_db_available():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database unavailable")

    async with get_session() as session:
        result = await session.execute(
            select(UserModel).where(UserModel.id == user_id)
        )
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="User not found")
        if getattr(user, "status", "active") != "pending":
            raise HTTPException(status.HTTP_409_CONFLICT, detail="User is not in pending state")

        # Activate user
        await session.execute(
            sa_update(UserModel)
            .where(UserModel.id == user_id)
            .values(status="active")
        )

        # Grant credit balance to the user's tenant if requested
        if body.credit_amount is not None:
            await session.execute(
                sa_update(TenantModel)
                .where(TenantModel.id == user.tenant_id)
                .values(credit_balance=body.credit_amount)
            )

    return {
        "user_id":        user_id,
        "status":         "active",
        "credit_granted": body.credit_amount,
    }


# ---------------------------------------------------------------------------
# GET /admin/tenants
# ---------------------------------------------------------------------------

@router.get("/tenants")
async def list_all_tenants(
    _current_user: CurrentUser = Depends(require_super_admin),
):
    """Return all tenants — used by the workspace switcher in the sidebar."""
    from db.connection import get_session, is_db_available
    from db.models import TenantModel
    from sqlalchemy import select

    if not is_db_available():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database unavailable")

    async with get_session() as session:
        rows = (await session.execute(
            select(TenantModel)
            .where(TenantModel.is_active == True)  # noqa: E712
            .order_by(TenantModel.created_at.desc())
        )).scalars().all()

    return [
        {
            "id":         t.id,
            "name":       t.name,
            "slug":       t.slug,
            "plan":       t.plan,
            "created_at": t.created_at,
        }
        for t in rows
    ]
