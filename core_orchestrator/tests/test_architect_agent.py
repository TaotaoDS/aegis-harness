"""Tests for architect agent — Tool Use (Function Calling) write_file protocol."""

import pytest

from core_orchestrator.architect_agent import ArchitectAgent, WRITE_FILE_TOOL
from core_orchestrator.llm_connector import ToolCall
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


def make_tool_calls(files=None):
    """Build a list of ToolCall objects simulating write_file calls."""
    if files is None:
        files = {"index.html": "<!DOCTYPE html>\n<html><body>Hello</body></html>",
                 "style.css": "body { margin: 0; }"}
    return [
        ToolCall(name="write_file", arguments={"filepath": path, "content": content})
        for path, content in files.items()
    ]


def make_single_tool_call(filepath="app.py", content="print('hello world')"):
    return [ToolCall(name="write_file", arguments={"filepath": filepath, "content": content})]


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


def build_architect(workspace, tool_calls=None, knowledge_context="") -> ArchitectAgent:
    """Build an ArchitectAgent with a mock tool_llm that returns given tool calls."""
    _calls = tool_calls if tool_calls is not None else []

    def mock_tool_llm(system: str, user_prompt: str, tools):
        return _calls

    return ArchitectAgent(
        tool_llm=mock_tool_llm, workspace=workspace, workspace_id="proj",
        knowledge_context=knowledge_context,
    )


# --- Tool Use protocol ---

class TestToolUseProtocol:
    """Verify that the architect uses write_file tool calls to write files."""

    def test_writes_files_from_tool_calls(self, workspace_with_tasks):
        calls = make_tool_calls({"index.html": "<html>Hello</html>", "style.css": "body {}"})
        arch = build_architect(workspace_with_tasks, tool_calls=calls)
        arch.solve_task("tasks/task_1.md")
        assert workspace_with_tasks.exists("proj", "deliverables/index.html")
        assert workspace_with_tasks.exists("proj", "deliverables/style.css")

    def test_file_content_correct(self, workspace_with_tasks):
        calls = make_tool_calls({"app.py": "print('hello')"})
        arch = build_architect(workspace_with_tasks, tool_calls=calls)
        arch.solve_task("tasks/task_1.md")
        content = workspace_with_tasks.read("proj", "deliverables/app.py")
        assert "print('hello')" in content

    def test_returns_artifact_path(self, workspace_with_tasks):
        calls = make_single_tool_call()
        arch = build_architect(workspace_with_tasks, tool_calls=calls)
        path = arch.solve_task("tasks/task_1.md")
        assert path == "artifacts/task_1_solution.md"

    def test_artifact_lists_written_files(self, workspace_with_tasks):
        calls = make_tool_calls({"index.html": "<html></html>", "app.js": "x=1"})
        arch = build_architect(workspace_with_tasks, tool_calls=calls)
        arch.solve_task("tasks/task_1.md")
        content = workspace_with_tasks.read("proj", "artifacts/task_1_solution.md")
        assert "Written Files" in content
        assert "index.html" in content
        assert "app.js" in content

    def test_zero_tool_calls_still_writes_artifact(self, workspace_with_tasks):
        arch = build_architect(workspace_with_tasks, tool_calls=[])
        arch.solve_task("tasks/task_1.md")
        assert workspace_with_tasks.exists("proj", "artifacts/task_1_solution.md")

    def test_skips_empty_filepath(self, workspace_with_tasks):
        calls = [ToolCall(name="write_file", arguments={"filepath": "", "content": "x"})]
        arch = build_architect(workspace_with_tasks, tool_calls=calls)
        arch.solve_task("tasks/task_1.md")
        assert arch.get_written_files("task_1") == []

    def test_skips_empty_content(self, workspace_with_tasks):
        calls = [ToolCall(name="write_file", arguments={"filepath": "x.py", "content": ""})]
        arch = build_architect(workspace_with_tasks, tool_calls=calls)
        arch.solve_task("tasks/task_1.md")
        assert arch.get_written_files("task_1") == []

    def test_non_write_file_calls_ignored(self, workspace_with_tasks):
        calls = [
            ToolCall(name="other_tool", arguments={"x": 1}),
            ToolCall(name="write_file", arguments={"filepath": "app.py", "content": "x=1"}),
        ]
        arch = build_architect(workspace_with_tasks, tool_calls=calls)
        arch.solve_task("tasks/task_1.md")
        files = arch.get_written_files("task_1")
        assert files == ["app.py"]

    def test_deliverables_prefix_not_duplicated(self, workspace_with_tasks):
        """If tool call already includes deliverables/ prefix, don't double it."""
        calls = [ToolCall(name="write_file", arguments={
            "filepath": "deliverables/app.py", "content": "x=1"
        })]
        arch = build_architect(workspace_with_tasks, tool_calls=calls)
        arch.solve_task("tasks/task_1.md")
        assert workspace_with_tasks.exists("proj", "deliverables/app.py")

    def test_tool_definition_has_required_fields(self):
        """Verify WRITE_FILE_TOOL schema is well-formed."""
        assert WRITE_FILE_TOOL["name"] == "write_file"
        assert "parameters" in WRITE_FILE_TOOL
        assert "filepath" in WRITE_FILE_TOOL["parameters"]["properties"]
        assert "content" in WRITE_FILE_TOOL["parameters"]["properties"]
        assert WRITE_FILE_TOOL["parameters"]["required"] == ["filepath", "content"]

    def test_tool_llm_receives_system_and_prompt(self, workspace_with_tasks):
        """Verify the tool_llm callable receives system prompt and task content."""
        captured = {}

        def capturing_tool_llm(system, user_prompt, tools):
            captured["system"] = system
            captured["user_prompt"] = user_prompt
            captured["tools"] = tools
            return []

        arch = ArchitectAgent(
            tool_llm=capturing_tool_llm, workspace=workspace_with_tasks, workspace_id="proj",
        )
        arch.solve_task("tasks/task_1.md")
        assert "write_file" in captured["system"]
        assert "Design API" in captured["user_prompt"]
        assert len(captured["tools"]) == 1
        assert captured["tools"][0]["name"] == "write_file"


