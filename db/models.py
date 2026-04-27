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

Tables (v1.3.0 — FinOps billing)
----------------------------------
model_pricing    — per-model input/output token price rates (USD per 1M tokens)
billing_events   — immutable per-LLM-call cost records (audit trail)
"""

import enum

from sqlalchemy import Boolean, Column, Float, Index, Integer, Numeric, String, Text, JSON, ForeignKeyConstraint, PrimaryKeyConstraint, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase

try:
    from pgvector.sqlalchemy import Vector as _Vector
    _VECTOR_TYPE = _Vector(1536)
except ImportError:  # pgvector not installed; fall back to JSON (no ANN index)
    _Vector = None
    _VECTOR_TYPE = JSON


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
    # v1.1.0 — quota management (added in migration 006)
    token_usage_daily  = Column(Integer, nullable=False, default=0)
    token_budget_daily = Column(Integer, nullable=True)   # NULL = unlimited
    last_usage_reset   = Column(String(10), nullable=True)  # ISO date "YYYY-MM-DD"
    # v1.3.0 — FinOps credit balance (added in migration 007)
    # NULL = unlimited (default for existing tenants); 0.0 = exhausted → 402
    credit_balance = Column(Numeric(12, 6), nullable=True)
    # Running total of all-time API spend in USD (informational)
    total_cost_usd = Column(Numeric(12, 6), nullable=False, default=0)


class UserModel(Base):
    __tablename__ = "users"

    id              = Column(String(36),  primary_key=True)   # UUID string
    tenant_id       = Column(String(36),  nullable=False, index=True)
    email           = Column(String(255), unique=True, nullable=False)
    display_name    = Column(String(255))
    hashed_password = Column(String(255), nullable=False)
    # role: "super_admin" | "owner" | "admin" | "member"
    role            = Column(String(50),  nullable=False, default="member")
    # status: "active" | "pending" | "suspended"
    # New registrations start as "pending" until a super_admin approves them.
    status          = Column(String(20),  nullable=False, default="active")
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


# ===========================================================================
# v1.3.0 — FinOps billing models
# ===========================================================================

class ModelPricingModel(Base):
    """Per-model token pricing rates in USD per 1 million tokens.

    model_id matches the exact string returned by the provider in the
    API response (e.g. 'gpt-4o-2024-08-06', 'claude-sonnet-4-20250514').
    Seeded by migration 007; can be managed via admin API.
    """
    __tablename__ = "model_pricing"

    model_id              = Column(String(128), primary_key=True)
    provider              = Column(String(50),  nullable=False)
    input_price_per_1m    = Column(Numeric(10, 6), nullable=False)   # USD / 1M prompt tokens
    output_price_per_1m   = Column(Numeric(10, 6), nullable=False)   # USD / 1M completion tokens
    is_active             = Column(Boolean,     nullable=False, default=True)
    updated_at            = Column(String(50),  nullable=False)


class BillingEventModel(Base):
    """Immutable per-LLM-call cost record (append-only audit trail).

    One row is written for every successful LLM API response that had
    usage data. cost_usd is calculated at write-time from ModelPricingModel
    (or 0 if no pricing row exists for that model_id).
    """
    __tablename__ = "billing_events"

    id                = Column(Integer,     primary_key=True, autoincrement=True)
    tenant_id         = Column(String(36),  nullable=False, index=True)
    job_id            = Column(String(8),   nullable=True,  index=True)
    model_id          = Column(String(128), nullable=False)
    prompt_tokens     = Column(Integer,     nullable=False, default=0)
    completion_tokens = Column(Integer,     nullable=False, default=0)
    cost_usd          = Column(Numeric(12, 8), nullable=False, default=0)  # actual computed cost
    created_at        = Column(String(50),  nullable=False)


# ===========================================================================
# v2.0.0 — Knowledge Graph (AI Second Brain)
# ===========================================================================

class NodeType(str, enum.Enum):
    document = "document"   # uploaded file / web page
    concept  = "concept"    # extracted key concept
    tag      = "tag"        # classification label
    entity   = "entity"     # named entity (person, org, place)
    solution = "solution"   # linked from SolutionModel


class NodeModel(Base):
    """Knowledge graph node — fundamental unit of the second brain.

    ``embedding`` uses pgvector's Vector(1536) when the extension is
    available; falls back to JSON so the app starts without pgvector.
    """
    __tablename__ = "nodes"
    __table_args__ = (
        Index("ix_nodes_tenant_type", "tenant_id", "node_type"),
        Index("ix_nodes_tenant_hash", "tenant_id", "content_hash"),
    )

    id           = Column(String(36),         primary_key=True)           # UUID
    tenant_id    = Column(String(36),         nullable=False, index=True)
    node_type    = Column(String(50),         nullable=False)              # NodeType values
    title        = Column(String(500),        nullable=False, default="")  # graph display label
    content      = Column(Text,               nullable=True)               # Markdown body for RAG
    node_metadata = Column("metadata", JSON,  nullable=False, default=dict)
    content_hash = Column(String(64),         nullable=True)               # SHA-256 for dedup
    created_at   = Column(String(50),         nullable=False)
    updated_at   = Column(String(50),         nullable=True)
    embedding    = Column(_VECTOR_TYPE,       nullable=True)               # 1536-dim; NULL until embedded


class EdgeModel(Base):
    """Directed relationship between two knowledge graph nodes."""
    __tablename__ = "edges"
    __table_args__ = (
        ForeignKeyConstraint(["source_node_id"], ["nodes.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["target_node_id"], ["nodes.id"], ondelete="CASCADE"),
        Index("ix_edges_source", "source_node_id"),
        Index("ix_edges_target", "target_node_id"),
        Index("ix_edges_tenant", "tenant_id"),
    )

    id                = Column(Integer,        primary_key=True, autoincrement=True)
    tenant_id         = Column(String(36),     nullable=False)
    source_node_id    = Column(String(36),     nullable=False)
    target_node_id    = Column(String(36),     nullable=False)
    relationship_type = Column(String(100),    nullable=False)  # "references", "tagged_by", "related_to", …
    weight            = Column(Numeric(5, 4),  nullable=False, default=1.0)
    edge_metadata     = Column("metadata", JSON, nullable=True)
    created_at        = Column(String(50),     nullable=False)
