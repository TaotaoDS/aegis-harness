"""Knowledge graph tables: nodes and edges.

Revision ID: 009
Revises: 008
Create Date: 2026-04-27

Changes
-------
1. Enable pgvector extension (CREATE EXTENSION IF NOT EXISTS vector).
2. Create ``nodes`` table:
   - id, tenant_id, node_type, title, content, metadata (JSONB),
     content_hash (SHA-256 for dedup), created_at, updated_at,
     embedding vector(1536).
   - Composite indexes on (tenant_id, node_type) and (tenant_id, content_hash).
   - IVFFlat ANN index on embedding for cosine similarity search.
3. Create ``edges`` table:
   - id, tenant_id, source_node_id → nodes.id (CASCADE),
     target_node_id → nodes.id (CASCADE), relationship_type, weight,
     metadata (JSONB), created_at.
   - Indexes on tenant_id, source_node_id, target_node_id.
"""

from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa

try:
    from pgvector.sqlalchemy import Vector
    _HAS_PGVECTOR = True
except ImportError:
    _HAS_PGVECTOR = False

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. pgvector extension ─────────────────────────────────────────────────
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ── 2. nodes ──────────────────────────────────────────────────────────────
    embedding_col = (
        sa.Column("embedding", Vector(1536), nullable=True)
        if _HAS_PGVECTOR
        else sa.Column("embedding", sa.JSON, nullable=True)
    )

    op.create_table(
        "nodes",
        sa.Column("id",           sa.String(36),  primary_key=True),
        sa.Column("tenant_id",    sa.String(36),  nullable=False),
        sa.Column("node_type",    sa.String(50),  nullable=False),
        sa.Column("title",        sa.String(500), nullable=False, server_default=""),
        sa.Column("content",      sa.Text,        nullable=True),
        sa.Column("metadata",     sa.JSON,        nullable=False, server_default="{}"),
        sa.Column("content_hash", sa.String(64),  nullable=True),
        sa.Column("created_at",   sa.String(50),  nullable=False),
        sa.Column("updated_at",   sa.String(50),  nullable=True),
        embedding_col,
    )

    op.create_index("ix_nodes_tenant_id",   "nodes", ["tenant_id"])
    op.create_index("ix_nodes_tenant_type", "nodes", ["tenant_id", "node_type"])
    op.create_index("ix_nodes_tenant_hash", "nodes", ["tenant_id", "content_hash"])

    # IVFFlat ANN index — only useful once rows exist; safe to create empty.
    # lists=100 is a good default for up to ~1M vectors; tune later.
    if _HAS_PGVECTOR:
        op.execute(
            "CREATE INDEX ix_nodes_embedding ON nodes "
            "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
        )

    # ── 3. edges ──────────────────────────────────────────────────────────────
    op.create_table(
        "edges",
        sa.Column("id",                sa.Integer,      primary_key=True, autoincrement=True),
        sa.Column("tenant_id",         sa.String(36),   nullable=False),
        sa.Column("source_node_id",    sa.String(36),   nullable=False),
        sa.Column("target_node_id",    sa.String(36),   nullable=False),
        sa.Column("relationship_type", sa.String(100),  nullable=False),
        sa.Column("weight",            sa.Numeric(5, 4), nullable=False, server_default="1.0"),
        sa.Column("metadata",          sa.JSON,          nullable=True),
        sa.Column("created_at",        sa.String(50),    nullable=False),
        sa.ForeignKeyConstraint(["source_node_id"], ["nodes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_node_id"], ["nodes.id"], ondelete="CASCADE"),
    )

    op.create_index("ix_edges_tenant",  "edges", ["tenant_id"])
    op.create_index("ix_edges_source",  "edges", ["source_node_id"])
    op.create_index("ix_edges_target",  "edges", ["target_node_id"])


def downgrade() -> None:
    op.drop_index("ix_edges_target",  table_name="edges")
    op.drop_index("ix_edges_source",  table_name="edges")
    op.drop_index("ix_edges_tenant",  table_name="edges")
    op.drop_table("edges")

    if _HAS_PGVECTOR:
        op.execute("DROP INDEX IF EXISTS ix_nodes_embedding")
    op.drop_index("ix_nodes_tenant_hash", table_name="nodes")
    op.drop_index("ix_nodes_tenant_type", table_name="nodes")
    op.drop_index("ix_nodes_tenant_id",   table_name="nodes")
    op.drop_table("nodes")
    # Leave the vector extension in place — other tables may use it.
