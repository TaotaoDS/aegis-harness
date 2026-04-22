"""Tests for ReflectionAgent — post-execution knowledge distillation."""

import json

import pytest

from core_orchestrator.llm_gateway import LLMGateway
from core_orchestrator.reflection_agent import ReflectionAgent, _format_event_log
from core_orchestrator.solution_store import SolutionStore
from core_orchestrator.workspace_manager import WorkspaceManager


# ---------------------------------------------------------------------------
# Helpers & fixtures
# ---------------------------------------------------------------------------

def make_lessons_response(lessons: list) -> str:
    return json.dumps({"lessons": lessons})


GOOD_LESSON = {
    "type": "error_fix",
    "problem": "Missing CORS header caused 403 in production",
    "solution": "Add CORSMiddleware with allow_origins=['*'] for dev",
    "context": "FastAPI app on port 8000",
    "tags": ["python", "cors"],
}

MINIMAL_LESSON = {
    "type": "best_practice",
    "problem": "Always use f-strings",
    "solution": "Replace .format() calls",
}


@pytest.fixture
def workspace(tmp_path):
    wm = WorkspaceManager(tmp_path, isolated=True)
    wm.create("test_ws")
    return wm


@pytest.fixture
def store(workspace):
    return SolutionStore(workspace, "test_ws")


def build_agent(workspace, responses: list[str]) -> ReflectionAgent:
    """Create a ReflectionAgent with a mock LLM."""
    idx = {"i": 0}

    def mock_llm(text: str) -> str:
        i = idx["i"]
        idx["i"] += 1
        return responses[i] if i < len(responses) else json.dumps({"lessons": []})

    gateway = LLMGateway(llm=mock_llm)
    return ReflectionAgent(
        gateway=gateway,
        workspace=workspace,
        workspace_id="test_ws",
    )


SAMPLE_EVENTS = [
    {
        "type": "pipeline.start",
        "label": "🚀 任务已启动",
        "data": {},
        "timestamp": "2025-04-22T10:00:00",
        "job_id": "abc123",
    },
    {
        "type": "evaluator.fail",
        "label": "🔴 沙箱验证失败",
        "data": {"task_id": "task_1", "feedback": "SyntaxError on line 5"},
        "timestamp": "2025-04-22T10:01:00",
        "job_id": "abc123",
    },
    {
        "type": "evaluator.pass",
        "label": "✅ 沙箱验证通过",
        "data": {"task_id": "task_1"},
        "timestamp": "2025-04-22T10:02:00",
        "job_id": "abc123",
    },
    {
        "type": "pipeline.complete",
        "label": "🎉 全部任务完成",
        "data": {},
        "timestamp": "2025-04-22T10:03:00",
        "job_id": "abc123",
    },
]


# ---------------------------------------------------------------------------
# TestReflect
# ---------------------------------------------------------------------------

class TestReflect:
    def test_returns_count_of_saved_lessons(self, workspace):
        agent = build_agent(workspace, [make_lessons_response([GOOD_LESSON])])
        count = agent.reflect(SAMPLE_EVENTS, requirement="Build REST API")
        assert count == 1

    def test_saves_to_solution_store(self, workspace, store):
        agent = build_agent(workspace, [make_lessons_response([GOOD_LESSON])])
        agent.reflect(SAMPLE_EVENTS, requirement="Build REST API")
        assert store.count() == 1

    def test_saved_lesson_content_correct(self, workspace, store):
        agent = build_agent(workspace, [make_lessons_response([GOOD_LESSON])])
        agent.reflect(SAMPLE_EVENTS, requirement="Build REST API")
        solutions = store.load_all()
        assert solutions[0]["problem"] == GOOD_LESSON["problem"]
        assert solutions[0]["solution"] == GOOD_LESSON["solution"]

    def test_stamps_job_id_when_provided(self, workspace, store):
        agent = build_agent(workspace, [make_lessons_response([GOOD_LESSON])])
        agent.reflect(SAMPLE_EVENTS, requirement="req", job_id="myjob99")
        saved = store.load_all()[0]
        assert saved["job_id"] == "myjob99"

    def test_multiple_lessons_all_saved(self, workspace, store):
        lessons = [GOOD_LESSON, MINIMAL_LESSON]
        agent = build_agent(workspace, [make_lessons_response(lessons)])
        count = agent.reflect(SAMPLE_EVENTS, requirement="req")
        assert count == 2
        assert store.count() == 2

    def test_empty_lessons_saves_nothing(self, workspace, store):
        agent = build_agent(workspace, [make_lessons_response([])])
        count = agent.reflect(SAMPLE_EVENTS, requirement="req")
        assert count == 0
        assert store.count() == 0

    def test_lesson_missing_problem_is_skipped(self, workspace, store):
        bad = {"type": "error_fix", "solution": "Fix it"}   # no problem
        agent = build_agent(workspace, [make_lessons_response([bad])])
        count = agent.reflect(SAMPLE_EVENTS, requirement="req")
        assert count == 0

    def test_lesson_missing_solution_is_skipped(self, workspace, store):
        bad = {"type": "error_fix", "problem": "Something broke"}   # no solution
        agent = build_agent(workspace, [make_lessons_response([bad])])
        count = agent.reflect(SAMPLE_EVENTS, requirement="req")
        assert count == 0

    def test_non_dict_lesson_is_skipped(self, workspace, store):
        agent = build_agent(workspace, [make_lessons_response(["not a dict", 42])])
        count = agent.reflect(SAMPLE_EVENTS, requirement="req")
        assert count == 0

    def test_empty_events_log_still_works(self, workspace):
        agent = build_agent(workspace, [make_lessons_response([GOOD_LESSON])])
        count = agent.reflect([], requirement="req")
        assert count == 1   # LLM can still produce best-practices


