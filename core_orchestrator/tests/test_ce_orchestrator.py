"""Tests for CE (Compound Experience) orchestrator — post-mortem analysis."""

import json

import pytest

from core_orchestrator.ce_orchestrator import (
    CEOrchestrator,
    analyze_context,
    extract_solution,
    search_docs,
    plan_prevention,
    classify,
)
from core_orchestrator.llm_gateway import LLMGateway
from core_orchestrator.workspace_manager import WorkspaceManager


# --- Mock LLM responses for each sub-agent ---

CONTEXT_RESPONSE = json.dumps({
    "problem_type": "API design flaw",
    "components": ["auth module", "gateway"],
    "severity": "high",
})

SOLUTION_RESPONSE = json.dumps({
    "failed_attempts": ["Attempt 1: plain JWT — rejected for missing refresh flow"],
    "root_cause": "No token refresh mechanism in initial design",
    "final_solution": "Added OAuth2 with refresh tokens via FastAPI middleware",
})

DOC_SEARCH_RESPONSE = json.dumps({
    "existing_doc": None,
    "action": "create",
})

DOC_SEARCH_UPDATE_RESPONSE = json.dumps({
    "existing_doc": "auth_patterns.md",
    "action": "update",
})

PREVENTION_RESPONSE = json.dumps({
    "strategies": [
        "Add auth checklist to task templates",
        "Require security review for all API tasks",
    ],
})

CLASSIFY_RESPONSE = json.dumps({
    "tags": ["auth", "api", "security"],
    "category": "security/authentication",
})


# --- Fixtures ---

TASK_CONTENT = (
    "# Design auth API\n\n- **ID:** task_1\n- **Priority:** high\n"
    "- **Description:** Implement authentication endpoints\n"
)
ARTIFACT_CONTENT = "# Solution: task_1\n\n## Implementation\nOAuth2 with refresh tokens.\n"
FEEDBACK_CONTENT = "# QA Feedback: task_1\n\n## Issues\n1. Missing token refresh\n"


@pytest.fixture
def workspace(tmp_path):
    wm = WorkspaceManager(tmp_path)
    wm.create("proj")
    wm.write("proj", "tasks/task_1.md", TASK_CONTENT)
    wm.write("proj", "artifacts/task_1_solution.md", ARTIFACT_CONTENT)
    wm.write("proj", "feedback/task_1_feedback.md", FEEDBACK_CONTENT)
    return wm


@pytest.fixture
def workspace_no_feedback(tmp_path):
    wm = WorkspaceManager(tmp_path)
    wm.create("proj")
    wm.write("proj", "tasks/task_1.md", TASK_CONTENT)
    wm.write("proj", "artifacts/task_1_solution.md", ARTIFACT_CONTENT)
    return wm


ALL_RESPONSES = [
    CONTEXT_RESPONSE,
    SOLUTION_RESPONSE,
    DOC_SEARCH_RESPONSE,
    PREVENTION_RESPONSE,
    CLASSIFY_RESPONSE,
]


def build_ce(workspace, llm_responses=None, knowledge_base_path=None):
    responses = llm_responses or list(ALL_RESPONSES)
    idx = {"i": 0}

    def mock_llm(text):
        i = idx["i"]
        idx["i"] += 1
        if i < len(responses):
            return responses[i]
        return json.dumps({})

    gateway = LLMGateway(llm=mock_llm)
    return CEOrchestrator(
        gateway=gateway, workspace=workspace, workspace_id="proj",
        knowledge_base_path=knowledge_base_path,
    )


# --- Individual sub-agent functions ---

class TestAnalyzeContext:
    def test_returns_structured_result(self):
        gw = LLMGateway(llm=lambda t: CONTEXT_RESPONSE)
        result = analyze_context(gw, "some context")
        assert result["problem_type"] == "API design flaw"
        assert "auth module" in result["components"]
        assert result["severity"] == "high"

    def test_prompt_includes_context(self):
        prompts = []
        def capture(t):
            prompts.append(t)
            return CONTEXT_RESPONSE
        gw = LLMGateway(llm=capture)
        analyze_context(gw, "auth failure in gateway")
        assert any("auth failure" in p for p in prompts)


class TestExtractSolution:
    def test_returns_structured_result(self):
        gw = LLMGateway(llm=lambda t: SOLUTION_RESPONSE)
        result = extract_solution(gw, "context")
        assert len(result["failed_attempts"]) == 1
        assert "refresh" in result["root_cause"]
        assert "OAuth2" in result["final_solution"]


class TestSearchDocs:
    def test_create_action(self):
        gw = LLMGateway(llm=lambda t: DOC_SEARCH_RESPONSE)
        result = search_docs(gw, "context", [])
        assert result["action"] == "create"
        assert result["existing_doc"] is None

    def test_update_action(self):
        gw = LLMGateway(llm=lambda t: DOC_SEARCH_UPDATE_RESPONSE)
        result = search_docs(gw, "context", ["auth_patterns.md"])
        assert result["action"] == "update"
        assert result["existing_doc"] == "auth_patterns.md"

    def test_prompt_includes_existing_docs(self):
        prompts = []
        def capture(t):
            prompts.append(t)
            return DOC_SEARCH_RESPONSE
        gw = LLMGateway(llm=capture)
        search_docs(gw, "ctx", ["old_doc.md", "other.md"])
        assert any("old_doc.md" in p for p in prompts)


class TestPlanPrevention:
    def test_returns_strategies(self):
        gw = LLMGateway(llm=lambda t: PREVENTION_RESPONSE)
        result = plan_prevention(gw, "context")
        assert len(result["strategies"]) == 2


