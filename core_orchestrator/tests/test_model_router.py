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

    def test_resolve_skips_model_with_missing_key(self, tmp_path):
        """When first route's model has no key, falls back to next route whose key IS set."""
        config = {
            "models": {
                "no-key-model": {"provider": "openai", "model_id": "x", "api_key_env": "MISSING_KEY_XYZ", "max_tokens": 100, "tier": "standard"},
                "has-key-model": {"provider": "openai", "model_id": "y", "api_key_env": "PRESENT_KEY_ABC", "max_tokens": 100, "tier": "standard"},
            },
            "routes": [
                {"match": {}, "model": "no-key-model"},
                {"match": {}, "model": "has-key-model"},
            ],
        }
        path = tmp_path / "fallback.yaml"
        path.write_text(yaml.dump(config))
        with patch.dict(os.environ, {"PRESENT_KEY_ABC": "real-key-value"}, clear=False):
            os.environ.pop("MISSING_KEY_XYZ", None)
            router = ModelRouter(path)
            assert router.resolve() == "has-key-model"

    def test_resolve_fallback_to_any_available_when_all_routes_missing(self, tmp_path):
        """When ALL routes have missing keys, fall back to any model that has a key."""
        config = {
            "models": {
                "route-model":   {"provider": "openai", "model_id": "x", "api_key_env": "MISSING_A", "max_tokens": 100, "tier": "standard"},
                "offroute-model": {"provider": "openai", "model_id": "y", "api_key_env": "PRESENT_B", "max_tokens": 100, "tier": "standard"},
            },
            "routes": [
                {"match": {}, "model": "route-model"},
            ],
        }
        path = tmp_path / "allskip.yaml"
        path.write_text(yaml.dump(config))
        with patch.dict(os.environ, {"PRESENT_B": "real-key-value"}, clear=False):
            os.environ.pop("MISSING_A", None)
            router = ModelRouter(path)
            assert router.resolve() == "offroute-model"

    def test_resolve_raises_when_no_key_anywhere(self, tmp_path):
        """ConfigError raised when every model in the config has a missing key."""
        config = {
            "models": {
                "m1": {"provider": "openai", "model_id": "x", "api_key_env": "MISSING_1", "max_tokens": 100, "tier": "standard"},
                "m2": {"provider": "openai", "model_id": "y", "api_key_env": "MISSING_2", "max_tokens": 100, "tier": "standard"},
            },
            "routes": [
                {"match": {}, "model": "m1"},
            ],
        }
        path = tmp_path / "nokeys.yaml"
        path.write_text(yaml.dump(config))
        for var in ("MISSING_1", "MISSING_2"):
            os.environ.pop(var, None)
        router = ModelRouter(path)
        with pytest.raises(ConfigError, match="No model with a valid API key"):
            router.resolve()


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


# --- ${VAR} interpolation ---

