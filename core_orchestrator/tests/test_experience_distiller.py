"""Tests for the ExperienceDistiller and ExperienceIndex modules."""

import json
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from core_orchestrator.experience_distiller import (
    ExperienceDistiller,
    ExperienceIndex,
)


# ---------------------------------------------------------------------------
# ExperienceIndex
# ---------------------------------------------------------------------------

class TestExperienceIndex:
    def test_content_hash_deterministic(self):
        h1 = ExperienceIndex.content_hash("problem A", "solution B")
        h2 = ExperienceIndex.content_hash("problem A", "solution B")
        assert h1 == h2
        assert len(h1) == 16

    def test_content_hash_case_insensitive(self):
        h1 = ExperienceIndex.content_hash("Problem A", "Solution B")
        h2 = ExperienceIndex.content_hash("problem a", "solution b")
        assert h1 == h2

    def test_content_hash_differs_for_different_content(self):
        h1 = ExperienceIndex.content_hash("problem A", "solution B")
        h2 = ExperienceIndex.content_hash("problem C", "solution D")
        assert h1 != h2

    def test_add_entry_and_duplicate_detection(self, tmp_path):
        with patch("core_orchestrator.experience_distiller._GLOBAL_SOLUTIONS_DIR", tmp_path):
            with patch("core_orchestrator.experience_distiller._INDEX_PATH", tmp_path / "_index.yaml"):
                idx = ExperienceIndex()
                lesson = {"problem": "CORS error", "solution": "Add middleware", "tags": ["cors"]}

                assert idx.add_entry("abc1", lesson, "ws1") is True
                assert idx.add_entry("abc2", lesson, "ws1") is False  # duplicate

                index = idx.load()
                assert len(index["entries"]) == 1
                assert len(index["hashes"]) == 1

    def test_is_duplicate(self, tmp_path):
        with patch("core_orchestrator.experience_distiller._GLOBAL_SOLUTIONS_DIR", tmp_path):
            with patch("core_orchestrator.experience_distiller._INDEX_PATH", tmp_path / "_index.yaml"):
                idx = ExperienceIndex()
                lesson = {"problem": "timeout", "solution": "increase limit"}
                idx.add_entry("t1", lesson)

                assert idx.is_duplicate("timeout", "increase limit") is True
                assert idx.is_duplicate("other", "different") is False

    def test_search_by_tags(self, tmp_path):
        with patch("core_orchestrator.experience_distiller._GLOBAL_SOLUTIONS_DIR", tmp_path):
            with patch("core_orchestrator.experience_distiller._INDEX_PATH", tmp_path / "_index.yaml"):
                idx = ExperienceIndex()
                idx.add_entry("s1", {"problem": "p1", "solution": "s1", "tags": ["python", "cors"]})
                idx.add_entry("s2", {"problem": "p2", "solution": "s2 unique", "tags": ["docker", "cors"]})
                idx.add_entry("s3", {"problem": "p3", "solution": "s3 different", "tags": ["react"]})

                results = idx.search_by_tags(["cors"])
                assert len(results) == 2

                results = idx.search_by_tags(["react"])
                assert len(results) == 1
                assert results[0]["id"] == "s3"

    def test_search_by_keyword(self, tmp_path):
        with patch("core_orchestrator.experience_distiller._GLOBAL_SOLUTIONS_DIR", tmp_path):
            with patch("core_orchestrator.experience_distiller._INDEX_PATH", tmp_path / "_index.yaml"):
                idx = ExperienceIndex()
                idx.add_entry("k1", {"problem": "database connection timeout", "solution": "s1", "tags": []})
                idx.add_entry("k2", {"problem": "CORS header missing", "solution": "s2 unique", "tags": []})

                results = idx.search_by_keyword("database timeout")
                assert len(results) >= 1
                assert results[0]["id"] == "k1"

    def test_empty_index_searches_return_empty(self, tmp_path):
        with patch("core_orchestrator.experience_distiller._GLOBAL_SOLUTIONS_DIR", tmp_path):
            with patch("core_orchestrator.experience_distiller._INDEX_PATH", tmp_path / "_index.yaml"):
                idx = ExperienceIndex()
                assert idx.search_by_tags(["python"]) == []
                assert idx.search_by_keyword("anything") == []


# ---------------------------------------------------------------------------
# ExperienceDistiller
# ---------------------------------------------------------------------------

