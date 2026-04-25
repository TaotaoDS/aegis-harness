"""MCP server management endpoints.

GET  /mcp/servers          — list registered MCP servers for the tenant
POST /mcp/servers          — register a new server (admin+)
PUT  /mcp/servers/{id}     — update name / URL / enabled flag (admin+)
DELETE /mcp/servers/{id}   — remove a server (admin+)
POST /mcp/servers/{id}/probe — test connection + discover tools (admin+)

Auth & authorisation
--------------------
All write operations require Admin or Owner role.
Reads (GET) are visible to all authenticated users.

Multi-tenancy
-------------
MCP server registrations are isolated per tenant.  The in-process manager
cache is keyed by tenant_id so different tenants never share server lists.
Persistence uses the scoped ``mcp_servers`` key in the settings service.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..deps import CurrentUser, get_current_user, require_admin
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
# Per-tenant manager cache
# ---------------------------------------------------------------------------

_managers: Dict[str, Any] = {}   # tenant_id → MCPManager


async def _get_manager(tenant_id: str):
    """Return the MCPManager for ``tenant_id``, loading persisted servers lazily."""
    if tenant_id not in _managers:
        from core_orchestrator.mcp_manager import MCPManager
        saved = await get_setting("mcp_servers", tenant_id) or []
        if not isinstance(saved, list):
            saved = []
        _managers[tenant_id] = MCPManager(servers=saved)
    return _managers[tenant_id]


async def _persist(manager, tenant_id: str) -> None:
    await set_setting("mcp_servers", manager.to_dict_list(), tenant_id)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/servers")
async def list_servers(
    current_user: CurrentUser = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    """Return all MCP servers registered for the current tenant."""
    m = await _get_manager(str(current_user.tenant_id))
    return m.to_dict_list()


@router.post("/servers", status_code=201)
async def add_server(
    body: AddServerRequest,
    current_user: CurrentUser = Depends(require_admin),
) -> Dict[str, Any]:
    """Register a new MCP server (admin/owner only)."""
    if not body.name.strip():
        raise HTTPException(status_code=422, detail="name must not be empty")
    if not body.url.strip():
        raise HTTPException(status_code=422, detail="url must not be empty")

    tid = str(current_user.tenant_id)
    m   = await _get_manager(tid)
    server = m.add_server(
        name=body.name, url=body.url,
        description=body.description, enabled=body.enabled,
    )
    await _persist(m, tid)
    return server.to_dict()


@router.put("/servers/{server_id}")
async def update_server(
    server_id: str,
    body: UpdateServerRequest,
    current_user: CurrentUser = Depends(require_admin),
) -> Dict[str, Any]:
    """Update a server (admin/owner only)."""
    tid = str(current_user.tenant_id)
    m   = await _get_manager(tid)
    server = m.update_server(
        server_id, name=body.name, url=body.url,
        enabled=body.enabled, description=body.description,
    )
    if server is None:
        raise HTTPException(status_code=404, detail=f"Server '{server_id}' not found")
    await _persist(m, tid)
    return server.to_dict()


@router.delete("/servers/{server_id}")
async def remove_server(
    server_id: str,
    current_user: CurrentUser = Depends(require_admin),
) -> Dict[str, str]:
    """Remove an MCP server (admin/owner only)."""
    tid = str(current_user.tenant_id)
    m   = await _get_manager(tid)
    removed = m.remove_server(server_id)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Server '{server_id}' not found")
    await _persist(m, tid)
    return {"id": server_id, "status": "deleted"}


@router.post("/servers/{server_id}/probe")
async def probe_server(
    server_id: str,
    current_user: CurrentUser = Depends(require_admin),
) -> Dict[str, Any]:
    """Probe connectivity and discover tools (admin/owner only)."""
    tid = str(current_user.tenant_id)
    m   = await _get_manager(tid)
    if not m.get_server(server_id):
        raise HTTPException(status_code=404, detail=f"Server '{server_id}' not found")
    result = m.probe_server(server_id)
    await _persist(m, tid)
    return result
