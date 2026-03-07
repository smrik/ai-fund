from src.stage_03_judgment.base_agent import BaseAgent


def test_base_agent_initializes():
    agent = BaseAgent()
    assert agent.client is not None
    assert agent.name == "BaseAgent"


def test_tool_format_is_anthropic():
    """Tool definitions must use Anthropic format, not OpenAI format."""
    tool = BaseAgent._tool(
        name="test_tool",
        description="A test tool",
        properties={"param": {"type": "string", "description": "A param"}},
        required=["param"],
    )
    # Anthropic format
    assert "name" in tool
    assert "input_schema" in tool
    assert tool["name"] == "test_tool"
    # Must NOT have OpenAI format
    assert "type" not in tool or tool.get("type") != "function"
    assert "function" not in tool


def test_tool_input_schema_structure():
    tool = BaseAgent._tool(
        name="my_tool",
        description="desc",
        properties={"x": {"type": "integer"}},
        required=["x"],
    )
    schema = tool["input_schema"]
    assert schema["type"] == "object"
    assert "x" in schema["properties"]
    assert "x" in schema["required"]
