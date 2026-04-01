"""Tests for LLM gateway."""

import tiktoken

from core_orchestrator.llm_gateway import LLMGateway, DEFAULT_MAX_TOKENS
from core_orchestrator.pii_sanitizer import default_pipeline


class TestLLMGatewayDefaults:
    """Gateway with default sanitizer and mock LLM."""

    def setup_method(self):
        self.gw = LLMGateway()

    def test_clean_text_passes_through(self):
        result = self.gw.send("hello world")
        assert result["sanitized_input"] == "hello world"
        assert result["llm_response"] is not None

    def test_pii_is_sanitized(self):
        result = self.gw.send("email me at user@test.com")
        assert "user@test.com" not in result["sanitized_input"]
        assert "[EMAIL_REDACTED]" in result["sanitized_input"]

    def test_llm_receives_sanitized_text(self):
        result = self.gw.send("call 13800138000")
        # default mock echoes its input, so llm_response == sanitized_input
        assert result["llm_response"] == result["sanitized_input"]

    def test_mixed_pii(self):
        text = "user@a.com 13800138000 110101199001011234 4111111111111111"
        result = self.gw.send(text)
        sanitized = result["sanitized_input"]
        assert "user@a.com" not in sanitized
        assert "13800138000" not in sanitized
        assert "110101199001011234" not in sanitized
        assert "4111111111111111" not in sanitized

    def test_chinese_text_with_pii(self):
        text = "请联系张三，邮箱zhang@test.com，电话13912345678"
        result = self.gw.send(text)
        assert "张三" in result["sanitized_input"]
        assert "zhang@test.com" not in result["sanitized_input"]
        assert "13912345678" not in result["sanitized_input"]

    def test_empty_string(self):
        result = self.gw.send("")
        assert result["sanitized_input"] == ""
        assert result["llm_response"] == ""


class TestLLMGatewayCustom:
    """Gateway with injected sanitizer and LLM callable."""

    def test_custom_sanitizer(self):
        custom = lambda t: t.replace("SECRET", "[REDACTED]")
        gw = LLMGateway(sanitizer=custom)
        result = gw.send("my SECRET value")
        assert result["sanitized_input"] == "my [REDACTED] value"

    def test_custom_llm(self):
        mock_llm = lambda t: f"Response to: {t}"
        gw = LLMGateway(llm=mock_llm)
        result = gw.send("hello")
        assert result["llm_response"] == "Response to: hello"

    def test_custom_both(self):
        upper = lambda t: t.upper()
        reverse_llm = lambda t: t[::-1]
        gw = LLMGateway(sanitizer=upper, llm=reverse_llm)
        result = gw.send("abc")
        assert result["sanitized_input"] == "ABC"
        assert result["llm_response"] == "CBA"

    def test_original_input_preserved(self):
        gw = LLMGateway()
        result = gw.send("email user@test.com")
        assert result["original_input"] == "email user@test.com"


# --- Token overflow & summarization ---

def _count_tokens(text: str) -> int:
    """Helper: precise token count using tiktoken."""
    enc = tiktoken.get_encoding("cl100k_base")
    return len(enc.encode(text))


class TestHistoryAccumulation:
    """Gateway tracks conversation history across sends."""

    def test_history_grows(self):
        gw = LLMGateway(max_tokens=4096)
        gw.send("first message")
        gw.send("second message")
        assert len(gw.history) == 4  # 2 user inputs + 2 LLM responses

    def test_history_contains_sanitized_not_original(self):
        gw = LLMGateway(max_tokens=4096)
        gw.send("email user@secret.com")
        assert "user@secret.com" not in gw.history[0]
        assert "[EMAIL_REDACTED]" in gw.history[0]


class TestTokenOverflow:
    """When history reaches 85% of max_tokens, compression triggers."""

    def test_no_compression_under_threshold(self):
        gw = LLMGateway(max_tokens=4096)
        gw.send("short")
        # History is tiny, no compression
        assert len(gw.history) == 2  # input + response
        assert "[SUMMARY]" not in gw.history[0]

    def test_compression_triggers_at_threshold(self):
        # Use a very small max_tokens to trigger compression easily
        gw = LLMGateway(max_tokens=50)
        # Send enough messages to exceed 85% of 50 tokens
        for i in range(10):
            gw.send(f"This is message number {i} with some padding text here")
        # After compression, total tokens should be under max_tokens
        full_history = "\n".join(gw.history)
        assert _count_tokens(full_history) < 50

    def test_summary_preserved_in_history(self):
        called_with = []
        def spy_summarizer(text: str) -> str:
            called_with.append(text)
            return "[SUMMARY] condensed"

        gw = LLMGateway(max_tokens=50, summarizer=spy_summarizer)
        for i in range(10):
            gw.send(f"Message {i} with extra words to fill tokens")
        # Summarizer was called at least once
        assert len(called_with) > 0
        # Summary text appears in history
        assert any("[SUMMARY]" in entry for entry in gw.history)

    def test_custom_summarizer_receives_old_history(self):
        received = []
        def capture_summarizer(text: str) -> str:
            received.append(text)
            return "summary"

        gw = LLMGateway(max_tokens=50, summarizer=capture_summarizer)
        for i in range(10):
            gw.send(f"Message {i} padding padding padding padding")
        # The summarizer received a non-empty string (the old history)
        assert all(len(t) > 0 for t in received)

    def test_default_summarizer_truncates(self):
        # No custom summarizer -> default truncation behavior
        gw = LLMGateway(max_tokens=50)
        for i in range(10):
            gw.send(f"Message {i} with enough text to overflow the limit")
        full_history = "\n".join(gw.history)
        # Must be under max_tokens after compression
        assert _count_tokens(full_history) < 50
        # First entry should contain the truncation marker
        assert "[TRUNCATED]" in gw.history[0]

    def test_recent_messages_preserved_after_compression(self):
        gw = LLMGateway(max_tokens=80)
        for i in range(15):
            gw.send(f"Message {i} padding text to fill up tokens quickly")
        # The most recent exchange should still be in history
        last_result = gw.send("final message")
        assert last_result["sanitized_input"] == "final message"
        # "final message" should appear in history
        assert any("final message" in entry for entry in gw.history)


class TestTokenOverflowBackwardCompat:
    """Existing behavior is preserved when max_tokens is not set."""

    def test_default_max_tokens_is_large(self):
        assert DEFAULT_MAX_TOKENS >= 4096

    def test_no_compression_with_defaults(self):
        gw = LLMGateway()
        for i in range(5):
            gw.send(f"message {i}")
        # With default large max_tokens, no compression should happen
        assert len(gw.history) == 10  # 5 inputs + 5 responses
        assert not any("[TRUNCATED]" in e for e in gw.history)

    def test_threshold_configurable(self):
        # threshold=0.5 means compression at 50% instead of 85%
        gw = LLMGateway(max_tokens=100, threshold=0.5)
        for i in range(10):
            gw.send(f"Message {i} padding text to trigger early compression")
        full_history = "\n".join(gw.history)
        assert _count_tokens(full_history) < 100
