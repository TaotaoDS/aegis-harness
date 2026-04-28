"""Resize nodes.embedding from vector(1536) to vector(1024).

Revision ID: 010
Revises: 009
Create Date: 2026-04-28

Rationale
---------
Migration 009 created nodes.embedding as vector(1536) targeting OpenAI's
text-embedding-3-small.  The production embedding backend is now NVIDIA NIM
(nvidia/nv-embedqa-e5-v5) which produces 1024-dimensional vectors.

Steps
-----
1. Drop the IVFFlat index on nodes.embedding (required before ALTER).
2. ALTER the column from vector(1536) → vector(1024).
3. Re-create the IVFFlat ANN index calibrated for 1024 dims.

Any existing NULL embeddings are unaffected.  Non-NULL embeddings from the old
schema are dropped (there are none yet in production; the column was never
successfully populated due to missing OpenAI key).
"""

from alembic import op
import sqlalchemy as sa

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Drop the old IVFFlat index (tied to vector dimension)
    op.execute("DROP INDEX IF EXISTS ix_nodes_embedding")

    # 2. Clear any stale non-NULL embeddings (dimension mismatch would error
    #    on INSERT anyway; better to reset cleanly)
    op.execute("UPDATE nodes SET embedding = NULL WHERE embedding IS NOT NULL")

    # 3. Alter the column to the new dimension
    op.execute("ALTER TABLE nodes ALTER COLUMN embedding TYPE vector(1024) USING NULL")

    # 4. Re-create the IVFFlat index for the new dimension
    #    lists=50 is appropriate for typical knowledge-graph sizes (<50k nodes).
    #    Use vector_cosine_ops to match the <=> cosine-distance queries.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_nodes_embedding "
        "ON nodes USING ivfflat (embedding vector_cosine_ops) WITH (lists = 50)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_nodes_embedding")
    op.execute("UPDATE nodes SET embedding = NULL WHERE embedding IS NOT NULL")
    op.execute("ALTER TABLE nodes ALTER COLUMN embedding TYPE vector(1536) USING NULL")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_nodes_embedding "
        "ON nodes USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )
