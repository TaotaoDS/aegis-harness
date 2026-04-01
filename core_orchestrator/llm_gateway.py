"""Minimal LLM gateway with PII sanitization and token overflow management.

Flow: user_input -> sanitize -> [check token overflow -> compress history] -> llm -> response
"""

from typing import Callable, List, Optional

import tiktoken

from .pii_sanitizer import Sanitizer, default_pipeline

DEFAULT_MAX_TOKENS = 8192
_THRESHOLD = 0.85


def _mock_llm(text: str) -> str:
    """Echo the input. Placeholder for a real LLM call."""
    return text


def _default_summarizer(text: str) -> str:
    """Truncate old history using fast character estimate for the cut point."""
    # Keep roughly 200 tokens worth of text (200 * 4 chars ≈ 800 chars)
    keep_chars = 200 * 4
    if len(text) <= keep_chars:
        return text
    return text[:keep_chars] + "\n[TRUNCATED]"


# Module-level encoder (loaded once)
_encoding = tiktoken.get_encoding("cl100k_base")


def _count_tokens(text: str) -> int:
    """Precise token count using tiktoken."""
    return len(_encoding.encode(text))


class LLMGateway:
    """Thin gateway that sanitizes input, manages history token budget,
    and forwards to an LLM."""

    def __init__(
        self,
        sanitizer: Optional[Sanitizer] = None,
        llm: Optional[Callable[[str], str]] = None,
        summarizer: Optional[Callable[[str], str]] = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        threshold: float = _THRESHOLD,
    ):
        self._sanitizer = sanitizer or default_pipeline()
        self._llm = llm or _mock_llm
        self._summarizer = summarizer or _default_summarizer
        self._max_tokens = max_tokens
        self._threshold = threshold
        self._history: List[str] = []

    @property
    def history(self) -> List[str]:
        return self._history

    def _compress_history(self) -> None:
        """When history tokens >= threshold, summarize older entries."""
        if len(self._history) <= 2:
            return

        # Keep the most recent exchange (last 2 entries)
        old_entries = self._history[:-2]
        recent = self._history[-2:]

        old_text = "\n".join(old_entries)
        summary = self._summarizer(old_text)
        self._history = [summary] + recent

    def _hard_truncate_summary(self, token_limit: int) -> None:
        """When the summary + recent exchange still exceeds the budget,
        use len//4 char estimate to aggressively trim the summary."""
        if not self._history:
            return
        # Measure how many tokens the recent entries (everything except summary) use
        recent_text = "\n".join(self._history[1:])
        recent_tokens = _count_tokens(recent_text)
        # Budget available for the summary
        summary_budget = max(token_limit - recent_tokens - 1, 0)
        # Fast char-level estimate: tokens * 4 ≈ chars
        keep_chars = summary_budget * 4
        summary = self._history[0]
        if keep_chars <= 0:
            self._history[0] = "[TRUNCATED]"
        elif len(summary) > keep_chars:
            self._history[0] = summary[:keep_chars] + "\n[TRUNCATED]"

    def send(self, user_input: str) -> dict:
        sanitized = self._sanitizer(user_input)
        self._history.append(sanitized)

        response = self._llm(sanitized)
        self._history.append(response)

        # Check token budget after appending
        full_text = "\n".join(self._history)
        token_count = _count_tokens(full_text)
        token_limit = int(self._max_tokens * self._threshold)

        if token_count >= token_limit and len(self._history) > 2:
            # Step 1: summarize old entries via the injected summarizer
            self._compress_history()
            # Step 2: if still over budget, hard-truncate the summary
            full_text = "\n".join(self._history)
            if _count_tokens(full_text) >= token_limit:
                self._hard_truncate_summary(token_limit)

        return {
            "original_input": user_input,
            "sanitized_input": sanitized,
            "llm_response": response,
        }
