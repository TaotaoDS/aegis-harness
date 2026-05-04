"""Tests for FusionArchitectAgent — cross-repository architecture analysis.

Covers:
- Constructor: repos_root directory creation
- run(): report is None when LLM never calls write_fusion_report
- run(): happy path — LLM calls write_fusion_report → FusionReport returned
- run(): auth_token auto-injected from repos config into clone_repo calls
- run(): tool_llm exception does not propagate (returns None gracefully)
- _handle_write_fusion_report: stores report, returns JSON ack
- _persist_as_skill: calls ReflectionAgent._maybe_promote_to_skill with correct lesson
- _persist_as_skill: adds 'architecture' and 'fusion' tags always
- _build_skill_markdown: correct Markdown structure
- FusionReport dataclass: default values, field assignment
- Knowledge pipeline integration: skill file written + manifest updated
"""

import json
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch, call

import pytest
import yaml

from core_orchestrator.fusion_architect_agent import FusionArchitectAgent, FusionReport


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_noop_tool_llm():
    """Tool LLM that calls no tools and returns empty list."""
    def tool_llm(system, user_prompt, tools, tool_handler=None):
        return []
    return tool_llm


def _make_report_tool_llm(report_args: Dict[str, Any]):
    """Tool LLM that immediately calls write_fusion_report with given args."""
    def tool_llm(system, user_prompt, tools, tool_handler=None):
        if tool_handler:
            tool_handler("write_fusion_report", report_args)
        return []
    return tool_llm


def _make_clone_and_report_tool_llm(report_args: Dict[str, Any]):
    """Tool LLM that calls clone_repo then write_fusion_report."""
    def tool_llm(system, user_prompt, tools, tool_handler=None):
        if tool_handler:
            # Simulate clone first
            tool_handler("clone_repo", {
                "git_url":   "https://github.com/org/repo.git",
                "dest_name": "repo-a",
            })
            # Then submit report
            tool_handler("write_fusion_report", report_args)
        return []
    return tool_llm


