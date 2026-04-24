"""Settings CRUD endpoints.

GET  /settings              — all settings (api_keys are masked)
GET  /settings/{key}        — single setting value
PUT  /settings/{key}        — upsert a setting
DELETE /settings/{key}      — remove a setting

Security note
-------------
API keys stored under the ``api_keys`` key are **masked** in GET
responses (only the last 4 characters are shown).  The full value is
returned to the backend for validation, never to the browser.

After a model-config change the ModelRouter's TTL cache is invalidated
so the new active model takes effect on the next pipeline run (≤ 30 s).
"""

from __future__ import annotations

import re
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..settings_service import get_all_settings, get_setting, set_setting

router = APIRouter(prefix="/settings", tags=["settings"])


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

_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


def _validate_key(key: str) -> None:
    if not _KEY_PATTERN.match(key):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid settings key '{key}'. Use lowercase letters, digits, and underscores.",
        )


def _mask_api_keys(data: Any) -> Any:
    """Recursively mask API key values in a settings dict.

    Any value whose key ends with ``_key`` or equals ``key`` (case-insensitive)
    and whose string value is longer than 8 chars gets masked to ``****<last4>``.
    """
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


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/test_db_connection")
async def test_db_connection(body: DbTestRequest) -> Dict[str, Any]:
    """Test a PostgreSQL URL without modifying the running engine.

    Returns ``{"ok": bool, "latency_ms": float, "error": str | null}``.
    """
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    raw_url = body.url.strip()
    if not raw_url:
        raise HTTPException(status_code=422, detail="url is required")

    # Normalise to asyncpg driver scheme
    normalised = raw_url
    for plain in ("postgresql://", "postgres://"):
        if raw_url.startswith(plain):
            normalised = "postgresql+asyncpg://" + raw_url[len(plain):]
            break

    engine = None
    t0 = time.monotonic()
    try:
        engine = create_async_engine(
            normalised,
            echo=False,
            pool_size=1,
            max_overflow=0,
            connect_args={"timeout": 10},
        )
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        latency_ms = round((time.monotonic() - t0) * 1000, 1)
        return {"ok": True, "latency_ms": latency_ms, "error": None}
    except Exception as exc:  # noqa: BLE001
        latency_ms = round((time.monotonic() - t0) * 1000, 1)
        return {"ok": False, "latency_ms": latency_ms, "error": str(exc)}
    finally:
        if engine is not None:
            await engine.dispose()


@router.get("")
async def list_settings() -> Dict[str, Any]:
    """Return all settings with API keys masked."""
    raw = await get_all_settings()
    # Mask api_keys section specifically
    if "api_keys" in raw:
        raw = dict(raw)
        raw["api_keys"] = _mask_api_keys(raw["api_keys"])
    return raw


@router.get("/{key}")
async def read_setting(key: str) -> Dict[str, Any]:
    """Return a single setting value."""
    _validate_key(key)
    value = await get_setting(key)
    if value is None:
        raise HTTPException(status_code=404, detail=f"Setting '{key}' not found")

    # Mask if this is the api_keys setting
    if key == "api_keys":
        value = _mask_api_keys(value)

    return {"key": key, "value": value}


@router.put("/{key}", status_code=200)
async def write_setting(key: str, body: SettingValue) -> Dict[str, Any]:
    """Create or update a setting.

    Special side-effects:
    - Writing ``model_config`` invalidates the ModelRouter TTL cache so
      the new active model is picked up on the next pipeline run.
    - Writing ``api_keys`` merges with existing keys (does not clobber
      keys omitted from the payload).
    """
    _validate_key(key)

    # Special handling: api_keys → merge with existing rather than replace
    if key == "api_keys" and isinstance(body.value, dict):
        existing = await get_setting("api_keys") or {}
        if isinstance(existing, dict):
            merged = {**existing, **body.value}
            # Remove empty-string values (user clearing a key)
            merged = {k: v for k, v in merged.items() if v != ""}
            await set_setting("api_keys", merged)
            return {"key": key, "value": _mask_api_keys(merged)}

    await set_setting(key, body.value)

    # Invalidate model cache after config change
    if key in ("model_config", "api_keys"):
        try:
            from core_orchestrator.model_router import invalidate_model_cache
            invalidate_model_cache()
        except Exception:  # noqa: BLE001
            pass

    return {"key": key, "value": body.value}


@router.delete("/{key}", status_code=200)
async def delete_setting(key: str) -> Dict[str, str]:
    """Remove a setting (sets it to null in DB / removes from memory)."""
    _validate_key(key)
    await set_setting(key, None)
    return {"key": key, "status": "deleted"}


# ---------------------------------------------------------------------------
# Special read-only: expose current model list from YAML config
# ---------------------------------------------------------------------------

@router.get("/model_runtime", include_in_schema=True)
async def get_model_runtime() -> Dict[str, Any]:
    """Return the currently loaded model definitions for the Settings UI.

    Reads from the ModelRouter config (cached, ≤ 30 s stale).
    Does NOT expose API keys.
    """
    try:
        from pathlib import Path
        from core_orchestrator.model_router import ModelRouter

        config_path = Path(__file__).parent.parent.parent / "models_config.yaml"
        if not config_path.exists():
            return {"key": "model_runtime", "value": {"models": {}}}

        router_obj = ModelRouter(config_path)
        # Strip sensitive fields before returning
        safe_models = {}
        for name, cfg in router_obj.models.items():
            safe_models[name] = {
                k: v for k, v in cfg.items()
                if k not in ("api_key", "api_key_env")
            }
        return {"key": "model_runtime", "value": {"models": safe_models}}
    except Exception as exc:  # noqa: BLE001
        return {"key": "model_runtime", "value": {"models": {}, "error": str(exc)}}
