"""Tests for UserProfile, TechLevel, and CEOAgent adaptive interview.

Coverage:
  - UserProfile construction with defaults and custom values
  - TechLevel enum values and predicates
  - Serialisation round-trip (to_dict / from_dict)
  - from_dict tolerates unknown/missing/invalid keys
  - user_context_block formatting
  - interview_style_instructions for each tech level
  - CEOAgent backward compat (no user_profile = technical mode)
  - CEOAgent with NON_TECHNICAL profile uses non-tech prompt
  - CEOAgent with SEMI_TECHNICAL profile uses semi-tech instructions
  - ModelRouter TTL cache and invalidate_model_cache
"""

import json
import time

import pytest

from core_orchestrator.user_profile import (
    DEFAULT_PROFILE,
    TechLevel,
    UserProfile,
    _NON_TECH_STYLE,
    _SEMI_TECH_STYLE,
)
from core_orchestrator.ceo_agent import CEOAgent, _INTERVIEW_SYSTEM, _INTERVIEW_SYSTEM_NON_TECH
from core_orchestrator.llm_gateway import LLMGateway
from core_orchestrator.workspace_manager import WorkspaceManager


# ===========================================================================
# TestTechLevel
# ===========================================================================

class TestTechLevel:
    def test_values_exist(self):
        assert TechLevel.TECHNICAL.value       == "technical"
        assert TechLevel.SEMI_TECHNICAL.value  == "semi_technical"
        assert TechLevel.NON_TECHNICAL.value   == "non_technical"

    def test_is_str_subclass(self):
        assert isinstance(TechLevel.TECHNICAL, str)

    def test_from_string(self):
        assert TechLevel("technical")      is TechLevel.TECHNICAL
        assert TechLevel("semi_technical") is TechLevel.SEMI_TECHNICAL
        assert TechLevel("non_technical")  is TechLevel.NON_TECHNICAL


# ===========================================================================
# TestUserProfileDefaults
# ===========================================================================

class TestUserProfileDefaults:
    def test_default_name(self):
        p = UserProfile()
        assert p.name == "User"

    def test_default_tech_level(self):
        p = UserProfile()
        assert p.technical_level == TechLevel.TECHNICAL

    def test_default_language(self):
        p = UserProfile()
        assert p.language == "auto"

    def test_technical_predicate(self):
        p = UserProfile(technical_level=TechLevel.TECHNICAL)
        assert p.is_technical
        assert not p.is_semi_technical
        assert not p.is_non_technical

    def test_semi_technical_predicate(self):
        p = UserProfile(technical_level=TechLevel.SEMI_TECHNICAL)
        assert p.is_semi_technical
        assert not p.is_technical
        assert not p.is_non_technical

    def test_non_technical_predicate(self):
        p = UserProfile(technical_level=TechLevel.NON_TECHNICAL)
        assert p.is_non_technical
        assert not p.is_technical

    def test_display_name_uses_name(self):
        p = UserProfile(name="Alice")
        assert p.display_name == "Alice"

    def test_display_name_fallback_for_empty(self):
        p = UserProfile(name="")
        assert p.display_name == "there"

    def test_default_profile_singleton_is_technical(self):
        assert DEFAULT_PROFILE.is_technical


# ===========================================================================
# TestUserProfileSerialisation
# ===========================================================================

class TestUserProfileSerialisation:
    def test_to_dict_keys(self):
        p = UserProfile(name="Bob", role="PM")
        d = p.to_dict()
        assert "name" in d
        assert "role" in d
        assert "technical_level" in d
        assert "language" in d
        assert "notes" in d

    def test_to_dict_tech_level_is_string(self):
        p = UserProfile(technical_level=TechLevel.NON_TECHNICAL)
        assert p.to_dict()["technical_level"] == "non_technical"

    def test_round_trip(self):
        p = UserProfile(name="Carol", role="CTO",
                        technical_level=TechLevel.SEMI_TECHNICAL,
                        language="zh", notes="Works in fintech")
        p2 = UserProfile.from_dict(p.to_dict())
        assert p2.name            == p.name
        assert p2.role            == p.role
        assert p2.technical_level == p.technical_level
        assert p2.language        == p.language
        assert p2.notes           == p.notes

    def test_from_dict_missing_keys_use_defaults(self):
        p = UserProfile.from_dict({})
        assert p.name  == "User"
        assert p.is_technical

    def test_from_dict_ignores_unknown_keys(self):
        p = UserProfile.from_dict({"name": "Dave", "unknown_field": 42})
        assert p.name == "Dave"

    def test_from_dict_invalid_tech_level_falls_back(self):
        p = UserProfile.from_dict({"technical_level": "super_expert"})
        assert p.technical_level == TechLevel.TECHNICAL

    def test_from_dict_none_name_uses_default(self):
        p = UserProfile.from_dict({"name": None})
        assert p.name == "User"


