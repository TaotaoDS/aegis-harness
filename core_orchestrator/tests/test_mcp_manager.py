"""Tests for MCPManager: registry CRUD, serialisation, probe behaviour.

All network calls are mocked — no real HTTP requests.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from core_orchestrator.mcp_manager import MCPManager, MCPServer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_manager(*urls: str) -> MCPManager:
    """Build a manager with pre-registered servers."""
    m = MCPManager()
    ids = []
    for i, url in enumerate(urls):
        srv = m.add_server(name=f"Server {i}", url=url)
        ids.append(srv.id)
    return m, ids


# ---------------------------------------------------------------------------
# TestMCPServer
# ---------------------------------------------------------------------------

class TestMCPServer:
    def test_defaults(self):
        s = MCPServer(id="abc", name="Test", url="http://localhost:3001")
        assert s.enabled is True
        assert s.status == "unknown"
        assert s.tools == []
        assert s.error == ""

    def test_to_dict_round_trip(self):
        s = MCPServer(
            id="abc123", name="My Server", url="http://srv:8080",
            enabled=False, description="desc", status="connected",
            tools=[{"name": "tool_a"}], error="",
        )
        d = s.to_dict()
        s2 = MCPServer.from_dict(d)
        assert s2.id          == s.id
        assert s2.name        == s.name
        assert s2.url         == s.url
        assert s2.enabled     == s.enabled
        assert s2.description == s.description
        assert s2.status      == s.status
        assert s2.tools       == s.tools

    def test_from_dict_strips_trailing_slash(self):
        s = MCPServer.from_dict({"id": "x", "name": "n", "url": "http://srv/"})
        assert s.url == "http://srv"

    def test_from_dict_missing_keys_use_defaults(self):
        s = MCPServer.from_dict({})
        assert s.id == ""
        assert s.enabled is True


# ---------------------------------------------------------------------------
# TestMCPManagerCRUD
# ---------------------------------------------------------------------------

class TestMCPManagerCRUD:
    def test_add_server_returns_server(self):
        m = MCPManager()
        srv = m.add_server("Alpha", "http://alpha:3000")
        assert srv.name == "Alpha"
        assert srv.url  == "http://alpha:3000"
        assert len(srv.id) == 8

    def test_add_server_strips_trailing_slash(self):
        m = MCPManager()
        srv = m.add_server("A", "http://a:3000/")
        assert srv.url == "http://a:3000"

    def test_list_returns_all_servers(self):
        m, _ = _make_manager("http://a:1", "http://b:2", "http://c:3")
        assert len(m.list_servers()) == 3

    def test_get_server_returns_correct(self):
        m = MCPManager()
        srv = m.add_server("X", "http://x:9")
        found = m.get_server(srv.id)
        assert found is srv

    def test_get_server_unknown_returns_none(self):
        m = MCPManager()
        assert m.get_server("no-such-id") is None

    def test_remove_server_returns_true(self):
        m = MCPManager()
        srv = m.add_server("R", "http://r:1")
        assert m.remove_server(srv.id) is True
        assert m.get_server(srv.id) is None

    def test_remove_unknown_returns_false(self):
        m = MCPManager()
        assert m.remove_server("ghost") is False

    def test_update_server_name(self):
        m = MCPManager()
        srv = m.add_server("Old", "http://srv:1")
        m.update_server(srv.id, name="New")
        assert m.get_server(srv.id).name == "New"

    def test_update_server_enabled_flag(self):
        m = MCPManager()
        srv = m.add_server("S", "http://s:1", enabled=True)
        m.update_server(srv.id, enabled=False)
        assert m.get_server(srv.id).enabled is False

    def test_update_unknown_returns_none(self):
        m = MCPManager()
        assert m.update_server("nope", name="X") is None


# ---------------------------------------------------------------------------
# TestMCPManagerSerialisation
# ---------------------------------------------------------------------------

class TestMCPManagerSerialisation:
    def test_empty_manager_to_dict_list(self):
        assert MCPManager().to_dict_list() == []

    def test_round_trip_via_dict_list(self):
        m1 = MCPManager()
        m1.add_server("A", "http://a:1", description="desc A")
        m1.add_server("B", "http://b:2", enabled=False)

        m2 = MCPManager(servers=m1.to_dict_list())
        servers = m2.list_servers()
        names = {s.name for s in servers}
        assert names == {"A", "B"}
        b = next(s for s in servers if s.name == "B")
        assert b.enabled is False

    def test_init_with_servers_param(self):
        servers = [
            {"id": "aaa", "name": "S1", "url": "http://s1:1"},
            {"id": "bbb", "name": "S2", "url": "http://s2:2"},
        ]
        m = MCPManager(servers=servers)
        assert len(m.list_servers()) == 2

    def test_init_ignores_entries_without_id(self):
        """Entries missing 'id' should be silently skipped."""
        m = MCPManager(servers=[{"name": "noid", "url": "http://x"}])
        assert len(m.list_servers()) == 0


# ---------------------------------------------------------------------------
# TestProbeServer
# ---------------------------------------------------------------------------

class TestProbeServer:
    def _make_mock_response(self, body: str, status: int = 200):
        mock_resp = MagicMock()
        mock_resp.read.return_value = body.encode("utf-8")
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        return mock_resp

    def test_probe_unknown_server_returns_error(self):
        m = MCPManager()
        result = m.probe_server("no-such-id")
        assert result["status"] == "error"

    def test_probe_success_list_response(self):
        m = MCPManager()
        srv = m.add_server("Good", "http://good:3000")
        tools_json = json.dumps([{"name": "tool_a"}, {"name": "tool_b"}])

        with patch("urllib.request.urlopen",
                   return_value=self._make_mock_response(tools_json)):
            result = m.probe_server(srv.id)

        assert result["status"] == "connected"
        assert result["tool_count"] == 2
        assert m.get_server(srv.id).status == "connected"

    def test_probe_success_dict_response(self):
        m = MCPManager()
        srv = m.add_server("Wrapped", "http://wrap:3000")
        tools_json = json.dumps({"tools": [{"name": "x"}], "version": "1.0"})

        with patch("urllib.request.urlopen",
                   return_value=self._make_mock_response(tools_json)):
            result = m.probe_server(srv.id)

        assert result["status"] == "connected"
        assert result["tool_count"] == 1

    def test_probe_connection_refused_returns_error(self):
        import urllib.error
        m = MCPManager()
        srv = m.add_server("Down", "http://down:9999")

        with patch("urllib.request.urlopen",
                   side_effect=urllib.error.URLError("Connection refused")):
            result = m.probe_server(srv.id)

        assert result["status"] == "error"
        assert m.get_server(srv.id).status == "error"

    def test_probe_updates_server_tools(self):
        m = MCPManager()
        srv = m.add_server("T", "http://t:1")
        tools_json = json.dumps([{"name": "calc"}, {"name": "search"}])

        with patch("urllib.request.urlopen",
                   return_value=self._make_mock_response(tools_json)):
            m.probe_server(srv.id)

        assert len(m.get_server(srv.id).tools) == 2