# --- File tools ---

class TestFileTools:
    def test_write_file(self, workspace):
        arch = build_architect(workspace)
        arch.write_file("deliverables/test.txt", "hello")
        assert workspace.read("proj", "deliverables/test.txt") == "hello"

    def test_read_file(self, workspace):
        workspace.write("proj", "deliverables/data.txt", "content")
        arch = build_architect(workspace)
        assert arch.read_file("deliverables/data.txt") == "content"

    def test_file_exists_true(self, workspace):
        workspace.write("proj", "deliverables/x.txt", "y")
        arch = build_architect(workspace)
        assert arch.file_exists("deliverables/x.txt") is True

    def test_file_exists_false(self, workspace):
        arch = build_architect(workspace)
        assert arch.file_exists("deliverables/nope.txt") is False


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


# --- Solve task with tool calls ---

class TestSolveTask:
    def test_prompt_includes_task_content(self, workspace_with_tasks):
        captured = {}

        def capturing_tool_llm(system, user_prompt, tools):
            captured["system"] = system
            captured["user_prompt"] = user_prompt
            return []

        arch = ArchitectAgent(
            tool_llm=capturing_tool_llm, workspace=workspace_with_tasks, workspace_id="proj",
        )
        arch.solve_task("tasks/task_1.md")
        assert "Design API schema" in captured["user_prompt"]

    def test_prompt_includes_plan_context(self, workspace_with_tasks):
        workspace_with_tasks.write("proj", "plan.md", "# Plan\n## task_1: Design API")
        captured = {}

        def capturing_tool_llm(system, user_prompt, tools):
            captured["system"] = system
            return []

        arch = ArchitectAgent(
            tool_llm=capturing_tool_llm, workspace=workspace_with_tasks, workspace_id="proj",
        )
        arch.solve_task("tasks/task_1.md")
        assert "Plan" in captured["system"]

    def test_nonexistent_task_raises(self, workspace):
        arch = build_architect(workspace)
        with pytest.raises(WorkspaceError):
            arch.solve_task("tasks/ghost.md")

    def test_prompt_includes_feedback(self, workspace_with_tasks):
        workspace_with_tasks.write("proj", "feedback/task_1_feedback.md", "Missing auth handling")
        captured = {}

        def capturing_tool_llm(system, user_prompt, tools):
            captured["system"] = system
            return []

        arch = ArchitectAgent(
            tool_llm=capturing_tool_llm, workspace=workspace_with_tasks, workspace_id="proj",
        )
        arch.solve_task("tasks/task_1.md")
        assert "Missing auth" in captured["system"]


