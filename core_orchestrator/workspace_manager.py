"""Shared workspace manager for multi-agent state exchange.

Each workspace is an isolated directory under a common base.
Agents read/write persistent files (plan.md, feedback.md, etc.)
to coordinate without sharing in-memory state.

Supports two layout modes:
  - Classic (isolated=False): all files live flat under workspace root.
  - Isolated (isolated=True): internal state goes to _workspace/,
    deliverables go to deliverables/. Agents see the same logical paths;
    physical separation is transparent.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union


class WorkspaceError(Exception):
    """Raised for workspace access violations or missing resources."""


# ---------------------------------------------------------------------------
# Directory isolation constants
# ---------------------------------------------------------------------------

INTERNAL_DIR = "_workspace"
DELIVERABLE_DIR = "deliverables"

# Known internal directories (auto-routed in isolated mode)
_INTERNAL_DIRS = frozenset({
    "tasks", "artifacts", "feedback", "escalations", "approved", "docs",
    "solutions",   # workspace-scoped lessons learned (SolutionStore)
})

# Known internal root-level files
_INTERNAL_FILES = frozenset({
    "plan.md", "requirement.md", "interview_log.md", "checkpoint.json",
})


class WorkspaceManager:
    """File-based shared workspace with path-traversal protection."""

    def __init__(self, base_dir: Union[str, Path], *, isolated: bool = False):
        self._base = Path(base_dir).resolve()
        self._base.mkdir(parents=True, exist_ok=True)
        self._isolated = isolated

    @property
    def isolated(self) -> bool:
        return self._isolated

    # --- Path safety ---

    def _validate_workspace_id(self, workspace_id: str) -> None:
        """Reject IDs containing slashes, dots-sequences, or other traversal tricks."""
        if "/" in workspace_id or "\\" in workspace_id or ".." in workspace_id:
            raise WorkspaceError(f"Invalid workspace id: '{workspace_id}'")

    def _route_path(self, filename: str) -> str:
        """In isolated mode, route internal paths to _workspace/ directory.

        Returns the filename unchanged in classic mode.
        """
        if not self._isolated:
            return filename

        # Already routed — don't double-prefix
        if filename.startswith(f"{INTERNAL_DIR}/") or filename == INTERNAL_DIR:
            return filename
        if filename.startswith(f"{DELIVERABLE_DIR}/") or filename == DELIVERABLE_DIR:
            return filename

        # Check first path segment against known internal dirs
        first_segment = filename.split("/")[0]
        if first_segment in _INTERNAL_DIRS:
            return f"{INTERNAL_DIR}/{filename}"

        # Check root-level internal files
        if filename in _INTERNAL_FILES:
            return f"{INTERNAL_DIR}/{filename}"

        return filename

    def _unroute_path(self, filename: str) -> str:
        """Strip _workspace/ prefix for logical path display."""
        prefix = f"{INTERNAL_DIR}/"
        if filename.startswith(prefix):
            return filename[len(prefix):]
        return filename

    def _safe_path(self, workspace_id: str, filename: Optional[str] = None) -> Path:
        """Resolve and validate a path, ensuring it stays within base_dir."""
        ws_path = (self._base / workspace_id).resolve()
        if not str(ws_path).startswith(str(self._base)):
            raise WorkspaceError(f"Invalid workspace id: '{workspace_id}'")

        if filename is None:
            return ws_path

        if filename.startswith("/") or filename.startswith("\\"):
            raise WorkspaceError(f"Invalid filename: '{filename}'")

        # Apply routing in isolated mode
        routed = self._route_path(filename)

        file_path = (ws_path / routed).resolve()
        if not str(file_path).startswith(str(ws_path)):
            raise WorkspaceError(f"Invalid filename: '{filename}'")

        return file_path

    def _require_workspace(self, workspace_id: str) -> Path:
        """Return workspace path, raising if it doesn't exist."""
        ws_path = self._safe_path(workspace_id)
        if not ws_path.is_dir():
            raise WorkspaceError(f"Workspace not found: '{workspace_id}'")
        return ws_path

    # --- Public API ---

    def create(self, workspace_id: str) -> Path:
        """Create an isolated workspace directory. Idempotent."""
        self._validate_workspace_id(workspace_id)
        ws_path = self._safe_path(workspace_id)
        ws_path.mkdir(parents=True, exist_ok=True)
        if self._isolated:
            (ws_path / INTERNAL_DIR).mkdir(exist_ok=True)
            (ws_path / DELIVERABLE_DIR).mkdir(exist_ok=True)
        return ws_path

    def write(self, workspace_id: str, filename: str, content: str) -> Path:
        """Write a file into a workspace. Creates parent dirs as needed."""
        self._require_workspace(workspace_id)
        file_path = self._safe_path(workspace_id, filename)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        return file_path

    def read(self, workspace_id: str, filename: str) -> str:
        """Read a file from a workspace."""
        self._require_workspace(workspace_id)
        file_path = self._safe_path(workspace_id, filename)
        if not file_path.is_file():
            raise WorkspaceError(f"File not found: '{filename}' in workspace '{workspace_id}'")
        return file_path.read_text(encoding="utf-8")

    def list_files(self, workspace_id: str) -> List[str]:
        """List all files in a workspace (relative paths, recursive).

        In isolated mode, internal paths are returned WITHOUT the
        _workspace/ prefix so agents see the same logical paths.
        """
        ws_path = self._require_workspace(workspace_id)
        raw = sorted(
            str(p.relative_to(ws_path))
            for p in ws_path.rglob("*")
            if p.is_file()
        )
        if self._isolated:
            return sorted(self._unroute_path(f) for f in raw)
        return raw

    def exists(self, workspace_id: str, filename: Optional[str] = None) -> bool:
        """Check if a workspace or a specific file within it exists."""
        try:
            path = self._safe_path(workspace_id, filename)
        except WorkspaceError:
            return False
        if filename is None:
            return path.is_dir()
        return path.is_file()

    def delete(self, workspace_id: str, filename: str) -> None:
        """Delete a single file from a workspace."""
        self._require_workspace(workspace_id)
        file_path = self._safe_path(workspace_id, filename)
        if not file_path.is_file():
            raise WorkspaceError(f"File not found: '{filename}' in workspace '{workspace_id}'")
        file_path.unlink()

    # -----------------------------------------------------------------------
    # Checkpoint helpers (pipeline crash-recovery)
    # -----------------------------------------------------------------------

    def save_checkpoint(
        self,
        workspace_id: str,
        data: Dict[str, Any],
    ) -> None:
        """Persist a pipeline checkpoint to ``checkpoint.json``.

        ``data`` should be a JSON-serialisable dict that captures enough
        state to resume the pipeline after a crash.  Typical keys:

            phase               — e.g. "interviewing", "planning", "executing"
            job_id              — owning job id
            completed_tasks     — list of task IDs already done
            current_task_index  — zero-based index in the task list

        The workspace must already exist; the file is created/overwritten
        atomically (write-to-temp, then rename).
        """
        self._require_workspace(workspace_id)
        file_path = self._safe_path(workspace_id, "checkpoint.json")
        file_path.parent.mkdir(parents=True, exist_ok=True)

        content = json.dumps(data, ensure_ascii=False, indent=2)
        # Atomic write via a sibling temp file
        tmp = file_path.with_suffix(".tmp")
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(file_path)

    def load_checkpoint(self, workspace_id: str) -> Optional[Dict[str, Any]]:
        """Read the last saved checkpoint.

        Returns the parsed dict, or ``None`` when no checkpoint exists or
        the file is corrupt.
        """
        if not self.exists(workspace_id, "checkpoint.json"):
            return None
        try:
            content = self.read(workspace_id, "checkpoint.json")
            return json.loads(content)
        except (json.JSONDecodeError, WorkspaceError):
            return None
