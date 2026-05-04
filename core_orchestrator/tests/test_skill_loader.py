"""Tests for SkillManifest + SkillLoader (progressive disclosure system).

Covers:
- Manifest load from YAML (empty / populated / missing file)
- Keyword matching: score calculation, top_k capping, zero-match exclusion
- SkillLoader: single-skill load, front-matter stripping, missing file
- load_matched: end-to-end match → load → formatted block
- No-match → empty string (never injects noise)
- ReflectionAgent integration: _should_promote, _slug, _infer_category,
  _maybe_promote_to_skill writes .md + updates manifest.yaml
"""

import os
import tempfile
from pathlib import Path

import pytest
import yaml

from core_orchestrator.skill_loader import SkillManifest, SkillLoader, SkillEntry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_project(tmp_path: Path) -> Path:
    """Create a minimal project tree with skills/ directory."""
    (tmp_path / "skills").mkdir()
    (tmp_path / "skills" / "python").mkdir()
    (tmp_path / "skills" / "frontend").mkdir()
    manifest = tmp_path / "skills" / "manifest.yaml"
    manifest.write_text("skills: []\n", encoding="utf-8")
    return tmp_path


def _write_manifest(project: Path, skills: list) -> None:
    path = project / "skills" / "manifest.yaml"
    path.write_text(yaml.dump({"skills": skills}), encoding="utf-8")


def _write_skill(project: Path, rel_path: str, body: str, front_matter: dict | None = None) -> None:
    skill_file = project / rel_path
    skill_file.parent.mkdir(parents=True, exist_ok=True)
    if front_matter:
        fm_text = yaml.dump(front_matter, default_flow_style=False).strip()
        content = f"---\n{fm_text}\n---\n\n{body}"
    else:
        content = body
    skill_file.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# SkillManifest
# ---------------------------------------------------------------------------

class TestSkillManifest:
    def test_load_empty_manifest(self, tmp_project):
        m = SkillManifest(tmp_project / "skills" / "manifest.yaml")
        m.load()
        assert m.entries == []

    def test_load_missing_manifest(self, tmp_path):
        m = SkillManifest(tmp_path / "nonexistent" / "manifest.yaml")
        m.load()
        assert m.entries == []

    def test_load_populated_manifest(self, tmp_project):
        _write_manifest(tmp_project, [
            {"id": "cors-fix", "name": "CORS Fix", "file": "skills/python/cors-fix.md",
             "triggers": ["cors", "403", "fastapi"], "category": "python", "version": 1},
            {"id": "redis-cache", "name": "Redis Caching", "file": "skills/python/redis-cache.md",
             "triggers": ["redis", "cache", "performance"], "category": "python", "version": 1},
        ])
        m = SkillManifest(tmp_project / "skills" / "manifest.yaml")
        m.load()
        assert len(m.entries) == 2
        assert m.entries[0].id == "cors-fix"
        assert "cors" in m.entries[0].triggers
        assert m.entries[1].id == "redis-cache"

    def test_load_skips_invalid_entries(self, tmp_project):
        """Entries missing 'id' or 'file' are silently dropped."""
        _write_manifest(tmp_project, [
            {"name": "No ID", "file": "skills/x.md", "triggers": []},        # missing id
            {"id": "no-file", "name": "No File", "triggers": []},             # missing file
            {"id": "valid", "name": "Valid", "file": "skills/valid.md", "triggers": ["valid"]},
        ])
        m = SkillManifest(tmp_project / "skills" / "manifest.yaml")
        m.load()
        assert len(m.entries) == 1
        assert m.entries[0].id == "valid"

    def test_match_no_entries_returns_empty(self, tmp_project):
        m = SkillManifest(tmp_project / "skills" / "manifest.yaml")
        m.load()
        assert m.match("anything") == []

    def test_match_single_hit(self, tmp_project):
        _write_manifest(tmp_project, [
            {"id": "cors-fix", "name": "CORS", "file": "skills/python/cors-fix.md",
             "triggers": ["cors", "middleware", "fastapi"], "category": "python", "version": 1},
        ])
        m = SkillManifest(tmp_project / "skills" / "manifest.yaml")
        m.load()
        results = m.match("cors issue in fastapi app")
        assert len(results) == 1
        assert results[0].id == "cors-fix"
        assert results[0].score == 2  # "cors" + "fastapi"

    def test_match_no_hit_returns_empty(self, tmp_project):
        _write_manifest(tmp_project, [
            {"id": "cors-fix", "name": "CORS", "file": "skills/python/cors-fix.md",
             "triggers": ["cors", "middleware"], "category": "python", "version": 1},
        ])
        m = SkillManifest(tmp_project / "skills" / "manifest.yaml")
        m.load()
        results = m.match("totally unrelated task about databases")
        assert results == []

    def test_match_top_k_capped(self, tmp_project):
        skills = [
            {"id": f"skill-{i}", "name": f"Skill {i}", "file": f"skills/python/skill-{i}.md",
             "triggers": ["python", "test"], "category": "python", "version": 1}
            for i in range(5)
        ]
        _write_manifest(tmp_project, skills)
        m = SkillManifest(tmp_project / "skills" / "manifest.yaml")
        m.load()
        results = m.match("python test suite", top_k=3)
        assert len(results) == 3

    def test_match_sorted_by_score_desc(self, tmp_project):
        _write_manifest(tmp_project, [
            {"id": "low", "name": "Low", "file": "skills/python/low.md",
             "triggers": ["cors"], "category": "python", "version": 1},
            {"id": "high", "name": "High", "file": "skills/python/high.md",
             "triggers": ["cors", "fastapi", "middleware"], "category": "python", "version": 1},
        ])
        m = SkillManifest(tmp_project / "skills" / "manifest.yaml")
        m.load()
        results = m.match("cors fastapi middleware integration")
        assert results[0].id == "high"
        assert results[0].score > results[1].score

    def test_match_is_case_insensitive(self, tmp_project):
        _write_manifest(tmp_project, [
            {"id": "auth-jwt", "name": "JWT Auth", "file": "skills/python/auth-jwt.md",
             "triggers": ["jwt", "authentication"], "category": "python", "version": 1},
        ])
        m = SkillManifest(tmp_project / "skills" / "manifest.yaml")
        m.load()
        results = m.match("JWT Authentication token validation")
        assert len(results) == 1
        assert results[0].id == "auth-jwt"


