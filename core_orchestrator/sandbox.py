"""Sandbox execution environment for generated code.

Provides two isolation tiers:
  ContentPreScreener  — static analysis deny-list (runs before any execution)
  DockerSandbox       — container-level isolation (preferred in production)
  ResourceLimitSandbox— OS-level resource limits (fallback / dev / CI)

Use SandboxFactory.create() to obtain the best available sandbox.
Runtime detection order: HARNESS_SANDBOX_MODE env var → Docker availability → OS limits.
"""

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import List, Optional, Tuple


# ---------------------------------------------------------------------------
# Content Pre-Screener
# ---------------------------------------------------------------------------

# Each entry: (compiled_regex, human-readable description)
# First match wins and blocks execution.
_RAW_DENY_PATTERNS: List[Tuple[str, str]] = [
    # Shell / process execution
    (r"\bsubprocess\b",                                       "subprocess module usage"),
    (r"os\.system\s*\(",                                      "os.system() shell execution"),
    (r"os\.popen\s*\(",                                       "os.popen() shell pipe"),
    (r"os\.exec[vle]*p?\s*\(",                                "os.exec*() process replacement"),
    (r"os\.spawn[vle]*p?\s*\(",                               "os.spawn*() process creation"),
    # Network access
    (r"\burllib\.request\.(urlopen|urlretrieve|Request)\b",   "urllib.request network call"),
    (r"\bimport\s+urllib\.request\b",                         "urllib.request import"),
    (r"\bfrom\s+urllib\.request\b",                           "urllib.request import"),
    (r"\brequests\.(get|post|put|delete|patch|head|options|request)\s*\(", "requests HTTP call"),
    (r"\bimport\s+requests\b",                                "requests module import"),
    (r"\bimport\s+httpx\b",                                   "httpx module import"),
    (r"\bfrom\s+httpx\b",                                     "httpx module import"),
    (r"\bsocket\.socket\s*\(",                                "raw socket creation"),
    (r"\bimport\s+socket\b",                                  "socket module import"),
    (r"\bfrom\s+socket\b",                                    "socket module import"),
    # Dynamic code execution
    (r"\beval\s*\(",                                          "eval() code execution"),
    (r"\bexec\s*\(",                                          "exec() code execution"),
    (r"\b__import__\s*\(",                                    "__import__() dynamic import"),
    (r"\bimportlib\b",                                        "importlib usage"),
    (r"\bcompile\s*\(.*,\s*['\"].*['\"],\s*['\"]exec['\"]",  "compile(..., 'exec') code execution"),
    # Sensitive filesystem access
    (r'open\s*\(\s*["\'][/\\](?:etc|proc|sys|app|root|home|var|usr)[/\\]',
     "open() with sensitive system path"),
    (r'open\s*\(\s*["\']\.\./',                               "open() with path traversal"),
    (r'open\s*\(\s*["\']\.\.\\',                              "open() with path traversal (Windows)"),
]

_DENY_PATTERNS: List[Tuple[re.Pattern, str]] = [
    (re.compile(pat, re.IGNORECASE), desc)
    for pat, desc in _RAW_DENY_PATTERNS
]


class ScreenResult:
    """Result of a content pre-screening check."""

    __slots__ = ("allowed", "reason")

    def __init__(self, allowed: bool, reason: str = "") -> None:
        self.allowed = allowed
        self.reason = reason

    def __bool__(self) -> bool:
        return self.allowed

    def __repr__(self) -> str:  # pragma: no cover
        return f"ScreenResult(allowed={self.allowed}, reason={self.reason!r})"


class ContentPreScreener:
    """Static analysis pre-filter: blocks code containing known dangerous patterns.

    Designed to be fast (pure regex, no AST parsing) and conservative —
    it produces false negatives (misses some dangerous code) rather than
    false positives (blocking legitimate code).  The sandbox provides the
    second layer of defence.
    """

    @staticmethod
    def check(content: str) -> ScreenResult:
        """Check a string of source code. Returns ScreenResult."""
        for pattern, desc in _DENY_PATTERNS:
            if pattern.search(content):
                return ScreenResult(
                    allowed=False,
                    reason=f"Dangerous pattern blocked: {desc}",
                )
        return ScreenResult(allowed=True)

    @staticmethod
    def check_file(file_path: Path) -> ScreenResult:
        """Read *file_path* and screen its contents."""
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return ScreenResult(
                allowed=False,
                reason=f"Cannot read file for pre-screening: {exc}",
            )
        return ContentPreScreener.check(content)