# ===========================================================================
# TestUserContextBlock
# ===========================================================================

class TestUserContextBlock:
    def test_contains_name(self):
        p = UserProfile(name="Eve")
        assert "Eve" in p.user_context_block()

    def test_contains_role_when_set(self):
        p = UserProfile(name="Frank", role="DevOps Engineer")
        block = p.user_context_block()
        assert "DevOps Engineer" in block

    def test_no_tech_level_for_technical_user(self):
        """Technical is the default — no need to clutter the prompt."""
        p = UserProfile(technical_level=TechLevel.TECHNICAL)
        block = p.user_context_block()
        assert "technical" not in block.lower()

    def test_tech_level_shown_for_non_technical(self):
        p = UserProfile(technical_level=TechLevel.NON_TECHNICAL)
        block = p.user_context_block()
        assert "non technical" in block.lower() or "non_technical" in block.lower()

    def test_notes_included_when_present(self):
        p = UserProfile(notes="Leads a 50-person team")
        assert "50-person" in p.user_context_block()


# ===========================================================================
# TestInterviewStyleInstructions
# ===========================================================================

class TestInterviewStyleInstructions:
    def test_technical_returns_empty_string(self):
        p = UserProfile(technical_level=TechLevel.TECHNICAL)
        assert p.interview_style_instructions() == ""

    def test_non_technical_returns_non_tech_style(self):
        p = UserProfile(technical_level=TechLevel.NON_TECHNICAL)
        instr = p.interview_style_instructions()
        assert "NON-TECHNICAL" in instr
        assert "FORBIDDEN" in instr

    def test_semi_technical_returns_semi_tech_style(self):
        p = UserProfile(technical_level=TechLevel.SEMI_TECHNICAL)
        instr = p.interview_style_instructions()
        assert "SEMI-TECHNICAL" in instr


# ===========================================================================
# Fixtures
# ===========================================================================

def _build_ceo(workspace, responses, user_profile=None):
    idx = {"i": 0}

    def mock_llm(text):
        i = idx["i"]; idx["i"] += 1
        return responses[i] if i < len(responses) else json.dumps({"question": "", "done": True})

    gw = LLMGateway(llm=mock_llm)
    return CEOAgent(gateway=gw, workspace=workspace, workspace_id="proj",
                    user_profile=user_profile)


@pytest.fixture
def workspace(tmp_path):
    wm = WorkspaceManager(tmp_path)
    wm.create("proj")
    return wm


# ===========================================================================
# TestCEOAgentBackwardCompat
# ===========================================================================

class TestCEOAgentBackwardCompat:
    """user_profile=None must preserve the exact original behaviour."""

    def test_no_profile_uses_standard_prompt(self, workspace):
        prompts = []

        def capture(text):
            prompts.append(text)
            return json.dumps({"question": "", "done": True})

        gw = LLMGateway(llm=capture)
        ceo = CEOAgent(gateway=gw, workspace=workspace, workspace_id="proj")
        ceo.start_interview("Build an API")
        # Standard prompt contains the classic requirements-analyst framing
        assert "requirements analyst" in prompts[0].lower()

    def test_start_interview_still_returns_question(self, workspace):
        ceo = _build_ceo(workspace, [
            json.dumps({"confidence": 50, "question": "What is the scope?", "done": False}),
            json.dumps({"question": "", "done": True}),
            json.dumps({"tasks": [{"id": "task_1", "title": "T", "description": "D", "priority": "high"}]}),
        ])
        q = ceo.start_interview("Build REST API")
        assert q == "What is the scope?"

    def test_no_user_profile_attribute_on_agent(self, workspace):
        """The _user_profile attribute exists but is None."""
        ceo = _build_ceo(workspace, [json.dumps({"question": "", "done": True})])
        assert ceo._user_profile is None


# ===========================================================================
# TestCEOAgentNonTechnicalProfile
# ===========================================================================

