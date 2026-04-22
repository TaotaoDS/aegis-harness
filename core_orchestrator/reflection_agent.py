"""Reflection Agent — post-execution knowledge distillation.

Runs after each pipeline (build or update) completes or fails.
Reads the event log, synthesises key lessons learned, and persists
them via SolutionStore.

This is the engine of the Compound Engineering flywheel:
    execute → reflect → store → inject into next run → execute better

Design notes:
- Failures are MORE valuable than successes — always reflect both.
- The agent is stateless: one call to reflect() per pipeline run.
- The LLM response is expected to be strict JSON (no fences).
- Gracefully returns 0 on any LLM / parse failure (never crashes pipeline).
"""

from typing import Any, Dict, List, Optional

from .json_parser import parse_llm_json
from .llm_gateway import LLMGateway
from .solution_store import SolutionStore
from .workspace_manager import WorkspaceManager


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_REFLECT_SYSTEM = """\
You are an experienced software engineering post-mortem analyst.
Your job is to analyze an AI agent pipeline execution log and extract
concise, actionable lessons that will prevent future failures and
reinforce successful patterns.

## Execution Summary

Original requirement:
{requirement}

Event log (newest events are most relevant):
{event_log}

## Instructions

Extract 1–5 lessons from this execution. Focus on:
1. Errors that occurred and how they were fixed
2. Architectural / design decisions that proved correct or incorrect
3. Patterns that caused retries or escalation (and how they were resolved)
4. Best practices that emerged from this specific project

For each lesson choose one type:
  "error_fix"              — an error happened and was fixed
  "architectural_decision" — a key design choice was made (good or bad)
  "best_practice"          — a technique/pattern that worked well

Respond in strict JSON (no markdown fences):
{{"lessons": [
  {{
    "type": "error_fix",
    "problem": "Short description of what went wrong (≤ 120 chars)",
    "solution": "What fixed it / should be done instead (≤ 200 chars)",
    "context": "Relevant code/config/tool detail — optional (≤ 150 chars)",
    "tags": ["python", "auth"]
  }}
]}}

Quality rules:
- Be SPECIFIC and ACTIONABLE, not vague.
  BAD:  "always validate input"
  GOOD: "FastAPI form data requires Form() not Body() for non-JSON endpoints"
- If the pipeline ran flawlessly with no retries, extract best-practice lessons only.
- Omit lessons where you're not confident (partial information).
- Return {{"lessons": []}} if nothing noteworthy happened.
- All output MUST be in English.
"""


# ---------------------------------------------------------------------------
# Event log formatter
# ---------------------------------------------------------------------------

def _format_event_log(
    events_log: List[Dict[str, Any]],
    max_chars: int = 4_000,
) -> str:
    """Convert raw event list to a compact, readable text for the LLM."""
    lines: List[str] = []
    for e in events_log:
        label   = e.get("label") or e.get("type", "")
        data    = e.get("data", {})
        ts      = str(e.get("timestamp", ""))[:19]  # drop sub-second

        # Attach the most diagnostic data fields inline
        extras = ""
        for key in ("error", "filepath", "task_id", "feedback",
                    "attempt", "verdict", "problem"):
            if key in data:
                val = str(data[key])[:80]
                extras += f" [{key}={val}]"

        lines.append(f"{ts}  {label}{extras}")

    text = "\n".join(lines)

    # Truncate to fit LLM context — keep the most recent events
    if len(text) > max_chars:
        text = text[-max_chars:]
        newline_pos = text.find("\n")
        if newline_pos > 0:
            text = text[newline_pos + 1:]
        text = "…(earlier events truncated)\n" + text

    return text or "(empty event log)"


# ---------------------------------------------------------------------------
# Reflection Agent
# ---------------------------------------------------------------------------

class ReflectionAgent:
    """Analyses execution events and saves structured lessons to SolutionStore."""

    def __init__(
        self,
        gateway: LLMGateway,
        workspace: WorkspaceManager,
        workspace_id: str,
    ) -> None:
        self._gateway = gateway
        self._store   = SolutionStore(workspace, workspace_id)

    def reflect(
        self,
        events_log: List[Dict[str, Any]],
        requirement: str,
        job_id: Optional[str] = None,
        bus: Any = None,
    ) -> int:
        """Analyse events, extract lessons, save to solutions/.

        Args:
            events_log:  Raw event list from AsyncQueueBus.events_log
                         or EventBus.events.
            requirement: The original user requirement (gives the LLM
                         the "why" behind the execution).
            job_id:      Optional — stamped into each saved solution.
            bus:         Optional event bus for emitting progress events.

        Returns:
            Number of solutions successfully saved (0 on any failure).
        """
        if bus:
            bus.emit("reflection.start")

        try:
            return self._do_reflect(events_log, requirement, job_id, bus)
        except Exception:
            # Reflection must never crash the caller
            if bus:
                bus.emit("reflection.complete", saved=0)
            return 0

    def _do_reflect(
        self,
        events_log: List[Dict[str, Any]],
        requirement: str,
        job_id: Optional[str],
        bus: Any,
    ) -> int:
        event_log_text = _format_event_log(events_log)

        prompt = _REFLECT_SYSTEM.format(
            requirement=requirement,
            event_log=event_log_text,
        )

        result = self._gateway.send(prompt)
        parsed = parse_llm_json(
            result["llm_response"],
            fallback={"lessons": []},
        )

        lessons: List[Dict[str, Any]] = parsed.get("lessons", [])
        saved = 0

        for lesson in lessons:
            if not isinstance(lesson, dict):
                continue
            # Require at minimum a non-empty problem AND solution
            if not lesson.get("problem") or not lesson.get("solution"):
                continue

            if job_id:
                lesson["job_id"] = job_id

            sol_id = self._store.save(lesson)
            saved += 1

            if bus:
                bus.emit(
                    "reflection.solution_saved",
                    sol_id=sol_id,
                    type=lesson.get("type", "unknown"),
                    problem=lesson.get("problem", ""),
                )

        if bus:
            bus.emit("reflection.complete", saved=saved)

        return saved
