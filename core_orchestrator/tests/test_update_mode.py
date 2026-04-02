"""Tests for v0.7.0 Update Mode — incremental project iteration.

Covers:
- CEO Agent: plan_update, _scan_deliverables, _next_task_id
- Architect Agent: codebase context injection, read_file tool handler
- main.py: run_update_mode, --update CLI argument
"""

import json
import re

import pytest

from core_orchestrator.ceo_agent import CEOAgent, CEOStateError
from core_orchestrator.architect_agent import ArchitectAgent, WRITE_FILE_TOOL, READ_FILE_TOOL
from core_orchestrator.llm_connector import ToolCall
from core_orchestrator.llm_gateway import LLMGateway
from core_orchestrator.workspace_manager import WorkspaceManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_sequenced_llm(responses):
    """Return a mock LLM that yields responses in order."""
    idx = {"i": 0}

    def mock_llm(text):
        i = idx["i"]
        idx["i"] += 1
        if i < len(responses):
            return responses[i]
        return json.dumps({})

    return mock_llm


def _make_write_file_tool_llm(files=None):
    """Return a tool_llm that produces write_file ToolCalls."""
    if files is None:
        files = {"app.py": "print('hello')"}

    def tool_llm(system, user_prompt, tools, tool_handler=None):
        return [
            ToolCall(name="write_file", arguments={"filepath": p, "content": c})
            for p, c in files.items()
        ]
    return tool_llm


@pytest.fixture
def workspace(tmp_path):
    wm = WorkspaceManager(tmp_path)
    wm.create("proj")
    return wm


@pytest.fixture
def workspace_with_deliverables(workspace):
    """Workspace with existing deliverables simulating a completed first build."""
    workspace.write("proj", "deliverables/index.html", "<html><body>Hello</body></html>\n")
    workspace.write("proj", "deliverables/style.css", "body { margin: 0; }\n")
    workspace.write("proj", "deliverables/app.js", "console.log('app');\n")
    workspace.write("proj", "plan.md", "# Plan\n## task_1: Build homepage\n")
    workspace.write("proj", "tasks/task_1.md", "# Build homepage\n- **ID:** task_1\n")
    workspace.write("proj", "tasks/task_2.md", "# Add styling\n- **ID:** task_2\n")
    return workspace


def _build_ceo(workspace, llm_responses, ws_id="proj"):
    """Create a CEOAgent with a mock LLM."""
    gateway = LLMGateway(llm=_make_sequenced_llm(llm_responses))
    return CEOAgent(gateway=gateway, workspace=workspace, workspace_id=ws_id)


# ===========================================================================
# CEO Agent — Update Mode
# ===========================================================================

class TestCEOScanDeliverables:
    def test_lists_deliverables_with_line_counts(self, workspace_with_deliverables):
        ceo = _build_ceo(workspace_with_deliverables, [])
        result = ceo._scan_deliverables()
        assert "index.html" in result
        assert "style.css" in result
        assert "app.js" in result
        # Should include line counts in parentheses
        assert re.search(r"\(\d+ lines?\)", result)

    def test_no_deliverables_returns_placeholder(self, workspace):
        ceo = _build_ceo(workspace, [])
        result = ceo._scan_deliverables()
        assert "no deliverables" in result.lower()


class TestCEONextTaskId:
    def test_returns_1_when_no_tasks(self, workspace):
        ceo = _build_ceo(workspace, [])
        assert ceo._next_task_id() == 1

    def test_returns_next_after_existing(self, workspace_with_deliverables):
        ceo = _build_ceo(workspace_with_deliverables, [])
        # workspace_with_deliverables has task_1 and task_2
        assert ceo._next_task_id() == 3

    def test_handles_gaps_in_task_ids(self, workspace):
        workspace.write("proj", "tasks/task_1.md", "x")
        workspace.write("proj", "tasks/task_5.md", "x")
        ceo = _build_ceo(workspace, [])
        assert ceo._next_task_id() == 6


