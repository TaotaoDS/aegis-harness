# Task ④ — Multi-Tenancy & Permission System: Technical Design

> **Status**: Design only — no business code modified  
> **Author**: AegisHarness Engineering  
> **Date**: 2026-04-24  
> **Target version**: v0.1.0

---

## Table of Contents

1. [Goals & Constraints](#1-goals--constraints)
2. [Authentication Scheme](#2-authentication-scheme)
3. [Tenant & User Data Model](#3-tenant--user-data-model)
4. [Permission Model (RBAC)](#4-permission-model-rbac)
5. [Database Migration Plan](#5-database-migration-plan)
6. [Middleware & Dependency Injection](#6-middleware--dependency-injection)
7. [Settings Scoping](#7-settings-scoping)
8. [API Surface Changes](#8-api-surface-changes)
9. [Frontend Changes](#9-frontend-changes)
10. [Security Hardening](#10-security-hardening)
11. [Backward Compatibility](#11-backward-compatibility)
12. [Implementation Order](#12-implementation-order)
13. [Testing Strategy](#13-testing-strategy)
14. [Open Questions](#14-open-questions)

---

## 1. Goals & Constraints

### Goals

| # | Goal |
|---|------|
| G1 | Multiple independent organisations (tenants) share one deployment; data is strictly isolated |
| G2 | Within a tenant, three roles: **Owner**, **Admin**, **Member** |
| G3 | All existing API endpoints become tenant-scoped with zero behavioural regression for single-tenant users |
| G4 | Zero Blast Radius: 598 existing tests continue to pass throughout implementation |
| G5 | Graceful degradation: the system stays functional in single-tenant mode without auth infrastructure |

### Out of Scope (v0.1.0)

- SSO / SAML / OIDC federation (design for it, implement later)
- Billing / quota enforcement (tenant `plan` column reserved)
- Per-workspace fine-grained ACL (workspace_members table is modelled but not enforced)
- Audit log table (reserved, implementation deferred)

---

## 2. Authentication Scheme

### 2.1 Decision: JWT with Refresh Tokens

**Chosen**: Stateless JWT access tokens + DB-backed refresh tokens.

| Option | Pros | Cons | Decision |
|--------|------|------|----------|
| Session cookie (DB-backed) | Simple revocation, CSRF-friendly | Requires session store; less REST-friendly | Rejected |
| Opaque access tokens | Easy revocation | Requires DB lookup on every request | Rejected |
| **JWT access + DB refresh** | Stateless hot path; revocation via refresh table | Slightly more complex token lifecycle | **Chosen** |
| OAuth2 / OIDC (external IdP) | Enterprise SSO; no password management | Adds external dependency | Deferred to v0.2 |

### 2.2 Token Design

#### Access Token (JWT, RS256 or HS256)

```json
{
  "sub":   "550e8400-e29b-41d4-a716-446655440000",   // user UUID
  "tid":   "f47ac10b-58cc-4372-a567-0e02b2c3d479",   // tenant UUID
  "role":  "admin",                                   // owner | admin | member
  "email": "alice@example.com",
  "exp":   1745500800,                               // 15 minutes from issue
  "iat":   1745499900,
  "type":  "access"
}
```

- **Algorithm**: HS256 (single secret, simpler ops); upgrade path to RS256 for JWKS federation
- **Expiry**: 15 minutes (configurable via `ACCESS_TOKEN_EXPIRE_MINUTES`)
- **No DB lookup** on every request — tenant_id and role are embedded

#### Refresh Token (opaque UUID stored in DB)

```json
{
  "sub":  "550e8400-e29b-41d4-a716-446655440000",
  "jti":  "7c9e6679-7425-40de-944b-e07fc1f90ae7",   // stored as SHA-256 hash in DB
  "exp":  1746104700,                               // 7 days from issue
  "type": "refresh"
}
```

- Stored as `SHA-256(token)` in `refresh_tokens` table (raw token never persisted)
- Revocable by deleting or setting `revoked_at`
- Rotated on every use (refresh returns a new pair; old refresh token is immediately revoked)

### 2.3 Password Security

- **Hashing**: `bcrypt` with cost factor 12 via `passlib[bcrypt]`
- **Min length**: 8 characters (enforced at API + frontend)
- **No plaintext storage** anywhere in pipeline

### 2.4 Token Transport

| Token | Storage | Transport |
|-------|---------|-----------|
| Access token | `httpOnly` cookie (`aegis_access`) OR `Authorization: Bearer` header | Cookie preferred; header accepted for API clients |
| Refresh token | `httpOnly` cookie (`aegis_refresh`) | Cookie only; never exposed to JS |

Cookie attributes: `httpOnly; Secure; SameSite=Lax; Path=/`

Using cookies (not localStorage) eliminates XSS-based token theft.

### 2.5 New Environment Variables

```bash
# ── Auth ──────────────────────────────────────────────────────────────────────
SECRET_KEY=<64-byte random hex>          # JWT signing key — REQUIRED for auth
ACCESS_TOKEN_EXPIRE_MINUTES=15
REFRESH_TOKEN_EXPIRE_DAYS=7

# ── Optional: encrypt stored provider API keys at rest ────────────────────────
ENCRYPTION_KEY=<32-byte random hex>      # Fernet symmetric key

# ── Optional: invite email ────────────────────────────────────────────────────
SMTP_HOST=
SMTP_PORT=587
SMTP_USER=
SMTP_PASSWORD=
EMAIL_FROM=noreply@aegisharness.io
```

---

## 3. Tenant & User Data Model

### 3.1 New Tables

#### `tenants`

```sql
CREATE TABLE tenants (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    slug        VARCHAR(63) UNIQUE NOT NULL,   -- URL-safe: ^[a-z0-9-]{3,63}$
    name        VARCHAR(255) NOT NULL,
    plan        VARCHAR(50)  NOT NULL DEFAULT 'free',  -- free | pro | enterprise
    is_active   BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

`slug` is the stable, human-readable identifier used in workspace URLs
(`/workspaces/acme-corp/...`). `id` (UUID) is used in all FK references.

#### `users`

```sql
CREATE TABLE users (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    email           VARCHAR(255) UNIQUE NOT NULL,
    display_name    VARCHAR(255),
    hashed_password VARCHAR(255) NOT NULL,
    role            VARCHAR(50)  NOT NULL DEFAULT 'member',  -- owner | admin | member
    is_active       BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login_at   TIMESTAMPTZ
);

CREATE INDEX ix_users_tenant_id ON users (tenant_id);
CREATE INDEX ix_users_email     ON users (email);
```

**One user ↔ one tenant** in v0.1.0. Cross-tenant access (consultant accounts) deferred.

#### `refresh_tokens`

```sql
CREATE TABLE refresh_tokens (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash  VARCHAR(64) UNIQUE NOT NULL,   -- SHA-256 hex of raw token
    expires_at  TIMESTAMPTZ NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at  TIMESTAMPTZ                    -- NULL = still valid
);

CREATE INDEX ix_refresh_tokens_user_id    ON refresh_tokens (user_id);
CREATE INDEX ix_refresh_tokens_token_hash ON refresh_tokens (token_hash);
```

A background job (or on-login cleanup) should purge expired rows periodically.

#### `workspaces`

```sql
CREATE TABLE workspaces (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    slug        VARCHAR(255) NOT NULL,          -- matches existing workspace_id strings
    name        VARCHAR(255) NOT NULL,
    created_by  UUID        REFERENCES users(id) ON DELETE SET NULL,
    is_active   BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, slug)
);

CREATE INDEX ix_workspaces_tenant_id ON workspaces (tenant_id);
```

The `slug` column is the value that currently flows through the system as
`workspace_id` (e.g. `"default"`, `"my_project"`). This table formalises
those strings as first-class entities without breaking existing code.

#### `workspace_members` (v0.1.0: modelled, not enforced)

```sql
CREATE TABLE workspace_members (
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    user_id      UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    can_write    BOOLEAN NOT NULL DEFAULT TRUE,
    added_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (workspace_id, user_id)
);
```

In v0.1.0, **all members of a tenant can access all workspaces in that tenant**
(the `workspace_members` table is created but the permission check is skipped).
Per-workspace ACL will be enforced in v0.2.0.

### 3.2 Modified Existing Tables

All changes are **additive** (new nullable columns). Existing rows are backfilled
to a bootstrap "system" tenant during migration.

#### `jobs` — add `tenant_id`, `created_by`

```sql
ALTER TABLE jobs
    ADD COLUMN tenant_id   UUID REFERENCES tenants(id),
    ADD COLUMN created_by  UUID REFERENCES users(id);

-- Backfill: assign to bootstrap tenant
UPDATE jobs SET tenant_id = '<bootstrap-tenant-uuid>' WHERE tenant_id IS NULL;

-- After backfill, enforce NOT NULL
ALTER TABLE jobs ALTER COLUMN tenant_id SET NOT NULL;

CREATE INDEX ix_jobs_tenant_id ON jobs (tenant_id);
```

#### `solutions` — add `tenant_id`

```sql
ALTER TABLE solutions
    ADD COLUMN tenant_id UUID REFERENCES tenants(id);

UPDATE solutions SET tenant_id = '<bootstrap-tenant-uuid>' WHERE tenant_id IS NULL;

ALTER TABLE solutions ALTER COLUMN tenant_id SET NOT NULL;

CREATE INDEX ix_solutions_tenant_id ON solutions (tenant_id);
```

#### `settings` — change PK from `key` to `(tenant_id, key)`

This is the only breaking schema change. The `settings` table currently has
`key` as its sole PK. Multi-tenancy requires that the same key exists for
multiple tenants.

**Migration approach** (three-step, backward-safe):

```sql
-- Step 1: add nullable tenant_id
ALTER TABLE settings ADD COLUMN tenant_id UUID REFERENCES tenants(id);

-- Step 2: backfill
UPDATE settings SET tenant_id = '<bootstrap-tenant-uuid>' WHERE tenant_id IS NULL;

-- Step 3: drop old PK, create composite PK
ALTER TABLE settings DROP CONSTRAINT settings_pkey;
ALTER TABLE settings ADD PRIMARY KEY (tenant_id, key);
```

The `SettingModel` ORM class gains a `tenant_id` column and the PK becomes
composite. `settings_service.py` must be updated to always pass `tenant_id`
(sourced from the request context).

### 3.3 Entity Relationship Diagram

```
tenants ─────────────────────────────────────────┐
  │ 1                                             │
  │                                               │
  ├── N ── users                                  │
  │          │ 1                                  │
  │          └── N ── refresh_tokens              │
  │                                               │
  ├── N ── workspaces ─── N ── workspace_members  │
  │          │ (tenant_id, slug)                  │
  │          │                                    │
  │    (workspace.slug = jobs.workspace_id)        │
  │                                               │
  ├── N ── jobs ─── N ── events                   │
  │          │ ──── 1 ── checkpoints              │
  │                                               │
  ├── N ── solutions                              │
  │                                               │
  └── N ── settings  (PK: tenant_id + key) ───────┘
```

---

## 4. Permission Model (RBAC)

### 4.1 Roles

| Role | Who has it | Description |
|------|-----------|-------------|
| `owner` | Exactly one per tenant (the registrant) | Full control including deleting the tenant, managing billing, transferring ownership |
| `admin` | Appointed by Owner | Manage users (invite/remove/role-change except Owner), manage all workspaces and settings |
| `member` | Default for invited users | Create/run jobs in any tenant workspace; cannot manage users or global settings |

### 4.2 Permission Matrix

| Action | owner | admin | member |
|--------|:-----:|:-----:|:------:|
| View own jobs | ✓ | ✓ | ✓ |
| Create job | ✓ | ✓ | ✓ |
| View all tenant jobs | ✓ | ✓ | ✗ |
| Approve HITL gate (own job) | ✓ | ✓ | ✓ |
| Approve HITL gate (any job) | ✓ | ✓ | ✗ |
| Read settings (profile, ceo_config) | ✓ | ✓ | ✓ |
| Write settings (profile) | ✓ | ✓ | ✓ (own only) |
| Write settings (api_keys, model_config, ceo_config) | ✓ | ✓ | ✗ |
| Manage MCP servers | ✓ | ✓ | ✗ |
| Invite users | ✓ | ✓ | ✗ |
| Remove users | ✓ | ✓ | ✗ |
| Change user role (to admin/member) | ✓ | ✓ | ✗ |
| Change user role (to owner) | ✓ | ✗ | ✗ |
| Delete tenant | ✓ | ✗ | ✗ |

### 4.3 Job Visibility Rule

Members see **only their own jobs**. Admins and Owners see **all jobs in the tenant**.
This is enforced at the repository level:

```python
# In repo: list_jobs(tenant_id, user_id=None, role="member")
# member:  WHERE tenant_id = :tid AND created_by = :uid
# admin/owner: WHERE tenant_id = :tid
```

---

## 5. Database Migration Plan

Three new Alembic revisions, each independently reversible:

### Migration 003 — Auth tables

**File**: `db/migrations/versions/003_add_auth_tables.py`

```
Creates: tenants, users, refresh_tokens
Inserts: one bootstrap tenant (id stored in env/settings for backfill)
```

Downgrade: `DROP TABLE refresh_tokens, users, tenants CASCADE`

### Migration 004 — Workspace formalisation

**File**: `db/migrations/versions/004_add_workspaces.py`

```
Creates: workspaces, workspace_members
Backfills: one workspace row per distinct (tenant_id, workspace_id) pair
           found in jobs and solutions
```

Downgrade: `DROP TABLE workspace_members, workspaces CASCADE`

### Migration 005 — Add tenant_id to existing tables

**File**: `db/migrations/versions/005_tenant_scope_existing_tables.py`

```
Phase A: ADD COLUMN tenant_id UUID (nullable) to jobs, solutions, settings
Phase B: UPDATE ... SET tenant_id = bootstrap_tenant WHERE tenant_id IS NULL
Phase C: ALTER COLUMN tenant_id SET NOT NULL; ADD INDEX
Phase D: ALTER settings PK to (tenant_id, key)
```

The three-phase approach (A → B → C) means the migration is safe to run
against a live database: the backfill happens before the NOT NULL constraint.

Downgrade: remove indexes, restore PK, drop tenant_id columns.

### Why three separate migrations?

Each migration must pass all tests independently. Separating auth tables from
workspace tables from column additions makes rollback surgical and keeps each
revision focused.

---

## 6. Middleware & Dependency Injection

### 6.1 Architecture Choice: FastAPI Dependencies (not ASGI Middleware)

Using FastAPI's `Depends()` system rather than a raw ASGI middleware gives:

- Per-route opt-in (public routes like `/healthz`, `/auth/login` need no token)
- Direct access to the DB session (already managed via `Depends(get_session)`)
- Typed `CurrentUser` objects in route handlers
- Testable — mock the dependency in unit tests

### 6.2 New File: `api/deps.py`

```python
from dataclasses import dataclass
from uuid import UUID
from fastapi import Depends, HTTPException, status, Cookie
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import decode_access_token, TokenPayload
from db.connection import get_session
from db import repository as repo

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


@dataclass(frozen=True)
class CurrentUser:
    user_id:   UUID
    tenant_id: UUID
    role:      str      # "owner" | "admin" | "member"
    email:     str


async def _extract_token(
    bearer: str | None = Depends(oauth2_scheme),
    aegis_access: str | None = Cookie(default=None),
) -> str:
    """Accept token from Authorization header or httpOnly cookie."""
    token = bearer or aegis_access
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    return token


async def get_current_user(
    token: str = Depends(_extract_token),
    session: AsyncSession = Depends(get_session),
) -> CurrentUser:
    payload: TokenPayload = decode_access_token(token)  # raises 401 if expired/invalid
    user = await repo.get_user_by_id(session, payload.sub)
    if user is None or not user["is_active"]:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User inactive or not found")
    return CurrentUser(
        user_id=UUID(user["id"]),
        tenant_id=UUID(user["tenant_id"]),
        role=user["role"],
        email=user["email"],
    )


async def require_admin(
    current_user: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    if current_user.role not in ("owner", "admin"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin role required")
    return current_user


async def require_owner(
    current_user: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    if current_user.role != "owner":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Owner role required")
    return current_user
```

### 6.3 New File: `api/auth.py`

```python
# Responsibilities:
# - create_access_token(user_id, tenant_id, role, email) -> str
# - create_refresh_token(user_id) -> str
# - decode_access_token(token) -> TokenPayload  (raises 401 on failure)
# - verify_refresh_token(token, session) -> UserRow  (checks DB, raises 401)
# - hash_password(plain) -> str
# - verify_password(plain, hashed) -> bool
# - rotate_refresh_token(old_token, session) -> (access_token, refresh_token)

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import os
from uuid import UUID, uuid4

from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import HTTPException, status

SECRET_KEY = os.environ["SECRET_KEY"]
ALGORITHM  = "HS256"
ACCESS_EXPIRE_MINUTES  = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "15"))
REFRESH_EXPIRE_DAYS    = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


@dataclass
class TokenPayload:
    sub:   UUID
    tid:   UUID
    role:  str
    email: str


def create_access_token(user_id: UUID, tenant_id: UUID, role: str, email: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_EXPIRE_MINUTES)
    return jwt.encode(
        {"sub": str(user_id), "tid": str(tenant_id),
         "role": role, "email": email,
         "exp": expire, "type": "access"},
        SECRET_KEY, algorithm=ALGORITHM,
    )


def decode_access_token(token: str) -> TokenPayload:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "access":
            raise ValueError("Wrong token type")
        return TokenPayload(
            sub=UUID(payload["sub"]), tid=UUID(payload["tid"]),
            role=payload["role"],     email=payload["email"],
        )
    except (JWTError, KeyError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")


def hash_refresh_token(raw: str) -> str:
    return sha256(raw.encode()).hexdigest()


def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)
```

### 6.4 Route Protection Pattern

**Before** (current — no auth):
```python
@router.get("/jobs")
async def list_jobs():
    return job_store.list()
```

**After** (with tenant scoping):
```python
from api.deps import get_current_user, CurrentUser

@router.get("/jobs")
async def list_jobs(
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    return await repo.load_jobs_by_tenant(
        session,
        tenant_id=current_user.tenant_id,
        # members only see their own jobs:
        user_id=current_user.user_id if current_user.role == "member" else None,
    )
```

**Setting ownership check** (admin-only write):
```python
@router.put("/settings/{key}")
async def put_setting(
    key: str,
    body: SettingBody,
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    _ADMIN_ONLY_KEYS = {"api_keys", "model_config", "ceo_config", "mcp_servers"}
    if key in _ADMIN_ONLY_KEYS and current_user.role not in ("owner", "admin"):
        raise HTTPException(403, "Admin role required to modify this setting")
    await settings_service.set_setting(key, body.value, tenant_id=current_user.tenant_id)
```

### 6.5 SSE Stream Ownership Check

```python
@router.get("/jobs/{job_id}/stream")
async def stream_job_events(
    job_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    job = await repo.get_job(session, job_id)
    # 404 (not 403) to prevent tenant enumeration
    if job is None or job["tenant_id"] != str(current_user.tenant_id):
        raise HTTPException(404, "Job not found")
    # Members may only stream their own jobs
    if current_user.role == "member" and job["created_by"] != str(current_user.user_id):
        raise HTTPException(404, "Job not found")
    # ... rest of SSE logic unchanged
```

### 6.6 Public Routes (no `Depends(get_current_user)`)

```
GET  /healthz
POST /auth/register
POST /auth/login
POST /auth/refresh
POST /auth/logout          (needs refresh token cookie; not access token)
POST /auth/accept-invite/{token}
```

---

## 7. Settings Scoping

### 7.1 Current vs Target

| Setting key | Current scope | Target scope | Who can write |
|-------------|--------------|--------------|---------------|
| `api_keys` | Global (single row) | Per-tenant | owner, admin |
| `model_config` | Global | Per-tenant | owner, admin |
| `ceo_config` | Global | Per-tenant | owner, admin |
| `mcp_servers` | Global | Per-tenant | owner, admin |
| `user_profile` | Global (one per system) | Per-user (keyed by user_id) | self only |
| `onboarded` | Global | Per-tenant | system (set on first login) |

### 7.2 settings_service.py Signature Changes

```python
# Before:
async def get_setting(key: str) -> Optional[Any]
async def set_setting(key: str, value: Any) -> None

# After:
async def get_setting(key: str, tenant_id: UUID) -> Optional[Any]
async def set_setting(key: str, value: Any, tenant_id: UUID) -> None

# New: per-user profile
async def get_user_profile(user_id: UUID, tenant_id: UUID) -> Optional[UserProfile]
async def set_user_profile(user_id: UUID, tenant_id: UUID, profile: UserProfile) -> None
```

`user_profile` will be stored as key `user_profile:{user_id}` under the tenant
scope, so the existing `settings` table PK `(tenant_id, key)` naturally supports
per-user profiles without a separate table.

### 7.3 API Keys Encryption (Optional, Recommended)

Currently API keys are stored as plaintext JSON. With multiple tenants sharing
one DB, at-rest encryption adds meaningful protection:

```python
from cryptography.fernet import Fernet

_fernet = Fernet(os.environ["ENCRYPTION_KEY"].encode())

def encrypt_api_keys(keys: dict) -> str:
    return _fernet.encrypt(json.dumps(keys).encode()).decode()

def decrypt_api_keys(ciphertext: str) -> dict:
    return json.loads(_fernet.decrypt(ciphertext.encode()))
```

The `value` column in `settings` stores the ciphertext for `api_keys` rows.
The existing masking logic in `settings.py` still applies on read.

---

## 8. API Surface Changes

### 8.1 New Auth Endpoints — `api/routes/auth.py`

```
POST /auth/register
  Body: { email, password, tenant_name }
  → Creates tenant (slug derived from tenant_name), owner user
  → Returns: { access_token }  + sets httpOnly refresh cookie
  → 409 if email already exists

POST /auth/login
  Body: { email, password }
  → Returns: { access_token, user: { id, email, display_name, role, tenant } }
  → Sets httpOnly refresh cookie
  → Updates last_login_at

POST /auth/refresh
  Cookie: aegis_refresh
  → Verifies hash in DB, checks not revoked/expired
  → Rotates: revokes old, issues new pair
  → Returns: { access_token }  + new refresh cookie

POST /auth/logout
  Cookie: aegis_refresh
  → Revokes refresh token (sets revoked_at)
  → Clears cookies
  → 204 No Content

GET /auth/me
  Auth required
  → Returns: { id, email, display_name, role, tenant: { id, slug, name, plan } }

POST /auth/invite
  Auth required (admin+)
  Body: { email, role }
  → Creates a one-time invite token (stored in refresh_tokens with type="invite")
  → Sends email if SMTP configured; otherwise returns token in response (dev mode)

POST /auth/accept-invite/{token}
  Body: { password, display_name }
  → Creates user account, associates with tenant
  → Returns: { access_token }  + sets refresh cookie

PUT /auth/users/{user_id}/role
  Auth required (admin+, owner for owner-role changes)
  Body: { role }
  → Updates user.role
  → 403 if trying to set "owner" without being owner

DELETE /auth/users/{user_id}
  Auth required (admin+)
  → Soft-delete: sets is_active = false
  → Cannot deactivate self or the owner (unless transferring ownership first)
```

### 8.2 Modified Existing Endpoints

| Endpoint | Change |
|----------|--------|
| `GET /jobs` | Add `Depends(get_current_user)`; filter by tenant_id; members see own jobs only |
| `POST /jobs` | Add `Depends(get_current_user)`; set `tenant_id` and `created_by` on new job |
| `GET /jobs/{id}` | Ownership check: tenant match + member own-job rule |
| `GET /jobs/{id}/stream` | Same ownership check |
| `GET /jobs/{id}/events` | Same ownership check |
| `POST /jobs/{id}/approve` | Ownership check |
| `POST /jobs/{id}/answer` | Ownership check |
| `GET /settings` | Scope by `current_user.tenant_id` |
| `GET /settings/{key}` | Scope by tenant + user (for user_profile) |
| `PUT /settings/{key}` | Scope by tenant; admin-only guard for sensitive keys |
| `DELETE /settings/{key}` | Admin-only |
| `GET /mcp/servers` | Scope by tenant_id |
| `POST /mcp/servers` | Scope by tenant_id; admin-only |
| `PUT /mcp/servers/{id}` | Scope by tenant_id; admin-only |
| `DELETE /mcp/servers/{id}` | Scope by tenant_id; admin-only |
| `POST /settings/test_db_connection` | Admin-only |

---

## 9. Frontend Changes

### 9.1 New Pages

```
web/app/login/page.tsx          — Email/password login form
web/app/register/page.tsx       — New tenant + owner account signup
web/app/invite/[token]/page.tsx — Accept invitation, set password
```

### 9.2 New Auth Utilities — `web/lib/auth/`

```
web/lib/auth/
    client.ts     — API call wrappers: login(), logout(), refresh(), getMe()
    context.tsx   — AuthProvider + useAuth() hook
    guards.tsx    — <RequireAuth>, <RequireAdmin> components
```

**`useAuth()` shape**:
```typescript
interface AuthContextValue {
  user:       CurrentUser | null;
  tenant:     Tenant | null;
  loading:    boolean;
  login:      (email: string, password: string) => Promise<void>;
  logout:     () => Promise<void>;
  isAdmin:    boolean;   // role === "owner" || role === "admin"
  isOwner:    boolean;   // role === "owner"
}
```

**Token storage**: Since tokens are in `httpOnly` cookies, the frontend only
stores user metadata in React state (fetched via `GET /auth/me` on mount).
No token ever touches `localStorage`.

### 9.3 Providers.tsx Update

```tsx
// Before:
export function Providers({ children }: { children: React.ReactNode }) {
  return <LocaleProvider>{children}</LocaleProvider>;
}

// After:
export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <LocaleProvider>
      <AuthProvider>{children}</AuthProvider>
    </LocaleProvider>
  );
}
```

### 9.4 Shell.tsx Route Guard

```tsx
// Current: only splits onboarding vs. app layout
// Addition: if no auth session, redirect to /login
// (except /login, /register, /invite/* which are public)

const PUBLIC_PATHS = ["/login", "/register", "/invite"];

export function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && !user && !PUBLIC_PATHS.some(p => pathname.startsWith(p))) {
      router.replace(`/login?next=${encodeURIComponent(pathname)}`);
    }
  }, [user, loading, pathname, router]);

  if (pathname.startsWith("/onboarding")) { /* fullscreen */ }
  if (PUBLIC_PATHS.some(p => pathname.startsWith(p))) { /* centered card */ }
  return <SidebarLayout>{children}</SidebarLayout>;
}
```

### 9.5 API Proxy Update

`web/app/api/proxy/[...path]/route.ts` must forward the browser's cookies to
the backend (they are httpOnly — Next.js server route handlers can read and
forward them):

```typescript
// Add to each proxy handler:
const cookieHeader = request.headers.get("cookie") ?? "";
const response = await fetch(backendUrl, {
  ...options,
  headers: { ...options.headers, cookie: cookieHeader },
});
// Forward Set-Cookie from backend to browser:
const setCookie = response.headers.get("set-cookie");
if (setCookie) {
  nextResponse.headers.set("set-cookie", setCookie);
}
```

### 9.6 i18n Keys to Add

```typescript
// New keys needed in zh.ts and en.ts:
auth: {
  loginTitle, loginSubtitle,
  registerTitle, registerSubtitle,
  emailLabel, passwordLabel, tenantNameLabel, displayNameLabel,
  loginBtn, registerBtn, logoutBtn,
  loginError, registerError,
  inviteTitle, acceptInviteBtn,
  usersTab, inviteUserBtn, roleLabel, removeUserBtn,
  roleMember, roleAdmin, roleOwner,
}
```

---

## 10. Security Hardening

### 10.1 Rate Limiting

Add `slowapi` (wraps `limits`) to FastAPI:

```python
# api/main.py additions:
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# In auth routes:
@router.post("/auth/login")
@limiter.limit("10/minute")
async def login(request: Request, ...): ...

@router.post("/auth/register")
@limiter.limit("5/hour")
async def register(request: Request, ...): ...
```

### 10.2 CORS Update

```python
# Expand allow_origins to support production domain:
allow_origins=[
    "http://localhost:3000",
    os.getenv("FRONTEND_ORIGIN", ""),  # e.g. "https://app.aegisharness.io"
]
```

### 10.3 Tenant Enumeration Prevention

- Job/workspace not-found responses always return 404 (never 403) for
  cross-tenant access attempts — prevents confirming whether a resource exists.
- User lookup by email in login: use constant-time comparison; return generic
  error ("Invalid email or password") regardless of which field is wrong.

### 10.4 Existing API Key Masking

The current `_mask_api_keys()` function continues to apply. With encryption
added, the decrypt-then-mask flow is:
```
DB ciphertext → decrypt (server-side) → mask (for response) → send to client
```
The plaintext key never leaves the server.

---

## 11. Backward Compatibility

### 11.1 Single-Tenant / Dev Mode

When `SECRET_KEY` is **not set** in the environment:
- Auth middleware is bypassed entirely (same as today)
- All requests behave as if they belong to a synthetic bootstrap tenant
- The `get_current_user` dependency returns a hardcoded `CurrentUser` with
  `role="owner"` — no DB lookup performed
- Suitable for local development and the existing test suite

This preserves the Zero Blast Radius principle: **all 598 existing tests pass
without modification** because they don't set `SECRET_KEY`.

### 11.2 Bootstrap Tenant

Migration 003 inserts one row into `tenants`:

```sql
INSERT INTO tenants (id, slug, name, plan)
VALUES ('<fixed-uuid>', 'default', 'Default Tenant', 'free');
```

The UUID is deterministic (written into the migration file) so migrations are
reproducible. All backfilled rows in `jobs`, `solutions`, `settings` point to
this tenant.

The first user to run `/auth/register` after migration creates a **new** tenant.
The bootstrap tenant is only used for pre-existing data.

### 11.3 Onboarding Wizard

The current `/onboarding` flow configures the system without an account.
Post-migration:

1. `/onboarding` stays accessible without auth (still used for initial system setup)
2. On the final "Done" step, a "Create Account" form appears (creates owner + tenant)
3. If account already exists, the step shows "Log in" instead
4. `onboarded` setting is scoped to the tenant; the onboarding check on the
   dashboard (`GET /settings/onboarded`) passes `tenant_id` from the request

---

## 12. Implementation Order

Split into four atomic sprints, each mergeable independently:

### Sprint A — Auth Foundation (no route changes)

Files to create/modify:
- `api/auth.py` — token utilities, password hashing
- `api/deps.py` — `CurrentUser`, dependency functions
- `api/routes/auth.py` — `/auth/*` endpoints
- `db/migrations/versions/003_add_auth_tables.py`
- New tests: `core_orchestrator/tests/test_auth.py`

**Done when**: `POST /auth/register` + `POST /auth/login` + `GET /auth/me` work;
existing tests still pass.

### Sprint B — DB Schema Migration

Files to create/modify:
- `db/models.py` — add new ORM models + modified columns
- `db/repository.py` — add tenant-scoped query variants (additive, not replacing)
- `db/migrations/versions/004_add_workspaces.py`
- `db/migrations/versions/005_tenant_scope_existing_tables.py`

**Done when**: `alembic upgrade head` completes cleanly on a fresh and on an
existing DB; all existing repo tests still pass.

### Sprint C — API Route Protection

Files to modify (add `Depends(get_current_user)` and `tenant_id` filtering):
- `api/routes/jobs.py`
- `api/routes/stream.py`
- `api/routes/approvals.py`
- `api/routes/interview.py`
- `api/routes/settings.py` + `api/settings_service.py`
- `api/routes/mcp.py`
- `api/main.py` — register auth router

**Done when**: authenticated requests work end-to-end; `SECRET_KEY` unset still
bypasses auth (dev mode); new integration tests cover the permission matrix.

### Sprint D — Frontend Auth

Files to create/modify:
- `web/lib/auth/client.ts`, `context.tsx`, `guards.tsx`
- `web/components/Providers.tsx`
- `web/components/Shell.tsx`
- `web/app/login/page.tsx`
- `web/app/register/page.tsx`
- `web/app/api/proxy/[...path]/route.ts` (cookie forwarding)
- `web/lib/i18n/zh.ts` + `en.ts` (auth keys)

**Done when**: browser login flow works end-to-end; unauthenticated browser
redirects to `/login`; all existing E2E flows work when logged in.

---

## 13. Testing Strategy

### Unit Tests (core_orchestrator/tests/)

| New test file | What it covers |
|---------------|---------------|
| `test_auth.py` | `create_access_token`, `decode_access_token` (valid/expired/tampered), `hash_password`/`verify_password`, `hash_refresh_token` |
| `test_deps.py` | `get_current_user` with valid token, expired token, missing token, inactive user; `require_admin` rejects members |
| `test_auth_routes.py` | Register flow (happy path, duplicate email, weak password), login (wrong password, inactive user), refresh (rotation, revoked token), logout |

### Integration Tests

- Tenant isolation: create two tenants, verify job from tenant A is not visible
  to tenant B's member
- Permission matrix: parametrised test hitting all rows in the matrix table
  in §4.2
- SSE stream auth: unauthenticated request returns 401; cross-tenant job_id
  returns 404

### Regression Guard

```bash
# Must pass throughout all sprints:
python -m pytest core_orchestrator/tests/ -v
# Target: 598 + (new tests) passing, 0 failing
```

### Test Fixture Pattern

```python
# conftest.py additions:
@pytest.fixture
def bootstrap_tenant() -> dict:
    return {"id": BOOTSTRAP_TENANT_ID, "slug": "default", ...}

@pytest.fixture
def owner_user(bootstrap_tenant) -> dict:
    return {"id": uuid4(), "tenant_id": bootstrap_tenant["id"], "role": "owner", ...}

@pytest.fixture
def member_user(bootstrap_tenant) -> dict:
    return {"id": uuid4(), "tenant_id": bootstrap_tenant["id"], "role": "member", ...}

@pytest.fixture
def override_current_user(app, owner_user):
    """FastAPI dependency override for tests."""
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(**owner_user)
    yield
    app.dependency_overrides.clear()
```

---

## 14. Open Questions

| # | Question | Recommended Default |
|---|----------|-------------------|
| Q1 | Should API keys be **per-tenant** (all members share one OpenAI key) or **per-user** (each user supplies their own)? | Per-tenant (current behaviour preserved; simpler billing) |
| Q2 | Should `workspace_id` strings in existing jobs/solutions be automatically migrated to `workspaces.slug` rows? | Yes — Migration 004 backfills one workspace row per distinct `(tenant_id, workspace_id)` pair |
| Q3 | Invite flow: send email, or just return the invite URL in the API response? | Return URL in response (dev-friendly); add SMTP sending later behind `SMTP_HOST` env check |
| Q4 | Should the onboarding wizard be removed post-auth, or kept as an admin-only "system setup" page? | Keep as admin-only; redirect non-admins who land on it to `/settings` |
| Q5 | Token storage: `httpOnly` cookie vs `Authorization` header for the SPA? | Cookie (safer against XSS); proxy route already exists to forward cookies server-side |
| Q6 | Should we enforce workspace_members ACL in v0.1.0 or keep all-tenant-members-access? | All-tenant-members-access in v0.1.0; workspace_members table created but not enforced |
| Q7 | PostgreSQL Row-Level Security (RLS) as defence-in-depth on top of app-level filtering? | Desirable; schedule as a hardening task after Sprint C is stable |

---

## Appendix A — New Python Dependencies

```
# requirements.txt additions:
python-jose[cryptography]>=3.3.0   # JWT encode/decode
passlib[bcrypt]>=1.7.4             # Password hashing
cryptography>=42.0                 # Fernet for API key encryption
slowapi>=0.1.9                     # Rate limiting (optional, recommended)
```

## Appendix B — New npm Dependencies

```
# web/package.json additions:
# None required — auth calls use the existing fetch-based proxy;
# React context is already available in Next.js 14
```

## Appendix C — File Change Summary

### New files

```
api/auth.py
api/deps.py
api/routes/auth.py
db/migrations/versions/003_add_auth_tables.py
db/migrations/versions/004_add_workspaces.py
db/migrations/versions/005_tenant_scope_existing_tables.py
core_orchestrator/tests/test_auth.py
core_orchestrator/tests/test_deps.py
core_orchestrator/tests/test_auth_routes.py
web/lib/auth/client.ts
web/lib/auth/context.tsx
web/lib/auth/guards.tsx
web/app/login/page.tsx
web/app/register/page.tsx
web/app/invite/[token]/page.tsx
docs/task4_design.md   ← this file
```

### Modified files

```
db/models.py             — add TenantModel, UserModel, RefreshTokenModel,
                           WorkspaceModel, WorkspaceMemberModel;
                           add tenant_id/created_by to JobModel, SolutionModel;
                           change SettingModel PK to (tenant_id, key)
db/repository.py         — add tenant-scoped variants of list_jobs,
                           get_user_by_id, get_user_by_email, etc.
api/main.py              — register auth router; optional rate limit middleware
api/routes/jobs.py       — add Depends(get_current_user), tenant filtering
api/routes/stream.py     — add ownership check
api/routes/approvals.py  — add ownership check
api/routes/interview.py  — add ownership check
api/routes/settings.py   — add tenant scoping, admin-only guards
api/routes/mcp.py        — add tenant scoping, admin-only guards
api/settings_service.py  — add tenant_id parameter to all functions
web/components/Providers.tsx     — wrap with AuthProvider
web/components/Shell.tsx         — add unauthenticated redirect
web/app/api/proxy/[...path]/route.ts — forward cookies backend↔browser
web/lib/i18n/zh.ts       — add auth.* keys
web/lib/i18n/en.ts       — add auth.* keys
.env.example             — document SECRET_KEY, ENCRYPTION_KEY, SMTP_*
requirements.txt         — add python-jose, passlib, cryptography, slowapi
```
