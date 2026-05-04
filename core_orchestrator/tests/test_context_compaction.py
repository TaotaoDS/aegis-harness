"""Tests for the deep context compaction system (Layer 1 + Layer 2)."""

import os
import tempfile

import pytest

from core_orchestrator.tool_output_store import ToolOutputStore
from core_orchestrator.context_summarizer import (
    ContextSummarizer,
    count_message_tokens,
)


# ---------------------------------------------------------------------------
# Layer 1: ToolOutputStore
# ---------------------------------------------------------------------------

class TestToolOutputStore:
    def setup_method(self):
        self._tmpdir = tempfile.mkdtemp()
        os.makedirs(os.path.join(self._tmpdir, "ws1", "_workspace"), exist_ok=True)
        self.store = ToolOutputStore(
            workspace_path=self._tmpdir,
            workspace_id="ws1",
            threshold=100,
            preview_chars=30,
        )

    def test_small_content_passes_through(self):
        result = self.store.maybe_evict("tc1", "short content")
        assert result == "short content"

    def test_large_content_evicted_to_disk(self):
        big = "A" * 200
        result = self.store.maybe_evict("tc2", big)
        assert len(result) < len(big)
        assert "evicted to disk" in result
        assert "200 chars total" in result

    def test_evicted_content_retrievable(self):
        big = "B" * 500
        self.store.maybe_evict("tc3", big)
        retrieved = self.store.retrieve("tc3")
        assert retrieved == big

    def test_retrieve_nonexistent_returns_none(self):
        assert self.store.retrieve("nonexistent") is None

    def test_preview_contains_head_and_tail(self):
        content = "HEAD_" + "x" * 200 + "_TAIL"
        result = self.store.maybe_evict("tc4", content)
        assert "HEAD_" in result
        assert "_TAIL" in result

    def test_clear_removes_all_files(self):
        self.store.maybe_evict("tc5", "C" * 200)
        self.store.maybe_evict("tc6", "D" * 200)
        self.store.clear()
        assert self.store.retrieve("tc5") is None
        assert self.store.retrieve("tc6") is None

    def test_safe_id_sanitization(self):
        result = self.store.maybe_evict("../../../etc/passwd", "E" * 200)
        assert "evicted to disk" in result
        retrieved = self.store.retrieve("../../../etc/passwd")
        assert retrieved == "E" * 200


# ---------------------------------------------------------------------------
# Layer 2: ContextSummarizer
# ---------------------------------------------------------------------------

class TestContextSummarizer:
    def test_should_compact_below_threshold(self):
        cs = ContextSummarizer(context_window=100_000)
        msgs = [{"role": "user", "content": "hello"}]
        assert not cs.should_compact(msgs)

    def test_should_compact_above_threshold(self):
        cs = ContextSummarizer(context_window=50)
        msgs = [{"role": "user", "content": "The quick brown fox jumps over the lazy dog. " * 20}]
        assert cs.should_compact(msgs)

    def test_compact_preserves_system_and_recent(self):
        cs = ContextSummarizer(context_window=100)
        msgs = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "old msg 1"},
            {"role": "assistant", "content": "old reply 1"},
            {"role": "user", "content": "old msg 2"},
            {"role": "assistant", "content": "old reply 2"},
            {"role": "user", "content": "recent question"},
            {"role": "assistant", "content": "recent answer"},
        ]
        compacted = cs.compact_messages(msgs, keep_system=True, keep_recent=2)
        assert compacted[0]["role"] == "system"
        assert compacted[0]["content"] == "You are helpful."
        assert compacted[-1]["content"] == "recent answer"
        assert compacted[-2]["content"] == "recent question"
        assert len(compacted) < len(msgs)

    def test_compact_with_llm_summarizer(self):
        def mock_llm(prompt):
            return "Summary: old messages discussed file paths and errors."

        cs = ContextSummarizer(llm_callable=mock_llm, context_window=100)
        msgs = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "old1"},
            {"role": "assistant", "content": "old2"},
            {"role": "user", "content": "old3"},
            {"role": "assistant", "content": "old4"},
            {"role": "user", "content": "recent"},
            {"role": "assistant", "content": "reply"},
        ]
        compacted = cs.compact_messages(msgs, keep_recent=2)
        summary_msg = compacted[1]
        assert "CONTEXT SUMMARY" in summary_msg["content"]
        assert "old messages discussed" in summary_msg["content"]

    def test_compact_too_few_messages_returns_unchanged(self):
        cs = ContextSummarizer(context_window=100)
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        compacted = cs.compact_messages(msgs, keep_recent=4)
        assert compacted == msgs

    def test_fallback_on_llm_failure(self):
        def broken_llm(prompt):
            raise RuntimeError("LLM down")

        cs = ContextSummarizer(llm_callable=broken_llm, context_window=100)
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "a" * 200},
            {"role": "assistant", "content": "b" * 200},
            {"role": "user", "content": "recent"},
            {"role": "assistant", "content": "reply"},
        ]
        compacted = cs.compact_messages(msgs, keep_recent=2)
        assert len(compacted) < len(msgs)


class TestCountMessageTokens:
    def test_simple_messages(self):
        msgs = [{"role": "user", "content": "hello world"}]
        count = count_message_tokens(msgs)
        assert count > 0

    def test_list_content_messages(self):
        msgs = [
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "content": "some result", "tool_use_id": "x"},
                ],
            }
        ]
        count = count_message_tokens(msgs)
        assert count > 0
