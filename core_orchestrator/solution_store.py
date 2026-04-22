"""SolutionStore — workspace-scoped structured knowledge persistence.

Solutions are saved as individual YAML files under:
    workspaces/{workspace_id}/_workspace/solutions/{uuid8}.yaml

(The "solutions/" prefix is auto-routed to _workspace/solutions/ by
WorkspaceManager when isolated=True — see _INTERNAL_DIRS.)

Each solution captures one lesson learned:
  - error_fix:             an error occurred and was resolved
  - architectural_decision: a key design choice was made
  - best_practice:         a technique or pattern that worked well

The Compound Engineering flywheel:
    execute → reflect → store → inject → execute better → repeat
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

import yaml

from .workspace_manager import WorkspaceManager

_SOLUTIONS_DIR = "solutions"


class SolutionStore:
    """Read/write lessons-learned for a single workspace.

    Thread-safe for concurrent reads. Writes rely on the filesystem for
    atomicity (one YAML file per solution, unique UUID names).
    """

    def __init__(self, workspace: WorkspaceManager, workspace_id: str) -> None:
        self._ws = workspace
        self._ws_id = workspace_id

    # ── Write ─────────────────────────────────────────────────────────────

    def save(self, solution: Dict[str, Any]) -> str:
        """Persist a solution dict and return its generated ID.

        Required keys: "problem", "solution".
        Optional keys: "type", "context", "tags", "job_id".
        """
        sol = dict(solution)  # shallow copy — don't mutate caller's dict
        sol_id = str(uuid.uuid4()).replace("-", "")[:8]
        sol.setdefault("id", sol_id)
        sol.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
        sol.setdefault("type", "best_practice")
        sol.setdefault("tags", [])

        filename = f"{_SOLUTIONS_DIR}/{sol_id}.yaml"
        content = yaml.dump(
            sol,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        )
        self._ws.write(self._ws_id, filename, content)
        return sol_id

    # ── Read ──────────────────────────────────────────────────────────────

    def load_all(self) -> List[Dict[str, Any]]:
        """Return all solutions, sorted chronologically (oldest first).

        Silently skips any unreadable or malformed files.
        """
        try:
            all_files = self._ws.list_files(self._ws_id)
        except Exception:
            return []

        solutions: List[Dict[str, Any]] = []
        for filepath in all_files:
            if not filepath.startswith(f"{_SOLUTIONS_DIR}/"):
                continue
            if not filepath.endswith(".yaml"):
                continue
            try:
                raw = self._ws.read(self._ws_id, filepath)
                sol = yaml.safe_load(raw)
                if isinstance(sol, dict):
                    solutions.append(sol)
            except Exception:
                continue  # corrupted file — skip gracefully

        return sorted(solutions, key=lambda s: s.get("timestamp", ""))

    def count(self) -> int:
        """Return the number of saved solutions."""
        return len(self.load_all())

    # ── Format ────────────────────────────────────────────────────────────

    def format_as_context(self) -> str:
        """Return an LLM-ready context block of all known lessons.

        Returns an empty string when no solutions exist yet (so callers
        can cleanly skip injecting the section).
        """
        solutions = self.load_all()
        if not solutions:
            return ""

        lines: List[str] = [
            "## MANDATORY: Lessons From Past Projects\n"
            "Study these lessons carefully. You MUST apply them and "
            "NEVER repeat the same mistakes.\n",
        ]

        for i, sol in enumerate(solutions, 1):
            sol_type = sol.get("type", "lesson")
            problem  = sol.get("problem",  "(no problem description)")
            solution = sol.get("solution", "(no solution description)")
            context  = sol.get("context",  "")
            tags     = sol.get("tags",     [])

            lines.append(f"### Lesson {i} [{sol_type}]")
            lines.append(f"**Problem**: {problem}")
            lines.append(f"**Solution**: {solution}")
            if context:
                lines.append(f"**Context**: {context}")
            if tags:
                lines.append(f"**Tags**: {', '.join(str(t) for t in tags)}")
            lines.append("")

        return "\n".join(lines)
