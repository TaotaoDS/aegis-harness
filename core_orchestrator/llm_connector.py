"""LLM Connector abstraction layer — model-agnostic provider dispatch.

Agents never interact with this layer directly. The call chain is:
    Agent → LLMGateway(llm=Callable) → ModelRouter.as_llm() → Connector.call()

Supported providers:
    - "openai"     — OpenAI API and ALL OpenAI-compatible APIs
                     (DeepSeek, Zhipu/GLM, Kimi/Moonshot, vLLM, Ollama, etc.)
    - "anthropic"  — Anthropic Messages API

To add a new provider (e.g. Gemini):
    1. Create a class with a .call() method matching the LLMConnector protocol.
    2. Call register_connector("gemini", GeminiConnector()).
"""

from typing import Optional, Protocol, runtime_checkable


@runtime_checkable
class LLMConnector(Protocol):
    """Protocol that all provider connectors must satisfy."""

    def call(
        self,
        *,
        model_id: str,
        api_key: str,
        text: str,
        max_tokens: int,
        temperature: float,
        base_url: Optional[str] = None,
    ) -> str: ...


# ---------------------------------------------------------------------------
# Concrete connectors
# ---------------------------------------------------------------------------

class OpenAIConnector:
    """Handles OpenAI and all OpenAI-compatible APIs.

    Covers: OpenAI, DeepSeek, Zhipu (GLM), Kimi (Moonshot),
    vLLM, Ollama, LiteLLM, and any provider exposing an
    OpenAI-compatible /v1/chat/completions endpoint.

    Set base_url to route to a non-OpenAI endpoint.
    """

    @staticmethod
    def _import_openai():
        from openai import OpenAI
        return OpenAI

    def call(
        self,
        *,
        model_id: str,
        api_key: str,
        text: str,
        max_tokens: int,
        temperature: float,
        base_url: Optional[str] = None,
    ) -> str:
        OpenAI = self._import_openai()
        client = OpenAI(api_key=api_key, base_url=base_url)
        resp = client.chat.completions.create(
            model=model_id,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[{"role": "user", "content": text}],
        )
        return resp.choices[0].message.content


class AnthropicConnector:
    """Handles the Anthropic Messages API."""

    @staticmethod
    def _import_anthropic():
        from anthropic import Anthropic
        return Anthropic

    def call(
        self,
        *,
        model_id: str,
        api_key: str,
        text: str,
        max_tokens: int,
        temperature: float,
        base_url: Optional[str] = None,
    ) -> str:
        Anthropic = self._import_anthropic()
        client = Anthropic(api_key=api_key, base_url=base_url)
        msg = client.messages.create(
            model=model_id,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[{"role": "user", "content": text}],
        )
        return msg.content[0].text


# ---------------------------------------------------------------------------
# Connector registry
# ---------------------------------------------------------------------------

_CONNECTORS: dict[str, LLMConnector] = {
    "openai": OpenAIConnector(),
    "anthropic": AnthropicConnector(),
}


def get_connector(provider: str) -> LLMConnector:
    """Look up a connector by provider name. Raises ValueError if unknown."""
    connector = _CONNECTORS.get(provider)
    if connector is None:
        raise ValueError(
            f"Unknown provider: '{provider}'. "
            f"Available: {', '.join(sorted(_CONNECTORS))}. "
            f"Use register_connector() to add new providers."
        )
    return connector


def register_connector(provider: str, connector: LLMConnector) -> None:
    """Register a custom connector for a new provider.

    Example:
        class GeminiConnector:
            def call(self, *, model_id, api_key, text, max_tokens, temperature, base_url=None):
                ...
        register_connector("gemini", GeminiConnector())
    """
    _CONNECTORS[provider] = connector
