"""FastAPI dependency functions for authentication and authorisation.

Usage
-----
In any route that requires an authenticated user::

    from api.deps import get_current_user, CurrentUser

    @router.get("/jobs")
    async def list_jobs(current_user: CurrentUser = Depends(get_current_user)):
        ...

For admin-only endpoints::

    @router.put("/settings/{key}")
    async def put_setting(
        key: str,
        current_user: CurrentUser = Depends(require_admin),
    ):
        ...

Dev mode
--------
When ``SECRET_KEY`` is absent from the environment, ``get_current_user``
returns a synthetic owner that belongs to the bootstrap tenant.  This means
the entire existing test suite passes without any modification — no tokens,
no DB user rows needed.

The bootstrap tenant UUID is the same constant used in migrations 003/005 so
backfilled rows are already associated with it.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from fastapi import Cookie, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from api.auth import DEV_MODE, TokenPayload, decode_access_token

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Fixed UUID used for the bootstrap tenant (matches migration 003 INSERT).
BOOTSTRAP_TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")
BOOTSTRAP_USER_ID   = UUID("00000000-0000-0000-0000-000000000002")

# auto_error=False so we can also accept a cookie without FastAPI raising 401
# before we get a chance to check the cookie.
_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


# ---------------------------------------------------------------------------
# CurrentUser dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CurrentUser:
    user_id:   UUID
    tenant_id: UUID
    role:      str      # "super_admin" | "owner" | "admin" | "member"
    email:     str
    status:    str = "active"  # "active" | "pending" | "suspended"

    @property
    def is_super_admin(self) -> bool:
        return self.role == "super_admin"

    @property
    def is_admin(self) -> bool:
        return self.role in ("super_admin", "owner", "admin")

    @property
    def is_owner(self) -> bool:
        return self.role in ("super_admin", "owner")

    @property
    def is_active(self) -> bool:
        return self.status == "active"


# ---------------------------------------------------------------------------
# Dev-mode synthetic user (returned when SECRET_KEY is unset)
# ---------------------------------------------------------------------------

_DEV_USER = CurrentUser(
    user_id=BOOTSTRAP_USER_ID,
    tenant_id=BOOTSTRAP_TENANT_ID,
    role="super_admin",
    email="dev@localhost",
    status="active",
)


# ---------------------------------------------------------------------------
# Token extraction helper
# ---------------------------------------------------------------------------

async def _extract_token(
    bearer: str | None = Depends(_oauth2_scheme),
    aegis_access: str | None = Cookie(default=None),
) -> str | None:
    """Return the raw JWT from either the Authorization header or the cookie."""
    return bearer or aegis_access


# ---------------------------------------------------------------------------
# Core dependency: get_current_user
# ---------------------------------------------------------------------------

async def get_current_user(
    token: str | None = Depends(_extract_token),
) -> CurrentUser:
    """Resolve the current authenticated user.

    In dev mode (``SECRET_KEY`` unset) returns the synthetic bootstrap owner
    without any token validation.

    In production mode validates the JWT and returns a ``CurrentUser`` built
    directly from the token payload — no DB round-trip on the hot path.
    A DB lookup is only needed for user-deactivation checks; those are done
    lazily in ``require_active_user`` when strict enforcement is needed.
    """
    if DEV_MODE:
        return _DEV_USER

    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    payload: TokenPayload = decode_access_token(token)   # raises 401 on failure
    return CurrentUser(
        user_id=payload.sub,
        tenant_id=payload.tid,
        role=payload.role,
        email=payload.email,
        status=payload.status,
    )


# ---------------------------------------------------------------------------
# Role-gating dependencies
# ---------------------------------------------------------------------------

async def require_admin(
    current_user: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    """Raise 403 unless the user has admin or owner role."""
    if not current_user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Admin role required")
    return current_user


async def require_owner(
    current_user: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    """Raise 403 unless the user has owner or super_admin role."""
    if not current_user.is_owner:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Owner role required")
    return current_user


async def require_super_admin(
    current_user: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    """Raise 403 unless the user has the super_admin role."""
    if not current_user.is_super_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Super admin role required")
    return current_user


async def require_active(
    current_user: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    """Raise 403 if the user's account is not yet approved (status != 'active')."""
    if not current_user.is_active:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Account pending approval — please wait for an administrator to activate your account",
        )
    return current_user