class TestCEOAgentNonTechnicalProfile:
    """NON_TECHNICAL profile triggers the non-tech interview prompt."""

    def _non_tech_profile(self):
        return UserProfile(
            name="Alice", role="Founder",
            technical_level=TechLevel.NON_TECHNICAL,
        )

    def test_non_tech_prompt_used(self, workspace):
        prompts = []

        def capture(text):
            prompts.append(text)
            return json.dumps({"confidence": 80, "question": "...", "options": [], "done": False})

        gw = LLMGateway(llm=capture)
        ceo = CEOAgent(gateway=gw, workspace=workspace, workspace_id="proj",
                       user_profile=self._non_tech_profile())
        ceo.start_interview("I want to build an app")
        # The non-tech system prompt instructs about FORBIDDEN jargon
        assert "FORBIDDEN" in prompts[0] or "NON-TECHNICAL" in prompts[0]

    def test_non_tech_prompt_forbids_jargon(self, workspace):
        prompts = []

        def capture(text):
            prompts.append(text)
            return json.dumps({"confidence": 97, "question": "", "options": [], "done": True})

        gw = LLMGateway(llm=capture)
        ceo = CEOAgent(gateway=gw, workspace=workspace, workspace_id="proj",
                       user_profile=self._non_tech_profile())
        ceo.start_interview("I want something")
        assert "FORBIDDEN" in prompts[0]

    def test_technical_profile_does_not_get_non_tech_prompt(self, workspace):
        prompts = []

        def capture(text):
            prompts.append(text)
            return json.dumps({"confidence": 97, "question": "", "done": True})

        gw = LLMGateway(llm=capture)
        profile = UserProfile(technical_level=TechLevel.TECHNICAL)
        ceo = CEOAgent(gateway=gw, workspace=workspace, workspace_id="proj",
                       user_profile=profile)
        ceo.start_interview("Build a microservice")
        assert "FORBIDDEN" not in prompts[0]

    def test_semi_tech_prompt_contains_style_instructions(self, workspace):
        prompts = []

        def capture(text):
            prompts.append(text)
            return json.dumps({"confidence": 97, "question": "", "done": True})

        gw = LLMGateway(llm=capture)
        profile = UserProfile(technical_level=TechLevel.SEMI_TECHNICAL)
        ceo = CEOAgent(gateway=gw, workspace=workspace, workspace_id="proj",
                       user_profile=profile)
        ceo.start_interview("Build a dashboard")
        assert "SEMI-TECHNICAL" in prompts[0]


# ===========================================================================
# TestModelRouterTTLCache
# ===========================================================================

class TestModelRouterTTLCache:
    """ModelRouter TTL cache must not affect correctness; only speed."""

    def test_invalidate_clears_cache(self, tmp_path):
        from core_orchestrator.model_router import (
            _CONFIG_CACHE,
            invalidate_model_cache,
        )
        # Prime with a fake entry
        _CONFIG_CACHE["fake/path.yaml"] = (time.monotonic(), {"models": {}, "routes": []})
        invalidate_model_cache("fake/path.yaml")
        assert "fake/path.yaml" not in _CONFIG_CACHE

    def test_invalidate_all_clears_cache(self, tmp_path):
        from core_orchestrator.model_router import _CONFIG_CACHE, invalidate_model_cache
        _CONFIG_CACHE["a"] = (time.monotonic(), {})
        _CONFIG_CACHE["b"] = (time.monotonic(), {})
        invalidate_model_cache()
        assert len(_CONFIG_CACHE) == 0

    def test_cache_returns_same_dict_within_ttl(self, tmp_path):
        """Two loads within TTL should return the same dict object."""
        from core_orchestrator.model_router import _load_yaml_cached, invalidate_model_cache
        import yaml as _yaml

        cfg_path = tmp_path / "mini.yaml"
        cfg_path.write_text(_yaml.dump({"models": {}, "routes": []}))
        path_str = str(cfg_path)

        invalidate_model_cache(path_str)
        d1 = _load_yaml_cached(path_str, ttl=60)
        d2 = _load_yaml_cached(path_str, ttl=60)
        assert d1 is d2   # same object → cache hit

    def test_expired_cache_reloads(self, tmp_path):
        """After TTL expires the file is re-read."""
        from core_orchestrator.model_router import _load_yaml_cached, invalidate_model_cache
        import yaml as _yaml

        cfg_path = tmp_path / "mini2.yaml"
        cfg_path.write_text(_yaml.dump({"models": {}, "routes": []}))
        path_str = str(cfg_path)

        invalidate_model_cache(path_str)
        d1 = _load_yaml_cached(path_str, ttl=0.001)  # 1 ms TTL
        time.sleep(0.01)                               # let it expire
        d2 = _load_yaml_cached(path_str, ttl=0.001)
        # Different dict objects → cache miss → reload
        assert d1 is not d2
