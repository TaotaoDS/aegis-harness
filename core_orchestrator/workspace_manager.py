"""Shared workspace manager for multi-agent state exchange.

Each workspace is an isolated directory under a common base.
Agents read/write persistent files (plan.md, feedback.md, etc.)
to coordinate without sharing in-memory state.
"""

from pathlib import Path
from typing import List, Optional, Union


class WorkspaceError(Exception):
    """Raised for workspace access violations or missing resources."""


class WorkspaceManager:
    """File-based shared workspace with path-traversal protection."""

    def __init__(self, base_dir: Union[str, Path]):
        self._base = Path(base_dir).resolve()
        self._base.mkdir(parents=True, exist_ok=True)

    # --- Path safety ---

    def _validate_workspace_id(self, workspace_id: str) -> None:
        """Reject IDs containing slashes, dots-sequences, or other traversal tricks."""
        if "/" in workspace_id or "\\" in workspace_id or ".." in workspace_id:
            raise WorkspaceError(f"Invalid workspace id: '{workspace_id}'")

    def _safe_path(self, workspace_id: str, filename: Optional[str] = None) -> Path:
        """Resolve and validate a path, ensuring it stays within base_dir."""
        ws_path = (self._base / workspace_id).resolve()
        if not str(ws_path).startswith(str(self._base)):
            raise WorkspaceError(f"Invalid workspace id: '{workspace_id}'")

        if filename is None:
            return ws_path

        if filename.startswith("/") or filename.startswith("\\"):
            raise WorkspaceError(f"Invalid filename: '{filename}'")

        file_path = (ws_path / filename).resolve()
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
        """List all files in a workspace (relative paths, recursive)."""
        ws_path = self._require_workspace(workspace_id)
        return sorted(
            str(p.relative_to(ws_path))
            for p in ws_path.rglob("*")
            if p.is_file()
        )

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
