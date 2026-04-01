"""Knowledge manager: global knowledge base for accumulated lessons.

Provides two core operations:
1. append_lesson() — write a new bug/fix/guide entry after a successful repair
2. load_knowledge() — read the full knowledge base for injection into agent prompts

The knowledge base is a single Markdown file stored in the workspace at
docs/solutions/global_knowledge_base.md, enabling compound learning across tasks.
"""

import datetime
from typing import Optional

from .workspace_manager import WorkspaceManager

KB_FILENAME = "docs/solutions/global_knowledge_base.md"

_KB_HEADER = """\
# Global Knowledge Base — Accumulated Lessons

> This file is auto-maintained by the system. Each entry records a bug
> root cause and avoidance guide extracted after a successful fix.
> Agents read this before every new task to avoid repeating mistakes.

"""


class KnowledgeManager:
    """Read/write interface for the global knowledge base."""

    def __init__(
        self,
        workspace: WorkspaceManager,
        workspace_id: str,
    ):
        self._workspace = workspace
        self._ws_id = workspace_id

    def _ensure_kb_exists(self) -> None:
        """Create the knowledge base file with header if it doesn't exist."""
        if not self._workspace.exists(self._ws_id, KB_FILENAME):
            self._workspace.write(self._ws_id, KB_FILENAME, _KB_HEADER)

    def load_knowledge(self) -> str:
        """Load the full knowledge base text. Returns '' if not found."""
        if not self._workspace.exists(self._ws_id, KB_FILENAME):
            return ""
        return self._workspace.read(self._ws_id, KB_FILENAME)

    def append_lesson(
        self,
        *,
        task_id: str,
        bug_root_cause: str,
        fix_description: str,
        avoidance_guide: str,
        date: Optional[str] = None,
    ) -> None:
        """Append a new lesson entry to the knowledge base.

        Each entry contains:
        - task_id: which task surfaced the bug
        - bug_root_cause: what went wrong and why
        - fix_description: how it was fixed
        - avoidance_guide: how to prevent it in the future
        """
        self._ensure_kb_exists()

        date_str = date or datetime.date.today().isoformat()
        entry = (
            f"---\n"
            f"### [{date_str}] {task_id}\n"
            f"**Bug Root Cause**: {bug_root_cause}\n"
            f"**Fix**: {fix_description}\n"
            f"**Avoidance Guide**: {avoidance_guide}\n"
            f"---\n\n"
        )

        existing = self._workspace.read(self._ws_id, KB_FILENAME)
        self._workspace.write(self._ws_id, KB_FILENAME, existing + entry)

    def has_lessons(self) -> bool:
        """Check if the knowledge base has any entries."""
        content = self.load_knowledge()
        return "###" in content