# --- Knowledge context injection ---

class TestKnowledgeInjection:
    def test_knowledge_injected_into_prompt(self, workspace_with_tasks):
        captured = {}

        def capturing_tool_llm(system, user_prompt, tools):
            captured["system"] = system
            return []

        arch = ArchitectAgent(
            tool_llm=capturing_tool_llm, workspace=workspace_with_tasks, workspace_id="proj",
            knowledge_context="Always use devicePixelRatio for canvas.",
        )
        arch.solve_task("tasks/task_1.md")
        assert "devicePixelRatio" in captured["system"]

    def test_empty_knowledge_no_section(self, workspace_with_tasks):
        captured = {}

        def capturing_tool_llm(system, user_prompt, tools):
            captured["system"] = system
            return []

        arch = ArchitectAgent(
            tool_llm=capturing_tool_llm, workspace=workspace_with_tasks, workspace_id="proj",
            knowledge_context="",
        )
        arch.solve_task("tasks/task_1.md")
        assert "Knowledge Base" not in captured["system"]


# --- Solve all ---

class TestSolveAll:
    def test_returns_all_artifact_paths(self, workspace_with_tasks):
        arch = build_architect(workspace_with_tasks, tool_calls=[])
        paths = arch.solve_all()
        assert sorted(paths) == ["artifacts/task_1_solution.md", "artifacts/task_2_solution.md"]

    def test_empty_tasks_returns_empty(self, workspace):
        arch = build_architect(workspace, tool_calls=[])
        assert arch.solve_all() == []


# --- get_written_files ---

class TestGetWrittenFiles:
    def test_returns_written_files(self, workspace_with_tasks):
        calls = make_tool_calls({"index.html": "<html></html>", "style.css": "body {}"})
        arch = build_architect(workspace_with_tasks, tool_calls=calls)
        arch.solve_task("tasks/task_1.md")
        files = arch.get_written_files("task_1")
        assert "index.html" in files
        assert "style.css" in files

    def test_empty_when_no_artifact(self, workspace):
        arch = build_architect(workspace)
        assert arch.get_written_files("task_999") == []

    def test_empty_when_no_tool_calls(self, workspace_with_tasks):
        arch = build_architect(workspace_with_tasks, tool_calls=[])
        arch.solve_task("tasks/task_1.md")
        assert arch.get_written_files("task_1") == []


# --- Event bus integration ---

class TestEventBusIntegration:
    def test_emits_solving_event(self, workspace_with_tasks):
        from core_orchestrator.event_bus import ListBus
        bus = ListBus()

        def mock_tool_llm(system, user_prompt, tools):
            return make_single_tool_call()

        arch = ArchitectAgent(
            tool_llm=mock_tool_llm, workspace=workspace_with_tasks,
            workspace_id="proj", bus=bus,
        )
        arch.solve_task("tasks/task_1.md")
        events = [e[0] for e in bus.events]
        assert "architect.solving" in events
        assert "architect.llm_response" in events
        assert "architect.files_written" in events

    def test_emits_zero_files_event(self, workspace_with_tasks):
        from core_orchestrator.event_bus import ListBus
        bus = ListBus()

        arch = ArchitectAgent(
            tool_llm=lambda s, p, t: [], workspace=workspace_with_tasks,
            workspace_id="proj", bus=bus,
        )
        arch.solve_task("tasks/task_1.md")
        events = [e[0] for e in bus.events]
        assert "architect.zero_files" in events

    def test_emits_file_written_per_file(self, workspace_with_tasks):
        from core_orchestrator.event_bus import ListBus
        bus = ListBus()
        calls = make_tool_calls({"a.py": "x=1", "b.py": "y=2"})

        arch = ArchitectAgent(
            tool_llm=lambda s, p, t: calls, workspace=workspace_with_tasks,
            workspace_id="proj", bus=bus,
        )
        arch.solve_task("tasks/task_1.md")
        file_written_events = [e for e in bus.events if e[0] == "architect.file_written"]
        assert len(file_written_events) == 2