class TestClassify:
    def test_returns_tags_and_category(self):
        gw = LLMGateway(llm=lambda t: CLASSIFY_RESPONSE)
        result = classify(gw, "context")
        assert "auth" in result["tags"]
        assert result["category"] == "security/authentication"


# --- Full analyze pipeline ---

class TestAnalyze:
    def test_runs_all_five_agents(self, workspace):
        ce = build_ce(workspace)
        result = ce.analyze("task_1")
        assert "context_analysis" in result
        assert "solution_extraction" in result
        assert "doc_search" in result
        assert "prevention_plan" in result
        assert "classification" in result

    def test_writes_postmortem_file(self, workspace):
        ce = build_ce(workspace)
        ce.analyze("task_1")
        assert workspace.exists("proj", "docs/solutions/task_1_postmortem.md")

    def test_postmortem_contains_all_sections(self, workspace):
        ce = build_ce(workspace)
        ce.analyze("task_1")
        content = workspace.read("proj", "docs/solutions/task_1_postmortem.md")
        assert "Problem Type" in content or "problem_type" in content.lower()
        assert "Root Cause" in content or "root_cause" in content.lower()
        assert "Prevention" in content or "prevention" in content.lower()
        assert "Tags" in content or "tags" in content.lower()

    def test_postmortem_includes_task_id(self, workspace):
        ce = build_ce(workspace)
        ce.analyze("task_1")
        content = workspace.read("proj", "docs/solutions/task_1_postmortem.md")
        assert "task_1" in content

    def test_works_without_feedback(self, workspace_no_feedback):
        ce = build_ce(workspace_no_feedback)
        result = ce.analyze("task_1")
        assert "context_analysis" in result

    def test_context_includes_feedback_when_present(self, workspace):
        prompts = []
        def capture(t):
            prompts.append(t)
            return CONTEXT_RESPONSE
        gw = LLMGateway(llm=capture)
        ce = CEOrchestrator(gateway=gw, workspace=workspace, workspace_id="proj")
        ce.analyze("task_1")
        # At least one prompt should contain feedback content
        assert any("Missing token refresh" in p for p in prompts)


# --- Analyze all ---

class TestAnalyzeAll:
    def test_processes_all_tasks(self, workspace):
        workspace.write("proj", "tasks/task_2.md", "# Task 2\n- **ID:** task_2\n")
        workspace.write("proj", "artifacts/task_2_solution.md", "# Solution: task_2\nDone.\n")
        responses = ALL_RESPONSES + ALL_RESPONSES  # enough for 2 tasks
        ce = build_ce(workspace, llm_responses=responses)
        results = ce.analyze_all()
        assert len(results) == 2
        ids = sorted(r["task_id"] for r in results)
        assert ids == ["task_1", "task_2"]

    def test_skips_tasks_without_artifacts(self, workspace):
        workspace.write("proj", "tasks/task_2.md", "# Task 2\n")
        # No artifact for task_2
        ce = build_ce(workspace)
        results = ce.analyze_all()
        ids = [r["task_id"] for r in results]
        assert "task_1" in ids
        assert "task_2" not in ids


# --- Knowledge base dedup ---

class TestKnowledgeBaseDedup:
    def test_scans_knowledge_base_path(self, workspace, tmp_path):
        kb_path = tmp_path / "kb"
        kb_path.mkdir()
        (kb_path / "auth_patterns.md").write_text("existing doc")

        responses = list(ALL_RESPONSES)
        responses[2] = DOC_SEARCH_UPDATE_RESPONSE  # doc searcher says update

        ce = build_ce(workspace, llm_responses=responses,
                      knowledge_base_path=str(kb_path))
        result = ce.analyze("task_1")
        assert result["doc_search"]["action"] == "update"

    def test_empty_knowledge_base(self, workspace, tmp_path):
        kb_path = tmp_path / "kb_empty"
        kb_path.mkdir()

        ce = build_ce(workspace, knowledge_base_path=str(kb_path))
        result = ce.analyze("task_1")
        assert result["doc_search"]["action"] == "create"


# --- _safe_dict robustness ---

class TestSafeDict:
    """_format_postmortem must tolerate list / dict / garbage sub-agent results."""

    def test_dict_passthrough(self):
        assert CEOrchestrator._safe_dict({"a": 1}) == {"a": 1}

    def test_list_wrapped(self):
        result = CEOrchestrator._safe_dict(["s1", "s2"], default_key="strategies")
        assert result == {"strategies": ["s1", "s2"]}

    def test_none_returns_empty_dict(self):
        assert CEOrchestrator._safe_dict(None) == {}

    def test_string_returns_empty_dict(self):
        assert CEOrchestrator._safe_dict("garbage") == {}

    def test_postmortem_with_list_prevention(self, workspace):
        """Reproduce the original bug: prevention_plan comes back as a list."""
        responses = list(ALL_RESPONSES)
        # prevention agent returns a bare list instead of {"strategies": [...]}
        responses[3] = json.dumps(["add tests", "code review"])
        ce = build_ce(workspace, llm_responses=responses)
        result = ce.analyze("task_1")
        content = workspace.read("proj", "docs/solutions/task_1_postmortem.md")
        assert "add tests" in content
        assert "code review" in content

    def test_postmortem_with_list_context(self, workspace):
        """context_analysis returns a list instead of dict."""
        responses = list(ALL_RESPONSES)
        responses[0] = json.dumps(["item1", "item2"])
        ce = build_ce(workspace, llm_responses=responses)
        # Should not raise
        result = ce.analyze("task_1")
        assert "context_analysis" in result