# ---------------------------------------------------------------------------
# SkillLoader
# ---------------------------------------------------------------------------

class TestSkillLoader:
    def test_no_manifest_returns_empty(self, tmp_path):
        """Missing manifest → load_matched returns empty string."""
        loader = SkillLoader(project_root=tmp_path)
        result = loader.load_matched("anything")
        assert result == ""

    def test_load_skill_basic(self, tmp_project):
        _write_manifest(tmp_project, [
            {"id": "cors-fix", "name": "CORS Fix", "file": "skills/python/cors-fix.md",
             "triggers": ["cors", "fastapi"], "category": "python", "version": 1},
        ])
        _write_skill(tmp_project, "skills/python/cors-fix.md",
                     "## Solution\nAdd CORSMiddleware to FastAPI app.")
        loader = SkillLoader(project_root=tmp_project)
        body = loader.load_skill("cors-fix")
        assert "CORSMiddleware" in body
        assert "## Solution" in body

    def test_load_skill_strips_front_matter(self, tmp_project):
        _write_manifest(tmp_project, [
            {"id": "redis-cache", "name": "Redis", "file": "skills/python/redis-cache.md",
             "triggers": ["redis"], "category": "python", "version": 1},
        ])
        _write_skill(tmp_project, "skills/python/redis-cache.md",
                     "## Solution\nUse redis.StrictRedis for caching.",
                     front_matter={"id": "redis-cache", "triggers": ["redis"]})
        loader = SkillLoader(project_root=tmp_project)
        body = loader.load_skill("redis-cache")
        # Front matter should be stripped
        assert "---" not in body
        assert "triggers:" not in body
        assert "StrictRedis" in body

    def test_load_skill_missing_file_returns_empty(self, tmp_project):
        _write_manifest(tmp_project, [
            {"id": "ghost", "name": "Ghost", "file": "skills/python/ghost.md",
             "triggers": ["ghost"], "category": "python", "version": 1},
        ])
        loader = SkillLoader(project_root=tmp_project)
        assert loader.load_skill("ghost") == ""

    def test_load_skill_unknown_id_returns_empty(self, tmp_project):
        loader = SkillLoader(project_root=tmp_project)
        assert loader.load_skill("nonexistent-skill") == ""

    def test_load_matched_returns_formatted_block(self, tmp_project):
        _write_manifest(tmp_project, [
            {"id": "cors-fix", "name": "CORS Fix", "file": "skills/python/cors-fix.md",
             "triggers": ["cors", "fastapi"], "category": "python", "version": 1},
        ])
        _write_skill(tmp_project, "skills/python/cors-fix.md",
                     "## Solution\nAdd CORSMiddleware.")
        loader = SkillLoader(project_root=tmp_project)
        result = loader.load_matched("cors problem in fastapi")
        assert "## Relevant Skills" in result
        assert "CORS Fix" in result
        assert "CORSMiddleware" in result

    def test_load_matched_no_match_returns_empty(self, tmp_project):
        _write_manifest(tmp_project, [
            {"id": "cors-fix", "name": "CORS Fix", "file": "skills/python/cors-fix.md",
             "triggers": ["cors"], "category": "python", "version": 1},
        ])
        _write_skill(tmp_project, "skills/python/cors-fix.md", "## Solution\nCORS fix.")
        loader = SkillLoader(project_root=tmp_project)
        result = loader.load_matched("unrelated database performance task")
        assert result == ""

    def test_reload_manifest_picks_up_new_entries(self, tmp_project):
        loader = SkillLoader(project_root=tmp_project)
        assert loader.load_matched("cors fastapi") == ""  # empty before

        # Now add a skill to manifest and disk
        _write_manifest(tmp_project, [
            {"id": "cors-fix", "name": "CORS Fix", "file": "skills/python/cors-fix.md",
             "triggers": ["cors", "fastapi"], "category": "python", "version": 1},
        ])
        _write_skill(tmp_project, "skills/python/cors-fix.md", "## Solution\nCORS fix.")
        loader.reload_manifest()
        result = loader.load_matched("cors fastapi issue")
        assert "CORS Fix" in result


