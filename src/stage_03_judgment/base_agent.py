"""
BaseAgent — shared infrastructure for all agents.
Handles OpenAI client, tool-call loop, and error recovery.
"""

import json
import os
import re
import time
from openai import OpenAI, RateLimitError, APITimeoutError, APIConnectionError
from typing import Any, Callable

from config import LLM_MODEL, LLM_BASE_URL

# Retry config for transient API errors
_MAX_RETRIES = 3
_RETRY_BACKOFF = [5, 15, 30]  # seconds to wait before each retry attempt


ToolDefinition = dict[str, Any]
ToolHandler = Callable[[str, dict], str]


class BaseAgent:
    """
    Base class for all research agents.

    Subclasses define:
      - self.name: display name
      - self.system_prompt: agent-specific instructions
      - self.tools: list of OpenAI tool definitions
      - self.tool_handlers: dict mapping tool name → callable(input_dict) → str
    """

    def __init__(self, model: str | None = None):
        import os
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or os.getenv("OPENAI_API_KEY", "")
        kwargs: dict = {"api_key": api_key}
        if LLM_BASE_URL:
            kwargs["base_url"] = LLM_BASE_URL
        self.client = OpenAI(**kwargs)
        self.model = model or LLM_MODEL
        self.name = "BaseAgent"
        self.prompt_version = "v1"
        self.system_prompt = "You are a financial research assistant."
        self.tools: list[ToolDefinition] = []
        self.tool_handlers: dict[str, ToolHandler] = {}

    def _execute_tool(self, tool_name: str, tool_input: dict) -> str:
        """Dispatch a tool call to the registered handler."""
        handler = self.tool_handlers.get(tool_name)
        if handler is None:
            return f"Error: unknown tool '{tool_name}'"
        try:
            result = handler(tool_input)
            if isinstance(result, str):
                return result
            return json.dumps(result, default=str)
        except Exception as e:
            return f"Tool error ({tool_name}): {e}"

    def _create_with_retry(self, **kwargs) -> Any:
        """Call the OpenAI API with exponential backoff on transient errors."""
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                return self.client.chat.completions.create(**kwargs)
            except RateLimitError as e:
                last_exc = e
                if attempt < _MAX_RETRIES:
                    time.sleep(_RETRY_BACKOFF[attempt])
                else:
                    raise
            except (APITimeoutError, APIConnectionError) as e:
                last_exc = e
                if attempt < _MAX_RETRIES:
                    time.sleep(_RETRY_BACKOFF[attempt])
                else:
                    raise
        raise last_exc  # unreachable, satisfies type checkers

    @staticmethod
    def _serialize_tool_call(tool_call: Any) -> dict[str, Any]:
        """
        Serialize a tool call while preserving provider-specific metadata.

        Gemini's OpenAI-compatible tool-calling path returns
        `extra_content.google.thought_signature` on each tool call. That field
        must be sent back unchanged on the assistant tool-call turn.
        """
        if hasattr(tool_call, "model_dump"):
            dumped = tool_call.model_dump(exclude_none=True)
            if isinstance(dumped, dict):
                return dumped

        return {
            "id": tool_call.id,
            "type": "function",
            "function": {
                "name": tool_call.function.name,
                "arguments": tool_call.function.arguments,
            },
        }

    @classmethod
    def _serialize_assistant_message(cls, message: Any) -> dict[str, Any]:
        """
        Serialize an assistant message while preserving tool-call metadata.
        """
        if hasattr(message, "model_dump"):
            dumped = message.model_dump(exclude_none=True)
            if isinstance(dumped, dict):
                return dumped

        payload: dict[str, Any] = {
            "role": "assistant",
            "content": message.content,
        }
        tool_calls = getattr(message, "tool_calls", None)
        if tool_calls:
            payload["tool_calls"] = [cls._serialize_tool_call(tc) for tc in tool_calls]
        return payload

    def run(self, user_message: str, max_iterations: int = 10) -> str:
        """
        Run the agent with tool-call loop.
        Returns the final text response.
        """
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_message},
        ]
        tools_param = self.tools if self.tools else None

        for _ in range(max_iterations):
            kwargs = {
                "model": self.model,
                "max_tokens": 8192,
                "messages": messages,
            }
            if tools_param:
                kwargs["tools"] = tools_param

            response = self._create_with_retry(**kwargs)
            choice = response.choices[0]

            # Model wants to use tools
            if choice.finish_reason == "tool_calls":
                # Preserve provider-specific tool-call metadata such as Gemini
                # thought signatures when passing the assistant turn back.
                messages.append(self._serialize_assistant_message(choice.message))

                # Execute each tool call and append results
                for tc in choice.message.tool_calls:
                    try:
                        tool_input = json.loads(tc.function.arguments)
                    except Exception:
                        tool_input = {}
                    result_text = self._execute_tool(tc.function.name, tool_input)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result_text,
                    })
                continue

            # Model finished — return text
            return choice.message.content or ""

        return "Max iterations reached without a final response."

    @staticmethod
    def extract_json(raw: str) -> dict:
        """Extract JSON dict from LLM response, handling markdown code fences."""
        if not raw:
            raise ValueError("empty response")
        fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
        if fence:
            return json.loads(fence.group(1))
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start == -1 or end <= start:
            raise ValueError("no JSON found")
        return json.loads(raw[start:end])

    @staticmethod
    def _tool(name: str, description: str, properties: dict, required: list[str]) -> ToolDefinition:
        """Helper to build an OpenAI tool definition."""
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }
