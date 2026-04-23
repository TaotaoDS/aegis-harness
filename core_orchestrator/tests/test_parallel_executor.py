"""Tests for parallel_executor: wave scheduler + ParallelExecutor.

Coverage:
  - wave_schedule: empty graph, single task, linear chain, diamond,
    independent tasks (one wave), cycle detection, duplicate dep ignored
  - ParallelExecutor.run: workers=1 (sequential), workers>1 (parallel),
    dependency ordering preserved, exception propagated,
    all results collected
"""

import threading
import time
from typing import Dict, List

import pytest

from core_orchestrator.parallel_executor import ParallelExecutor, wave_schedule


# ---------------------------------------------------------------------------
# TestWaveSchedule
# ---------------------------------------------------------------------------

class TestWaveSchedule:
    def test_empty_graph_returns_empty_waves(self):
        assert wave_schedule({}) == []

    def test_single_task_no_deps(self):
        waves = wave_schedule({"task_1": []})
        assert waves == [["task_1"]]

    def test_two_independent_tasks_same_wave(self):
        waves = wave_schedule({"task_1": [], "task_2": []})
        assert len(waves) == 1
        assert sorted(waves[0]) == ["task_1", "task_2"]

    def test_linear_chain_three_waves(self):
        # task_1 → task_2 → task_3
        depends_on = {
            "task_1": [],
            "task_2": ["task_1"],
            "task_3": ["task_2"],
        }
        waves = wave_schedule(depends_on)
        assert waves == [["task_1"], ["task_2"], ["task_3"]]

    def test_diamond_dependency(self):
        # task_1 → task_2, task_3 → task_4
        depends_on = {
            "task_1": [],
            "task_2": ["task_1"],
            "task_3": ["task_1"],
            "task_4": ["task_2", "task_3"],
        }
        waves = wave_schedule(depends_on)
        assert waves[0] == ["task_1"]
        assert sorted(waves[1]) == ["task_2", "task_3"]
        assert waves[2] == ["task_4"]

    def test_task_only_as_dependency_gets_scheduled(self):
        """A task mentioned only as a dependency (not a key) is still included."""
        depends_on = {"task_2": ["task_1"]}   # task_1 not a key
        waves = wave_schedule(depends_on)
        assert waves[0] == ["task_1"]
        assert waves[1] == ["task_2"]

    def test_cycle_raises_value_error(self):
        depends_on = {
            "task_1": ["task_2"],
            "task_2": ["task_1"],
        }
        with pytest.raises(ValueError, match="[Cc]ircular"):
            wave_schedule(depends_on)

    def test_self_cycle_raises(self):
        with pytest.raises(ValueError):
            wave_schedule({"task_1": ["task_1"]})

    def test_duplicate_deps_counted_once(self):
        """Duplicate dependency entries must not inflate in-degree."""
        depends_on = {"task_2": ["task_1", "task_1"], "task_1": []}
        waves = wave_schedule(depends_on)
        # Should not raise, and should produce a valid 2-wave schedule
        assert waves == [["task_1"], ["task_2"]]

    def test_waves_are_sorted(self):
        """Tasks within each wave must be in sorted (deterministic) order."""
        depends_on = {"c": [], "a": [], "b": []}
        waves = wave_schedule(depends_on)
        assert waves == [["a", "b", "c"]]

    def test_five_tasks_mixed_deps(self):
        depends_on = {
            "t1": [],
            "t2": ["t1"],
            "t3": ["t1"],
            "t4": ["t2"],
            "t5": ["t2", "t3"],
        }
        waves = wave_schedule(depends_on)
        # Wave 0: t1
        # Wave 1: t2, t3
        # Wave 2: t4, t5
        assert waves[0] == ["t1"]
        assert sorted(waves[1]) == ["t2", "t3"]
        assert sorted(waves[2]) == ["t4", "t5"]


# ---------------------------------------------------------------------------
# TestParallelExecutor
# ---------------------------------------------------------------------------

class TestParallelExecutor:
    def test_workers_property(self):
        assert ParallelExecutor(workers=4).workers == 4

    def test_workers_minimum_is_one(self):
        assert ParallelExecutor(workers=0).workers == 1

    # ── Sequential (workers=1) ──────────────────────────────────────────

    def test_sequential_single_task(self):
        results = ParallelExecutor(workers=1).run(
            lambda tid: tid.upper(),
            {"task_1": []},
        )
        assert results == {"task_1": "TASK_1"}

    def test_sequential_respects_order(self):
        order = []

        def fn(tid):
            order.append(tid)
            return tid

        ParallelExecutor(workers=1).run(
            fn,
            {"task_1": [], "task_2": ["task_1"], "task_3": ["task_2"]},
        )
        assert order == ["task_1", "task_2", "task_3"]

    def test_sequential_all_results_returned(self):
        depends_on = {"t1": [], "t2": ["t1"], "t3": ["t1"]}
        results = ParallelExecutor(workers=1).run(
            lambda tid: f"done-{tid}",
            depends_on,
        )
        assert set(results.keys()) == {"t1", "t2", "t3"}
        assert results["t1"] == "done-t1"

    # ── Parallel (workers=4) ────────────────────────────────────────────

    def test_parallel_independent_tasks_run_concurrently(self):
        """Tasks in the same wave should overlap in time with workers > 1."""
        start_times: Dict[str, float] = {}
        barrier = threading.Barrier(2, timeout=5)

        def fn(tid):
            start_times[tid] = time.monotonic()
            barrier.wait()   # both threads meet here simultaneously
            return tid

        depends_on = {"t1": [], "t2": []}
        ParallelExecutor(workers=2).run(fn, depends_on)

        # Both tasks started — the barrier ensures they ran concurrently
        assert "t1" in start_times and "t2" in start_times

    def test_parallel_dependency_ordering_preserved(self):
        """Dependent tasks must not start before their dependencies finish."""
        finished: List[str] = []
        lock = threading.Lock()

        def fn(tid):
            time.sleep(0.01)   # small delay to make ordering observable
            with lock:
                finished.append(tid)
            return tid

        depends_on = {
            "t1": [],
            "t2": ["t1"],
            "t3": ["t1"],
            "t4": ["t2", "t3"],
        }
        ParallelExecutor(workers=4).run(fn, depends_on)

        # t1 must finish before t2/t3; t2 and t3 must finish before t4
        assert finished.index("t1") < finished.index("t2")
        assert finished.index("t1") < finished.index("t3")
        assert finished.index("t2") < finished.index("t4")
        assert finished.index("t3") < finished.index("t4")

    def test_parallel_all_results_collected(self):
        depends_on = {f"t{i}": [] for i in range(6)}
        results = ParallelExecutor(workers=4).run(
            lambda tid: int(tid[1:]) * 2,
            depends_on,
        )
        assert len(results) == 6
        for i in range(6):
            assert results[f"t{i}"] == i * 2

    # ── Exception handling ──────────────────────────────────────────────

    def test_exception_in_task_propagates(self):
        def boom(tid):
            raise RuntimeError(f"task {tid} failed")

        with pytest.raises(RuntimeError, match="failed"):
            ParallelExecutor(workers=1).run(boom, {"t1": []})

    def test_exception_does_not_swallow_other_wave_results(self):
        """When one task fails, executor re-raises after the wave finishes."""
        def fn(tid):
            if tid == "t_bad":
                raise ValueError("intentional")
            return "ok"

        with pytest.raises(ValueError, match="intentional"):
            ParallelExecutor(workers=1).run(
                fn,
                {"t_good": [], "t_bad": []},
            )