class TestCEOPlanUpdate:
    def test_transitions_idle_to_delegating(self, workspace_with_deliverables):
        update_tasks = [
            {"id": "task_3", "title": "Fix button", "description": "Fix the submit button",
             "priority": "high", "files_to_modify": ["index.html"]},
        ]
        ceo = _build_ceo(workspace_with_deliverables, [json.dumps({"tasks": update_tasks})])
        ceo.plan_update("Fix the submit button color")
        assert ceo.state == "delegating"

    def test_cannot_plan_update_twice(self, workspace_with_deliverables):
        update_tasks = [
            {"id": "task_3", "title": "Fix X", "description": "D", "priority": "high"},
        ]
        ceo = _build_ceo(workspace_with_deliverables, [
            json.dumps({"tasks": update_tasks}),
            json.dumps({"tasks": update_tasks}),
        ])
        ceo.plan_update("Fix something")
        with pytest.raises(CEOStateError, match="idle"):
            ceo.plan_update("Fix another thing")

    def test_returns_plan_with_tasks(self, workspace_with_deliverables):
        update_tasks = [
            {"id": "task_3", "title": "Add nav", "description": "Add navigation bar",
             "priority": "medium", "files_to_modify": ["index.html", "style.css"]},
        ]
        ceo = _build_ceo(workspace_with_deliverables, [json.dumps({"tasks": update_tasks})])
        plan = ceo.plan_update("Add a navigation bar")
        assert len(plan["tasks"]) == 1
        assert plan["tasks"][0]["id"] == "task_3"

    def test_writes_update_requirement(self, workspace_with_deliverables):
        ceo = _build_ceo(workspace_with_deliverables, [json.dumps({"tasks": []})])
        ceo.plan_update("Fix the footer")
        content = workspace_with_deliverables.read("proj", "update_requirement.md")
        assert "Fix the footer" in content

    def test_appends_to_plan_md(self, workspace_with_deliverables):
        update_tasks = [
            {"id": "task_3", "title": "Fix footer", "description": "Center the footer",
             "priority": "low", "files_to_modify": ["style.css"]},
        ]
        ceo = _build_ceo(workspace_with_deliverables, [json.dumps({"tasks": update_tasks})])
        ceo.plan_update("Fix footer alignment")
        plan_content = workspace_with_deliverables.read("proj", "plan.md")
        # Should contain both original plan content and update plan
        assert "Build homepage" in plan_content  # original
        assert "Fix footer" in plan_content  # new

    def test_prompt_includes_file_listing(self, workspace_with_deliverables):
        """Verify the update plan prompt contains existing file info."""
        prompts_sent = []

        def capture_llm(text):
            prompts_sent.append(text)
            return json.dumps({"tasks": []})

        gateway = LLMGateway(llm=capture_llm)
        ceo = CEOAgent(gateway=gateway, workspace=workspace_with_deliverables, workspace_id="proj")
        ceo.plan_update("Fix something")
        assert any("index.html" in p for p in prompts_sent)
        assert any("style.css" in p for p in prompts_sent)


