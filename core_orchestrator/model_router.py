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

import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import yaml
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

from .llm_connector import ToolCall, ToolHandler, get_connector


# ---------------------------------------------------------------------------
# Failover-worthy error classification
# ---------------------------------------------------------------------------

# HTTP status codes that mean "this model/account is permanently unavailable
# right now" — switching to a different provider will help.
_FAILOVER_STATUS_CODES = frozenset({
    401,  # Unauthorized / invalid API key
    402,  # Payment required / quota exhausted
    403,  # Forbidden / account suspended
    529,  # Anthropic-specific "overloaded"
})

# SDK exception class names that indicate the current model is unusable
# and a different provider should be tried.
_FAILOVER_CLASS_NAMES = frozenset({
    "AuthenticationError",
    "PermissionDeniedError",
    "InsufficientQuotaError",
    "QuotaExceededError",
    "BillingError",
})


def _is_failover_worthy(exc: BaseException) -> bool:
    """Return True when the error signals this model is unusable and we should switch.

    Distinct from is_retryable(): retryable errors are brief (429 burst, server
    blip) and recover with backoff on the *same* model.  Failover-worthy errors
    are persistent (bad key, quota exhausted, account suspended) and require
    switching to a *different* model.
    """
    status = getattr(exc, "status_code", None)
    if status is not None:
        return int(status) in _FAILOVER_STATUS_CODES
    return type(exc).__name__ in _FAILOVER_CLASS_NAMES


# ---------------------------------------------------------------------------
# Per-model circuit breaker
# ---------------------------------------------------------------------------

_CIRCUIT_COOLDOWN_S = 300   # 5-minute cooldown before HALF-OPEN probe
_CIRCUIT_THRESHOLD  = 2     # consecutive failures before OPEN


class _ModelHealthTracker:
    """Thread-safe per-model circuit breaker (CLOSED → OPEN → HALF-OPEN → CLOSED).

    CLOSED  — healthy; requests flow normally.
    OPEN    — unhealthy; requests are skipped (failover immediately).
    HALF-OPEN — cooldown elapsed; one probe request is allowed.  Success → CLOSED,
               failure → OPEN again with a fresh cooldown.
    """

    def __init__(self, cooldown: float = _CIRCUIT_COOLDOWN_S, threshold: int = _CIRCUIT_THRESHOLD):
        self._cooldown   = cooldown
        self._threshold  = threshold
        self._failures:   Dict[str, int]   = {}
        self._open_until: Dict[str, float] = {}
        self._lock = threading.Lock()

    def is_healthy(self, model: str) -> bool:
        with self._lock:
            deadline = self._open_until.get(model)
            if deadline is None:
                return True                          # CLOSED
            if time.monotonic() >= deadline:
                del self._open_until[model]          # → HALF-OPEN
                self._failures.pop(model, None)
                logger.info("[Circuit] '%s' HALF-OPEN — allowing probe request", model)
                return True
            return False                             # OPEN

    def record_success(self, model: str) -> None:
        with self._lock:
            was_open = model in self._open_until
            self._failures.pop(model, None)
            self._open_until.pop(model, None)
        if was_open:
            logger.info("[Circuit] '%s' back to CLOSED after successful probe", model)

    def record_failure(self, model: str) -> None:
        with self._lock:
            n = self._failures.get(model, 0) + 1
            self._failures[model] = n
            if n >= self._threshold:
                self._open_until[model] = time.monotonic() + self._cooldown
                logger.warning(
                    "[Circuit] '%s' OPEN after %d failures — cooldown %ds",
                    model, n, int(self._cooldown),
                )

    def open_models(self) -> List[str]:
        now = time.monotonic()
        with self._lock:
            return [m for m, d in self._open_until.items() if now < d]

    def reset(self, model: Optional[str] = None) -> None:
        """Manually close a circuit (useful for testing or admin override)."""
        with self._lock:
            if model:
                self._failures.pop(model, None)
                self._open_until.pop(model, None)
            else:
                self._failures.clear()
                self._open_until.clear()


