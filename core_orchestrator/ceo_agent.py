"""CEO orchestrator agent with 95%-confidence reverse-interview and task delegation.

State machine:
  Green-field: idle -> interviewing -> planning -> delegating -> done
  Update mode: idle -> update_planning -> delegating -> done

The CEO never writes code. It:
  1. Runs a reverse interview until it reaches ≥ 95% confidence in the
     user's real intent (scope, constraints, acceptance criteria).
  2. Injects workspace solutions (past lessons) into the planning prompt.
  3. Decomposes work into a structured plan.
  4. Delegates sub-tasks to the shared workspace for downstream agents.

In Update Mode the CEO reads existing deliverables and generates
incremental modification / fix tasks instead of a full decomposition.

Backward-compatibility: the `confidence` field in interview LLM responses
is optional — existing mock responses that omit it default to 0 (the
interview continues until `done: true`).
"""

import json
import re
from typing import List, Optional

from .json_parser import parse_llm_json
from .llm_gateway import LLMGateway
from .workspace_manager import WorkspaceManager


class CEOStateError(Exception):
    """Raised when an operation is called in the wrong state."""


# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

_INTERVIEW_SYSTEM = """\
You are a senior requirements analyst conducting a structured requirements
interview. Your job is to ask ONE focused, specific clarifying question
per round to build a complete understanding of the user's requirement.

Track your own confidence level (0–100%) across these dimensions:
  • Core functionality scope
  • Target users and deployment environment
  • Key constraints (tech stack, performance, security, budget)
  • Acceptance criteria and definition of done

Original requirement: {requirement}

Prior Q&A:
{qa_context}

Respond in strict JSON (no markdown fences):
{{
  "confidence": <integer 0-100>,
  "question": "your next focused clarifying question",
  "done": false
}}

When your confidence reaches 95 or higher, respond:
{{
  "confidence": 97,
  "question": "",
  "done": true
}}

Rules:
- Ask exactly ONE question per round — specific and immediately answerable.
- Raise confidence only when answers genuinely resolve ambiguities.
- Never repeat a question already asked.
- Cover the most impactful unknown first.
- Always respond in the user's language.
- IRON RULE: set done=true ONLY when confidence ≥ 95.
"""

_PLAN_SYSTEM = """\
You are a senior technical project manager. Decompose the following
requirement into concrete, actionable sub-tasks.

{solutions_context}

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
- If solutions_context is provided, ensure tasks explicitly avoid the
  described pitfalls and apply the lessons learned.

IRON RULE: All output MUST be in English. Internal workspace artifacts
(plan.md, tasks/*.md, feedback/*.md) are strictly English-only to
minimise token cost and maximise model reasoning quality.
"""

_UPDATE_PLAN_SYSTEM = """\
You are a senior technical project manager performing an UPDATE to an
existing project. You must generate focused, incremental tasks to modify
or fix the existing codebase.

{solutions_context}

## Existing Project Files
{file_listing}

## Update Requirement
{requirement}

Generate 1-5 focused, incremental tasks. Each task should target specific
files that need modification.

Task IDs MUST start from {next_task_id} (e.g., "task_{next_task_num}").
Do NOT reuse IDs of existing tasks.

Respond in strict JSON (no markdown fences):
{{"tasks": [
  {{"id": "task_{next_task_num}", "title": "...", "description": "...", \
"priority": "high|medium|low", "files_to_modify": ["file1.html", "file2.js"]}},
  ...
]}}

Rules:
- Each task must reference specific files to modify in "files_to_modify".
- Descriptions must be precise: explain WHAT to change and WHY.
- For bug fixes: include reproduction steps or symptoms in the description.
- For new features: explain how they integrate with existing code.
- Priorities: high (blocking/critical bug), medium (important), low (nice-to-have).
- Apply all lessons from solutions_context — never repeat a known mistake.

IRON RULE: All output MUST be in English.
"""

_NO_SOLUTIONS = "(no prior experience recorded for this workspace yet)"


