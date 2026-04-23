"""MCP server management endpoints.

GET  /mcp/servers          — list all registered MCP servers
POST /mcp/servers          — register a new server
PUT  /mcp/servers/{id}     — update name / URL / enabled flag
DELETE /mcp/servers/{id}   — remove a server
POST /mcp/servers/{id}/probe — test connection + discover tools

Persistence
-----------
Server registrations are stored under the ``mcp_servers`` key in the
settings service (DB-backed, in-memory fallback) so they survive restarts.

The MCPManager instance is module-level and loaded from settings on the
first request.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..settings_service import get_setting, set_setting

router = APIRouter(prefix="/mcp", tags=["mcp"])


# ---------------------------------------------------------------------------
# Pydantic request/response models
# ---------------------------------------------------------------------------

class AddServerRequest(BaseModel):
    name:        str
    url:         str
    description: str  = ""
    enabled:     bool = True


class UpdateServerRequest(BaseModel):
    name:        Optional[str]  = None
    url:         Optional[str]  = None
    enabled:     Optional[bool] = None
    description: Optional[str] = None


# ---------------------------------------------------------------------------
# Manager lifecycle (lazy-loaded singleton per process)
# ---------------------------------------------------------------------------

_manager = None


async def _get_manager():
    """Return the module-level MCPManager, loading persisted servers on first use."""
    global _manager
    if _manager is None:
        from core_orchestrator.mcp_manager import MCPManager
        saved = await get_setting("mcp_servers") or []
        if not isinstance(saved, list):
            saved = []
        _manager = MCPManager(servers=saved)
    return _manager


async def _persist(manager) -> None:
    """Write current server list back to the settings store."""
    await set_setting("mcp_servers", manager.to_dict_list())


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/servers")
async def list_servers() -> List[Dict[str, Any]]:
    """Return all registered MCP servers."""
    m = await _get_manager()
    return m.to_dict_list()


@router.post("/servers", status_code=201)
async def add_server(body: AddServerRequest) -> Dict[str, Any]:
    """Register a new MCP server."""
    if not body.name.strip():
        raise HTTPException(status_code=422, detail="name must not be empty")
    if not body.url.strip():
        raise HTTPException(status_code=422, detail="url must not be empty")

    m = await _get_manager()
    server = m.add_server(
        name        = body.name,
        url         = body.url,
        description = body.description,
        enabled     = body.enabled,
    )
    await _persist(m)
    return server.to_dict()


@router.put("/servers/{server_id}")
async def update_server(
    server_id: str,
    body: UpdateServerRequest,
) -> Dict[str, Any]:
    """Update a registered server's name, URL, or enabled state."""
    m = await _get_manager()
    server = m.update_server(
        server_id,
        name        = body.name,
        url         = body.url,
        enabled     = body.enabled,
        description = body.description,
    )
    if server is None:
        raise HTTPException(status_code=404, detail=f"Server '{server_id}' not found")
    await _persist(m)
    return server.to_dict()


@router.delete("/servers/{server_id}")
async def remove_server(server_id: str) -> Dict[str, str]:
    """Remove an MCP server registration."""
    m = await _get_manager()
    removed = m.remove_server(server_id)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Server '{server_id}' not found")
    await _persist(m)
    return {"id": server_id, "status": "deleted"}


@router.post("/servers/{server_id}/probe")
async def probe_server(server_id: str) -> Dict[str, Any]:
    """Probe an MCP server: verify connectivity and discover its tools.

    Returns ``{"status": "connected", "tools": [...], "tool_count": N}``
    on success, or ``{"status": "error", "error": "..."}`` on failure.
    Persists the updated tool list and status.
    """
    m = await _get_manager()
    if not m.get_server(server_id):
        raise HTTPException(status_code=404, detail=f"Server '{server_id}' not found")

    result = m.probe_server(server_id)
    await _persist(m)   # persist updated status + tool list
    return result
