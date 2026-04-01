"""Tests for shared workspace manager."""

import pytest

from core_orchestrator.workspace_manager import WorkspaceManager, WorkspaceError


@pytest.fixture
def wm(tmp_path):
    """Create a WorkspaceManager rooted in a temp directory."""
    return WorkspaceManager(tmp_path)


# --- Create ---

class TestCreate:
    def test_create_workspace(self, wm):
        wm.create("task_001")
        assert wm.exists("task_001")

    def test_create_is_idempotent(self, wm):
        wm.create("task_001")
        wm.create("task_001")  # no error
        assert wm.exists("task_001")

    def test_create_multiple_workspaces(self, wm):
        wm.create("a")
        wm.create("b")
        assert wm.exists("a")
        assert wm.exists("b")


# --- Write & Read ---

class TestWriteRead:
    def test_write_and_read(self, wm):
        wm.create("ws")
        wm.write("ws", "plan.md", "# Plan\nStep 1")
        assert wm.read("ws", "plan.md") == "# Plan\nStep 1"

    def test_write_overwrites(self, wm):
        wm.create("ws")
        wm.write("ws", "plan.md", "v1")
        wm.write("ws", "plan.md", "v2")
        assert wm.read("ws", "plan.md") == "v2"

    def test_write_creates_subdirectories(self, wm):
        wm.create("ws")
        wm.write("ws", "artifacts/report.txt", "data")
        assert wm.read("ws", "artifacts/report.txt") == "data"

    def test_read_nonexistent_file_raises(self, wm):
        wm.create("ws")
        with pytest.raises(WorkspaceError, match="not found"):
            wm.read("ws", "ghost.md")

    def test_write_to_nonexistent_workspace_raises(self, wm):
        with pytest.raises(WorkspaceError, match="not found"):
            wm.write("nope", "file.md", "content")

    def test_read_from_nonexistent_workspace_raises(self, wm):
        with pytest.raises(WorkspaceError, match="not found"):
            wm.read("nope", "file.md")

    def test_unicode_content(self, wm):
        wm.create("ws")
        content = "中文测试内容\n日本語テスト\nemoji 🚀"
        wm.write("ws", "i18n.md", content)
        assert wm.read("ws", "i18n.md") == content

    def test_empty_content(self, wm):
        wm.create("ws")
        wm.write("ws", "empty.md", "")
        assert wm.read("ws", "empty.md") == ""


# --- List files ---

class TestListFiles:
    def test_list_empty_workspace(self, wm):
        wm.create("ws")
        assert wm.list_files("ws") == []

    def test_list_files(self, wm):
        wm.create("ws")
        wm.write("ws", "plan.md", "plan")
        wm.write("ws", "feedback.md", "feedback")
        files = sorted(wm.list_files("ws"))
        assert files == ["feedback.md", "plan.md"]

    def test_list_includes_nested_files(self, wm):
        wm.create("ws")
        wm.write("ws", "top.md", "x")
        wm.write("ws", "sub/deep.md", "y")
        files = sorted(wm.list_files("ws"))
        assert "top.md" in files
        assert "sub/deep.md" in files

    def test_list_nonexistent_workspace_raises(self, wm):
        with pytest.raises(WorkspaceError, match="not found"):
            wm.list_files("nope")


# --- Exists ---

class TestExists:
    def test_workspace_exists(self, wm):
        assert not wm.exists("ws")
        wm.create("ws")
        assert wm.exists("ws")

    def test_file_exists(self, wm):
        wm.create("ws")
        assert not wm.exists("ws", "plan.md")
        wm.write("ws", "plan.md", "x")
        assert wm.exists("ws", "plan.md")


# --- Delete ---

class TestDelete:
    def test_delete_file(self, wm):
        wm.create("ws")
        wm.write("ws", "plan.md", "x")
        wm.delete("ws", "plan.md")
        assert not wm.exists("ws", "plan.md")

    def test_delete_nonexistent_file_raises(self, wm):
        wm.create("ws")
        with pytest.raises(WorkspaceError, match="not found"):
            wm.delete("ws", "ghost.md")

    def test_delete_from_nonexistent_workspace_raises(self, wm):
        with pytest.raises(WorkspaceError, match="not found"):
            wm.delete("nope", "file.md")


# --- Isolation ---

class TestIsolation:
    def test_workspaces_are_isolated(self, wm):
        wm.create("agent_a")
        wm.create("agent_b")
        wm.write("agent_a", "state.md", "a's data")
        wm.write("agent_b", "state.md", "b's data")
        assert wm.read("agent_a", "state.md") == "a's data"
        assert wm.read("agent_b", "state.md") == "b's data"

    def test_list_only_own_files(self, wm):
        wm.create("agent_a")
        wm.create("agent_b")
        wm.write("agent_a", "a.md", "x")
        wm.write("agent_b", "b.md", "y")
        assert wm.list_files("agent_a") == ["a.md"]
        assert wm.list_files("agent_b") == ["b.md"]


# --- Path traversal prevention ---

class TestPathSafety:
    def test_workspace_id_traversal_blocked(self, wm):
        with pytest.raises(WorkspaceError, match="[Ii]nvalid"):
            wm.create("../escape")

    def test_filename_traversal_blocked(self, wm):
        wm.create("ws")
        with pytest.raises(WorkspaceError, match="[Ii]nvalid"):
            wm.write("ws", "../../etc/passwd", "evil")

    def test_read_traversal_blocked(self, wm):
        wm.create("ws")
        with pytest.raises(WorkspaceError, match="[Ii]nvalid"):
            wm.read("ws", "../other_ws/secret.md")

    def test_absolute_path_blocked(self, wm):
        wm.create("ws")
        with pytest.raises(WorkspaceError, match="[Ii]nvalid"):
            wm.write("ws", "/etc/passwd", "evil")

    def test_workspace_id_with_slashes_blocked(self, wm):
        with pytest.raises(WorkspaceError, match="[Ii]nvalid"):
            wm.create("a/b/c")
