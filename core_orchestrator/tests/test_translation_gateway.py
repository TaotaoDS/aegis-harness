"""Tests for multilingual translation gateway — English-only internal artifacts.

Iron Rule: All internal workspace artifacts (plan.md, tasks/*.md, feedback/*.md,
docs/solutions/*.md) MUST be in English. CEO acts as translation gateway:
user's language for user-facing communication, pure English internally.
"""

import json

import pytest

from core_orchestrator.ceo_agent import CEOAgent, _INTERVIEW_SYSTEM, _PLAN_SYSTEM
from core_orchestrator.architect_agent import ArchitectAgent, _SOLVE_SYSTEM
from core_orchestrator.qa_agent import QAAgent, _REVIEW_SYSTEM
from core_orchestrator.ce_orchestrator import (
    _CONTEXT_PROMPT, _SOLUTION_PROMPT, _DOC_SEARCH_PROMPT,
    _PREVENTION_PROMPT, _CLASSIFY_PROMPT,
)
from core_orchestrator.llm_gateway import LLMGateway
from core_orchestrator.workspace_manager import WorkspaceManager


ENGLISH_RULE_MARKER = "IRON RULE"
ENGLISH_KEYWORD = "English"


# ---------------------------------------------------------------------------
# 1. CEO — Interview prompt: user-language instruction
# ---------------------------------------------------------------------------

class TestCEOInterviewLanguage:
    """CEO interview prompt must instruct LLM to respond in user's language."""

    def test_interview_prompt_mentions_user_language(self):
        """The interview system prompt should instruct responding in user's native language."""
        sample = _INTERVIEW_SYSTEM.format(requirement="test", qa_context="none")
        assert "user" in sample.lower() and "language" in sample.lower()

    def test_interview_prompt_sent_to_llm_contains_language_instruction(self, tmp_path):
        """Verify the actual prompt sent to the LLM during interview contains language instruction."""
        prompts = []

        def capture(text):
            prompts.append(text)
            return json.dumps({"question": "Q?", "done": False})

        wm = WorkspaceManager(tmp_path)
        wm.create("proj")
        gw = LLMGateway(llm=capture)
        ceo = CEOAgent(gateway=gw, workspace=wm, workspace_id="proj")
        ceo.start_interview("Build an API")
        assert any("language" in p.lower() for p in prompts)


# ---------------------------------------------------------------------------
# 2. CEO — Plan prompt: English iron rule
# ---------------------------------------------------------------------------

class TestCEOPlanEnglish:
    """CEO plan prompt must enforce English-only output."""

    def test_plan_prompt_contains_english_rule(self):
        sample = _PLAN_SYSTEM.format(requirement="test", interview_log="none")
        assert ENGLISH_KEYWORD in sample

    def test_plan_prompt_contains_iron_rule(self):
        sample = _PLAN_SYSTEM.format(requirement="test", interview_log="none")
        assert ENGLISH_RULE_MARKER in sample

    def test_plan_prompt_sent_to_llm(self, tmp_path):
        """Verify the actual plan prompt enforces English."""
        prompts = []
        call_count = {"i": 0}

        def capture(text):
            prompts.append(text)
            call_count["i"] += 1
            if call_count["i"] == 1:
                return json.dumps({"question": "", "done": True})
            return json.dumps({"tasks": [
                {"id": "task_1", "title": "Do X", "description": "Details", "priority": "high"}
            ]})

        wm = WorkspaceManager(tmp_path)
        wm.create("proj")
        gw = LLMGateway(llm=capture)
        ceo = CEOAgent(gateway=gw, workspace=wm, workspace_id="proj")
        ceo.start_interview("Build X")
        ceo.create_plan()
        plan_prompt = prompts[-1]
        assert ENGLISH_KEYWORD in plan_prompt


# ---------------------------------------------------------------------------
# 3. Architect — English iron rule
# ---------------------------------------------------------------------------

