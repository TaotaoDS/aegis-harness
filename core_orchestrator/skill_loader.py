"""Skill Dynamic Loading Architecture.

Two-class design for progressive disclosure of reusable engineering skills:

  SkillManifest  — lightweight keyword index over skills/manifest.yaml
                   O(n) match at task arrival time; loads fast.

  SkillLoader    — on-demand full Markdown skill file reader + formatter.
                   Only reads matched skill files, not all of them.

Usage:
    loader = SkillLoader(project_root=Path("/workspace"))
    context = loader.load_matched("CORS issue with FastAPI middleware", top_k=2)
    # → Markdown block injected into system prompt, or "" if no match.

Design notes:
- No match → empty string returned (never inject noise).
- Missing manifest or skill files → silently degrade to "".
- Thread-safe: SkillManifest.load() is idempotent; SkillLoader is stateless.
- Skill files may contain YAML front-matter (--- fenced) — stripped on load
  so only the Markdown body reaches the LLM.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import yaml


# ---------------------------------------------------------------------------
# Default paths (relative to project root)
# ---------------------------------------------------------------------------

_DEFAULT_MANIFEST   = "skills/manifest.yaml"
_DEFAULT_SKILLS_DIR = "skills"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class SkillEntry:
    """A single row in the manifest."""
    id:       str
    name:     str
    file:     str                        # relative path from project root
    triggers: List[str] = field(default_factory=list)
    category: str = ""
    version:  int = 1
    score:    int = 0                   # populated during match, not persisted


# ---------------------------------------------------------------------------
# SkillManifest — keyword index
# ---------------------------------------------------------------------------

class SkillManifest:
    """Lightweight trigger-based index over skills/manifest.yaml.

    Attributes
    ----------
    entries:
        Loaded skill entries after ``load()`` is called.
    """

    def __init__(self, manifest_path: Path) -> None:
        self._path    = manifest_path
        self.entries: List[SkillEntry] = []

    # ------------------------------------------------------------------
    def load(self) -> None:
        """Parse manifest.yaml.  Idempotent — safe to call multiple times."""
        if not self._path.exists():
            self.entries = []
            return

        try:
            with open(self._path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except Exception:
            self.entries = []
            return

        raw_skills = data.get("skills", [])
        entries: List[SkillEntry] = []
        for item in raw_skills:
            if not isinstance(item, dict):
                continue
            if not item.get("id") or not item.get("file"):
                continue
            entries.append(
                SkillEntry(
                    id=item["id"],
                    name=item.get("name", item["id"]),
                    file=item["file"],
                    triggers=[t.lower() for t in item.get("triggers", [])],
                    category=item.get("category", ""),
                    version=int(item.get("version", 1)),
                )
            )
        self.entries = entries

    # ------------------------------------------------------------------
    def match(self, task_text: str, top_k: int = 3) -> List[SkillEntry]:
        """Return up to *top_k* skills whose triggers best overlap *task_text*.

        Scoring: +1 per trigger word found as a substring of the lower-cased
        task text.  Skills with score == 0 are excluded.

        Results are sorted descending by score, then ascending by id for
        determinism.
        """
        if not self.entries:
            return []

        needle = task_text.lower()
        scored: List[SkillEntry] = []

        for entry in self.entries:
            score = sum(1 for t in entry.triggers if t in needle)
            if score > 0:
                clone = SkillEntry(
                    id=entry.id,
                    name=entry.name,
                    file=entry.file,
                    triggers=entry.triggers,
                    category=entry.category,
                    version=entry.version,
                    score=score,
                )
                scored.append(clone)

        scored.sort(key=lambda e: (-e.score, e.id))
        return scored[:top_k]


# ---------------------------------------------------------------------------
# SkillLoader — on-demand Markdown loader
# ---------------------------------------------------------------------------

class SkillLoader:
    """Load and format Markdown skill files from the project skills directory.

    Parameters
    ----------
    project_root:
        Absolute path to the repository root (e.g. ``Path("/workspace")``).
    manifest_path:
        Optional override for the manifest YAML path (defaults to
        ``project_root/skills/manifest.yaml``).
    """

    # Front-matter fence pattern (--- ... ---)
    _FM_RE = re.compile(r"^\s*---.*?---\s*\n?", re.DOTALL)

    def __init__(
        self,
        project_root: Path,
        manifest_path: Optional[Path] = None,
    ) -> None:
        self._root   = project_root
        mpath        = manifest_path or (project_root / _DEFAULT_MANIFEST)
        self._manifest = SkillManifest(mpath)
        self._manifest.load()

    # ------------------------------------------------------------------
    def reload_manifest(self) -> None:
        """Reload the manifest from disk (e.g. after ReflectionAgent updated it)."""
        self._manifest.load()

    # ------------------------------------------------------------------
    def load_skill(self, skill_id: str) -> str:
        """Return the raw Markdown body for *skill_id*, or "" if not found."""
        entry = next((e for e in self._manifest.entries if e.id == skill_id), None)
        if entry is None:
            return ""

        skill_path = self._root / entry.file
        if not skill_path.exists():
            return ""

        try:
            text = skill_path.read_text(encoding="utf-8")
        except Exception:
            return ""

        # Strip YAML front-matter if present
        text = self._FM_RE.sub("", text, count=1).strip()
        return text

    # ------------------------------------------------------------------
    def load_matched(self, task_text: str, top_k: int = 3) -> str:
        """Match task_text against the manifest and return a formatted block.

        Returns an empty string when no skills match (clean no-op injection).
        """
        matches = self._manifest.match(task_text, top_k=top_k)
        if not matches:
            return ""

        parts: List[str] = ["## Relevant Skills from Knowledge Base\n"]
        for entry in matches:
            body = self.load_skill(entry.id)
            if not body:
                continue
            parts.append(f"### {entry.name}\n")
            parts.append(body)
            parts.append("")  # blank line between skills

        if len(parts) == 1:
            # No bodies loaded despite matches (files missing)
            return ""

        return "\n".join(parts).strip()

    # ------------------------------------------------------------------
    @property
    def manifest(self) -> SkillManifest:
        """Expose the underlying manifest (for testing / ReflectionAgent)."""
        return self._manifest
