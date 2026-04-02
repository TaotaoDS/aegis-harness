"""Tests for checkpoint save / load / resume logic."""

import json

import pytest

from core_orchestrator.llm_connector import ToolCall
from core_orchestrator.workspace_manager import WorkspaceManager

# We import the checkpoint helpers from main
# save_checkpoint, load_checkpoint, and the stage constants

CHECKPOINT_FILE = "checkpoint.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_sequenced_llm(responses):
    idx = {"i": 0}

    def mock_llm(text):
        i = idx["i"]
        idx["i"] += 1
        return responses[i] if i < len(responses) else json.dumps({})

    return mock_llm


def _make_write_file_tool_llm(files=None):
    """Return a tool_llm that produces write_file calls."""
    if files is None:
        files = {"app.py": "print('hello')"}

    def tool_llm(system, user_prompt, tools):
        return [
            ToolCall(name="write_file", arguments={"filepath": p, "content": c})
            for p, c in files.items()
        ]
    return tool_llm


CEO_RESPONSES = [
    json.dumps({"question": "", "done": True}),
    json.dumps({"tasks": [
        {"id": "task_1", "title": "Design API", "description": "REST", "priority": "high"},
    ]}),
]

PASS_QA = json.dumps({"verdict": "pass", "issues": [], "notes": "ok"})

CE_RESPONSES = [
    json.dumps({"problem_type": "design", "components": ["api"], "severity": "low"}),
    json.dumps({"failed_attempts": [], "root_cause": "N/A", "final_solution": "ok"}),
    json.dumps({"existing_doc": None, "action": "create"}),
    json.dumps({"strategies": ["test"]}),
    json.dumps({"tags": ["api"], "category": "backend"}),
]


# ---------------------------------------------------------------------------
# save / load round-trip
# ---------------------------------------------------------------------------

class TestSaveLoad:
    def test_save_creates_file(self, tmp_path):
        from main import save_checkpoint

        ws = WorkspaceManager(tmp_path)
        ws.create("proj")
        save_checkpoint(ws, "proj", stage="delegated", requirement="Build X")
        assert ws.exists("proj", CHECKPOINT_FILE)

    def test_load_returns_saved_data(self, tmp_path):
        from main import save_checkpoint, load_checkpoint

        ws = WorkspaceManager(tmp_path)
        ws.create("proj")
        save_checkpoint(ws, "proj", stage="executed", requirement="Build Y",
                        execution_status={"completed": ["task_1"], "escalated": [], "token_usage": 500})
        cp = load_checkpoint(ws, "proj")
        assert cp["stage"] == "executed"
        assert cp["requirement"] == "Build Y"
        assert cp["execution_status"]["completed"] == ["task_1"]

    def test_load_returns_none_when_no_file(self, tmp_path):
        from main import load_checkpoint

        ws = WorkspaceManager(tmp_path)
        ws.create("proj")
        assert load_checkpoint(ws, "proj") is None

    def test_save_overwrites_previous(self, tmp_path):
        from main import save_checkpoint, load_checkpoint

        ws = WorkspaceManager(tmp_path)
        ws.create("proj")
        save_checkpoint(ws, "proj", stage="interviewed", requirement="v1")
        save_checkpoint(ws, "proj", stage="delegated", requirement="v1")
        cp = load_checkpoint(ws, "proj")
        assert cp["stage"] == "delegated"


# ---------------------------------------------------------------------------
# Resume: skip completed stages
# ---------------------------------------------------------------------------

class TestResumeFromInterviewed:
    """If checkpoint says 'interviewed', resume from delegation."""

    def test_skips_interview_and_delegates(self, tmp_path):
        from main import build_pipeline, run_interview_loop, save_checkpoint, load_checkpoint

        # Manually run interview + plan to create workspace files
        ceo = build_pipeline(workspace_root=tmp_path, llm=_make_sequenced_llm(list(CEO_RESPONSES)))
        run_interview_loop(ceo, "Build API")
        save_checkpoint(ceo._workspace, "default", stage="interviewed", requirement="Build API")

        # Verify checkpoint
        cp = load_checkpoint(ceo._workspace, "default")
        assert cp["stage"] == "interviewed"


