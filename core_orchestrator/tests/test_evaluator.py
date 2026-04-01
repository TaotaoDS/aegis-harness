"""Tests for Evaluator: sandbox code execution and verification."""

import sys

import pytest

from core_orchestrator.evaluator import Evaluator, EvalResult
from core_orchestrator.workspace_manager import WorkspaceManager


@pytest.fixture
def workspace(tmp_path):
    wm = WorkspaceManager(tmp_path)
    wm.create("proj")
    return wm


@pytest.fixture
def evaluator(workspace):
    return Evaluator(workspace=workspace, workspace_id="proj", timeout=10)


# --- EvalResult ---

class TestEvalResult:
    def test_success_result(self):
        r = EvalResult(success=True, stdout="ok")
        assert r.success is True
        assert r.error_summary() == ""

    def test_failure_result(self):
        r = EvalResult(success=False, stderr="SyntaxError", return_code=1)
        summary = r.error_summary()
        assert "SyntaxError" in summary
        assert "EXIT CODE: 1" in summary

    def test_timeout_result(self):
        r = EvalResult(success=False, timed_out=True, return_code=-1)
        assert "TIMEOUT" in r.error_summary()

    def test_to_dict(self):
        r = EvalResult(success=True, stdout="ok", stderr="", return_code=0)
        d = r.to_dict()
        assert d["success"] is True
        assert d["return_code"] == 0


# --- File existence validation ---

class TestValidateFilesExist:
    def test_all_files_present(self, workspace, evaluator):
        workspace.write("proj", "src/index.html", "<html></html>")
        workspace.write("proj", "src/style.css", "body {}")
        result = evaluator.validate_files_exist(["index.html", "style.css"])
        assert result.success is True

    def test_missing_file(self, workspace, evaluator):
        workspace.write("proj", "src/index.html", "<html></html>")
        result = evaluator.validate_files_exist(["index.html", "missing.js"])
        assert result.success is False
        assert "missing.js" in result.stderr

    def test_empty_file_list(self, evaluator):
        result = evaluator.validate_files_exist([])
        assert result.success is True


# --- Python syntax check ---

class TestSyntaxCheckPython:
    def test_valid_python(self, workspace, evaluator):
        workspace.write("proj", "src/app.py", "print('hello')\n")
        result = evaluator.syntax_check_python("src/app.py")
        assert result.success is True

    def test_invalid_python(self, workspace, evaluator):
        workspace.write("proj", "src/bad.py", "def foo(\n")
        result = evaluator.syntax_check_python("src/bad.py")
        assert result.success is False

    def test_missing_file(self, evaluator):
        result = evaluator.syntax_check_python("src/nope.py")
        assert result.success is False
        assert "not found" in result.stderr


# --- HTML validation ---

class TestValidateHtml:
    def test_valid_html(self, workspace, evaluator):
        html = "<!DOCTYPE html><html><head><title>T</title></head><body></body></html>"
        workspace.write("proj", "src/index.html", html)
        result = evaluator.validate_html("src/index.html")
        assert result.success is True

    def test_missing_doctype(self, workspace, evaluator):
        workspace.write("proj", "src/bad.html", "<html><body></body></html>")
        result = evaluator.validate_html("src/bad.html")
        assert result.success is False
        assert "DOCTYPE" in result.stderr

    def test_missing_file(self, evaluator):
        result = evaluator.validate_html("src/nope.html")
        assert result.success is False


# --- run_eval (composite) ---

class TestRunEval:
    def test_all_valid(self, workspace, evaluator):
        workspace.write("proj", "src/app.py", "x = 1\n")
        html = "<!DOCTYPE html><html><head></head><body></body></html>"
        workspace.write("proj", "src/index.html", html)
        workspace.write("proj", "src/style.css", "body {}")
        result = evaluator.run_eval(["app.py", "index.html", "style.css"])
        assert result.success is True

    def test_missing_file_fails(self, workspace, evaluator):
        result = evaluator.run_eval(["nonexistent.py"])
        assert result.success is False

    def test_syntax_error_fails(self, workspace, evaluator):
        workspace.write("proj", "src/bad.py", "def (:\n")
        result = evaluator.run_eval(["bad.py"])
        assert result.success is False

    def test_empty_file_list(self, evaluator):
        result = evaluator.run_eval([])
        assert result.success is True


# --- run_python ---

class TestRunPython:
    def test_successful_script(self, workspace, evaluator):
        workspace.write("proj", "src/hello.py", "print('hello world')\n")
        result = evaluator.run_python("src/hello.py")
        assert result.success is True
        assert "hello world" in result.stdout

    def test_failing_script(self, workspace, evaluator):
        workspace.write("proj", "src/fail.py", "raise ValueError('boom')\n")
        result = evaluator.run_python("src/fail.py")
        assert result.success is False
        assert "boom" in result.stderr

    def test_missing_script(self, evaluator):
        result = evaluator.run_python("src/nope.py")
        assert result.success is False
