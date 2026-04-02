"""Tests for main.py CLI entry point — full pipeline end-to-end."""

import json
from unittest.mock import patch, MagicMock

import pytest

from core_orchestrator.llm_connector import ToolCall
from core_orchestrator.llm_gateway import LLMGateway
from core_orchestrator.workspace_manager import WorkspaceManager


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_sequenced_llm(responses):
    """Return a mock LLM that yields responses in order, then empty JSON."""
    idx = {"i": 0}

    def mock_llm(text):
        i = idx["i"]
        idx["i"] += 1
        if i < len(responses):
            return responses[i]
        return json.dumps({})

    return mock_llm


def _make_write_file_tool_llm(files=None):
    """Return a tool_llm that produces write_file calls."""
    if files is None:
        files = {"app.py": "print('hello')"}

    def tool_llm(system, user_prompt, tools, tool_handler=None):
        return [
            ToolCall(name="write_file", arguments={"filepath": p, "content": c})
            for p, c in files.items()
        ]
    return tool_llm


# CEO phase responses (interview done immediately + 2 tasks)
CEO_RESPONSES = [
    json.dumps({"question": "", "done": True}),
    json.dumps({"tasks": [
        {"id": "task_1", "title": "Design API", "description": "REST endpoints", "priority": "high"},
        {"id": "task_2", "title": "Write tests", "description": "Unit tests", "priority": "medium"},
    ]}),
]


# ---------------------------------------------------------------------------
# Test: build_pipeline assembles all components
# ---------------------------------------------------------------------------

class TestBuildPipeline:
    def test_returns_ceo_agent(self, tmp_path):
        from main import build_pipeline

        def mock_llm(text):
            return json.dumps({"question": "Q?", "done": False})

        ceo = build_pipeline(workspace_root=tmp_path, llm=mock_llm)
        from core_orchestrator.ceo_agent import CEOAgent
        assert isinstance(ceo, CEOAgent)

    def test_creates_workspace_directory(self, tmp_path):
        from main import build_pipeline

        ceo = build_pipeline(
            workspace_root=tmp_path,
            llm=lambda t: json.dumps({"question": "Q?", "done": False}),
        )
        ws = tmp_path / "default"
        assert ws.is_dir()

    def test_custom_workspace_id(self, tmp_path):
        from main import build_pipeline

        ceo = build_pipeline(
            workspace_root=tmp_path,
            workspace_id="my_project",
            llm=lambda t: json.dumps({"question": "Q?", "done": False}),
        )
        ws = tmp_path / "my_project"
        assert ws.is_dir()


# ---------------------------------------------------------------------------
# Test: run_interview_loop drives CEO through full interview cycle
# ---------------------------------------------------------------------------

class TestRunInterviewLoop:
    def test_single_question_then_done(self, tmp_path):
        from main import build_pipeline, run_interview_loop

        responses = [
            json.dumps({"question": "What is the scope?", "done": False}),
            json.dumps({"question": "", "done": True}),
            json.dumps({"tasks": [
                {"id": "task_1", "title": "Do X", "description": "Details", "priority": "high"},
            ]}),
        ]
        ceo = build_pipeline(workspace_root=tmp_path, llm=_make_sequenced_llm(responses))

        user_inputs = iter(["Full-stack web app"])
        with patch("builtins.input", lambda prompt="": next(user_inputs)):
            run_interview_loop(ceo, "Build a web app")

        assert ceo.state == "delegating"

    def test_interview_writes_plan_md(self, tmp_path):
        from main import build_pipeline, run_interview_loop

        responses = [
            json.dumps({"question": "", "done": True}),
            json.dumps({"tasks": [
                {"id": "task_1", "title": "Design API", "description": "REST", "priority": "high"},
            ]}),
        ]
        ceo = build_pipeline(workspace_root=tmp_path, llm=_make_sequenced_llm(responses))
        run_interview_loop(ceo, "Build an API")

        ws = WorkspaceManager(tmp_path, isolated=True)
        plan = ws.read("default", "plan.md")
        assert "Design API" in plan

    def test_multi_round_interview(self, tmp_path):
        from main import build_pipeline, run_interview_loop

        responses = [
            json.dumps({"question": "Who are the users?", "done": False}),
            json.dumps({"question": "What's the deadline?", "done": False}),
            json.dumps({"question": "", "done": True}),
            json.dumps({"tasks": [
                {"id": "task_1", "title": "T1", "description": "D1", "priority": "high"},
            ]}),
        ]
        ceo = build_pipeline(workspace_root=tmp_path, llm=_make_sequenced_llm(responses))

        user_inputs = iter(["Engineers", "End of Q2"])
        with patch("builtins.input", lambda prompt="": next(user_inputs)):
            run_interview_loop(ceo, "Build a dashboard")

        assert ceo.state == "delegating"


