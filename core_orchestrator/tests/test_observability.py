"""Tests for Module 3 — StructuredObservability.

Covers:
  JsonEventBus   — JSON-line output, job_id injection, logger handle pooling
  bus_from_workspace — structured=True returns JsonEventBus
  EventBus logger pool — repeated instantiation on same dir keeps one handler
  /metrics endpoint — 200 OK, Prometheus text format, required metric names
"""

import io
import json
import logging

import pytest

from core_orchestrator.event_bus import (
    EventBus,
    JsonEventBus,
    NullBus,
    bus_from_workspace,
    _LOGGER_POOL,
    AUDIT_LOG_FILENAME,
)
from core_orchestrator.workspace_manager import WorkspaceManager


# ===========================================================================
# JsonEventBus — output format
# ===========================================================================

class TestJsonEventBusOutput:
    def test_emit_writes_valid_json(self, tmp_path):
        stream = io.StringIO()
        bus = JsonEventBus(tmp_path, job_id="job-1", enable_file_log=False, stream=stream)
        bus.emit("architect.solving", task_id="task_1")
        line = stream.getvalue().strip()
        record = json.loads(line)  # must not raise
        assert record["event"] == "architect.solving"

    def test_emit_contains_required_fields(self, tmp_path):
        stream = io.StringIO()
        bus = JsonEventBus(tmp_path, job_id="abc123", enable_file_log=False, stream=stream)
        bus.emit("pipeline.start", workspace="proj")
        record = json.loads(stream.getvalue().strip())
        assert "ts" in record
        assert "job_id" in record
        assert "event" in record

    def test_job_id_injected_in_every_emit(self, tmp_path):
        stream = io.StringIO()
        bus = JsonEventBus(tmp_path, job_id="xyz-99", enable_file_log=False, stream=stream)
        bus.emit("event.one")
        bus.emit("event.two")
        lines = stream.getvalue().strip().splitlines()
        for line in lines:
            assert json.loads(line)["job_id"] == "xyz-99"

    def test_kwargs_included_in_record(self, tmp_path):
        stream = io.StringIO()
        bus = JsonEventBus(tmp_path, job_id="j1", enable_file_log=False, stream=stream)
        bus.emit("evaluator.fail", task_id="t1", error="SyntaxError")
        record = json.loads(stream.getvalue().strip())
        assert record["task_id"] == "t1"
        assert record["error"] == "SyntaxError"

    def test_ts_is_iso8601_utc(self, tmp_path):
        stream = io.StringIO()
        bus = JsonEventBus(tmp_path, job_id="j1", enable_file_log=False, stream=stream)
        bus.emit("test.event")
        ts = json.loads(stream.getvalue().strip())["ts"]
        assert "T" in ts and ts.endswith("Z")

    def test_multiple_emits_produce_multiple_lines(self, tmp_path):
        stream = io.StringIO()
        bus = JsonEventBus(tmp_path, job_id="j1", enable_file_log=False, stream=stream)
        for i in range(5):
            bus.emit(f"event.{i}")
        lines = [l for l in stream.getvalue().splitlines() if l.strip()]
        assert len(lines) == 5
        for line in lines:
            json.loads(line)  # each line must be valid JSON

    def test_empty_job_id_allowed(self, tmp_path):
        stream = io.StringIO()
        bus = JsonEventBus(tmp_path, enable_file_log=False, stream=stream)
        bus.emit("test.event")
        record = json.loads(stream.getvalue().strip())
        assert record["job_id"] == ""

    def test_writes_to_log_file(self, tmp_path):
        bus = JsonEventBus(tmp_path, job_id="j1", enable_file_log=True)
        bus.emit("architect.solving", task_id="t1")
        log_path = tmp_path / AUDIT_LOG_FILENAME
        assert log_path.exists()
        record = json.loads(log_path.read_text().strip())
        assert record["event"] == "architect.solving"
        assert record["job_id"] == "j1"


# ===========================================================================
# JsonEventBus — logger handle pooling (no leaks)
# ===========================================================================

