"""Evaluator: content pre-screening + sandboxed code execution.

Security model (two layers):
  Layer 1 — ContentPreScreener: static regex analysis before any execution.
             Blocks calls to subprocess, network libs, eval/exec, and
             sensitive filesystem paths.  Fast, zero-overhead.

  Layer 2 — SandboxFactory: routes actual code execution through
             DockerSandbox (production) or ResourceLimitSandbox (fallback).
             Enforces CPU-time and file-write limits in the child process.

Pipeline position:
    Architect writes files → Evaluator screens + runs → pass/fail → QA or retry
"""

import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

from .sandbox import ContentPreScreener, SandboxFactory, SandboxSpec
from .workspace_manager import WorkspaceManager


_DEFAULT_TIMEOUT = 30  # seconds


class EvalResult:
    """Structured result from a sandbox evaluation."""

    __slots__ = (
        "success", "stdout", "stderr", "return_code",
        "timed_out", "blocked", "blocked_reason", "sandbox_mode",
    )

    def __init__(
        self,
        *,
        success: bool,
        stdout: str = "",
        stderr: str = "",
        return_code: int = 0,
        timed_out: bool = False,
        blocked: bool = False,
        blocked_reason: str = "",
        sandbox_mode: str = "",
    ):
        self.success = success
        self.stdout = stdout
        self.stderr = stderr
        self.return_code = return_code
        self.timed_out = timed_out
        self.blocked = blocked
        self.blocked_reason = blocked_reason
        self.sandbox_mode = sandbox_mode

    def to_dict(self) -> Dict:
        return {
            "success": self.success,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "return_code": self.return_code,
            "timed_out": self.timed_out,
            "blocked": self.blocked,
            "blocked_reason": self.blocked_reason,
            "sandbox_mode": self.sandbox_mode,
        }

    def error_summary(self, max_chars: int = 2000) -> str:
        """Format a concise error report for injection into Architect feedback."""
        if self.success:
            return ""
        parts = []
        if self.blocked:
            parts.append(f"BLOCKED (pre-screen): {self.blocked_reason}")
        if self.timed_out:
            parts.append(f"TIMEOUT: Process exceeded {_DEFAULT_TIMEOUT}s limit")
        if self.stderr:
            parts.append(f"STDERR:\n{self.stderr[:max_chars]}")
        if self.return_code != 0:
            parts.append(f"EXIT CODE: {self.return_code}")
        if self.stdout:
            parts.append(f"STDOUT:\n{self.stdout[:max_chars]}")
        return "\n\n".join(parts) if parts else "Unknown error"


