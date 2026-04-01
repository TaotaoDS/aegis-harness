"""Tests for model router: config loading, routing, provider adapters, gateway integration."""

import os
import textwrap
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import yaml

from core_orchestrator.model_router import ModelRouter, ConfigError
from core_orchestrator.llm_gateway import LLMGateway


# --- Fixtures ---

@pytest.fixture
def tmp_config(tmp_path):
    """Write a minimal YAML config and return its path."""
    config = {
        "models": {
            "fast-model": {
                "provider": "openai",
                "model_id": "gpt-4o-mini",
                "api_key_env": "TEST_OPENAI_KEY",
                "max_tokens": 2048,
                "tier": "standard",
            },
            "smart-model": {
                "provider": "anthropic",
                "model_id": "claude-opus-4-20250918",
                "api_key_env": "TEST_ANTHROPIC_KEY",
                "max_tokens": 8192,
                "tier": "advanced",
            },
        },
        "routes": [
            {"match": {"customer": "vip", "task": "reasoning"}, "model": "smart-model"},
            {"match": {"customer": "vip"}, "model": "fast-model"},
            {"match": {"task": "reasoning"}, "model": "smart-model"},
            {"match": {}, "model": "fast-model"},
        ],
    }
    path = tmp_path / "models.yaml"
    path.write_text(yaml.dump(config))
    return path


@pytest.fixture
def env_with_keys(monkeypatch):
    """Set fake API keys in environment."""
    monkeypatch.setenv("TEST_OPENAI_KEY", "sk-test-openai-fake")
    monkeypatch.setenv("TEST_ANTHROPIC_KEY", "sk-test-anthropic-fake")


# --- Config loading ---

class TestConfigLoading:
    def test_loads_valid_yaml(self, tmp_config, env_with_keys):
        router = ModelRouter(tmp_config)
        assert "fast-model" in router.models
        assert "smart-model" in router.models

    def test_raises_on_missing_file(self):
        with pytest.raises(FileNotFoundError):
            ModelRouter("/nonexistent/path.yaml")

    def test_raises_on_missing_models_key(self, tmp_path):
        path = tmp_path / "bad.yaml"
        path.write_text(yaml.dump({"routes": []}))
        with pytest.raises(ConfigError, match="models"):
            ModelRouter(path)

    def test_raises_on_missing_routes_key(self, tmp_path):
        path = tmp_path / "bad.yaml"
        path.write_text(yaml.dump({"models": {"m": {"provider": "openai", "model_id": "x", "api_key_env": "K", "max_tokens": 100, "tier": "standard"}}}))
        with pytest.raises(ConfigError, match="routes"):
            ModelRouter(path)

    def test_model_fields_parsed(self, tmp_config, env_with_keys):
        router = ModelRouter(tmp_config)
        m = router.models["fast-model"]
        assert m["provider"] == "openai"
        assert m["model_id"] == "gpt-4o-mini"
        assert m["api_key_env"] == "TEST_OPENAI_KEY"
        assert m["max_tokens"] == 2048
        assert m["tier"] == "standard"


# --- Environment variable safety ---

class TestEnvSafety:
    def test_api_key_resolved_from_env(self, tmp_config, env_with_keys):
        router = ModelRouter(tmp_config)
        key = router.get_api_key("fast-model")
        assert key == "sk-test-openai-fake"

    def test_raises_on_missing_env_var(self, tmp_config):
        # No env_with_keys fixture -> keys not set
        router = ModelRouter(tmp_config)
        with pytest.raises(ConfigError, match="TEST_OPENAI_KEY"):
            router.get_api_key("fast-model")

    def test_api_key_never_in_config_object(self, tmp_config, env_with_keys):
        router = ModelRouter(tmp_config)
        for model_cfg in router.models.values():
            # Config stores env var NAME, never the actual key value
            assert not model_cfg.get("api_key", "").startswith("sk-")


# --- Route matching ---

class TestRouteMatching:
    def test_exact_match(self, tmp_config, env_with_keys):
        router = ModelRouter(tmp_config)
        assert router.resolve(customer="vip", task="reasoning") == "smart-model"

    def test_partial_match_customer(self, tmp_config, env_with_keys):
        router = ModelRouter(tmp_config)
        assert router.resolve(customer="vip") == "fast-model"

    def test_partial_match_task(self, tmp_config, env_with_keys):
        router = ModelRouter(tmp_config)
        assert router.resolve(task="reasoning") == "smart-model"

    def test_fallback_default(self, tmp_config, env_with_keys):
        router = ModelRouter(tmp_config)
        assert router.resolve() == "fast-model"
        assert router.resolve(customer="unknown", task="chat") == "fast-model"

    def test_first_match_wins(self, tmp_config, env_with_keys):
        router = ModelRouter(tmp_config)
        # customer=vip + task=reasoning -> first route (smart), not second (fast)
        assert router.resolve(customer="vip", task="reasoning") == "smart-model"

    def test_no_matching_route_raises(self, tmp_path, env_with_keys):
        """Config with no fallback route and non-matching context."""
        config = {
            "models": {
                "m": {"provider": "openai", "model_id": "x", "api_key_env": "TEST_OPENAI_KEY", "max_tokens": 100, "tier": "standard"},
            },
            "routes": [
                {"match": {"customer": "specific-only"}, "model": "m"},
            ],
        }
        path = tmp_path / "strict.yaml"
        path.write_text(yaml.dump(config))
        router = ModelRouter(path)
        with pytest.raises(ConfigError, match="No route"):
            router.resolve(customer="other")