class TestJsonEventBusLoggerPool:
    def test_same_dir_shares_one_handler(self, tmp_path):
        _LOGGER_POOL.clear()
        JsonEventBus(tmp_path, job_id="a", enable_file_log=True)
        JsonEventBus(tmp_path, job_id="b", enable_file_log=True)
        pool_key = f"json:{tmp_path.resolve()}"
        logger = _LOGGER_POOL[pool_key]
        assert len(logger.handlers) == 1

    def test_different_dirs_get_separate_loggers(self, tmp_path):
        _LOGGER_POOL.clear()
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir()
        dir_b.mkdir()
        JsonEventBus(dir_a, job_id="x", enable_file_log=True)
        JsonEventBus(dir_b, job_id="y", enable_file_log=True)
        key_a = f"json:{dir_a.resolve()}"
        key_b = f"json:{dir_b.resolve()}"
        assert key_a in _LOGGER_POOL
        assert key_b in _LOGGER_POOL
        assert _LOGGER_POOL[key_a] is not _LOGGER_POOL[key_b]


# ===========================================================================
# EventBus — legacy logger handle pooling fix
# ===========================================================================

class TestEventBusLoggerPool:
    def test_repeated_instantiation_same_dir_one_handler(self, tmp_path):
        _LOGGER_POOL.clear()
        EventBus(tmp_path, enable_terminal=False, enable_file_log=True)
        EventBus(tmp_path, enable_terminal=False, enable_file_log=True)
        pool_key = str(tmp_path.resolve())
        logger = _LOGGER_POOL[pool_key]
        assert len(logger.handlers) == 1


# ===========================================================================
# bus_from_workspace — structured=True
# ===========================================================================

class TestBusFromWorkspaceStructured:
    def test_structured_returns_json_event_bus(self, tmp_path):
        ws = WorkspaceManager(tmp_path)
        ws.create("proj")
        bus = bus_from_workspace(ws, "proj", structured=True, job_id="j1", enable_file_log=False)
        assert isinstance(bus, JsonEventBus)

    def test_default_returns_event_bus(self, tmp_path):
        ws = WorkspaceManager(tmp_path)
        ws.create("proj")
        bus = bus_from_workspace(ws, "proj", enable_file_log=False, enable_terminal=False)
        assert isinstance(bus, EventBus)

    def test_structured_bus_writes_valid_json(self, tmp_path):
        stream = io.StringIO()
        ws = WorkspaceManager(tmp_path)
        ws.create("proj")
        bus = bus_from_workspace(
            ws, "proj",
            structured=True, job_id="j99",
            enable_file_log=False, stream=stream,
        )
        bus.emit("architect.solving", task_id="t1")
        record = json.loads(stream.getvalue().strip())
        assert record["job_id"] == "j99"
        assert record["event"] == "architect.solving"

    def test_structured_bus_isolates_to_workspace_dir(self, tmp_path):
        ws = WorkspaceManager(tmp_path, isolated=True)
        ws.create("proj")
        bus = bus_from_workspace(ws, "proj", structured=True, job_id="j1")
        bus.emit("test.event")
        log_path = tmp_path / "proj" / "_workspace" / AUDIT_LOG_FILENAME
        assert log_path.exists()


# ===========================================================================
# /metrics endpoint
# ===========================================================================

class TestMetricsEndpoint:
    def _client(self):
        from fastapi.testclient import TestClient
        from api.main import app
        return TestClient(app)

    def test_metrics_returns_200(self):
        client = self._client()
        resp = client.get("/metrics")
        assert resp.status_code == 200

    def test_metrics_content_type_is_prometheus(self):
        client = self._client()
        resp = client.get("/metrics")
        assert "text/plain" in resp.headers["content-type"]

    def test_metrics_contains_jobs_total(self):
        client = self._client()
        resp = client.get("/metrics")
        assert "harness_jobs_total" in resp.text

    def test_metrics_contains_task_duration(self):
        client = self._client()
        resp = client.get("/metrics")
        assert "harness_task_duration_seconds" in resp.text

    def test_metrics_contains_llm_tokens(self):
        client = self._client()
        resp = client.get("/metrics")
        assert "harness_llm_tokens_total" in resp.text

    def test_metrics_contains_escalations(self):
        client = self._client()
        resp = client.get("/metrics")
        assert "harness_escalations_total" in resp.text

    def test_metrics_counter_increments(self):
        from api.metrics import jobs_total
        before_text = self._client().get("/metrics").text
        jobs_total.labels(status="completed").inc()
        after_text = self._client().get("/metrics").text
        assert "harness_jobs_total" in after_text
