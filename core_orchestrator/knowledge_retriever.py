"""Knowledge Retriever — pre-task injection of past solutions.

Searches the docs/solutions/ knowledge base and workspace-scoped solutions
for entries relevant to the current task. Returns formatted context that is
injected into the Architect and CEO system prompts to prevent repeated failures.

Falls back to keyword matching when vector embeddings are unavailable.
"""

import os
import re
from pathlib import Path
from typing import List, Optional

import yaml


_SOLUTIONS_DIR = "docs/solutions"
_MAX_RESULTS = 3
_MAX_CONTEXT_CHARS = 3000


class KnowledgeRetriever:
    """Semantic + keyword retrieval over the solution knowledge base."""

    def __init__(
        self,
        project_root: str,
        vector_store=None,
    ):
        self._project_root = Path(project_root)
        self._solutions_path = self._project_root / _SOLUTIONS_DIR
        self._vector_store = vector_store

    def retrieve_relevant(
        self,
        task_description: str,
        top_k: int = _MAX_RESULTS,
    ) -> str:
        """Find solutions relevant to the task and format as injectable context.

        Returns empty string if no relevant solutions found.
        """
        if self._vector_store:
            results = self._semantic_search(task_description, top_k)
            if results:
                return self._format_results(results)

        results = self._keyword_search(task_description, top_k)
        if results:
            return self._format_results(results)

        return ""

    def _semantic_search(self, query: str, top_k: int) -> List[dict]:
        """Search using vector similarity."""
        try:
            hits = self._vector_store.search_similar(
                query=query,
                top_k=top_k,
                filter_metadata={"source": "solution"},
            )
            return [
                {"problem": h.get("problem", ""), "solution": h.get("solution", ""),
                 "context": h.get("context", ""), "type": h.get("type", "")}
                for h in hits
            ]
        except Exception:
            return []

    def _keyword_search(self, query: str, top_k: int) -> List[dict]:
        """Fallback: keyword-based search over YAML solution files."""
        if not self._solutions_path.is_dir():
            return []

        query_words = set(re.findall(r'\w+', query.lower()))
        if not query_words:
            return []

        scored = []
        for fpath in self._solutions_path.glob("**/*.yaml"):
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    doc = yaml.safe_load(f)
                if not isinstance(doc, dict):
                    continue

                searchable = " ".join([
                    str(doc.get("problem", "")),
                    str(doc.get("solution", "")),
                    str(doc.get("context", "")),
                    " ".join(doc.get("tags", [])),
                ]).lower()

                doc_words = set(re.findall(r'\w+', searchable))
                overlap = len(query_words & doc_words)
                if overlap >= 2:
                    scored.append((overlap, doc))
            except Exception:
                continue

        scored.sort(key=lambda x: x[0], reverse=True)
        return [doc for _, doc in scored[:top_k]]

    def _format_results(self, results: List[dict]) -> str:
        """Format solution entries as injectable context."""
        if not results:
            return ""

        lines = ["## Past Solutions (avoid repeating these failures)\n"]
        for i, r in enumerate(results, 1):
            problem = r.get("problem", "unknown")
            solution = r.get("solution", "unknown")
            context = r.get("context", "")
            sol_type = r.get("type", "lesson")

            entry = f"### {i}. [{sol_type}] {problem}\n**Solution:** {solution}"
            if context:
                entry += f"\n**Context:** {context}"
            lines.append(entry)

        text = "\n\n".join(lines)
        if len(text) > _MAX_CONTEXT_CHARS:
            text = text[:_MAX_CONTEXT_CHARS] + "\n[… additional solutions truncated]"
        return text
