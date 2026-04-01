"""Evaluator: sandbox code execution and automated verification.

Runs code or test scripts in a subprocess sandbox, captures stdout/stderr,
and returns a structured result for the Architect-QA feedback loop.

The Evaluator sits between Architect and QA in the resilience pipeline:
    Architect writes files → Evaluator runs them → pass/fail → QA or retry
"""

import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

from .workspace_manager import WorkspaceManager


_DEFAULT_TIMEOUT = 30  # seconds


class EvalResult:
    """Structured result from a sandbox evaluation."""

    __slots__ = ("success", "stdout", "stderr", "return_code", "timed_out")

    def __init__(
        self,
        *,
        success: bool,
        stdout: str = "",
        stderr: str = "",
        return_code: int = 0,
        timed_out: bool = False,
    ):
        self.success = success
        self.stdout = stdout
        self.stderr = stderr
        self.return_code = return_code
        self.timed_out = timed_out

    def to_dict(self) -> Dict:
        return {
            "success": self.success,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "return_code": self.return_code,
            "timed_out": self.timed_out,
        }

    def error_summary(self, max_chars: int = 2000) -> str:
        """Format a concise error report for injection into Architect feedback."""
        if self.success:
            return ""
        parts = []
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
    """Runs code in a subprocess sandbox and captures results.

    Supports:
    - Python scripts (.py)
    - Node.js scripts (.js, .html via syntax check)
    - Generic shell commands
    - Static validation (file existence, basic syntax)
    """

    def __init__(
        self,
        workspace: WorkspaceManager,
        workspace_id: str,
        timeout: int = _DEFAULT_TIMEOUT,
    ):
        self._workspace = workspace
        self._ws_id = workspace_id
        self._timeout = timeout

    @property
    def workspace_root(self) -> Path:
        """Return the physical path to the workspace root."""
        return self._workspace._base / self._ws_id

    def _run_command(
        self,
        cmd: List[str],
        cwd: Optional[Path] = None,
    ) -> EvalResult:
        """Execute a command in subprocess with timeout and capture."""
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

    def validate_files_exist(self, expected_files: List[str]) -> EvalResult:
        """Check that all expected files were actually written."""
        missing = []
        for f in expected_files:
            path = f if f.startswith("src/") else f"src/{f}"
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
        """Run a Python script in the workspace."""
        full_path = self.workspace_root / script_path
        if not full_path.exists():
            return EvalResult(
                success=False,
                stderr=f"Script not found: {script_path}",
                return_code=1,
            )
        return self._run_command([sys.executable, str(full_path)])

    def syntax_check_python(self, file_path: str) -> EvalResult:
        """Check Python syntax without executing."""
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
        """Basic HTML validation: check for required tags."""
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
        """Smart evaluation: validate files, then run syntax checks by type.

        Returns the first failure, or a success result if all pass.
        """
        # Step 1: all files must exist
        existence = self.validate_files_exist(src_files)
        if not existence.success:
            return existence

        # Step 2: per-file syntax checks
        all_stdout = [existence.stdout]
        for f in src_files:
            src_path = f"src/{f}" if not f.startswith("src/") else f
            full = self.workspace_root / src_path

            if not full.exists():
                continue

            if f.endswith(".py"):
                result = self.syntax_check_python(src_path)
            elif f.endswith(".js"):
                result = self.syntax_check_js(src_path)
            elif f.endswith(".html"):
                result = self.validate_html(src_path)
            else:
                # CSS, images, etc. — existence is sufficient
                result = EvalResult(success=True, stdout=f"File exists: {f}")

            if not result.success:
                return result
            all_stdout.append(result.stdout)

        return EvalResult(
            success=True,
            stdout="\n".join(s for s in all_stdout if s),
        )
