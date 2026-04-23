"""MCP (Model Context Protocol) server registry.

Manages external tool-server registrations so agents can discover and call
tools hosted on remote MCP servers.  Persistence is delegated to the
settings service (key ``mcp_servers``), so registrations survive restarts.

Public API
----------
MCPServer  — dataclass describing a single registered server
MCPManager — registry: add / remove / list / probe servers

Probe protocol
--------------
MCP servers advertise their tools via ``GET {url}/tools``.  The response
is expected to be either a JSON array of tool objects, or an object with a
``"tools"`` key.  Probe also tries ``GET {url}/info`` for human-readable
metadata.  Both calls use ``urllib.request`` (stdlib) — no extra deps.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class MCPServer:
    """A single registered MCP server."""

    id:          str
    name:        str
    url:         str
    enabled:     bool               = True
    description: str                = ""
    status:      str                = "unknown"   # "connected" | "error" | "unknown"
    tools:       List[Dict[str, Any]] = field(default_factory=list)
    error:       str                = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id":          self.id,
            "name":        self.name,
            "url":         self.url,
            "enabled":     self.enabled,
            "description": self.description,
            "status":      self.status,
            "tools":       self.tools,
            "error":       self.error,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MCPServer":
        return cls(
            id          = data.get("id", ""),
            name        = data.get("name", ""),
            url         = data.get("url", "").rstrip("/"),
            enabled     = bool(data.get("enabled", True)),
            description = data.get("description", ""),
            status      = data.get("status", "unknown"),
            tools       = data.get("tools", []),
            error       = data.get("error", ""),
        )


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

class MCPManager:
    """Registry for MCP server connections.

    Parameters
    ----------
    servers:
        Optional list of server dicts (as persisted in settings) to
        pre-populate the registry on construction.
    """

    def __init__(self, servers: Optional[List[Dict[str, Any]]] = None) -> None:
        self._servers: Dict[str, MCPServer] = {}
        if servers:
            for s in servers:
                srv = MCPServer.from_dict(s)
                if srv.id:
                    self._servers[srv.id] = srv

    # ── CRUD ─────────────────────────────────────────────────────────────

    def add_server(
        self,
        name: str,
        url: str,
        description: str = "",
        enabled: bool = True,
    ) -> MCPServer:
        """Register a new MCP server and return the created entry."""
        server_id = uuid.uuid4().hex[:8]
        server = MCPServer(
            id          = server_id,
            name        = name.strip(),
            url         = url.strip().rstrip("/"),
            description = description.strip(),
            enabled     = enabled,
        )
        self._servers[server_id] = server
        return server

    def remove_server(self, server_id: str) -> bool:
        """Remove a server by ID.  Returns True if it existed."""
        return bool(self._servers.pop(server_id, None))

    def get_server(self, server_id: str) -> Optional[MCPServer]:
        return self._servers.get(server_id)

    def list_servers(self) -> List[MCPServer]:
        return list(self._servers.values())

    def update_server(
        self,
        server_id: str,
        *,
        name: Optional[str] = None,
        url: Optional[str] = None,
        enabled: Optional[bool] = None,
        description: Optional[str] = None,
    ) -> Optional[MCPServer]:
        """Partially update a server.  Returns the updated server or None."""
        server = self._servers.get(server_id)
        if not server:
            return None
        if name        is not None: server.name        = name.strip()
        if url         is not None: server.url         = url.strip().rstrip("/")
        if enabled     is not None: server.enabled     = enabled
        if description is not None: server.description = description.strip()
        return server

    # ── Serialisation ────────────────────────────────────────────────────

    def to_dict_list(self) -> List[Dict[str, Any]]:
        """Return all servers as a list of dicts (suitable for settings storage)."""
        return [s.to_dict() for s in self._servers.values()]

    # ── Probe ────────────────────────────────────────────────────────────

    def probe_server(
        self,
        server_id: str,
        timeout: int = 5,
    ) -> Dict[str, Any]:
        """Attempt to connect and discover tools from an MCP server.

        Tries ``GET {url}/tools`` first.  Falls back to ``GET {url}/``
        if /tools returns a non-200 status.

        Returns
        -------
        On success: ``{"status": "connected", "tools": [...], "tool_count": N}``
        On failure: ``{"status": "error", "error": "reason"}``
        """
        server = self._servers.get(server_id)
        if not server:
            return {"status": "error", "error": f"Server '{server_id}' not found"}

        try:
            tools = self._fetch_tools(server.url, timeout)
            server.tools  = tools
            server.status = "connected"
            server.error  = ""
            return {"status": "connected", "tools": tools, "tool_count": len(tools)}
        except urllib.error.URLError as exc:
            msg = str(exc.reason) if hasattr(exc, "reason") else str(exc)
            server.status = "error"
            server.error  = msg
            return {"status": "error", "error": msg}
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            server.status = "error"
            server.error  = msg
            return {"status": "error", "error": msg}

    @staticmethod
    def _fetch_tools(base_url: str, timeout: int) -> List[Dict[str, Any]]:
        """HTTP GET {base_url}/tools and parse the tool list."""
        url = f"{base_url}/tools"
        req = urllib.request.Request(
            url,
            headers={"Accept": "application/json", "User-Agent": "EnterpriseHarness/1.0"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")

        data = json.loads(raw)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("tools", [])
        return []
