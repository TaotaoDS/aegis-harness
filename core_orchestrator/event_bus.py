"""Event bus: real-time observability for the multi-agent pipeline.

Provides two output backends:
1. Terminal renderer — ANSI-colored status stream on sys.stderr
2. File audit logger — append-only execution.log for ``tail -f`` monitoring

Usage:
    bus = bus_from_workspace(workspace, workspace_id)
    bus.emit("architect.solving", task_id="task_1")

Agents receive ``bus=None`` (defaults to NullBus) so all existing
callers and tests work unchanged with zero output.
"""

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, IO, Optional

from .workspace_manager import WorkspaceManager


# ---------------------------------------------------------------------------
# ANSI color codes
# ---------------------------------------------------------------------------

_COLORS = {
    "red": "\033[91m",
    "green": "\033[92m",
    "yellow": "\033[93m",
    "blue": "\033[94m",
    "magenta": "\033[95m",
    "cyan": "\033[96m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "reset": "\033[0m",
}


def _pick_color(event: str) -> str:
    """Map an event name to an ANSI color string.

    Priority order (first match wins):
    1. Failure/error events → red
    2. Success events → green
    3. Agent-prefix based colors
    """
    # Extract the action part (after the last dot)
    action = event.rsplit(".", 1)[-1] if "." in event else event

    # Failure / error — always red (highest priority)
    _FAIL_ACTIONS = {
        "fail", "error", "escalated", "zero_files", "rejected",
        "budget_exceeded", "file_fail",
    }
    if action in _FAIL_ACTIONS:
        return _COLORS["red"]

    # Success — green
    _SUCCESS_ACTIONS = {
        "pass", "success", "approved", "all_pass",
    }
    # Check action directly, or check if action ends with _complete/_pass
    if action in _SUCCESS_ACTIONS or action.endswith("_complete") or action.endswith("_pass"):
        return _COLORS["green"]

    # Agent-prefix colors
    if event.startswith("architect."):
        return _COLORS["cyan"]
    if event.startswith("evaluator."):
        return _COLORS["yellow"]
    if event.startswith("qa."):
        return _COLORS["blue"]
    if event.startswith("resilience."):
        return _COLORS["magenta"]
    if event.startswith("pipeline."):
        return _COLORS["bold"]

    return ""


def _format_kwargs(kwargs: Dict[str, Any]) -> str:
    """Format keyword arguments into a compact key=value string."""
    if not kwargs:
        return ""
    parts = []
    for k, v in kwargs.items():
        if isinstance(v, str) and len(v) > 200:
            v = v[:200] + "..."
        parts.append(f"{k}={v}")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Audit log file name (written inside _workspace/)
# ---------------------------------------------------------------------------

AUDIT_LOG_FILENAME = "execution.log"


# ---------------------------------------------------------------------------
# EventBus — the real implementation
# ---------------------------------------------------------------------------

class EventBus:
    """Publish-subscribe event bus with terminal + file backends."""

    def __init__(
        self,
        log_dir: Path,
        *,
        stream: Optional[IO] = None,
        enable_terminal: bool = True,
        enable_file_log: bool = True,
    ):
        self._stream = stream or sys.stderr
        self._enable_terminal = enable_terminal
        self._enable_file_log = enable_file_log
        self._use_color = hasattr(self._stream, "isatty") and self._stream.isatty()

        # File logger setup
        self._logger: Optional[logging.Logger] = None
        if enable_file_log:
            log_dir.mkdir(parents=True, exist_ok=True)
            log_path = log_dir / AUDIT_LOG_FILENAME
            logger = logging.getLogger(f"aegis_harness.audit.{id(self)}")
            logger.setLevel(logging.INFO)
            # Avoid duplicate handlers on repeated construction
            if not logger.handlers:
                handler = logging.FileHandler(str(log_path), mode="a", encoding="utf-8")
                handler.setFormatter(
                    logging.Formatter("%(asctime)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
                )
                logger.addHandler(handler)
            self._logger = logger

    def emit(self, event: str, **kwargs: Any) -> None:
        """Emit a named event with structured data to all backends."""
        if self._enable_terminal:
            self._render_terminal(event, kwargs)
        if self._enable_file_log and self._logger:
            self._log_to_file(event, kwargs)

    def _render_terminal(self, event: str, kwargs: Dict[str, Any]) -> None:
        """Write a colorized event line to the terminal stream."""
        ts = datetime.now().strftime("%H:%M:%S")
        tag = event.upper()
        detail = _format_kwargs(kwargs)

        if self._use_color:
            color = _pick_color(event)
            reset = _COLORS["reset"]
            dim = _COLORS["dim"]
            line = f"{dim}[{ts}]{reset} {color}[{tag}]{reset} {detail}"
        else:
            line = f"[{ts}] [{tag}] {detail}"

        self._stream.write(line + "\n")
        self._stream.flush()

    def _log_to_file(self, event: str, kwargs: Dict[str, Any]) -> None:
        """Write a structured log entry to the audit file."""
        tag = event.upper()
        detail = _format_kwargs(kwargs)
        self._logger.info("[%s] %s", tag, detail)


# ---------------------------------------------------------------------------
# NullBus — no-op default for backward compatibility
# ---------------------------------------------------------------------------

class NullBus:
    """No-op event bus — all emit() calls are silently discarded."""

    def emit(self, event: str, **kwargs: Any) -> None:
        pass


# ---------------------------------------------------------------------------
# ListBus — test double that captures events
# ---------------------------------------------------------------------------

class ListBus:
    """Test double that records all emitted events into a list.

    Usage in tests:
        bus = ListBus()
        agent = ArchitectAgent(..., bus=bus)
        agent.solve_task(...)
        assert any(e[0] == "architect.solving" for e in bus.events)
    """

    def __init__(self) -> None:
        self.events: list = []

    def emit(self, event: str, **kwargs: Any) -> None:
        self.events.append((event, kwargs))


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def bus_from_workspace(
    workspace: WorkspaceManager,
    workspace_id: str,
    *,
    stream: Optional[IO] = None,
    enable_terminal: bool = True,
    enable_file_log: bool = True,
) -> EventBus:
    """Create an EventBus that logs to the workspace's _workspace/ directory.

    The audit log is written to:
        <workspace_root>/<workspace_id>/_workspace/execution.log

    If the workspace is not in isolated mode, the log goes to:
        <workspace_root>/<workspace_id>/execution.log
    """
    ws_root = workspace._base / workspace_id
    if workspace.isolated:
        log_dir = ws_root / "_workspace"
    else:
        log_dir = ws_root
    return EventBus(
        log_dir=log_dir,
        stream=stream,
        enable_terminal=enable_terminal,
        enable_file_log=enable_file_log,
    )
