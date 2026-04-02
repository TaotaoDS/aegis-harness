"""Multi-model router with YAML config, dynamic parameters, and connector dispatch.

Loads model definitions and routing rules from a YAML file,
resolves API keys and base URLs from environment variables (never hardcoded),
and dispatches calls through the LLMConnector abstraction layer.

Supports any OpenAI-compatible provider (DeepSeek, Zhipu, Kimi, etc.)
via base_url_env, and allows per-model temperature configuration.
"""

import os
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Union

import yaml
from dotenv import load_dotenv

from .llm_connector import get_connector

_DEFAULT_TEMPERATURE = 0.7


class ConfigError(Exception):
    """Raised for invalid or missing configuration."""


class ModelRouter:
    """Load YAML config, resolve routes, dispatch through LLM connectors."""

    def __init__(self, config_path: Union[str, Path], env_path: Optional[Union[str, Path]] = None):
        # Load .env if provided (or auto-discover)
        load_dotenv(dotenv_path=env_path or None)

        config_path = Path(config_path)
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")

        with open(config_path) as f:
            cfg = yaml.safe_load(f)

        if "models" not in cfg:
            raise ConfigError("Config missing required key: 'models'")
        if "routes" not in cfg:
            raise ConfigError("Config missing required key: 'routes'")

        self._models: Dict[str, Dict[str, Any]] = cfg["models"]
        self._routes = cfg["routes"]

    @property
    def models(self) -> Dict[str, Dict[str, Any]]:
        return self._models

    def get_api_key(self, model_name: str) -> str:
        """Resolve the API key for a model from environment variables."""
        model_cfg = self._models.get(model_name)
        if not model_cfg:
            raise ConfigError(f"Unknown model: '{model_name}'")
        env_var = model_cfg["api_key_env"]
        key = os.environ.get(env_var)
        if not key:
            raise ConfigError(
                f"Environment variable '{env_var}' not set (required by model '{model_name}')"
            )
        return key

    def _get_base_url(self, model_name: str) -> Optional[str]:
        """Resolve the base URL for a model from environment variables.

        Returns None if base_url_env is not configured or the env var is unset,
        which tells the connector to use its default endpoint.
        """
        model_cfg = self._models.get(model_name, {})
        env_var = model_cfg.get("base_url_env")
        if not env_var:
            return None
        return os.environ.get(env_var) or None

    def resolve(self, **context: str) -> str:
        """Match context against routes, return the first matching model name."""
        for route in self._routes:
            match_criteria = route.get("match", {})
            if all(context.get(k) == v for k, v in match_criteria.items()):
                return route["model"]
        raise ConfigError(f"No route matched context: {context}")

    def call(self, model_name: str, text: str) -> str:
        """Call a specific model by name, dispatching through its connector."""
        model_cfg = self._models.get(model_name)
        if not model_cfg:
            raise ConfigError(f"Unknown model: '{model_name}'")

        api_key = self.get_api_key(model_name)
        base_url = self._get_base_url(model_name)
        temperature = model_cfg.get("temperature", _DEFAULT_TEMPERATURE)

        try:
            connector = get_connector(model_cfg["provider"])
        except ValueError as e:
            raise ConfigError(f"Unknown provider: '{model_cfg['provider']}'") from e

        return connector.call(
            model_id=model_cfg["model_id"],
            api_key=api_key,
            text=text,
            max_tokens=model_cfg["max_tokens"],
            temperature=temperature,
            base_url=base_url,
        )

    def as_llm(self, **context: str) -> Callable[[str], str]:
        """Return a Callable[[str], str] suitable for LLMGateway(llm=...).

        The model is resolved once at creation time based on the context.
        """
        model_name = self.resolve(**context)

        def _llm(text: str) -> str:
            return self.call(model_name, text)

        return _llm
