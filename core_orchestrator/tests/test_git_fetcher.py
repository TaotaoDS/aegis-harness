"""Tests for core_orchestrator/git_fetcher.py — Universal Git Fetcher.

Covers:
- clone_repo: URL construction, token injection, SSH key path, idempotency,
  timeout handling, error scrubbing, directory cleanup on failure
- read_repo_file: happy path, missing file, path traversal rejection, truncation
- glob_repo: matching, max_results cap, missing repo error
- grep_repo: hits, no hits, context lines, invalid regex
- analyze_ast: Python AST extraction, front-matter / generic regex fallback
- make_tool_handler: dispatcher for all tool names, unknown tool
- _safe_repo_path / _safe_file_path: sandbox enforcement
"""

import ast
import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from core_orchestrator.git_fetcher import (
    clone_repo,
    read_repo_file,
    glob_repo,
    grep_repo,
    analyze_ast,
    make_tool_handler,
    _safe_repo_path,
    _safe_file_path,
    _scrub_token,
    CLONE_REPO_TOOL,
    READ_REPO_FILE_TOOL,
    GLOB_REPO_TOOL,
    GREP_REPO_TOOL,
    ANALYZE_AST_TOOL,
    WRITE_FUSION_REPORT_TOOL,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def repos_root(tmp_path: Path) -> Path:
    root = tmp_path / "repos"
    root.mkdir()
    return root


@pytest.fixture()
def fake_repo(repos_root: Path) -> Path:
    """Create a minimal fake cloned repo (has .git dir + some files)."""
    repo = repos_root / "my-repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / "README.md").write_text("# Hello\nThis is a test repo.", encoding="utf-8")
    src = repo / "src"
    src.mkdir()
    (src / "main.py").write_text(
        "import os\nimport sys\n\nclass App:\n    def run(self):\n        print('hello')\n",
        encoding="utf-8",
    )
    (src / "utils.py").write_text(
        "def helper(x):\n    return x * 2\n",
        encoding="utf-8",
    )
    (repo / "config.yaml").write_text("debug: true\nport: 8080\n", encoding="utf-8")
    return repo


# ---------------------------------------------------------------------------
# _scrub_token
# ---------------------------------------------------------------------------

class TestScrubToken:
    def test_scrubs_token_in_url(self):
        url = "https://my-secret-token@github.com/org/repo"
        scrubbed = _scrub_token(url, "my-secret-token")
        assert "my-secret-token" not in scrubbed
        assert "***" in scrubbed

    def test_empty_token_returns_url_unchanged(self):
        url = "https://github.com/org/repo"
        assert _scrub_token(url, "") == url


# ---------------------------------------------------------------------------
# _safe_repo_path
# ---------------------------------------------------------------------------

class TestSafeRepoPath:
    def test_valid_name_returns_path(self, repos_root):
        p = _safe_repo_path(repos_root, "my-repo")
        assert p == repos_root / "my-repo"

    def test_valid_underscore(self, repos_root):
        p = _safe_repo_path(repos_root, "repo_v2")
        assert p == repos_root / "repo_v2"

    def test_path_traversal_rejected(self, repos_root):
        with pytest.raises(ValueError, match="Invalid repo_name"):
            _safe_repo_path(repos_root, "../../../etc/passwd")

    def test_slash_in_name_rejected(self, repos_root):
        with pytest.raises(ValueError, match="Invalid repo_name"):
            _safe_repo_path(repos_root, "org/repo")

    def test_empty_name_rejected(self, repos_root):
        with pytest.raises(ValueError, match="Invalid repo_name"):
            _safe_repo_path(repos_root, "")

    def test_too_long_name_rejected(self, repos_root):
        with pytest.raises(ValueError, match="Invalid repo_name"):
            _safe_repo_path(repos_root, "a" * 65)


# ---------------------------------------------------------------------------
# _safe_file_path
# ---------------------------------------------------------------------------

class TestSafeFilePath:
    def test_valid_relative_path(self, repos_root, fake_repo):
        p = _safe_file_path(fake_repo, "src/main.py")
        assert p == fake_repo / "src" / "main.py"

    def test_traversal_rejected(self, repos_root, fake_repo):
        with pytest.raises(ValueError, match="Path traversal"):
            _safe_file_path(fake_repo, "../../etc/passwd")


# ---------------------------------------------------------------------------
# clone_repo
# ---------------------------------------------------------------------------

class TestCloneRepo:
    def _mock_ok(self):
        r = MagicMock()
        r.returncode = 0
        r.stderr = ""
        return r

    def test_basic_clone_calls_git(self, repos_root):
        with patch("subprocess.run", return_value=self._mock_ok()) as mock_run:
            path = clone_repo(
                git_url   = "https://github.com/org/repo.git",
                dest_name = "repo",
                repos_root= repos_root,
            )
        cmd = mock_run.call_args[0][0]
        assert "git" in cmd
        assert "clone" in cmd
        assert str(repos_root / "repo") in cmd
        assert path == str(repos_root / "repo")

    def test_token_injected_into_https_url(self, repos_root):
        with patch("subprocess.run", return_value=self._mock_ok()) as mock_run:
            clone_repo(
                git_url    = "https://github.com/org/private.git",
                dest_name  = "private",
                repos_root = repos_root,
                auth_token = "ghp_secret",
            )
        cmd = mock_run.call_args[0][0]
        url_arg = [a for a in cmd if "github.com" in a][0]
        assert "ghp_secret@" in url_arg

    def test_token_not_in_exception_message(self, repos_root):
        """Tokens must be scrubbed from error messages."""
        fail = MagicMock()
        fail.returncode = 128
        fail.stderr = "fatal: Authentication failed for 'https://ghp_secret@github.com'"
        with patch("subprocess.run", return_value=fail):
            with pytest.raises(RuntimeError) as exc_info:
                clone_repo(
                    git_url    = "https://github.com/org/repo.git",
                    dest_name  = "repo",
                    repos_root = repos_root,
                    auth_token = "ghp_secret",
                )
        assert "ghp_secret" not in str(exc_info.value)
        assert "***" in str(exc_info.value)

    def test_idempotent_if_already_cloned(self, repos_root, fake_repo):
        """If .git already exists, clone_repo skips subprocess and returns path."""
        with patch("subprocess.run") as mock_run:
            path = clone_repo(
                git_url    = "https://github.com/org/repo.git",
                dest_name  = "my-repo",
                repos_root = repos_root,
            )
        mock_run.assert_not_called()
        assert path == str(fake_repo)

    def test_shallow_clone_uses_depth_flag(self, repos_root):
        with patch("subprocess.run", return_value=self._mock_ok()) as mock_run:
            clone_repo(
                git_url    = "https://github.com/org/repo.git",
                dest_name  = "shallow",
                repos_root = repos_root,
                depth      = 1,
            )
        cmd = mock_run.call_args[0][0]
        assert "--depth" in cmd
        assert "1" in cmd

    def test_branch_flag_forwarded(self, repos_root):
        with patch("subprocess.run", return_value=self._mock_ok()) as mock_run:
            clone_repo(
                git_url    = "https://github.com/org/repo.git",
                dest_name  = "branched",
                repos_root = repos_root,
                branch     = "develop",
            )
        cmd = mock_run.call_args[0][0]
        assert "--branch" in cmd
        assert "develop" in cmd

    def test_timeout_raises_runtime_error(self, repos_root):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("git", 300)):
            with pytest.raises(RuntimeError, match="timed out"):
                clone_repo(
                    git_url    = "https://github.com/org/repo.git",
                    dest_name  = "slow",
                    repos_root = repos_root,
                )

    def test_git_failure_raises_runtime_error(self, repos_root):
        fail = MagicMock()
        fail.returncode = 128
        fail.stderr = "fatal: repository not found"
        with patch("subprocess.run", return_value=fail):
            with pytest.raises(RuntimeError, match="git clone failed"):
                clone_repo(
                    git_url    = "https://github.com/org/bad.git",
                    dest_name  = "bad",
                    repos_root = repos_root,
                )

    def test_ssh_url_sets_ssh_command_env(self, repos_root):
        """SSH auth token treated as key file path; GIT_SSH_COMMAND set in env."""
        with patch("subprocess.run", return_value=self._mock_ok()) as mock_run:
            clone_repo(
                git_url    = "git@github.com:org/repo.git",
                dest_name  = "ssh-repo",
                repos_root = repos_root,
                auth_token = "/home/user/.ssh/deploy_key",
            )
        env = mock_run.call_args[1]["env"]
        assert "GIT_SSH_COMMAND" in env
        assert "/home/user/.ssh/deploy_key" in env["GIT_SSH_COMMAND"]


