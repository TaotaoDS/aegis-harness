"""Authentication endpoints.

Routes
------
POST /auth/register        — Create new tenant + owner account
POST /auth/login           — Exchange credentials for tokens
POST /auth/refresh         — Rotate refresh token → new token pair
POST /auth/logout          — Revoke refresh token + clear cookies
GET  /auth/me              — Return current user info
POST /auth/invite          — Owner/Admin: invite user to tenant
POST /auth/accept-invite/{token} — Accept invitation, set password
PUT  /auth/users/{user_id}/role  — Owner/Admin: change a user's role
DELETE /auth/users/{user_id}     — Owner/Admin: deactivate a user

Dev mode
--------
When ``SECRET_KEY`` is absent (``DEV_MODE=True``) all mutation endpoints
return 503 with a clear message.  GET /auth/me returns the synthetic dev
user so the frontend can always render the UI.
"""

import re
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, field_validator

from api.rate_limit import limiter

from api.auth import (
    DEV_MODE,
    create_access_token,
    create_refresh_token,
    decode_refresh_token_sub,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from api.deps import (
    BOOTSTRAP_TENANT_ID,
    BOOTSTRAP_USER_ID,
    CurrentUser,
    get_current_user,
    require_admin,
)

router = APIRouter(prefix="/auth", tags=["auth"])

# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9\-]{1,61}[a-z0-9]$")


class RegisterRequest(BaseModel):
    email:       EmailStr
    password:    str
    tenant_name: str
    display_name: Optional[str] = None

    @field_validator("password")
    @classmethod
    def _check_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v

    @field_validator("tenant_name")
    @classmethod
    def _check_tenant_name(cls, v: str) -> str:
        if len(v.strip()) < 2:
            raise ValueError("Tenant name must be at least 2 characters")
        return v.strip()


class LoginRequest(BaseModel):
    email:    EmailStr
    password: str


class InviteRequest(BaseModel):
    email: EmailStr
    role:  str = "member"

    @field_validator("role")
    @classmethod
    def _check_role(cls, v: str) -> str:
        if v not in ("admin", "member"):
            raise ValueError("Role must be 'admin' or 'member'")
        return v


class AcceptInviteRequest(BaseModel):
    password:     str
    display_name: Optional[str] = None

    @field_validator("password")
    @classmethod
    def _check_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class ChangeRoleRequest(BaseModel):
    role: str

    @field_validator("role")
    @classmethod
    def _check_role(cls, v: str) -> str:
        if v not in ("owner", "admin", "member"):
            raise ValueError("Role must be 'owner', 'admin', or 'member'")
        return v


# ---------------------------------------------------------------------------
# Cookie helpers
# ---------------------------------------------------------------------------

_COOKIE_OPTS = dict(httponly=True, samesite="lax", secure=False)  # secure=True in prod


def _set_tokens(response: Response, access_token: str, refresh_token: str) -> None:
    response.set_cookie("aegis_access",  access_token,  max_age=60 * 15, **_COOKIE_OPTS)
    response.set_cookie("aegis_refresh", refresh_token, max_age=60 * 60 * 24 * 7, **_COOKIE_OPTS)


def _clear_tokens(response: Response) -> None:
    response.delete_cookie("aegis_access")
    response.delete_cookie("aegis_refresh")


# ---------------------------------------------------------------------------
# Dev-mode guard
# ---------------------------------------------------------------------------

def _require_auth_configured() -> None:
    if DEV_MODE:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Auth is disabled — set SECRET_KEY to enable",
        )


# ---------------------------------------------------------------------------
# Tenant / user helpers (thin wrappers over DB or in-memory store)
# ---------------------------------------------------------------------------

def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:63] or "tenant"


async def _get_tenant_by_slug(session, slug: str):
    from sqlalchemy import select
    from db.models import TenantModel
    result = await session.execute(select(TenantModel).where(TenantModel.slug == slug))
    return result.scalar_one_or_none()


async def _get_user_by_email(session, email: str):
    from sqlalchemy import select
    from db.models import UserModel
    result = await session.execute(
        select(UserModel).where(UserModel.email == email.lower())
    )
    return result.scalar_one_or_none()


