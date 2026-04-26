"""008 — Super-admin setup & user status

Adds:
  - users.status  VARCHAR(20) NOT NULL DEFAULT 'active'
      Values: 'active' | 'pending' | 'suspended'
      Existing rows backfilled to 'active'.
      New self-registrations will be set to 'pending' at the application layer.
"""

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
    )
    # Backfill all existing rows to 'active' so nothing breaks on upgrade.
    op.execute("UPDATE users SET status = 'active' WHERE status IS NULL OR status = ''")


def downgrade() -> None:
    op.drop_column("users", "status")