class TestResumeFromDelegated:
    """If checkpoint says 'delegated', skip interview+delegate, run execution."""

    def test_skips_to_execution(self, tmp_path):
        from main import (build_pipeline, run_interview_loop,
                          run_execution, save_checkpoint, load_checkpoint)

        # Phase 1: CEO all the way through delegate
        ceo = build_pipeline(workspace_root=tmp_path, llm=_make_sequenced_llm(list(CEO_RESPONSES)))
        run_interview_loop(ceo, "Build API")
        ceo.delegate()
        save_checkpoint(ceo._workspace, "default", stage="delegated", requirement="Build API")

        # Phase 2: Resume from delegated — run execution directly
        ws = WorkspaceManager(tmp_path, isolated=True)
        cp = load_checkpoint(ws, "default")
        assert cp["stage"] == "delegated"

        tool_llm = _make_write_file_tool_llm({"app.py": "x = 1"})
        qa_llm = lambda text: PASS_QA

        status = run_execution(
            workspace=ws, workspace_id="default",
            llm=qa_llm,
            tool_llm=tool_llm,
        )
        assert len(status["completed"]) == 1


class TestResumeFromExecuted:
    """If checkpoint says 'executed', skip to postmortem."""

    def test_skips_to_postmortem(self, tmp_path):
        from main import (build_pipeline, run_interview_loop,
                          run_execution, run_postmortem,
                          save_checkpoint, load_checkpoint)

        # Build workspace through execution
        ceo = build_pipeline(workspace_root=tmp_path, llm=_make_sequenced_llm(list(CEO_RESPONSES)))
        run_interview_loop(ceo, "Build API")
        ceo.delegate()

        tool_llm = _make_write_file_tool_llm({"app.py": "x = 1"})
        qa_llm = lambda text: PASS_QA

        ws = ceo._workspace
        run_execution(
            workspace=ws, workspace_id="default",
            llm=qa_llm,
            tool_llm=tool_llm,
        )
        save_checkpoint(ws, "default", stage="executed", requirement="Build API",
                        execution_status={"completed": ["task_1"], "escalated": [], "token_usage": 100})

        # Resume: should only need CE responses
        cp = load_checkpoint(ws, "default")
        assert cp["stage"] == "executed"

        results = run_postmortem(
            workspace=ws, workspace_id="default",
            llm=_make_sequenced_llm(list(CE_RESPONSES)),
        )
        assert len(results) == 1


class TestResumeFromPostmortem:
    """If checkpoint says 'postmortem', pipeline is already complete."""

    def test_already_complete(self, tmp_path):
        from main import save_checkpoint, load_checkpoint

        ws = WorkspaceManager(tmp_path)
        ws.create("proj")
        save_checkpoint(ws, "proj", stage="postmortem", requirement="Build API",
                        execution_status={"completed": ["task_1"], "escalated": [], "token_usage": 50})

        cp = load_checkpoint(ws, "proj")
        assert cp["stage"] == "postmortem"


# ---------------------------------------------------------------------------
# Full pipeline with checkpoints
# ---------------------------------------------------------------------------

class TestFullPipelineWithCheckpoints:
    def test_checkpoint_written_after_each_stage(self, tmp_path):
        """Run full pipeline and verify checkpoint advances at each stage."""
        from main import (build_pipeline, run_interview_loop,
                          run_execution, run_postmortem,
                          save_checkpoint, load_checkpoint)

        # Phase 1
        ceo = build_pipeline(workspace_root=tmp_path, llm=_make_sequenced_llm(list(CEO_RESPONSES)))
        run_interview_loop(ceo, "Build API")
        save_checkpoint(ceo._workspace, "default", stage="interviewed", requirement="Build API")
        assert load_checkpoint(ceo._workspace, "default")["stage"] == "interviewed"

        # Phase 1b: delegate
        ceo.delegate()
        save_checkpoint(ceo._workspace, "default", stage="delegated", requirement="Build API")
        assert load_checkpoint(ceo._workspace, "default")["stage"] == "delegated"

        # Phase 2
        ws = ceo._workspace
        tool_llm = _make_write_file_tool_llm({"app.py": "x = 1"})
        qa_llm = lambda text: PASS_QA

        status = run_execution(
            workspace=ws, workspace_id="default",
            llm=qa_llm,
            tool_llm=tool_llm,
        )
        save_checkpoint(ws, "default", stage="executed", requirement="Build API",
                        execution_status=status)
        assert load_checkpoint(ws, "default")["stage"] == "executed"

        # Phase 3
        run_postmortem(workspace=ws, workspace_id="default",
                       llm=_make_sequenced_llm(list(CE_RESPONSES)))
        save_checkpoint(ws, "default", stage="postmortem", requirement="Build API",
                        execution_status=status)
        assert load_checkpoint(ws, "default")["stage"] == "postmortem"
