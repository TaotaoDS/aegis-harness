"""Tests for architect agent — file-block protocol, write/read tools, knowledge injection."""

import json

import pytest

from core_orchestrator.architect_agent import ArchitectAgent, parse_file_blocks
from core_orchestrator.llm_gateway import LLMGateway
from core_orchestrator.workspace_manager import WorkspaceManager, WorkspaceError


# --- Helpers ---

TASK_1_CONTENT = (
    "# Design API schema\n\n"
    "- **ID:** task_1\n"
    "- **Priority:** high\n"
    "- **Description:** Define REST endpoints for user management\n"
)

TASK_2_CONTENT = (
    "# Implement backend\n\n"
    "- **ID:** task_2\n"
    "- **Priority:** high\n"
    "- **Description:** Build the service layer with FastAPI\n"
)

MOCK_FILE_BLOCK_RESPONSE = (
    "Here is the implementation:\n\n"
    "===FILE: index.html===\n"
    "<!DOCTYPE html>\n<html><body>Hello</body></html>\n"
    "===FILE: style.css===\n"
    "body { margin: 0; }\n"
    "===END==="
)

MOCK_SINGLE_FILE_RESPONSE = (
    "===FILE: app.py===\n"
    "print('hello world')\n"
    "===END==="
)


@pytest.fixture
def workspace(tmp_path):
    wm = WorkspaceManager(tmp_path)
    wm.create("proj")
    return wm


@pytest.fixture
def workspace_with_tasks(workspace):
    workspace.write("proj", "tasks/task_1.md", TASK_1_CONTENT)
    workspace.write("proj", "tasks/task_2.md", TASK_2_CONTENT)
    return workspace


def build_architect(workspace, llm_response="mock solution", knowledge_context="") -> ArchitectAgent:
    def mock_llm(text: str) -> str:
        return llm_response
    gateway = LLMGateway(llm=mock_llm)
    return ArchitectAgent(
        gateway=gateway, workspace=workspace, workspace_id="proj",
        knowledge_context=knowledge_context,
    )


# --- parse_file_blocks ---

class TestParseFileBlocks:
    def test_extracts_two_files(self):
        blocks = parse_file_blocks(MOCK_FILE_BLOCK_RESPONSE)
        assert "index.html" in blocks
        assert "style.css" in blocks

    def test_html_content(self):
        blocks = parse_file_blocks(MOCK_FILE_BLOCK_RESPONSE)
        assert "<!DOCTYPE html>" in blocks["index.html"]

    def test_css_content(self):
        blocks = parse_file_blocks(MOCK_FILE_BLOCK_RESPONSE)
        assert "margin: 0" in blocks["style.css"]

    def test_single_file(self):
        blocks = parse_file_blocks(MOCK_SINGLE_FILE_RESPONSE)
        assert "app.py" in blocks
        assert "hello world" in blocks["app.py"]

    def test_empty_input(self):
        assert parse_file_blocks("") == {}

    def test_no_file_markers(self):
        assert parse_file_blocks("just regular text\nno markers") == {}

    def test_path_with_subdirectory(self):
        text = "===FILE: src/js/app.js===\nconsole.log('hi');\n===END==="
        blocks = parse_file_blocks(text)
        assert "src/js/app.js" in blocks

    def test_strips_quotes_from_path(self):
        text = "===FILE: `main.py`===\npass\n===END==="
        blocks = parse_file_blocks(text)
        assert "main.py" in blocks


# --- File tools ---

class TestFileTools:
    def test_write_file(self, workspace):
        arch = build_architect(workspace)
        arch.write_file("src/test.txt", "hello")
        assert workspace.read("proj", "src/test.txt") == "hello"

    def test_read_file(self, workspace):
        workspace.write("proj", "src/data.txt", "content")
        arch = build_architect(workspace)
        assert arch.read_file("src/data.txt") == "content"

    def test_file_exists_true(self, workspace):
        workspace.write("proj", "src/x.txt", "y")
        arch = build_architect(workspace)
        assert arch.file_exists("src/x.txt") is True

    def test_file_exists_false(self, workspace):
        arch = build_architect(workspace)
        assert arch.file_exists("src/nope.txt") is False


# --- List tasks ---

class TestListTasks:
    def test_lists_task_files(self, workspace_with_tasks):
        arch = build_architect(workspace_with_tasks)
        tasks = arch.list_tasks()
        assert sorted(tasks) == ["tasks/task_1.md", "tasks/task_2.md"]

    def test_empty_when_no_tasks_dir(self, workspace):
        arch = build_architect(workspace)
        assert arch.list_tasks() == []

    def test_only_md_files(self, workspace):
        workspace.write("proj", "tasks/task_1.md", TASK_1_CONTENT)
        workspace.write("proj", "tasks/notes.txt", "random notes")
        arch = build_architect(workspace)
        assert arch.list_tasks() == ["tasks/task_1.md"]


# --- Solve task with file blocks ---

