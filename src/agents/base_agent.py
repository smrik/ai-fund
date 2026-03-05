"""
BaseAgent — shared infrastructure for all 6 agents.
Handles Claude client, streaming tool loop, and error recovery.
"""

import json
import anthropic
from typing import Any, Callable
from config import CLAUDE_MODEL


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
        self.client = anthropic.Anthropic()
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
            # Handlers may return str or dict; normalise to str
            if isinstance(result, str):
                return result
            return json.dumps(result, default=str)
        except Exception as e:
            return f"Tool error ({tool_name}): {e}"

    def run(self, user_message: str, max_iterations: int = 8) -> str:
        """
        Run the agent with streaming + tool loop.
        Returns the final text response from Claude.
        """
        messages = [{"role": "user", "content": user_message}]

        for _ in range(max_iterations):
            # Stream each Claude call
            with self.client.messages.stream(
                model=CLAUDE_MODEL,
                max_tokens=4096,
                thinking={"type": "adaptive"},
                system=self.system_prompt,
                tools=self.tools if self.tools else anthropic.NOT_GIVEN,
                messages=messages,
            ) as stream:
                response = stream.get_final_message()

            # Collect text blocks for final return
            text_blocks = [
                b.text for b in response.content if b.type == "text"
            ]

            if response.stop_reason == "end_turn":
                return "\n".join(text_blocks)

            if response.stop_reason == "tool_use":
                # Append assistant turn (includes tool_use blocks)
                messages.append({"role": "assistant", "content": response.content})

                # Execute each tool call and build tool_results
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        result_text = self._execute_tool(block.name, block.input)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result_text,
                        })

                messages.append({"role": "user", "content": tool_results})
                continue

            # Any other stop reason — return what we have
            return "\n".join(text_blocks)

        return "Max iterations reached without a final response."

    @staticmethod
    def _tool(name: str, description: str, properties: dict, required: list[str]) -> ToolDefinition:
        """Helper to build a clean Anthropic tool definition dict."""
        return {
            "name": name,
            "description": description,
            "input_schema": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        }