# ---------------------------------------------------------------------------
# ReflectionAgent skill promotion helpers
# ---------------------------------------------------------------------------

class TestReflectionSkillPromotion:
    def test_should_promote_error_fix_with_symptoms_and_failed(self):
        from core_orchestrator.reflection_agent import ReflectionAgent
        lesson = {
            "type": "error_fix",
            "problem": "CORS blocked by browser",
            "symptoms": "403 Forbidden on preflight",
            "failed_attempts": "Tried adding headers manually",
            "solution": "Use CORSMiddleware",
        }
        assert ReflectionAgent._should_promote(lesson) is True

    def test_should_promote_error_fix_missing_symptoms(self):
        from core_orchestrator.reflection_agent import ReflectionAgent
        lesson = {
            "type": "error_fix",
            "problem": "Import error",
            "failed_attempts": "tried pip install",
            "solution": "pin the version",
        }
        assert ReflectionAgent._should_promote(lesson) is False

    def test_should_promote_architectural_long_solution(self):
        from core_orchestrator.reflection_agent import ReflectionAgent
        lesson = {
            "type": "architectural_decision",
            "problem": "Cache invalidation strategy",
            "solution": "Use event-driven invalidation with Redis pub/sub. "
                        "Each service publishes cache-evict events on mutations. "
                        "Consumers subscribe to evict their local caches.",
        }
        assert ReflectionAgent._should_promote(lesson) is True

    def test_should_promote_architectural_short_solution(self):
        from core_orchestrator.reflection_agent import ReflectionAgent
        lesson = {
            "type": "architectural_decision",
            "problem": "Caching",
            "solution": "Use Redis.",  # < 80 chars
        }
        assert ReflectionAgent._should_promote(lesson) is False

    def test_should_not_promote_best_practice(self):
        from core_orchestrator.reflection_agent import ReflectionAgent
        lesson = {
            "type": "best_practice",
            "problem": "Testing",
            "symptoms": "tests fail",
            "failed_attempts": "no mocks",
            "solution": "always mock external dependencies",
        }
        assert ReflectionAgent._should_promote(lesson) is False

    def test_slug_sanitizes_text(self):
        from core_orchestrator.reflection_agent import ReflectionAgent
        assert ReflectionAgent._slug("CORS issue with FastAPI!") == "cors-issue-with-fastapi"
        assert ReflectionAgent._slug("") == ""
        assert len(ReflectionAgent._slug("a" * 100)) <= 40

    def test_infer_category_python(self):
        from core_orchestrator.reflection_agent import ReflectionAgent
        assert ReflectionAgent._infer_category(["python", "fastapi"]) == "python"

    def test_infer_category_frontend(self):
        from core_orchestrator.reflection_agent import ReflectionAgent
        assert ReflectionAgent._infer_category(["javascript", "react"]) == "frontend"

    def test_infer_category_unknown_falls_back(self):
        from core_orchestrator.reflection_agent import ReflectionAgent
        assert ReflectionAgent._infer_category(["unknown-tag"]) == "general"

    def test_maybe_promote_writes_skill_file(self, tmp_path, monkeypatch):
        """_maybe_promote_to_skill creates .md + updates manifest.yaml."""
        from core_orchestrator import reflection_agent as ra_module

        # Redirect _SKILLS_DIR and _MANIFEST_PATH to tmp_path
        skills_dir    = tmp_path / "skills"
        manifest_path = skills_dir / "manifest.yaml"
        skills_dir.mkdir()
        manifest_path.write_text("skills: []\n", encoding="utf-8")

        monkeypatch.setattr(ra_module, "_SKILLS_DIR",    skills_dir)
        monkeypatch.setattr(ra_module, "_MANIFEST_PATH", manifest_path)

        from core_orchestrator.reflection_agent import ReflectionAgent

        lesson = {
            "type": "error_fix",
            "problem": "CORS blocked in FastAPI",
            "symptoms": "403 Forbidden on preflight OPTIONS request",
            "failed_attempts": "Added headers manually to each route handler",
            "solution": "Use CORSMiddleware from fastapi.middleware.cors; configure allow_origins",
            "root_cause": "FastAPI does not handle CORS by default",
            "tags": ["fastapi", "python", "cors"],
        }
        ReflectionAgent._maybe_promote_to_skill("test-sol-001", lesson)

        # Skill file should exist
        skill_files = list(skills_dir.rglob("*.md"))
        assert len(skill_files) == 1
        content = skill_files[0].read_text(encoding="utf-8")
        assert "CORS blocked in FastAPI" in content
        assert "CORSMiddleware" in content

        # Manifest should have one entry
        data = yaml.safe_load(manifest_path.read_text())
        assert len(data["skills"]) == 1
        entry = data["skills"][0]
        assert entry["created_from"] == "reflection"
        assert entry["source_solution"] == "test-sol-001"
        assert "fastapi" in entry["triggers"]

    def test_maybe_promote_idempotent(self, tmp_path, monkeypatch):
        """Calling _maybe_promote_to_skill twice for same lesson doesn't duplicate."""
        from core_orchestrator import reflection_agent as ra_module

        skills_dir    = tmp_path / "skills"
        manifest_path = skills_dir / "manifest.yaml"
        skills_dir.mkdir()
        manifest_path.write_text("skills: []\n", encoding="utf-8")

        monkeypatch.setattr(ra_module, "_SKILLS_DIR",    skills_dir)
        monkeypatch.setattr(ra_module, "_MANIFEST_PATH", manifest_path)

        from core_orchestrator.reflection_agent import ReflectionAgent

        lesson = {
            "type": "error_fix",
            "problem": "Redis connection timeout",
            "symptoms": "ConnectionError after 2s",
            "failed_attempts": "Increased timeout in config",
            "solution": "Use connection pooling with max_connections=50",
            "tags": ["redis", "database"],
        }
        ReflectionAgent._maybe_promote_to_skill("sol-001", lesson)
        ReflectionAgent._maybe_promote_to_skill("sol-001", lesson)  # second call

        data = yaml.safe_load(manifest_path.read_text())
        assert len(data["skills"]) == 1  # not duplicated

    def test_maybe_promote_does_nothing_when_not_qualifying(self, tmp_path, monkeypatch):
        """Non-qualifying lessons leave manifest unchanged."""
        from core_orchestrator import reflection_agent as ra_module

        skills_dir    = tmp_path / "skills"
        manifest_path = skills_dir / "manifest.yaml"
        skills_dir.mkdir()
        manifest_path.write_text("skills: []\n", encoding="utf-8")

        monkeypatch.setattr(ra_module, "_SKILLS_DIR",    skills_dir)
        monkeypatch.setattr(ra_module, "_MANIFEST_PATH", manifest_path)

        from core_orchestrator.reflection_agent import ReflectionAgent

        lesson = {
            "type": "best_practice",   # not promotable
            "problem": "Always test",
            "solution": "Write tests.",
            "tags": ["testing"],
        }
        ReflectionAgent._maybe_promote_to_skill("sol-002", lesson)

        data = yaml.safe_load(manifest_path.read_text())
        assert data["skills"] == []
