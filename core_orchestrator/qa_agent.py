"""QA evaluator agent: reviews artifacts against task requirements.

The QA agent NEVER modifies code. It either approves (copies to approved/)
or rejects (writes feedback to feedback/) for the Architect to rework.
"""

import json
from typing import Dict, List

from .json_parser import parse_llm_json
from .llm_gateway import LLMGateway
from .workspace_manager import WorkspaceManager


class QAError(Exception):
    """Raised for QA-specific errors (missing files, bad responses)."""


_REVIEW_SYSTEM = """\
You are a strict QA engineer. Review the solution against the task requirements.

## Original Task
{task_content}

## Proposed Solution
{solution_content}

Evaluate for:
1. Completeness — does it address every requirement in the task?
2. Correctness — are the technical choices sound?
3. Security — any obvious vulnerabilities?
4. Clarity — is it well-structured and maintainable?

Respond in strict JSON (no markdown fences):
{{"verdict": "pass" or "fail", "issues": ["issue1", ...], "notes": "overall assessment"}}

If ALL criteria are met, verdict is "pass" with an empty issues list.
If ANY criterion fails, verdict is "fail" with specific issues listed.
Be strict. When in doubt, fail.

IRON RULE: All output MUST be in English. Internal workspace artifacts \
(feedback/*.md, approved/*.md) are strictly English-only to minimize \
token cost and maximize model reasoning quality.
"""


class QAAgent:
    """Reviews artifacts and gates them into approved/ or feedback/."""

    def __init__(
        self,
        gateway: LLMGateway,
        workspace: WorkspaceManager,
        workspace_id: str,
        bus=None,
    ):
        from .event_bus import NullBus
        self._gateway = gateway
        self._workspace = workspace
        self._ws_id = workspace_id
        self._results: List[Dict] = []
        self._bus = bus or NullBus()

    def _require_file(self, filename: str, label: str) -> str:
        """Read a file or raise QAError with a clear message."""
        if not self._workspace.exists(self._ws_id, filename):
            raise QAError(f"QA: {label} not found: '{filename}'")
        return self._workspace.read(self._ws_id, filename)

    def review_task(self, task_id: str) -> Dict:
        """Review a single task's artifact. Returns {"task_id", "verdict", "path"}."""
        task_file = f"tasks/{task_id}.md"
        artifact_file = f"artifacts/{task_id}_solution.md"

        task_content = self._require_file(task_file, "task file")
        solution_content = self._require_file(artifact_file, "artifact")

        prompt = _REVIEW_SYSTEM.format(
            task_content=task_content,
            solution_content=solution_content,
        )
        self._bus.emit("qa.reviewing", task_id=task_id)
        response = self._gateway.send(prompt)
        review = parse_llm_json(
            response["llm_response"],
            fallback={"verdict": "fail", "issues": ["LLM returned unparseable response"], "notes": ""},
        )

        verdict = review.get("verdict", "fail")

        if verdict == "pass":
            path = f"approved/{task_id}_solution.md"
            self._workspace.write(self._ws_id, path, solution_content)
            self._bus.emit("qa.approved", task_id=task_id, path=path)
        else:
            path = f"feedback/{task_id}_feedback.md"
            feedback = self._format_feedback(task_id, review)
            self._workspace.write(self._ws_id, path, feedback)
            self._bus.emit("qa.rejected", task_id=task_id, issues=review.get("issues", []))

        result = {"task_id": task_id, "verdict": verdict, "path": path}
        self._results.append(result)
        return result

    def _format_feedback(self, task_id: str, review: Dict) -> str:
        """Format a human-readable feedback file."""
        lines = [
            f"# QA Feedback: {task_id}\n",
            f"**Verdict:** FAIL\n",
            f"**Notes:** {review.get('notes', '')}\n",
            "## Issues\n",
        ]
        for i, issue in enumerate(review.get("issues", []), 1):
            lines.append(f"{i}. {issue}")
        lines.append("\n\n---\n*Action required: Architect must rework this task.*\n")
        return "\n".join(lines)

    def review_all(self) -> List[Dict]:
        """Review all tasks that have corresponding artifacts."""
        all_files = self._workspace.list_files(self._ws_id)
        task_ids = sorted(
            f.removeprefix("tasks/").removesuffix(".md")
            for f in all_files
            if f.startswith("tasks/") and f.endswith(".md")
        )
        # Only review tasks that have artifacts
        reviewable = [
            tid for tid in task_ids
            if self._workspace.exists(self._ws_id, f"artifacts/{tid}_solution.md")
        ]
        return [self.review_task(tid) for tid in reviewable]

    def summary(self) -> Dict:
        """Return a summary of all reviews performed so far."""
        passed = [r["task_id"] for r in self._results if r["verdict"] == "pass"]
        failed = [r["task_id"] for r in self._results if r["verdict"] == "fail"]
        return {"passed": passed, "failed": failed, "total": len(self._results)}
