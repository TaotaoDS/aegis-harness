"""Tests for CEO orchestrator agent."""

import json

import pytest

from core_orchestrator.ceo_agent import CEOAgent, CEOStateError
from core_orchestrator.llm_gateway import LLMGateway
from core_orchestrator.workspace_manager import WorkspaceManager


# --- Helpers ---

def make_interview_response(question: str, done: bool = False) -> str:
    """Build a mock LLM response for the interview phase."""
    return json.dumps({"question": question, "done": done})


def make_plan_response(tasks: list[dict]) -> str:
    """Build a mock LLM response for the planning phase."""
    return json.dumps({"tasks": tasks})


SAMPLE_TASKS = [
    {"id": "task_1", "title": "Design API schema", "description": "Define REST endpoints", "priority": "high"},
    {"id": "task_2", "title": "Implement backend", "description": "Build the service layer", "priority": "high"},
    {"id": "task_3", "title": "Write tests", "description": "Unit and integration tests", "priority": "medium"},
]


@pytest.fixture
def workspace(tmp_path):
    wm = WorkspaceManager(tmp_path)
    wm.create("project_x")
    return wm


def build_ceo(workspace, llm_responses: list[str]) -> CEOAgent:
    """Create a CEOAgent with a mock LLM that returns responses in order."""
    call_index = {"i": 0}

    def mock_llm(text: str) -> str:
        idx = call_index["i"]
        call_index["i"] += 1
        if idx < len(llm_responses):
            return llm_responses[idx]
        return json.dumps({"question": "fallback?", "done": True})

    gateway = LLMGateway(llm=mock_llm)
    return CEOAgent(gateway=gateway, workspace=workspace, workspace_id="project_x")


# --- State transitions ---

class TestStateTransitions:
    def test_initial_state_is_idle(self, workspace):
        ceo = build_ceo(workspace, [])
        assert ceo.state == "idle"

    def test_start_interview_transitions_to_interviewing(self, workspace):
        ceo = build_ceo(workspace, [make_interview_response("What is the scope?")])
        ceo.start_interview("Build a web app")
        assert ceo.state == "interviewing"

    def test_interview_done_transitions_to_planning(self, workspace):
        ceo = build_ceo(workspace, [
            make_interview_response("What is the scope?"),
            make_interview_response("", done=True),
        ])
        ceo.start_interview("Build a web app")
        ceo.answer_question("Full-stack app")
        assert ceo.state == "planning"

    def test_create_plan_transitions_to_delegating(self, workspace):
        ceo = build_ceo(workspace, [
            make_interview_response("", done=True),
            make_plan_response(SAMPLE_TASKS),
        ])
        ceo.start_interview("Build a web app")
        ceo.create_plan()
        assert ceo.state == "delegating"

    def test_delegate_transitions_to_done(self, workspace):
        ceo = build_ceo(workspace, [
            make_interview_response("", done=True),
            make_plan_response(SAMPLE_TASKS),
        ])
        ceo.start_interview("Build a web app")
        ceo.create_plan()
        ceo.delegate()
        assert ceo.state == "done"


# --- Illegal state transitions ---

class TestIllegalTransitions:
    def test_cannot_answer_before_interview(self, workspace):
        ceo = build_ceo(workspace, [])
        with pytest.raises(CEOStateError, match="interviewing"):
            ceo.answer_question("answer")

    def test_cannot_create_plan_before_interview_done(self, workspace):
        ceo = build_ceo(workspace, [make_interview_response("Q?")])
        ceo.start_interview("Build something")
        with pytest.raises(CEOStateError, match="planning"):
            ceo.create_plan()

    def test_cannot_delegate_before_plan(self, workspace):
        ceo = build_ceo(workspace, [make_interview_response("", done=True)])
        ceo.start_interview("Build something")
        with pytest.raises(CEOStateError, match="delegating"):
            ceo.delegate()

    def test_cannot_start_interview_twice(self, workspace):
        ceo = build_ceo(workspace, [make_interview_response("Q?")])
        ceo.start_interview("Build something")
        with pytest.raises(CEOStateError, match="idle"):
            ceo.start_interview("Another thing")


# --- Reverse interview ---

class TestReverseInterview:
    def test_start_interview_returns_first_question(self, workspace):
        ceo = build_ceo(workspace, [make_interview_response("What is the target user?")])
        question = ceo.start_interview("Build a mobile app")
        assert question == "What is the target user?"

    def test_multi_round_interview(self, workspace):
        ceo = build_ceo(workspace, [
            make_interview_response("Who are the users?"),
            make_interview_response("What's the deadline?"),
            make_interview_response("", done=True),
        ])
        q1 = ceo.start_interview("Build a dashboard")
        assert q1 == "Who are the users?"
        assert ceo.state == "interviewing"

        q2 = ceo.answer_question("Internal ops team")
        assert q2 == "What's the deadline?"
        assert ceo.state == "interviewing"

        q3 = ceo.answer_question("End of Q2")
        assert q3 is None  # interview done
        assert ceo.state == "planning"

    def test_interview_saves_requirement(self, workspace):
        ceo = build_ceo(workspace, [make_interview_response("Q?")])
        ceo.start_interview("Build an API gateway")
        content = workspace.read("project_x", "requirement.md")
        assert "Build an API gateway" in content

    def test_interview_saves_log(self, workspace):
        ceo = build_ceo(workspace, [
            make_interview_response("Scope?"),
            make_interview_response("", done=True),
        ])
        ceo.start_interview("Build X")
        ceo.answer_question("Full scope")
        log = workspace.read("project_x", "interview_log.md")
        assert "Scope?" in log
        assert "Full scope" in log