# ---------------------------------------------------------------------------
# Test: delegate writes task files
# ---------------------------------------------------------------------------

class TestDelegate:
    def test_delegate_creates_task_files(self, tmp_path):
        from main import build_pipeline, run_interview_loop

        ceo = build_pipeline(workspace_root=tmp_path, llm=_make_sequenced_llm(list(CEO_RESPONSES)))
        run_interview_loop(ceo, "Build something")
        files = ceo.delegate()

        ws = WorkspaceManager(tmp_path, isolated=True)
        assert ws.exists("default", "tasks/task_1.md")
        assert ws.exists("default", "tasks/task_2.md")


# ---------------------------------------------------------------------------
# Test: run_execution produces artifacts via ResilienceManager
# ---------------------------------------------------------------------------

class TestRunExecution:
    def _setup_workspace_with_tasks(self, tmp_path):
        """Create a workspace with 2 tasks already delegated."""
        from main import build_pipeline, run_interview_loop
        ceo = build_pipeline(workspace_root=tmp_path, llm=_make_sequenced_llm(list(CEO_RESPONSES)))
        run_interview_loop(ceo, "Build something")
        ceo.delegate()
        return WorkspaceManager(tmp_path, isolated=True)

    def test_run_execution_creates_artifacts(self, tmp_path):
        from main import run_execution

        ws = self._setup_workspace_with_tasks(tmp_path)
        tool_llm = _make_write_file_tool_llm({"app.py": "print('hello')"})
        qa_llm = lambda text: json.dumps({"verdict": "pass", "issues": [], "notes": "LGTM"})

        run_execution(
            workspace=ws, workspace_id="default",
            llm=qa_llm,
            tool_llm=tool_llm,
        )

        # Artifacts should exist for both tasks
        assert ws.exists("default", "approved/task_1_solution.md")
        assert ws.exists("default", "approved/task_2_solution.md")

    def test_run_execution_returns_status(self, tmp_path):
        from main import run_execution

        ws = self._setup_workspace_with_tasks(tmp_path)
        tool_llm = _make_write_file_tool_llm({"app.py": "x = 1"})
        qa_llm = lambda text: json.dumps({"verdict": "pass", "issues": [], "notes": "ok"})

        status = run_execution(
            workspace=ws, workspace_id="default",
            llm=qa_llm,
            tool_llm=tool_llm,
        )

        assert "completed" in status
        assert "task_1" in status["completed"]
        assert "task_2" in status["completed"]

    def test_run_execution_escalates_on_repeated_failure(self, tmp_path):
        from main import run_execution

        ws = self._setup_workspace_with_tasks(tmp_path)
        tool_llm = _make_write_file_tool_llm({"app.py": "x = 1"})
        qa_llm = lambda text: json.dumps({
            "verdict": "fail",
            "issues": ["Incomplete implementation"],
            "notes": "Not good enough",
        })

        status = run_execution(
            workspace=ws, workspace_id="default",
            llm=qa_llm,
            tool_llm=tool_llm,
        )

        # All tasks should be escalated
        assert "escalated" in status
        assert len(status["escalated"]) == 2

    def test_run_execution_writes_escalation_files(self, tmp_path):
        from main import run_execution

        ws = self._setup_workspace_with_tasks(tmp_path)
        tool_llm = _make_write_file_tool_llm({"app.py": "x = 1"})
        qa_llm = lambda text: json.dumps({"verdict": "fail", "issues": ["bug"], "notes": "no"})

        run_execution(
            workspace=ws, workspace_id="default",
            llm=qa_llm,
            tool_llm=tool_llm,
        )

        assert ws.exists("default", "escalations/task_1_escalation.md")
        assert ws.exists("default", "escalations/task_2_escalation.md")


# ---------------------------------------------------------------------------
# Test: run_postmortem writes postmortem docs for completed tasks
# ---------------------------------------------------------------------------

