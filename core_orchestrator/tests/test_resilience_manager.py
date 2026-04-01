"""Tests for resilience manager: 3-layer escalation + Evaluator + knowledge capture."""

import json

import pytest

from core_orchestrator.resilience_manager import ResilienceManager
from core_orchestrator.knowledge_manager import KnowledgeManager, KB_FILENAME
from core_orchestrator.llm_gateway import LLMGateway
from core_orchestrator.workspace_manager import WorkspaceManager


# --- Helpers ---

TASK_CONTENT = (
    "# Design API\n\n"
    "- **ID:** task_1\n"
    "- **Priority:** high\n"
    "- **Description:** Define REST endpoints\n"
)


def make_qa_pass():
    return json.dumps({"verdict": "pass", "issues": [], "notes": "Good."})


def make_qa_fail(issues=None):
    return json.dumps({
        "verdict": "fail",
        "issues": issues or ["Needs improvement"],
        "notes": "Not ready.",
    })


def make_architect_response(content="## Solution\nUse FastAPI."):
    """What the Architect's LLM returns."""
    return content


def make_file_block_response(files=None):
    """Build a response with ===FILE:=== blocks."""
    if files is None:
        files = {"app.py": "print('hello')"}
    parts = []
    for path, code in files.items():
        parts.append(f"===FILE: {path}===\n{code}")
    parts.append("===END===")
    return "\n".join(parts)


@pytest.fixture
def workspace(tmp_path):
    wm = WorkspaceManager(tmp_path)
    wm.create("proj")
    wm.write("proj", "tasks/task_1.md", TASK_CONTENT)
    return wm


@pytest.fixture
def workspace_two_tasks(workspace):
    workspace.write("proj", "tasks/task_2.md",
        "# Implement backend\n\n- **ID:** task_2\n- **Priority:** high\n"
        "- **Description:** Build service layer\n")
    return workspace


def build_manager(
    workspace,
    architect_responses,
    qa_responses,
    escalated_architect_responses=None,
    max_retries=3,
    token_budget=100000,
    token_threshold=0.8,
    knowledge_manager=None,
    knowledge_context="",
):
    """Build a ResilienceManager with sequenced mock LLMs."""
    arch_idx = {"i": 0}
    qa_idx = {"i": 0}
    esc_idx = {"i": 0}

    def arch_llm(text):
        idx = arch_idx["i"]
        arch_idx["i"] += 1
        if idx < len(architect_responses):
            return architect_responses[idx]
        return make_architect_response("fallback solution")

    def qa_llm(text):
        idx = qa_idx["i"]
        qa_idx["i"] += 1
        if idx < len(qa_responses):
            return qa_responses[idx]
        return make_qa_pass()

    esc_responses = escalated_architect_responses or architect_responses

    def esc_llm(text):
        idx = esc_idx["i"]
        esc_idx["i"] += 1
        if idx < len(esc_responses):
            return esc_responses[idx]
        return make_architect_response("escalated fallback")

    def gateway_factory():
        return LLMGateway(llm=arch_llm)

    def escalated_gateway_factory():
        return LLMGateway(llm=esc_llm)

    qa_gateway = LLMGateway(llm=qa_llm)

    return ResilienceManager(
        workspace=workspace,
        workspace_id="proj",
        gateway_factory=gateway_factory,
        escalated_gateway_factory=escalated_gateway_factory,
        qa_gateway=qa_gateway,
        max_retries=max_retries,
        token_budget=token_budget,
        token_threshold=token_threshold,
        knowledge_manager=knowledge_manager,
        knowledge_context=knowledge_context,
    )


# --- Layer 1: Context reset on first failure ---

class TestLayer1ContextReset:
    def test_first_fail_retries_with_fresh_gateway(self, workspace):
        gateways_created = {"count": 0}

        def counting_factory():
            gateways_created["count"] += 1
            return LLMGateway(llm=lambda t: make_architect_response(f"attempt {gateways_created['count']}"))

        qa_responses = [make_qa_fail(), make_qa_pass()]
        qa_gw = LLMGateway(llm=lambda t: qa_responses.pop(0))

        rm = ResilienceManager(
            workspace=workspace, workspace_id="proj",
            gateway_factory=counting_factory,
            escalated_gateway_factory=counting_factory,
            qa_gateway=qa_gw,
        )
        result = rm.run_task_loop("task_1")
        assert gateways_created["count"] >= 2
        assert result["verdict"] == "pass"
        assert result["attempts"] == 2

    def test_feedback_injected_into_workspace(self, workspace):
        rm = build_manager(workspace,
            architect_responses=[make_architect_response("v1"), make_architect_response("v2")],
            qa_responses=[make_qa_fail(["Missing auth"]), make_qa_pass()],
        )
        rm.run_task_loop("task_1")
        assert workspace.exists("proj", "feedback/task_1_feedback.md")