# ---------------------------------------------------------------------------
# read_repo_file
# ---------------------------------------------------------------------------

class TestReadRepoFile:
    def test_reads_existing_file(self, repos_root, fake_repo):
        content = read_repo_file("my-repo", "README.md", repos_root)
        assert "Hello" in content

    def test_missing_file_returns_error_string(self, repos_root, fake_repo):
        content = read_repo_file("my-repo", "nonexistent.txt", repos_root)
        assert "[error]" in content

    def test_path_traversal_returns_error(self, repos_root, fake_repo):
        content = read_repo_file("my-repo", "../../etc/shadow", repos_root)
        assert "[error]" in content

    def test_unknown_repo_returns_error(self, repos_root):
        content = read_repo_file("ghost-repo", "README.md", repos_root)
        assert "[error]" in content

    def test_large_file_truncated(self, repos_root, fake_repo):
        big = fake_repo / "big.txt"
        big.write_text("X" * 10_000, encoding="utf-8")
        content = read_repo_file("my-repo", "big.txt", repos_root)
        assert "truncated" in content
        assert len(content) < 10_000


# ---------------------------------------------------------------------------
# glob_repo
# ---------------------------------------------------------------------------

class TestGlobRepo:
    def test_finds_python_files(self, repos_root, fake_repo):
        result = json.loads(glob_repo("my-repo", "**/*.py", repos_root))
        assert result["count"] == 2
        files = result["files"]
        assert any("main.py" in f for f in files)
        assert any("utils.py" in f for f in files)

    def test_no_match_returns_empty_list(self, repos_root, fake_repo):
        result = json.loads(glob_repo("my-repo", "**/*.go", repos_root))
        assert result["count"] == 0
        assert result["files"] == []

    def test_max_results_caps_output(self, repos_root, fake_repo):
        # Create 10 extra .py files
        for i in range(10):
            (fake_repo / f"extra_{i}.py").write_text("pass\n")
        result = json.loads(glob_repo("my-repo", "**/*.py", repos_root, max_results=3))
        assert result["count"] == 3
        assert result["truncated"] is True

    def test_unknown_repo_returns_error(self, repos_root):
        result = json.loads(glob_repo("ghost", "**/*", repos_root))
        assert "error" in result


