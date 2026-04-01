"""Tests for LLM Connector abstraction layer.

Verifies Protocol compliance, provider dispatch, base_url forwarding,
temperature passthrough, and extensibility for new providers.
"""

from unittest.mock import patch, MagicMock

import pytest

from core_orchestrator.llm_connector import (
    LLMConnector,
    OpenAIConnector,
    AnthropicConnector,
    get_connector,
)


# ---------------------------------------------------------------------------
# Registry: get_connector
# ---------------------------------------------------------------------------

class TestGetConnector:
    def test_returns_openai_connector(self):
        c = get_connector("openai")
        assert isinstance(c, OpenAIConnector)

    def test_returns_anthropic_connector(self):
        c = get_connector("anthropic")
        assert isinstance(c, AnthropicConnector)

    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="gemini"):
            get_connector("gemini")

    def test_openai_compatible_alias(self):
        """'openai' connector covers all OpenAI-compatible APIs."""
        c = get_connector("openai")
        assert isinstance(c, OpenAIConnector)


# ---------------------------------------------------------------------------
# OpenAIConnector
# ---------------------------------------------------------------------------

class TestOpenAIConnector:
    def test_call_creates_client_and_sends(self):
        mock_client_cls = MagicMock()
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = "hello from openai"
        mock_client_cls.return_value.chat.completions.create.return_value = mock_resp

        connector = OpenAIConnector()
        with patch.object(connector, "_import_openai", return_value=mock_client_cls):
            result = connector.call(
                model_id="gpt-4o", api_key="sk-test", text="hi",
                max_tokens=100, temperature=0.7,
            )
        assert result == "hello from openai"
        mock_client_cls.assert_called_once_with(api_key="sk-test", base_url=None)

    def test_call_forwards_base_url(self):
        mock_client_cls = MagicMock()
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = "deepseek says hi"
        mock_client_cls.return_value.chat.completions.create.return_value = mock_resp

        connector = OpenAIConnector()
        with patch.object(connector, "_import_openai", return_value=mock_client_cls):
            result = connector.call(
                model_id="deepseek-chat", api_key="sk-ds",
                text="hi", max_tokens=4096, temperature=0.3,
                base_url="https://api.deepseek.com/v1",
            )
        assert result == "deepseek says hi"
        mock_client_cls.assert_called_once_with(
            api_key="sk-ds", base_url="https://api.deepseek.com/v1",
        )

    def test_call_forwards_temperature(self):
        mock_client_cls = MagicMock()
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = "ok"
        mock_client_cls.return_value.chat.completions.create.return_value = mock_resp

        connector = OpenAIConnector()
        with patch.object(connector, "_import_openai", return_value=mock_client_cls):
            connector.call(
                model_id="gpt-4o", api_key="k", text="t",
                max_tokens=100, temperature=0.0,
            )
        call_kwargs = mock_client_cls.return_value.chat.completions.create.call_args[1]
        assert call_kwargs["temperature"] == 0.0

    def test_call_forwards_max_tokens(self):
        mock_client_cls = MagicMock()
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = "ok"
        mock_client_cls.return_value.chat.completions.create.return_value = mock_resp

        connector = OpenAIConnector()
        with patch.object(connector, "_import_openai", return_value=mock_client_cls):
            connector.call(
                model_id="m", api_key="k", text="t",
                max_tokens=2048, temperature=0.5,
            )
        call_kwargs = mock_client_cls.return_value.chat.completions.create.call_args[1]
        assert call_kwargs["max_tokens"] == 2048


# ---------------------------------------------------------------------------
# AnthropicConnector
# ---------------------------------------------------------------------------