# --- Layer 2: Model escalation on second failure ---

class TestLayer2ModelEscalation:
    def test_second_fail_escalates_model(self, workspace):
        escalated_used = {"flag": False}

        def esc_factory():
            escalated_used["flag"] = True
            return LLMGateway(llm=lambda t: make_architect_response("escalated solution"))

        qa_responses = [make_qa_fail(), make_qa_fail(), make_qa_pass()]
        qa_gw = LLMGateway(llm=lambda t: qa_responses.pop(0))

        rm = ResilienceManager(
            workspace=workspace, workspace_id="proj",
            gateway_factory=lambda: LLMGateway(llm=lambda t: make_architect_response()),
            escalated_gateway_factory=esc_factory,
            qa_gateway=qa_gw,
        )
        result = rm.run_task_loop("task_1")
        assert escalated_used["flag"]
        assert result["attempts"] == 3
        assert result["escalation_level"] == 2

    def test_escalation_level_tracked(self, workspace):
        rm = build_manager(workspace,
            architect_responses=[make_architect_response(), make_architect_response()],
            qa_responses=[make_qa_fail(), make_qa_fail(), make_qa_pass()],
            escalated_architect_responses=[make_architect_response("advanced")],
        )
        result = rm.run_task_loop("task_1")
        assert result["escalation_level"] == 2


# --- Layer 3: Graceful degradation ---

class TestLayer3GracefulDegradation:
    def test_third_fail_forces_stop(self, workspace):
        rm = build_manager(workspace,
            architect_responses=[make_architect_response()] * 3,
            qa_responses=[make_qa_fail(), make_qa_fail(), make_qa_fail()],
        )
        result = rm.run_task_loop("task_1")
        assert result["verdict"] == "escalated"
        assert result["attempts"] == 3

    def test_escalation_writes_warning_file(self, workspace):
        rm = build_manager(workspace,
            architect_responses=[make_architect_response()] * 3,
            qa_responses=[make_qa_fail(["bug"])] * 3,
        )
        rm.run_task_loop("task_1")
        assert workspace.exists("proj", "escalations/task_1_escalation.md")
        content = workspace.read("proj", "escalations/task_1_escalation.md")
        assert "human" in content.lower() or "intervention" in content.lower()

    def test_best_artifact_preserved(self, workspace):
        rm = build_manager(workspace,
            architect_responses=[
                make_architect_response("v1"),
                make_architect_response("v2"),
            ],
            qa_responses=[make_qa_fail(), make_qa_fail(), make_qa_fail()],
            escalated_architect_responses=[make_architect_response("v3 best")],
        )
        rm.run_task_loop("task_1")
        content = workspace.read("proj", "artifacts/task_1_solution.md")
        assert "v3 best" in content


# --- Token budget guard ---

class TestTokenBudget:
    def test_budget_exceeded_forces_stop(self, workspace):
        rm = build_manager(workspace,
            architect_responses=[make_architect_response("x" * 5000)] * 3,
            qa_responses=[make_qa_fail()] * 3,
            token_budget=100,
            token_threshold=0.8,
        )
        result = rm.run_task_loop("task_1")
        assert result["verdict"] == "escalated"
        assert result["attempts"] <= 3

    def test_budget_tracking_in_status(self, workspace):
        rm = build_manager(workspace,
            architect_responses=[make_architect_response()],
            qa_responses=[make_qa_pass()],
            token_budget=100000,
        )
        rm.run_task_loop("task_1")
        s = rm.status()
        assert "token_usage" in s
        assert s["token_usage"] > 0


# --- Happy path ---

class TestHappyPath:
    def test_pass_on_first_try(self, workspace):
        rm = build_manager(workspace,
            architect_responses=[make_architect_response("perfect solution")],
            qa_responses=[make_qa_pass()],
        )
        result = rm.run_task_loop("task_1")
        assert result["verdict"] == "pass"
        assert result["attempts"] == 1
        assert result["escalation_level"] == 0

    def test_approved_file_created(self, workspace):
        rm = build_manager(workspace,
            architect_responses=[make_architect_response()],
            qa_responses=[make_qa_pass()],
        )
        rm.run_task_loop("task_1")
        assert workspace.exists("proj", "approved/task_1_solution.md")


