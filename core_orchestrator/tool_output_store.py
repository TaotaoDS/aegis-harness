"""Tool Output Store — Layer 1 of the deep context compaction system.

When tool outputs (read_url, search_web, read_file) exceed a size threshold,
the full content is spilled to disk and only a head/tail preview is kept in
the LLM conversation messages. This prevents large tool results from consuming
the model's context window during multi-turn tool-use sessions.

The model can request the full content back via a `recall_tool_output` tool
if the preview is insufficient.
"""

import os
from typing import Optional

_DEFAULT_THRESHOLD = 1200  # chars; ~300 tokens
_DEFAULT_PREVIEW = 600     # chars kept from head and tail


class ToolOutputStore:
    """Spill large tool outputs to disk, keep head/tail preview in messages."""

    def __init__(
        self,
        workspace_path: str,
        workspace_id: str,
        threshold: int = _DEFAULT_THRESHOLD,
        preview_chars: int = _DEFAULT_PREVIEW,
    ):
        self._workspace_path = workspace_path
        self._ws_id = workspace_id
        self._threshold = threshold
        self._preview_chars = preview_chars
        self._store_dir = os.path.join(
            workspace_path, workspace_id, "_workspace", "tool_outputs"
        )

    def _ensure_dir(self) -> None:
        os.makedirs(self._store_dir, exist_ok=True)

    def maybe_evict(self, tool_call_id: str, content: str) -> str:
        """If content exceeds threshold, spill to disk and return a preview stub.

        Returns the original content unchanged if it's small enough.
        """
        if len(content) <= self._threshold:
            return content

        self._ensure_dir()
        safe_id = tool_call_id.replace("/", "_").replace("..", "_")
        filepath = os.path.join(self._store_dir, f"{safe_id}.txt")
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)

        head = content[: self._preview_chars]
        tail = content[-self._preview_chars :]
        total = len(content)
        return (
            f"{head}\n\n"
            f"[… {total} chars total — evicted to disk: {safe_id}.txt "
            f"— use recall_tool_output to retrieve full content …]\n\n"
            f"{tail}"
        )

    def retrieve(self, tool_call_id: str) -> Optional[str]:
        """Read full content back from disk. Returns None if not found."""
        safe_id = tool_call_id.replace("/", "_").replace("..", "_")
        filepath = os.path.join(self._store_dir, f"{safe_id}.txt")
        if not os.path.isfile(filepath):
            return None
        with open(filepath, "r", encoding="utf-8") as f:
            return f.read()

    def clear(self) -> None:
        """Remove all evicted tool outputs (call at end of task)."""
        if not os.path.isdir(self._store_dir):
            return
        for fname in os.listdir(self._store_dir):
            fpath = os.path.join(self._store_dir, fname)
            if os.path.isfile(fpath):
                os.remove(fpath)
