"""Multi-model router with YAML config, dynamic parameters, and connector dispatch.

Loads model definitions and routing rules from a YAML file,
resolves API keys and base URLs from environment variables (never hardcoded),
and dispatches calls through the LLMConnector abstraction layer.

Supports any OpenAI-compatible provider (DeepSeek, Zhipu, Kimi, NVIDIA NIM, etc.)
via two equivalent patterns:

  Pattern A — env-var indirection (original, still supported):
      api_key_env: NVIDIA_API_KEY        # stores the env var *name*
      base_url_env: NVIDIA_BASE_URL      # stores the env var *name*

  Pattern B — inline ${VAR} interpolation (new, recommended for readability):
      api_key: ${NVIDIA_API_KEY}         # resolved at load time from .env / shell
      base_url: https://integrate.api.nvidia.com/v1   # literal or interpolated URL

Both patterns can be mixed freely within the same config file.
"""

import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import yaml
from dotenv import load_dotenv

from .llm_connector import ToolCall, ToolHandler, get_connector

_DEFAULT_TEMPERATURE = 0.7

# ---------------------------------------------------------------------------
# Module-level TTL config cache
# ---------------------------------------------------------------------------
# Stores: path → (load_timestamp, raw_yaml_dict)
# Key is the resolved absolute path string so different config files
# never share a cache entry.  Tests use unique tmp paths — they always
# miss the cache and read fresh, preserving isolation.

_CONFIG_CACHE: Dict[str, Tuple[float, dict]] = {}
_CACHE_LOCK   = threading.Lock()
_DEFAULT_TTL  = 30.0   # seconds


def _load_yaml_cached(config_path: str, ttl: float = _DEFAULT_TTL) -> dict:
    """Return the parsed YAML dict for ``config_path``.

    Re-reads the file when the cached entry is older than ``ttl`` seconds.
    Thread-safe via ``_CACHE_LOCK``.
    """
    now = time.monotonic()
    with _CACHE_LOCK:
        if config_path in _CONFIG_CACHE:
            cached_at, cached_dict = _CONFIG_CACHE[config_path]
            if now - cached_at < ttl:
                return cached_dict          # cache hit

        # Cache miss — (re)load from disk
        with open(config_path) as fh:
            raw = yaml.safe_load(fh)
        _CONFIG_CACHE[config_path] = (now, raw)
        return raw


def invalidate_model_cache(config_path: Optional[str] = None) -> None:
    """Invalidate the YAML config cache.

    Parameters
    ----------
    config_path:
        When given, only the entry for that path is removed.
        When ``None``, the entire cache is cleared (useful after a
        settings API call that may have changed the active model).
    """
    with _CACHE_LOCK:
        if config_path:
            _CONFIG_CACHE.pop(str(config_path), None)
        else:
            _CONFIG_CACHE.clear()


# ---------------------------------------------------------------------------
# YAML env-var interpolation
# ---------------------------------------------------------------------------

def _interpolate_env_vars(value: Any) -> Any:
    """Recursively replace ``${VAR_NAME}`` placeholders with os.environ values.

    Called after YAML loading so that any string in the config can reference
    environment variables using the ``${...}`` syntax familiar from Docker
    Compose and shell scripting.

    Unresolved variables (env var not set) are left as-is so that
    ``get_api_key()`` can raise a clear error later.

    Examples::

        api_key: ${NVIDIA_API_KEY}        →  api_key: "nvapi-xxxx"
        base_url: ${NVIDIA_BASE_URL}      →  base_url: "https://integrate..."
        base_url: https://literal.url/v1  →  unchanged (no placeholder)
    """
    if isinstance(value, dict):
        return {k: _interpolate_env_vars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_interpolate_env_vars(v) for v in value]
    if isinstance(value, str):
        def _replace(m: re.Match) -> str:
            return os.environ.get(m.group(1), m.group(0))
        return re.sub(r"\$\{([^}]+)\}", _replace, value)
    return value


class ConfigError(Exception):
    """Raised for invalid or missing configuration."""