async def _get_user_by_id(session, user_id: UUID):
    from sqlalchemy import select
    from db.models import UserModel
    result = await session.execute(
        select(UserModel).where(UserModel.id == str(user_id))
    )
    return result.scalar_one_or_none()


async def _get_valid_refresh_token(session, token_hash: str):
    """Return a non-revoked, non-expired refresh_token row or None."""
    from sqlalchemy import select
    from db.models import RefreshTokenModel
    now = datetime.now(timezone.utc).isoformat()
    result = await session.execute(
        select(RefreshTokenModel).where(
            RefreshTokenModel.token_hash == token_hash,
            RefreshTokenModel.revoked_at.is_(None),
            RefreshTokenModel.expires_at > now,
        )
    )
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# POST /auth/register
# ---------------------------------------------------------------------------

@router.post("/register", status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
async def register(request: Request, body: RegisterRequest, response: Response):
    """Create a new tenant and an owner account.

    Returns the access token in the response body AND sets both tokens as
    httpOnly cookies so the browser and API clients both work.
    """
    _require_auth_configured()

    from db.connection import get_session, is_db_available
    from db.models import TenantModel, UserModel, RefreshTokenModel
    from datetime import timedelta

    if not is_db_available():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database unavailable")

    slug = _slugify(body.tenant_name)
    now  = datetime.now(timezone.utc).isoformat()

    async with get_session() as session:
        # Reject duplicate email early
        existing = await _get_user_by_email(session, body.email)
        if existing:
            raise HTTPException(status.HTTP_409_CONFLICT, detail="Email already registered")

        # Deduplicate slug
        base_slug = slug
        counter   = 1
        while await _get_tenant_by_slug(session, slug):
            slug = f"{base_slug}-{counter}"
            counter += 1

        # Create tenant
        from uuid import uuid4
        tenant_id = uuid4()
        session.add(TenantModel(
            id         = str(tenant_id),
            slug       = slug,
            name       = body.tenant_name,
            plan       = "free",
            is_active  = True,
            created_at = now,
        ))

        # Create owner user
        user_id = uuid4()
        session.add(UserModel(
            id              = str(user_id),
            tenant_id       = str(tenant_id),
            email           = body.email.lower(),
            display_name    = body.display_name or body.email.split("@")[0],
            hashed_password = hash_password(body.password),
            role            = "owner",
            is_active       = True,
            created_at      = now,
        ))

        # Issue refresh token
        raw_refresh, refresh_hash = create_refresh_token(user_id)
        expire_at = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
        session.add(RefreshTokenModel(
            id          = str(uuid4()),
            user_id     = str(user_id),
            token_hash  = refresh_hash,
            expires_at  = expire_at,
            created_at  = now,
        ))

    access_token = create_access_token(user_id, tenant_id, "owner", body.email.lower())
    _set_tokens(response, access_token, raw_refresh)

    return {
        "access_token": access_token,
        "token_type":   "bearer",
        "user": {
            "id":           str(user_id),
            "email":        body.email.lower(),
            "display_name": body.display_name or body.email.split("@")[0],
            "role":         "owner",
            "tenant": {"id": str(tenant_id), "slug": slug, "name": body.tenant_name},
        },
    }


# ---------------------------------------------------------------------------
# POST /auth/login
# ---------------------------------------------------------------------------

@router.post("/login")
@limiter.limit("10/minute")
async def login(request: Request, body: LoginRequest, response: Response):
    """Exchange credentials for a token pair."""
    _require_auth_configured()

    from db.connection import get_session, is_db_available
    from db.models import RefreshTokenModel, TenantModel
    from sqlalchemy import select
    from datetime import timedelta
    from uuid import uuid4

    if not is_db_available():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database unavailable")

    _INVALID = HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    async with get_session() as session:
        user = await _get_user_by_email(session, body.email)
        # Constant-time path: always call verify_password even on miss
        hashed = user.hashed_password if user else "$2b$12$invalidhashpadding000000000000000000000000000000000000000"
        if not verify_password(body.password, hashed) or not user:
            raise _INVALID
        if not user.is_active:
            raise _INVALID

        # Load tenant (for response payload)
        tenant_result = await session.execute(
            select(TenantModel).where(TenantModel.id == user.tenant_id)
        )
        tenant = tenant_result.scalar_one_or_none()

        # Rotate: revoke all existing refresh tokens for this user
        from sqlalchemy import update as sa_update
        await session.execute(
            sa_update(RefreshTokenModel)
            .where(
                RefreshTokenModel.user_id == user.id,
                RefreshTokenModel.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(timezone.utc).isoformat())
        )

        # Issue new refresh token
        user_uuid = UUID(user.id)
        raw_refresh, refresh_hash = create_refresh_token(user_uuid)
        now = datetime.now(timezone.utc).isoformat()
        expire_at = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
        session.add(RefreshTokenModel(
            id          = str(uuid4()),
            user_id     = user.id,
            token_hash  = refresh_hash,
            expires_at  = expire_at,
            created_at  = now,
        ))

        # Update last_login_at
        from sqlalchemy import update as sa_update2
        from db.models import UserModel
        await session.execute(
            sa_update2(UserModel)
            .where(UserModel.id == user.id)
            .values(last_login_at=now)
        )

    tenant_id = UUID(user.tenant_id)
    access_token = create_access_token(user_uuid, tenant_id, user.role, user.email)
    _set_tokens(response, access_token, raw_refresh)

    return {
        "access_token": access_token,
        "token_type":   "bearer",
        "user": {
            "id":           user.id,
            "email":        user.email,
            "display_name": user.display_name,
            "role":         user.role,
            "tenant": {
                "id":   tenant.id   if tenant else user.tenant_id,
                "slug": tenant.slug if tenant else "",
                "name": tenant.name if tenant else "",
                "plan": tenant.plan if tenant else "free",
            },
        },
    }


# ---------------------------------------------------------------------------
# POST /auth/refresh
# ---------------------------------------------------------------------------

@router.post("/refresh")
async def refresh_tokens(
    response: Response,
    aegis_refresh: Optional[str] = Cookie(default=None),
):
    """Rotate the refresh token and issue a new access token."""
    _require_auth_configured()

    from db.connection import get_session, is_db_available
    from db.models import RefreshTokenModel, TenantModel
    from sqlalchemy import select, update as sa_update
    from datetime import timedelta
    from uuid import uuid4

    if not is_db_available():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database unavailable")

    if not aegis_refresh:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Refresh token missing")

    token_hash = hash_refresh_token(aegis_refresh)
    user_id    = decode_refresh_token_sub(aegis_refresh)   # fast decode, no DB

    async with get_session() as session:
        token_row = await _get_valid_refresh_token(session, token_hash)
        if token_row is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Refresh token invalid or expired")

        user = await _get_user_by_id(session, user_id)
        if not user or not user.is_active:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="User inactive")

        # Revoke old token
        await session.execute(
            sa_update(RefreshTokenModel)
            .where(RefreshTokenModel.id == token_row.id)
            .values(revoked_at=datetime.now(timezone.utc).isoformat())
        )

        # Issue new refresh token
        raw_refresh, refresh_hash_new = create_refresh_token(user_id)
        now = datetime.now(timezone.utc).isoformat()
        expire_at = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
        session.add(RefreshTokenModel(
            id         = str(uuid4()),
            user_id    = user.id,
            token_hash = refresh_hash_new,
            expires_at = expire_at,
            created_at = now,
        ))

    tenant_id    = UUID(user.tenant_id)
    access_token = create_access_token(user_id, tenant_id, user.role, user.email)
    _set_tokens(response, access_token, raw_refresh)

    return {"access_token": access_token, "token_type": "bearer"}


