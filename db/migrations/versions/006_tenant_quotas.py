"""Add token quota columns to tenants table.

Revision ID: 006
Revises: 005
Create Date: 2026-04-26

Adds three columns to ``tenants`` for per-tenant daily token quota tracking:

  token_usage_daily  INTEGER NOT NULL DEFAULT 0
      Running total of tokens consumed today (UTC). Reset lazily by
      QuotaManager.record_usage() when the date advances.

  token_budget_daily INTEGER NULL
      Daily token cap for the tenant.  NULL means unlimited.
      Set via admin API; free-plan tenants may have a default applied
      by a separate provisioning job.

  last_usage_reset   VARCHAR(10) NULL
      ISO date string ("YYYY-MM-DD", UTC) of the last counter reset.
      Used by QuotaManager to detect day boundaries without a cron job.

Safe for live databases — all columns are additive (no constraint changes,
no data backfill required).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column(
            "token_usage_daily",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "tenants",
        sa.Column(
            "token_budget_daily",
            sa.Integer(),
            nullable=True,
        ),
    )
    op.add_column(
        "tenants",
        sa.Column(
            "last_usage_reset",
            sa.String(10),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("tenants", "last_usage_reset")
    op.drop_column("tenants", "token_budget_daily")
    op.drop_column("tenants", "token_usage_daily")