# ---------------------------------------------------------------------------
# Sandbox data types
# ---------------------------------------------------------------------------

class NetworkPolicy(str, Enum):
    NONE = "none"
    LOOPBACK = "loopback"
    ALL = "all"


@dataclass
class SandboxSpec:
    """Configuration knobs for sandbox execution."""
    memory_mb: int = 512          # Docker memory cap (MiB)
    cpu_time_s: int = 25          # OS RLIMIT_CPU seconds (ResourceLimitSandbox)
    timeout_s: int = 30           # Wall-clock timeout passed to Evaluator
    network: NetworkPolicy = NetworkPolicy.NONE


@dataclass
class SandboxRunResult:
    """Structured result from sandbox execution."""
    success: bool
    stdout: str = ""
    stderr: str = ""
    return_code: int = 0
    timed_out: bool = False
    blocked: bool = False          # True when pre-screener rejected the file
    blocked_reason: str = ""
    sandbox_mode: str = "unknown"  # "docker" | "resource_limit" | "direct"

    def to_dict(self) -> dict:
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


# ---------------------------------------------------------------------------
# Sandbox base
# ---------------------------------------------------------------------------

class _SandboxBase:
    """Abstract base for sandbox implementations."""

    sandbox_mode: str = "unknown"

    def run(
        self,
        cmd: List[str],
        cwd: Path,
        timeout: int,
    ) -> SandboxRunResult:
        raise NotImplementedError  # pragma: no cover


# ---------------------------------------------------------------------------
# ResourceLimitSandbox
# ---------------------------------------------------------------------------

def _apply_resource_limits(cpu_time_s: int) -> None:
    """preexec_fn: tighten resource limits in the child process.

    We deliberately skip RLIMIT_AS (virtual memory) because it is
    unreliable on macOS with large-footprint runtimes (Anaconda, etc.)
    and causes false-positive OOM kills.  CPU time and file-write size
    are safe cross-platform limits.
    """
    try:
        import resource  # not available on Windows
        # CPU time: hard limit = soft + 1 so SIGXCPU fires cleanly
        try:
            resource.setrlimit(
                resource.RLIMIT_CPU,
                (cpu_time_s, cpu_time_s + 1),
            )
        except (AttributeError, ValueError, resource.error):
            pass
        # Max file write: 50 MiB — prevents runaway disk writes
        try:
            fifty_mb = 50 * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_FSIZE, (fifty_mb, fifty_mb))
        except (AttributeError, ValueError, resource.error):
            pass
    except ImportError:
        pass  # Windows — degrade gracefully


class ResourceLimitSandbox(_SandboxBase):
    """OS-level sandboxing via POSIX resource limits (cross-platform fallback).

    Provides CPU-time and file-write caps.  Does NOT restrict network or
    filesystem access — rely on ContentPreScreener for those threats.
    """

    sandbox_mode = "resource_limit"

    def __init__(self, spec: Optional[SandboxSpec] = None) -> None:
        self._spec = spec or SandboxSpec()

    def run(
        self,
        cmd: List[str],
        cwd: Path,
        timeout: int,
    ) -> SandboxRunResult:
        import functools

        preexec_fn = None
        if sys.platform != "win32":
            preexec_fn = functools.partial(
                _apply_resource_limits,
                self._spec.cpu_time_s,
            )

        try:
            proc = subprocess.run(
                cmd,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=timeout,
                preexec_fn=preexec_fn,
            )
            return SandboxRunResult(
                success=(proc.returncode == 0),
                stdout=proc.stdout,
                stderr=proc.stderr,
                return_code=proc.returncode,
                sandbox_mode=self.sandbox_mode,
            )
        except subprocess.TimeoutExpired:
            return SandboxRunResult(
                success=False,
                stderr=f"Process timed out after {timeout}s",
                return_code=-1,
                timed_out=True,
                sandbox_mode=self.sandbox_mode,
            )
        except FileNotFoundError as exc:
            return SandboxRunResult(
                success=False,
                stderr=f"Command not found: {exc}",
                return_code=-1,
                sandbox_mode=self.sandbox_mode,
            )


# ---------------------------------------------------------------------------
# DockerSandbox
# ---------------------------------------------------------------------------

