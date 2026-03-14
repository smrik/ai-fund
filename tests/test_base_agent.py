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