# ---------------------------------------------------------------------------
# TestBusEvents
# ---------------------------------------------------------------------------

class TestBusEvents:
    def test_emits_reflection_start(self, workspace):
        emitted = []

        class FakeBus:
            def emit(self, event, **kwargs):
                emitted.append(event)

        agent = build_agent(workspace, [make_lessons_response([GOOD_LESSON])])
        agent.reflect(SAMPLE_EVENTS, requirement="req", bus=FakeBus())
        assert "reflection.start" in emitted

    def test_emits_reflection_complete(self, workspace):
        emitted = []

        class FakeBus:
            def emit(self, event, **kwargs):
                emitted.append(event)

        agent = build_agent(workspace, [make_lessons_response([GOOD_LESSON])])
        agent.reflect(SAMPLE_EVENTS, requirement="req", bus=FakeBus())
        assert "reflection.complete" in emitted

    def test_emits_solution_saved_per_lesson(self, workspace):
        emitted = []

        class FakeBus:
            def emit(self, event, **kwargs):
                emitted.append(event)

        lessons = [GOOD_LESSON, MINIMAL_LESSON]
        agent = build_agent(workspace, [make_lessons_response(lessons)])
        agent.reflect(SAMPLE_EVENTS, requirement="req", bus=FakeBus())
        saved_events = [e for e in emitted if e == "reflection.solution_saved"]
        assert len(saved_events) == 2

    def test_complete_event_includes_count(self, workspace):
        events_data = []

        class FakeBus:
            def emit(self, event, **kwargs):
                events_data.append((event, kwargs))

        agent = build_agent(workspace, [make_lessons_response([GOOD_LESSON, MINIMAL_LESSON])])
        agent.reflect(SAMPLE_EVENTS, requirement="req", bus=FakeBus())
        complete = next(d for e, d in events_data if e == "reflection.complete")
        assert complete["saved"] == 2


# ---------------------------------------------------------------------------
# TestMalformedLLMResponse
# ---------------------------------------------------------------------------

class TestMalformedLLMResponse:
    def test_garbage_response_returns_zero(self, workspace):
        agent = build_agent(workspace, ["not json at all!!!"])
        count = agent.reflect(SAMPLE_EVENTS, requirement="req")
        assert count == 0

    def test_missing_lessons_key_returns_zero(self, workspace):
        agent = build_agent(workspace, [json.dumps({"result": []})])
        count = agent.reflect(SAMPLE_EVENTS, requirement="req")
        assert count == 0

    def test_exception_in_llm_returns_zero(self, workspace):
        def crashing_llm(text):
            raise RuntimeError("LLM down")

        gateway = LLMGateway(llm=crashing_llm)
        agent = ReflectionAgent(
            gateway=gateway,
            workspace=workspace,
            workspace_id="test_ws",
        )
        # Must not propagate the exception
        count = agent.reflect(SAMPLE_EVENTS, requirement="req")
        assert count == 0


# ---------------------------------------------------------------------------
# TestFormatEventLog
# ---------------------------------------------------------------------------

class TestFormatEventLog:
    def test_empty_log_returns_placeholder(self):
        result = _format_event_log([])
        assert result == "(empty event log)"

    def test_includes_event_labels(self):
        result = _format_event_log(SAMPLE_EVENTS)
        assert "🚀" in result or "pipeline.start" in result

    def test_truncates_long_logs(self):
        many_events = SAMPLE_EVENTS * 100   # ~4x the truncation limit
        result = _format_event_log(many_events, max_chars=500)
        assert len(result) <= 600   # some overhead for the truncation notice

    def test_includes_diagnostic_fields(self):
        result = _format_event_log(SAMPLE_EVENTS)
        assert "SyntaxError on line 5" in result   # feedback field from evaluator.fail

    def test_returns_string(self):
        result = _format_event_log(SAMPLE_EVENTS)
        assert isinstance(result, str)