# --- System prompt ---

class TestSystemPrompt:
    def test_interview_prompt_includes_requirement(self, workspace):
        prompts_sent = []

        def capture_llm(text: str) -> str:
            prompts_sent.append(text)
            return make_interview_response("Q?")

        gateway = LLMGateway(llm=capture_llm)
        ceo = CEOAgent(gateway=gateway, workspace=workspace, workspace_id="project_x")
        ceo.start_interview("Build a search engine")
        assert any("Build a search engine" in p for p in prompts_sent)

    def test_interview_prompt_includes_prior_qa(self, workspace):
        prompts_sent = []
        call_count = {"i": 0}

        def capture_llm(text: str) -> str:
            prompts_sent.append(text)
            call_count["i"] += 1
            if call_count["i"] == 1:
                return make_interview_response("Users?")
            return make_interview_response("", done=True)

        gateway = LLMGateway(llm=capture_llm)
        ceo = CEOAgent(gateway=gateway, workspace=workspace, workspace_id="project_x")
        ceo.start_interview("Build X")
        ceo.answer_question("Engineers")
        # The second prompt should contain the prior Q&A
        assert any("Users?" in p and "Engineers" in p for p in prompts_sent)

    def test_plan_prompt_includes_interview_context(self, workspace):
        prompts_sent = []
        call_count = {"i": 0}

        def capture_llm(text: str) -> str:
            prompts_sent.append(text)
            call_count["i"] += 1
            if call_count["i"] == 1:
                return make_interview_response("", done=True)
            return make_plan_response(SAMPLE_TASKS)

        gateway = LLMGateway(llm=capture_llm)
        ceo = CEOAgent(gateway=gateway, workspace=workspace, workspace_id="project_x")
        ceo.start_interview("Build Y")
        ceo.create_plan()
        # The plan prompt should contain the original requirement
        plan_prompt = prompts_sent[-1]
        assert "Build Y" in plan_prompt


# --- Create plan ---

class TestCreatePlan:
    def test_returns_structured_plan(self, workspace):
        ceo = build_ceo(workspace, [
            make_interview_response("", done=True),
            make_plan_response(SAMPLE_TASKS),
        ])
        ceo.start_interview("Build a service")
        plan = ceo.create_plan()
        assert "tasks" in plan
        assert len(plan["tasks"]) == 3
        assert plan["tasks"][0]["id"] == "task_1"

    def test_writes_plan_md(self, workspace):
        ceo = build_ceo(workspace, [
            make_interview_response("", done=True),
            make_plan_response(SAMPLE_TASKS),
        ])
        ceo.start_interview("Build a service")
        ceo.create_plan()
        content = workspace.read("project_x", "plan.md")
        assert "Design API schema" in content
        assert "task_1" in content

    def test_plan_includes_all_tasks(self, workspace):
        ceo = build_ceo(workspace, [
            make_interview_response("", done=True),
            make_plan_response(SAMPLE_TASKS),
        ])
        ceo.start_interview("Build a service")
        plan = ceo.create_plan()
        ids = [t["id"] for t in plan["tasks"]]
        assert ids == ["task_1", "task_2", "task_3"]


# --- Delegate ---

class TestDelegate:
    def test_writes_task_files(self, workspace):
        ceo = build_ceo(workspace, [
            make_interview_response("", done=True),
            make_plan_response(SAMPLE_TASKS),
        ])
        ceo.start_interview("Build a service")
        ceo.create_plan()
        files = ceo.delegate()
        assert len(files) == 3
        assert "tasks/task_1.md" in files

    def test_task_file_contains_details(self, workspace):
        ceo = build_ceo(workspace, [
            make_interview_response("", done=True),
            make_plan_response(SAMPLE_TASKS),
        ])
        ceo.start_interview("Build a service")
        ceo.create_plan()
        ceo.delegate()
        content = workspace.read("project_x", "tasks/task_1.md")
        assert "Design API schema" in content
        assert "Define REST endpoints" in content
        assert "high" in content

    def test_all_task_files_exist(self, workspace):
        ceo = build_ceo(workspace, [
            make_interview_response("", done=True),
            make_plan_response(SAMPLE_TASKS),
        ])
        ceo.start_interview("Build a service")
        ceo.create_plan()
        ceo.delegate()
        for task in SAMPLE_TASKS:
            assert workspace.exists("project_x", f"tasks/{task['id']}.md")
