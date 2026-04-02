"""Tests for event bus: terminal rendering, file logging, NullBus, ListBus."""

import io
import os
from pathlib import Path

import pytest

from core_orchestrator.event_bus import (
    EventBus,
    NullBus,
    ListBus,
    bus_from_workspace,
    _pick_color,
    _format_kwargs,
    _COLORS,
    AUDIT_LOG_FILENAME,
)
from core_orchestrator.workspace_manager import WorkspaceManager


# ---------------------------------------------------------------------------
# _pick_color
# ---------------------------------------------------------------------------

class TestPickColor:
    def test_fail_events_are_red(self):
        assert _pick_color("evaluator.fail") == _COLORS["red"]
        assert _pick_color("qa.fail") == _COLORS["red"]

    def test_error_events_are_red(self):
        assert _pick_color("architect.error") == _COLORS["red"]

    def test_escalated_is_red(self):
        assert _pick_color("resilience.escalated") == _COLORS["red"]

    def test_zero_files_is_red(self):
        assert _pick_color("evaluator.zero_files") == _COLORS["red"]

    def test_budget_exceeded_is_red(self):
        assert _pick_color("resilience.budget_exceeded") == _COLORS["red"]

    def test_file_fail_is_red(self):
        assert _pick_color("evaluator.file_fail") == _COLORS["red"]

    def test_rejected_is_red(self):
        assert _pick_color("qa.rejected") == _COLORS["red"]

    def test_pass_events_are_green(self):
        assert _pick_color("qa.pass") == _COLORS["green"]
        assert _pick_color("evaluator.pass") == _COLORS["green"]

    def test_approved_is_green(self):
        assert _pick_color("qa.approved") == _COLORS["green"]

    def test_complete_is_green(self):
        assert _pick_color("pipeline.execution_complete") == _COLORS["green"]

    def test_all_pass_is_green(self):
        assert _pick_color("evaluator.all_pass") == _COLORS["green"]

    def test_architect_is_cyan(self):
        assert _pick_color("architect.solving") == _COLORS["cyan"]
        assert _pick_color("architect.llm_response") == _COLORS["cyan"]

    def test_evaluator_is_yellow(self):
        assert _pick_color("evaluator.start") == _COLORS["yellow"]

    def test_qa_is_blue(self):
        assert _pick_color("qa.reviewing") == _COLORS["blue"]

    def test_resilience_is_magenta(self):
        assert _pick_color("resilience.attempt_start") == _COLORS["magenta"]

    def test_pipeline_is_bold(self):
        assert _pick_color("pipeline.start") == _COLORS["bold"]

    def test_unknown_event_empty(self):
        assert _pick_color("unknown.thing") == ""

    def test_failure_overrides_prefix(self):
        """Failure suffix takes priority over agent prefix color."""
        # evaluator.fail should be red, not yellow
        assert _pick_color("evaluator.fail") == _COLORS["red"]
        # architect.error should be red, not cyan
        assert _pick_color("architect.error") == _COLORS["red"]


# ---------------------------------------------------------------------------
# _format_kwargs
# ---------------------------------------------------------------------------

class TestFormatKwargs:
    def test_empty(self):
        assert _format_kwargs({}) == ""

    def test_single(self):
        assert _format_kwargs({"task_id": "task_1"}) == "task_id=task_1"

    def test_multiple(self):
        result = _format_kwargs({"a": 1, "b": "x"})
        assert "a=1" in result
        assert "b=x" in result

    def test_long_string_truncated(self):
        result = _format_kwargs({"data": "x" * 300})
        assert "..." in result
        assert len(result) < 300


# ---------------------------------------------------------------------------
# NullBus
# ---------------------------------------------------------------------------

class TestNullBus:
    def test_emit_does_nothing(self):
        bus = NullBus()
        # Should not raise
        bus.emit("any.event", key="value")

    def test_multiple_emits(self):
        bus = NullBus()
        for _ in range(100):
            bus.emit("test.event")


# ---------------------------------------------------------------------------
# ListBus
# ---------------------------------------------------------------------------

class TestListBus:
    def test_captures_events(self):
        bus = ListBus()
        bus.emit("architect.solving", task_id="task_1")
        bus.emit("qa.pass", task_id="task_1")
        assert len(bus.events) == 2

    def test_event_structure(self):
        bus = ListBus()
        bus.emit("evaluator.fail", task_id="task_2", error="SyntaxError")
        event_name, kwargs = bus.events[0]
        assert event_name == "evaluator.fail"
        assert kwargs["task_id"] == "task_2"
        assert kwargs["error"] == "SyntaxError"

    def test_starts_empty(self):
        bus = ListBus()
        assert bus.events == []


# ---------------------------------------------------------------------------
# EventBus — terminal rendering
# ---------------------------------------------------------------------------

class TestEventBusTerminal:
    def test_writes_to_stream(self, tmp_path):
        stream = io.StringIO()
        bus = EventBus(tmp_path, stream=stream, enable_file_log=False)
        bus.emit("architect.solving", task_id="task_1")
        output = stream.getvalue()
        assert "ARCHITECT.SOLVING" in output
        assert "task_id=task_1" in output

    def test_no_ansi_on_non_tty(self, tmp_path):
        """StringIO is not a TTY, so no ANSI codes should appear."""
        stream = io.StringIO()
        bus = EventBus(tmp_path, stream=stream, enable_file_log=False)
        bus.emit("evaluator.fail", error="bad")
        output = stream.getvalue()
        assert "\033[" not in output

    def test_timestamp_present(self, tmp_path):
        stream = io.StringIO()
        bus = EventBus(tmp_path, stream=stream, enable_file_log=False)
        bus.emit("pipeline.start")
        output = stream.getvalue()
        # Should have [HH:MM:SS] format
        assert "[" in output and "]" in output

    def test_terminal_disabled(self, tmp_path):
        stream = io.StringIO()
        bus = EventBus(tmp_path, stream=stream, enable_terminal=False, enable_file_log=False)
        bus.emit("test.event")
        assert stream.getvalue() == ""


