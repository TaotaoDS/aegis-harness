"""Architect agent: reads tasks, generates solutions, writes code files to workspace.

Uses LLM native Tool Use (Function Calling) to write code files. A `write_file`
tool is registered with the LLM, and the system prompt enforces that ALL code
must be submitted via tool calls -- never as inline text.

Unlike the CEO (stateful orchestrator), the Architect is a stateless
task executor -- each solve_task() call is independent.
"""

from typing import Any, Callable, Dict, List, Optional

from .llm_connector import ToolCall
from .workspace_manager import WorkspaceManager


# ---------------------------------------------------------------------------
# write_file tool definition (provider-agnostic format)
# ---------------------------------------------------------------------------
# Connectors convert this to the provider-specific schema:
#   OpenAI:    {"type": "function", "function": {"name":..., "parameters":...}}
#   Anthropic: {"name":..., "input_schema":...}

WRITE_FILE_TOOL: Dict[str, Any] = {
    "name": "write_file",
    "description": (
        "Write a code file to the project workspace. "
        "You MUST call this tool for EVERY file you produce. "
        "Do NOT output code in the response text -- use this tool exclusively."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "filepath": {
                "type": "string",
                "description": (
                    "Relative file path including extension "
                    "(e.g., 'index.html', 'src/app.js', 'style.css')"
                ),
            },
            "content": {
                "type": "string",
                "description": "The complete file content. Must be production-ready code.",
            },
        },
        "required": ["filepath", "content"],
    },
}

# Type alias for the tool-calling LLM callable.
# Signature: (system: str, user_prompt: str, tools: List[Dict]) -> List[ToolCall]
ToolLLM = Callable[..., List[ToolCall]]


# ---------------------------------------------------------------------------
# System prompt -- instructs LLM to use write_file tool exclusively
# ---------------------------------------------------------------------------

_SOLVE_SYSTEM = """\
You are a senior software architect who writes production code.

{knowledge_context}
{plan_context}

## TOOL USE -- MANDATORY

You have access to a `write_file` tool. You MUST use it to submit every code file.
DO NOT output code blocks in your response text. ALL code must be submitted
exclusively through `write_file(filepath, content)` tool calls.

For each file you need to create, call `write_file` with:
- `filepath`: the relative path (e.g., "index.html", "css/style.css")
- `content`: the complete, production-ready file content

{feedback_context}

CRITICAL RULES:
1. You are a CODE PRODUCER. Output runnable code via write_file, not descriptions.
2. Every file must contain complete, production-ready code -- no placeholders.
3. If the task says "Build" or "Implement", you MUST produce actual code files.
4. Cover ALL requirements -- check for plural nouns (e.g., "historical scores" = list).
5. For canvas/rendering tasks: handle devicePixelRatio for high-DPI.
6. For UI tasks: include accessibility attributes (ARIA, focus management).
7. Call write_file for EVERY file. Do NOT put code in your text response.

IRON RULE: All output MUST be in English.
"""


class ArchitectAgent:
    """Reads task files, calls LLM with write_file tool, writes code to workspace."""

    def __init__(
        self,
        tool_llm: ToolLLM,
        workspace: WorkspaceManager,
        workspace_id: str,
        knowledge_context: str = "",
        bus=None,
    ):
        from .event_bus import NullBus
        self._tool_llm = tool_llm
        self._workspace = workspace
        self._ws_id = workspace_id
        self._knowledge_context = knowledge_context
        self._bus = bus or NullBus()

    # --- File tools (workspace-scoped) ---

    def write_file(self, path: str, content: str) -> None:
        """Write a file to the workspace under deliverables/."""
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
        """Read a task, call LLM with write_file tool, write files to workspace.

        Returns the artifact path (e.g. 'artifacts/task_1_solution.md').
        The LLM is given a `write_file` tool and instructed to use it for
        every code file. Tool calls are extracted and written to deliverables/.
        """
        task_content = self._workspace.read(self._ws_id, task_filename)
        plan_context = self._get_plan_context()
        knowledge_context = self._get_knowledge_context()
        task_id = self._task_id_from_filename(task_filename)
        feedback_context = feedback or self._get_feedback_context(task_id)

        self._bus.emit("architect.solving", task_id=task_id)

        system_prompt = _SOLVE_SYSTEM.format(
            plan_context=plan_context,
            task_content=task_content,
            knowledge_context=knowledge_context,
            feedback_context=feedback_context,
        )

        # Call LLM with write_file tool -- returns List[ToolCall]
        tool_calls = self._tool_llm(system_prompt, task_content, [WRITE_FILE_TOOL])

        # Extract write_file calls and write files to workspace
        written_files: List[str] = []
        for tc in tool_calls:
            if tc.name == "write_file":
                filepath = tc.arguments.get("filepath", "")
                content = tc.arguments.get("content", "")
                if filepath and content:
                    full_path = (
                        f"deliverables/{filepath}"
                        if not filepath.startswith("deliverables/")
                        else filepath
                    )
                    self.write_file(full_path, content)
                    written_files.append(filepath)
                    self._bus.emit(
                        "architect.file_written",
                        task_id=task_id,
                        filepath=filepath,
                    )

        self._bus.emit(
            "architect.llm_response",
            task_id=task_id,
            file_count=len(written_files),
            tool_call_count=len(tool_calls),
        )

        if not written_files:
            self._bus.emit(
                "architect.zero_files",
                task_id=task_id,
                tool_call_count=len(tool_calls),
            )

        # Always write the artifact summary
        artifact_path = f"artifacts/{task_id}_solution.md"
        files_section = ""
        if written_files:
            files_section = (
                "## Written Files\n"
                + "\n".join(f"- `{f}`" for f in written_files)
                + "\n\n"
            )

        artifact_content = (
            f"# Solution: {task_id}\n\n"
            f"## Source Task\n`{task_filename}`\n\n"
            f"{files_section}"
            f"## Tool Calls\n{len(tool_calls)} write_file call(s) executed\n"
        )
        self._workspace.write(self._ws_id, artifact_path, artifact_content)
        self._bus.emit("architect.files_written", task_id=task_id, files=written_files)
        return artifact_path

    def solve_all(self) -> List[str]:
        """Solve every task in tasks/ and return all artifact paths."""
        tasks = self.list_tasks()
        return [self.solve_task(t) for t in tasks]

    def get_written_files(self, task_id: str) -> List[str]:
        """List deliverables/ files written for a given task by reading the artifact."""
        artifact = f"artifacts/{task_id}_solution.md"
        if not self._workspace.exists(self._ws_id, artifact):
            return []
        content = self._workspace.read(self._ws_id, artifact)
        # Extract from "## Written Files" section
        files: List[str] = []
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
