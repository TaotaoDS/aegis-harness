"""Human-in-the-Loop (HITL) approval gate.

Architecture:
- Pipeline runs in a ThreadPoolExecutor background thread.
- check_file_write() / check_update_mode() BLOCK the pipeline thread
  using threading.Event until a human approves or rejects.
- resolve() is called from the async FastAPI handler and sets the event,
  unblocking the pipeline thread.

Two trigger conditions:
1. Update Mode start — before any existing code is modified.
2. Sensitive file write — before writing auth/config/key/secret files.
"""

import re
import threading
from typing import Any, Callable, Dict, List, Optional


# ---------------------------------------------------------------------------
# Sensitive file detection
# ---------------------------------------------------------------------------

_SENSITIVE_PATTERNS: List[str] = [
    r"auth[^/]*\.(py|js|ts|jsx|tsx)$",
    r"config[^/]*\.(py|js|ts|yaml|yml|json|toml)$",
    r"settings[^/]*\.(py|js|ts|jsx|tsx)$",
    r".*\.env([^/]*)$",
    r".*secret[^/]*\.(py|js|ts|jsx|tsx)$",
    r".*key[^/]*\.(py|js|ts)$",
    r"middleware[^/]*\.(py|js|ts|jsx|tsx)$",
    r"security[^/]*\.(py|js|ts|jsx|tsx)$",
    r"permission[^/]*\.(py|js|ts)$",
    r"password[^/]*\.(py|js|ts)$",
]


def is_sensitive_file(filepath: str) -> bool:
    """Return True if the filepath matches any sensitive-file pattern."""
    name = filepath.lower().replace("\\", "/").lstrip("/")
    if name.startswith("deliverables/"):
        name = name[len("deliverables/"):]
    return any(re.search(pat, name) for pat in _SENSITIVE_PATTERNS)


# ---------------------------------------------------------------------------
# One-shot gate
# ---------------------------------------------------------------------------

class HITLGate:
    """A one-shot threading.Event-based approval gate."""

    TIMEOUT_SECONDS = 600.0   # 10 minutes

    def __init__(self):
        self._event = threading.Event()
        self._result: Optional[Dict[str, Any]] = None

    def wait_for_approval(self) -> Dict[str, Any]:
        """Block the calling thread. Returns result dict."""
        if not self._event.wait(timeout=self.TIMEOUT_SECONDS):
            return {"approved": False, "note": "Timed out after 10 minutes"}
        return self._result or {"approved": False, "note": "No result set"}

    def resolve(self, approved: bool, note: str = "") -> None:
        """Unblock the waiting thread (called from async context)."""
        self._result = {"approved": approved, "note": note}
        self._event.set()


# ---------------------------------------------------------------------------
# Manager (one per job)
# ---------------------------------------------------------------------------

class HITLManager:
    """Manages all approval gates for one job.

    Passed to ArchitectAgent and called from job_runner at decision points.
    """

    def __init__(
        self,
        job_id: str,
        bus,
        on_status_change: Optional[Callable[[str, str], None]] = None,
    ):
        self.job_id = job_id
        self._bus = bus
        self._on_status_change = on_status_change   # fn(job_id, status)
        self._current_gate: Optional[HITLGate] = None
        self._pending: Optional[Dict[str, Any]] = None

    # ------------------------------------------------------------------
    # Decision points (called from pipeline thread — BLOCKING)
    # ------------------------------------------------------------------

    def check_file_write(self, filepath: str, content: str) -> bool:
        """Block and request approval before writing a sensitive file.
        Returns True if approved, False if rejected.
        """
        if not is_sensitive_file(filepath):
            return True
        return self._request_approval(
            reason="sensitive_file",
            action=f"写入敏感文件：{filepath}",
            risk="high",
            details={
                "filepath": filepath,
                "content_preview": content[:300] + ("…" if len(content) > 300 else ""),
                "reason": "此文件含认证、配置或密钥相关逻辑，写入前需要您的确认。",
            },
        )

    def check_update_mode(self, requirement: str, files_to_modify: List[str]) -> bool:
        """Block and request approval before Update Mode modifies existing code.
        Returns True if approved, False if rejected.
        """
        return self._request_approval(
            reason="update_mode",
            action="Update Mode：即将修改现有代码",
            risk="medium",
            details={
                "requirement": requirement,
                "files_to_modify": files_to_modify,
                "reason": "此操作将修改现有项目文件，请确认变更内容后再继续。",
            },
        )

    # ------------------------------------------------------------------
    # Resolution (called from async FastAPI handler)
    # ------------------------------------------------------------------

    def resolve(self, approved: bool, note: str = "") -> bool:
        """Resolve the current pending gate.
        Returns False if no gate is currently waiting.
        """
        if self._current_gate is None:
            return False
        self._current_gate.resolve(approved=approved, note=note)
        return True

    @property
    def pending_approval(self) -> Optional[Dict[str, Any]]:
        return self._pending

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _request_approval(
        self, reason: str, action: str, risk: str, details: Dict[str, Any]
    ) -> bool:
        gate = HITLGate()
        self._current_gate = gate
        self._pending = {"reason": reason, "action": action, "risk": risk, "details": details}

        if self._on_status_change:
            self._on_status_change(self.job_id, "waiting_approval")

        self._bus.emit(
            "hitl.approval_required",
            reason=reason,
            action=action,
            risk=risk,
            details=details,
        )

        result = gate.wait_for_approval()

        self._current_gate = None
        self._pending = None

        if self._on_status_change:
            self._on_status_change(self.job_id, "running")

        if result["approved"]:
            self._bus.emit("hitl.approved", action=action, note=result.get("note", ""))
            return True
        else:
            self._bus.emit("hitl.rejected", action=action, note=result.get("note", ""))
            return False