class Evaluator:
    """Screens and runs code in an isolated sandbox, captures results.

    Supports:
    - Python scripts (.py) — pre-screened + sandboxed execution
    - Node.js scripts (.js) — syntax check via ``node --check``
    - HTML files — structural tag validation
    - Generic files (CSS, images, etc.) — existence check only

    Pre-screening is applied to Python files before execution.
    Syntax-only checks (py_compile, node --check) bypass the full sandbox
    since they do not execute arbitrary logic.
    """

    def __init__(
        self,
        workspace: WorkspaceManager,
        workspace_id: str,
        timeout: int = _DEFAULT_TIMEOUT,
        bus=None,
        sandbox_spec: Optional[SandboxSpec] = None,
    ):
        from .event_bus import NullBus
        self._workspace = workspace
        self._ws_id = workspace_id
        self._timeout = timeout
        self._bus = bus or NullBus()
        self._sandbox_spec = sandbox_spec  # None → use SandboxSpec defaults

    @property
    def workspace_root(self) -> Path:
        """Return the physical path to the workspace root."""
        return self._workspace._base / self._ws_id

    # ------------------------------------------------------------------
    # Internal: low-level command runners
    # ------------------------------------------------------------------

    def _run_command(
        self,
        cmd: List[str],
        cwd: Optional[Path] = None,
    ) -> EvalResult:
        """Execute a command directly (for safe static-analysis tools only).

        Use this only for commands that do NOT execute arbitrary generated
        code (e.g. ``py_compile``, ``node --check``).  For actual script
        execution, use ``_run_sandboxed``.
        """
        work_dir = cwd or self.workspace_root
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(work_dir),
                capture_output=True,
                text=True,
                timeout=self._timeout,
            )
            return EvalResult(
                success=(proc.returncode == 0),
                stdout=proc.stdout,
                stderr=proc.stderr,
                return_code=proc.returncode,
            )
        except subprocess.TimeoutExpired:
            return EvalResult(
                success=False,
                stderr=f"Process timed out after {self._timeout}s",
                return_code=-1,
                timed_out=True,
            )
        except FileNotFoundError as e:
            return EvalResult(
                success=False,
                stderr=f"Command not found: {e}",
                return_code=-1,
            )

    def _run_sandboxed(
        self,
        cmd: List[str],
        cwd: Optional[Path] = None,
    ) -> EvalResult:
        """Execute a command through the active sandbox (Docker or OS limits).

        All execution of generated Python code must go through this method.
        """
        work_dir = cwd or self.workspace_root
        sandbox = SandboxFactory.create(spec=self._sandbox_spec)
        result = sandbox.run(cmd, work_dir, self._timeout)
        return EvalResult(
            success=result.success,
            stdout=result.stdout,
            stderr=result.stderr,
            return_code=result.return_code,
            timed_out=result.timed_out,
            sandbox_mode=result.sandbox_mode,
        )

    # ------------------------------------------------------------------
    # Public: file-level checks
    # ------------------------------------------------------------------

    def validate_files_exist(self, expected_files: List[str]) -> EvalResult:
        """Check that all expected deliverable files were actually written."""
        missing = []
        for f in expected_files:
            path = f if f.startswith("deliverables/") else f"deliverables/{f}"
            if not self._workspace.exists(self._ws_id, path):
                missing.append(path)

        if missing:
            return EvalResult(
                success=False,
                stderr=f"Missing files: {', '.join(missing)}",
                return_code=1,
            )
        return EvalResult(success=True, stdout=f"All {len(expected_files)} files present")

    def run_python(self, script_path: str) -> EvalResult:
        """Screen and execute a Python script inside the sandbox.

        Layer 1 — ContentPreScreener rejects dangerous patterns before
        any subprocess is spawned.
        Layer 2 — SandboxFactory enforces resource limits at runtime.
        """
        full_path = self.workspace_root / script_path
        if not full_path.exists():
            return EvalResult(
                success=False,
                stderr=f"Script not found: {script_path}",
                return_code=1,
            )

        # --- Layer 1: static pre-screen ---
        screen = ContentPreScreener.check_file(full_path)
        if not screen.allowed:
            return EvalResult(
                success=False,
                stderr=screen.reason,
                return_code=1,
                blocked=True,
                blocked_reason=screen.reason,
            )

        # --- Layer 2: sandboxed execution ---
        return self._run_sandboxed([sys.executable, str(full_path)])

    def syntax_check_python(self, file_path: str) -> EvalResult:
        """Check Python syntax without executing (py_compile — safe, no sandbox needed)."""
        full_path = self.workspace_root / file_path
        if not full_path.exists():
            return EvalResult(
                success=False,
                stderr=f"File not found: {file_path}",
                return_code=1,
            )
        return self._run_command(
            [sys.executable, "-m", "py_compile", str(full_path)]
        )

    def syntax_check_js(self, file_path: str) -> EvalResult:
        """Check JavaScript syntax via Node.js --check (if available)."""
        full_path = self.workspace_root / file_path
        if not full_path.exists():
            return EvalResult(
                success=False,
                stderr=f"File not found: {file_path}",
                return_code=1,
            )
        return self._run_command(["node", "--check", str(full_path)])

    def validate_html(self, file_path: str) -> EvalResult:
        """Basic HTML validation: check for required structural tags."""
        full_path = self.workspace_root / file_path
        if not full_path.exists():
            return EvalResult(
                success=False,
                stderr=f"File not found: {file_path}",
                return_code=1,
            )
        content = full_path.read_text(encoding="utf-8")
        errors = []
        for tag in ["<!DOCTYPE", "<html", "<head", "<body"]:
            if tag.lower() not in content.lower():
                errors.append(f"Missing required tag: {tag}")
        if errors:
            return EvalResult(
                success=False,
                stderr="\n".join(errors),
                return_code=1,
            )
        return EvalResult(success=True, stdout="HTML structure valid")

    def run_eval(self, src_files: List[str]) -> EvalResult:
        """Smart evaluation: validate files, pre-screen Python, run syntax checks.

        Returns the first failure, or a success result if all pass.

        Python files are pre-screened for dangerous patterns before syntax
        checking so that malicious code is rejected early with a clear message.
        """
        self._bus.emit("evaluator.start", file_count=len(src_files))

        # Step 1: all files must exist
        existence = self.validate_files_exist(src_files)
        if not existence.success:
            return existence

        # Step 2: per-file checks
        all_stdout = [existence.stdout]
        for f in src_files:
            src_path = f"deliverables/{f}" if not f.startswith("deliverables/") else f
            full = self.workspace_root / src_path

            if not full.exists():
                continue

            if f.endswith(".py"):
                # Pre-screen before syntax check — reject dangerous code early
                screen = ContentPreScreener.check_file(full)
                if not screen.allowed:
                    result = EvalResult(
                        success=False,
                        stderr=screen.reason,
                        return_code=1,
                        blocked=True,
                        blocked_reason=screen.reason,
                    )
                    self._bus.emit(
                        "evaluator.file_fail",
                        file=f,
                        error=screen.reason[:150],
                    )
                    return result
                result = self.syntax_check_python(src_path)

            elif f.endswith(".js"):
                result = self.syntax_check_js(src_path)

            elif f.endswith(".html"):
                result = self.validate_html(src_path)

            else:
                # CSS, images, etc. — existence is sufficient
                result = EvalResult(success=True, stdout=f"File exists: {f}")

            if not result.success:
                self._bus.emit("evaluator.file_fail", file=f, error=result.stderr[:150])
                return result
            all_stdout.append(result.stdout)

        self._bus.emit("evaluator.all_pass", file_count=len(src_files))
        return EvalResult(
            success=True,
            stdout="\n".join(s for s in all_stdout if s),
        )