# --- Provider adapters (mocked) ---

class TestProviderCall:
    def test_call_openai_dispatches(self, tmp_config, env_with_keys):
        router = ModelRouter(tmp_config)
        mock_connector = MagicMock(return_value="openai-resp")
        mock_connector.call = MagicMock(return_value="openai-resp")
        with patch("core_orchestrator.model_router.get_connector", return_value=mock_connector):
            result = router.call("fast-model", "hello")
            mock_connector.call.assert_called_once_with(
                model_id="gpt-4o-mini",
                api_key="sk-test-openai-fake",
                text="hello",
                max_tokens=2048,
                temperature=0.7,  # default
                base_url=None,
            )
            assert result == "openai-resp"

    def test_call_anthropic_dispatches(self, tmp_config, env_with_keys):
        router = ModelRouter(tmp_config)
        mock_connector = MagicMock()
        mock_connector.call = MagicMock(return_value="claude-resp")
        with patch("core_orchestrator.model_router.get_connector", return_value=mock_connector):
            result = router.call("smart-model", "think hard")
            mock_connector.call.assert_called_once_with(
                model_id="claude-opus-4-20250918",
                api_key="sk-test-anthropic-fake",
                text="think hard",
                max_tokens=8192,
                temperature=0.7,  # default
                base_url=None,
            )

    def test_call_unknown_model_raises(self, tmp_config, env_with_keys):
        router = ModelRouter(tmp_config)
        with pytest.raises(ConfigError, match="nonexistent"):
            router.call("nonexistent", "hello")

    def test_unknown_provider_raises(self, tmp_config, env_with_keys):
        router = ModelRouter(tmp_config)
        with patch("core_orchestrator.model_router.get_connector", side_effect=ValueError("bad")):
            with pytest.raises(ConfigError, match="provider"):
                router.call("fast-model", "hello")


# --- Temperature and base_url ---

class TestDynamicParams:
    def test_temperature_from_config(self, tmp_path, env_with_keys, monkeypatch):
        """Models can specify custom temperature in YAML."""
        config = {
            "models": {
                "creative": {
                    "provider": "openai",
                    "model_id": "gpt-4o",
                    "api_key_env": "TEST_OPENAI_KEY",
                    "max_tokens": 2048,
                    "tier": "standard",
                    "temperature": 1.2,
                },
            },
            "routes": [{"match": {}, "model": "creative"}],
        }
        path = tmp_path / "temp.yaml"
        path.write_text(yaml.dump(config))
        router = ModelRouter(path)
        mock_connector = MagicMock()
        mock_connector.call = MagicMock(return_value="hot")
        with patch("core_orchestrator.model_router.get_connector", return_value=mock_connector):
            router.call("creative", "be creative")
            call_kwargs = mock_connector.call.call_args[1]
            assert call_kwargs["temperature"] == 1.2

    def test_default_temperature_is_0_7(self, tmp_config, env_with_keys):
        """If no temperature in config, default to 0.7."""
        router = ModelRouter(tmp_config)
        mock_connector = MagicMock()
        mock_connector.call = MagicMock(return_value="ok")
        with patch("core_orchestrator.model_router.get_connector", return_value=mock_connector):
            router.call("fast-model", "hi")
            call_kwargs = mock_connector.call.call_args[1]
            assert call_kwargs["temperature"] == 0.7

    def test_base_url_from_env(self, tmp_path, monkeypatch):
        """base_url_env resolves to environment variable value."""
        monkeypatch.setenv("TEST_KEY", "sk-test")
        monkeypatch.setenv("CUSTOM_BASE_URL", "https://api.deepseek.com/v1")
        config = {
            "models": {
                "deepseek": {
                    "provider": "openai",
                    "model_id": "deepseek-chat",
                    "api_key_env": "TEST_KEY",
                    "max_tokens": 4096,
                    "tier": "standard",
                    "base_url_env": "CUSTOM_BASE_URL",
                },
            },
            "routes": [{"match": {}, "model": "deepseek"}],
        }
        path = tmp_path / "ds.yaml"
        path.write_text(yaml.dump(config))
        router = ModelRouter(path)
        mock_connector = MagicMock()
        mock_connector.call = MagicMock(return_value="ok")
        with patch("core_orchestrator.model_router.get_connector", return_value=mock_connector):
            router.call("deepseek", "hi")
            call_kwargs = mock_connector.call.call_args[1]
            assert call_kwargs["base_url"] == "https://api.deepseek.com/v1"

    def test_base_url_none_when_no_env_key(self, tmp_config, env_with_keys):
        """If no base_url_env, base_url is None (use provider default)."""
        router = ModelRouter(tmp_config)
        mock_connector = MagicMock()
        mock_connector.call = MagicMock(return_value="ok")
        with patch("core_orchestrator.model_router.get_connector", return_value=mock_connector):
            router.call("fast-model", "hi")
            call_kwargs = mock_connector.call.call_args[1]
            assert call_kwargs["base_url"] is None

    def test_base_url_none_when_env_var_not_set(self, tmp_path, monkeypatch):
        """If base_url_env is specified but env var is empty, base_url is None."""
        monkeypatch.setenv("TEST_KEY", "sk-test")
        # NOT setting MISSING_URL
        config = {
            "models": {
                "m": {
                    "provider": "openai",
                    "model_id": "m",
                    "api_key_env": "TEST_KEY",
                    "max_tokens": 100,
                    "tier": "standard",
                    "base_url_env": "MISSING_URL",
                },
            },
            "routes": [{"match": {}, "model": "m"}],
        }
        path = tmp_path / "m.yaml"
        path.write_text(yaml.dump(config))
        router = ModelRouter(path)
        mock_connector = MagicMock()
        mock_connector.call = MagicMock(return_value="ok")
        with patch("core_orchestrator.model_router.get_connector", return_value=mock_connector):
            router.call("m", "hi")
            call_kwargs = mock_connector.call.call_args[1]
            assert call_kwargs["base_url"] is None