# ---------------------------------------------------------------------------
# EventBus — file audit log
# ---------------------------------------------------------------------------

class TestEventBusFileLog:
    def test_creates_log_file(self, tmp_path):
        bus = EventBus(tmp_path, enable_terminal=False)
        bus.emit("pipeline.start", workspace="test")
        log_path = tmp_path / AUDIT_LOG_FILENAME
        assert log_path.exists()

    def test_log_contains_event(self, tmp_path):
        bus = EventBus(tmp_path, enable_terminal=False)
        bus.emit("architect.solving", task_id="task_1")
        log_content = (tmp_path / AUDIT_LOG_FILENAME).read_text()
        assert "ARCHITECT.SOLVING" in log_content
        assert "task_id=task_1" in log_content

    def test_log_appends(self, tmp_path):
        bus = EventBus(tmp_path, enable_terminal=False)
        bus.emit("event.one")
        bus.emit("event.two")
        log_content = (tmp_path / AUDIT_LOG_FILENAME).read_text()
        assert "EVENT.ONE" in log_content
        assert "EVENT.TWO" in log_content

    def test_log_has_timestamp(self, tmp_path):
        bus = EventBus(tmp_path, enable_terminal=False)
        bus.emit("test.event")
        log_content = (tmp_path / AUDIT_LOG_FILENAME).read_text()
        # Should contain date-time pattern like "2026-04-02 14:30:00"
        assert "|" in log_content  # timestamp | message separator

    def test_file_log_disabled(self, tmp_path):
        bus = EventBus(tmp_path, enable_terminal=False, enable_file_log=False)
        bus.emit("test.event")
        log_path = tmp_path / AUDIT_LOG_FILENAME
        assert not log_path.exists()


# ---------------------------------------------------------------------------
# bus_from_workspace factory
# ---------------------------------------------------------------------------

class TestBusFromWorkspace:
    def test_creates_event_bus_isolated(self, tmp_path):
        ws = WorkspaceManager(tmp_path, isolated=True)
        ws.create("proj")
        bus = bus_from_workspace(ws, "proj", enable_terminal=False)
        bus.emit("test.event")
        log_path = tmp_path / "proj" / "_workspace" / AUDIT_LOG_FILENAME
        assert log_path.exists()

    def test_creates_event_bus_classic(self, tmp_path):
        ws = WorkspaceManager(tmp_path, isolated=False)
        ws.create("proj")
        bus = bus_from_workspace(ws, "proj", enable_terminal=False)
        bus.emit("test.event")
        log_path = tmp_path / "proj" / AUDIT_LOG_FILENAME
        assert log_path.exists()

    def test_custom_stream(self, tmp_path):
        ws = WorkspaceManager(tmp_path)
        ws.create("proj")
        stream = io.StringIO()
        bus = bus_from_workspace(ws, "proj", stream=stream, enable_file_log=False)
        bus.emit("architect.solving", task_id="task_1")
        assert "ARCHITECT.SOLVING" in stream.getvalue()


# ---------------------------------------------------------------------------
# Integration: agents emit events via ListBus
# ---------------------------------------------------------------------------

class TestAgentIntegration:
    """Verify that agents actually emit events when bus is provided."""

    @pytest.fixture
    def workspace(self, tmp_path):
        wm = WorkspaceManager(tmp_path)
        wm.create("proj")
        wm.write("proj", "tasks/task_1.md",
                 "# Task 1\n- **ID:** task_1\n- **Priority:** high\n- **Description:** Test\n")
        return wm

    def test_architect_emits_events(self, workspace):
        from core_orchestrator.architect_agent import ArchitectAgent
        from core_orchestrator.llm_gateway import LLMGateway

        bus = ListBus()
        gateway = LLMGateway(llm=lambda t: "===FILE: app.py===\nx = 1\n===END===")
        arch = ArchitectAgent(
            gateway=gateway, workspace=workspace, workspace_id="proj", bus=bus,
        )
        arch.solve_task("tasks/task_1.md")
        event_names = [e[0] for e in bus.events]
        assert "architect.solving" in event_names
        assert "architect.llm_response" in event_names
        assert "architect.files_written" in event_names

    def test_evaluator_emits_events(self, workspace):
        from core_orchestrator.evaluator import Evaluator

        workspace.write("proj", "deliverables/app.py", "x = 1\n")
        bus = ListBus()
        ev = Evaluator(workspace=workspace, workspace_id="proj", bus=bus)
        ev.run_eval(["app.py"])
        event_names = [e[0] for e in bus.events]
        assert "evaluator.start" in event_names
        assert "evaluator.all_pass" in event_names

    def test_qa_emits_events(self, workspace):
        import json
        from core_orchestrator.qa_agent import QAAgent
        from core_orchestrator.llm_gateway import LLMGateway

        workspace.write("proj", "artifacts/task_1_solution.md", "# Solution\nDone.")
        bus = ListBus()
        gateway = LLMGateway(
            llm=lambda t: json.dumps({"verdict": "pass", "issues": [], "notes": "ok"}),
        )
        qa = QAAgent(gateway=gateway, workspace=workspace, workspace_id="proj", bus=bus)
        qa.review_task("task_1")
        event_names = [e[0] for e in bus.events]
        assert "qa.reviewing" in event_names
        assert "qa.approved" in event_names