# ---------------------------------------------------------------------------
# POST /auth/logout
# ---------------------------------------------------------------------------

@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    aegis_refresh: Optional[str] = Cookie(default=None),
):
    """Revoke the refresh token and clear auth cookies."""
    if aegis_refresh:
        try:
            from db.connection import get_session, is_db_available
            from sqlalchemy import update as sa_update
            from db.models import RefreshTokenModel

            if is_db_available():
                token_hash = hash_refresh_token(aegis_refresh)
                async with get_session() as session:
                    await session.execute(
                        sa_update(RefreshTokenModel)
                        .where(RefreshTokenModel.token_hash == token_hash)
                        .values(revoked_at=datetime.now(timezone.utc).isoformat())
                    )
        except Exception:   # noqa: BLE001 — best effort
            pass

    _clear_tokens(response)


# ---------------------------------------------------------------------------
# GET /auth/me
# ---------------------------------------------------------------------------

@router.get("/me")
async def me(current_user: CurrentUser = Depends(get_current_user)):
    """Return current user info (works in dev mode too)."""
    if DEV_MODE:
        return {
            "id":           str(current_user.user_id),
            "email":        current_user.email,
            "display_name": "Dev User",
            "role":         current_user.role,
            "tenant": {
                "id":   str(current_user.tenant_id),
                "slug": "default",
                "name": "Default Tenant",
                "plan": "free",
            },
        }

    from db.connection import get_session, is_db_available
    from db.models import TenantModel
    from sqlalchemy import select

    if not is_db_available():
        return {"id": str(current_user.user_id), "email": current_user.email,
                "role": current_user.role, "tenant": None}

    async with get_session() as session:
        user   = await _get_user_by_id(session, current_user.user_id)
        tenant_row = None
        if user:
            result = await session.execute(
                select(TenantModel).where(TenantModel.id == user.tenant_id)
            )
            tenant_row = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="User not found")

    return {
        "id":           user.id,
        "email":        user.email,
        "display_name": user.display_name,
        "role":         user.role,
        "tenant": {
            "id":   tenant_row.id   if tenant_row else user.tenant_id,
            "slug": tenant_row.slug if tenant_row else "",
            "name": tenant_row.name if tenant_row else "",
            "plan": tenant_row.plan if tenant_row else "free",
        } if tenant_row else None,
    }


