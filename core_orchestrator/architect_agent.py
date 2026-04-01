"""Architect agent: reads tasks, generates technical solutions via LLM,
and writes artifacts to the shared workspace.

Unlike the CEO (stateful orchestrator), the Architect is a stateless
task executor — each solve_task() call is independent.
"""

from typing import List

from .llm_gateway import LLMGateway
from .workspace_manager import WorkspaceManager


_SOLVE_SYSTEM = """\
You are a senior software architect. Given the task below, produce a \
concrete technical implementation plan or code solution.

{plan_context}

## Task
{task_content}

Requirements:
- Be specific: include file names, function signatures, data structures.
- If writing code, use fenced code blocks with the language specified.
- If the task is design-oriented, output a structured technical spec.

IRON RULE: All output MUST be in English. Internal workspace artifacts \
are strictly English-only to minimize token cost and maximize model \
reasoning quality.
"""


class ArchitectAgent:
    """Reads task files from workspace, generates solutions, writes artifacts."""

    def __init__(
        self,
        gateway: LLMGateway,
        workspace: WorkspaceManager,
        workspace_id: str,
    ):
        self._gateway = gateway
        self._workspace = workspace
        self._ws_id = workspace_id

    def list_tasks(self) -> List[str]:
        """Return .md files under tasks/ in the workspace."""
        try:
            all_files = self._workspace.list_files(self._ws_id)
        except Exception:
            return []
        return sorted(
            f for f in all_files
            if f.startswith("tasks/") and f.endswith(".md")
        )

    def _get_plan_context(self) -> str:
        """Load plan.md if it exists, for broader project context."""
        if self._workspace.exists(self._ws_id, "plan.md"):
            plan = self._workspace.read(self._ws_id, "plan.md")
            return f"## Project Plan\n{plan}\n"
        return ""

    def _task_id_from_filename(self, task_filename: str) -> str:
        """Extract 'task_1' from 'tasks/task_1.md'."""
        basename = task_filename.rsplit("/", 1)[-1]
        return basename.removesuffix(".md")

    def solve_task(self, task_filename: str) -> str:
        """Read a task, call LLM for a solution, write the artifact.

        Returns the artifact path (e.g. 'artifacts/task_1_solution.md').
        """
        task_content = self._workspace.read(self._ws_id, task_filename)
        plan_context = self._get_plan_context()

        prompt = _SOLVE_SYSTEM.format(
            plan_context=plan_context,
            task_content=task_content,
        )
        result = self._gateway.send(prompt)
        solution = result["llm_response"]

        task_id = self._task_id_from_filename(task_filename)
        artifact_path = f"artifacts/{task_id}_solution.md"

        artifact_content = (
            f"# Solution: {task_id}\n\n"
            f"## Source Task\n`{task_filename}`\n\n"
            f"## Implementation\n{solution}\n"
        )
        self._workspace.write(self._ws_id, artifact_path, artifact_content)
        return artifact_path

    def solve_all(self) -> List[str]:
        """Solve every task in tasks/ and return all artifact paths."""
        tasks = self.list_tasks()
        return [self.solve_task(t) for t in tasks]
