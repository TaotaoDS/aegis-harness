"""Context Summarizer — Layer 2 of the deep context compaction system.

Provides LLM-powered summarization of early conversation rounds when the
message history approaches the model's context window limit. This replaces
naive character truncation with an intelligent summary that preserves key
facts, decisions, and tool call outcomes.

Usage:
    summarizer = ContextSummarizer(llm_callable=router.as_llm())
    compact = summarizer.summarize(old_messages)
"""

import json
from typing import Any, Callable, Dict, List, Optional

import tiktoken

_encoding = tiktoken.get_encoding("cl100k_base")

_SUMMARIZE_SYSTEM = """\
You are a conversation compressor. Given a sequence of messages from an AI \
assistant's tool-use session, produce a concise summary that preserves:
1. Key decisions made and their rationale
2. Important facts discovered (file contents, search results, error messages)
3. Tool calls that succeeded and their outcomes
4. Tool calls that failed and why

Output a single paragraph of ≤ {max_tokens} tokens. Be factual and specific — \
include file names, error codes, and data values. Do NOT include pleasantries, \
hedging, or meta-commentary."""

_CONTEXT_THRESHOLD = 0.85  # trigger compaction at 85% of context window


def count_message_tokens(messages: List[Dict[str, Any]]) -> int:
    """Count approximate tokens across a list of chat messages."""
    total = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total += len(_encoding.encode(content))
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    text = block.get("content", "") or block.get("text", "")
                    if isinstance(text, str):
                        total += len(_encoding.encode(text))
    return total


class ContextSummarizer:
    """LLM-powered summarization of early conversation rounds."""

    def __init__(
        self,
        llm_callable: Optional[Callable[[str], str]] = None,
        max_summary_tokens: int = 500,
        context_window: int = 128_000,
    ):
        self._llm = llm_callable
        self._max_summary_tokens = max_summary_tokens
        self._context_window = context_window

    def should_compact(self, messages: List[Dict[str, Any]]) -> bool:
        """Return True if messages are approaching the context window limit."""
        token_count = count_message_tokens(messages)
        return token_count >= int(self._context_window * _CONTEXT_THRESHOLD)

    def compact_messages(
        self,
        messages: List[Dict[str, Any]],
        keep_system: bool = True,
        keep_recent: int = 6,
    ) -> List[Dict[str, Any]]:
        """Compact messages by summarizing early rounds.

        Preserves:
        - System message (index 0) if keep_system=True
        - The most recent `keep_recent` messages (default: last 3 exchanges)
        - Summarizes everything in between

        Returns a new message list with the summary injected.
        """
        if not self._llm:
            return self._fallback_compact(messages, keep_system, keep_recent)

        min_messages = (1 if keep_system else 0) + keep_recent
        if len(messages) <= min_messages:
            return messages

        start_idx = 1 if keep_system else 0
        split_idx = len(messages) - keep_recent

        if split_idx <= start_idx:
            return messages

        prefix = messages[:start_idx]
        to_summarize = messages[start_idx:split_idx]
        recent = messages[split_idx:]

        summary_text = self._summarize(to_summarize)

        summary_msg = {
            "role": "user",
            "content": (
                f"[CONTEXT SUMMARY — {len(to_summarize)} earlier messages compressed]\n\n"
                f"{summary_text}"
            ),
        }

        return prefix + [summary_msg] + recent

    def _summarize(self, messages: List[Dict[str, Any]]) -> str:
        """Call LLM to produce a summary of the given messages."""
        formatted = self._format_messages_for_summary(messages)
        prompt = (
            _SUMMARIZE_SYSTEM.format(max_tokens=self._max_summary_tokens)
            + "\n\n---\n\n"
            + formatted
        )
        try:
            return self._llm(prompt)
        except Exception:
            return self._char_fallback(messages)

    def _fallback_compact(
        self,
        messages: List[Dict[str, Any]],
        keep_system: bool,
        keep_recent: int,
    ) -> List[Dict[str, Any]]:
        """Fallback when no LLM is available — char-level truncation."""
        min_messages = (1 if keep_system else 0) + keep_recent
        if len(messages) <= min_messages:
            return messages

        start_idx = 1 if keep_system else 0
        split_idx = len(messages) - keep_recent

        if split_idx <= start_idx:
            return messages

        prefix = messages[:start_idx]
        to_summarize = messages[start_idx:split_idx]
        recent = messages[split_idx:]

        summary_text = self._char_fallback(to_summarize)
        summary_msg = {
            "role": "user",
            "content": (
                f"[CONTEXT SUMMARY — {len(to_summarize)} earlier messages compressed]\n\n"
                f"{summary_text}"
            ),
        }
        return prefix + [summary_msg] + recent

    def _char_fallback(self, messages: List[Dict[str, Any]]) -> str:
        """Character-level truncation as ultimate fallback."""
        parts = []
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if isinstance(content, str):
                parts.append(f"[{role}]: {content[:200]}")
            elif isinstance(content, list):
                text_parts = []
                for block in content:
                    if isinstance(block, dict):
                        t = block.get("content", "") or block.get("text", "")
                        if isinstance(t, str):
                            text_parts.append(t[:100])
                parts.append(f"[{role}]: {' | '.join(text_parts)[:200]}")

        combined = "\n".join(parts)
        max_chars = self._max_summary_tokens * 4
        if len(combined) > max_chars:
            combined = combined[:max_chars] + "\n[TRUNCATED]"
        return combined

    @staticmethod
    def _format_messages_for_summary(messages: List[Dict[str, Any]]) -> str:
        """Convert messages to a readable text block for the summarizer LLM."""
        lines = []
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if isinstance(content, str):
                lines.append(f"[{role}]: {content}")
            elif isinstance(content, list):
                text_parts = []
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "tool_result":
                            tid = block.get("tool_use_id", "?")
                            tc = block.get("content", "")
                            text_parts.append(f"tool_result({tid}): {tc[:500]}")
                        elif block.get("type") == "tool_use":
                            text_parts.append(f"tool_use({block.get('name', '?')})")
                        else:
                            t = block.get("content", "") or block.get("text", "")
                            if isinstance(t, str):
                                text_parts.append(t[:500])
                lines.append(f"[{role}]: {' | '.join(text_parts)}")

        text = "\n".join(lines)
        max_input = 8000
        if len(text) > max_input:
            text = text[:max_input] + "\n[… input truncated for summarization]"
        return text
