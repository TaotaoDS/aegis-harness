"""Tests for QA evaluator agent."""

import json

import pytest

from core_orchestrator.qa_agent import QAAgent, QAError
from core_orchestrator.llm_gateway import LLMGateway
from core_orchestrator.workspace_manager import WorkspaceManager


# --- Helpers ---

TASK_CONTENT = (
    "# Design API schema\n\n"
    "- **ID:** task_1\n"
    "- **Priority:** high\n"
    "- **Description:** Define REST endpoints\n"
)

SOLUTION_CONTENT = (
    "# Solution: task_1\n\n"
    "## Implementation\nUse FastAPI with Pydantic models.\n"
)

TASK_2_CONTENT = (
    "# Implement backend\n\n"
    "- **ID:** task_2\n"
    "- **Priority:** high\n"
    "- **Description:** Build the service layer\n"
)

SOLUTION_2_CONTENT = (
    "# Solution: task_2\n\n"
    "## Implementation\nFlask with SQLAlchemy.\n"
)


def make_pass_response(notes: str = "Looks good.") -> str:
    return json.dumps({"verdict": "pass", "issues": [], "notes": notes})


def make_fail_response(issues: list[str], notes: str = "Needs work.") -> str:
    return json.dumps({"verdict": "fail", "issues": issues, "notes": notes})


@pytest.fixture
def workspace(tmp_path):
    wm = WorkspaceManager(tmp_path)
    wm.create("proj")
    return wm


@pytest.fixture
def workspace_with_artifacts(workspace):
    workspace.write("proj", "tasks/task_1.md", TASK_CONTENT)
    workspace.write("proj", "artifacts/task_1_solution.md", SOLUTION_CONTENT)
    return workspace


@pytest.fixture
def workspace_mixed(workspace):
    """Two tasks: task_1 will pass, task_2 will fail."""
    workspace.write("proj", "tasks/task_1.md", TASK_CONTENT)
    workspace.write("proj", "artifacts/task_1_solution.md", SOLUTION_CONTENT)
    workspace.write("proj", "tasks/task_2.md", TASK_2_CONTENT)
    workspace.write("proj", "artifacts/task_2_solution.md", SOLUTION_2_CONTENT)
    return workspace


def build_qa(workspace, llm_response) -> QAAgent:
    """Build QAAgent with a mock LLM returning a fixed or sequenced response."""
    if isinstance(llm_response, list):
        call_idx = {"i": 0}
        def seq_llm(text: str) -> str:
            idx = call_idx["i"]
            call_idx["i"] += 1
            return llm_response[idx]
        gateway = LLMGateway(llm=seq_llm)
    else:
        gateway = LLMGateway(llm=lambda t: llm_response)
    return QAAgent(gateway=gateway, workspace=workspace, workspace_id="proj")


# --- Review single task: PASS ---

class TestReviewPass:
    def test_pass_returns_verdict(self, workspace_with_artifacts):
        qa = build_qa(workspace_with_artifacts, make_pass_response())
        result = qa.review_task("task_1")
        assert result["verdict"] == "pass"
        assert result["task_id"] == "task_1"

    def test_pass_copies_to_approved(self, workspace_with_artifacts):
        qa = build_qa(workspace_with_artifacts, make_pass_response())
        result = qa.review_task("task_1")
        assert result["path"] == "approved/task_1_solution.md"
        content = workspace_with_artifacts.read("proj", "approved/task_1_solution.md")
        assert "Use FastAPI" in content

    def test_pass_approved_matches_original(self, workspace_with_artifacts):
        qa = build_qa(workspace_with_artifacts, make_pass_response())
        qa.review_task("task_1")
        original = workspace_with_artifacts.read("proj", "artifacts/task_1_solution.md")
        approved = workspace_with_artifacts.read("proj", "approved/task_1_solution.md")
        assert original == approved

    def test_pass_no_feedback_file(self, workspace_with_artifacts):
        qa = build_qa(workspace_with_artifacts, make_pass_response())
        qa.review_task("task_1")
        assert not workspace_with_artifacts.exists("proj", "feedback/task_1_feedback.md")


# --- Review single task: FAIL ---

class TestReviewFail:
    def test_fail_returns_verdict(self, workspace_with_artifacts):
        qa = build_qa(workspace_with_artifacts, make_fail_response(["Missing auth"]))
        result = qa.review_task("task_1")
        assert result["verdict"] == "fail"
        assert result["task_id"] == "task_1"

    def test_fail_writes_feedback(self, workspace_with_artifacts):
        qa = build_qa(workspace_with_artifacts, make_fail_response(
            ["Missing authentication", "No error handling"],
            notes="Major gaps.",
        ))
        result = qa.review_task("task_1")
        assert result["path"] == "feedback/task_1_feedback.md"
        content = workspace_with_artifacts.read("proj", "feedback/task_1_feedback.md")
        assert "Missing authentication" in content
        assert "No error handling" in content
        assert "Major gaps." in content

    def test_fail_no_approved_file(self, workspace_with_artifacts):
        qa = build_qa(workspace_with_artifacts, make_fail_response(["bug"]))
        qa.review_task("task_1")
        assert not workspace_with_artifacts.exists("proj", "approved/task_1_solution.md")

    def test_fail_feedback_references_task(self, workspace_with_artifacts):
        qa = build_qa(workspace_with_artifacts, make_fail_response(["issue"]))
        qa.review_task("task_1")
        content = workspace_with_artifacts.read("proj", "feedback/task_1_feedback.md")
        assert "task_1" in content