# ---------------------------------------------------------------------------
# grep_repo
# ---------------------------------------------------------------------------

class TestGrepRepo:
    def test_finds_keyword(self, repos_root, fake_repo):
        result = grep_repo("my-repo", "class App", repos_root)
        assert "class App" in result
        assert "main.py" in result

    def test_no_match_returns_informative_message(self, repos_root, fake_repo):
        result = grep_repo("my-repo", "NONEXISTENT_PATTERN_XYZ", repos_root)
        assert "no matches" in result

    def test_context_lines_included(self, repos_root, fake_repo):
        # "run" is on line 5; context should include surrounding lines
        result = grep_repo("my-repo", r"def run", repos_root,
                           file_glob="**/*.py", context_lines=1)
        assert "def run" in result

    def test_invalid_regex_returns_error(self, repos_root, fake_repo):
        result = grep_repo("my-repo", "[invalid", repos_root)
        assert "[error]" in result

    def test_file_glob_filters_search(self, repos_root, fake_repo):
        # "debug" is only in config.yaml, not in .py files
        result_py   = grep_repo("my-repo", "debug", repos_root, file_glob="*.py")
        result_yaml = grep_repo("my-repo", "debug", repos_root, file_glob="*.yaml")
        assert "no matches" in result_py
        assert "debug" in result_yaml

    def test_unknown_repo_returns_error(self, repos_root):
        result = grep_repo("ghost", "pattern", repos_root)
        assert "[error]" in result


# ---------------------------------------------------------------------------
# analyze_ast
# ---------------------------------------------------------------------------

