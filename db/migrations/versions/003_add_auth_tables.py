"""Add multi-tenancy auth tables: tenants, users, refresh_tokens.

Revision ID: 003
Revises: 002
Create Date: 2026-04-24

Inserts one bootstrap tenant row whose UUID is the fixed constant
``00000000-0000-0000-0000-000000000001``.  This UUID is used by migrations
004 and 005 to backfill existing rows and by ``api/deps.py`` for dev-mode
operation when ``SECRET_KEY`` is not set.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Fixed UUIDs — deterministic so migrations are reproducible.
BOOTSTRAP_TENANT_ID = "00000000-0000-0000-0000-000000000001"
BOOTSTRAP_USER_ID   = "00000000-0000-0000-0000-000000000002"


def upgrade() -> None:
    # ------------------------------------------------------------------
    # tenants
    # ------------------------------------------------------------------
    op.create_table(
        "tenants",
        sa.Column("id",         sa.String(36),  primary_key=True),
        sa.Column("slug",       sa.String(63),  nullable=False),
        sa.Column("name",       sa.String(255), nullable=False),
        sa.Column("plan",       sa.String(50),  nullable=False, server_default="free"),
        sa.Column("is_active",  sa.Boolean(),   nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.String(50),  nullable=False),
        sa.UniqueConstraint("slug", name="uq_tenants_slug"),
    )
    op.create_index("ix_tenants_slug", "tenants", ["slug"], unique=True)

    # Bootstrap tenant — pre-existing data is backfilled to this row in 005.
    op.execute(
        sa.text(
            "INSERT INTO tenants (id, slug, name, plan, is_active, created_at) "
            "VALUES (:id, :slug, :name, :plan, :is_active, :created_at)"
        ).bindparams(
            id=BOOTSTRAP_TENANT_ID,
            slug="default",
            name="Default Tenant",
            plan="free",
            is_active=True,
            created_at="2026-01-01T00:00:00+00:00",
        )
    )

    # ------------------------------------------------------------------
    # users
    # ------------------------------------------------------------------
    op.create_table(
        "users",
        sa.Column("id",              sa.String(36),  primary_key=True),
        sa.Column("tenant_id",       sa.String(36),  nullable=False),
        sa.Column("email",           sa.String(255), nullable=False),
        sa.Column("display_name",    sa.String(255)),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("role",            sa.String(50),  nullable=False, server_default="member"),
        sa.Column("is_active",       sa.Boolean(),   nullable=False, server_default=sa.true()),
        sa.Column("created_at",      sa.String(50),  nullable=False),
        sa.Column("last_login_at",   sa.String(50)),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("ix_users_tenant_id", "users", ["tenant_id"])
    op.create_index("ix_users_email",     "users", ["email"], unique=True)

    # ------------------------------------------------------------------
    # refresh_tokens  (also used for one-time invite tokens via meta JSON)
    # ------------------------------------------------------------------
    op.create_table(
        "refresh_tokens",
        sa.Column("id",          sa.String(36),  primary_key=True),
        sa.Column("user_id",     sa.String(36),  nullable=False),
        sa.Column("token_hash",  sa.String(64),  nullable=False),
        sa.Column("expires_at",  sa.String(50),  nullable=False),
        sa.Column("created_at",  sa.String(50),  nullable=False),
        sa.Column("revoked_at",  sa.String(50)),
        sa.Column("meta",        sa.JSON()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("token_hash", name="uq_refresh_tokens_token_hash"),
    )
    op.create_index("ix_refresh_tokens_user_id",    "refresh_tokens", ["user_id"])
    op.create_index("ix_refresh_tokens_token_hash", "refresh_tokens", ["token_hash"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_refresh_tokens_token_hash", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_user_id",    table_name="refresh_tokens")
    op.drop_table("refresh_tokens")

    op.drop_index("ix_users_email",     table_name="users")
    op.drop_index("ix_users_tenant_id", table_name="users")
    op.drop_table("users")

    op.drop_index("ix_tenants_slug", table_name="tenants")
    op.drop_table("tenants")
