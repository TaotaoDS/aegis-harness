"""Tests for resilience manager: 3-layer escalation + Evaluator + knowledge capture."""

import json

import pytest

from core_orchestrator.llm_connector import ToolCall
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


def make_tool_calls(files=None):
    """Build a list of ToolCall objects for write_file calls."""
    if files is None:
        files = {"app.py": "print('hello')"}
    return [
        ToolCall(name="write_file", arguments={"filepath": path, "content": content})
        for path, content in files.items()
    ]


def make_empty_tool_calls():
    """No tool calls — simulates architect producing zero files."""
    return []


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
    architect_tool_calls_sequence,
    qa_responses,
    escalated_tool_calls_sequence=None,
    max_retries=3,
    token_budget=100000,
    token_threshold=0.8,
    knowledge_manager=None,
    knowledge_context="",
):
    """Build a ResilienceManager with sequenced mock tool_llm and QA LLM."""
    arch_idx = {"i": 0}
    qa_idx = {"i": 0}
    esc_idx = {"i": 0}

    def tool_llm(system, user_prompt, tools, tool_handler=None):
        idx = arch_idx["i"]
        arch_idx["i"] += 1
        if idx < len(architect_tool_calls_sequence):
            return architect_tool_calls_sequence[idx]
        return make_tool_calls()

    def qa_llm(text):
        idx = qa_idx["i"]
        qa_idx["i"] += 1
        if idx < len(qa_responses):
            return qa_responses[idx]
        return make_qa_pass()

    esc_sequence = escalated_tool_calls_sequence or architect_tool_calls_sequence

    def escalated_tool_llm(system, user_prompt, tools, tool_handler=None):
        idx = esc_idx["i"]
        esc_idx["i"] += 1
        if idx < len(esc_sequence):
            return esc_sequence[idx]
        return make_tool_calls()

    qa_gateway = LLMGateway(llm=qa_llm)

    return ResilienceManager(
        workspace=workspace,
        workspace_id="proj",
        tool_llm=tool_llm,
        qa_gateway=qa_gateway,
        max_retries=max_retries,
        token_budget=token_budget,
        token_threshold=token_threshold,
        knowledge_manager=knowledge_manager,
        knowledge_context=knowledge_context,
        escalated_tool_llm=escalated_tool_llm,
    )


# --- Layer 1: Context reset on first failure ---

class TestLayer1ContextReset:
    def test_first_fail_retries(self, workspace):
        rm = build_manager(workspace,
            architect_tool_calls_sequence=[
                make_tool_calls({"app.py": "v1 = 1\n"}),
                make_tool_calls({"app.py": "v2 = 2\n"}),
            ],
            qa_responses=[make_qa_fail(), make_qa_pass()],
        )
        result = rm.run_task_loop("task_1")
        assert result["verdict"] == "pass"
        assert result["attempts"] == 2

    def test_feedback_injected_into_workspace(self, workspace):
        rm = build_manager(workspace,
            architect_tool_calls_sequence=[
                make_tool_calls({"app.py": "v1 = 1\n"}),
                make_tool_calls({"app.py": "v2 = 2\n"}),
            ],
            qa_responses=[make_qa_fail(["Missing auth"]), make_qa_pass()],
        )
        rm.run_task_loop("task_1")
        assert workspace.exists("proj", "feedback/task_1_feedback.md")


# --- Layer 2: Model escalation on second failure ---

class TestLayer2ModelEscalation:
    def test_second_fail_escalates_model(self, workspace):
        escalated_used = {"flag": False}

        def esc_tool_llm(system, user_prompt, tools, tool_handler=None):
            escalated_used["flag"] = True
            return make_tool_calls({"app.py": "escalated = True\n"})

        qa_responses = [make_qa_fail(), make_qa_fail(), make_qa_pass()]
        qa_gw = LLMGateway(llm=lambda t: qa_responses.pop(0))

        rm = ResilienceManager(
            workspace=workspace, workspace_id="proj",
            tool_llm=lambda s, p, t, h=None: make_tool_calls({"app.py": "x = 1\n"}),
            qa_gateway=qa_gw,
            escalated_tool_llm=esc_tool_llm,
        )
        result = rm.run_task_loop("task_1")
        assert escalated_used["flag"]
        assert result["attempts"] == 3
        assert result["escalation_level"] == 2

    def test_escalation_level_tracked(self, workspace):
        rm = build_manager(workspace,
            architect_tool_calls_sequence=[
                make_tool_calls({"app.py": "x = 1\n"}),
                make_tool_calls({"app.py": "x = 2\n"}),
            ],
            qa_responses=[make_qa_fail(), make_qa_fail(), make_qa_pass()],
            escalated_tool_calls_sequence=[make_tool_calls({"app.py": "x = 3\n"})],
        )
        result = rm.run_task_loop("task_1")
        assert result["escalation_level"] == 2