class TestAnalyzeAst:
    def test_python_file_extracts_class(self, repos_root, fake_repo):
        result = json.loads(analyze_ast("my-repo", "src/main.py", repos_root))
        assert result["language"] == "python"
        classes = [c["name"] for c in result["classes"]]
        assert "App" in classes

    def test_python_file_extracts_imports(self, repos_root, fake_repo):
        result = json.loads(analyze_ast("my-repo", "src/main.py", repos_root))
        assert "os" in result["imports"]
        assert "sys" in result["imports"]

    def test_python_file_extracts_functions(self, repos_root, fake_repo):
        result = json.loads(analyze_ast("my-repo", "src/utils.py", repos_root))
        assert "helper" in result["functions"]

    def test_missing_file_returns_error(self, repos_root, fake_repo):
        result = json.loads(analyze_ast("my-repo", "nonexistent.py", repos_root))
        assert "error" in result

    def test_non_python_file_uses_regex_fallback(self, repos_root, fake_repo):
        # config.yaml has no Python AST — should use regex fallback
        result = json.loads(analyze_ast("my-repo", "config.yaml", repos_root))
        assert result["language"] == "yaml"
        # No "error" key expected
        assert "error" not in result

    def test_path_traversal_returns_error(self, repos_root, fake_repo):
        result = json.loads(analyze_ast("my-repo", "../../etc/passwd", repos_root))
        assert "error" in result

    def test_unknown_repo_returns_error(self, repos_root):
        result = json.loads(analyze_ast("ghost", "main.py", repos_root))
        assert "error" in result

    def test_syntax_error_handled_gracefully(self, repos_root, fake_repo):
        bad = fake_repo / "bad.py"
        bad.write_text("def foo(\n  # broken", encoding="utf-8")
        result = json.loads(analyze_ast("my-repo", "bad.py", repos_root))
        assert "error" in result


# ---------------------------------------------------------------------------
# make_tool_handler
# ---------------------------------------------------------------------------

class TestMakeToolHandler:
    def test_clone_repo_dispatched(self, repos_root):
        handler = make_tool_handler(repos_root)
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stderr = ""
        with patch("subprocess.run", return_value=mock_result):
            result = json.loads(handler("clone_repo", {
                "git_url": "https://github.com/org/repo.git",
                "dest_name": "repo",
            }))
        assert result["status"] == "cloned"

    def test_read_repo_file_dispatched(self, repos_root, fake_repo):
        handler = make_tool_handler(repos_root)
        content = handler("read_repo_file", {
            "repo_name": "my-repo",
            "file_path": "README.md",
        })
        assert "Hello" in content

    def test_glob_repo_dispatched(self, repos_root, fake_repo):
        handler = make_tool_handler(repos_root)
        result = json.loads(handler("glob_repo", {
            "repo_name": "my-repo",
            "pattern": "**/*.py",
        }))
        assert result["count"] > 0

    def test_grep_repo_dispatched(self, repos_root, fake_repo):
        handler = make_tool_handler(repos_root)
        result = handler("grep_repo", {
            "repo_name": "my-repo",
            "pattern": "class App",
        })
        assert "class App" in result

    def test_analyze_ast_dispatched(self, repos_root, fake_repo):
        handler = make_tool_handler(repos_root)
        result = json.loads(handler("analyze_ast", {
            "repo_name": "my-repo",
            "file_path": "src/main.py",
        }))
        assert result["language"] == "python"

    def test_unknown_tool_returns_error(self, repos_root):
        handler = make_tool_handler(repos_root)
        result = json.loads(handler("nonexistent_tool", {}))
        assert "error" in result

    def test_exception_in_handler_returns_error_json(self, repos_root):
        handler = make_tool_handler(repos_root)
        # Pass invalid dest_name — should return error JSON, not raise
        result = json.loads(handler("clone_repo", {
            "git_url": "https://github.com/org/repo.git",
            "dest_name": "../../../evil",
        }))
        assert "error" in result


# ---------------------------------------------------------------------------
# Tool definition schema sanity checks
# ---------------------------------------------------------------------------

class TestToolDefinitions:
    @pytest.mark.parametrize("tool", [
        CLONE_REPO_TOOL,
        READ_REPO_FILE_TOOL,
        GLOB_REPO_TOOL,
        GREP_REPO_TOOL,
        ANALYZE_AST_TOOL,
        WRITE_FUSION_REPORT_TOOL,
    ])
    def test_tool_has_required_fields(self, tool):
        assert "name" in tool
        assert "description" in tool
        assert "parameters" in tool
        assert tool["parameters"]["type"] == "object"
        assert "properties" in tool["parameters"]
        assert "required" in tool["parameters"]

    def test_clone_repo_tool_has_git_url_required(self):
        assert "git_url" in CLONE_REPO_TOOL["parameters"]["required"]
        assert "dest_name" in CLONE_REPO_TOOL["parameters"]["required"]

    def test_write_fusion_report_required_fields(self):
        req = WRITE_FUSION_REPORT_TOOL["parameters"]["required"]
        for field in ("title", "repos_analyzed", "fusion_architecture",
                      "implementation_steps", "tags"):
            assert field in req
