"""Alembic environment — supports both online (async) and offline modes.

Reads DATABASE_URL from the environment so the same migration can run
against any target database without editing alembic.ini.
"""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

# Import our ORM metadata so Alembic can inspect the schema
import sys
from pathlib import Path

# Ensure the project root is on sys.path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from db.models import Base  # noqa: E402

# Alembic Config object (gives access to values in alembic.ini)
config = context.config

# Set up Python logging from alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _get_url() -> str:
    """Return the database URL from DATABASE_URL env var or alembic.ini."""
    raw = os.getenv("DATABASE_URL", "").strip()
    if raw:
        # Normalise to asyncpg scheme
        for plain in ("postgresql://", "postgres://"):
            if raw.startswith(plain):
                return "postgresql+asyncpg://" + raw[len(plain):]
        return raw
    return config.get_main_option("sqlalchemy.url", "")


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a live connection (useful for review)."""
    url = _get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in online mode using an async engine."""
    engine = create_async_engine(_get_url(), echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(do_run_migrations)
    await engine.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
