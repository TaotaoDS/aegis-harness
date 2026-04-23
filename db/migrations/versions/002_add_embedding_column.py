"""Add embedding column to solutions table.

Revision ID: 002
Revises: 001
Create Date: 2026-04-23

Adds a JSONB ``embedding`` column to store 1536-dimensional OpenAI
text-embedding-3-small vectors.  JSONB is used (instead of pgvector's
``vector`` type) to avoid requiring the pgvector PostgreSQL extension at
migration time — the application computes cosine similarity in Python.

To switch to a native pgvector column once the extension is available::

    ALTER TABLE solutions
        ADD COLUMN embedding_v2 vector(1536)
        GENERATED ALWAYS AS (embedding::vector(1536)) STORED;

    -- then create the IVFFlat index:
    CREATE INDEX ON solutions USING ivfflat (embedding_v2 vector_cosine_ops)
    WITH (lists = 100);
"""

from alembic import op
import sqlalchemy as sa


revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "solutions",
        sa.Column("embedding", sa.JSON, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("solutions", "embedding")