class TestEnvVarInterpolation:
    """_interpolate_env_vars() resolves ${VAR} placeholders at load time."""

    def _write_config(self, tmp_path, model_cfg: dict) -> Path:
        config = {
            "models": {"m": model_cfg},
            "routes": [{"match": {}, "model": "m"}],
        }
        path = tmp_path / "cfg.yaml"
        path.write_text(yaml.dump(config))
        return path

    def test_interpolates_api_key_field(self, tmp_path, monkeypatch):
        """api_key: ${VAR} is resolved to the env var value at load time."""
        monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test-secret")
        path = self._write_config(tmp_path, {
            "provider": "openai",
            "model_id": "meta/llama-3.3-70b-instruct",
            "api_key": "${NVIDIA_API_KEY}",
            "base_url": "https://integrate.api.nvidia.com/v1",
            "max_tokens": 4096,
        })
        router = ModelRouter(path)
        assert router.get_api_key("m") == "nvapi-test-secret"

    def test_interpolates_base_url_field(self, tmp_path, monkeypatch):
        """base_url: ${VAR} is resolved to the env var value at load time."""
        monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")
        monkeypatch.setenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
        path = self._write_config(tmp_path, {
            "provider": "openai",
            "model_id": "meta/llama-3.3-70b-instruct",
            "api_key": "${NVIDIA_API_KEY}",
            "base_url": "${NVIDIA_BASE_URL}",
            "max_tokens": 4096,
        })
        router = ModelRouter(path)
        assert router._get_base_url("m") == "https://integrate.api.nvidia.com/v1"

    def test_literal_base_url_no_interpolation_needed(self, tmp_path, monkeypatch):
        """base_url: https://... (literal) works without any ${} syntax."""
        monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")
        path = self._write_config(tmp_path, {
            "provider": "openai",
            "model_id": "meta/llama-3.3-70b-instruct",
            "api_key": "${NVIDIA_API_KEY}",
            "base_url": "https://integrate.api.nvidia.com/v1",
            "max_tokens": 4096,
        })
        router = ModelRouter(path)
        assert router._get_base_url("m") == "https://integrate.api.nvidia.com/v1"

    def test_unresolved_placeholder_kept_as_is(self, tmp_path, monkeypatch):
        """If the env var is not set, the placeholder string is preserved
        so get_api_key() can raise a clear ConfigError."""
        monkeypatch.delenv("UNSET_KEY_12345", raising=False)
        path = self._write_config(tmp_path, {
            "provider": "openai",
            "model_id": "x",
            "api_key": "${UNSET_KEY_12345}",
            "base_url": "https://example.com/v1",
            "max_tokens": 100,
        })
        router = ModelRouter(path)
        # The unresolved placeholder is non-empty — but we can check that
        # the value still contains the placeholder text (not silently empty)
        raw_key = router._models["m"]["api_key"]
        assert "${UNSET_KEY_12345}" in raw_key

    def test_interpolation_does_not_affect_non_string_fields(self, tmp_path, monkeypatch):
        """Integer/boolean fields are untouched by interpolation."""
        monkeypatch.setenv("MY_KEY", "sk-test")
        path = self._write_config(tmp_path, {
            "provider": "openai",
            "model_id": "x",
            "api_key": "${MY_KEY}",
            "base_url": "https://example.com/v1",
            "max_tokens": 8192,
            "temperature": 0.3,
        })
        router = ModelRouter(path)
        assert router._models["m"]["max_tokens"] == 8192
        assert router._models["m"]["temperature"] == 0.3

    def test_mixed_old_and_new_pattern_in_same_config(self, tmp_path, monkeypatch):
        """Pattern A (api_key_env) and Pattern B (api_key: ${VAR}) can coexist."""
        monkeypatch.setenv("OLD_KEY", "sk-old-style")
        monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-new-style")
        config = {
            "models": {
                "old-model": {
                    "provider": "openai",
                    "model_id": "gpt-4o",
                    "api_key_env": "OLD_KEY",
                    "max_tokens": 2048,
                },
                "new-model": {
                    "provider": "openai",
                    "model_id": "meta/llama-3.3-70b-instruct",
                    "api_key": "${NVIDIA_API_KEY}",
                    "base_url": "https://integrate.api.nvidia.com/v1",
                    "max_tokens": 4096,
                },
            },
            "routes": [{"match": {}, "model": "old-model"}],
        }
        path = tmp_path / "mixed.yaml"
        path.write_text(yaml.dump(config))
        router = ModelRouter(path)
        assert router.get_api_key("old-model") == "sk-old-style"
        assert router.get_api_key("new-model") == "nvapi-new-style"
        assert router._get_base_url("new-model") == "https://integrate.api.nvidia.com/v1"


# --- Direct api_key / base_url fields ---