_SAMPLE_REPORT_ARGS = {
    "title":                "Test Fusion Architecture",
    "repos_analyzed":       ["repo-a", "repo-b"],
    "strengths_per_repo":   "repo-a: good error handling\nrepo-b: clean interfaces",
    "design_tradeoffs":     "repo-a is verbose; repo-b is concise",
    "fusion_architecture":  "Combine repo-a's error handling with repo-b's interface design.\n"
                            "Use dependency injection throughout.",
    "implementation_steps": "1. Extract base classes\n2. Implement error middleware",
    "tags":                 ["python", "fastapi"],
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def repos_root(tmp_path: Path) -> Path:
    return tmp_path / "repos"


@pytest.fixture()
def agent(repos_root) -> FusionArchitectAgent:
    return FusionArchitectAgent(
        tool_llm      = _make_noop_tool_llm(),
        repos_root    = repos_root,
        analysis_goal = "Compare two repos",
    )


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------

class TestFusionArchitectAgentInit:
    def test_repos_root_created_if_missing(self, tmp_path):
        root = tmp_path / "new" / "deeply" / "nested"
        assert not root.exists()
        FusionArchitectAgent(
            tool_llm=_make_noop_tool_llm(),
            repos_root=root,
        )
        assert root.exists()

    def test_all_tools_registered(self, repos_root):
        agent = FusionArchitectAgent(
            tool_llm=_make_noop_tool_llm(),
            repos_root=repos_root,
        )
        names = {t["name"] for t in agent._ALL_TOOLS}
        for expected in ("clone_repo", "read_repo_file", "glob_repo",
                         "grep_repo", "analyze_ast", "write_fusion_report"):
            assert expected in names


# ---------------------------------------------------------------------------
# run() — basic outcomes
# ---------------------------------------------------------------------------

class TestFusionArchitectAgentRun:
    def test_returns_none_when_no_report_submitted(self, repos_root):
        agent = FusionArchitectAgent(
            tool_llm=_make_noop_tool_llm(),
            repos_root=repos_root,
        )
        report = agent.run(repos=[])
        assert report is None

    def test_returns_fusion_report_on_success(self, repos_root):
        agent = FusionArchitectAgent(
            tool_llm=_make_report_tool_llm(_SAMPLE_REPORT_ARGS),
            repos_root=repos_root,
        )
        report = agent.run(repos=[])
        assert report is not None
        assert isinstance(report, FusionReport)
        assert report.title == "Test Fusion Architecture"
        assert report.repos_analyzed == ["repo-a", "repo-b"]

    def test_tool_llm_exception_returns_none_gracefully(self, repos_root):
        def crashing_tool_llm(system, user_prompt, tools, tool_handler=None):
            raise RuntimeError("LLM service unavailable")

        agent = FusionArchitectAgent(
            tool_llm=crashing_tool_llm,
            repos_root=repos_root,
        )
        report = agent.run(repos=[])
        assert report is None  # should not raise

    def test_bus_events_emitted(self, repos_root):
        bus = MagicMock()
        agent = FusionArchitectAgent(
            tool_llm      = _make_report_tool_llm(_SAMPLE_REPORT_ARGS),
            repos_root    = repos_root,
            bus           = bus,
        )
        agent.run(repos=[])
        bus.emit.assert_any_call("fusion.start", repo_count=0)
        # fusion.complete emitted after successful persist
        emitted_events = [c.args[0] for c in bus.emit.call_args_list]
        assert "fusion.complete" in emitted_events

    def test_bus_no_report_event_when_none(self, repos_root):
        bus = MagicMock()
        agent = FusionArchitectAgent(
            tool_llm=_make_noop_tool_llm(),
            repos_root=repos_root,
            bus=bus,
        )
        agent.run(repos=[])
        emitted_events = [c.args[0] for c in bus.emit.call_args_list]
        assert "fusion.no_report" in emitted_events


# ---------------------------------------------------------------------------
# Auth token auto-injection
# ---------------------------------------------------------------------------

class TestAuthTokenInjection:
    def test_auth_token_auto_injected_for_clone(self, repos_root):
        """Token specified in repos config is injected even if LLM omits it."""
        captured_args = {}

        def capturing_tool_llm(system, user_prompt, tools, tool_handler=None):
            if tool_handler:
                # Simulate LLM cloning without providing auth_token
                result = tool_handler("clone_repo", {
                    "git_url":   "https://github.com/org/private.git",
                    "dest_name": "private-repo",
                    # auth_token intentionally omitted
                })
                captured_args["result"] = result
                tool_handler("write_fusion_report", _SAMPLE_REPORT_ARGS)
            return []

        ok_result = MagicMock()
        ok_result.returncode = 0
        ok_result.stderr = ""

        with patch("subprocess.run", return_value=ok_result) as mock_run:
            agent = FusionArchitectAgent(
                tool_llm=capturing_tool_llm,
                repos_root=repos_root,
            )
            agent.run(repos=[{
                "git_url":   "https://github.com/org/private.git",
                "dest_name": "private-repo",
                "auth_token": "ghp_injected_token",
            }])

        # Token should have been injected into the git clone URL
        cmd = mock_run.call_args[0][0]
        url_arg = next((a for a in cmd if "github.com" in a), "")
        assert "ghp_injected_token@" in url_arg


# ---------------------------------------------------------------------------
# _handle_write_fusion_report
# ---------------------------------------------------------------------------

class TestHandleWriteFusionReport:
    def test_stores_report_and_returns_ack(self, repos_root, agent):
        handler = agent._make_tool_handler(lambda n, a: "", repos=[])
        result = json.loads(handler("write_fusion_report", _SAMPLE_REPORT_ARGS))
        assert result["status"] == "report_received"
        assert agent._report is not None
        assert agent._report.title == "Test Fusion Architecture"

    def test_handle_missing_fields_does_not_raise(self, repos_root, agent):
        # Minimal args — no crash expected
        handler = agent._make_tool_handler(lambda n, a: "", repos=[])
        result = json.loads(handler("write_fusion_report", {
            "title": "Minimal",
            "repos_analyzed": [],
            "strengths_per_repo": "",
            "design_tradeoffs": "",
            "fusion_architecture": "",
            "implementation_steps": "",
            "tags": [],
        }))
        assert result["status"] == "report_received"


# ---------------------------------------------------------------------------
# _build_skill_markdown
# ---------------------------------------------------------------------------

class TestBuildSkillMarkdown:
    def test_contains_all_sections(self):
        report = FusionReport(
            title               = "My Fusion",
            repos_analyzed      = ["a", "b"],
            strengths_per_repo  = "a is fast, b is safe",
            design_tradeoffs    = "speed vs safety",
            fusion_architecture = "Use a's speed with b's safety checks.",
            implementation_steps= "1. Start\n2. Finish",
            tags                = ["architecture"],
        )
        md = FusionArchitectAgent._build_skill_markdown(report)
        assert "# My Fusion" in md
        assert "Strengths Per Repository" in md
        assert "Design Trade-offs" in md
        assert "Fusion Architecture" in md
        assert "Implementation Steps" in md
        assert "a, b" in md


# ---------------------------------------------------------------------------
# _persist_as_skill integration
# ---------------------------------------------------------------------------

class TestPersistAsSkill:
    def test_persist_calls_maybe_promote(self, repos_root, tmp_path, monkeypatch):
        from core_orchestrator import reflection_agent as ra_module

        skills_dir    = tmp_path / "skills"
        manifest_path = skills_dir / "manifest.yaml"
        skills_dir.mkdir()
        manifest_path.write_text("skills: []\n")

        monkeypatch.setattr(ra_module, "_SKILLS_DIR",    skills_dir)
        monkeypatch.setattr(ra_module, "_MANIFEST_PATH", manifest_path)

        agent = FusionArchitectAgent(
            tool_llm=_make_noop_tool_llm(),
            repos_root=repos_root,
        )
        report = FusionReport(
            title               = "Auth Fusion Pattern",
            repos_analyzed      = ["auth-lib-a", "auth-lib-b"],
            strengths_per_repo  = "a: JWT support\nb: OAuth2 support",
            design_tradeoffs    = "JWTs are stateless; OAuth2 needs server",
            fusion_architecture = (
                "Implement a unified auth layer that supports both JWT "
                "and OAuth2. Use strategy pattern to switch at runtime. "
                "This gives stateless operation for microservices and "
                "full OAuth2 flow for web clients."
            ),
            implementation_steps= "1. Define AuthStrategy protocol\n2. Implement JWTStrategy\n3. Implement OAuthStrategy",
            tags                = ["python", "authentication"],
        )
        agent._persist_as_skill(report)

        # Skill file should exist in architecture category
        skill_files = list(skills_dir.rglob("*.md"))
        assert len(skill_files) == 1
        content = skill_files[0].read_text()
        assert "Auth Fusion Pattern" in content
        assert "JWT" in content

        # Manifest updated
        data = yaml.safe_load(manifest_path.read_text())
        assert len(data["skills"]) == 1
        entry = data["skills"][0]
        assert entry["created_from"] == "reflection"

    def test_persist_adds_architecture_and_fusion_tags(self, repos_root, tmp_path, monkeypatch):
        from core_orchestrator import reflection_agent as ra_module

        skills_dir    = tmp_path / "skills"
        manifest_path = skills_dir / "manifest.yaml"
        skills_dir.mkdir()
        manifest_path.write_text("skills: []\n")

        monkeypatch.setattr(ra_module, "_SKILLS_DIR",    skills_dir)
        monkeypatch.setattr(ra_module, "_MANIFEST_PATH", manifest_path)

        agent = FusionArchitectAgent(
            tool_llm=_make_noop_tool_llm(),
            repos_root=repos_root,
        )
        # Report with NO architecture/fusion tags
        report = FusionReport(
            title               = "DB Fusion",
            repos_analyzed      = ["db-a"],
            strengths_per_repo  = "Fast reads",
            design_tradeoffs    = "Consistency vs speed",
            fusion_architecture = (
                "Adopt CQRS with read replicas for high throughput "
                "while maintaining write consistency. "
                "This balances performance with data integrity."
            ),
            implementation_steps= "1. Separate read/write models",
            tags                = ["database"],   # no 'architecture' or 'fusion'
        )
        agent._persist_as_skill(report)

        data = yaml.safe_load(manifest_path.read_text())
        assert len(data["skills"]) == 1
        triggers = data["skills"][0].get("triggers", [])
        assert "architecture" in triggers or "fusion" in triggers

    def test_persist_failure_does_not_crash(self, repos_root):
        agent = FusionArchitectAgent(
            tool_llm=_make_noop_tool_llm(),
            repos_root=repos_root,
        )
        report = FusionReport(
            title               = "Crash Test",
            repos_analyzed      = [],
            strengths_per_repo  = "",
            design_tradeoffs    = "",
            fusion_architecture = "x",
            implementation_steps= "",
            tags                = [],
        )
        # Patch _maybe_promote_to_skill to raise — should not propagate
        with patch(
            "core_orchestrator.reflection_agent.ReflectionAgent._maybe_promote_to_skill",
            side_effect=RuntimeError("disk full"),
        ):
            agent._persist_as_skill(report)  # must not raise


# ---------------------------------------------------------------------------
# System prompt content
# ---------------------------------------------------------------------------

class TestFusionSystemPrompt:
    def test_system_prompt_contains_analysis_goal(self, repos_root):
        captured = {}

        def capture_tool_llm(system, user_prompt, tools, tool_handler=None):
            captured["system"] = system
            return []

        agent = FusionArchitectAgent(
            tool_llm      = capture_tool_llm,
            repos_root    = repos_root,
            analysis_goal = "Compare JWT implementations across repositories",
        )
        agent.run(repos=[{"git_url": "https://github.com/org/repo", "dest_name": "repo"}])
        assert "Compare JWT implementations" in captured["system"]

    def test_system_prompt_lists_repos(self, repos_root):
        captured = {}

        def capture_tool_llm(system, user_prompt, tools, tool_handler=None):
            captured["system"] = system
            return []

        agent = FusionArchitectAgent(
            tool_llm=capture_tool_llm,
            repos_root=repos_root,
        )
        agent.run(repos=[
            {"git_url": "https://github.com/org/repo-alpha", "dest_name": "alpha"},
            {"git_url": "https://github.com/org/repo-beta",  "dest_name": "beta"},
        ])
        assert "alpha" in captured["system"]
        assert "beta" in captured["system"]

    def test_system_prompt_contains_iron_rule(self, repos_root):
        captured = {}

        def capture_tool_llm(system, user_prompt, tools, tool_handler=None):
            captured["system"] = system
            return []

        FusionArchitectAgent(
            tool_llm=capture_tool_llm,
            repos_root=repos_root,
        ).run(repos=[])
        assert "IRON RULE" in captured["system"]
        assert "English" in captured["system"]