class TestAnthropicConnector:
    def test_call_creates_client_and_sends(self):
        mock_client_cls = MagicMock()
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock()]
        mock_msg.content[0].text = "hello from claude"
        mock_client_cls.return_value.messages.create.return_value = mock_msg

        connector = AnthropicConnector()
        with patch.object(connector, "_import_anthropic", return_value=mock_client_cls):
            result = connector.call(
                model_id="claude-sonnet-4-20250514", api_key="sk-ant-test",
                text="hi", max_tokens=4096, temperature=0.7,
            )
        assert result == "hello from claude"
        mock_client_cls.assert_called_once_with(api_key="sk-ant-test", base_url=None)

    def test_call_forwards_base_url(self):
        mock_client_cls = MagicMock()
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock()]
        mock_msg.content[0].text = "proxied"
        mock_client_cls.return_value.messages.create.return_value = mock_msg

        connector = AnthropicConnector()
        with patch.object(connector, "_import_anthropic", return_value=mock_client_cls):
            connector.call(
                model_id="claude-sonnet-4-20250514", api_key="k",
                text="t", max_tokens=100, temperature=0.5,
                base_url="https://proxy.example.com",
            )
        mock_client_cls.assert_called_once_with(
            api_key="k", base_url="https://proxy.example.com",
        )

    def test_call_forwards_temperature(self):
        mock_client_cls = MagicMock()
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock()]
        mock_msg.content[0].text = "ok"
        mock_client_cls.return_value.messages.create.return_value = mock_msg

        connector = AnthropicConnector()
        with patch.object(connector, "_import_anthropic", return_value=mock_client_cls):
            connector.call(
                model_id="m", api_key="k", text="t",
                max_tokens=100, temperature=0.2,
            )
        call_kwargs = mock_client_cls.return_value.messages.create.call_args[1]
        assert call_kwargs["temperature"] == 0.2


# ---------------------------------------------------------------------------
# Protocol compliance (structural typing)
# ---------------------------------------------------------------------------

class TestProtocolCompliance:
    def test_openai_connector_has_call(self):
        c = OpenAIConnector()
        assert hasattr(c, "call") and callable(c.call)

    def test_anthropic_connector_has_call(self):
        c = AnthropicConnector()
        assert hasattr(c, "call") and callable(c.call)

    def test_custom_connector_works_with_get_connector(self):
        """Verify extensibility: a custom connector can be registered."""
        from core_orchestrator.llm_connector import register_connector

        class DummyConnector:
            def call(self, *, model_id, api_key, text, max_tokens, temperature, base_url=None):
                return f"dummy: {text}"

        register_connector("dummy", DummyConnector())
        c = get_connector("dummy")
        result = c.call(
            model_id="m", api_key="k", text="hello",
            max_tokens=100, temperature=0.5,
        )
        assert result == "dummy: hello"


# ---------------------------------------------------------------------------
# Base URL support for OpenAI-compatible providers
# ---------------------------------------------------------------------------

class TestOpenAICompatibleProviders:
    """Verify that OpenAI connector works for DeepSeek, Zhipu, Kimi etc.
    by correctly forwarding base_url to the client constructor."""

    def test_deepseek_base_url(self):
        mock_client_cls = MagicMock()
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = "deepseek"
        mock_client_cls.return_value.chat.completions.create.return_value = mock_resp

        connector = OpenAIConnector()
        with patch.object(connector, "_import_openai", return_value=mock_client_cls):
            connector.call(
                model_id="deepseek-chat", api_key="sk-ds",
                text="hi", max_tokens=4096, temperature=0.3,
                base_url="https://api.deepseek.com/v1",
            )
        # Client created with custom base_url
        mock_client_cls.assert_called_once_with(
            api_key="sk-ds", base_url="https://api.deepseek.com/v1",
        )
        # Model ID forwarded correctly
        create_kwargs = mock_client_cls.return_value.chat.completions.create.call_args[1]
        assert create_kwargs["model"] == "deepseek-chat"

    def test_no_base_url_uses_default(self):
        mock_client_cls = MagicMock()
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = "ok"
        mock_client_cls.return_value.chat.completions.create.return_value = mock_resp

        connector = OpenAIConnector()
        with patch.object(connector, "_import_openai", return_value=mock_client_cls):
            connector.call(
                model_id="gpt-4o", api_key="sk-test",
                text="hi", max_tokens=100, temperature=0.7,
            )
        # base_url=None means use OpenAI default
        mock_client_cls.assert_called_once_with(api_key="sk-test", base_url=None)
