"""SQLAlchemy ORM models.

Tables (original)
-----------------
jobs         — job metadata + status
events       — SSE event log (append-only)
checkpoints  — pipeline phase checkpoints (upsert)
solutions    — workspace-scoped lessons (SolutionStore backing)
settings     — global key/JSONB settings store

Tables (v0.1.0 — multi-tenancy)
---------------------------------
tenants          — organisations (one row per company / team)
users            — user accounts (scoped to a tenant)
refresh_tokens   — refresh-token store + invite tokens
workspaces       — formalised workspace rows (slug matches legacy workspace_id)
workspace_members — fine-grained workspace ACL (enforced in v0.2.0)
"""

from sqlalchemy import Boolean, Column, Integer, String, Text, JSON, PrimaryKeyConstraint
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class JobModel(Base):
    __tablename__ = "jobs"

    id           = Column(String(8),   primary_key=True)
    type         = Column(String(50),  nullable=False)
    workspace_id = Column(String(255), nullable=False)
    requirement  = Column(Text,        nullable=False)
    status       = Column(String(50),  nullable=False, default="pending")
    created_at   = Column(String(50),  nullable=False)
    updated_at   = Column(String(50))
    meta         = Column(JSON,        default=dict)
    # v0.1.0 — multi-tenancy (nullable for backward compat; backfilled in migration 005)
    tenant_id    = Column(String(36))
    created_by   = Column(String(36))


class EventModel(Base):
    __tablename__ = "events"

    id        = Column(Integer,      primary_key=True, autoincrement=True)
    job_id    = Column(String(8),    nullable=False, index=True)
    seq       = Column(Integer,      nullable=False)
    type      = Column(String(100),  nullable=False)
    label     = Column(Text)
    data      = Column(JSON,         default=dict)
    timestamp = Column(String(50),   nullable=False)


class CheckpointModel(Base):
    __tablename__ = "checkpoints"

    job_id               = Column(String(8),  primary_key=True)
    phase                = Column(String(50), nullable=False)
    completed_tasks      = Column(JSON,       default=list)   # List[str]
    current_task_index   = Column(Integer,    default=0)
    data                 = Column(JSON,       default=dict)   # arbitrary phase data
    updated_at           = Column(String(50), nullable=False)


class SolutionModel(Base):
    __tablename__ = "solutions"

    id           = Column(String(8),   primary_key=True)
    workspace_id = Column(String(255), nullable=False, index=True)
    # v0.1.0 — multi-tenancy (nullable for backward compat; backfilled in migration 005)
    tenant_id    = Column(String(36))
    type         = Column(String(50))
    problem      = Column(Text,        nullable=False)
    solution     = Column(Text,        nullable=False)
    context      = Column(Text)
    tags         = Column(JSON,        default=list)
    job_id       = Column(String(50))
    timestamp    = Column(String(50))
    # Embedding stored as a JSON array of 1536 floats (text-embedding-3-small).
    # Added in Week 4 (M1 pgvector phase) via migration 002_add_embedding_column.
    embedding    = Column(JSON,        nullable=True)


class SettingModel(Base):
    """Global + tenant-scoped settings store.

    After migration 005 the PK is ``(tenant_id, key)``.
    ``tenant_id`` defaults to the bootstrap tenant UUID for backward
    compatibility with pre-multitenancy data.
    """
    __tablename__ = "settings"
    __table_args__ = (
        PrimaryKeyConstraint("tenant_id", "key", name="settings_pkey"),
    )

    # tenant_id defaults to the bootstrap tenant in repository helpers
    tenant_id  = Column(String(36),  nullable=False)
    key        = Column(String(255), nullable=False)
    value      = Column(JSON,        nullable=False)
    updated_at = Column(String(50),  nullable=False)


# ===========================================================================
# v0.1.0 — Multi-tenancy models
# ===========================================================================

class TenantModel(Base):
    __tablename__ = "tenants"

    id         = Column(String(36),  primary_key=True)   # UUID string
    slug       = Column(String(63),  unique=True, nullable=False)
    name       = Column(String(255), nullable=False)
    plan       = Column(String(50),  nullable=False, default="free")
    is_active  = Column(Boolean,     nullable=False, default=True)
    created_at = Column(String(50),  nullable=False)


class UserModel(Base):
    __tablename__ = "users"

    id              = Column(String(36),  primary_key=True)   # UUID string
    tenant_id       = Column(String(36),  nullable=False, index=True)
    email           = Column(String(255), unique=True, nullable=False)
    display_name    = Column(String(255))
    hashed_password = Column(String(255), nullable=False)
    role            = Column(String(50),  nullable=False, default="member")
    is_active       = Column(Boolean,     nullable=False, default=True)
    created_at      = Column(String(50),  nullable=False)
    last_login_at   = Column(String(50))


class RefreshTokenModel(Base):
    """Stores refresh-token hashes and one-time invite tokens.

    ``meta`` carries extra context for invite rows::

        {"type": "invite", "email": "...", "role": "member", "tenant_id": "..."}

    Regular refresh tokens have ``meta = None``.
    """
    __tablename__ = "refresh_tokens"

    id          = Column(String(36),  primary_key=True)   # UUID string
    user_id     = Column(String(36),  nullable=False, index=True)
    token_hash  = Column(String(64),  unique=True, nullable=False)
    expires_at  = Column(String(50),  nullable=False)
    created_at  = Column(String(50),  nullable=False)
    revoked_at  = Column(String(50))                       # NULL = valid
    meta        = Column(JSON)                             # invite metadata


class WorkspaceModel(Base):
    __tablename__ = "workspaces"

    id         = Column(String(36),  primary_key=True)   # UUID string
    tenant_id  = Column(String(36),  nullable=False, index=True)
    slug       = Column(String(255), nullable=False)      # matches legacy workspace_id
    name       = Column(String(255), nullable=False)
    created_by = Column(String(36))                        # user UUID (nullable)
    is_active  = Column(Boolean,     nullable=False, default=True)
    created_at = Column(String(50),  nullable=False)


class WorkspaceMemberModel(Base):
    """Fine-grained workspace ACL.  Modelled now; enforced in v0.2.0."""
    __tablename__ = "workspace_members"

    workspace_id = Column(String(36), primary_key=True)
    user_id      = Column(String(36), primary_key=True)
    can_write    = Column(Boolean,    nullable=False, default=True)
    added_at     = Column(String(50), nullable=False)
