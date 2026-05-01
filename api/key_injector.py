"""Bridge DB-stored API keys → os.environ for ModelRouter.

ModelRouter reads credentials from environment variables (``api_key_env:
OPENROUTER_API_KEY``, etc.).  When a user saves their keys via the Settings
UI those values are stored in the DB under ``api_keys``.  This module
provides :func:`inject_api_keys_to_env` to copy the DB values into
``os.environ`` so that ModelRouter picks them up — DB values override the
.env file, giving the UI-saved key the highest priority.

Call this:
  • In async API handlers: ``await inject_api_keys_to_env(tenant_id)`` before
    any ModelRouter creation.
  • In sync pipeline threads: use the already-running event loop —
    ``asyncio.run_coroutine_threadsafe(..., loop).result(timeout=5)``
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

# Mapping: DB settings key → environment variable name expected by models_config.yaml
_DB_KEY_TO_ENV: Dict[str, str] = {
    "openrouter":  "OPENROUTER_API_KEY",
    "anthropic":   "ANTHROPIC_API_KEY",
    "openai":      "OPENAI_API_KEY",
    "nvidia":      "NVIDIA_API_KEY",
    "deepseek":    "DEEPSEEK_API_KEY",
    "zhipu":       "ZHIPU_API_KEY",
    "moonshot":    "MOONSHOT_API_KEY",
    "google":      "GOOGLE_API_KEY",
    "qwen":        "DASHSCOPE_API_KEY",
    "mistral":     "MISTRAL_API_KEY",
    "groq":        "GROQ_API_KEY",
    "xai":         "XAI_API_KEY",
    "together":    "TOGETHER_API_KEY",
    "brave_search": "BRAVE_SEARCH_API_KEY",
}


async def inject_api_keys_to_env(
    tenant_id: str,
    *,
    override_existing: bool = True,
) -> None:
    """Fetch ``api_keys`` from DB settings and inject them into ``os.environ``.

    Parameters
    ----------
    tenant_id:
        The tenant whose stored keys should be loaded.
    override_existing:
        When ``True`` (default), a non-empty DB value replaces the current
        environment variable even if one is already set (e.g. from ``.env``).
        Set to ``False`` to let ``.env`` values take priority.
    """
    try:
        from .settings_service import get_setting
        api_keys: Any = await get_setting("api_keys", tenant_id)
    except Exception:   # noqa: BLE001
        return

    if not isinstance(api_keys, dict):
        return

    for db_key, env_var in _DB_KEY_TO_ENV.items():
        val: str = api_keys.get(db_key) or ""
        # Skip empty values and server-side masked placeholders
        if not val or val.startswith("****"):
            continue
        if override_existing or not os.environ.get(env_var):
            os.environ[env_var] = val