# ---------------------------------------------------------------------------
# POST /auth/invite
# ---------------------------------------------------------------------------

@router.post("/invite", status_code=status.HTTP_201_CREATED)
async def invite_user(
    body: InviteRequest,
    current_user: CurrentUser = Depends(require_admin),
):
    """Create a one-time invite token for a new team member.

    Returns ``{"invite_url": "/invite/<token>"}`` so the caller can share
    the link.  When SMTP is configured the email is sent automatically
    (implementation deferred to v0.1.1).
    """
    _require_auth_configured()

    from db.connection import get_session, is_db_available
    from db.models import RefreshTokenModel
    from datetime import timedelta
    from uuid import uuid4
    import secrets

    if not is_db_available():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database unavailable")

    async with get_session() as session:
        # Reject duplicate email
        existing = await _get_user_by_email(session, body.email)
        if existing and UUID(existing.tenant_id) == current_user.tenant_id:
            raise HTTPException(status.HTTP_409_CONFLICT, detail="User already in tenant")

        # Store invite as a special refresh_token row (type encoded in a
        # dedicated column added in migration 003).
        raw_token  = secrets.token_urlsafe(32)
        token_hash = hash_refresh_token(raw_token)
        now        = datetime.now(timezone.utc).isoformat()
        expire_at  = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()

        # user_id on the invite row is the inviter (for audit); the
        # meta JSON carries the invitee email, role, and tenant_id.
        session.add(RefreshTokenModel(
            id          = str(uuid4()),
            user_id     = str(current_user.user_id),
            token_hash  = token_hash,
            expires_at  = expire_at,
            created_at  = now,
            meta        = {
                "type":      "invite",
                "email":     body.email.lower(),
                "role":      body.role,
                "tenant_id": str(current_user.tenant_id),
            },
        ))

    return {
        "invite_url": f"/invite/{raw_token}",
        "email":      body.email,
        "role":       body.role,
        "expires_in": "7 days",
    }


# ---------------------------------------------------------------------------
# POST /auth/accept-invite/{token}
# ---------------------------------------------------------------------------

