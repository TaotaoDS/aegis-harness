"""CEO orchestrator agent with reverse-interview and task delegation.

State machine: idle -> interviewing -> planning -> delegating -> done

The CEO never writes code. It clarifies requirements via reverse interview,
decomposes work into a structured plan, and delegates sub-tasks to the
shared workspace for downstream agents.
"""

import json
from typing import Optional

from .json_parser import parse_llm_json
from .llm_gateway import LLMGateway
from .workspace_manager import WorkspaceManager


class CEOStateError(Exception):
    """Raised when an operation is called in the wrong state."""


# --- System prompts ---

_INTERVIEW_SYSTEM = """\
You are a senior requirements analyst. Your job is to ask ONE focused \
clarifying question about the user's requirement to lock down scope, \
constraints, priorities, or acceptance criteria.

IMPORTANT: Always respond in the user's language (match the language of \
the original requirement). You are the translation gateway between the \
user and the internal English-only pipeline.

Context so far:
- Original requirement: {requirement}
{qa_context}

Respond in strict JSON (no markdown fences):
{{"question": "your clarifying question here", "done": false}}

If you have enough information to fully specify the requirement, respond:
{{"question": "", "done": true}}
"""

_PLAN_SYSTEM = """\
You are a senior technical project manager. Decompose the following \
requirement into concrete, actionable sub-tasks.

Requirement: {requirement}

Interview context:
{interview_log}

Respond in strict JSON (no markdown fences):
{{"tasks": [
  {{"id": "task_1", "title": "...", "description": "...", "priority": "high|medium|low"}},
  ...
]}}

Rules:
- 3-7 tasks, ordered by dependency.
- Each task must be independently assignable to a single agent.
- Priorities: high (blocking), medium (important), low (nice-to-have).

IRON RULE: All output MUST be in English. Internal workspace artifacts \
(plan.md, tasks/*.md, feedback/*.md, docs/solutions/*.md) are strictly \
English-only to minimize token cost and maximize model reasoning quality.
"""


class CEOAgent:
    """Orchestrator that interviews, plans, and delegates."""

    def __init__(
        self,
        gateway: LLMGateway,
        workspace: WorkspaceManager,
        workspace_id: str,
    ):
        self._gateway = gateway
        self._workspace = workspace
        self._ws_id = workspace_id
        self._state = "idle"
        self._requirement = ""
        self._qa_pairs: list[tuple[str, str]] = []  # (question, answer)
        self._plan: Optional[dict] = None

    @property
    def state(self) -> str:
        return self._state

    def _require_state(self, expected: str) -> None:
        if self._state != expected:
            raise CEOStateError(
                f"Operation requires state '{expected}', but current state is '{self._state}'"
            )

    # --- Interview ---

    def _format_qa_context(self) -> str:
        if not self._qa_pairs:
            return "- No prior Q&A yet."
        lines = []
        for q, a in self._qa_pairs:
            lines.append(f"- Q: {q}")
            lines.append(f"  A: {a}")
        return "\n".join(lines)

    def _ask_llm_interview(self) -> dict:
        prompt = _INTERVIEW_SYSTEM.format(
            requirement=self._requirement,
            qa_context=self._format_qa_context(),
        )
        result = self._gateway.send(prompt)
        return parse_llm_json(result["llm_response"])

    def start_interview(self, requirement: str) -> str:
        """Accept a requirement and return the first clarifying question."""
        self._require_state("idle")
        self._requirement = requirement
        self._state = "interviewing"

        # Persist the original requirement
        self._workspace.write(self._ws_id, "requirement.md", f"# Requirement\n\n{requirement}\n")

        response = self._ask_llm_interview()
        if response.get("done"):
            self._state = "planning"
            self._save_interview_log()
            return None

        first_question = response["question"]
        return first_question

    def answer_question(self, answer: str) -> Optional[str]:
        """Provide an answer and get the next question, or None if done."""
        self._require_state("interviewing")

        # Record the previous question (from the last LLM response)
        # We need to reconstruct: the last question asked was returned to the user
        # We re-ask the LLM with the new answer included
        # First, figure out what the last question was by re-parsing isn't ideal,
        # so we track it properly:
        # The last question is whatever start_interview or the previous answer_question returned.
        # We store pending question in _pending_question.
        # But we didn't store it — let's reconstruct from gateway history.
        # Simpler: peek at the last LLM response in gateway history.
        last_llm_response = self._gateway.history[-1]
        last_parsed = parse_llm_json(last_llm_response)
        last_question = last_parsed.get("question", "")

        self._qa_pairs.append((last_question, answer))

        response = self._ask_llm_interview()
        if response.get("done"):
            self._state = "planning"
            self._save_interview_log()
            return None

        return response["question"]

    def _save_interview_log(self) -> None:
        lines = ["# Interview Log\n"]
        for q, a in self._qa_pairs:
            lines.append(f"## Q: {q}\n")
            lines.append(f"**A:** {a}\n")
        self._workspace.write(self._ws_id, "interview_log.md", "\n".join(lines))

    # --- Plan ---

    def create_plan(self) -> dict:
        """Decompose the requirement into sub-tasks and write plan.md."""
        self._require_state("planning")

        interview_log = self._format_qa_context()
        prompt = _PLAN_SYSTEM.format(
            requirement=self._requirement,
            interview_log=interview_log,
        )
        result = self._gateway.send(prompt)
        self._plan = parse_llm_json(
            result["llm_response"],
            fallback={"tasks": []},
        )

        # Write human-readable plan.md
        lines = ["# Plan\n"]
        for task in self._plan.get("tasks", []):
            lines.append(f"## {task['id']}: {task['title']}")
            lines.append(f"- **Priority:** {task['priority']}")
            lines.append(f"- **Description:** {task['description']}")
            lines.append("")
        self._workspace.write(self._ws_id, "plan.md", "\n".join(lines))

        self._state = "delegating"
        return self._plan

    # --- Delegate ---

    def delegate(self) -> list[str]:
        """Write each sub-task as an individual file for downstream agents."""
        self._require_state("delegating")

        files = []
        for task in self._plan.get("tasks", []):
            filename = f"tasks/{task['id']}.md"
            content = (
                f"# {task['title']}\n\n"
                f"- **ID:** {task['id']}\n"
                f"- **Priority:** {task['priority']}\n"
                f"- **Description:** {task['description']}\n"
            )
            self._workspace.write(self._ws_id, filename, content)
            files.append(filename)

        self._state = "done"
        return files
