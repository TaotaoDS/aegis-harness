"""Event bus: real-time observability for the multi-agent pipeline.

Provides three output backends:
1. Terminal renderer — ANSI-colored status stream on sys.stderr
2. File audit logger — append-only execution.log for ``tail -f`` monitoring
3. JsonEventBus — structured JSON lines for machine-parseable log aggregation

Usage:
    bus = bus_from_workspace(workspace, workspace_id)
    bus.emit("architect.solving", task_id="task_1")

    # Structured JSON backend:
    bus = bus_from_workspace(workspace, workspace_id, structured=True, job_id="abc123")
    bus.emit("architect.solving", task_id="task_1")
    # → {"ts": "2026-04-26T10:00:00Z", "job_id": "abc123", "event": "architect.solving", "task_id": "task_1"}

Agents receive ``bus=None`` (defaults to NullBus) so all existing
callers and tests work unchanged with zero output.
"""

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, IO, Optional

from .workspace_manager import WorkspaceManager


# ---------------------------------------------------------------------------
# Module-level logger pool — keyed by resolved log_dir to prevent handle leaks
# ---------------------------------------------------------------------------

_LOGGER_POOL: Dict[str, logging.Logger] = {}


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

        # File logger setup — pooled by resolved log_dir to prevent handle leaks.
        # Multiple EventBus instances pointing at the same directory share one
        # Logger (and therefore one FileHandler), so handler count stays at 1.
        self._logger: Optional[logging.Logger] = None
        if enable_file_log:
            log_dir.mkdir(parents=True, exist_ok=True)
            log_path = log_dir / AUDIT_LOG_FILENAME
            pool_key = str(log_dir.resolve())
            if pool_key not in _LOGGER_POOL:
                logger_name = f"aegis_harness.audit.{pool_key}"
                logger = logging.getLogger(logger_name)
                logger.setLevel(logging.INFO)
                logger.propagate = False
                if not logger.handlers:
                    handler = logging.FileHandler(str(log_path), mode="a", encoding="utf-8")
                    handler.setFormatter(
                        logging.Formatter("%(asctime)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
                    )
                    logger.addHandler(handler)
                _LOGGER_POOL[pool_key] = logger
            self._logger = _LOGGER_POOL[pool_key]

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
# JsonEventBus — structured JSON-lines backend for log aggregation
# ---------------------------------------------------------------------------

class JsonEventBus:
    """Writes one JSON line per event to an audit log file.

    Each line is valid JSON containing at minimum:
        {"ts": "<ISO-8601 UTC>", "job_id": "<id>", "event": "<name>", ...kwargs}

    Logger handles are pooled by ``log_dir`` path — instantiating
    ``JsonEventBus`` multiple times for the same directory results in exactly
    one ``FileHandler``, preventing file-descriptor leaks.

    Args:
        log_dir:  Directory that will contain ``execution.log``.
        job_id:   Correlation ID injected into every emitted record.
        enable_file_log: Set False to suppress file output (for testing).
        stream:   Optional IO stream to also write JSON lines to (for testing).
    """

    def __init__(
        self,
        log_dir: Path,
        *,
        job_id: str = "",
        enable_file_log: bool = True,
        stream: Optional[IO] = None,
    ) -> None:
        self._job_id = job_id
        self._stream = stream
        self._logger: Optional[logging.Logger] = None

        if enable_file_log:
            log_dir.mkdir(parents=True, exist_ok=True)
            log_path = log_dir / AUDIT_LOG_FILENAME
            pool_key = f"json:{log_dir.resolve()}"
            if pool_key not in _LOGGER_POOL:
                logger_name = f"aegis_harness.json.{pool_key}"
                logger = logging.getLogger(logger_name)
                logger.setLevel(logging.INFO)
                logger.propagate = False
                if not logger.handlers:
                    handler = logging.FileHandler(str(log_path), mode="a", encoding="utf-8")
                    handler.setFormatter(logging.Formatter("%(message)s"))
                    logger.addHandler(handler)
                _LOGGER_POOL[pool_key] = logger
            self._logger = _LOGGER_POOL[pool_key]

    def emit(self, event: str, **kwargs: Any) -> None:
        record: Dict[str, Any] = {
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "job_id": self._job_id,
            "event": event,
            **kwargs,
        }
        line = json.dumps(record, default=str)
        if self._logger:
            self._logger.info(line)
        if self._stream is not None:
            self._stream.write(line + "\n")
            self._stream.flush()


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
    structured: bool = False,
    job_id: str = "",
) -> "EventBus | JsonEventBus":
    """Create an EventBus that logs to the workspace's _workspace/ directory.

    The audit log is written to:
        <workspace_root>/<workspace_id>/_workspace/execution.log

    If the workspace is not in isolated mode, the log goes to:
        <workspace_root>/<workspace_id>/execution.log

    Args:
        structured: When True, returns a ``JsonEventBus`` instead of the
                    default ANSI terminal bus.  Each log line is a JSON object.
        job_id:     Correlation ID injected into every JSON record (only used
                    when ``structured=True``).
    """
    ws_root = workspace._base / workspace_id
    log_dir = ws_root / "_workspace" if workspace.isolated else ws_root

    if structured:
        return JsonEventBus(
            log_dir=log_dir,
            job_id=job_id,
            enable_file_log=enable_file_log,
            stream=stream,
        )
    return EventBus(
        log_dir=log_dir,
        stream=stream,
        enable_terminal=enable_terminal,
        enable_file_log=enable_file_log,
    )
