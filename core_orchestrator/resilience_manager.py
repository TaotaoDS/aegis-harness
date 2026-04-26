"""Resilience manager: 3-layer escalation with Evaluator and knowledge capture.

Pipeline per task:
    Architect writes code → Evaluator runs sandbox checks
        → PASS → QA review → PASS → done (knowledge captured if retried)
        → FAIL → feedback to Architect → retry (up to max_retries)
        → FAIL after max_retries → escalate to human

Layer 1 (Context Reset):    1st fail → inject feedback, retry with same tool_llm
Layer 2 (Model Escalation): 2nd fail → switch to escalated tool_llm
Layer 3 (Graceful Degradation): final fail OR token budget >= 80% → stop, request human

max_retries is configurable via models_config.yaml `execution.max_retries`.
"""

import json
import logging
import threading
from typing import Dict, List, Optional

import tiktoken

from .architect_agent import ArchitectAgent, ToolLLM
from .context_compressor import compress_task_progress
from .evaluator import Evaluator, EvalResult
from .knowledge_manager import KnowledgeManager
from .llm_gateway import LLMGateway
from .parallel_executor import ParallelExecutor
from .qa_agent import QAAgent
from .workspace_manager import WorkspaceManager

logger = logging.getLogger(__name__)

_DEFAULT_MAX_RETRIES = 3
_DEFAULT_TOKEN_BUDGET = 100_000
_DEFAULT_TOKEN_THRESHOLD = 0.8
_DEFAULT_EVAL_TIMEOUT = 30
_DEFAULT_PARALLEL_WORKERS = 1   # sequential by default — backward-compatible

_encoding = tiktoken.get_encoding("cl100k_base")


def _count_tokens(text: str) -> int:
    return len(_encoding.encode(text))


