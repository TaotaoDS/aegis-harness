"""Retry utilities: exponential backoff + jitter for LLM and tool calls.

Built on ``tenacity``.  Gracefully degrades (runs without any retry) when
tenacity is not installed — the rest of the codebase has zero hard
dependency on it.

Public API
----------
with_retry(fn, /, *args, max_attempts, wait_min, wait_max, **kwargs)
    Call ``fn(*args, **kwargs)`` with automatic retries on transient errors.

is_retryable(exc)
    Predicate: True for HTTP 429 / 5xx and known transient error class names.

DEFAULT_LLM_ATTEMPTS, DEFAULT_WAIT_MIN_S, DEFAULT_WAIT_MAX_S
    Tuneable module-level defaults for LLM API calls.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_LLM_ATTEMPTS: int   = 4      # total attempts (first call + 3 retries)
DEFAULT_WAIT_MIN_S:   float = 1.0    # floor for the backoff window  (seconds)
DEFAULT_WAIT_MAX_S:   float = 60.0   # ceiling for the backoff window (seconds)
DEFAULT_MULTIPLIER:   float = 2.0    # doubles wait time each retry

# HTTP status codes that signal transient server-side trouble.
_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})

# SDK-level exception class names that are inherently transient.
# Checked by class name so we never need to import provider SDKs here.
_RETRYABLE_CLASS_NAMES = frozenset({
    "RateLimitError",
    "InternalServerError",
    "APIConnectionError",
    "APITimeoutError",
    "Timeout",
    "ConnectionError",
    "ServiceUnavailableError",
    "TimeoutError",    # Playwright navigation timeouts (also: stdlib asyncio.TimeoutError)
    "PlaywrightError", # Playwright generic network/protocol errors
})


# ---------------------------------------------------------------------------
# Retryable predicate
# ---------------------------------------------------------------------------

def is_retryable(exc: BaseException) -> bool:
    """Return True when *exc* is a transient error worth retrying.

    Checks (in order):
    1. The exception's ``status_code`` attribute (present on openai /
       anthropic HTTP error objects) — retries on 429 and any 5xx code.
    2. The exception class name — retries on well-known transient names
       (``RateLimitError``, ``APIConnectionError``, etc.).
    3. Falls through to False for everything else (e.g. ValueError, KeyError).
    """
    status = getattr(exc, "status_code", None)
    if status is not None:
        return int(status) in _RETRYABLE_STATUS_CODES
    return type(exc).__name__ in _RETRYABLE_CLASS_NAMES


# ---------------------------------------------------------------------------
# Core retry helper
# ---------------------------------------------------------------------------

def with_retry(
    fn: Callable,
    /,
    *args: Any,
    max_attempts: int = DEFAULT_LLM_ATTEMPTS,
    wait_min: float = DEFAULT_WAIT_MIN_S,
    wait_max: float = DEFAULT_WAIT_MAX_S,
    multiplier: float = DEFAULT_MULTIPLIER,
    reraise: bool = True,
    **kwargs: Any,
) -> Any:
    """Call ``fn(*args, **kwargs)`` with exponential-backoff retry.

    Only retries when :func:`is_retryable` returns ``True`` for the raised
    exception.  Non-transient exceptions (e.g. ``ValueError``, ``KeyError``)
    propagate immediately — no attempt is wasted.

    Parameters
    ----------
    fn          : Callable to invoke.
    max_attempts: Maximum total attempts (first call + retries).
    wait_min    : Floor for the backoff window in seconds.
    wait_max    : Ceiling for the backoff window in seconds.
    multiplier  : Exponential multiplier per retry (default 2 → doubles).
    reraise     : When ``True`` (default), re-raise the last exception after
                  all attempts are exhausted.  When ``False``, raise
                  ``tenacity.RetryError`` instead.

    Returns
    -------
    Return value of ``fn`` on success.

    Notes
    -----
    If ``tenacity`` is not installed the call is forwarded to ``fn`` directly
    with no retry logic (graceful degradation).
    """
    try:
        from tenacity import (
            retry,
            retry_if_exception,
            stop_after_attempt,
            wait_exponential,
        )
    except ImportError:
        # tenacity not available — single attempt, no retry
        return fn(*args, **kwargs)

    @retry(
        retry=retry_if_exception(is_retryable),
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(
            multiplier=multiplier,
            min=wait_min,
            max=wait_max,
        ),
        reraise=reraise,
    )
    def _call() -> Any:
        return fn(*args, **kwargs)

    return _call()
