"""Async SQLAlchemy engine and session management.

Usage
-----
At application startup call ``await init_db()``.  It returns True when a
live PostgreSQL connection was established, False otherwise (file-only mode).

Guard every DB call with ``if is_db_available()``.  That way the system
degrades gracefully when DATABASE_URL is absent — all existing tests
continue to pass without a running database.

Driver note
-----------
SQLAlchemy async requires the ``asyncpg`` driver.  The DATABASE_URL may
use either the ``postgresql://`` or ``postgresql+asyncpg://`` scheme; this
module normalises it automatically.
"""

from __future__ import annotations

import os
import warnings
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .models import Base

# Module-level singletons — set by init_db(), cleared by close_db()
_engine: Optional[AsyncEngine] = None
_session_factory: Optional[async_sessionmaker] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def normalise_db_url(url: str) -> str:
    """Ensure the URL uses the asyncpg driver scheme."""
    for plain in ("postgresql://", "postgres://"):
        if url.startswith(plain):
            return "postgresql+asyncpg://" + url[len(plain):]
    return url  # already correct (postgresql+asyncpg://) or unsupported


def _get_database_url() -> Optional[str]:
    raw = os.getenv("DATABASE_URL", "").strip()
    return normalise_db_url(raw) if raw else None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def init_db() -> bool:
    """Initialise the engine and create all tables.

    Returns True on success, False when DATABASE_URL is not configured or
    the connection attempt fails (safe to ignore — file-only mode is used).
    """
    global _engine, _session_factory

    db_url = _get_database_url()
    if not db_url:
        return False

    try:
        _engine = create_async_engine(
            db_url,
            echo=False,
            pool_pre_ping=True,      # reconnect after idle disconnect
            pool_size=5,
            max_overflow=10,
        )
        _session_factory = async_sessionmaker(_engine, expire_on_commit=False)

        # Create tables (idempotent — IF NOT EXISTS)
        async with _engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        return True

    except Exception as exc:  # noqa: BLE001
        warnings.warn(
            f"[DB] init_db failed — running in file-only mode. Reason: {exc}",
            stacklevel=2,
        )
        _engine = None
        _session_factory = None
        return False


def is_db_available() -> bool:
    """True when a live engine has been initialised."""
    return _engine is not None


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Async context manager that yields a transactional session.

    Commits on clean exit, rolls back on exception.
    Raises RuntimeError if the DB is not initialised.
    """
    if _session_factory is None:
        raise RuntimeError("DB not initialised — call init_db() first")

    async with _session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def close_db() -> None:
    """Dispose the engine on application shutdown."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