class TestArchitectEnglish:
    """Architect prompt must enforce English-only output."""

    def test_solve_prompt_contains_english_rule(self):
        sample = _SOLVE_SYSTEM.format(plan_context="", task_content="test", knowledge_context="", feedback_context="", codebase_context="")
        assert ENGLISH_KEYWORD in sample

    def test_solve_prompt_contains_iron_rule(self):
        sample = _SOLVE_SYSTEM.format(plan_context="", task_content="test", knowledge_context="", feedback_context="", codebase_context="")
        assert ENGLISH_RULE_MARKER in sample

    def test_prompt_sent_to_llm_enforces_english(self, tmp_path):
        captured = {}

        def capture_tool_llm(system, user_prompt, tools, tool_handler=None):
            captured["system"] = system
            return []

        wm = WorkspaceManager(tmp_path)
        wm.create("proj")
        wm.write("proj", "tasks/task_1.md", "# Task 1\n- **ID:** task_1\n")
        arch = ArchitectAgent(tool_llm=capture_tool_llm, workspace=wm, workspace_id="proj")
        arch.solve_task("tasks/task_1.md")
        assert ENGLISH_KEYWORD in captured["system"]

    def test_prompt_forbids_specification_only(self):
        """Architect prompt must forbid specification-only responses."""
        sample = _SOLVE_SYSTEM.format(plan_context="", task_content="test", knowledge_context="", feedback_context="", codebase_context="")
        assert "CODE PRODUCER" in sample or "REJECTED" in sample

    def test_prompt_requires_tool_use(self):
        """Architect prompt must require write_file tool use."""
        sample = _SOLVE_SYSTEM.format(plan_context="", task_content="test", knowledge_context="", feedback_context="", codebase_context="")
        assert "write_file" in sample


# ---------------------------------------------------------------------------
# 4. QA — English iron rule
# ---------------------------------------------------------------------------

class TestQAEnglish:
    """QA prompt must enforce English-only output."""

    def test_review_prompt_contains_english_rule(self):
        sample = _REVIEW_SYSTEM.format(task_content="test", solution_content="test")
        assert ENGLISH_KEYWORD in sample

    def test_review_prompt_contains_iron_rule(self):
        sample = _REVIEW_SYSTEM.format(task_content="test", solution_content="test")
        assert ENGLISH_RULE_MARKER in sample

    def test_prompt_sent_to_llm_enforces_english(self, tmp_path):
        prompts = []

        def capture(text):
            prompts.append(text)
            return json.dumps({"verdict": "pass", "issues": [], "notes": "ok"})

        wm = WorkspaceManager(tmp_path)
        wm.create("proj")
        wm.write("proj", "tasks/task_1.md", "# Task\n")
        wm.write("proj", "artifacts/task_1_solution.md", "# Solution\n")
        gw = LLMGateway(llm=capture)
        qa = QAAgent(gateway=gw, workspace=wm, workspace_id="proj")
        qa.review_task("task_1")
        assert any(ENGLISH_KEYWORD in p for p in prompts)


# ---------------------------------------------------------------------------
# 5. CE Orchestrator — already English (verification)
# ---------------------------------------------------------------------------

class TestCEOrchestratorEnglish:
    """CE Orchestrator prompts should already be in English."""

    def test_context_prompt_is_english(self):
        assert "context analyst" in _CONTEXT_PROMPT.lower() or "English" in _CONTEXT_PROMPT

    def test_solution_prompt_is_english(self):
        assert "solution analyst" in _SOLUTION_PROMPT.lower() or "English" in _SOLUTION_PROMPT

    def test_doc_search_prompt_is_english(self):
        assert "documentation" in _DOC_SEARCH_PROMPT.lower()

    def test_prevention_prompt_is_english(self):
        assert "prevention" in _PREVENTION_PROMPT.lower()

    def test_classify_prompt_is_english(self):
        assert "classifier" in _CLASSIFY_PROMPT.lower()
