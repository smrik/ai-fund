from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.stage_03_judgment.base_agent import BaseAgent


def test_base_agent_initializes():
    agent = BaseAgent()
    assert agent.client is not None
    assert agent.name == "BaseAgent"


def test_tool_format_is_openai():
    """Tool definitions must use OpenAI function-calling format."""
    tool = BaseAgent._tool(
        name="test_tool",
        description="A test tool",
        properties={"param": {"type": "string", "description": "A param"}},
        required=["param"],
    )
    assert tool["type"] == "function"
    assert "function" in tool
    assert tool["function"]["name"] == "test_tool"
    assert tool["function"]["description"] == "A test tool"


def test_tool_parameters_structure():
    tool = BaseAgent._tool(
        name="my_tool",
        description="desc",
        properties={"x": {"type": "integer"}},
        required=["x"],
    )
    params = tool["function"]["parameters"]
    assert params["type"] == "object"
    assert "x" in params["properties"]
    assert "x" in params["required"]


def test_run_preserves_gemini_thought_signature_in_tool_calls():
    with patch("src.stage_03_judgment.base_agent.OpenAI"):
        agent = BaseAgent()

    agent.client = MagicMock()
    agent.tools = [
        BaseAgent._tool(
            name="dummy_tool",
            description="dummy",
            properties={"ticker": {"type": "string"}},
            required=["ticker"],
        )
    ]
    agent.tool_handlers = {"dummy_tool": lambda inp: '{"ok": true}'}

    tool_call = SimpleNamespace(
        id="call_1",
        type="function",
        function=SimpleNamespace(name="dummy_tool", arguments='{"ticker":"IBM"}'),
        model_dump=lambda exclude_none=True: {
            "id": "call_1",
            "type": "function",
            "function": {
                "name": "dummy_tool",
                "arguments": '{"ticker":"IBM"}',
            },
            "extra_content": {
                "google": {
                    "thought_signature": "sig_123",
                }
            },
        },
    )

    assistant_message = SimpleNamespace(
        content=None,
        tool_calls=[tool_call],
        model_dump=lambda exclude_none=True: {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "dummy_tool",
                        "arguments": '{"ticker":"IBM"}',
                    },
                    "extra_content": {
                        "google": {
                            "thought_signature": "sig_123",
                        }
                    },
                }
            ],
        },
    )

    response_1 = SimpleNamespace(
        choices=[SimpleNamespace(finish_reason="tool_calls", message=assistant_message)]
    )
    response_2 = SimpleNamespace(
        choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content="final"))]
    )

    agent.client.chat.completions.create.side_effect = [response_1, response_2]

    result = agent.run("test prompt", max_iterations=2)

    assert result == "final"
    second_call_kwargs = agent.client.chat.completions.create.call_args_list[1].kwargs
    assistant_turn = second_call_kwargs["messages"][2]
    assert assistant_turn["tool_calls"][0]["extra_content"]["google"]["thought_signature"] == "sig_123"
    assert agent.last_run_artifact["system_prompt"] == agent.system_prompt
    assert agent.last_run_artifact["user_prompt"] == "test prompt"
    assert agent.last_run_artifact["raw_final_output"] == "final"
    assert agent.last_run_artifact["parsed_output"] == "final"
    assert agent.last_run_artifact["api_trace"][0]["finish_reason"] == "tool_calls"
