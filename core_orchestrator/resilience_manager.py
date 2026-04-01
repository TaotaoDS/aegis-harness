"""Resilience manager: 3-layer escalation guard for Architect-QA loops.

Layer 1 (Context Reset):   1st QA fail → fresh Architect gateway, inject feedback
Layer 2 (Model Escalation): 2nd QA fail → switch to escalated (advanced) gateway
Layer 3 (Graceful Degradation): 3rd fail OR token budget >= 80% → stop, request human
"""

import json
from typing import Callable, Dict, List

import tiktoken

from .architect_agent import ArchitectAgent
from .llm_gateway import LLMGateway
from .qa_agent import QAAgent
from .workspace_manager import WorkspaceManager

_DEFAULT_MAX_RETRIES = 3
_DEFAULT_TOKEN_BUDGET = 100_000
_DEFAULT_TOKEN_THRESHOLD = 0.8

_encoding = tiktoken.get_encoding("cl100k_base")


def _count_tokens(text: str) -> int:
    return len(_encoding.encode(text))


class ResilienceManager:
    """Monitors Architect-QA loops with 3-layer progressive escalation."""

    def __init__(
        self,
        workspace: WorkspaceManager,
        workspace_id: str,
        gateway_factory: Callable[[], LLMGateway],
        escalated_gateway_factory: Callable[[], LLMGateway],
        qa_gateway: LLMGateway,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        token_budget: int = _DEFAULT_TOKEN_BUDGET,
        token_threshold: float = _DEFAULT_TOKEN_THRESHOLD,
    ):
        self._workspace = workspace
        self._ws_id = workspace_id
        self._gateway_factory = gateway_factory
        self._escalated_gateway_factory = escalated_gateway_factory
        self._qa_gateway = qa_gateway
        self._max_retries = max_retries
        self._token_budget = token_budget
        self._token_threshold = token_threshold
        self._token_usage = 0
        self._results: List[Dict] = []

    def _track_tokens(self, gateway: LLMGateway) -> None:
        """Accumulate token usage from a gateway's history."""
        for entry in gateway.history:
            self._token_usage += _count_tokens(entry)

    def _budget_exceeded(self) -> bool:
        return self._token_usage >= self._token_budget * self._token_threshold

    def _write_escalation(self, task_id: str, attempts: int, last_issues: str) -> str:
        """Write an escalation file requesting human intervention."""
        path = f"escalations/{task_id}_escalation.md"
        content = (
            f"# Escalation: {task_id}\n\n"
            f"**Status:** Requires human intervention\n"
            f"**Attempts exhausted:** {attempts}\n"
            f"**Token usage:** {self._token_usage}\n\n"
            f"## Last Known Issues\n{last_issues}\n\n"
            f"## Action Required\n"
            f"The automated Architect-QA loop could not resolve this task.\n"
            f"Please review `artifacts/{task_id}_solution.md` (best effort) "
            f"and `feedback/{task_id}_feedback.md` (latest issues), "
            f"then provide manual guidance or resolution.\n"
        )
        self._workspace.write(self._ws_id, path, content)
        return path

    def run_task_loop(self, task_id: str) -> Dict:
        """Run the Architect-QA loop for a single task with 3-layer escalation."""
        task_file = f"tasks/{task_id}.md"
        escalation_level = 0
        last_issues = ""

        for attempt in range(1, self._max_retries + 1):
            # Check token budget before each attempt
            if self._budget_exceeded():
                self._write_escalation(task_id, attempt - 1, last_issues)
                result = {
                    "task_id": task_id, "verdict": "escalated",
                    "attempts": attempt - 1, "escalation_level": escalation_level,
                    "path": f"escalations/{task_id}_escalation.md",
                }
                self._results.append(result)
                return result

            # Select gateway based on escalation level
            if escalation_level < 2:
                arch_gateway = self._gateway_factory()
            else:
                arch_gateway = self._escalated_gateway_factory()

            # Architect generates solution
            architect = ArchitectAgent(
                gateway=arch_gateway,
                workspace=self._workspace,
                workspace_id=self._ws_id,
            )
            architect.solve_task(task_file)
            self._track_tokens(arch_gateway)

            # QA reviews
            qa = QAAgent(
                gateway=self._qa_gateway,
                workspace=self._workspace,
                workspace_id=self._ws_id,
            )
            review = qa.review_task(task_id)
            self._track_tokens(self._qa_gateway)

            if review["verdict"] == "pass":
                result = {
                    "task_id": task_id, "verdict": "pass",
                    "attempts": attempt, "escalation_level": escalation_level,
                    "path": review["path"],
                }
                self._results.append(result)
                return result

            # QA failed — escalate
            last_feedback = ""
            if self._workspace.exists(self._ws_id, f"feedback/{task_id}_feedback.md"):
                last_feedback = self._workspace.read(
                    self._ws_id, f"feedback/{task_id}_feedback.md"
                )
            last_issues = last_feedback

            if attempt == 1:
                # Layer 1: Context reset (next iteration creates fresh gateway)
                escalation_level = 1
            elif attempt == 2:
                # Layer 2: Model escalation
                escalation_level = 2

        # Layer 3: All retries exhausted
        self._write_escalation(task_id, self._max_retries, last_issues)
        result = {
            "task_id": task_id, "verdict": "escalated",
            "attempts": self._max_retries, "escalation_level": 3,
            "path": f"escalations/{task_id}_escalation.md",
        }
        self._results.append(result)
        return result

    def run_all(self) -> List[Dict]:
        """Run the resilience loop for every task in tasks/."""
        all_files = self._workspace.list_files(self._ws_id)
        task_ids = sorted(
            f.removeprefix("tasks/").removesuffix(".md")
            for f in all_files
            if f.startswith("tasks/") and f.endswith(".md")
        )
        return [self.run_task_loop(tid) for tid in task_ids]

    def status(self) -> Dict:
        """Return overall status of all managed tasks."""
        completed = [r["task_id"] for r in self._results if r["verdict"] == "pass"]
        escalated = [r["task_id"] for r in self._results if r["verdict"] == "escalated"]
        return {
            "completed": completed,
            "escalated": escalated,
            "token_usage": self._token_usage,
        }
