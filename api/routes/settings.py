"""Settings CRUD endpoints.

GET  /settings              — all settings for the current tenant (api_keys masked)
GET  /settings/{key}        — single setting value
PUT  /settings/{key}        — upsert a setting
DELETE /settings/{key}      — remove a setting

Auth & authorisation
--------------------
All endpoints require an authenticated user.  Writes to sensitive keys
(``api_keys``, ``model_config``, ``ceo_config``, ``mcp_servers``) require
the Admin or Owner role; Members can only read/write ``user_profile`` (their
own) and other non-sensitive keys.

``user_profile`` is per-user: stored as ``user_profile:{user_id}`` so each
team member has independent preferences.

Security note
-------------
API keys stored under the ``api_keys`` key are **masked** in GET responses
(only the last 4 characters are shown).  The full value is used internally
but never returned to the browser.
"""

from __future__ import annotations

import re
import time
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from db.connection import normalise_db_url
from ..deps import CurrentUser, get_current_user, require_admin
from ..settings_service import get_all_settings, get_setting, set_setting

router = APIRouter(prefix="/settings", tags=["settings"])

# Keys that require Admin or Owner to write
_ADMIN_ONLY_WRITE_KEYS = {"api_keys", "model_config", "ceo_config", "mcp_servers", "onboarded"}

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class SettingValue(BaseModel):
    value: Any


class DbTestRequest(BaseModel):
    url: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_:]*$")   # allow "user_profile:uuid"


def _validate_key(key: str) -> None:
    if not _KEY_PATTERN.match(key):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid settings key '{key}'. Use lowercase letters, digits, underscores, and colons.",
        )


def _mask_api_keys(data: Any) -> Any:
    if isinstance(data, dict):
        return {k: _mask_if_key(k, v) for k, v in data.items()}
    return data


def _mask_if_key(field_name: str, value: Any) -> Any:
    name_lower = field_name.lower()
    if ("key" in name_lower or "secret" in name_lower or "token" in name_lower):
        if isinstance(value, str) and len(value) > 8:
            return "****" + value[-4:]
    if isinstance(value, dict):
        return _mask_api_keys(value)
    return value


def _check_write_permission(key: str, current_user: CurrentUser) -> None:
    """Raise 403 if the user lacks permission to write ``key``."""
    base_key = key.split(":")[0]            # "user_profile:uuid" → "user_profile"
    if base_key in _ADMIN_ONLY_WRITE_KEYS and not current_user.is_admin:
        raise HTTPException(
            status_code=403,
            detail=f"Admin role required to modify '{base_key}'",
        )


def _effective_key(key: str, current_user: CurrentUser) -> tuple[str, str]:
    """Return ``(effective_key, tenant_id)`` for the request.

    ``user_profile`` is automatically namespaced to the current user so
    members get/set only their own profile.
    """
    tid = str(current_user.tenant_id)
    if key == "user_profile":
        return f"user_profile:{current_user.user_id}", tid
    return key, tid


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/test_db_connection")
async def test_db_connection(
    body: DbTestRequest,
    current_user: CurrentUser = Depends(require_admin),   # admin-only
) -> Dict[str, Any]:
    """Test a PostgreSQL URL without modifying the running engine."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    raw_url = body.url.strip()
    if not raw_url:
        raise HTTPException(status_code=422, detail="url is required")

    normalised = normalise_db_url(raw_url)
    engine = None
    t0 = time.monotonic()
    try:
        engine = create_async_engine(
            normalised, echo=False, pool_size=1, max_overflow=0,
            connect_args={"timeout": 10},
        )
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {"ok": True, "latency_ms": round((time.monotonic() - t0) * 1000, 1), "error": None}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "latency_ms": round((time.monotonic() - t0) * 1000, 1), "error": str(exc)}
    finally:
        if engine is not None:
            await engine.dispose()


@router.get("")
async def list_settings(
    current_user: CurrentUser = Depends(get_current_user),
) -> Dict[str, Any]:
    """Return all settings for the current tenant (api_keys masked)."""
    tid = str(current_user.tenant_id)
    raw = await get_all_settings(tid)
    if "api_keys" in raw:
        raw = dict(raw)
        raw["api_keys"] = _mask_api_keys(raw["api_keys"])
    return raw


@router.get("/{key}")
async def read_setting(
    key: str,
    current_user: CurrentUser = Depends(get_current_user),
) -> Dict[str, Any]:
    """Return a single setting value (scoped to the current tenant/user)."""
    _validate_key(key)
    eff_key, tid = _effective_key(key, current_user)
    value = await get_setting(eff_key, tid)
    if value is None:
        raise HTTPException(status_code=404, detail=f"Setting '{key}' not found")
    if key == "api_keys":
        value = _mask_api_keys(value)
    return {"key": key, "value": value}


@router.put("/{key}", status_code=200)
async def write_setting(
    key: str,
    body: SettingValue,
    current_user: CurrentUser = Depends(get_current_user),
) -> Dict[str, Any]:
    """Create or update a setting for the current tenant/user.

    Requires Admin/Owner for sensitive keys (api_keys, model_config, ceo_config).
    Members can write user_profile (auto-namespaced to their user_id).
    """
    _validate_key(key)
    _check_write_permission(key, current_user)
    eff_key, tid = _effective_key(key, current_user)

    # api_keys: merge rather than replace
    if key == "api_keys" and isinstance(body.value, dict):
        existing = await get_setting("api_keys", tid) or {}
        if isinstance(existing, dict):
            merged = {**existing, **body.value}
            merged = {k: v for k, v in merged.items() if v != ""}
            await set_setting("api_keys", merged, tid)
            return {"key": key, "value": _mask_api_keys(merged)}

    await set_setting(eff_key, body.value, tid)

    if key in ("model_config", "api_keys"):
        try:
            from core_orchestrator.model_router import invalidate_model_cache
            invalidate_model_cache()
        except Exception:  # noqa: BLE001
            pass

    return {"key": key, "value": body.value}


@router.delete("/{key}", status_code=200)
async def delete_setting(
    key: str,
    current_user: CurrentUser = Depends(require_admin),   # admin-only
) -> Dict[str, str]:
    """Remove a setting (admin/owner only)."""
    _validate_key(key)
    eff_key, tid = _effective_key(key, current_user)
    await set_setting(eff_key, None, tid)
    return {"key": key, "status": "deleted"}


@router.get("/model_runtime", include_in_schema=True)
async def get_model_runtime(
    current_user: CurrentUser = Depends(get_current_user),
) -> Dict[str, Any]:
    """Return the currently loaded model definitions for the Settings UI."""
    try:
        from pathlib import Path
        from core_orchestrator.model_router import ModelRouter

        config_path = Path(__file__).parent.parent.parent / "models_config.yaml"
        if not config_path.exists():
            return {"key": "model_runtime", "value": {"models": {}}}

        router_obj = ModelRouter(config_path)
        safe_models = {
            name: {k: v for k, v in cfg.items() if k not in ("api_key", "api_key_env")}
            for name, cfg in router_obj.models.items()
        }
        return {"key": "model_runtime", "value": {"models": safe_models}}
    except Exception as exc:  # noqa: BLE001
        return {"key": "model_runtime", "value": {"models": {}, "error": str(exc)}}