class TestSolveTask:
    def test_returns_artifact_path(self, workspace_with_tasks):
        arch = build_architect(workspace_with_tasks, llm_response=MOCK_FILE_BLOCK_RESPONSE)
        path = arch.solve_task("tasks/task_1.md")
        assert path == "artifacts/task_1_solution.md"

    def test_writes_code_files_to_workspace(self, workspace_with_tasks):
        arch = build_architect(workspace_with_tasks, llm_response=MOCK_FILE_BLOCK_RESPONSE)
        arch.solve_task("tasks/task_1.md")
        assert workspace_with_tasks.exists("proj", "src/index.html")
        assert workspace_with_tasks.exists("proj", "src/style.css")

    def test_artifact_lists_written_files(self, workspace_with_tasks):
        arch = build_architect(workspace_with_tasks, llm_response=MOCK_FILE_BLOCK_RESPONSE)
        arch.solve_task("tasks/task_1.md")
        content = workspace_with_tasks.read("proj", "artifacts/task_1_solution.md")
        assert "Written Files" in content
        assert "index.html" in content

    def test_no_file_blocks_still_writes_artifact(self, workspace_with_tasks):
        arch = build_architect(workspace_with_tasks, llm_response="plain text solution")
        arch.solve_task("tasks/task_1.md")
        assert workspace_with_tasks.exists("proj", "artifacts/task_1_solution.md")

    def test_prompt_includes_task_content(self, workspace_with_tasks):
        prompts = []
        def capture_llm(text: str) -> str:
            prompts.append(text)
            return "solution"
        gateway = LLMGateway(llm=capture_llm)
        arch = ArchitectAgent(gateway=gateway, workspace=workspace_with_tasks, workspace_id="proj")
        arch.solve_task("tasks/task_1.md")
        assert any("Design API schema" in p for p in prompts)

    def test_prompt_includes_plan_context(self, workspace_with_tasks):
        workspace_with_tasks.write("proj", "plan.md", "# Plan\n## task_1: Design API")
        prompts = []
        def capture_llm(text: str) -> str:
            prompts.append(text)
            return "solution"
        gateway = LLMGateway(llm=capture_llm)
        arch = ArchitectAgent(gateway=gateway, workspace=workspace_with_tasks, workspace_id="proj")
        arch.solve_task("tasks/task_1.md")
        assert any("Plan" in p for p in prompts)

    def test_nonexistent_task_raises(self, workspace):
        arch = build_architect(workspace)
        with pytest.raises(WorkspaceError):
            arch.solve_task("tasks/ghost.md")

    def test_prompt_includes_feedback(self, workspace_with_tasks):
        workspace_with_tasks.write("proj", "feedback/task_1_feedback.md", "Missing auth handling")
        prompts = []
        def capture_llm(text: str) -> str:
            prompts.append(text)
            return "solution"
        gateway = LLMGateway(llm=capture_llm)
        arch = ArchitectAgent(gateway=gateway, workspace=workspace_with_tasks, workspace_id="proj")
        arch.solve_task("tasks/task_1.md")
        assert any("Missing auth" in p for p in prompts)


# --- Knowledge context injection ---

class TestKnowledgeInjection:
    def test_knowledge_injected_into_prompt(self, workspace_with_tasks):
        prompts = []
        def capture_llm(text: str) -> str:
            prompts.append(text)
            return "solution"
        gateway = LLMGateway(llm=capture_llm)
        arch = ArchitectAgent(
            gateway=gateway, workspace=workspace_with_tasks, workspace_id="proj",
            knowledge_context="Always use devicePixelRatio for canvas.",
        )
        arch.solve_task("tasks/task_1.md")
        assert any("devicePixelRatio" in p for p in prompts)

    def test_empty_knowledge_no_section(self, workspace_with_tasks):
        prompts = []
        def capture_llm(text: str) -> str:
            prompts.append(text)
            return "solution"
        gateway = LLMGateway(llm=capture_llm)
        arch = ArchitectAgent(
            gateway=gateway, workspace=workspace_with_tasks, workspace_id="proj",
            knowledge_context="",
        )
        arch.solve_task("tasks/task_1.md")
        assert not any("Knowledge Base" in p for p in prompts)


# --- Solve all ---

class TestSolveAll:
    def test_returns_all_artifact_paths(self, workspace_with_tasks):
        arch = build_architect(workspace_with_tasks, llm_response="solution")
        paths = arch.solve_all()
        assert sorted(paths) == ["artifacts/task_1_solution.md", "artifacts/task_2_solution.md"]

    def test_empty_tasks_returns_empty(self, workspace):
        arch = build_architect(workspace, llm_response="solution")
        assert arch.solve_all() == []


# --- get_written_files ---

class TestGetWrittenFiles:
    def test_returns_written_files(self, workspace_with_tasks):
        arch = build_architect(workspace_with_tasks, llm_response=MOCK_FILE_BLOCK_RESPONSE)
        arch.solve_task("tasks/task_1.md")
        files = arch.get_written_files("task_1")
        assert "index.html" in files
        assert "style.css" in files

    def test_empty_when_no_artifact(self, workspace):
        arch = build_architect(workspace)
        assert arch.get_written_files("task_999") == []

    def test_empty_when_no_file_blocks(self, workspace_with_tasks):
        arch = build_architect(workspace_with_tasks, llm_response="plain text")
        arch.solve_task("tasks/task_1.md")
        assert arch.get_written_files("task_1") == []
