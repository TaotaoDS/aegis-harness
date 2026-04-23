"""Tests for retry_utils: exponential-backoff retry for LLM/tool calls.

Coverage:
  - is_retryable: HTTP status codes 429/5xx, transient class names, non-retryable
  - with_retry: succeeds on first attempt, retries on retryable error,
    propagates non-retryable error immediately (no wasted attempt),
    exhausts all attempts and re-raises, reraise=False raises RetryError,
    graceful degradation when tenacity not available
  - Retry count verification (exact number of calls)
"""

import pytest

from core_orchestrator.retry_utils import (
    DEFAULT_LLM_ATTEMPTS,
    DEFAULT_MULTIPLIER,
    DEFAULT_WAIT_MAX_S,
    DEFAULT_WAIT_MIN_S,
    is_retryable,
    with_retry,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeAPIError(Exception):
    """Mimics openai / anthropic SDK HTTP errors with a status_code attr."""
    def __init__(self, status_code: int):
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


# Names must match _RETRYABLE_CLASS_NAMES exactly so is_retryable() recognises them.
class RateLimitError(Exception):
    """Mimics openai.RateLimitError (no status_code attr)."""


class APIConnectionError(Exception):
    """Mimics openai.APIConnectionError."""


# ---------------------------------------------------------------------------
# TestIsRetryable
# ---------------------------------------------------------------------------

class TestIsRetryable:
    def test_status_429_is_retryable(self):
        assert is_retryable(_FakeAPIError(429))

    def test_status_500_is_retryable(self):
        assert is_retryable(_FakeAPIError(500))

    def test_status_502_is_retryable(self):
        assert is_retryable(_FakeAPIError(502))

    def test_status_503_is_retryable(self):
        assert is_retryable(_FakeAPIError(503))

    def test_status_504_is_retryable(self):
        assert is_retryable(_FakeAPIError(504))

    def test_status_400_not_retryable(self):
        assert not is_retryable(_FakeAPIError(400))

    def test_status_404_not_retryable(self):
        assert not is_retryable(_FakeAPIError(404))

    def test_status_422_not_retryable(self):
        assert not is_retryable(_FakeAPIError(422))

    def test_rate_limit_class_name_is_retryable(self):
        assert is_retryable(RateLimitError())

    def test_api_connection_class_name_is_retryable(self):
        assert is_retryable(APIConnectionError())

    def test_plain_value_error_not_retryable(self):
        assert not is_retryable(ValueError("bad input"))

    def test_plain_key_error_not_retryable(self):
        assert not is_retryable(KeyError("key"))

    def test_runtime_error_not_retryable(self):
        assert not is_retryable(RuntimeError("oops"))


# ---------------------------------------------------------------------------
# TestWithRetrySuccess
# ---------------------------------------------------------------------------

class TestWithRetrySuccess:
    def test_success_on_first_attempt(self):
        calls = {"n": 0}

        def fn():
            calls["n"] += 1
            return "ok"

        result = with_retry(fn, max_attempts=3, wait_min=0, wait_max=0)
        assert result == "ok"
        assert calls["n"] == 1

    def test_passes_args_and_kwargs(self):
        def fn(a, b, c=0):
            return a + b + c

        result = with_retry(fn, 1, 2, max_attempts=2, wait_min=0, wait_max=0, c=10)
        assert result == 13

    def test_returns_none_when_fn_returns_none(self):
        result = with_retry(lambda: None, max_attempts=1, wait_min=0, wait_max=0)
        assert result is None


# ---------------------------------------------------------------------------
# TestWithRetryRetries
# ---------------------------------------------------------------------------

class TestWithRetryRetries:
    def test_retries_on_retryable_error(self):
        calls = {"n": 0}

        def fn():
            calls["n"] += 1
            if calls["n"] < 3:
                raise _FakeAPIError(429)
            return "recovered"

        result = with_retry(fn, max_attempts=4, wait_min=0, wait_max=0)
        assert result == "recovered"
        assert calls["n"] == 3

    def test_success_on_second_attempt(self):
        calls = {"n": 0}

        def fn():
            calls["n"] += 1
            if calls["n"] == 1:
                raise RateLimitError()
            return "second-ok"

        result = with_retry(fn, max_attempts=3, wait_min=0, wait_max=0)
        assert result == "second-ok"
        assert calls["n"] == 2

    def test_non_retryable_propagates_immediately(self):
        """A ValueError must NOT trigger a retry — only 1 call should happen."""
        calls = {"n": 0}

        def fn():
            calls["n"] += 1
            raise ValueError("bad")

        with pytest.raises(ValueError, match="bad"):
            with_retry(fn, max_attempts=5, wait_min=0, wait_max=0)

        assert calls["n"] == 1   # no retries

    def test_exhausts_attempts_and_reraises(self):
        calls = {"n": 0}

        def fn():
            calls["n"] += 1
            raise _FakeAPIError(503)

        with pytest.raises(_FakeAPIError):
            with_retry(fn, max_attempts=3, wait_min=0, wait_max=0)

        assert calls["n"] == 3

    def test_reraise_false_raises_retry_error(self):
        """When reraise=False, tenacity.RetryError is raised instead."""
        try:
            from tenacity import RetryError
        except ImportError:
            pytest.skip("tenacity not installed")

        def fn():
            raise _FakeAPIError(503)

        with pytest.raises(RetryError):
            with_retry(fn, max_attempts=2, wait_min=0, wait_max=0, reraise=False)

    def test_exact_attempt_count_matches_max_attempts(self):
        calls = {"n": 0}

        def fn():
            calls["n"] += 1
            raise _FakeAPIError(500)

        with pytest.raises(_FakeAPIError):
            with_retry(fn, max_attempts=2, wait_min=0, wait_max=0)

        assert calls["n"] == 2

    def test_503_retries(self):
        calls = {"n": 0}

        def fn():
            calls["n"] += 1
            if calls["n"] < 2:
                raise _FakeAPIError(503)
            return "done"

        result = with_retry(fn, max_attempts=3, wait_min=0, wait_max=0)
        assert result == "done"


# ---------------------------------------------------------------------------
# TestWithRetryDefaults
# ---------------------------------------------------------------------------

class TestWithRetryDefaults:
    def test_default_constants_exist(self):
        assert DEFAULT_LLM_ATTEMPTS == 4
        assert DEFAULT_WAIT_MIN_S >= 0
        assert DEFAULT_WAIT_MAX_S > DEFAULT_WAIT_MIN_S
        assert DEFAULT_MULTIPLIER > 1
