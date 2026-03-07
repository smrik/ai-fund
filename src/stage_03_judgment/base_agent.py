"""
BaseAgent — shared infrastructure for all agents.
Handles Anthropic client, tool-call loop, and error recovery.
"""

import json
import os
from anthropic import Anthropic
from typing import Any, Callable

from config import LLM_MODEL


ToolDefinition = dict[str, Any]
ToolHandler = Callable[[str, dict], str]


class BaseAgent:
    """
    Base class for all research agents.

    Subclasses define:
      - self.name: display name
      - self.system_prompt: agent-specific instructions
      - self.tools: list of Anthropic tool definitions
      - self.tool_handlers: dict mapping tool name → callable(input_dict) → str
    """

    def __init__(self):
        self.client = Anthropic()  # Uses ANTHROPIC_API_KEY from environment
        self.name = "BaseAgent"
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

    def run(self, user_message: str, max_iterations: int = 10) -> str:
        """
        Run the agent with tool-call loop.
        Returns the final text response.
        """
        messages = [{"role": "user", "content": user_message}]
        tools_param = self.tools if self.tools else None

        for _ in range(max_iterations):
            kwargs = {
                "model": LLM_MODEL,
                "max_tokens": 8192,
                "system": self.system_prompt,
                "messages": messages,
            }
            if tools_param:
                kwargs["tools"] = tools_param

            response = self.client.messages.create(**kwargs)

            # Model wants to use tools
            if response.stop_reason == "tool_use":
                # Append assistant's full response (includes tool_use blocks)
                messages.append({"role": "assistant", "content": response.content})

                # Execute each tool use block
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        result_text = self._execute_tool(block.name, block.input)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result_text,
                        })

                # Append tool results as a user turn
                messages.append({"role": "user", "content": tool_results})
                continue

            # Model finished — return text
            for block in response.content:
                if hasattr(block, "text"):
                    return block.text
            return ""

        return "Max iterations reached without a final response."

    @staticmethod
    def _tool(name: str, description: str, properties: dict, required: list[str]) -> ToolDefinition:
        """Helper to build an Anthropic tool definition."""
        return {
            "name": name,
            "description": description,
            "input_schema": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        }
