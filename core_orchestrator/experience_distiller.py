"""Experience Distiller — automatic post-task knowledge internalization.

Enhances the existing ReflectionAgent with:
  1. Parallel sub-agent extraction (symptoms, failed attempts, root cause, solution)
  2. Cross-workspace federation via a global index
  3. Deduplication of semantically similar lessons
  4. Smart pre-retrieval: hybrid keyword + semantic search for task planning

This is the engine of the Compound Engineering flywheel:
    execute → distill → index → retrieve → plan better → execute → ...

Usage:
    distiller = ExperienceDistiller(gateway, workspace, workspace_id)

    # After task completion:
    distiller.distill(events_log, requirement, job_id, bus)

    # Before task planning:
    context = distiller.retrieve_relevant(task_description, top_k=5)
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from .json_parser import parse_llm_json
from .llm_gateway import LLMGateway
from .reflection_agent import ReflectionAgent
from .solution_store import SolutionStore
from .workspace_manager import WorkspaceManager

logger = logging.getLogger(__name__)

_GLOBAL_SOLUTIONS_DIR = Path(__file__).parent.parent / "docs" / "solutions"
_INDEX_PATH = _GLOBAL_SOLUTIONS_DIR / "_index.yaml"


# ---------------------------------------------------------------------------
# Sub-agent prompts (run in parallel for speed)
# ---------------------------------------------------------------------------

_SYMPTOM_PROMPT = """\
Analyze this execution log and extract observable SYMPTOMS — what a developer
would see that indicates something went wrong (error messages, unexpected
behavior, performance degradation, test failures).

Event log:
{event_log}

Respond in strict JSON:
{{"symptoms": ["symptom 1 (≤100 chars)", "symptom 2", ...]}}
Return {{"symptoms": []}} if the execution was clean.
"""

_FAILURE_PROMPT = """\
Analyze this execution log and extract FAILED ATTEMPTS — approaches that were
tried but did NOT work, including why they failed. These are valuable for
future agents to avoid repeating the same mistakes.

Event log:
{event_log}

Respond in strict JSON:
{{"failed_attempts": [
  {{"approach": "what was tried (≤120 chars)", "why_failed": "reason (≤100 chars)"}}
]}}
Return {{"failed_attempts": []}} if no retries/failures occurred.
"""

_ROOT_CAUSE_PROMPT = """\
Analyze this execution log and identify ROOT CAUSES — the fundamental reasons
why problems occurred, not just surface-level symptoms.

Original requirement: {requirement}

Event log:
{event_log}

