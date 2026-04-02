"""Architect agent: reads tasks, generates solutions, writes code files to workspace.

The Architect has two core capabilities:
1. write_file / read_file — physical file operations on the workspace
2. parse_file_blocks() — multi-strategy extraction of code files from LLM output

Unlike the CEO (stateful orchestrator), the Architect is a stateless
task executor — each solve_task() call is independent.
"""

import os
import re
from typing import Dict, List, Optional, Tuple

from .llm_gateway import LLMGateway
from .workspace_manager import WorkspaceManager


# ---------------------------------------------------------------------------
# Multi-strategy file-block extraction
# ---------------------------------------------------------------------------
#
# LLMs don't always follow the ===FILE: path=== protocol strictly.
# We attempt multiple strategies in priority order:
#
#   Strategy 1 (primary):   ===FILE: path=== ... ===END===
#   Strategy 2 (fallback):  Markdown code blocks with filename annotations
#                           (HTML comments, inline comments, info-string labels)
#   Strategy 3 (fallback):  Heading or bold label immediately before a code block
#
# The first strategy that yields >=1 file wins.
# ---------------------------------------------------------------------------

# --- Strategy 1: ===FILE: path=== protocol ---

_FILE_BLOCK_RE = re.compile(
    r"={2,4}\s*FILE:\s*(.+?)\s*={2,4}\s*\n(.*?)(?=\n={2,4}\s*(?:FILE:|END)\s*={0,4}|$)",
    re.DOTALL,
)

# --- Strategy 2: Markdown fenced code blocks with filename annotations ---
#
# Matches triple-backtick blocks.  Returns (info_string, body).
# Pre-context is looked up separately using match.start() position.
_FENCED_BLOCK_RE = re.compile(
    r"```(\w*(?:[^\S\n][^\n]*)?)\n"    # opening fence with optional info string
    r"(.*?)"                           # body
    r"\n```",                          # closing fence
    re.DOTALL,
)

# Filename patterns inside info strings:  ```html title="index.html"
_INFO_TITLE_RE = re.compile(r'title\s*=\s*["\']([^"\']+)["\']')
# ```html (index.html)  or  ```html index.html
_INFO_PAREN_RE = re.compile(r'\(\s*([^)]+\.\w+)\s*\)')
_INFO_BARE_PATH_RE = re.compile(r'(\S+\.\w{1,10})$')

# Filename patterns as first line of code body:
#   <!-- filename: path -->   or   // filename: path   or   # filename: path
_BODY_COMMENT_RE = re.compile(
    r'^\s*(?:<!-{1,2}\s*filename:\s*(.+?)\s*-{1,2}>|'
    r'//\s*filename:\s*(.+?)$|'
    r'#\s*filename:\s*(.+?)$)',
    re.MULTILINE,
)

# --- Strategy 3: Label immediately before a code block ---
#
# **`index.html`**:   or   `index.html`:   or   ### index.html
_LABEL_RE = re.compile(
    r'(?:\*{1,2}`([^`]+\.\w{1,10})`\*{0,2}\s*:?'  # **`path`**: or *`path`*:
    r'|`([^`]+\.\w{1,10})`\s*:'                     # `path`:
    r'|#{1,6}\s+(\S+\.\w{1,10}))'                   # ### path
)

# File extensions we consider valid code deliverables
_CODE_EXTENSIONS = {
    ".html", ".htm", ".css", ".js", ".ts", ".jsx", ".tsx",
    ".py", ".rb", ".go", ".rs", ".java", ".c", ".cpp", ".h",
    ".json", ".yaml", ".yml", ".toml", ".xml", ".svg",
    ".sh", ".bash", ".sql", ".md", ".txt", ".cfg", ".ini",
    ".vue", ".svelte", ".php", ".swift", ".kt", ".scala",
}


def _looks_like_filepath(s: str) -> bool:
    """Check if a string looks like a file path (has a known extension)."""
    _, ext = os.path.splitext(s.strip().strip("`'\""))
    return ext.lower() in _CODE_EXTENSIONS


def _clean_path(raw: str) -> str:
    """Normalize a raw file path: strip whitespace, quotes, backticks."""
    return raw.strip().strip("`'\"").strip()


def _extract_filename_from_comment(body: str) -> Optional[str]:
    """Extract filename from a comment on the first line of a code block body."""
    m = _BODY_COMMENT_RE.search(body[:200])  # only check first 200 chars
    if m:
        path = m.group(1) or m.group(2) or m.group(3)
        if path:
            return _clean_path(path)
    return None