class CEOAgent:
    """Orchestrator that interviews, plans, and delegates."""

    def __init__(
        self,
        gateway: LLMGateway,
        workspace: WorkspaceManager,
        workspace_id: str,
    ):
        self._gateway    = gateway
        self._workspace  = workspace
        self._ws_id      = workspace_id
        self._state      = "idle"
        self._requirement = ""
        self._qa_pairs: List[tuple] = []   # [(question, answer), ...]
        self._plan: Optional[dict] = None
        self._confidence: int = 0          # tracks LLM-reported confidence

    @property
    def state(self) -> str:
        return self._state

    @property
    def confidence(self) -> int:
        """Last reported interview confidence (0–100)."""
        return self._confidence

    def _require_state(self, expected: str) -> None:
        if self._state != expected:
            raise CEOStateError(
                f"Operation requires state '{expected}', "
                f"but current state is '{self._state}'"
            )

    # ── Interview ────────────────────────────────────────────────────────

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

    def _interview_done(self, response: dict) -> bool:
        """Return True if the interview should end.

        Ends when:
          • LLM sets done=True, OR
          • LLM reports confidence ≥ 95

        The confidence field is optional — mocks that omit it default to 0,
        so existing tests that rely on done=True continue to work correctly.
        """
        self._confidence = int(response.get("confidence", self._confidence))
        return bool(response.get("done")) or self._confidence >= 95

    def start_interview(self, requirement: str) -> Optional[str]:
        """Accept a requirement and return the first clarifying question.

        Returns None if the LLM is already ≥ 95% confident (no question needed).
        """
        self._require_state("idle")
        self._requirement = requirement
        self._state = "interviewing"

        # Persist the original requirement
        self._workspace.write(
            self._ws_id, "requirement.md",
            f"# Requirement\n\n{requirement}\n",
        )

        response = self._ask_llm_interview()

        if self._interview_done(response):
            self._state = "planning"
            self._save_interview_log()
            return None

        return response.get("question") or None

    def answer_question(self, answer: str) -> Optional[str]:
        """Provide an answer; return the next question or None if interview done."""
        self._require_state("interviewing")

        # Recover the question that was just asked from gateway history
        last_llm_response = self._gateway.history[-1]
        last_parsed = parse_llm_json(last_llm_response)
        last_question = last_parsed.get("question", "")

        self._qa_pairs.append((last_question, answer))

        response = self._ask_llm_interview()

        if self._interview_done(response):
            self._state = "planning"
            self._save_interview_log()
            return None

        return response.get("question") or None

    def _save_interview_log(self) -> None:
        lines = ["# Interview Log\n"]
        lines.append(f"**Final confidence:** {self._confidence}%\n")
        for q, a in self._qa_pairs:
            lines.append(f"## Q: {q}\n")
            lines.append(f"**A:** {a}\n")
        self._workspace.write(self._ws_id, "interview_log.md", "\n".join(lines))

    # ── Plan ─────────────────────────────────────────────────────────────

    def create_plan(self, solutions_context: str = "") -> dict:
        """Decompose the requirement into sub-tasks and write plan.md.

        Args:
            solutions_context: Formatted lessons from SolutionStore.
                               Pass "" when no history exists yet.
        """
        self._require_state("planning")

        interview_log = self._format_qa_context()
        prompt = _PLAN_SYSTEM.format(
            requirement=self._requirement,
            interview_log=interview_log,
            solutions_context=solutions_context or _NO_SOLUTIONS,
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

    # ── Update mode ──────────────────────────────────────────────────────

    def _scan_deliverables(self) -> str:
        """List existing deliverables with line counts for context."""
        try:
            all_files = self._workspace.list_files(self._ws_id)
        except Exception:
            return "(no files found)"

        deliverables = sorted(
            f for f in all_files if f.startswith("deliverables/")
        )
        if not deliverables:
            return "(no deliverables yet)"

        lines = []
        for filepath in deliverables:
            display = filepath.removeprefix("deliverables/")
            try:
                content = self._workspace.read(self._ws_id, filepath)
                lc = content.count("\n") + 1
                lines.append(f"- {display} ({lc} lines)")
            except Exception:
                lines.append(f"- {display} (unreadable)")
        return "\n".join(lines)

    def _next_task_id(self) -> int:
        """Find the next available task ID number by scanning existing tasks."""
        try:
            all_files = self._workspace.list_files(self._ws_id)
        except Exception:
            return 1

        max_num = 0
        for f in all_files:
            if f.startswith("tasks/") and f.endswith(".md"):
                basename = f.removeprefix("tasks/").removesuffix(".md")
                m = re.match(r"task_(\d+)", basename)
                if m:
                    max_num = max(max_num, int(m.group(1)))
        return max_num + 1

    def plan_update(self, requirement: str, solutions_context: str = "") -> dict:
        """Generate incremental update/fix tasks based on existing codebase.

        Args:
            requirement:      The change/fix description.
            solutions_context: Formatted lessons from SolutionStore.

        Transitions: idle -> delegating
        """
        self._require_state("idle")
        self._requirement = requirement
        self._state = "update_planning"

        self._workspace.write(
            self._ws_id, "update_requirement.md",
            f"# Update Requirement\n\n{requirement}\n",
        )

        file_listing = self._scan_deliverables()
        next_num = self._next_task_id()

        prompt = _UPDATE_PLAN_SYSTEM.format(
            file_listing=file_listing,
            requirement=requirement,
            next_task_id=f"task_{next_num}",
            next_task_num=next_num,
            solutions_context=solutions_context or _NO_SOLUTIONS,
        )
        result = self._gateway.send(prompt)
        self._plan = parse_llm_json(
            result["llm_response"],
            fallback={"tasks": []},
        )

        # Append to plan.md
        lines = [f"\n\n# Update Plan (from task_{next_num})\n"]
        for task in self._plan.get("tasks", []):
            lines.append(f"## {task['id']}: {task['title']}")
            lines.append(f"- **Priority:** {task['priority']}")
            lines.append(f"- **Description:** {task['description']}")
            files_to_mod = task.get("files_to_modify", [])
            if files_to_mod:
                lines.append(f"- **Files to modify:** {', '.join(files_to_mod)}")
            lines.append("")

        existing_plan = ""
        if self._workspace.exists(self._ws_id, "plan.md"):
            existing_plan = self._workspace.read(self._ws_id, "plan.md")
        self._workspace.write(
            self._ws_id, "plan.md",
            existing_plan + "\n".join(lines),
        )

        self._state = "delegating"
        return self._plan

    # ── Delegate ─────────────────────────────────────────────────────────

    def delegate(self) -> List[str]:
        """Write each sub-task as an individual file for downstream agents."""
        self._require_state("delegating")

        files = []
        for task in self._plan.get("tasks", []):
            filename = f"tasks/{task['id']}.md"
            lines = [
                f"# {task['title']}\n",
                f"- **ID:** {task['id']}",
                f"- **Priority:** {task['priority']}",
                f"- **Description:** {task['description']}",
            ]
            files_to_mod = task.get("files_to_modify", [])
            if files_to_mod:
                lines.append(f"- **Type:** update")
                lines.append(f"- **Files to modify:** {', '.join(files_to_mod)}")
            content = "\n".join(lines) + "\n"
            self._workspace.write(self._ws_id, filename, content)
            files.append(filename)

        self._state = "done"
        return files