# Module-level singleton — shared across all ModelRouter instances in the process
_health = _ModelHealthTracker()

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
        self._routes = list(cfg["routes"])   # mutable copy

        # Allow env-var override of the preferred model.
        # AEGIS_DEFAULT_MODEL=claude-sonnet  →  prepend a high-priority catch-all route.
        preferred_override = (
            os.environ.get("AEGIS_DEFAULT_MODEL")
            or cfg.get("execution", {}).get("preferred_model", "")
        )
        if preferred_override and preferred_override in self._models:
            self._routes.insert(0, {"match": {}, "model": preferred_override})
            logger.info("[ModelRouter] Preferred model override: '%s'", preferred_override)
        elif preferred_override:
            logger.warning(
                "[ModelRouter] AEGIS_DEFAULT_MODEL='%s' not found in models config — ignored",
                preferred_override,
            )

        self._log_key_availability()

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

    # -----------------------------------------------------------------------
    # Key availability helpers
    # -----------------------------------------------------------------------

    def is_key_available(self, model_name: str) -> bool:
        """Return True iff the model's API key is set, non-empty, and not a placeholder."""
        try:
            key = self.get_api_key(model_name)
            # Reject obvious template placeholders (e.g. sk-xxxxx, nvapi-xxxxx)
            if "xxxxx" in key or key.endswith("-placeholder"):
                return False
            return True
        except ConfigError:
            return False

    def available_models(self) -> List[str]:
        """Return model names whose API keys are currently set."""
        return [name for name in self._models if self.is_key_available(name)]

    def _log_key_availability(self) -> None:
        """Log a one-time summary of which models have valid keys."""
        ok, missing = [], []
        for name in self._models:
            (ok if self.is_key_available(name) else missing).append(name)
        logger.info("[ModelRouter] Available models (%d): %s", len(ok), ok)
        if missing:
            logger.warning(
                "[ModelRouter] Models with missing/empty API key (%d) — will be "
                "skipped during routing: %s",
                len(missing),
                missing,
            )

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
        """Match context against routes, returning the first model with a valid API key.

        Routes are evaluated top-to-bottom.  If a matched route's model has no
        valid key, that route is silently skipped and evaluation continues to the
        next route.  This means you can list preferred providers first and cheaper
        fallbacks last — the router picks whichever one is actually configured.

        If every route is skipped (all keys missing), the router falls back to the
        first model in the config that *does* have a key, ensuring at least one
        provider is always tried.

        Raises ConfigError only when no model in the entire config has a key set.
        """
        skipped: List[str] = []   # routes that matched context but had missing keys

        for route in self._routes:
            match_criteria = route.get("match", {})
            if all(context.get(k) == v for k, v in match_criteria.items()):
                model_name = route["model"]
                if self.is_key_available(model_name):
                    return model_name
                skipped.append(model_name)
                logger.debug(
                    "[ModelRouter] Route matched but model '%s' has no valid key — skipping",
                    model_name,
                )

        if skipped:
            # At least one route matched context, but every matched model lacked a key.
            # Last resort: use the first model in the config that has any valid key.
            fallback_candidates = self.available_models()
            if fallback_candidates:
                chosen = fallback_candidates[0]
                logger.warning(
                    "[ModelRouter] All matched routes had missing API keys (skipped: %s). "
                    "Falling back to first available model: '%s'",
                    skipped,
                    chosen,
                )
                return chosen
            raise ConfigError(
                "No model with a valid API key is available. "
                f"Routes tried (all keys missing): {skipped}. "
                "Please set at least one API key in your .env file."
            )

        raise ConfigError(f"No route matched context: {context}")

    def call(self, model_name: str, text: str) -> str:
        """Call a specific model by name, dispatching through its connector.

        Transient API errors (429, 5xx, rate-limit exceptions) are retried
        automatically using exponential back-off via :mod:`.retry_utils`.
        Non-transient errors propagate immediately.

        Raises InsufficientCreditError (→ HTTP 402) when the active billing
        context has a depleted credit balance.
        """
        from .billing import check_credit
        check_credit()

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

        Raises InsufficientCreditError (→ HTTP 402) when the active billing
        context has a depleted credit balance.
        """
        from .billing import check_credit
        check_credit()

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

    # -----------------------------------------------------------------------
    # Failover helpers
    # -----------------------------------------------------------------------

    def _failover_candidates(self, preferred: str) -> List[str]:
        """Return an ordered list of models to try: preferred first, then the rest.

        Only includes models that currently have a valid API key.  The preferred
        model is always first (even if its circuit is currently OPEN — we still
        include it so the HALF-OPEN probe can happen naturally).
        """
        available = self.available_models()
        others = [m for m in available if m != preferred]
        return ([preferred] if preferred in self._models else []) + others

    def call_with_failover(self, preferred_model: str, text: str) -> str:
        """Call ``preferred_model``, failing over to alternatives on persistent errors.

        Transient errors (429 burst, 5xx blip) are retried on the *same* model
        via the existing ``with_retry`` logic inside ``call()``.

        Failover-worthy errors (bad key, quota exhausted, account suspended)
        trigger an immediate switch to the next healthy model in priority order.
        The circuit breaker is updated on each outcome.

        Returns the response text.  Raises the last exception only if every
        candidate model was tried and failed.
        """
        candidates = self._failover_candidates(preferred_model)
        last_exc: Optional[Exception] = None

        for model_name in candidates:
            if not _health.is_healthy(model_name):
                logger.debug("[Failover] Skipping '%s' — circuit OPEN", model_name)
                continue
            try:
                result = self.call(model_name, text)
                _health.record_success(model_name)
                if model_name != preferred_model:
                    logger.warning(
                        "[Failover] Used '%s' (preferred '%s' unavailable)",
                        model_name, preferred_model,
                    )
                return result
            except Exception as exc:
                if _is_failover_worthy(exc):
                    _health.record_failure(model_name)
                    logger.warning(
                        "[Failover] '%s' failed (%s: %s) — trying next model",
                        model_name, type(exc).__name__, str(exc)[:120],
                    )
                    last_exc = exc
                    continue
                raise   # non-failover errors propagate immediately

        if last_exc:
            raise last_exc
        raise ConfigError(
            f"All failover candidates exhausted for '{preferred_model}'. "
            f"Tried: {candidates}. Check API keys and account status."
        )

    def call_with_tools_failover(
        self,
        preferred_model: str,
        *,
        system: str,
        user_prompt: str,
        tools: List[Dict[str, Any]],
        max_rounds: int = 10,
        tool_handler: ToolHandler = None,
    ) -> List[ToolCall]:
        """call_with_tools() with the same multi-model failover semantics."""
        candidates = self._failover_candidates(preferred_model)
        last_exc: Optional[Exception] = None

        for model_name in candidates:
            if not _health.is_healthy(model_name):
                continue
            try:
                result = self.call_with_tools(
                    model_name,
                    system=system,
                    user_prompt=user_prompt,
                    tools=tools,
                    max_rounds=max_rounds,
                    tool_handler=tool_handler,
                )
                _health.record_success(model_name)
                if model_name != preferred_model:
                    logger.warning(
                        "[Failover] Tool-use used '%s' (preferred '%s' unavailable)",
                        model_name, preferred_model,
                    )
                return result
            except Exception as exc:
                if _is_failover_worthy(exc):
                    _health.record_failure(model_name)
                    logger.warning(
                        "[Failover] Tool-use '%s' failed (%s) — trying next",
                        model_name, type(exc).__name__,
                    )
                    last_exc = exc
                    continue
                raise

        if last_exc:
            raise last_exc
        raise ConfigError(f"All failover candidates exhausted for tool-use '{preferred_model}'.")

    # -----------------------------------------------------------------------
    # LLM callable factories
    # -----------------------------------------------------------------------

    def as_llm(self, **context: str) -> Callable[[str], str]:
        """Return a Callable[[str], str] suitable for LLMGateway(llm=...).

        The preferred model is resolved at creation time; the actual model used
        at call time may differ if the preferred model's circuit is OPEN.
        """
        preferred = self.resolve(**context)

        def _llm(text: str) -> str:
            return self.call_with_failover(preferred, text)

        return _llm

    def as_tool_llm(self, **context: str) -> Callable:
        """Return a callable for Tool Use calls with failover.

        Signature: (system, user_prompt, tools, tool_handler=None) -> List[ToolCall]
        """
        preferred = self.resolve(**context)

        def _tool_llm(
            system: str,
            user_prompt: str,
            tools: List[Dict[str, Any]],
            tool_handler: ToolHandler = None,
        ) -> List[ToolCall]:
            return self.call_with_tools_failover(
                preferred,
                system=system,
                user_prompt=user_prompt,
                tools=tools,
                tool_handler=tool_handler,
            )

        return _tool_llm

    def as_escalated_tool_llm(self, skip_model: Optional[str] = None, **context: str) -> Callable:
        """Return a tool_llm callable that skips ``skip_model`` (the failed preferred).

        Used by ResilienceManager for Layer-2 escalation: force a different model
        than the one that failed in Layer 1.
        """
        candidates = [
            m for m in self._failover_candidates(self.resolve(**context))
            if m != skip_model
        ]
        if not candidates:
            # If we somehow have no alternatives, fall back to resolve normally
            candidates = [self.resolve(**context)]

        preferred = candidates[0]
        logger.info("[Escalation] Escalated tool_llm using '%s' (skipping '%s')", preferred, skip_model)

        def _escalated_tool_llm(
            system: str,
            user_prompt: str,
            tools: List[Dict[str, Any]],
            tool_handler: ToolHandler = None,
        ) -> List[ToolCall]:
            return self.call_with_tools_failover(
                preferred,
                system=system,
                user_prompt=user_prompt,
                tools=tools,
                tool_handler=tool_handler,
            )

        return _escalated_tool_llm
