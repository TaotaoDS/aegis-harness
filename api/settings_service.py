"""Settings service — unified read/write for application settings.

Priority chain (highest → lowest):
  1. PostgreSQL ``settings`` table (when DB is available)
  2. In-process memory dict (always available as fallback)

This makes the settings API work correctly in both Docker (with DB) and
bare-metal dev (file-only) modes without changing any caller code.

Settings keys (by convention)
------------------------------
``user_profile``   — UserProfile dict (see core_orchestrator.user_profile)
``ceo_config``     — {"agent_name": str, "system_prompt_prefix": str}
``api_keys``       — {"anthropic": str, "openai": str, "nvidia": str, ...}
``model_config``   — {"default_model": str, "models_config_path": str}
"""

from __future__ import annotations

from typing import Any, Dict, Optional

# Module-level in-memory fallback (used when no DB is available)
_MEMORY: Dict[str, Any] = {}


async def get_setting(key: str) -> Optional[Any]:
    """Return the parsed value for ``key``, or ``None`` if not set."""
    # 1. Try DB
    try:
        from db.connection import get_session, is_db_available
        from db.repository import get_setting as db_get

        if is_db_available():
            async with get_session() as session:
                val = await db_get(session, key)
                if val is not None:
                    return val
    except Exception:  # noqa: BLE001
        pass

    # 2. In-memory fallback
    return _MEMORY.get(key)


async def set_setting(key: str, value: Any) -> None:
    """Persist ``value`` under ``key`` (DB + memory)."""
    # Always write to memory so it's instantly available
    _MEMORY[key] = value

    # Best-effort DB persist
    try:
        from db.connection import get_session, is_db_available
        from db.repository import set_setting as db_set

        if is_db_available():
            async with get_session() as session:
                await db_set(session, key, value)
    except Exception:  # noqa: BLE001
        pass


async def get_all_settings() -> Dict[str, Any]:
    """Return all settings as a dict.

    When DB is available it is the source of truth; the memory dict
    fills in any keys that haven't been committed to DB yet.
    """
    combined: Dict[str, Any] = dict(_MEMORY)   # start with memory

    try:
        from db.connection import get_session, is_db_available
        from sqlalchemy import select
        from db.models import SettingModel

        if is_db_available():
            async with get_session() as session:
                result = await session.execute(select(SettingModel))
                for row in result.scalars().all():
                    combined[row.key] = row.value   # DB wins
    except Exception:  # noqa: BLE001
        pass

    return combined


# ---------------------------------------------------------------------------
# Convenience: load user profile (used by job_runner + routes/jobs)
# ---------------------------------------------------------------------------

async def load_user_profile_dict() -> Optional[Dict[str, Any]]:
    """Return the stored user profile dict, or None if not configured."""
    val = await get_setting("user_profile")
    if isinstance(val, dict):
        return val
    return None