# --- Prompt verification ---

class TestPrompt:
    def test_prompt_includes_task_content(self, workspace_with_artifacts):
        prompts = []
        def capture(text):
            prompts.append(text)
            return make_pass_response()
        gateway = LLMGateway(llm=capture)
        qa = QAAgent(gateway=gateway, workspace=workspace_with_artifacts, workspace_id="proj")
        qa.review_task("task_1")
        assert any("Define REST endpoints" in p for p in prompts)

    def test_prompt_includes_solution_content(self, workspace_with_artifacts):
        prompts = []
        def capture(text):
            prompts.append(text)
            return make_pass_response()
        gateway = LLMGateway(llm=capture)
        qa = QAAgent(gateway=gateway, workspace=workspace_with_artifacts, workspace_id="proj")
        qa.review_task("task_1")
        assert any("Use FastAPI" in p for p in prompts)


# --- Error cases ---

class TestErrors:
    def test_missing_artifact_raises(self, workspace):
        workspace.write("proj", "tasks/task_1.md", TASK_CONTENT)
        # No artifact written
        qa = build_qa(workspace, make_pass_response())
        with pytest.raises(QAError, match="artifact.*not found"):
            qa.review_task("task_1")

    def test_missing_task_raises(self, workspace):
        workspace.write("proj", "artifacts/task_1_solution.md", SOLUTION_CONTENT)
        # No task file
        qa = build_qa(workspace, make_pass_response())
        with pytest.raises(QAError, match="task.*not found"):
            qa.review_task("task_1")


# --- Malformed LLM responses ---

class TestMalformedResponse:
    def test_empty_response_defaults_to_fail(self, workspace_with_artifacts):
        """When LLM returns empty string, QA should fail (not crash)."""
        qa = build_qa(workspace_with_artifacts, "")
        result = qa.review_task("task_1")
        assert result["verdict"] == "fail"
        assert result["task_id"] == "task_1"

    def test_garbage_response_defaults_to_fail(self, workspace_with_artifacts):
        qa = build_qa(workspace_with_artifacts, "I cannot review this sorry")
        result = qa.review_task("task_1")
        assert result["verdict"] == "fail"

    def test_markdown_fenced_pass(self, workspace_with_artifacts):
        """LLM wraps JSON in ```json fences — should still parse."""
        fenced = '```json\n{"verdict": "pass", "issues": [], "notes": "ok"}\n```'
        qa = build_qa(workspace_with_artifacts, fenced)
        result = qa.review_task("task_1")
        assert result["verdict"] == "pass"

    def test_markdown_fenced_fail(self, workspace_with_artifacts):
        fenced = '```json\n{"verdict": "fail", "issues": ["bug"], "notes": "no"}\n```'
        qa = build_qa(workspace_with_artifacts, fenced)
        result = qa.review_task("task_1")
        assert result["verdict"] == "fail"


# --- Review all ---

class TestReviewAll:
    def test_reviews_all_tasks(self, workspace_mixed):
        qa = build_qa(workspace_mixed, [
            make_pass_response(),
            make_fail_response(["bad"]),
        ])
        results = qa.review_all()
        assert len(results) == 2
        ids = sorted(r["task_id"] for r in results)
        assert ids == ["task_1", "task_2"]

    def test_mixed_verdicts(self, workspace_mixed):
        qa = build_qa(workspace_mixed, [
            make_pass_response(),
            make_fail_response(["issue"]),
        ])
        results = qa.review_all()
        verdicts = {r["task_id"]: r["verdict"] for r in results}
        assert verdicts["task_1"] == "pass"
        assert verdicts["task_2"] == "fail"

    def test_empty_when_no_artifacts(self, workspace):
        qa = build_qa(workspace, make_pass_response())
        assert qa.review_all() == []


# --- Summary ---

class TestSummary:
    def test_summary_counts(self, workspace_mixed):
        qa = build_qa(workspace_mixed, [
            make_pass_response(),
            make_fail_response(["issue"]),
        ])
        qa.review_all()
        s = qa.summary()
        assert s["passed"] == ["task_1"]
        assert s["failed"] == ["task_2"]
        assert s["total"] == 2

    def test_summary_all_pass(self, workspace_mixed):
        qa = build_qa(workspace_mixed, [
            make_pass_response(),
            make_pass_response(),
        ])
        qa.review_all()
        s = qa.summary()
        assert len(s["passed"]) == 2
        assert s["failed"] == []

    def test_summary_empty_before_review(self, workspace):
        qa = build_qa(workspace, make_pass_response())
        s = qa.summary()
        assert s["total"] == 0
