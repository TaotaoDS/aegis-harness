"""Tests for web_browser.py — all tests use mocked Playwright (no real network)."""

import json
import pathlib
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import pytest

from core_orchestrator.web_browser import (
    WebBrowserError,
    SEARCH_WEB_TOOL,
    READ_URL_TOOL,
    _html_to_text,
    search_web,
    read_url,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_launch_mock(anchors=None, page_html="<html><body><p>Hello</p></body></html>",
                      page_title="Test Page"):
    """Return a (mock_launch_fn, mock_browser, mock_context) triple.

    Patches _launch_browser (the private factory) rather than sync_playwright,
    because sync_playwright is a local import inside _launch_browser and is not
    present in the module namespace.
    """
    mock_anchor = MagicMock()
    mock_anchor.inner_text.return_value = "Result Title"
    mock_anchor.get_attribute.return_value = "https://example.com/result"

    anchors = anchors if anchors is not None else [mock_anchor]

    mock_page = MagicMock()
    mock_page.query_selector_all.return_value = anchors
    mock_page.content.return_value = page_html
    mock_page.title.return_value = page_title

    mock_context = MagicMock()
    mock_context.new_page.return_value = mock_page

    mock_browser = MagicMock()
    mock_pw = MagicMock()

    def mock_launch():
        return mock_pw, mock_browser, mock_context

    return mock_launch, mock_browser, mock_context, mock_pw


def _make_workspace():
    """Create a temporary WorkspaceManager with a 'proj' workspace."""
    from core_orchestrator.workspace_manager import WorkspaceManager
    tmp = pathlib.Path(tempfile.mkdtemp())
    ws = WorkspaceManager(tmp)
    ws.create("proj")
    return ws


def _make_architect(ws, enable_web_tools=False, tool_calls=None):
    """Build an ArchitectAgent with a stub tool_llm."""
    from core_orchestrator.architect_agent import ArchitectAgent
    _calls = tool_calls if tool_calls is not None else []

    def mock_tool_llm(system, user_prompt, tools, tool_handler=None):
        return _calls

    return ArchitectAgent(
        tool_llm=mock_tool_llm, workspace=ws, workspace_id="proj",
        enable_web_tools=enable_web_tools,
    )


# ---------------------------------------------------------------------------
# TestWebBrowserError
# ---------------------------------------------------------------------------

class TestWebBrowserError(unittest.TestCase):
    def test_is_exception_subclass(self):
        assert issubclass(WebBrowserError, Exception)

    def test_retryable_default_false(self):
        assert WebBrowserError("boom").retryable is False

    def test_retryable_true(self):
        assert WebBrowserError("timeout", retryable=True).retryable is True

    def test_message_preserved(self):
        assert str(WebBrowserError("network error")) == "network error"


# ---------------------------------------------------------------------------
# TestHtmlToText
# ---------------------------------------------------------------------------

class TestHtmlToText(unittest.TestCase):
    def test_strips_script_tags(self):
        html = "<html><body><script>alert(1)</script><p>Hello</p></body></html>"
        result = _html_to_text(html, "Title")
        assert "alert" not in result
        assert "Hello" in result

    def test_strips_style_tags(self):
        html = "<html><head><style>body{color:red}</style></head><body><p>Content</p></body></html>"
        result = _html_to_text(html, "Title")
        assert "color:red" not in result
        assert "Content" in result

    def test_strips_nav_tags(self):
        html = "<html><body><nav>Menu</nav><main><p>Article</p></main></body></html>"
        result = _html_to_text(html, "Title")
        assert "Menu" not in result
        assert "Article" in result

    def test_strips_aria_banner(self):
        html = '<html><body><div role="banner">Header</div><p>Body</p></body></html>'
        result = _html_to_text(html, "Title")
        assert "Header" not in result
        assert "Body" in result

    def test_prepends_title_as_h1(self):
        html = "<html><body><p>Content</p></body></html>"
        assert _html_to_text(html, "My Page").startswith("# My Page")

    def test_collapses_blank_lines(self):
        html = "<html><body><p>A</p><p>B</p><p>C</p></body></html>"
        assert "\n\n\n" not in _html_to_text(html, "T")


# ---------------------------------------------------------------------------
# TestSearchWeb
# ---------------------------------------------------------------------------

class TestSearchWeb(unittest.TestCase):

    @patch("core_orchestrator.web_browser.time.sleep")
    def test_happy_path_returns_valid_json(self, _sleep):
        mock_launch, _, _, _ = _make_launch_mock()
        with patch("core_orchestrator.web_browser._launch_browser", mock_launch):
            result = search_web("python fastapi")

        data = json.loads(result)
        assert "results" in data
        assert len(data["results"]) == 1
        assert data["results"][0]["title"] == "Result Title"
        assert data["results"][0]["url"] == "https://example.com/result"

    def test_unsupported_engine_raises_not_retryable(self):
        with pytest.raises(WebBrowserError) as exc_info:
            search_web("query", engine="duckduckgo")
        assert exc_info.value.retryable is False

    @patch("core_orchestrator.web_browser.time.sleep")
    def test_navigation_failure_raises_retryable(self, _sleep):
        mock_launch, _, mock_context, _ = _make_launch_mock()
        mock_context.new_page.return_value.goto.side_effect = Exception("ERR_NAME_NOT_RESOLVED")
        with patch("core_orchestrator.web_browser._launch_browser", mock_launch):
            with pytest.raises(WebBrowserError) as exc_info:
                search_web("query")
        assert exc_info.value.retryable is True

    @patch("core_orchestrator.web_browser.time.sleep")
    def test_no_results_raises_not_retryable(self, _sleep):
        mock_launch, _, _, _ = _make_launch_mock(anchors=[])
        with patch("core_orchestrator.web_browser._launch_browser", mock_launch):
            with pytest.raises(WebBrowserError) as exc_info:
                search_web("query")
        assert exc_info.value.retryable is False

    @patch("core_orchestrator.web_browser.time.sleep")
    def test_num_results_capped_at_10(self, _sleep):
        anchors = []
        for i in range(20):
            a = MagicMock()
            a.inner_text.return_value = f"Title {i}"
            a.get_attribute.return_value = f"https://example.com/{i}"
            anchors.append(a)

        mock_launch, _, _, _ = _make_launch_mock(anchors=anchors)
        with patch("core_orchestrator.web_browser._launch_browser", mock_launch):
            result = search_web("query", num_results=99)

        assert len(json.loads(result)["results"]) <= 10

    @patch("core_orchestrator.web_browser.time.sleep")
    def test_browser_closed_on_success(self, _sleep):
        mock_launch, mock_browser, mock_context, mock_pw = _make_launch_mock()
        with patch("core_orchestrator.web_browser._launch_browser", mock_launch):
            search_web("query")

        mock_context.close.assert_called_once()
        mock_browser.close.assert_called_once()
        mock_pw.stop.assert_called_once()

    @patch("core_orchestrator.web_browser.time.sleep")
    def test_browser_closed_on_navigation_exception(self, _sleep):
        mock_launch, mock_browser, mock_context, _ = _make_launch_mock()
        mock_context.new_page.return_value.goto.side_effect = Exception("fail")
        with patch("core_orchestrator.web_browser._launch_browser", mock_launch):
            with pytest.raises(WebBrowserError):
                search_web("query")

        mock_context.close.assert_called_once()
        mock_browser.close.assert_called_once()

    @patch("core_orchestrator.web_browser.time.sleep")
    def test_sogou_engine_uses_different_selector(self, _sleep):
        mock_launch, _, mock_context, _ = _make_launch_mock()
        mock_page = mock_context.new_page.return_value
        with patch("core_orchestrator.web_browser._launch_browser", mock_launch):
            search_web("query", engine="sogou")

        selector_arg = mock_page.query_selector_all.call_args[0][0]
        assert "vrwrap" in selector_arg


# ---------------------------------------------------------------------------
# TestReadUrl
# ---------------------------------------------------------------------------

class TestReadUrl(unittest.TestCase):

    def test_invalid_scheme_raises_not_retryable(self):
        with pytest.raises(WebBrowserError) as exc_info:
            read_url("ftp://example.com")
        assert exc_info.value.retryable is False

    def test_no_scheme_raises_not_retryable(self):
        with pytest.raises(WebBrowserError) as exc_info:
            read_url("example.com/page")
        assert exc_info.value.retryable is False

    @patch("core_orchestrator.web_browser.time.sleep")
    def test_happy_path_returns_text(self, _sleep):
        html = "<html><body><script>bad()</script><p>Good content here</p></body></html>"
        mock_launch, _, _, _ = _make_launch_mock(page_html=html, page_title="My Page")
        with patch("core_orchestrator.web_browser._launch_browser", mock_launch):
            result = read_url("https://example.com/page")

        assert "Good content here" in result
        assert "bad()" not in result
        assert result.startswith("# My Page")

    @patch("core_orchestrator.web_browser.time.sleep")
    def test_output_capped_at_4000_chars(self, _sleep):
        long_text = "x" * 10_000
        html = f"<html><body><p>{long_text}</p></body></html>"
        mock_launch, _, _, _ = _make_launch_mock(page_html=html)
        with patch("core_orchestrator.web_browser._launch_browser", mock_launch):
            result = read_url("https://example.com")
        assert len(result) <= 4_000

    @patch("core_orchestrator.web_browser.time.sleep")
    def test_navigation_failure_raises_retryable(self, _sleep):
        mock_launch, _, mock_context, _ = _make_launch_mock()
        mock_context.new_page.return_value.goto.side_effect = Exception("timeout")
        with patch("core_orchestrator.web_browser._launch_browser", mock_launch):
            with pytest.raises(WebBrowserError) as exc_info:
                read_url("https://example.com")
        assert exc_info.value.retryable is True

    @patch("core_orchestrator.web_browser.time.sleep")
    def test_empty_content_raises_not_retryable(self, _sleep):
        mock_launch, _, _, _ = _make_launch_mock()
        with patch("core_orchestrator.web_browser._launch_browser", mock_launch):
            with patch("core_orchestrator.web_browser._html_to_text", return_value="   "):
                with pytest.raises(WebBrowserError) as exc_info:
                    read_url("https://example.com")
        assert exc_info.value.retryable is False

    @patch("core_orchestrator.web_browser.time.sleep")
    def test_browser_closed_on_success(self, _sleep):
        mock_launch, mock_browser, mock_context, mock_pw = _make_launch_mock()
        with patch("core_orchestrator.web_browser._launch_browser", mock_launch):
            read_url("https://example.com")

        mock_context.close.assert_called_once()
        mock_browser.close.assert_called_once()
        mock_pw.stop.assert_called_once()

    @patch("core_orchestrator.web_browser.time.sleep")
    def test_browser_closed_on_exception(self, _sleep):
        mock_launch, mock_browser, mock_context, _ = _make_launch_mock()
        mock_context.new_page.return_value.goto.side_effect = Exception("fail")
        with patch("core_orchestrator.web_browser._launch_browser", mock_launch):
            with pytest.raises(WebBrowserError):
                read_url("https://example.com")

        mock_context.close.assert_called_once()
        mock_browser.close.assert_called_once()


# ---------------------------------------------------------------------------
# TestToolDicts
# ---------------------------------------------------------------------------

class TestToolDicts(unittest.TestCase):
    def test_search_web_tool_has_required_fields(self):
        for field in ("name", "description", "parameters"):
            assert field in SEARCH_WEB_TOOL
        assert SEARCH_WEB_TOOL["name"] == "search_web"
        assert "query" in SEARCH_WEB_TOOL["parameters"]["required"]

    def test_read_url_tool_has_required_fields(self):
        for field in ("name", "description", "parameters"):
            assert field in READ_URL_TOOL
        assert READ_URL_TOOL["name"] == "read_url"
        assert "url" in READ_URL_TOOL["parameters"]["required"]

    def test_search_web_engine_enum(self):
        props = SEARCH_WEB_TOOL["parameters"]["properties"]
        assert set(props["engine"]["enum"]) == {"bing", "sogou"}

    def test_num_results_bounds(self):
        props = SEARCH_WEB_TOOL["parameters"]["properties"]
        assert props["num_results"]["minimum"] == 1
        assert props["num_results"]["maximum"] == 10


# ---------------------------------------------------------------------------
# TestArchitectAgentWebToolIntegration
# ---------------------------------------------------------------------------

class TestArchitectAgentWebToolIntegration(unittest.TestCase):
    """Test _tool_handler dispatch and tool list assembly in ArchitectAgent."""

    _TASK_CONTENT = "# Task\n- **ID:** task_1\n- **Description:** test\n"

    def _ws_with_task(self):
        ws = _make_workspace()
        ws.write("proj", "tasks/task_1.md", self._TASK_CONTENT)
        return ws

    def test_web_tools_absent_when_disabled(self):
        captured = {}
        ws = self._ws_with_task()

        from core_orchestrator.architect_agent import ArchitectAgent

        def mock_llm(system, user_prompt, tools, tool_handler=None):
            captured["tools"] = tools
            return []

        arch = ArchitectAgent(tool_llm=mock_llm, workspace=ws, workspace_id="proj",
                              enable_web_tools=False)
        arch.solve_task("tasks/task_1.md")

        names = [t["name"] for t in captured["tools"]]
        assert "search_web" not in names
        assert "read_url" not in names

    def test_web_tools_present_when_enabled(self):
        captured = {}
        ws = self._ws_with_task()

        from core_orchestrator.architect_agent import ArchitectAgent

        def mock_llm(system, user_prompt, tools, tool_handler=None):
            captured["tools"] = tools
            return []

        arch = ArchitectAgent(tool_llm=mock_llm, workspace=ws, workspace_id="proj",
                              enable_web_tools=True)
        arch.solve_task("tasks/task_1.md")

        names = [t["name"] for t in captured["tools"]]
        assert "search_web" in names
        assert "read_url" in names

    def test_tool_handler_dispatches_search_web(self):
        ws = _make_workspace()
        arch = _make_architect(ws, enable_web_tools=True)

        fake = json.dumps({"results": [{"title": "T", "url": "https://x.com"}]})
        with patch("core_orchestrator.architect_agent.search_web", return_value=fake):
            result = arch._tool_handler("search_web", {"query": "fastapi"})

        data = json.loads(result)
        assert data["results"][0]["title"] == "T"

    def test_tool_handler_dispatches_read_url(self):
        ws = _make_workspace()
        arch = _make_architect(ws, enable_web_tools=True)

        with patch("core_orchestrator.architect_agent.read_url", return_value="# Page\n\nContent"):
            result = arch._tool_handler("read_url", {"url": "https://example.com"})

        data = json.loads(result)
        assert "content" in data
        assert "Content" in data["content"]

    def test_tool_handler_returns_json_error_on_search_browser_error(self):
        ws = _make_workspace()
        arch = _make_architect(ws, enable_web_tools=True)

        with patch("core_orchestrator.architect_agent.search_web",
                   side_effect=WebBrowserError("blocked", retryable=False)):
            result = arch._tool_handler("search_web", {"query": "test"})

        data = json.loads(result)
        assert "error" in data
        assert data["retryable"] is False

    def test_tool_handler_does_not_raise_on_read_url_browser_error(self):
        ws = _make_workspace()
        arch = _make_architect(ws, enable_web_tools=True)

        with patch("core_orchestrator.architect_agent.read_url",
                   side_effect=WebBrowserError("timeout", retryable=True)):
            result = arch._tool_handler("read_url", {"url": "https://example.com"})

        data = json.loads(result)
        assert "error" in data
        assert data["retryable"] is True

    def test_write_file_still_works_when_web_enabled(self):
        ws = self._ws_with_task()

        from core_orchestrator.architect_agent import ArchitectAgent
        from core_orchestrator.llm_connector import ToolCall

        calls = [ToolCall(name="write_file", arguments={"filepath": "out.py", "content": "x=1"})]

        def mock_llm(system, user_prompt, tools, tool_handler=None):
            return calls

        arch = ArchitectAgent(tool_llm=mock_llm, workspace=ws, workspace_id="proj",
                              enable_web_tools=True)
        arch.solve_task("tasks/task_1.md")
        assert ws.exists("proj", "deliverables/out.py")
