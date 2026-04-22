"""Architect agent: reads tasks, generates solutions, writes code files to workspace.

Uses LLM native Tool Use (Function Calling) to write code files. A `write_file`
tool is registered with the LLM, and the system prompt enforces that ALL code
must be submitted via tool calls -- never as inline text.

In Update Mode, the Architect also has access to `read_file` to inspect existing
code before making targeted modifications. The existing codebase is summarized
in the system prompt for context.

Unlike the CEO (stateful orchestrator), the Architect is a stateless
task executor -- each solve_task() call is independent.
"""

import json
from typing import Any, Callable, Dict, List, Optional

from .llm_connector import ToolCall
from .workspace_manager import WorkspaceManager


# ---------------------------------------------------------------------------
# Tool definitions (provider-agnostic format)
# ---------------------------------------------------------------------------

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

READ_FILE_TOOL: Dict[str, Any] = {
    "name": "read_file",
    "description": (
        "Read an existing file from the project deliverables. "
        "Use this to inspect current code before modifying it. "
        "Returns the full file content as a string."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "filepath": {
                "type": "string",
                "description": (
                    "Relative file path to read "
                    "(e.g., 'index.html', 'src/app.js')"
                ),
            },
        },
        "required": ["filepath"],
    },
}

# Type alias for the tool-calling LLM callable.
# Signature: (system, user_prompt, tools, tool_handler=None) -> List[ToolCall]
ToolLLM = Callable[..., List[ToolCall]]


# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

_SOLVE_SYSTEM = """\
You are a senior software architect who writes production code.

{knowledge_context}
{plan_context}

{solutions_context}

## TOOL USE -- MANDATORY

You have access to a `write_file` tool. You MUST use it to submit every code file.
DO NOT output code blocks in your response text. ALL code must be submitted
exclusively through `write_file(filepath, content)` tool calls.

For each file you need to create, call `write_file` with:
- `filepath`: the relative path (e.g., "index.html", "css/style.css")
- `content`: the complete, production-ready file content

{codebase_context}

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

_UPDATE_ADDENDUM = """\
## UPDATE MODE

You are modifying an EXISTING project, not building from scratch.
You have access to `read_file` to inspect current code before modifying it.

WORKFLOW:
1. Use `read_file` to read any files you need to understand or modify.
2. Make targeted, surgical changes -- do NOT rewrite files unnecessarily.
3. Use `write_file` to submit the COMPLETE updated file content.
   (write_file overwrites the entire file, so include ALL lines, not just diffs.)
