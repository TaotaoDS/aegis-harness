"""Robust JSON parser for LLM output.

LLMs frequently wrap JSON in markdown fences (```json ... ```) or
prepend/append conversational text. This module extracts and parses
the JSON payload, falling back gracefully on malformed input.
"""

import json
import re
import warnings
from typing import Any, Dict, Optional

# Matches ```json ... ``` or ``` ... ``` (first occurrence, non-greedy)
_FENCE_RE = re.compile(r"```(?:json)?\s*\n?(.*?)\n?\s*```", re.DOTALL)

# Matches the first { ... } or [ ... ] top-level structure
_BRACE_RE = re.compile(r"(\{.*\}|\[.*\])", re.DOTALL)


def parse_llm_json(
    raw: str,
    *,
    fallback: Optional[Dict] = None,
) -> Any:
    """Parse JSON from an LLM response string.

    Strategy (in order):
        1. Try raw string directly (fast path for well-behaved models).
        2. Strip markdown code fences and retry.
        3. Extract first { ... } or [ ... ] block and retry.
        4. Return fallback (default: empty dict) and emit a warning.
    """
    if fallback is None:
        fallback = {}

    # --- Strategy 1: direct parse ---
    text = raw.strip()
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass

    # --- Strategy 2: strip markdown fences ---
    fence_match = _FENCE_RE.search(text)
    if fence_match:
        try:
            return json.loads(fence_match.group(1).strip())
        except (json.JSONDecodeError, ValueError):
            pass

    # --- Strategy 3: extract first { ... } or [ ... ] ---
    brace_match = _BRACE_RE.search(text)
    if brace_match:
        try:
            return json.loads(brace_match.group(1))
        except (json.JSONDecodeError, ValueError):
            pass

    # --- Strategy 4: give up gracefully ---
    warnings.warn(
        f"parse_llm_json: could not extract JSON from LLM response "
        f"(first 120 chars: {raw[:120]!r})",
        stacklevel=2,
    )
    return fallback
