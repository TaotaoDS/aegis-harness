"""Add workspace tables: workspaces, workspace_members.

Revision ID: 004
Revises: 003
Create Date: 2026-04-24

Backfills one ``workspaces`` row for every distinct ``workspace_id`` value
found in the ``jobs`` and ``solutions`` tables, scoped to the bootstrap
tenant.  This means every job created before multi-tenancy was introduced
will have a matching ``workspaces`` row, preserving referential integrity
when migration 005 adds the FK.

``workspace_members`` is created but not populated — fine-grained ACL is
enforced in v0.2.0.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

BOOTSTRAP_TENANT_ID = "00000000-0000-0000-0000-000000000001"


def upgrade() -> None:
    # ------------------------------------------------------------------
    # workspaces
    # ------------------------------------------------------------------
    op.create_table(
        "workspaces",
        sa.Column("id",         sa.String(36),  primary_key=True),
        sa.Column("tenant_id",  sa.String(36),  nullable=False),
        sa.Column("slug",       sa.String(255), nullable=False),
        sa.Column("name",       sa.String(255), nullable=False),
        sa.Column("created_by", sa.String(36)),
        sa.Column("is_active",  sa.Boolean(),   nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.String(50),  nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("tenant_id", "slug", name="uq_workspaces_tenant_slug"),
    )
    op.create_index("ix_workspaces_tenant_id", "workspaces", ["tenant_id"])

    # Backfill: one workspace per distinct workspace_id in jobs + solutions
    # scoped to the bootstrap tenant.
    op.execute(sa.text("""
        INSERT INTO workspaces (id, tenant_id, slug, name, is_active, created_at)
        SELECT
            gen_random_uuid()::text,
            :tenant_id,
            ws_id,
            ws_id,
            true,
            now()::text
        FROM (
            SELECT workspace_id AS ws_id FROM jobs
            UNION
            SELECT workspace_id AS ws_id FROM solutions
        ) AS all_workspaces
        ON CONFLICT (tenant_id, slug) DO NOTHING
    """).bindparams(tenant_id=BOOTSTRAP_TENANT_ID))

    # ------------------------------------------------------------------
    # workspace_members  (modelled; ACL enforcement deferred to v0.2.0)
    # ------------------------------------------------------------------
    op.create_table(
        "workspace_members",
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("user_id",      sa.String(36), nullable=False),
        sa.Column("can_write",    sa.Boolean(),  nullable=False, server_default=sa.true()),
        sa.Column("added_at",     sa.String(50), nullable=False),
        sa.PrimaryKeyConstraint("workspace_id", "user_id", name="pk_workspace_members"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"],      ["users.id"],      ondelete="CASCADE"),
    )


def downgrade() -> None:
    op.drop_table("workspace_members")
    op.drop_index("ix_workspaces_tenant_id", table_name="workspaces")
    op.drop_table("workspaces")