class TestCEODelegateUpdate:
    def test_delegate_writes_update_task_files(self, workspace_with_deliverables):
        update_tasks = [
            {"id": "task_3", "title": "Fix button", "description": "Change color",
             "priority": "high", "files_to_modify": ["index.html"]},
            {"id": "task_4", "title": "Update styles", "description": "New theme",
             "priority": "medium", "files_to_modify": ["style.css"]},
        ]
        ceo = _build_ceo(workspace_with_deliverables, [json.dumps({"tasks": update_tasks})])
        ceo.plan_update("Update UI")
        files = ceo.delegate()
        assert "tasks/task_3.md" in files
        assert "tasks/task_4.md" in files

    def test_task_file_includes_files_to_modify(self, workspace_with_deliverables):
        update_tasks = [
            {"id": "task_3", "title": "Fix button", "description": "Change color",
             "priority": "high", "files_to_modify": ["index.html", "style.css"]},
        ]
        ceo = _build_ceo(workspace_with_deliverables, [json.dumps({"tasks": update_tasks})])
        ceo.plan_update("Fix button")
        ceo.delegate()
        content = workspace_with_deliverables.read("proj", "tasks/task_3.md")
        assert "update" in content.lower()
        assert "index.html" in content
        assert "style.css" in content

    def test_preserves_existing_task_files(self, workspace_with_deliverables):
        """Update mode should not delete existing task files."""
        update_tasks = [
            {"id": "task_3", "title": "New task", "description": "X", "priority": "low"},
        ]
        ceo = _build_ceo(workspace_with_deliverables, [json.dumps({"tasks": update_tasks})])
        ceo.plan_update("Add feature")
        ceo.delegate()
        # Original tasks should still exist
        assert workspace_with_deliverables.exists("proj", "tasks/task_1.md")
        assert workspace_with_deliverables.exists("proj", "tasks/task_2.md")
        # New task too
        assert workspace_with_deliverables.exists("proj", "tasks/task_3.md")


# ===========================================================================
# Architect Agent — Codebase context & read_file
# ===========================================================================

class TestArchitectCodebaseContext:
    def test_no_context_when_no_deliverables(self, workspace):
        workspace.write("proj", "tasks/task_1.md", "# Task\n- **ID:** task_1\n")

        captured = {}

        def capturing_tool_llm(system, user_prompt, tools, tool_handler=None):
            captured["system"] = system
            captured["tools"] = tools
            return []

        arch = ArchitectAgent(
            tool_llm=capturing_tool_llm, workspace=workspace, workspace_id="proj",
        )
        arch.solve_task("tasks/task_1.md")
        assert "Existing Codebase" not in captured["system"]
        # Should only have write_file tool
        assert len(captured["tools"]) == 1
        assert captured["tools"][0]["name"] == "write_file"

    def test_injects_context_when_deliverables_exist(self, workspace_with_deliverables):
        workspace_with_deliverables.write("proj", "tasks/task_3.md",
                                          "# Fix button\n- **ID:** task_3\n")
        captured = {}

        def capturing_tool_llm(system, user_prompt, tools, tool_handler=None):
            captured["system"] = system
            captured["tools"] = tools
            return []

        arch = ArchitectAgent(
            tool_llm=capturing_tool_llm,
            workspace=workspace_with_deliverables,
            workspace_id="proj",
        )
        arch.solve_task("tasks/task_3.md")
        assert "Existing Codebase" in captured["system"]
        assert "UPDATE MODE" in captured["system"]
        assert "index.html" in captured["system"]

    def test_read_file_tool_available_with_existing_code(self, workspace_with_deliverables):
        workspace_with_deliverables.write("proj", "tasks/task_3.md",
                                          "# Fix something\n- **ID:** task_3\n")
        captured = {}

        def capturing_tool_llm(system, user_prompt, tools, tool_handler=None):
            captured["tools"] = tools
            return []

        arch = ArchitectAgent(
            tool_llm=capturing_tool_llm,
            workspace=workspace_with_deliverables,
            workspace_id="proj",
        )
        arch.solve_task("tasks/task_3.md")
        tool_names = [t["name"] for t in captured["tools"]]
        assert "write_file" in tool_names
        assert "read_file" in tool_names

    def test_no_read_file_tool_without_existing_code(self, workspace):
        workspace.write("proj", "tasks/task_1.md", "# Task\n- **ID:** task_1\n")
        captured = {}

        def capturing_tool_llm(system, user_prompt, tools, tool_handler=None):
            captured["tools"] = tools
            return []

        arch = ArchitectAgent(
            tool_llm=capturing_tool_llm, workspace=workspace, workspace_id="proj",
        )
        arch.solve_task("tasks/task_1.md")
        tool_names = [t["name"] for t in captured["tools"]]
        assert "read_file" not in tool_names


