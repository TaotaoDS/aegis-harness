"""Wave-based parallel task executor.

Reads the optional ``depends_on`` list from a dependency map to build a DAG,
then groups independent tasks into "waves" that can run concurrently.

Public API
----------
wave_schedule(depends_on)
    Topological sort (Kahn's algorithm) → list of parallel waves.

ParallelExecutor
    Executes task waves with a ``ThreadPoolExecutor``.

Example
-------
    depends_on = {
        "task_1": [],
        "task_2": ["task_1"],
        "task_3": ["task_1"],
        "task_4": ["task_2", "task_3"],
    }
    waves = wave_schedule(depends_on)
    # [["task_1"], ["task_2", "task_3"], ["task_4"]]

    executor = ParallelExecutor(workers=4)
    results = executor.run(my_fn, depends_on)
    # {"task_1": ..., "task_2": ..., "task_3": ..., "task_4": ...}
"""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable, Dict, List


# ---------------------------------------------------------------------------
# Wave scheduler
# ---------------------------------------------------------------------------

def wave_schedule(depends_on: Dict[str, List[str]]) -> List[List[str]]:
    """Group task IDs into parallel execution waves.

    Uses Kahn's BFS algorithm for topological sorting.  Tasks in the same
    wave have all their declared dependencies satisfied by preceding waves
    and can therefore run concurrently.

    Parameters
    ----------
    depends_on:
        Mapping ``{task_id: [dep_task_id, ...]}``.
        Tasks that appear only as dependencies (not as keys) are included
        automatically with an empty dependency list.

    Returns
    -------
    List of waves; each wave is a **sorted** list of task IDs.

    Raises
    ------
    ValueError
        If the dependency graph contains a cycle.
    """
    # Collect all nodes: keys + everything referenced as a dependency
    all_tasks: set[str] = set(depends_on.keys())
    for deps in depends_on.values():
        all_tasks.update(deps)

    # Build in-degree and reverse-adjacency (dependents) maps
    in_degree: Dict[str, int]       = {t: 0 for t in all_tasks}
    dependents: Dict[str, List[str]] = {t: [] for t in all_tasks}

    for task, deps in depends_on.items():
        seen_deps: set[str] = set()
        for dep in deps:
            if dep in seen_deps:
                continue          # ignore duplicate dependency declarations
            seen_deps.add(dep)
            in_degree[task] += 1
            dependents[dep].append(task)

    # BFS over zero-in-degree nodes
    waves: List[List[str]] = []
    current_wave: List[str] = sorted(t for t in all_tasks if in_degree[t] == 0)

    while current_wave:
        waves.append(current_wave)
        next_wave: List[str] = []
        for completed in current_wave:
            for dependent in dependents[completed]:
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    next_wave.append(dependent)
        current_wave = sorted(next_wave)

    scheduled = sum(len(w) for w in waves)
    if scheduled < len(all_tasks):
        unscheduled = all_tasks - {t for wave in waves for t in wave}
        raise ValueError(
            f"Circular dependency detected among tasks: {sorted(unscheduled)}"
        )

    return waves


# ---------------------------------------------------------------------------
# Parallel executor
# ---------------------------------------------------------------------------

class ParallelExecutor:
    """Execute tasks in dependency order, parallelising independent waves.

    Each wave of independent tasks is submitted to a ``ThreadPoolExecutor``
    simultaneously.  The executor waits for all tasks in a wave to complete
    before starting the next wave, preserving the dependency ordering.

    Parameters
    ----------
    workers:
        Maximum number of concurrent threads.  ``workers=1`` is functionally
        identical to sequential execution (safe default for non-thread-safe
        task functions).
    """

    def __init__(self, workers: int = 1) -> None:
        self._workers = max(1, int(workers))

    @property
    def workers(self) -> int:
        return self._workers

    def run(
        self,
        task_fn: Callable[[str], Any],
        depends_on: Dict[str, List[str]],
    ) -> Dict[str, Any]:
        """Execute *task_fn(task_id)* for every task in *depends_on*.

        Parameters
        ----------
        task_fn:
            Callable that accepts a single ``task_id: str`` argument and
            returns a result.  Must be thread-safe when ``workers > 1``.
        depends_on:
            Dependency map ``{task_id: [dep_id, ...]}``.

        Returns
        -------
        ``{task_id: result}`` mapping for all tasks, in the order they
        were scheduled (wave-by-wave, tasks within each wave sorted).

        Raises
        ------
        The first exception raised by any task; the remaining futures in
        that wave are still awaited before the exception propagates.
        """
        waves = wave_schedule(depends_on)
        results: Dict[str, Any] = {}
        first_exc: BaseException | None = None

        with ThreadPoolExecutor(max_workers=self._workers) as pool:
            for wave in waves:
                futures: Dict[str, Future] = {
                    tid: pool.submit(task_fn, tid) for tid in wave
                }
                for tid in wave:
                    try:
                        results[tid] = futures[tid].result()
                    except Exception as exc:  # noqa: BLE001
                        if first_exc is None:
                            first_exc = exc

        if first_exc is not None:
            raise first_exc

        return results
