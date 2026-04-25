"""Settings service — unified read/write for application settings.

Priority chain (highest → lowest):
  1. PostgreSQL ``settings`` table (when DB is available)
  2. In-process memory dict (always available as fallback)

Multi-tenancy
-------------
Every function accepts an optional ``tenant_id`` parameter (defaults to the
bootstrap tenant UUID so all pre-multitenancy callers are unaffected).

Settings keys (by convention)
------------------------------
``user_profile``   — UserProfile dict  (per-user: stored as "user_profile:{user_id}")
``ceo_config``     — {"agent_name": str, "system_prompt_prefix": str}
``api_keys``       — {"anthropic": str, "openai": str, "nvidia": str, ...}
``model_config``   — {"default_model": str, "models_config_path": str}
``mcp_servers``    — list of MCP server dicts

Backward compatibility
----------------------
All existing callers that omit ``tenant_id`` continue to work: they
transparently operate against the bootstrap tenant.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

# Bootstrap tenant UUID (must match api/deps.py and migration 003).
_BOOTSTRAP_TENANT = "00000000-0000-0000-0000-000000000001"

# Module-level in-memory fallback: keyed as (tenant_id, setting_key).
_MEMORY: Dict[tuple[str, str], Any] = {}


# ---------------------------------------------------------------------------
# Core read/write
# ---------------------------------------------------------------------------

async def get_setting(
    key: str, tenant_id: str = _BOOTSTRAP_TENANT
) -> Optional[Any]:
    """Return the parsed value for ``key`` under ``tenant_id``, or ``None``."""
    # 1. Try DB
    try:
        from db.connection import get_session, is_db_available
        from db.repository import get_setting as db_get

        if is_db_available():
            async with get_session() as session:
                val = await db_get(session, key, tenant_id)
                if val is not None:
                    return val
    except Exception:   # noqa: BLE001
        pass

    # 2. In-memory fallback (exact tenant first, then bootstrap)
    val = _MEMORY.get((tenant_id, key))
    if val is None and tenant_id != _BOOTSTRAP_TENANT:
        val = _MEMORY.get((_BOOTSTRAP_TENANT, key))
    return val


async def set_setting(
    key: str, value: Any, tenant_id: str = _BOOTSTRAP_TENANT
) -> None:
    """Persist ``value`` under ``(tenant_id, key)`` (DB + memory)."""
    _MEMORY[(tenant_id, key)] = value

    try:
        from db.connection import get_session, is_db_available
        from db.repository import set_setting as db_set

        if is_db_available():
            async with get_session() as session:
                await db_set(session, key, value, tenant_id)
    except Exception:   # noqa: BLE001
        pass


async def get_all_settings(tenant_id: str = _BOOTSTRAP_TENANT) -> Dict[str, Any]:
    """Return all settings for ``tenant_id`` as a plain dict.

    When DB is available it is the source of truth; the memory dict
    fills in any keys that haven't been committed to DB yet.
    """
    # Start with in-memory keys for this tenant
    combined: Dict[str, Any] = {
        k: v for (tid, k), v in _MEMORY.items() if tid == tenant_id
    }

    try:
        from db.connection import get_session, is_db_available
        from db.repository import get_all_settings_by_tenant

        if is_db_available():
            async with get_session() as session:
                db_settings = await get_all_settings_by_tenant(session, tenant_id)
                combined.update(db_settings)   # DB wins
    except Exception:   # noqa: BLE001
        pass

    return combined


# ---------------------------------------------------------------------------
# Convenience: load user profile
# ---------------------------------------------------------------------------

async def load_user_profile_dict(
    tenant_id: str = _BOOTSTRAP_TENANT,
    user_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Return the stored user profile dict, or None if not configured.

    When ``user_id`` is provided, looks for ``user_profile:{user_id}``
    (per-user profile) before falling back to the tenant-level ``user_profile``.
    """
    if user_id:
        val = await get_setting(f"user_profile:{user_id}", tenant_id)
        if isinstance(val, dict):
            return val

    val = await get_setting("user_profile", tenant_id)
    if isinstance(val, dict):
        return val
    return None
