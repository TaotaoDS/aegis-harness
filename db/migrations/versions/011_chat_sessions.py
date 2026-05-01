"""Add chat_sessions and chat_messages tables for workspace conversation persistence.

Revision ID: 011
Revises: 010
Create Date: 2026-04-29
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "chat_sessions",
        sa.Column("id",               sa.String(36),  primary_key=True),
        sa.Column("tenant_id",        sa.String(36),  nullable=False),
        sa.Column("user_id",          sa.String(36),  nullable=False),
        sa.Column("title",            sa.String(200), nullable=False, server_default=""),
        sa.Column("context_node_ids", sa.JSON(),      nullable=False, server_default="[]"),
        sa.Column("message_count",    sa.Integer(),   nullable=False, server_default="0"),
        sa.Column("created_at",       sa.String(50),  nullable=False),
        sa.Column("updated_at",       sa.String(50),  nullable=True),
    )
    op.create_index("ix_chat_sessions_tenant_user", "chat_sessions", ["tenant_id", "user_id"])

    op.create_table(
        "chat_messages",
        sa.Column("id",         sa.Integer(),   primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.String(36),  nullable=False),
        sa.Column("role",       sa.String(20),  nullable=False),
        sa.Column("content",    sa.Text(),      nullable=False),
        sa.Column("created_at", sa.String(50),  nullable=False),
    )
    op.create_index("ix_chat_messages_session", "chat_messages", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_chat_messages_session", "chat_messages")
    op.drop_table("chat_messages")
    op.drop_index("ix_chat_sessions_tenant_user", "chat_sessions")
    op.drop_table("chat_sessions")
