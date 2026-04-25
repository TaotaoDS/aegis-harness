"""Add tenant_id (and created_by) to existing tables.

Revision ID: 005
Revises: 004
Create Date: 2026-04-24

Three-phase approach (safe for live databases):

  Phase A  Add nullable columns
  Phase B  Backfill with bootstrap tenant UUID
  Phase C  Add indexes (NOT NULL constraint intentionally omitted — the
           application layer enforces tenant isolation; imposing NOT NULL
           now would break any tooling that inserts rows directly without
           the new column).

The settings table PK is changed from (key) to (tenant_id, key) so the
same setting key can exist for each tenant independently.

Downgrade removes all added columns and restores the settings PK.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

BOOTSTRAP_TENANT_ID = "00000000-0000-0000-0000-000000000001"


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Phase A — add nullable columns
    # ------------------------------------------------------------------
    op.add_column("jobs",      sa.Column("tenant_id",  sa.String(36), nullable=True))
    op.add_column("jobs",      sa.Column("created_by", sa.String(36), nullable=True))
    op.add_column("solutions", sa.Column("tenant_id",  sa.String(36), nullable=True))
    op.add_column("settings",  sa.Column("tenant_id",  sa.String(36), nullable=True))

    # ------------------------------------------------------------------
    # Phase B — backfill existing rows to the bootstrap tenant
    # ------------------------------------------------------------------
    op.execute(
        sa.text("UPDATE jobs      SET tenant_id = :tid WHERE tenant_id IS NULL")
        .bindparams(tid=BOOTSTRAP_TENANT_ID)
    )
    op.execute(
        sa.text("UPDATE solutions SET tenant_id = :tid WHERE tenant_id IS NULL")
        .bindparams(tid=BOOTSTRAP_TENANT_ID)
    )
    op.execute(
        sa.text("UPDATE settings  SET tenant_id = :tid WHERE tenant_id IS NULL")
        .bindparams(tid=BOOTSTRAP_TENANT_ID)
    )

    # ------------------------------------------------------------------
    # Phase C — indexes
    # ------------------------------------------------------------------
    op.create_index("ix_jobs_tenant_id",      "jobs",      ["tenant_id"])
    op.create_index("ix_solutions_tenant_id", "solutions", ["tenant_id"])

    # ------------------------------------------------------------------
    # Settings PK: (key) → (tenant_id, key)
    #
    # PostgreSQL does not allow ALTER TABLE DROP CONSTRAINT on a primary
    # key that is implicitly named; use the explicit constraint name.
    # The Alembic-generated name is "settings_pkey".
    # ------------------------------------------------------------------
    op.drop_constraint("settings_pkey", "settings", type_="primary")
    op.create_primary_key("settings_pkey", "settings", ["tenant_id", "key"])
    op.create_index("ix_settings_tenant_id", "settings", ["tenant_id"])


def downgrade() -> None:
    # Restore settings PK
    op.drop_index("ix_settings_tenant_id", table_name="settings")
    op.drop_constraint("settings_pkey", "settings", type_="primary")
    op.create_primary_key("settings_pkey", "settings", ["key"])

    # Drop indexes
    op.drop_index("ix_solutions_tenant_id", table_name="solutions")
    op.drop_index("ix_jobs_tenant_id",      table_name="jobs")

    # Drop columns
    op.drop_column("settings",  "tenant_id")
    op.drop_column("solutions", "tenant_id")
    op.drop_column("jobs",      "created_by")
    op.drop_column("jobs",      "tenant_id")