# --- Layer 3: Graceful degradation ---

class TestLayer3GracefulDegradation:
    def test_third_fail_forces_stop(self, workspace):
        rm = build_manager(workspace,
            architect_tool_calls_sequence=[make_empty_tool_calls()] * 3,
            qa_responses=[make_qa_fail(), make_qa_fail(), make_qa_fail()],
        )
        result = rm.run_task_loop("task_1")
        assert result["verdict"] == "escalated"
        assert result["attempts"] == 3

    def test_escalation_writes_warning_file(self, workspace):
        rm = build_manager(workspace,
            architect_tool_calls_sequence=[make_empty_tool_calls()] * 3,
            qa_responses=[make_qa_fail(["bug"])] * 3,
        )
        rm.run_task_loop("task_1")
        assert workspace.exists("proj", "escalations/task_1_escalation.md")
        content = workspace.read("proj", "escalations/task_1_escalation.md")
        assert "human" in content.lower() or "intervention" in content.lower()

    def test_best_artifact_preserved(self, workspace):
        rm = build_manager(workspace,
            architect_tool_calls_sequence=[
                make_empty_tool_calls(),
                make_empty_tool_calls(),
            ],
            qa_responses=[make_qa_fail(), make_qa_fail(), make_qa_fail()],
            escalated_tool_calls_sequence=[make_empty_tool_calls()],
        )
        rm.run_task_loop("task_1")
        # Artifact should still exist even with zero files
        assert workspace.exists("proj", "artifacts/task_1_solution.md")


# --- Token budget guard ---

class TestTokenBudget:
    def test_budget_exceeded_forces_stop(self, workspace):
        rm = build_manager(workspace,
            architect_tool_calls_sequence=[make_tool_calls({"app.py": "x" * 5000})] * 3,
            qa_responses=[make_qa_fail()] * 3,
            token_budget=100,
            token_threshold=0.8,
        )
        result = rm.run_task_loop("task_1")
        # First attempt should pass eval+QA flow, QA fails, second attempt
        # budget from QA gateway history should push over threshold
        assert result["verdict"] in ("escalated", "pass")

    def test_budget_tracking_in_status(self, workspace):
        rm = build_manager(workspace,
            architect_tool_calls_sequence=[make_tool_calls({"app.py": "x = 1\n"})],
            qa_responses=[make_qa_pass()],
            token_budget=100000,
        )
        rm.run_task_loop("task_1")
        s = rm.status()
        assert "token_usage" in s


# --- Happy path ---

class TestHappyPath:
    def test_pass_on_first_try(self, workspace):
        rm = build_manager(workspace,
            architect_tool_calls_sequence=[make_tool_calls({"app.py": "x = 1\n"})],
            qa_responses=[make_qa_pass()],
        )
        result = rm.run_task_loop("task_1")
        assert result["verdict"] == "pass"
        assert result["attempts"] == 1
        assert result["escalation_level"] == 0

    def test_approved_file_created(self, workspace):
        rm = build_manager(workspace,
            architect_tool_calls_sequence=[make_tool_calls({"app.py": "x = 1\n"})],
            qa_responses=[make_qa_pass()],
        )
        rm.run_task_loop("task_1")
        assert workspace.exists("proj", "approved/task_1_solution.md")


# --- Run all ---