def _strip_filename_comment(body: str) -> str:
    """Remove the filename comment from the first line if present."""
    lines = body.split("\n", 1)
    if lines and _BODY_COMMENT_RE.match(lines[0]):
        return lines[1] if len(lines) > 1 else ""
    return body


def _strategy_file_blocks(text: str) -> Dict[str, str]:
    """Strategy 1: ===FILE: path=== protocol (primary)."""
    matches = _FILE_BLOCK_RE.findall(text)
    result: Dict[str, str] = {}
    for path, content in matches:
        clean = _clean_path(path)
        if clean:
            result[clean] = content.rstrip()
    return result


def _get_pre_context(text: str, pos: int, lines: int = 2) -> str:
    """Extract up to `lines` lines of text immediately before position `pos`."""
    before = text[:pos]
    parts = before.rsplit("\n", lines + 1)
    # parts[-lines:] gives the last `lines` segments (lines before pos)
    return "\n".join(parts[-(lines):]) if len(parts) > 1 else before


def _strategy_markdown_blocks(text: str) -> Dict[str, str]:
    """Strategy 2+3: Markdown fenced code blocks with filename annotations."""
    result: Dict[str, str] = {}

    for match in _FENCED_BLOCK_RE.finditer(text):
        info_string = match.group(1).strip()
        body = match.group(2)

        if not body.strip():
            continue

        filename: Optional[str] = None

        # 2a: Check info string for title="path"
        m = _INFO_TITLE_RE.search(info_string)
        if m and _looks_like_filepath(m.group(1)):
            filename = _clean_path(m.group(1))

        # 2b: Check info string for (path) or bare path
        if not filename:
            m = _INFO_PAREN_RE.search(info_string)
            if m and _looks_like_filepath(m.group(1)):
                filename = _clean_path(m.group(1))

        if not filename:
            # Split info_string: first word is language, rest might be path
            parts = info_string.split(None, 1)
            if len(parts) == 2 and _looks_like_filepath(parts[1]):
                filename = _clean_path(parts[1])

        # 2c: Check first line of body for filename comment
        if not filename:
            filename = _extract_filename_from_comment(body)
            if filename:
                body = _strip_filename_comment(body)

        # 3: Check pre-context for label
        if not filename:
            pre_context = _get_pre_context(text, match.start())
            if pre_context.strip():
                m = _LABEL_RE.search(pre_context)
                if m:
                    path = m.group(1) or m.group(2) or m.group(3)
                    if path and _looks_like_filepath(path):
                        filename = _clean_path(path)

        if filename and body.strip():
            result[filename] = body.rstrip()

    return result


def parse_file_blocks(text: str) -> Dict[str, str]:
    """Extract {filepath: content} from LLM output using multi-strategy parsing.

    Strategies tried in order (first to yield >=1 file wins):
    1. ===FILE: path=== delimited blocks (primary protocol)
    2. Markdown fenced code blocks with filename annotations
       (info-string titles, HTML/inline comments, heading/label context)

    Returns an empty dict if no files can be extracted.
    """
    if not text or not text.strip():
        return {}

    # Strategy 1: ===FILE: path=== protocol
    result = _strategy_file_blocks(text)
    if result:
        return result

    # Strategy 2+3: Markdown code blocks with filename annotations
    result = _strategy_markdown_blocks(text)
    if result:
        return result

    return {}

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


class ArchitectAgent:
    """Reads task files, generates solutions, writes code to workspace."""

    def __init__(
        self,
        gateway: LLMGateway,
        workspace: WorkspaceManager,
        workspace_id: str,
        knowledge_context: str = "",
        bus=None,
    ):
        from .event_bus import NullBus
        self._gateway = gateway
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

        self._bus.emit("architect.solving", task_id=task_id)

        prompt = _SOLVE_SYSTEM.format(
            plan_context=plan_context,
            task_content=task_content,
            knowledge_context=knowledge_context,
            feedback_context=feedback_context,
        )
        result = self._gateway.send(prompt)
        solution = result["llm_response"]

        # Parse and write file blocks to workspace (multi-strategy)
        file_blocks = parse_file_blocks(solution)
        self._bus.emit("architect.llm_response", task_id=task_id, file_count=len(file_blocks))
        if not file_blocks and solution.strip():
            # Diagnostic: log first 300 chars of raw response for debugging
            self._bus.emit(
                "architect.parse_failed",
                task_id=task_id,
                response_preview=solution[:300],
            )
        written_files: List[str] = []
        for filepath, content in file_blocks.items():
            self.write_file(f"deliverables/{filepath}" if not filepath.startswith("deliverables/") else filepath, content)
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
