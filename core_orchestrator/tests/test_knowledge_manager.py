"""Tests for KnowledgeManager: global knowledge base read/write."""

import pytest

from core_orchestrator.knowledge_manager import KnowledgeManager, KB_FILENAME
from core_orchestrator.workspace_manager import WorkspaceManager


@pytest.fixture
def workspace(tmp_path):
    wm = WorkspaceManager(tmp_path)
    wm.create("proj")
    return wm


@pytest.fixture
def km(workspace):
    return KnowledgeManager(workspace=workspace, workspace_id="proj")


# --- load_knowledge ---

class TestLoadKnowledge:
    def test_returns_empty_when_no_file(self, km):
        assert km.load_knowledge() == ""

    def test_returns_content_after_append(self, km):
        km.append_lesson(
            task_id="task_1",
            bug_root_cause="Missing imports",
            fix_description="Added import statement",
            avoidance_guide="Always check imports",
            date="2026-04-01",
        )
        content = km.load_knowledge()
        assert "task_1" in content
        assert "Missing imports" in content


# --- append_lesson ---

class TestAppendLesson:
    def test_creates_file_on_first_append(self, workspace, km):
        assert not workspace.exists("proj", KB_FILENAME)
        km.append_lesson(
            task_id="task_1",
            bug_root_cause="bug",
            fix_description="fix",
            avoidance_guide="guide",
            date="2026-04-01",
        )
        assert workspace.exists("proj", KB_FILENAME)

    def test_entry_contains_all_fields(self, km):
        km.append_lesson(
            task_id="task_2",
            bug_root_cause="Null pointer",
            fix_description="Added null check",
            avoidance_guide="Validate inputs",
            date="2026-04-01",
        )
        content = km.load_knowledge()
        assert "task_2" in content
        assert "Null pointer" in content
        assert "Added null check" in content
        assert "Validate inputs" in content
        assert "2026-04-01" in content

    def test_multiple_lessons_accumulated(self, km):
        km.append_lesson(task_id="t1", bug_root_cause="b1",
                         fix_description="f1", avoidance_guide="g1", date="2026-01-01")
        km.append_lesson(task_id="t2", bug_root_cause="b2",
                         fix_description="f2", avoidance_guide="g2", date="2026-01-02")
        content = km.load_knowledge()
        assert "t1" in content
        assert "t2" in content
        assert content.index("t1") < content.index("t2")  # chronological order

    def test_header_written_once(self, km):
        km.append_lesson(task_id="t1", bug_root_cause="b",
                         fix_description="f", avoidance_guide="g", date="2026-01-01")
        km.append_lesson(task_id="t2", bug_root_cause="b",
                         fix_description="f", avoidance_guide="g", date="2026-01-02")
        content = km.load_knowledge()
        assert content.count("Global Knowledge Base") == 1


# --- has_lessons ---

class TestHasLessons:
    def test_false_when_empty(self, km):
        assert km.has_lessons() is False

    def test_true_after_append(self, km):
        km.append_lesson(task_id="t1", bug_root_cause="b",
                         fix_description="f", avoidance_guide="g")
        assert km.has_lessons() is True