class ResilienceManager:
    """Monitors Architect-QA loops with Evaluator verification and 3-layer escalation."""

    def __init__(
        self,
        workspace: WorkspaceManager,
        workspace_id: str,
        tool_llm: ToolLLM,
        qa_gateway: LLMGateway,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        token_budget: int = _DEFAULT_TOKEN_BUDGET,
        token_threshold: float = _DEFAULT_TOKEN_THRESHOLD,
        eval_timeout: int = _DEFAULT_EVAL_TIMEOUT,
        knowledge_manager: Optional[KnowledgeManager] = None,
        knowledge_context: str = "",
        solutions_context: str = "",
        bus=None,
        escalated_tool_llm: Optional[ToolLLM] = None,
        hitl_manager=None,
        parallel_workers: int = _DEFAULT_PARALLEL_WORKERS,
    ):
        from .event_bus import NullBus
        self._workspace = workspace
        self._ws_id = workspace_id
        self._tool_llm = tool_llm
        self._escalated_tool_llm = escalated_tool_llm or tool_llm
        self._qa_gateway = qa_gateway
        self._max_retries = max_retries
        self._token_budget = token_budget
        self._token_threshold = token_threshold
        self._eval_timeout = eval_timeout
        self._knowledge_manager = knowledge_manager
        self._knowledge_context = knowledge_context
        self._solutions_context = solutions_context  # workspace lessons forwarded to Architect
        self._bus = bus or NullBus()
        self._hitl_manager = hitl_manager   # Optional HITLManager forwarded to ArchitectAgent
        self._parallel_workers = max(1, int(parallel_workers))
        self._lock = threading.Lock()       # guards _token_usage and _results
        self._token_usage = 0
        self._results: List[Dict] = []
        self._failed_model: Optional[str] = None   # last model that hit a hard failure

    def _track_tokens(self, gateway: LLMGateway) -> None:
        """Accumulate token usage from a gateway's history (thread-safe)."""
        usage = sum(_count_tokens(entry) for entry in gateway.history)
        with self._lock:
            self._token_usage += usage

    def _budget_exceeded(self) -> bool:
        return self._token_usage >= self._token_budget * self._token_threshold

    def _write_escalation(self, task_id: str, attempts: int, last_issues: str) -> str:
        """Write an escalation file requesting human intervention."""
        path = f"escalations/{task_id}_escalation.md"
        content = (
            f"# Escalation: {task_id}\n\n"
            f"**Status:** Requires human intervention\n"
            f"**Attempts exhausted:** {attempts}\n"
            f"**Token usage:** {self._token_usage}\n\n"
            f"## Last Known Issues\n{last_issues}\n\n"
            f"## Action Required\n"
            f"The automated Architect-QA loop could not resolve this task.\n"
            f"Please review `artifacts/{task_id}_solution.md` (best effort) "
            f"and `feedback/{task_id}_feedback.md` (latest issues), "
            f"then provide manual guidance or resolution.\n"
        )
        self._workspace.write(self._ws_id, path, content)
        return path

    def _capture_knowledge(
        self, task_id: str, attempts: int, last_feedback: str
    ) -> None:
        """After a successful retry, extract lesson into knowledge base."""
        if self._knowledge_manager is None:
            return
        if attempts <= 1:
            # First-try pass — no lesson to learn
            return

        self._knowledge_manager.append_lesson(
            task_id=task_id,
            bug_root_cause=f"Failed {attempts - 1} time(s) before passing. Last feedback: {last_feedback[:500]}",
            fix_description=f"Resolved after {attempts} attempts with escalation.",
            avoidance_guide=f"Review feedback patterns from {task_id} before similar tasks.",
        )

    def run_task_loop(self, task_id: str) -> Dict:
        """Run the Architect → Evaluator → QA loop for a single task."""
        task_file = f"tasks/{task_id}.md"
        escalation_level = 0
        last_issues = ""

        evaluator = Evaluator(
            workspace=self._workspace,
            workspace_id=self._ws_id,
            timeout=self._eval_timeout,
            bus=self._bus,
        )

        for attempt in range(1, self._max_retries + 1):
            self._bus.emit(
                "resilience.attempt_start",
                task_id=task_id,
                attempt=f"{attempt}/{self._max_retries}",
                escalation_level=escalation_level,
            )

            # Check token budget before each attempt
            if self._budget_exceeded():
                self._bus.emit(
                    "resilience.budget_exceeded",
                    task_id=task_id,
                    token_usage=self._token_usage,
                    budget=self._token_budget,
                )
                self._write_escalation(task_id, attempt - 1, last_issues)
                result = {
                    "task_id": task_id, "verdict": "escalated",
                    "attempts": attempt - 1, "escalation_level": escalation_level,
                    "path": f"escalations/{task_id}_escalation.md",
                }
                with self._lock:
                    self._results.append(result)
                return result

            # Select tool_llm based on escalation level.
            # At level 2+ we try to use a model different from the one that failed.
            if escalation_level >= 2 and self._failed_model:
                # Ask the router to skip the failed model explicitly
                router = getattr(self._tool_llm, "_router", None)
                if router is not None and hasattr(router, "as_escalated_tool_llm"):
                    current_tool_llm = router.as_escalated_tool_llm(
                        skip_model=self._failed_model
                    )
                    logger.info(
                        "[Resilience] Layer-2 escalation: skipping failed model '%s'",
                        self._failed_model,
                    )
                else:
                    current_tool_llm = self._escalated_tool_llm
            elif escalation_level >= 2:
                current_tool_llm = self._escalated_tool_llm
            else:
                current_tool_llm = self._tool_llm

            self._bus.emit(
                "resilience.gateway_selected",
                task_id=task_id,
                escalation_level=escalation_level,
                is_escalated=(escalation_level >= 2),
            )

            # Architect generates solution via Tool Use (with knowledge context)
            architect = ArchitectAgent(
                tool_llm=current_tool_llm,
                workspace=self._workspace,
                workspace_id=self._ws_id,
                knowledge_context=self._knowledge_context,
                solutions_context=self._solutions_context,
                bus=self._bus,
                hitl_manager=self._hitl_manager,
            )
            try:
                architect.solve_task(task_file)
            except Exception as model_exc:
                # Model-level failure (not a task-level failure):
                # the LLM itself is unavailable (quota, auth, persistent timeout).
                # Compress what we know so far, write it as feedback, and let
                # the retry loop switch to a different provider.
                self._bus.emit(
                    "resilience.model_failure",
                    task_id=task_id,
                    attempt=attempt,
                    error=str(model_exc)[:200],
                )
                logger.warning(
                    "[Resilience] Model-level failure on task '%s' attempt %d: %s",
                    task_id, attempt, model_exc,
                )
                # Remember which model failed so escalation can explicitly skip it
                self._failed_model = str(getattr(model_exc, "_model_name", "unknown"))

                # Build compressed briefing for the next attempt
                completed_so_far = architect.get_written_files(task_id)
                try:
                    task_content = self._workspace.read(self._ws_id, task_file)
                except Exception:
                    task_content = task_id
                compressed = compress_task_progress(
                    task_content=task_content,
                    completed_files=completed_so_far,
                    error_summary=f"Model failure: {type(model_exc).__name__}: {model_exc}",
                    attempt=attempt,
                    failed_model=self._failed_model,
                )
                self._workspace.write(
                    self._ws_id,
                    f"feedback/{task_id}_feedback.md",
                    compressed,
                )
                last_issues = compressed
                escalation_level = min(escalation_level + 1, 2)
                continue   # retry with next model

            self._bus.emit("architect.solve_complete", task_id=task_id, attempt=attempt)

            # Evaluator: run sandbox checks on written files
            written_files = architect.get_written_files(task_id)

            # Zero-file guard: if Architect produced no code files at all,
            # immediately fail with clear feedback instead of sending to QA.
            if not written_files:
                self._bus.emit(
                    "evaluator.zero_files",
                    task_id=task_id,
                    attempt=f"{attempt}/{self._max_retries}",
                )
                zero_feedback = (
                    f"# Evaluator Feedback: {task_id}\n\n"
                    f"**Verdict:** FAIL (zero files produced)\n\n"
                    f"## Error\n"
                    f"Architect produced 0 code files. The write_file tool "
                    f"was not called -- no file writes were found "
                    f"in the LLM tool call output.\n\n"
                    f"You MUST call write_file(filepath, content) for every "
                    f"code file you produce.\n\n"
                    f"---\n*Resubmit with actual code files.*\n"
                )
                self._workspace.write(
                    self._ws_id,
                    f"feedback/{task_id}_feedback.md",
                    zero_feedback,
                )
                last_issues = zero_feedback
                if attempt == 1:
                    escalation_level = 1
                elif attempt == 2:
                    escalation_level = 2
                continue  # Retry without sending to QA

            eval_result = evaluator.run_eval(written_files)
            if not eval_result.success:
                self._bus.emit(
                    "evaluator.fail",
                    task_id=task_id,
                    attempt=f"{attempt}/{self._max_retries}",
                    error=eval_result.error_summary()[:200],
                )
                # Eval failed — write feedback and retry
                error_feedback = (
                    f"# Evaluator Feedback: {task_id}\n\n"
                    f"**Verdict:** FAIL (automated verification)\n\n"
                    f"## Errors\n```\n{eval_result.error_summary()}\n```\n\n"
                    f"---\n*Fix ALL errors above and resubmit.*\n"
                )
                self._workspace.write(
                    self._ws_id,
                    f"feedback/{task_id}_feedback.md",
                    error_feedback,
                )
                last_issues = error_feedback

                # Escalate
                if attempt == 1:
                    escalation_level = 1
                elif attempt == 2:
                    escalation_level = 2
                continue  # Skip QA, go straight to retry

            # QA reviews (eval passed)
            self._bus.emit("evaluator.pass", task_id=task_id, file_count=len(written_files))
            qa = QAAgent(
                gateway=self._qa_gateway,
                workspace=self._workspace,
                workspace_id=self._ws_id,
                bus=self._bus,
            )
            review = qa.review_task(task_id)
            self._track_tokens(self._qa_gateway)

            if review["verdict"] == "pass":
                self._bus.emit(
                    "qa.pass",
                    task_id=task_id,
                    attempt=attempt,
                    escalation_level=escalation_level,
                )
                self._capture_knowledge(task_id, attempt, last_issues)
                result = {
                    "task_id": task_id, "verdict": "pass",
                    "attempts": attempt, "escalation_level": escalation_level,
                    "path": review["path"],
                }
                with self._lock:
                    self._results.append(result)
                return result

            # QA failed — escalate
            self._bus.emit("qa.fail", task_id=task_id, attempt=f"{attempt}/{self._max_retries}")
            last_feedback = ""
            fb_path = f"feedback/{task_id}_feedback.md"
            if self._workspace.exists(self._ws_id, fb_path):
                last_feedback = self._workspace.read(self._ws_id, fb_path)
            last_issues = last_feedback

            if attempt == 1:
                escalation_level = 1
            elif attempt == 2:
                escalation_level = 2

        # Layer 3: All retries exhausted
        self._bus.emit(
            "resilience.escalated",
            task_id=task_id,
            attempts=self._max_retries,
            escalation_level=3,
        )
        self._write_escalation(task_id, self._max_retries, last_issues)
        result = {
            "task_id": task_id, "verdict": "escalated",
            "attempts": self._max_retries, "escalation_level": 3,
            "path": f"escalations/{task_id}_escalation.md",
        }
        self._results.append(result)
        return result

    def _read_depends_on(self, task_id: str) -> List[str]:
        """Parse the ``Depends on:`` field from a task file.

        Task files written by :meth:`CEOAgent.delegate` may contain a line::

            - **Depends on:** task_1, task_2

        Returns a list of dependency task IDs, or an empty list when the
        field is absent.
        """
        task_file = f"tasks/{task_id}.md"
        try:
            content = self._workspace.read(self._ws_id, task_file)
        except Exception:
            return []
        for line in content.split("\n"):
            stripped = line.strip().lower()
            if stripped.startswith("- **depends on:**"):
                raw = line.split(":", 1)[-1].strip()
                return [t.strip() for t in raw.split(",") if t.strip()]
        return []

    def run_all(self) -> List[Dict]:
        """Run the resilience loop for every task, honouring ``depends_on``.

        Tasks are grouped into parallel *waves* by :func:`wave_schedule`:
        tasks within the same wave have no unsatisfied dependencies and can
        run concurrently.  ``parallel_workers=1`` (the default) keeps the
        original sequential behaviour for backward compatibility.
        """
        all_files = self._workspace.list_files(self._ws_id)
        task_ids = sorted(
            f.removeprefix("tasks/").removesuffix(".md")
            for f in all_files
            if f.startswith("tasks/") and f.endswith(".md")
        )
        self._bus.emit("pipeline.execution_start", task_count=len(task_ids))

        # Build dependency map from task file contents
        depends_on: Dict[str, List[str]] = {
            tid: self._read_depends_on(tid) for tid in task_ids
        }

        executor = ParallelExecutor(workers=self._parallel_workers)
        results_map = executor.run(self.run_task_loop, depends_on)

        # Return results in the original sorted task order
        results = [results_map[tid] for tid in task_ids]

        passed   = sum(1 for r in results if r["verdict"] == "pass")
        escalated = sum(1 for r in results if r["verdict"] == "escalated")
        self._bus.emit(
            "pipeline.execution_complete",
            passed=passed,
            escalated=escalated,
            token_usage=self._token_usage,
        )
        return results

    def status(self) -> Dict:
        """Return overall status of all managed tasks."""
        completed = [r["task_id"] for r in self._results if r["verdict"] == "pass"]
        escalated = [r["task_id"] for r in self._results if r["verdict"] == "escalated"]
        return {
            "completed": completed,
            "escalated": escalated,
            "token_usage": self._token_usage,
        }