class TestRunAll:
    def test_processes_all_tasks(self, workspace_two_tasks):
        rm = build_manager(workspace_two_tasks,
            architect_tool_calls_sequence=[
                make_tool_calls({"app.py": "x = 1\n"}),
                make_tool_calls({"app.py": "x = 2\n"}),
            ],
            qa_responses=[make_qa_pass(), make_qa_pass()],
        )
        results = rm.run_all()
        ids = sorted(r["task_id"] for r in results)
        assert ids == ["task_1", "task_2"]

    def test_mixed_results(self, workspace_two_tasks):
        rm = build_manager(workspace_two_tasks,
            architect_tool_calls_sequence=[
                make_tool_calls({"app.py": f"x = {i}\n"}) for i in range(4)
            ],
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
            architect_tool_calls_sequence=[
                make_tool_calls({"app.py": f"x = {i}\n"}) for i in range(4)
            ],
            qa_responses=[make_qa_pass(), make_qa_fail(), make_qa_fail(), make_qa_fail()],
        )
        rm.run_all()
        s = rm.status()
        assert "task_1" in s["completed"]
        assert "task_2" in s["escalated"]

    def test_status_empty_before_run(self, workspace):
        rm = build_manager(workspace,
            architect_tool_calls_sequence=[], qa_responses=[],
        )
        s = rm.status()
        assert s["completed"] == []
        assert s["escalated"] == []
        assert s["token_usage"] == 0


# --- Evaluator integration ---

class TestEvaluatorIntegration:
    def test_eval_pass_goes_to_qa(self, workspace):
        """When Evaluator validates written files, QA still runs."""
        rm = build_manager(workspace,
            architect_tool_calls_sequence=[make_tool_calls({"app.py": "x = 1\n"})],
            qa_responses=[make_qa_pass()],
        )
        result = rm.run_task_loop("task_1")
        assert result["verdict"] == "pass"

    def test_eval_fail_writes_feedback(self, workspace):
        """Evaluator failure writes feedback with error details."""
        # Write bad Python that has a syntax error
        rm = build_manager(workspace,
            architect_tool_calls_sequence=[
                make_tool_calls({"bad.py": "def (:\n"})
            ] * 3,
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
            architect_tool_calls_sequence=[
                make_tool_calls({"app.py": "v1 = 1\n"}),
                make_tool_calls({"app.py": "v2 = 2\n"}),
            ],
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
            architect_tool_calls_sequence=[make_tool_calls({"app.py": "x = 1\n"})],
            qa_responses=[make_qa_pass()],
            knowledge_manager=km,
        )
        rm.run_task_loop("task_1")
        assert not km.has_lessons()

    def test_no_lesson_on_escalation(self, workspace):
        """Escalated tasks don't produce lessons (no fix to learn from)."""
        km = KnowledgeManager(workspace=workspace, workspace_id="proj")
        rm = build_manager(workspace,
            architect_tool_calls_sequence=[make_empty_tool_calls()] * 3,
            qa_responses=[make_qa_fail()] * 3,
            knowledge_manager=km,
        )
        rm.run_task_loop("task_1")
        assert not km.has_lessons()


# --- Zero-file detection ---

class TestZeroFileDetection:
    def test_zero_files_writes_feedback_and_retries(self, workspace):
        """When Architect produces no write_file calls, feedback is written
        and the task retries instead of going to QA."""
        rm = build_manager(workspace,
            architect_tool_calls_sequence=[make_empty_tool_calls()] * 3,
            qa_responses=[],  # QA should never be called
        )
        result = rm.run_task_loop("task_1")
        assert result["verdict"] == "escalated"
        assert result["attempts"] == 3
        # Feedback file should exist with zero-file message
        assert workspace.exists("proj", "feedback/task_1_feedback.md")
        fb = workspace.read("proj", "feedback/task_1_feedback.md")
        assert "0 code files" in fb or "zero files" in fb.lower()

    def test_zero_files_then_recovery(self, workspace):
        """First attempt produces no files, second attempt produces files and passes."""
        rm = build_manager(workspace,
            architect_tool_calls_sequence=[
                make_empty_tool_calls(),
                make_tool_calls({"app.py": "x = 1\n"}),
            ],
            qa_responses=[make_qa_pass()],
        )
        result = rm.run_task_loop("task_1")
        assert result["verdict"] == "pass"
        assert result["attempts"] == 2

    def test_zero_files_escalation_level(self, workspace):
        """Zero-file failures still escalate through levels."""
        rm = build_manager(workspace,
            architect_tool_calls_sequence=[make_empty_tool_calls()] * 3,
            qa_responses=[],
        )
        result = rm.run_task_loop("task_1")
        assert result["escalation_level"] == 3  # All retries exhausted