4. Only modify files that are relevant to the task. Leave others untouched.
"""


class ArchitectAgent:
    """Reads task files, calls LLM with write_file tool, writes code to workspace."""

    def __init__(
        self,
        tool_llm: ToolLLM,
        workspace: WorkspaceManager,
        workspace_id: str,
        knowledge_context: str = "",
        solutions_context: str = "",
        bus=None,
        hitl_manager=None,
    ):
        from .event_bus import NullBus
        self._tool_llm = tool_llm
        self._workspace = workspace
        self._ws_id = workspace_id
        self._knowledge_context = knowledge_context
        self._solutions_context = solutions_context  # workspace lessons (SolutionStore)
        self._bus = bus or NullBus()
        self._hitl_manager = hitl_manager   # Optional HITLManager for sensitive-file gates

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

    # --- Codebase context ---

    def _list_deliverables(self) -> List[str]:
        """Return list of files under deliverables/ in the workspace."""
        try:
            all_files = self._workspace.list_files(self._ws_id)
        except Exception:
            return []
        return sorted(
            f for f in all_files
            if f.startswith("deliverables/")
        )

    def _build_codebase_context(self) -> str:
        """Build a summary of existing deliverables for the system prompt.

        Returns an empty string if no deliverables exist (green-field task).
        When deliverables exist, returns a formatted section listing each file
        with its line count, giving the LLM awareness of the existing codebase.
        """
        deliverables = self._list_deliverables()
        if not deliverables:
            return ""

        lines = [
            "## Existing Codebase",
            "The project already has the following files in deliverables/.",
            "Use `read_file` to inspect any file before modifying it,",
            "then `write_file` to submit your changes.",
            "",
        ]
        for filepath in deliverables:
            try:
                content = self._workspace.read(self._ws_id, filepath)
                line_count = content.count("\n") + 1
                display_path = filepath.removeprefix("deliverables/")
                lines.append(f"- `{display_path}` ({line_count} lines)")
            except Exception:
                display_path = filepath.removeprefix("deliverables/")
                lines.append(f"- `{display_path}` (unreadable)")

        lines.append("")
        return "\n".join(lines)

    # --- Tool handler for read_file ---

    def _tool_handler(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """Handle tool calls during the LLM tool loop.

        - read_file: returns actual file content from deliverables/
        - write_file: returns {"status": "ok"} (file writing is handled post-loop)
        """
        if tool_name == "read_file":
            filepath = arguments.get("filepath", "")
            # Normalize path to include deliverables/ prefix
            read_path = (
                filepath if filepath.startswith("deliverables/")
                else f"deliverables/{filepath}"
            )
            try:
                content = self._workspace.read(self._ws_id, read_path)
                self._bus.emit(
                    "architect.file_read",
                    filepath=filepath,
                )
                return json.dumps({"content": content})
            except Exception as e:
                return json.dumps({"error": f"File not found: {filepath}"})

        # write_file and any other tool: acknowledge
        return json.dumps({"status": "ok"})

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
        """Read a task, call LLM with tools, write files to workspace.

        Returns the artifact path (e.g. 'artifacts/task_1_solution.md').

        When existing deliverables are present, the system prompt includes
        a codebase summary and the read_file tool is made available alongside
        write_file. A tool_handler callback enables read_file to return real
        file content during the multi-turn LLM loop.
        """
        task_content = self._workspace.read(self._ws_id, task_filename)
        plan_context = self._get_plan_context()
        knowledge_context = self._get_knowledge_context()
        task_id = self._task_id_from_filename(task_filename)
        feedback_context = feedback or self._get_feedback_context(task_id)

        self._bus.emit("architect.solving", task_id=task_id)

        # Detect existing codebase for context injection
        codebase_context = self._build_codebase_context()
        has_existing_code = bool(codebase_context)

        # If existing code, add UPDATE MODE addendum to codebase context
        if has_existing_code:
            codebase_context = _UPDATE_ADDENDUM + "\n" + codebase_context

        system_prompt = _SOLVE_SYSTEM.format(
            plan_context=plan_context,
            task_content=task_content,
            knowledge_context=knowledge_context,
            feedback_context=feedback_context,
            codebase_context=codebase_context,
            solutions_context=self._solutions_context or "",
        )

        # Select tools: always write_file; add read_file when codebase exists
        tools = [WRITE_FILE_TOOL]
        tool_handler = None
        if has_existing_code:
            tools.append(READ_FILE_TOOL)
            tool_handler = self._tool_handler

        # Call LLM with tools -- returns List[ToolCall]
        tool_calls = self._tool_llm(
            system_prompt, task_content, tools, tool_handler,
        )

        # Extract write_file calls and write files to workspace
        written_files: List[str] = []
        for tc in tool_calls:
            if tc.name == "write_file":
                filepath = tc.arguments.get("filepath", "")
                content = tc.arguments.get("content", "")
                if filepath and content:
                    # ── HITL gate 2: block before writing sensitive files ──
                    if self._hitl_manager:
                        allowed = self._hitl_manager.check_file_write(filepath, content)
                        if not allowed:
                            self._bus.emit(
                                "architect.file_write_blocked",
                                task_id=task_id,
                                filepath=filepath,
                            )
                            continue

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
            f"## Tool Calls\n{len(tool_calls)} tool call(s) executed\n"
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