class ModelRouter:
    """Load YAML config, resolve routes, dispatch through LLM connectors.

    Config caching
    --------------
    By default the YAML file is cached for ``cache_ttl`` seconds
    (default 30 s).  In production this means model-config changes made
    via the Settings UI take effect within 30 s without a server restart.
    In tests each instance receives a unique tmp-path so the cache never
    interferes between test cases.

    To force an immediate reload (e.g. right after a settings PUT), call
    ``invalidate_model_cache(config_path)``.
    """

    def __init__(
        self,
        config_path: Union[str, Path],
        env_path: Optional[Union[str, Path]] = None,
        cache_ttl: float = _DEFAULT_TTL,
    ):
        # Load .env before interpolation so ${VAR} references resolve correctly
        load_dotenv(dotenv_path=env_path or None)

        config_path = Path(config_path).resolve()
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")

        self._config_path = str(config_path)
        self._cache_ttl   = cache_ttl

        # Resolve ${VAR_NAME} placeholders throughout the entire config tree
        raw_cfg = _load_yaml_cached(self._config_path, ttl=cache_ttl)
        cfg = _interpolate_env_vars(raw_cfg)

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
        """Resolve the API key for a model.

        Supports two patterns (can be mixed within the same config):

        * **Pattern B** — ``api_key: ${NVIDIA_API_KEY}`` (or a literal string):
          The value has already been interpolated by ``_interpolate_env_vars``
          at load time; just return it directly.

        * **Pattern A** — ``api_key_env: NVIDIA_API_KEY``:
          The field stores the *name* of an environment variable which is
          resolved lazily here via ``os.environ``.
        """
        model_cfg = self._models.get(model_name)
        if not model_cfg:
            raise ConfigError(f"Unknown model: '{model_name}'")

        # Pattern B: direct api_key field (already interpolated or literal)
        if "api_key" in model_cfg:
            key = model_cfg["api_key"]
            if not key:
                raise ConfigError(
                    f"api_key for model '{model_name}' is empty. "
                    f"Check that the referenced environment variable is set."
                )
            return key

        # Pattern A: api_key_env holds the env var name
        env_var = model_cfg.get("api_key_env")
        if not env_var:
            raise ConfigError(
                f"Model '{model_name}' has neither 'api_key' nor 'api_key_env' configured."
            )
        key = os.environ.get(env_var)
        if not key:
            raise ConfigError(
                f"Environment variable '{env_var}' not set (required by model '{model_name}')"
            )
        return key

    def _get_base_url(self, model_name: str) -> Optional[str]:
        """Resolve the base URL for a model.

        Returns ``None`` if unconfigured, which tells the connector to use
        its default endpoint (e.g. ``https://api.openai.com/v1``).

        Supports two patterns:

        * **Pattern B** — ``base_url: https://integrate.api.nvidia.com/v1``
          (literal URL or ``${VAR}`` already interpolated at load time).

        * **Pattern A** — ``base_url_env: NVIDIA_BASE_URL``
          (env var name resolved lazily here via ``os.environ``).
        """
        model_cfg = self._models.get(model_name, {})

        # Pattern B: direct base_url field (already interpolated or literal)
        if "base_url" in model_cfg:
            return model_cfg["base_url"] or None

        # Pattern A: base_url_env holds the env var name
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
        """Call a specific model by name, dispatching through its connector.

        Transient API errors (429, 5xx, rate-limit exceptions) are retried
        automatically using exponential back-off via :mod:`.retry_utils`.
        Non-transient errors propagate immediately.
        """
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

        from .retry_utils import with_retry
        return with_retry(
            connector.call,
            model_id=model_cfg["model_id"],
            api_key=api_key,
            text=text,
            max_tokens=model_cfg["max_tokens"],
            temperature=temperature,
            base_url=base_url,
        )

    def call_with_tools(
        self,
        model_name: str,
        *,
        system: str,
        user_prompt: str,
        tools: List[Dict[str, Any]],
        max_rounds: int = 10,
        tool_handler: ToolHandler = None,
    ) -> List[ToolCall]:
        """Call a model with Tool Use (Function Calling).

        If tool_handler is provided, it is invoked for each tool call and
        its return value (a JSON string) is sent back to the model as the
        tool result. This enables tools like read_file to return real content.

        Returns a list of ToolCall objects collected across all rounds.
        """
        model_cfg = self._models.get(model_name)
        if not model_cfg:
            raise ConfigError(f"Unknown model: '{model_name}'")

        api_key = self.get_api_key(model_name)
        base_url = self._get_base_url(model_name)
        temperature = model_cfg.get("temperature", _DEFAULT_TEMPERATURE)

        connector = get_connector(model_cfg["provider"])

        from .retry_utils import with_retry
        return with_retry(
            connector.call_with_tools,
            model_id=model_cfg["model_id"],
            api_key=api_key,
            system=system,
            user_prompt=user_prompt,
            tools=tools,
            max_tokens=model_cfg["max_tokens"],
            temperature=temperature,
            base_url=base_url,
            max_rounds=max_rounds,
            tool_handler=tool_handler,
        )

    def as_llm(self, **context: str) -> Callable[[str], str]:
        """Return a Callable[[str], str] suitable for LLMGateway(llm=...).

        The model is resolved once at creation time based on the context.
        """
        model_name = self.resolve(**context)

        def _llm(text: str) -> str:
            return self.call(model_name, text)

        return _llm

    def as_tool_llm(self, **context: str) -> Callable:
        """Return a callable for Tool Use calls.

        Signature: (system, user_prompt, tools, tool_handler=None) -> List[ToolCall]

        The model is resolved once at creation time based on the context.
        """
        model_name = self.resolve(**context)

        def _tool_llm(
            system: str,
            user_prompt: str,
            tools: List[Dict[str, Any]],
            tool_handler: ToolHandler = None,
        ) -> List[ToolCall]:
            return self.call_with_tools(
                model_name,
                system=system,
                user_prompt=user_prompt,
                tools=tools,
                tool_handler=tool_handler,
            )

        return _tool_llm
