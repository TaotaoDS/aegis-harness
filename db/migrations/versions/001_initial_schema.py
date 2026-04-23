"""Initial schema — jobs, events, checkpoints, solutions, settings.

Revision ID: 001
Revises:
Create Date: 2026-04-22
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # jobs
    # ------------------------------------------------------------------
    op.create_table(
        "jobs",
        sa.Column("id",           sa.String(8),   primary_key=True),
        sa.Column("type",         sa.String(50),  nullable=False),
        sa.Column("workspace_id", sa.String(255), nullable=False),
        sa.Column("requirement",  sa.Text(),       nullable=False),
        sa.Column("status",       sa.String(50),  nullable=False, server_default="pending"),
        sa.Column("created_at",   sa.String(50),  nullable=False),
        sa.Column("updated_at",   sa.String(50)),
        sa.Column("meta",         sa.JSON(),       server_default="{}"),
    )

    # ------------------------------------------------------------------
    # events  (append-only SSE log)
    # ------------------------------------------------------------------
    op.create_table(
        "events",
        sa.Column("id",        sa.Integer(),    primary_key=True, autoincrement=True),
        sa.Column("job_id",    sa.String(8),    nullable=False, index=True),
        sa.Column("seq",       sa.Integer(),    nullable=False),
        sa.Column("type",      sa.String(100),  nullable=False),
        sa.Column("label",     sa.Text()),
        sa.Column("data",      sa.JSON(),       server_default="{}"),
        sa.Column("timestamp", sa.String(50),   nullable=False),
    )
    op.create_index("ix_events_job_id", "events", ["job_id"])

    # ------------------------------------------------------------------
    # checkpoints  (upserted at each pipeline phase boundary)
    # ------------------------------------------------------------------
    op.create_table(
        "checkpoints",
        sa.Column("job_id",               sa.String(8),  primary_key=True),
        sa.Column("phase",                sa.String(50), nullable=False),
        sa.Column("completed_tasks",      sa.JSON(),     server_default="[]"),
        sa.Column("current_task_index",   sa.Integer(),  server_default="0"),
        sa.Column("data",                 sa.JSON(),     server_default="{}"),
        sa.Column("updated_at",           sa.String(50), nullable=False),
    )

    # ------------------------------------------------------------------
    # solutions  (workspace-scoped compound-learning store)
    # ------------------------------------------------------------------
    op.create_table(
        "solutions",
        sa.Column("id",           sa.String(8),   primary_key=True),
        sa.Column("workspace_id", sa.String(255), nullable=False, index=True),
        sa.Column("type",         sa.String(50)),
        sa.Column("problem",      sa.Text(),       nullable=False),
        sa.Column("solution",     sa.Text(),       nullable=False),
        sa.Column("context",      sa.Text()),
        sa.Column("tags",         sa.JSON(),       server_default="[]"),
        sa.Column("job_id",       sa.String(50)),
        sa.Column("timestamp",    sa.String(50)),
        # NOTE: embedding vector(1536) added in Week-4 pgvector migration
    )
    op.create_index("ix_solutions_workspace_id", "solutions", ["workspace_id"])

    # ------------------------------------------------------------------
    # settings  (global JSON key/value store)
    # ------------------------------------------------------------------
    op.create_table(
        "settings",
        sa.Column("key",        sa.String(255), primary_key=True),
        sa.Column("value",      sa.JSON(),       nullable=False),
        sa.Column("updated_at", sa.String(50),   nullable=False),
    )


def downgrade() -> None:
    op.drop_table("settings")
    op.drop_index("ix_solutions_workspace_id", table_name="solutions")
    op.drop_table("solutions")
    op.drop_table("checkpoints")
    op.drop_index("ix_events_job_id", table_name="events")
    op.drop_table("events")
    op.drop_table("jobs")