class TestArchitectToolHandler:
    def test_read_file_returns_content(self, workspace_with_deliverables):
        arch = ArchitectAgent(
            tool_llm=lambda s, p, t, h=None: [],
            workspace=workspace_with_deliverables,
            workspace_id="proj",
        )
        result = arch._tool_handler("read_file", {"filepath": "index.html"})
        parsed = json.loads(result)
        assert "content" in parsed
        assert "<html>" in parsed["content"]

    def test_read_file_with_deliverables_prefix(self, workspace_with_deliverables):
        arch = ArchitectAgent(
            tool_llm=lambda s, p, t, h=None: [],
            workspace=workspace_with_deliverables,
            workspace_id="proj",
        )
        result = arch._tool_handler("read_file", {"filepath": "deliverables/style.css"})
        parsed = json.loads(result)
        assert "content" in parsed
        assert "margin" in parsed["content"]

    def test_read_file_not_found(self, workspace):
        arch = ArchitectAgent(
            tool_llm=lambda s, p, t, h=None: [],
            workspace=workspace,
            workspace_id="proj",
        )
        result = arch._tool_handler("read_file", {"filepath": "nonexistent.py"})
        parsed = json.loads(result)
        assert "error" in parsed

    def test_write_file_handler_returns_ok(self, workspace):
        arch = ArchitectAgent(
            tool_llm=lambda s, p, t, h=None: [],
            workspace=workspace,
            workspace_id="proj",
        )
        result = arch._tool_handler("write_file", {"filepath": "x.py", "content": "pass"})
        parsed = json.loads(result)
        assert parsed["status"] == "ok"

    def test_tool_handler_passed_when_codebase_exists(self, workspace_with_deliverables):
        workspace_with_deliverables.write("proj", "tasks/task_3.md",
                                          "# Fix\n- **ID:** task_3\n")
        captured = {}

        def capturing_tool_llm(system, user_prompt, tools, tool_handler=None):
            captured["tool_handler"] = tool_handler
            return []

        arch = ArchitectAgent(
            tool_llm=capturing_tool_llm,
            workspace=workspace_with_deliverables,
            workspace_id="proj",
        )
        arch.solve_task("tasks/task_3.md")
        assert captured["tool_handler"] is not None

    def test_tool_handler_none_for_greenfield(self, workspace):
        workspace.write("proj", "tasks/task_1.md", "# Task\n- **ID:** task_1\n")
        captured = {}

        def capturing_tool_llm(system, user_prompt, tools, tool_handler=None):
            captured["tool_handler"] = tool_handler
            return []

        arch = ArchitectAgent(
            tool_llm=capturing_tool_llm, workspace=workspace, workspace_id="proj",
        )
        arch.solve_task("tasks/task_1.md")
        assert captured["tool_handler"] is None


class TestReadFileToolSchema:
    def test_read_file_tool_has_required_fields(self):
        assert READ_FILE_TOOL["name"] == "read_file"
        assert "parameters" in READ_FILE_TOOL
        assert "filepath" in READ_FILE_TOOL["parameters"]["properties"]
        assert READ_FILE_TOOL["parameters"]["required"] == ["filepath"]


# ===========================================================================
# main.py — run_update_mode
# ===========================================================================