class TestDirectFields:
    """Pattern B: api_key and base_url as direct YAML fields (not _env variants)."""

    def test_get_api_key_from_direct_field(self, tmp_path, monkeypatch):
        """api_key field takes precedence over api_key_env."""
        monkeypatch.setenv("SOME_ENV_KEY", "should-not-be-used")
        config = {
            "models": {"m": {
                "provider": "openai",
                "model_id": "x",
                "api_key": "direct-key-value",
                "api_key_env": "SOME_ENV_KEY",   # should be ignored
                "max_tokens": 100,
            }},
            "routes": [{"match": {}, "model": "m"}],
        }
        path = tmp_path / "cfg.yaml"
        path.write_text(yaml.dump(config))
        router = ModelRouter(path)
        assert router.get_api_key("m") == "direct-key-value"

    def test_get_api_key_raises_when_direct_field_empty(self, tmp_path):
        config = {
            "models": {"m": {
                "provider": "openai",
                "model_id": "x",
                "api_key": "",
                "max_tokens": 100,
            }},
            "routes": [{"match": {}, "model": "m"}],
        }
        path = tmp_path / "cfg.yaml"
        path.write_text(yaml.dump(config))
        router = ModelRouter(path)
        with pytest.raises(ConfigError, match="empty"):
            router.get_api_key("m")

    def test_base_url_direct_field_returned(self, tmp_path, monkeypatch):
        """base_url direct field is returned without env var lookup."""
        monkeypatch.setenv("TEST_KEY", "sk-test")
        config = {
            "models": {"m": {
                "provider": "openai",
                "model_id": "x",
                "api_key_env": "TEST_KEY",
                "base_url": "https://custom.endpoint.com/v1",
                "max_tokens": 100,
            }},
            "routes": [{"match": {}, "model": "m"}],
        }
        path = tmp_path / "cfg.yaml"
        path.write_text(yaml.dump(config))
        router = ModelRouter(path)
        assert router._get_base_url("m") == "https://custom.endpoint.com/v1"

    def test_base_url_direct_overrides_base_url_env(self, tmp_path, monkeypatch):
        """base_url takes precedence over base_url_env when both are present."""
        monkeypatch.setenv("TEST_KEY", "sk-test")
        monkeypatch.setenv("OTHER_URL", "https://should-not-use.com/v1")
        config = {
            "models": {"m": {
                "provider": "openai",
                "model_id": "x",
                "api_key_env": "TEST_KEY",
                "base_url": "https://direct.url/v1",
                "base_url_env": "OTHER_URL",
                "max_tokens": 100,
            }},
            "routes": [{"match": {}, "model": "m"}],
        }
        path = tmp_path / "cfg.yaml"
        path.write_text(yaml.dump(config))
        router = ModelRouter(path)
        assert router._get_base_url("m") == "https://direct.url/v1"

    def test_nvidia_nim_pattern_dispatches_correctly(self, tmp_path, monkeypatch):
        """Full NVIDIA NIM Pattern B config dispatches to OpenAI connector."""
        monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test-1234")
        config = {
            "models": {"nvidia-llama": {
                "provider": "openai",
                "model_id": "meta/llama-3.3-70b-instruct",
                "api_key": "${NVIDIA_API_KEY}",
                "base_url": "https://integrate.api.nvidia.com/v1",
                "max_tokens": 4096,
                "temperature": 0.2,
            }},
            "routes": [{"match": {}, "model": "nvidia-llama"}],
        }
        path = tmp_path / "nvidia.yaml"
        path.write_text(yaml.dump(config))
        router = ModelRouter(path)

        mock_connector = MagicMock()
        mock_connector.call = MagicMock(return_value="llama-response")
        with patch("core_orchestrator.model_router.get_connector", return_value=mock_connector):
            result = router.call("nvidia-llama", "Hello from NVIDIA")
            mock_connector.call.assert_called_once_with(
                model_id="meta/llama-3.3-70b-instruct",
                api_key="nvapi-test-1234",
                text="Hello from NVIDIA",
                max_tokens=4096,
                temperature=0.2,
                base_url="https://integrate.api.nvidia.com/v1",
            )
            assert result == "llama-response"
