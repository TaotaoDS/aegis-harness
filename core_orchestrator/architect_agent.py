"""Architect agent: reads tasks, generates solutions, writes code files to workspace.

The Architect has two core capabilities:
1. write_file / read_file — physical file operations on the workspace
2. _parse_file_blocks() — extracts ===FILE: path=== blocks from LLM output

Unlike the CEO (stateful orchestrator), the Architect is a stateless
task executor — each solve_task() call is independent.
"""

import re
from typing import Dict, List, Optional

from .llm_gateway import LLMGateway
from .workspace_manager import WorkspaceManager


# ---------------------------------------------------------------------------
# File-block protocol: LLM outputs code wrapped in ===FILE: path=== markers
# ---------------------------------------------------------------------------

_FILE_BLOCK_RE = re.compile(
    r"===FILE:\s*(.+?)\s*===\s*\n(.*?)(?=\n===(?:FILE:|END===)|$)",
    re.DOTALL,
)

_SOLVE_SYSTEM = """\
You are a senior software architect who writes production code.

{knowledge_context}
{plan_context}

## Task
{task_content}

{feedback_context}

## OUTPUT FORMAT — MANDATORY
You MUST output ALL code using the file-block protocol below.
Every file is delimited by ===FILE: <path>=== markers.

Example:
===FILE: src/index.html===
<!DOCTYPE html>
<html>...</html>
===FILE: src/style.css===
body {{ margin: 0; }}
===END===

CRITICAL RULES:
1. You are a CODE PRODUCER, not a specification writer. Output runnable \
   code, not descriptions or architecture documents.
2. Every file block must contain complete, production-ready code — no \
   placeholders like "// TODO" or "implement here".
3. If the task says "Build" or "Implement", you MUST produce actual code \
   files. Specification-only responses will be REJECTED.
4. Cover ALL requirements mentioned in the task — check for plural nouns \
   (e.g., "historical high scores" means a list, not a single value).
5. For canvas/rendering tasks: always handle devicePixelRatio for high-DPI.
6. For UI tasks: include accessibility attributes (ARIA, focus management).

IRON RULE: All output MUST be in English. Internal workspace artifacts \
are strictly English-only to minimize token cost and maximize model \
reasoning quality.
"""


def parse_file_blocks(text: str) -> Dict[str, str]:
    """Extract {filepath: content} from ===FILE: path=== delimited blocks.

    Returns an empty dict if no file blocks are found.
    """
    matches = _FILE_BLOCK_RE.findall(text)
    result: Dict[str, str] = {}
    for path, content in matches:
        clean_path = path.strip().strip("`'\"")
        clean_content = content.rstrip()
        if clean_path:
            result[clean_path] = clean_content
    return result


class ArchitectAgent:
    """Reads task files, generates solutions, writes code to workspace."""

    def __init__(
        self,
        gateway: LLMGateway,
        workspace: WorkspaceManager,
        workspace_id: str,
        knowledge_context: str = "",
    ):
        self._gateway = gateway
        self._workspace = workspace
        self._ws_id = workspace_id
        self._knowledge_context = knowledge_context

    # --- File tools (workspace-scoped) ---

    def write_file(self, path: str, content: str) -> None:
        """Write a file to the workspace under src/."""
        self._workspace.write(self._ws_id, path, content)

    def read_file(self, path: str) -> str:
        """Read a file from the workspace."""
        return self._workspace.read(self._ws_id, path)

    def file_exists(self, path: str) -> bool:
        """Check if a file exists in the workspace."""
        return self._workspace.exists(self._ws_id, path)

    # --- Task operations ---

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

    def _get_knowledge_context(self) -> str:
        """Return knowledge base context for injection into prompt."""
        if self._knowledge_context:
            return f"## Knowledge Base (lessons from past tasks)\n{self._knowledge_context}\n"
        return ""

    def _get_feedback_context(self, task_id: str) -> str:
        """Load previous QA/Evaluator feedback if it exists."""
        feedback_path = f"feedback/{task_id}_feedback.md"
        if self._workspace.exists(self._ws_id, feedback_path):
            fb = self._workspace.read(self._ws_id, feedback_path)
            return (
                f"## Previous Feedback (MUST be addressed)\n{fb}\n"
                f"You MUST fix ALL issues listed above. Do not repeat the same mistakes."
            )
        return ""

    def _task_id_from_filename(self, task_filename: str) -> str:
        """Extract 'task_1' from 'tasks/task_1.md'."""
        basename = task_filename.rsplit("/", 1)[-1]
        return basename.removesuffix(".md")

    def solve_task(self, task_filename: str, *, feedback: str = "") -> str:
        """Read a task, call LLM, parse file blocks, write to workspace.

        Returns the artifact path (e.g. 'artifacts/task_1_solution.md').
        The LLM is instructed to output ===FILE: path=== blocks;
        each block is written as a real file in the workspace.
        """
        task_content = self._workspace.read(self._ws_id, task_filename)
        plan_context = self._get_plan_context()
        knowledge_context = self._get_knowledge_context()
        task_id = self._task_id_from_filename(task_filename)
        feedback_context = feedback or self._get_feedback_context(task_id)

        prompt = _SOLVE_SYSTEM.format(
            plan_context=plan_context,
            task_content=task_content,
            knowledge_context=knowledge_context,
            feedback_context=feedback_context,
        )
        result = self._gateway.send(prompt)
        solution = result["llm_response"]

        # Parse and write file blocks to workspace
        file_blocks = parse_file_blocks(solution)
        written_files: List[str] = []
        for filepath, content in file_blocks.items():
            self.write_file(f"src/{filepath}" if not filepath.startswith("src/") else filepath, content)
            written_files.append(filepath)

        # Always write the artifact summary
        artifact_path = f"artifacts/{task_id}_solution.md"
        files_section = ""
        if written_files:
            files_section = "## Written Files\n" + "\n".join(f"- `{f}`" for f in written_files) + "\n\n"

        artifact_content = (
            f"# Solution: {task_id}\n\n"
            f"## Source Task\n`{task_filename}`\n\n"
            f"{files_section}"
            f"## Implementation\n{solution}\n"
        )
        self._workspace.write(self._ws_id, artifact_path, artifact_content)
        return artifact_path

    def solve_all(self) -> List[str]:
        """Solve every task in tasks/ and return all artifact paths."""
        tasks = self.list_tasks()
        return [self.solve_task(t) for t in tasks]

    def get_written_files(self, task_id: str) -> List[str]:
        """List src/ files written for a given task by reading the artifact."""
        artifact = f"artifacts/{task_id}_solution.md"
        if not self._workspace.exists(self._ws_id, artifact):
            return []
        content = self._workspace.read(self._ws_id, artifact)
        # Extract from "## Written Files" section
        files = []
        in_section = False
        for line in content.split("\n"):
            if line.strip() == "## Written Files":
                in_section = True
                continue
            if in_section:
                if line.startswith("- `") and line.endswith("`"):
                    files.append(line[3:-1])
                elif line.startswith("##"):
                    break
        return files