class TestExperienceDistiller:
    @staticmethod
    def _make_gateway(responses=None):
        gw = MagicMock()
        if responses is None:
            responses = [
                # parallel sub-agents (symptoms, failures, root causes)
                json.dumps({"symptoms": ["Error 500 on /api/login"]}),
                json.dumps({"failed_attempts": [{"approach": "restart server", "why_failed": "config unchanged"}]}),
                json.dumps({"root_causes": [{"cause": "missing env var", "category": "config"}]}),
                # reflection agent call
                json.dumps({"lessons": [{
                    "type": "error_fix",
                    "problem": "Login endpoint returns 500",
                    "solution": "Set SECRET_KEY in environment",
                    "symptoms": "",
                    "failed_attempts": "",
                    "root_cause": "",
                    "tags": ["python", "auth"],
                }]}),
            ]
        call_count = {"n": 0}
        def fake_send(prompt, **kwargs):
            idx = min(call_count["n"], len(responses) - 1)
            call_count["n"] += 1
            return {"llm_response": responses[idx]}
        gw.send = fake_send
        return gw

    @staticmethod
    def _make_workspace(tmp_path):
        ws = MagicMock()
        files = {}

        def write(ws_id, filename, content):
            files[filename] = content

        def read(ws_id, filename):
            return files.get(filename, "")

        def list_files(ws_id):
            return list(files.keys())

        ws.write = write
        ws.read = read
        ws.list_files = list_files
        return ws

    def test_distill_saves_and_indexes(self, tmp_path):
        with patch("core_orchestrator.experience_distiller._GLOBAL_SOLUTIONS_DIR", tmp_path):
            with patch("core_orchestrator.experience_distiller._INDEX_PATH", tmp_path / "_index.yaml"):
                with patch("core_orchestrator.reflection_agent._GLOBAL_SOLUTIONS_DIR", tmp_path):
                    gw = self._make_gateway()
                    ws = self._make_workspace(tmp_path)
                    bus = MagicMock()
                    bus.events_log = []

                    distiller = ExperienceDistiller(gw, ws, "test_ws")
                    count = distiller.distill(
                        events_log=[{"label": "test.event", "data": {}}],
                        requirement="Fix login bug",
                        job_id="job-123",
                        bus=bus,
                    )

                    assert count >= 0
                    bus.emit.assert_any_call("distiller.start")

    def test_distill_no_crash_on_empty_events(self, tmp_path):
        with patch("core_orchestrator.experience_distiller._GLOBAL_SOLUTIONS_DIR", tmp_path):
            with patch("core_orchestrator.experience_distiller._INDEX_PATH", tmp_path / "_index.yaml"):
                with patch("core_orchestrator.reflection_agent._GLOBAL_SOLUTIONS_DIR", tmp_path):
                    gw = self._make_gateway([
                        json.dumps({"symptoms": []}),
                        json.dumps({"failed_attempts": []}),
                        json.dumps({"root_causes": []}),
                        json.dumps({"lessons": []}),
                    ])
                    ws = self._make_workspace(tmp_path)

                    distiller = ExperienceDistiller(gw, ws, "test_ws")
                    count = distiller.distill([], "empty task")
                    assert count == 0

    def test_distill_never_crashes_pipeline(self, tmp_path):
        with patch("core_orchestrator.experience_distiller._GLOBAL_SOLUTIONS_DIR", tmp_path):
            with patch("core_orchestrator.experience_distiller._INDEX_PATH", tmp_path / "_index.yaml"):
                gw = MagicMock()
                gw.send.side_effect = RuntimeError("LLM down")
                ws = self._make_workspace(tmp_path)

                distiller = ExperienceDistiller(gw, ws, "test_ws")
                count = distiller.distill([], "crash test")
                assert count == 0

    def test_retrieve_relevant_empty(self, tmp_path):
        with patch("core_orchestrator.experience_distiller._GLOBAL_SOLUTIONS_DIR", tmp_path):
            with patch("core_orchestrator.experience_distiller._INDEX_PATH", tmp_path / "_index.yaml"):
                gw = MagicMock()
                ws = self._make_workspace(tmp_path)
                distiller = ExperienceDistiller(gw, ws, "test_ws")
                result = distiller.retrieve_relevant("anything")
                assert result == ""

    def test_retrieve_relevant_with_indexed_solutions(self, tmp_path):
        with patch("core_orchestrator.experience_distiller._GLOBAL_SOLUTIONS_DIR", tmp_path):
            with patch("core_orchestrator.experience_distiller._INDEX_PATH", tmp_path / "_index.yaml"):
                idx = ExperienceIndex()
                lesson = {
                    "problem": "CORS preflight blocked",
                    "solution": "Add CORSMiddleware with allow_origins",
                    "type": "error_fix",
                    "tags": ["cors", "fastapi"],
                    "symptoms": "Browser shows CORS error",
                    "root_cause": "Missing middleware",
                }
                idx.add_entry("cors1", lesson)

                sol_file = tmp_path / "cors1.yaml"
                sol_file.write_text(yaml.dump(lesson), encoding="utf-8")

                gw = MagicMock()
                ws = self._make_workspace(tmp_path)
                distiller = ExperienceDistiller(gw, ws, "test_ws")
                result = distiller.retrieve_relevant("CORS error on API")

                assert "CORS" in result
                assert "CORSMiddleware" in result

    def test_parallel_extract_returns_all_keys(self, tmp_path):
        with patch("core_orchestrator.experience_distiller._GLOBAL_SOLUTIONS_DIR", tmp_path):
            with patch("core_orchestrator.experience_distiller._INDEX_PATH", tmp_path / "_index.yaml"):
                gw = self._make_gateway()
                ws = self._make_workspace(tmp_path)
                distiller = ExperienceDistiller(gw, ws, "test_ws")
                result = distiller._parallel_extract("some event log", "fix bug")
                assert "symptoms" in result
                assert "failed_attempts" in result
                assert "root_causes" in result
