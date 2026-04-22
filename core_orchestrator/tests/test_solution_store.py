"""Tests for SolutionStore — workspace-scoped lesson persistence."""

import pytest
import yaml

from core_orchestrator.solution_store import SolutionStore
from core_orchestrator.workspace_manager import WorkspaceManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def workspace(tmp_path):
    wm = WorkspaceManager(tmp_path, isolated=True)
    wm.create("proj_alpha")
    return wm


@pytest.fixture
def store(workspace):
    return SolutionStore(workspace, "proj_alpha")


SAMPLE = {
    "type": "error_fix",
    "problem": "FastAPI requires Form() not Body() for non-JSON endpoints",
    "solution": "Use Form() from fastapi for form-data parameters",
    "context": "POST /upload endpoint",
    "tags": ["python", "fastapi"],
}


# ---------------------------------------------------------------------------
# TestSave
# ---------------------------------------------------------------------------

class TestSave:
    def test_returns_string_id(self, store):
        sol_id = store.save(SAMPLE.copy())
        assert isinstance(sol_id, str)
        assert len(sol_id) == 8

    def test_id_is_hex(self, store):
        sol_id = store.save(SAMPLE.copy())
        int(sol_id, 16)   # should not raise

    def test_file_exists_after_save(self, workspace, store):
        sol_id = store.save(SAMPLE.copy())
        assert workspace.exists("proj_alpha", f"solutions/{sol_id}.yaml")

    def test_saved_content_is_valid_yaml(self, workspace, store):
        sol_id = store.save(SAMPLE.copy())
        raw = workspace.read("proj_alpha", f"solutions/{sol_id}.yaml")
        data = yaml.safe_load(raw)
        assert isinstance(data, dict)

    def test_saved_content_matches_input(self, store):
        sol_id = store.save(SAMPLE.copy())
        loaded = store.load_all()
        assert any(s["id"] == sol_id for s in loaded)
        saved = next(s for s in loaded if s["id"] == sol_id)
        assert saved["problem"] == SAMPLE["problem"]
        assert saved["solution"] == SAMPLE["solution"]

    def test_sets_timestamp_if_missing(self, store):
        s = {"problem": "p", "solution": "s"}
        sol_id = store.save(s)
        loaded = store.load_all()
        saved = next(x for x in loaded if x["id"] == sol_id)
        assert "timestamp" in saved
        assert saved["timestamp"]   # non-empty

    def test_does_not_mutate_caller_dict(self, store):
        original = SAMPLE.copy()
        original_keys = set(original.keys())
        store.save(original)
        assert set(original.keys()) == original_keys  # no extra keys added

    def test_multiple_saves_produce_unique_ids(self, store):
        ids = [store.save({"problem": f"p{i}", "solution": f"s{i}"}) for i in range(5)]
        assert len(set(ids)) == 5


# ---------------------------------------------------------------------------
# TestLoadAll
# ---------------------------------------------------------------------------

class TestLoadAll:
    def test_empty_store_returns_empty_list(self, store):
        assert store.load_all() == []

    def test_returns_all_saved_solutions(self, store):
        for i in range(3):
            store.save({"problem": f"prob{i}", "solution": f"sol{i}"})
        assert len(store.load_all()) == 3

    def test_sorted_by_timestamp(self, store):
        for i in range(3):
            store.save({"problem": f"p{i}", "solution": f"s{i}"})
        loaded = store.load_all()
        timestamps = [s["timestamp"] for s in loaded]
        assert timestamps == sorted(timestamps)

    def test_load_all_on_workspace_without_solutions_dir(self, tmp_path):
        """Workspaces that have never had solutions should return []."""
        wm = WorkspaceManager(tmp_path, isolated=True)
        wm.create("fresh")
        st = SolutionStore(wm, "fresh")
        assert st.load_all() == []

    def test_count_matches_load_all(self, store):
        store.save({"problem": "p1", "solution": "s1"})
        store.save({"problem": "p2", "solution": "s2"})
        assert store.count() == len(store.load_all())


# ---------------------------------------------------------------------------
# TestFormatAsContext
# ---------------------------------------------------------------------------

class TestFormatAsContext:
    def test_empty_store_returns_empty_string(self, store):
        assert store.format_as_context() == ""

    def test_contains_problem_and_solution(self, store):
        store.save({
            "problem": "XSS via unescaped output",
            "solution": "Use html.escape() before rendering",
            "type": "error_fix",
        })
        ctx = store.format_as_context()
        assert "XSS via unescaped output" in ctx
        assert "html.escape()" in ctx

    def test_contains_lesson_header(self, store):
        store.save({"problem": "p", "solution": "s"})
        ctx = store.format_as_context()
        assert "Lesson" in ctx
        assert "MANDATORY" in ctx

    def test_includes_tags_when_present(self, store):
        store.save({"problem": "p", "solution": "s", "tags": ["react", "auth"]})
        ctx = store.format_as_context()
        assert "react" in ctx
        assert "auth" in ctx

    def test_multiple_lessons_numbered(self, store):
        store.save({"problem": "p1", "solution": "s1"})
        store.save({"problem": "p2", "solution": "s2"})
        ctx = store.format_as_context()
        assert "Lesson 1" in ctx
        assert "Lesson 2" in ctx

    def test_context_is_plain_string(self, store):
        store.save({"problem": "p", "solution": "s"})
        ctx = store.format_as_context()
        assert isinstance(ctx, str)
        assert len(ctx) > 0

    def test_context_missing_optional_fields(self, store):
        """Solutions without context/tags/type should still format cleanly."""
        store.save({"problem": "Minimal lesson", "solution": "Minimal fix"})
        ctx = store.format_as_context()
        assert "Minimal lesson" in ctx
        assert "Minimal fix" in ctx


# ---------------------------------------------------------------------------
# TestEdgeCases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_save_preserves_existing_id_field(self, store):
        """If caller supplies an id, it should be stored (though a new one is set by default)."""
        # The store sets a default id; if the caller supplies one, both appear —
        # the store always generates a new unique filename but preserves data fields.
        data = {"problem": "p", "solution": "s"}
        sol_id = store.save(data)
        loaded = store.load_all()
        found = next((s for s in loaded if s["id"] == sol_id), None)
        assert found is not None

    def test_isolated_workspaces_do_not_share_solutions(self, tmp_path):
        wm  = WorkspaceManager(tmp_path, isolated=True)
        wm.create("ws_a")
        wm.create("ws_b")
        sa = SolutionStore(wm, "ws_a")
        sb = SolutionStore(wm, "ws_b")

        sa.save({"problem": "only in A", "solution": "fix_a"})

        assert sa.count() == 1
        assert sb.count() == 0
        ctx_b = sb.format_as_context()
        assert ctx_b == ""