# --- Run all ---

class TestRunAll:
    def test_processes_all_tasks(self, workspace_two_tasks):
        rm = build_manager(workspace_two_tasks,
            architect_responses=[make_architect_response(), make_architect_response()],
            qa_responses=[make_qa_pass(), make_qa_pass()],
        )
        results = rm.run_all()
        ids = sorted(r["task_id"] for r in results)
        assert ids == ["task_1", "task_2"]

    def test_mixed_results(self, workspace_two_tasks):
        rm = build_manager(workspace_two_tasks,
            architect_responses=[make_architect_response()] * 4,
            qa_responses=[make_qa_pass(), make_qa_fail(), make_qa_fail(), make_qa_fail()],
        )
        results = rm.run_all()
        verdicts = {r["task_id"]: r["verdict"] for r in results}
        assert verdicts["task_1"] == "pass"
        assert verdicts["task_2"] == "escalated"


# --- Status ---

class TestStatus:
    def test_status_after_run(self, workspace_two_tasks):
        rm = build_manager(workspace_two_tasks,
            architect_responses=[make_architect_response()] * 4,
            qa_responses=[make_qa_pass(), make_qa_fail(), make_qa_fail(), make_qa_fail()],
        )
        rm.run_all()
        s = rm.status()
        assert "task_1" in s["completed"]
        assert "task_2" in s["escalated"]
        assert s["token_usage"] > 0

    def test_status_empty_before_run(self, workspace):
        rm = build_manager(workspace,
            architect_responses=[], qa_responses=[],
        )
        s = rm.status()
        assert s["completed"] == []
        assert s["escalated"] == []
        assert s["token_usage"] == 0


# --- Evaluator integration ---

class TestEvaluatorIntegration:
    def test_eval_pass_goes_to_qa(self, workspace):
        """When Evaluator validates written files, QA still runs."""
        resp = make_file_block_response({"app.py": "x = 1\n"})
        rm = build_manager(workspace,
            architect_responses=[resp],
            qa_responses=[make_qa_pass()],
        )
        result = rm.run_task_loop("task_1")
        assert result["verdict"] == "pass"

    def test_eval_fail_writes_feedback(self, workspace):
        """Evaluator failure writes feedback with error details."""
        # Write bad Python that has a syntax error
        resp = make_file_block_response({"bad.py": "def (:\n"})
        rm = build_manager(workspace,
            architect_responses=[resp] * 3,
            qa_responses=[make_qa_fail()] * 3,
        )
        rm.run_task_loop("task_1")
        assert workspace.exists("proj", "feedback/task_1_feedback.md")
        fb = workspace.read("proj", "feedback/task_1_feedback.md")
        assert "Evaluator" in fb or "FAIL" in fb


# --- Knowledge capture ---

class TestKnowledgeCapture:
    def test_lesson_written_after_retry_pass(self, workspace):
        """When a task passes after retries, lesson is captured."""
        km = KnowledgeManager(workspace=workspace, workspace_id="proj")
        rm = build_manager(workspace,
            architect_responses=[make_architect_response("v1"), make_architect_response("v2")],
            qa_responses=[make_qa_fail(["Missing auth"]), make_qa_pass()],
            knowledge_manager=km,
        )
        rm.run_task_loop("task_1")
        assert km.has_lessons()
        content = km.load_knowledge()
        assert "task_1" in content

    def test_no_lesson_on_first_try_pass(self, workspace):
        """First-try pass doesn't generate a lesson (nothing to learn)."""
        km = KnowledgeManager(workspace=workspace, workspace_id="proj")
        rm = build_manager(workspace,
            architect_responses=[make_architect_response()],
            qa_responses=[make_qa_pass()],
            knowledge_manager=km,
        )
        rm.run_task_loop("task_1")
        assert not km.has_lessons()

    def test_no_lesson_on_escalation(self, workspace):
        """Escalated tasks don't produce lessons (no fix to learn from)."""
        km = KnowledgeManager(workspace=workspace, workspace_id="proj")
        rm = build_manager(workspace,
            architect_responses=[make_architect_response()] * 3,
            qa_responses=[make_qa_fail()] * 3,
            knowledge_manager=km,
        )
        rm.run_task_loop("task_1")
        assert not km.has_lessons()