class DockerSandbox(_SandboxBase):
    """Container-level isolation via Docker.

    Each execution runs inside a fresh ``python:3.12-slim`` container with:
      --network none      no outbound network
      --memory <N>m       memory cap
      --cpus 0.5          CPU throttle
      --read-only         immutable root filesystem
      --tmpfs /tmp        writable scratch only
      workspace mounted at /workspace (read-write)

    Paths from the host workspace are automatically remapped to /workspace
    inside the container.  The host Python executable is replaced with the
    container's ``python3``.
    """

    sandbox_mode = "docker"
    _DEFAULT_IMAGE = "python:3.12-slim"

    # Module-level cache: None = unchecked, True/False = result
    _docker_available: Optional[bool] = None

    def __init__(
        self,
        spec: Optional[SandboxSpec] = None,
        image: Optional[str] = None,
    ) -> None:
        self._spec = spec or SandboxSpec()
        self._image = image or self._DEFAULT_IMAGE

    # ------------------------------------------------------------------
    # Path / command remapping
    # ------------------------------------------------------------------

    def _remap_cmd(self, cmd: List[str], workspace_host: Path) -> List[str]:
        """Translate host paths and Python executable for the container."""
        ws_str = str(workspace_host)
        result = []
        for arg in cmd:
            s = str(arg)
            # Replace host Python with container Python
            if s == sys.executable:
                s = "python3"
            # Replace workspace-absolute paths with /workspace/...
            elif ws_str and s.startswith(ws_str):
                s = "/workspace" + s[len(ws_str):]
            result.append(s)
        return result

    # ------------------------------------------------------------------
    # Docker availability check
    # ------------------------------------------------------------------

    @classmethod
    def is_available(cls) -> bool:
        """Return True if Docker CLI is reachable and the daemon is running.

        Result is cached for the lifetime of the process.
        """
        if cls._docker_available is None:
            try:
                r = subprocess.run(
                    ["docker", "info"],
                    capture_output=True,
                    timeout=5,
                )
                cls._docker_available = r.returncode == 0
            except (FileNotFoundError, subprocess.TimeoutExpired):
                cls._docker_available = False
        return cls._docker_available

    @classmethod
    def _reset_cache(cls) -> None:
        """Reset availability cache (test helper)."""
        cls._docker_available = None

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def run(
        self,
        cmd: List[str],
        cwd: Path,
        timeout: int,
    ) -> SandboxRunResult:
        network_mode = "none" if self._spec.network == NetworkPolicy.NONE else "bridge"
        remapped = self._remap_cmd(cmd, cwd)

        docker_cmd = [
            "docker", "run", "--rm",
            "--network", network_mode,
            f"--memory={self._spec.memory_mb}m",
            "--cpus=0.5",
            "--read-only",
            "--tmpfs", "/tmp",
            "--volume", f"{cwd}:/workspace:rw",
            "--workdir", "/workspace",
            self._image,
        ] + remapped

        try:
            proc = subprocess.run(
                docker_cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return SandboxRunResult(
                success=(proc.returncode == 0),
                stdout=proc.stdout,
                stderr=proc.stderr,
                return_code=proc.returncode,
                sandbox_mode=self.sandbox_mode,
            )
        except subprocess.TimeoutExpired:
            return SandboxRunResult(
                success=False,
                stderr=f"Container timed out after {timeout}s",
                return_code=-1,
                timed_out=True,
                sandbox_mode=self.sandbox_mode,
            )
        except FileNotFoundError:
            return SandboxRunResult(
                success=False,
                stderr="Docker CLI not found",
                return_code=-1,
                sandbox_mode=self.sandbox_mode,
            )


# ---------------------------------------------------------------------------
# SandboxFactory
# ---------------------------------------------------------------------------

class SandboxFactory:
    """Select the best available sandbox for the current environment.

    Selection priority (overridable via HARNESS_SANDBOX_MODE env var):
      "docker"   → DockerSandbox (requires Docker daemon)
      "resource" → ResourceLimitSandbox
      "auto"     → Docker if available, else ResourceLimitSandbox (default)
    """

    @staticmethod
    def create(spec: Optional[SandboxSpec] = None) -> _SandboxBase:
        mode = os.environ.get("HARNESS_SANDBOX_MODE", "auto").lower().strip()

        if mode == "docker":
            return DockerSandbox(spec=spec)
        if mode == "resource":
            return ResourceLimitSandbox(spec=spec)
        # auto
        if DockerSandbox.is_available():
            return DockerSandbox(spec=spec)
        return ResourceLimitSandbox(spec=spec)