class TestRunPostmortem:
    def _setup_completed_workspace(self, tmp_path):
        """Create a workspace where tasks have been solved and approved."""
        from main import build_pipeline, run_interview_loop, run_execution

        ceo = build_pipeline(workspace_root=tmp_path, llm=_make_sequenced_llm(list(CEO_RESPONSES)))
        run_interview_loop(ceo, "Build something")
        ceo.delegate()

        ws = WorkspaceManager(tmp_path, isolated=True)
        tool_llm = _make_write_file_tool_llm({"app.py": "print('hello')"})
        qa_llm = lambda text: json.dumps({"verdict": "pass", "issues": [], "notes": "LGTM"})

        run_execution(
            workspace=ws, workspace_id="default",
            llm=qa_llm,
            tool_llm=tool_llm,
        )
        return ws

    def test_postmortem_writes_docs(self, tmp_path):
        from main import run_postmortem

        ws = self._setup_completed_workspace(tmp_path)

        # CE sub-agents return structured JSON
        ce_responses = [
            json.dumps({"problem_type": "API design", "components": ["api"], "severity": "low"}),
            json.dumps({"failed_attempts": [], "root_cause": "None", "final_solution": "FastAPI"}),
            json.dumps({"existing_doc": None, "action": "create"}),
            json.dumps({"strategies": ["Add integration tests"]}),
            json.dumps({"tags": ["api"], "category": "backend/api"}),
        ]
        # Need 5 responses per task, 2 tasks = 10
        all_ce_responses = ce_responses + ce_responses

        results = run_postmortem(
            workspace=ws, workspace_id="default",
            llm=_make_sequenced_llm(all_ce_responses),
        )

        assert len(results) == 2
        assert ws.exists("default", "docs/solutions/task_1_postmortem.md")
        assert ws.exists("default", "docs/solutions/task_2_postmortem.md")

    def test_postmortem_returns_analysis(self, tmp_path):
        from main import run_postmortem

        ws = self._setup_completed_workspace(tmp_path)

        ce_responses = [
            json.dumps({"problem_type": "API", "components": ["api"], "severity": "low"}),
            json.dumps({"failed_attempts": [], "root_cause": "N/A", "final_solution": "Done"}),
            json.dumps({"existing_doc": None, "action": "create"}),
            json.dumps({"strategies": ["test"]}),
            json.dumps({"tags": ["api"], "category": "backend"}),
        ] * 2

        results = run_postmortem(
            workspace=ws, workspace_id="default",
            llm=_make_sequenced_llm(ce_responses),
        )

        assert results[0]["task_id"] in ["task_1", "task_2"]
        assert "context_analysis" in results[0]
        assert "classification" in results[0]


# ---------------------------------------------------------------------------
# Test: full end-to-end pipeline
# ---------------------------------------------------------------------------

class TestFullPipeline:
    def test_end_to_end(self, tmp_path):
        """Full pipeline: CEO -> delegate -> execute -> postmortem."""
        from main import build_pipeline, run_interview_loop, run_execution, run_postmortem

        # Phase 1: CEO interview + plan + delegate
        ceo = build_pipeline(workspace_root=tmp_path, llm=_make_sequenced_llm(list(CEO_RESPONSES)))
        run_interview_loop(ceo, "Build an API")
        ceo.delegate()

        ws = WorkspaceManager(tmp_path, isolated=True)

        # Phase 2: Architect (Tool Use) + QA (pass on first try)
        tool_llm = _make_write_file_tool_llm({"app.py": "print('hello')"})
        qa_llm = lambda text: json.dumps({"verdict": "pass", "issues": [], "notes": "ok"})

        status = run_execution(
            workspace=ws, workspace_id="default",
            llm=qa_llm,
            tool_llm=tool_llm,
        )
        assert len(status["completed"]) == 2
        assert len(status["escalated"]) == 0

        # Phase 3: CE Orchestrator postmortem
        ce_responses = [
            json.dumps({"problem_type": "design", "components": ["api"], "severity": "low"}),
            json.dumps({"failed_attempts": [], "root_cause": "N/A", "final_solution": "FastAPI"}),
            json.dumps({"existing_doc": None, "action": "create"}),
            json.dumps({"strategies": ["testing"]}),
            json.dumps({"tags": ["api"], "category": "backend"}),
        ] * 2

        results = run_postmortem(
            workspace=ws, workspace_id="default",
            llm=_make_sequenced_llm(ce_responses),
        )

        # Everything should be in workspace
        assert ws.exists("default", "requirement.md")
        assert ws.exists("default", "plan.md")
        assert ws.exists("default", "tasks/task_1.md")
        assert ws.exists("default", "tasks/task_2.md")
        assert ws.exists("default", "approved/task_1_solution.md")
        assert ws.exists("default", "approved/task_2_solution.md")
        assert ws.exists("default", "docs/solutions/task_1_postmortem.md")
        assert ws.exists("default", "docs/solutions/task_2_postmortem.md")
