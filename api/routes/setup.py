"""One-time system initialisation endpoints.

Routes
------
GET  /setup/status  — Check whether a super_admin already exists (unauthenticated).
POST /setup         — Create the global super_admin account (locked once used).

Design
------
Once a super_admin account exists this endpoint permanently returns 423 Locked
so the attack surface is zero after initial setup.  The endpoint is intentionally
rate-limited to prevent brute-force enumeration during the setup window.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, field_validator

from api.rate_limit import limiter
from api.auth import DEV_MODE, create_access_token, create_refresh_token, hash_password

router = APIRouter(prefix="/setup", tags=["setup"])

# Bootstrap tenant ID — super_admin lives in this tenant.
_SYSTEM_TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _super_admin_exists(session) -> bool:
    from sqlalchemy import select
    from db.models import UserModel
    result = await session.execute(
        select(UserModel.id).where(UserModel.role == "super_admin").limit(1)
    )
    return result.scalar_one_or_none() is not None


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class SetupRequest(BaseModel):
    email:        EmailStr
    password:     str
    display_name: Optional[str] = None

    @field_validator("password")
    @classmethod
    def _check_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


# ---------------------------------------------------------------------------
# GET /setup/status
# ---------------------------------------------------------------------------

@router.get("/status")
async def setup_status():
    """Return whether the system has been initialised with a super_admin.

    Used by the frontend to decide whether to show the onboarding wizard.
    Always returns 200 so the frontend can reliably check without dealing
    with error handling for this specific case.
    """
    from db.connection import get_session, is_db_available

    if not is_db_available():
        return {"initialized": False}

    try:
        async with get_session() as session:
            exists = await _super_admin_exists(session)
        return {"initialized": exists}
    except Exception:
        return {"initialized": False}


# ---------------------------------------------------------------------------
# POST /setup
# ---------------------------------------------------------------------------

@router.post("", status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
async def setup(request: Request, body: SetupRequest, response: Response):
    """Create the one-and-only super_admin account.

    Locked (423) once any super_admin account exists.
    Requires SECRET_KEY to be configured so a real JWT can be issued.
    """
    if DEV_MODE:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Auth is disabled — set SECRET_KEY to enable",
        )

    from db.connection import get_session, is_db_available
    from db.models import UserModel, RefreshTokenModel

    if not is_db_available():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database unavailable")

    async with get_session() as session:
        if await _super_admin_exists(session):
            raise HTTPException(
                status.HTTP_423_LOCKED,
                detail="System already initialised — super admin account exists",
            )

        now        = datetime.now(timezone.utc).isoformat()
        user_id    = uuid4()
        tenant_id  = _SYSTEM_TENANT_ID

        session.add(UserModel(
            id              = str(user_id),
            tenant_id       = str(tenant_id),
            email           = body.email.lower(),
            display_name    = body.display_name or body.email.split("@")[0],
            hashed_password = hash_password(body.password),
            role            = "super_admin",
            status          = "active",
            is_active       = True,
            created_at      = now,
        ))

        raw_refresh, refresh_hash = create_refresh_token(user_id)
        expire_at = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
        session.add(RefreshTokenModel(
            id         = str(uuid4()),
            user_id    = str(user_id),
            token_hash = refresh_hash,
            expires_at = expire_at,
            created_at = now,
        ))

    access_token = create_access_token(user_id, tenant_id, "super_admin", body.email.lower(), status="active")
    response.set_cookie("aegis_access",  access_token, max_age=60 * 15,        httponly=True, samesite="lax", secure=False)
    response.set_cookie("aegis_refresh", raw_refresh,  max_age=60 * 60 * 24 * 7, httponly=True, samesite="lax", secure=False)

    return {
        "access_token": access_token,
        "token_type":   "bearer",
        "user": {
            "id":           str(user_id),
            "email":        body.email.lower(),
            "display_name": body.display_name or body.email.split("@")[0],
            "role":         "super_admin",
            "status":       "active",
            "tenant":       None,
        },
    }