# --- as_llm bridge ---

class TestAsLlm:
    def test_returns_callable(self, tmp_config, env_with_keys):
        router = ModelRouter(tmp_config)
        llm_fn = router.as_llm()
        assert callable(llm_fn)

    def test_as_llm_uses_resolved_model(self, tmp_config, env_with_keys):
        router = ModelRouter(tmp_config)
        with patch.object(router, "call", return_value="response") as mock_call:
            llm_fn = router.as_llm(customer="vip", task="reasoning")
            result = llm_fn("some text")
            mock_call.assert_called_once_with("smart-model", "some text")
            assert result == "response"

    def test_as_llm_with_default_route(self, tmp_config, env_with_keys):
        router = ModelRouter(tmp_config)
        with patch.object(router, "call", return_value="resp") as mock_call:
            llm_fn = router.as_llm()
            llm_fn("hello")
            mock_call.assert_called_once_with("fast-model", "hello")


# --- Gateway integration ---

class TestGatewayIntegration:
    def test_gateway_with_router_as_llm(self, tmp_config, env_with_keys):
        router = ModelRouter(tmp_config)
        with patch.object(router, "call", return_value="routed response"):
            llm_fn = router.as_llm(customer="vip")
            gw = LLMGateway(llm=llm_fn)
            result = gw.send("tell me about user@test.com")
            # PII sanitized
            assert "user@test.com" not in result["sanitized_input"]
            # Response came from router
            assert result["llm_response"] == "routed response"

    def test_gateway_pii_before_router(self, tmp_config, env_with_keys):
        """Verify sanitization happens BEFORE the text reaches the router."""
        received_texts = []
        def capture_call(model_name, text):
            received_texts.append(text)
            return "ok"

        router = ModelRouter(tmp_config)
        with patch.object(router, "call", side_effect=capture_call):
            llm_fn = router.as_llm()
            gw = LLMGateway(llm=llm_fn)
            gw.send("my email is secret@corp.com")
            assert len(received_texts) == 1
            assert "secret@corp.com" not in received_texts[0]
            assert "[EMAIL_REDACTED]" in received_texts[0]


# --- Real YAML config file ---

class TestRealConfig:
    def test_bundled_config_is_valid(self):
        """The models_config.yaml shipped with the project parses correctly."""
        config_path = Path(__file__).parent.parent.parent / "models_config.yaml"
        assert config_path.exists(), f"Missing {config_path}"
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
        assert "models" in cfg
        assert "routes" in cfg
        assert len(cfg["models"]) > 0
        assert len(cfg["routes"]) > 0
        # Every route references an existing model
        for route in cfg["routes"]:
            assert route["model"] in cfg["models"], f"Route references unknown model: {route['model']}"
