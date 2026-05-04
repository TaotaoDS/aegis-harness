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
- Enhanced compound knowledge: extracts symptoms, failed_attempts, root_cause
  for richer searchability in future retrievals.
"""

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from .json_parser import parse_llm_json
from .llm_gateway import LLMGateway
from .solution_store import SolutionStore
from .workspace_manager import WorkspaceManager

_GLOBAL_SOLUTIONS_DIR = Path(__file__).parent.parent / "docs" / "solutions"
_SKILLS_DIR           = Path(__file__).parent.parent / "skills"
_MANIFEST_PATH        = _SKILLS_DIR / "manifest.yaml"

# Mapping from lesson tags to skill category directories
_TAG_TO_CATEGORY: Dict[str, str] = {
    "python":     "python",
    "fastapi":    "python",
    "flask":      "python",
    "django":     "python",
    "javascript": "frontend",
    "typescript": "frontend",
    "react":      "frontend",
    "vue":        "frontend",
    "css":        "frontend",
    "html":       "frontend",
    "docker":     "devops",
    "kubernetes": "devops",
    "nginx":      "devops",
    "ci":         "devops",
    "database":    "database",
    "sql":         "database",
    "postgres":    "database",
    "mysql":       "database",
    "redis":       "database",
    "architecture": "architecture",
    "fusion":       "architecture",
    "design":       "architecture",
    "pattern":      "architecture",
    "microservice": "architecture",
    "monolith":     "architecture",
}


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
    "symptoms": "Observable indicators that this issue is occurring (≤ 150 chars)",
    "failed_attempts": "Approaches tried that did NOT work (≤ 200 chars)",
    "solution": "What fixed it / should be done instead (≤ 200 chars)",
    "root_cause": "Why the problem occurred at a fundamental level (≤ 150 chars)",
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

    @staticmethod
    def _persist_global(sol_id: str, lesson: Dict[str, Any]) -> None:
        """Persist lesson to docs/solutions/ for cross-workspace retrieval."""
        try:
            _GLOBAL_SOLUTIONS_DIR.mkdir(parents=True, exist_ok=True)
            filepath = _GLOBAL_SOLUTIONS_DIR / f"{sol_id}.yaml"
            with open(filepath, "w", encoding="utf-8") as f:
                yaml.safe_dump(lesson, f, allow_unicode=True, default_flow_style=False)
        except Exception:
            pass

    @staticmethod
    def _slug(text: str, max_len: int = 40) -> str:
        """Convert free text to a URL-safe slug."""
        text = text.lower()
        text = re.sub(r"[^a-z0-9]+", "-", text)
        text = text.strip("-")
        return text[:max_len].rstrip("-")

    @staticmethod
    def _infer_category(tags: List[str]) -> str:
        """Map lesson tags → skill category directory name."""
        for tag in [t.lower() for t in tags]:
            if tag in _TAG_TO_CATEGORY:
                return _TAG_TO_CATEGORY[tag]
        return "general"

    @staticmethod
    def _should_promote(lesson: Dict[str, Any]) -> bool:
        """Return True when this lesson has enough info to become a reusable skill."""
        ltype    = lesson.get("type", "")
        symptoms = lesson.get("symptoms", "")
        failed   = lesson.get("failed_attempts", "")
        solution = lesson.get("solution", "")

        if ltype == "error_fix" and symptoms and failed:
            return True
        if ltype == "architectural_decision" and len(solution) >= 80:
            return True
        return False

    @staticmethod
    def _update_manifest(skill_id: str, entry: Dict[str, Any]) -> None:
        """Append a new entry to skills/manifest.yaml (idempotent by id)."""
        try:
            _MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)

            # Load existing
            existing: Dict[str, Any] = {"skills": []}
            if _MANIFEST_PATH.exists():
                with open(_MANIFEST_PATH, encoding="utf-8") as f:
                    existing = yaml.safe_load(f) or {"skills": []}

            skills: List[Dict[str, Any]] = existing.get("skills", [])

            # Idempotent: skip if already registered
            if any(s.get("id") == skill_id for s in skills):
                return

            skills.append(entry)
            existing["skills"] = skills

            with open(_MANIFEST_PATH, "w", encoding="utf-8") as f:
                yaml.safe_dump(existing, f, allow_unicode=True, default_flow_style=False)
        except Exception:
            pass

    @staticmethod
    def _maybe_promote_to_skill(sol_id: str, lesson: Dict[str, Any]) -> None:
        """Conditionally promote a lesson to a reusable Markdown skill file."""
        if not ReflectionAgent._should_promote(lesson):
            return

        try:
            tags     = lesson.get("tags", [])
            category = ReflectionAgent._infer_category(tags)
            problem  = lesson.get("problem", sol_id)
            skill_id = ReflectionAgent._slug(problem)

            if not skill_id:
                skill_id = sol_id

            # Build skill Markdown
            ltype    = lesson.get("type", "")
            symptoms = lesson.get("symptoms", "")
            failed   = lesson.get("failed_attempts", "")
            solution = lesson.get("solution", "")
            root     = lesson.get("root_cause", "")
            context  = lesson.get("context", "")
            tags_str = ", ".join(tags) if tags else ""

            front_matter = yaml.dump(
                {
                    "id":       skill_id,
                    "category": category,
                    "triggers": [t.lower() for t in tags] or [skill_id],
                    "version":  1,
                    "source_solution": sol_id,
                    "type": ltype,
                },
                default_flow_style=False,
            ).strip()

            md_lines = [
                "---",
                front_matter,
                "---",
                "",
                f"## Problem",
                problem,
                "",
            ]
            if symptoms:
                md_lines += [f"## Symptoms", symptoms, ""]
            if failed:
                md_lines += [f"## Failed Approaches", failed, ""]
            md_lines += [f"## Solution", solution, ""]
            if root:
                md_lines += [f"## Root Cause", root, ""]
            if context:
                md_lines += [f"## Context", context, ""]
            if tags_str:
                md_lines += [f"## Tags", tags_str, ""]

            skill_md = "\n".join(md_lines)

            # Write skill file
            cat_dir = _SKILLS_DIR / category
            cat_dir.mkdir(parents=True, exist_ok=True)
            skill_file = cat_dir / f"{skill_id}.md"
            skill_file.write_text(skill_md, encoding="utf-8")

            # Update manifest
            relative_path = str(skill_file.relative_to(_SKILLS_DIR.parent))
            manifest_entry: Dict[str, Any] = {
                "id":              skill_id,
                "name":            problem[:60],
                "category":        category,
                "triggers":        [t.lower() for t in tags] or [skill_id],
                "file":            relative_path,
                "created_from":    "reflection",
                "source_solution": sol_id,
                "version":         1,
            }
            ReflectionAgent._update_manifest(skill_id, manifest_entry)

        except Exception:
            pass  # Promotion is best-effort; never crash the pipeline

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

            # Also persist to global docs/solutions/ for cross-workspace retrieval
            self._persist_global(sol_id, lesson)

            # Conditionally promote high-value lessons to reusable Skill Markdown
            self._maybe_promote_to_skill(sol_id, lesson)

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
