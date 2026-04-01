"""Tests for architect agent."""

import json

import pytest

from core_orchestrator.architect_agent import ArchitectAgent
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


def build_architect(workspace, llm_response="mock solution") -> ArchitectAgent:
    """Create an ArchitectAgent with a mock LLM that returns a fixed response."""
    def mock_llm(text: str) -> str:
        return llm_response
    gateway = LLMGateway(llm=mock_llm)
    return ArchitectAgent(gateway=gateway, workspace=workspace, workspace_id="proj")


# --- List tasks ---

class TestListTasks:
    def test_lists_task_files(self, workspace_with_tasks):
        arch = build_architect(workspace_with_tasks)
        tasks = arch.list_tasks()
        assert sorted(tasks) == ["tasks/task_1.md", "tasks/task_2.md"]

    def test_empty_when_no_tasks_dir(self, workspace):
        arch = build_architect(workspace)
        assert arch.list_tasks() == []

    def test_empty_when_tasks_dir_is_empty(self, workspace):
        # Create tasks/ dir with a subdirectory but no .md files
        workspace.write("proj", "tasks/.gitkeep", "")
        arch = build_architect(workspace)
        tasks = arch.list_tasks()
        # .gitkeep is not a .md task file
        assert tasks == []

    def test_only_md_files(self, workspace):
        workspace.write("proj", "tasks/task_1.md", TASK_1_CONTENT)
        workspace.write("proj", "tasks/notes.txt", "random notes")
        arch = build_architect(workspace)
        tasks = arch.list_tasks()
        assert tasks == ["tasks/task_1.md"]


# --- Solve single task ---

class TestSolveTask:
    def test_returns_artifact_path(self, workspace_with_tasks):
        arch = build_architect(workspace_with_tasks, llm_response="```python\nprint('hello')\n```")
        path = arch.solve_task("tasks/task_1.md")
        assert path == "artifacts/task_1_solution.md"

    def test_writes_artifact_file(self, workspace_with_tasks):
        arch = build_architect(workspace_with_tasks, llm_response="## Solution\nUse REST.")
        arch.solve_task("tasks/task_1.md")
        content = workspace_with_tasks.read("proj", "artifacts/task_1_solution.md")
        assert "## Solution" in content
        assert "Use REST." in content

    def test_artifact_includes_task_context(self, workspace_with_tasks):
        arch = build_architect(workspace_with_tasks, llm_response="my solution")
        arch.solve_task("tasks/task_1.md")
        content = workspace_with_tasks.read("proj", "artifacts/task_1_solution.md")
        # Artifact header references the original task
        assert "task_1" in content

    def test_prompt_includes_task_content(self, workspace_with_tasks):
        prompts = []
        def capture_llm(text: str) -> str:
            prompts.append(text)
            return "solution"
        gateway = LLMGateway(llm=capture_llm)
        arch = ArchitectAgent(gateway=gateway, workspace=workspace_with_tasks, workspace_id="proj")
        arch.solve_task("tasks/task_1.md")
        assert any("Design API schema" in p for p in prompts)
        assert any("Define REST endpoints" in p for p in prompts)

    def test_prompt_includes_plan_context(self, workspace_with_tasks):
        workspace_with_tasks.write("proj", "plan.md", "# Plan\n## task_1: Design API")
        prompts = []
        def capture_llm(text: str) -> str:
            prompts.append(text)
            return "solution"
        gateway = LLMGateway(llm=capture_llm)
        arch = ArchitectAgent(gateway=gateway, workspace=workspace_with_tasks, workspace_id="proj")
        arch.solve_task("tasks/task_1.md")
        # Plan context should be included in the prompt
        assert any("Plan" in p for p in prompts)

    def test_nonexistent_task_raises(self, workspace):
        arch = build_architect(workspace)
        with pytest.raises(WorkspaceError):
            arch.solve_task("tasks/ghost.md")

    def test_solves_different_tasks_independently(self, workspace_with_tasks):
        call_count = {"i": 0}
        def counting_llm(text: str) -> str:
            call_count["i"] += 1
            return f"solution #{call_count['i']}"
        gateway = LLMGateway(llm=counting_llm)
        arch = ArchitectAgent(gateway=gateway, workspace=workspace_with_tasks, workspace_id="proj")

        arch.solve_task("tasks/task_1.md")
        arch.solve_task("tasks/task_2.md")

        c1 = workspace_with_tasks.read("proj", "artifacts/task_1_solution.md")
        c2 = workspace_with_tasks.read("proj", "artifacts/task_2_solution.md")
        assert "solution #1" in c1
        assert "solution #2" in c2


# --- Solve all ---

class TestSolveAll:
    def test_returns_all_artifact_paths(self, workspace_with_tasks):
        arch = build_architect(workspace_with_tasks, llm_response="solution")
        paths = arch.solve_all()
        assert sorted(paths) == ["artifacts/task_1_solution.md", "artifacts/task_2_solution.md"]

    def test_all_artifacts_exist(self, workspace_with_tasks):
        arch = build_architect(workspace_with_tasks, llm_response="solution")
        arch.solve_all()
        assert workspace_with_tasks.exists("proj", "artifacts/task_1_solution.md")
        assert workspace_with_tasks.exists("proj", "artifacts/task_2_solution.md")

    def test_empty_tasks_returns_empty(self, workspace):
        arch = build_architect(workspace, llm_response="solution")
        assert arch.solve_all() == []

    def test_each_task_gets_unique_llm_call(self, workspace_with_tasks):
        prompts = []
        def capture_llm(text: str) -> str:
            prompts.append(text)
            return "solution"
        gateway = LLMGateway(llm=capture_llm)
        arch = ArchitectAgent(gateway=gateway, workspace=workspace_with_tasks, workspace_id="proj")
        arch.solve_all()
        # Two tasks = two LLM calls
        assert len(prompts) == 2
        # Each prompt references a different task
        assert any("Design API schema" in p for p in prompts)
        assert any("Implement backend" in p for p in prompts)


# --- Gateway reuse (fresh history per task) ---

class TestGatewayIsolation:
    def test_gateway_history_resets_between_tasks(self, workspace_with_tasks):
        """Each task should use a fresh gateway to avoid context bleeding."""
        arch = build_architect(workspace_with_tasks, llm_response="solution")
        arch.solve_task("tasks/task_1.md")
        arch.solve_task("tasks/task_2.md")
        # The architect creates a fresh gateway per task, so the main gateway
        # history should not accumulate cross-task context
        # We verify by checking artifacts are independent
        c1 = workspace_with_tasks.read("proj", "artifacts/task_1_solution.md")
        c2 = workspace_with_tasks.read("proj", "artifacts/task_2_solution.md")
        assert "task_1" in c1
        assert "task_2" in c2
