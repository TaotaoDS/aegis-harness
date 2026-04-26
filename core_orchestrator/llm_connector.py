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
from typing import Any, Callable, Dict, List, Optional, Protocol, runtime_checkable

# Callback type for handling tool calls during multi-turn loops.
# Signature: (tool_name: str, arguments: Dict) -> str (JSON result content)
# When None, all tool calls receive {"status": "ok"} as the result.
ToolHandler = Optional[Callable[[str, Dict[str, Any]], str]]


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
        # Intercept usage from the actual HTTP response for FinOps billing.
        try:
            from .billing import record_usage
            if resp.usage:
                record_usage(
                    model_id=resp.model or model_id,
                    prompt_tokens=resp.usage.prompt_tokens or 0,
                    completion_tokens=resp.usage.completion_tokens or 0,
                )
        except Exception:
            pass
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
        tool_handler: ToolHandler = None,
    ) -> List[ToolCall]:
        """Multi-turn tool loop. Returns all tool calls collected across rounds.

        If tool_handler is provided, it is called for each tool invocation
        and its return value is sent back to the model as the tool result.
        This enables tools like read_file to return real content.
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
            # Intercept usage from each round for FinOps billing.
            try:
                from .billing import record_usage
                if resp.usage:
                    record_usage(
                        model_id=resp.model or model_id,
                        prompt_tokens=resp.usage.prompt_tokens or 0,
                        completion_tokens=resp.usage.completion_tokens or 0,
                    )
            except Exception:
                pass
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
                    try:
                        tc_args = json.loads(tc.function.arguments)
                    except (json.JSONDecodeError, TypeError):
                        tc_args = {}
                    if tool_handler:
                        result_content = tool_handler(tc.function.name, tc_args)
                    else:
                        result_content = json.dumps({"status": "ok"})
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result_content,
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
        # Intercept usage from the actual HTTP response for FinOps billing.
        try:
            from .billing import record_usage
            if msg.usage:
                record_usage(
                    model_id=msg.model or model_id,
                    prompt_tokens=msg.usage.input_tokens or 0,
                    completion_tokens=msg.usage.output_tokens or 0,
                )
        except Exception:
            pass
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
        tool_handler: ToolHandler = None,
    ) -> List[ToolCall]:
        """Multi-turn tool loop for Anthropic. Returns all tool calls.

        If tool_handler is provided, it is called for each tool invocation
        and its return value is sent back to the model as the tool result.
        """
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
            # Intercept usage from each round for FinOps billing.
            try:
                from .billing import record_usage
                if msg.usage:
                    record_usage(
                        model_id=msg.model or model_id,
                        prompt_tokens=msg.usage.input_tokens or 0,
                        completion_tokens=msg.usage.output_tokens or 0,
                    )
            except Exception:
                pass

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
            tool_results = []
            for b in tool_blocks:
                b_args = b.input if isinstance(b.input, dict) else {}
                if tool_handler:
                    result_content = tool_handler(b.name, b_args)
                else:
                    result_content = json.dumps({"status": "ok"})
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": b.id,
                    "content": result_content,
                })
            messages.append({"role": "user", "content": tool_results})

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