class TestRunUpdateMode:
    def _setup_workspace_with_deliverables(self, tmp_path):
        """Create a workspace with existing deliverables."""
        ws = WorkspaceManager(tmp_path)
        ws.create("default")
        ws.write("default", "deliverables/index.html", "<html>Hello</html>\n")
        ws.write("default", "deliverables/style.css", "body { color: red; }\n")
        ws.write("default", "plan.md", "# Plan\n## task_1: Build\n")
        ws.write("default", "tasks/task_1.md", "# Build\n- **ID:** task_1\n")
        return ws

    def test_run_update_mode_generates_and_executes_tasks(self, tmp_path):
        from main import run_update_mode

        ws = self._setup_workspace_with_deliverables(tmp_path)

        # CEO LLM: return update plan with 1 task
        update_tasks = [
            {"id": "task_2", "title": "Fix color", "description": "Change body color to blue",
             "priority": "high", "files_to_modify": ["style.css"]},
        ]
        ceo_llm = _make_sequenced_llm([json.dumps({"tasks": update_tasks})])

        # Tool LLM: write updated file
        tool_llm = _make_write_file_tool_llm({"style.css": "body { color: blue; }\n"})

        # QA LLM: pass immediately
        qa_llm = lambda text: json.dumps({"verdict": "pass", "issues": [], "notes": "ok"})

        # We need a combined LLM: ceo uses gateway (text llm), execution uses tool_llm
        # run_update_mode creates its own gateway with the llm param
        # The llm must handle both CEO planning call and QA calls
        call_count = {"i": 0}

        def combined_llm(text):
            i = call_count["i"]
            call_count["i"] += 1
            if i == 0:
                # CEO plan_update call
                return json.dumps({"tasks": update_tasks})
            # QA calls
            return json.dumps({"verdict": "pass", "issues": [], "notes": "ok"})

        status = run_update_mode(
            workspace=ws,
            workspace_id="default",
            requirement="Change body color to blue",
            llm=combined_llm,
            tool_llm=tool_llm,
        )

        assert "completed" in status
        assert "task_2" in status["completed"]

    def test_run_update_mode_returns_empty_on_zero_tasks(self, tmp_path):
        from main import run_update_mode

        ws = self._setup_workspace_with_deliverables(tmp_path)

        status = run_update_mode(
            workspace=ws,
            workspace_id="default",
            requirement="Nothing to do",
            llm=lambda text: json.dumps({"tasks": []}),
            tool_llm=_make_write_file_tool_llm(),
        )

        assert status["completed"] == []
        assert status["escalated"] == []

    def test_run_update_mode_preserves_existing_files(self, tmp_path):
        from main import run_update_mode

        ws = self._setup_workspace_with_deliverables(tmp_path)

        update_tasks = [
            {"id": "task_2", "title": "Add script", "description": "Add JS file",
             "priority": "medium", "files_to_modify": []},
        ]

        call_count = {"i": 0}

        def combined_llm(text):
            i = call_count["i"]
            call_count["i"] += 1
            if i == 0:
                return json.dumps({"tasks": update_tasks})
            return json.dumps({"verdict": "pass", "issues": [], "notes": "ok"})

        run_update_mode(
            workspace=ws,
            workspace_id="default",
            requirement="Add a JS file",
            llm=combined_llm,
            tool_llm=_make_write_file_tool_llm({"app.js": "console.log('hi')"}),
        )

        # Original deliverables should still exist
        assert ws.exists("default", "deliverables/index.html")
        assert ws.exists("default", "deliverables/style.css")
        # Original task files should still exist
        assert ws.exists("default", "tasks/task_1.md")


# ===========================================================================
# CLI argument parsing
# ===========================================================================

class TestCLIUpdateArgument:
    def test_parser_accepts_update_flag(self):
        """Verify --update / -u is accepted by the argument parser."""
        import argparse
        # Re-create the parser as main() does
        from main import main
        import main as main_module

        parser = argparse.ArgumentParser()
        parser.add_argument("--workspace", "-w", default="default")
        parser.add_argument("--reset", action="store_true")
        parser.add_argument("--update", "-u", type=str, default=None, metavar="DESCRIPTION")

        args = parser.parse_args(["--update", "Fix the login button"])
        assert args.update == "Fix the login button"

    def test_parser_accepts_short_flag(self):
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument("--workspace", "-w", default="default")
        parser.add_argument("--reset", action="store_true")
        parser.add_argument("--update", "-u", type=str, default=None, metavar="DESCRIPTION")

        args = parser.parse_args(["-u", "Fix bug"])
        assert args.update == "Fix bug"

    def test_parser_default_is_none(self):
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument("--workspace", "-w", default="default")
        parser.add_argument("--reset", action="store_true")
        parser.add_argument("--update", "-u", type=str, default=None, metavar="DESCRIPTION")

        args = parser.parse_args([])
        assert args.update is None
