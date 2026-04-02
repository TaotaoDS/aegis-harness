"""LLM Connector abstraction layer — model-agnostic provider dispatch.

Agents never interact with this layer directly. The call chain is:
    Agent -> LLMGateway(llm=Callable) -> ModelRouter.as_llm() -> Connector.call()

For Tool Use (Function Calling):
    Agent -> ModelRouter.as_tool_llm() -> Connector.call_with_tools()

Supported providers:
    - "openai"     -- OpenAI API and ALL OpenAI-compatible APIs
                     (DeepSeek, Zhipu/GLM, Kimi/Moonshot, vLLM, Ollama, etc.)
    - "anthropic"  -- Anthropic Messages API

To add a new provider (e.g. Gemini):
    1. Create a class with a .call() method matching the LLMConnector protocol.
    2. Call register_connector("gemini", GeminiConnector()).
"""

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Tool Call data types (provider-agnostic)
# ---------------------------------------------------------------------------

@dataclass
class ToolCall:
    """A single tool invocation extracted from an LLM response."""
    name: str
    arguments: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------

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

    def call_with_tools(
        self,
        *,
        model_id: str,
        api_key: str,
        system: str,
        user_prompt: str,
        tools: List[Dict[str, Any]],
        max_tokens: int,
        temperature: float,
        base_url: Optional[str] = None,
        max_rounds: int = 10,
    ) -> List[ToolCall]:
        """Multi-turn tool loop. Returns all tool calls collected across rounds.

        The loop continues until the model stops calling tools (finish_reason
        becomes 'stop') or max_rounds is reached.
        """
        OpenAI = self._import_openai()
        client = OpenAI(api_key=api_key, base_url=base_url)

        # Convert provider-agnostic tool defs to OpenAI format
        openai_tools = [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t["parameters"],
                },
            }
            for t in tools
        ]

        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_prompt},
        ]
        all_calls: List[ToolCall] = []

        for _ in range(max_rounds):
            resp = client.chat.completions.create(
                model=model_id,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=messages,
                tools=openai_tools,
                tool_choice="auto",
            )
            choice = resp.choices[0]
            msg = choice.message

            if msg.tool_calls:
                for tc in msg.tool_calls:
                    try:
                        args = json.loads(tc.function.arguments)
                    except (json.JSONDecodeError, TypeError):
                        args = {"_raw": tc.function.arguments}
                    all_calls.append(ToolCall(
                        name=tc.function.name,
                        arguments=args,
                    ))

                # Feed tool results back so the model can continue
                messages.append({
                    "role": "assistant",
                    "content": msg.content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in msg.tool_calls
                    ],
                })
                for tc in msg.tool_calls:
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps({"status": "ok"}),
                    })

            # Stop when model is done (no more tool calls)
            if choice.finish_reason == "stop" or not msg.tool_calls:
                break

        return all_calls


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

    def call_with_tools(
        self,
        *,
        model_id: str,
        api_key: str,
        system: str,
        user_prompt: str,
        tools: List[Dict[str, Any]],
        max_tokens: int,
        temperature: float,
        base_url: Optional[str] = None,
        max_rounds: int = 10,
    ) -> List[ToolCall]:
        """Multi-turn tool loop for Anthropic. Returns all tool calls."""
        Anthropic = self._import_anthropic()
        client = Anthropic(api_key=api_key, base_url=base_url)

        # Convert provider-agnostic tool defs to Anthropic format
        anthropic_tools = [
            {
                "name": t["name"],
                "description": t.get("description", ""),
                "input_schema": t["parameters"],
            }
            for t in tools
        ]

        messages: list = [{"role": "user", "content": user_prompt}]
        all_calls: List[ToolCall] = []

        for _ in range(max_rounds):
            msg = client.messages.create(
                model=model_id,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system,
                messages=messages,
                tools=anthropic_tools,
            )

            # Extract tool_use blocks
            tool_blocks = [b for b in msg.content if b.type == "tool_use"]
            for b in tool_blocks:
                all_calls.append(ToolCall(
                    name=b.name,
                    arguments=b.input if isinstance(b.input, dict) else {},
                ))

            # Stop when model signals end_turn or no tool calls
            if msg.stop_reason == "end_turn" or not tool_blocks:
                break

            # Feed tool results back for multi-turn
            messages.append({"role": "assistant", "content": msg.content})
            messages.append({
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": b.id,
                        "content": json.dumps({"status": "ok"}),
                    }
                    for b in tool_blocks
                ],
            })

        return all_calls


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