@router.post("/accept-invite/{token}", status_code=status.HTTP_201_CREATED)
async def accept_invite(token: str, body: AcceptInviteRequest, response: Response):
    """Accept an invitation and create the user account."""
    _require_auth_configured()

    from db.connection import get_session, is_db_available
    from db.models import UserModel, RefreshTokenModel, TenantModel
    from sqlalchemy import select, update as sa_update
    from datetime import timedelta
    from uuid import uuid4

    if not is_db_available():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database unavailable")

    token_hash = hash_refresh_token(token)

    async with get_session() as session:
        # Find invite row
        result = await session.execute(
            select(RefreshTokenModel).where(
                RefreshTokenModel.token_hash == token_hash,
                RefreshTokenModel.revoked_at.is_(None),
                RefreshTokenModel.expires_at > datetime.now(timezone.utc).isoformat(),
            )
        )
        invite_row = result.scalar_one_or_none()
        if not invite_row or not isinstance(invite_row.meta, dict):
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Invite not found or expired")
        if invite_row.meta.get("type") != "invite":
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Invite not found or expired")

        email     = invite_row.meta["email"]
        role      = invite_row.meta["role"]
        tenant_id = UUID(invite_row.meta["tenant_id"])

        # Check email not already taken
        existing = await _get_user_by_email(session, email)
        if existing:
            raise HTTPException(status.HTTP_409_CONFLICT, detail="Email already registered")

        # Create user
        now     = datetime.now(timezone.utc).isoformat()
        user_id = uuid4()
        session.add(UserModel(
            id              = str(user_id),
            tenant_id       = str(tenant_id),
            email           = email,
            display_name    = body.display_name or email.split("@")[0],
            hashed_password = hash_password(body.password),
            role            = role,
            is_active       = True,
            created_at      = now,
        ))

        # Revoke invite token
        await session.execute(
            sa_update(RefreshTokenModel)
            .where(RefreshTokenModel.id == invite_row.id)
            .values(revoked_at=now)
        )

        # Issue auth refresh token
        raw_refresh, refresh_hash = create_refresh_token(user_id)
        expire_at = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
        session.add(RefreshTokenModel(
            id         = str(uuid4()),
            user_id    = str(user_id),
            token_hash = refresh_hash,
            expires_at = expire_at,
            created_at = now,
        ))

    access_token = create_access_token(user_id, tenant_id, role, email)
    _set_tokens(response, access_token, raw_refresh)

    return {
        "access_token": access_token,
        "token_type":   "bearer",
        "user": {"id": str(user_id), "email": email, "role": role},
    }


# ---------------------------------------------------------------------------
# PUT /auth/users/{user_id}/role
# ---------------------------------------------------------------------------

@router.put("/users/{user_id}/role")
async def change_role(
    user_id: str,
    body: ChangeRoleRequest,
    current_user: CurrentUser = Depends(require_admin),
):
    """Change a team member's role (admin+ only; only owner can assign owner)."""
    _require_auth_configured()

    from db.connection import get_session, is_db_available
    from db.models import UserModel
    from sqlalchemy import select, update as sa_update

    if not is_db_available():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database unavailable")

    if body.role == "owner" and not current_user.is_owner:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Only an owner can assign the owner role")

    async with get_session() as session:
        result = await session.execute(
            select(UserModel).where(
                UserModel.id == user_id,
                UserModel.tenant_id == str(current_user.tenant_id),
            )
        )
        target = result.scalar_one_or_none()
        if not target:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="User not found")

        # Prevent self-demotion if only owner
        if target.id == str(current_user.user_id) and current_user.role == "owner" and body.role != "owner":
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Cannot remove your own owner role")

        await session.execute(
            sa_update(UserModel)
            .where(UserModel.id == user_id)
            .values(role=body.role)
        )

    return {"user_id": user_id, "role": body.role}


# ---------------------------------------------------------------------------
# DELETE /auth/users/{user_id}
# ---------------------------------------------------------------------------

@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_user(
    user_id: str,
    current_user: CurrentUser = Depends(require_admin),
):
    """Soft-delete a user (sets is_active=False)."""
    _require_auth_configured()

    from db.connection import get_session, is_db_available
    from db.models import UserModel
    from sqlalchemy import select, update as sa_update

    if not is_db_available():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database unavailable")

    if user_id == str(current_user.user_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Cannot deactivate yourself")

    async with get_session() as session:
        result = await session.execute(
            select(UserModel).where(
                UserModel.id == user_id,
                UserModel.tenant_id == str(current_user.tenant_id),
            )
        )
        target = result.scalar_one_or_none()
        if not target:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="User not found")
        if target.role == "owner" and not current_user.is_owner:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Cannot deactivate the tenant owner")

        await session.execute(
            sa_update(UserModel)
            .where(UserModel.id == user_id)
            .values(is_active=False)
        )