Respond in strict JSON:
{{"root_causes": [
  {{"cause": "fundamental reason (≤150 chars)", "category": "config|code|design|dependency|environment|data"}}
]}}
Return {{"root_causes": []}} if execution was clean.
"""


# ---------------------------------------------------------------------------
# Global Experience Index
# ---------------------------------------------------------------------------

class ExperienceIndex:
    """Federated cross-workspace index of all distilled experiences.

    Maintains a lightweight YAML index at docs/solutions/_index.yaml for
    fast lookup without scanning every solution file. Supports deduplication
    via content hashing.
    """

    def __init__(self) -> None:
        _GLOBAL_SOLUTIONS_DIR.mkdir(parents=True, exist_ok=True)

    def load(self) -> Dict[str, Any]:
        if _INDEX_PATH.exists():
            try:
                with open(_INDEX_PATH, encoding="utf-8") as f:
                    return yaml.safe_load(f) or {"entries": [], "hashes": []}
            except Exception:
                pass
        return {"entries": [], "hashes": []}

    def save(self, index: Dict[str, Any]) -> None:
        try:
            with open(_INDEX_PATH, "w", encoding="utf-8") as f:
                yaml.safe_dump(index, f, allow_unicode=True, default_flow_style=False)
        except Exception:
            logger.warning("Failed to save experience index")

    @staticmethod
    def content_hash(problem: str, solution: str) -> str:
        """Generate a short hash for deduplication."""
        normalized = f"{problem.strip().lower()}|{solution.strip().lower()}"
        return hashlib.sha256(normalized.encode()).hexdigest()[:16]

    def is_duplicate(self, problem: str, solution: str) -> bool:
        index = self.load()
        h = self.content_hash(problem, solution)
        return h in index.get("hashes", [])

    def add_entry(
        self,
        sol_id: str,
        lesson: Dict[str, Any],
        workspace_id: str = "",
    ) -> bool:
        """Add a lesson to the index. Returns False if duplicate."""
        problem = lesson.get("problem", "")
        solution = lesson.get("solution", "")
        h = self.content_hash(problem, solution)

        index = self.load()
        if h in index.get("hashes", []):
            return False

        index.setdefault("entries", []).append({
            "id": sol_id,
            "type": lesson.get("type", "best_practice"),
            "problem": problem[:120],
            "tags": lesson.get("tags", []),
            "category": lesson.get("category", "general"),
            "workspace": workspace_id,
            "timestamp": lesson.get("timestamp", datetime.now(timezone.utc).isoformat()),
            "hash": h,
        })
        index.setdefault("hashes", []).append(h)

        self.save(index)
        return True

    def search_by_tags(self, tags: List[str], top_k: int = 10) -> List[Dict]:
        """Fast tag-based search over the index (no LLM needed)."""
        index = self.load()
        tag_set = {t.lower() for t in tags}
        scored = []
        for entry in index.get("entries", []):
            overlap = len(tag_set & {t.lower() for t in entry.get("tags", [])})
            if overlap > 0:
                scored.append((overlap, entry))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [e for _, e in scored[:top_k]]

    def search_by_keyword(self, query: str, top_k: int = 10) -> List[Dict]:
        """Simple keyword search over problem descriptions in the index."""
        index = self.load()
        words = {w.lower() for w in re.split(r"\W+", query) if len(w) > 2}
        scored = []
        for entry in index.get("entries", []):
            problem_words = {w.lower() for w in re.split(r"\W+", entry.get("problem", "")) if len(w) > 2}
            overlap = len(words & problem_words)
            if overlap > 0:
                scored.append((overlap, entry))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [e for _, e in scored[:top_k]]


# ---------------------------------------------------------------------------
# Experience Distiller
# ---------------------------------------------------------------------------

class ExperienceDistiller:
    """Orchestrates parallel sub-agent extraction and federated indexing.

    Enhances ReflectionAgent with:
    - Parallel symptom/failure/root-cause extraction
    - Deduplication via content hashing
    - Cross-workspace indexing
    - Hybrid retrieval for task planning
    """

    def __init__(
        self,
        gateway: LLMGateway,
        workspace: WorkspaceManager,
        workspace_id: str,
    ) -> None:
        self._gateway = gateway
        self._workspace = workspace
        self._workspace_id = workspace_id
        self._reflection = ReflectionAgent(gateway, workspace, workspace_id)
        self._store = SolutionStore(workspace, workspace_id)
        self._index = ExperienceIndex()

    def distill(
        self,
        events_log: List[Dict[str, Any]],
        requirement: str,
        job_id: Optional[str] = None,
        bus: Any = None,
    ) -> int:
        """Full distillation pipeline: extract → deduplicate → index → promote.

        Returns the number of new (non-duplicate) lessons saved.
        """
        if bus:
            bus.emit("distiller.start")

        try:
            return self._do_distill(events_log, requirement, job_id, bus)
        except Exception as exc:
            logger.warning("ExperienceDistiller.distill failed: %s", exc)
            if bus:
                bus.emit("distiller.complete", saved=0, error=str(exc))
            return 0

    def _do_distill(
        self,
        events_log: List[Dict[str, Any]],
        requirement: str,
        job_id: Optional[str],
        bus: Any,
    ) -> int:
        from .reflection_agent import _format_event_log

        event_text = _format_event_log(events_log)

        # ── Phase 1: Parallel sub-agent extraction ────────────────────────
        enrichments = self._parallel_extract(event_text, requirement)

        if bus:
            bus.emit("distiller.enrichment_complete",
                     symptoms=len(enrichments.get("symptoms", [])),
                     failed_attempts=len(enrichments.get("failed_attempts", [])),
                     root_causes=len(enrichments.get("root_causes", [])))

        # ── Phase 2: Run standard reflection (produces structured lessons) ─
        saved_count = self._reflection.reflect(
            events_log=events_log,
            requirement=requirement,
            job_id=job_id,
            bus=bus,
        )

        # ── Phase 3: Enrich saved solutions with sub-agent findings ───────
        all_solutions = self._store.load_all()
        job_solutions = [s for s in all_solutions if s.get("job_id") == job_id] if job_id else all_solutions[-saved_count:] if saved_count else []

        new_count = 0
        for sol in job_solutions:
            sol_id = sol.get("id", "")

            if not enrichments.get("symptoms") and not enrichments.get("failed_attempts"):
                pass
            else:
                if enrichments.get("symptoms") and not sol.get("symptoms"):
                    sol["symptoms"] = "; ".join(enrichments["symptoms"][:3])
                if enrichments.get("failed_attempts") and not sol.get("failed_attempts"):
                    attempts = [f"{a['approach']} → {a['why_failed']}" for a in enrichments["failed_attempts"][:3]]
                    sol["failed_attempts"] = "; ".join(attempts)
                if enrichments.get("root_causes") and not sol.get("root_cause"):
                    sol["root_cause"] = enrichments["root_causes"][0].get("cause", "")

                filename = f"solutions/{sol_id}.yaml"
                content = yaml.dump(sol, allow_unicode=True, default_flow_style=False, sort_keys=False)
                try:
                    self._workspace.write(self._workspace_id, filename, content)
                except Exception:
                    pass

            # ── Phase 4: Deduplicate and index globally ───────────────────
            if self._index.add_entry(sol_id, sol, self._workspace_id):
                new_count += 1
                ReflectionAgent._persist_global(sol_id, sol)
                ReflectionAgent._maybe_promote_to_skill(sol_id, sol)

                if bus:
                    bus.emit("distiller.indexed", sol_id=sol_id,
                             problem=sol.get("problem", "")[:80])

        if bus:
            bus.emit("distiller.complete", saved=saved_count, indexed=new_count)

        return new_count

    def _parallel_extract(
        self,
        event_text: str,
        requirement: str,
    ) -> Dict[str, Any]:
        """Run symptom, failure, and root-cause extraction in parallel threads."""
        prompts = {
            "symptoms": _SYMPTOM_PROMPT.format(event_log=event_text),
            "failed_attempts": _FAILURE_PROMPT.format(event_log=event_text),
            "root_causes": _ROOT_CAUSE_PROMPT.format(
                event_log=event_text, requirement=requirement,
            ),
        }

        results: Dict[str, Any] = {}

        def _call_llm(key: str, prompt: str) -> tuple:
            try:
                resp = self._gateway.send(prompt)
                parsed = parse_llm_json(resp["llm_response"], fallback={})
                return (key, parsed.get(key, []))
            except Exception:
                return (key, [])

        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = {pool.submit(_call_llm, k, p): k for k, p in prompts.items()}
            for future in as_completed(futures):
                key, data = future.result()
                results[key] = data

        return results

    # ------------------------------------------------------------------
    # Retrieval API (used before task planning)
    # ------------------------------------------------------------------

    def retrieve_relevant(
        self,
        task_description: str,
        top_k: int = 5,
    ) -> str:
        """Hybrid retrieval: keyword + tag + semantic search.

        Returns an LLM-ready context block of the most relevant past
        experiences for the given task.
        """
        # ── Layer 1: Keyword search over global index ─────────────────────
        keyword_hits = self._index.search_by_keyword(task_description, top_k=top_k * 2)

        # ── Layer 2: Tag-based search ─────────────────────────────────────
        task_words = [w.lower() for w in re.split(r"\W+", task_description) if len(w) > 2]
        tag_hits = self._index.search_by_tags(task_words, top_k=top_k * 2)

        # ── Layer 3: Semantic search via vector store ─────────────────────
        semantic_ctx = self._store.semantic_search(task_description, top_k=top_k)

        # ── Merge and deduplicate ─────────────────────────────────────────
        seen_ids = set()
        merged: List[Dict] = []
        for hit in keyword_hits + tag_hits:
            hid = hit.get("id", "")
            if hid not in seen_ids:
                seen_ids.add(hid)
                merged.append(hit)

        # Load full solution content for top matches
        full_solutions: List[Dict] = []
        for entry in merged[:top_k]:
            sol = self._load_global_solution(entry.get("id", ""))
            if sol:
                full_solutions.append(sol)

        if not full_solutions and not semantic_ctx:
            return ""

        lines: List[str] = [
            "## Compound Experience: Relevant Past Lessons\n"
            "These lessons were retrieved from past executions. Apply them to avoid\n"
            "repeating known mistakes and leverage proven patterns.\n",
        ]

        for i, sol in enumerate(full_solutions, 1):
            lines.append(f"### Experience {i} [{sol.get('type', 'lesson')}]")
            lines.append(f"**Problem**: {sol.get('problem', '')}")
            if sol.get("symptoms"):
                lines.append(f"**Symptoms**: {sol['symptoms']}")
            if sol.get("failed_attempts"):
                lines.append(f"**Failed Attempts**: {sol['failed_attempts']}")
            lines.append(f"**Solution**: {sol.get('solution', '')}")
            if sol.get("root_cause"):
                lines.append(f"**Root Cause**: {sol['root_cause']}")
            lines.append("")

        if semantic_ctx:
            lines.append(semantic_ctx)

        return "\n".join(lines)

    @staticmethod
    def _load_global_solution(sol_id: str) -> Optional[Dict]:
        """Load a single solution from the global docs/solutions/ directory."""
        filepath = _GLOBAL_SOLUTIONS_DIR / f"{sol_id}.yaml"
        if not filepath.exists():
            return None
        try:
            with open(filepath, encoding="utf-8") as f:
                return yaml.safe_load(f)
        except Exception:
            return None
