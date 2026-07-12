import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.stage_03_judgment.base_agent import BaseAgent


def test_base_agent_initializes():
    agent = BaseAgent()
    assert agent.client is not None
    assert agent.name == "BaseAgent"


def test_base_agent_resolves_base_url_at_construction(monkeypatch):
    sentinel = "https://sentinel.example/v1"
    monkeypatch.setenv("LLM_BASE_URL", sentinel)

    agent = BaseAgent()

    assert str(agent.client.base_url).startswith(sentinel)


def test_base_agent_resolves_default_model_at_construction(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "sentinel/model")

    agent = BaseAgent()

    assert agent.model == "sentinel/model"
    assert agent.last_used_model == "sentinel/model"


def test_codex_backend_returns_final_message_and_records_provenance(monkeypatch):
    monkeypatch.setenv("ALPHA_POD_AGENT_BACKEND", "codex")
    monkeypatch.setenv("ALPHA_POD_CODEX_MODEL", "gpt-5.6-luna")
    monkeypatch.setenv("ALPHA_POD_CODEX_EFFORT", "low")
    calls: dict[str, object] = {}

    def fake_run(command, *, input, text, capture_output, timeout, check, env=None):
        calls.update(
            command=command,
            input=input,
            text=text,
            capture_output=capture_output,
            timeout=timeout,
            check=check,
            env=env,
            # The empty AGENTS_HOME only exists during the call (temp dir),
            # so existence must be captured here, not asserted afterwards.
            agents_home_skills_exists=(
                env is not None
                and "AGENTS_HOME" in env
                and (Path(env["AGENTS_HOME"]) / "skills").is_dir()
            ),
        )
        output_path = Path(command[command.index("-o") + 1])
        output_path.write_text("codex answer", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="banner", stderr="")

    monkeypatch.setattr("src.stage_03_judgment.base_agent.subprocess.run", fake_run)

    agent = BaseAgent()

    assert agent.run("return a short answer") == "codex answer"
    assert agent.last_used_model == "codex:gpt-5.6-luna@low"
    assert agent.last_run_artifact["raw_final_output"] == "codex answer"
    assert agent.last_run_artifact["parsed_output"] == "codex answer"
    assert agent.last_run_artifact["api_trace"][0]["model"] == "codex:gpt-5.6-luna@low"
    assert agent.last_run_artifact["api_trace"][0]["backend"] == "codex"
    assert calls["timeout"] == 120
    assert calls["check"] is False
    command = calls["command"]
    assert "--ephemeral" in command
    assert "--ignore-user-config" not in command
    assert command[command.index("-s") + 1] == "read-only"
    assert command[command.index("-m") + 1] == "gpt-5.6-luna"
    assert command[command.index("-c") + 1] == "model_reasoning_effort=low"
    assert "-o" in command
    assert command[-1] == "-"
    # Minimal-context invocation: the user's skills library must not be scanned.
    assert calls["agents_home_skills_exists"] is True


def test_codex_backend_honors_explicit_executable(monkeypatch):
    monkeypatch.setenv("ALPHA_POD_AGENT_BACKEND", "codex")
    monkeypatch.setenv("ALPHA_POD_CODEX_EXECUTABLE", r"C:\\tmp\\codex-current.exe")
    calls: dict[str, object] = {}

    def fake_run(command, *, input, text, capture_output, timeout, check, env=None):
        calls["command"] = command
        output_path = Path(command[command.index("-o") + 1])
        output_path.write_text("isolated codex answer", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("src.stage_03_judgment.base_agent.subprocess.run", fake_run)

    assert BaseAgent().run("use the selected executable") == "isolated codex answer"
    assert calls["command"][0] == r"C:\\tmp\\codex-current.exe"


def test_codex_backend_honors_configurable_timeout(monkeypatch):
    monkeypatch.setenv("ALPHA_POD_AGENT_BACKEND", "codex")
    monkeypatch.setenv("ALPHA_POD_CODEX_TIMEOUT_SECONDS", "240")
    calls: dict[str, object] = {}

    def fake_run(command, *, input, text, capture_output, timeout, check, env=None):
        calls["timeout"] = timeout
        output_path = Path(command[command.index("-o") + 1])
        output_path.write_text("patient codex answer", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("src.stage_03_judgment.base_agent.subprocess.run", fake_run)

    assert BaseAgent().run("wait for the real response") == "patient codex answer"
    assert calls["timeout"] == 240


def test_codex_backend_can_fail_closed_without_provider_fallback(monkeypatch):
    monkeypatch.setenv("ALPHA_POD_AGENT_BACKEND", "codex")
    monkeypatch.setenv("ALPHA_POD_CODEX_ALLOW_FALLBACK", "0")

    def fake_run(command, *, input, text, capture_output, timeout, check, env=None):
        return SimpleNamespace(returncode=7, stdout="", stderr="codex failed")

    monkeypatch.setattr("src.stage_03_judgment.base_agent.subprocess.run", fake_run)
    agent = BaseAgent()

    with pytest.raises(RuntimeError, match="codex exec exited with status 7"):
        agent.run("do not hide a real-agent failure")

    assert agent.last_run_artifact["codex_error"] == {
        "type": "RuntimeError",
        "message": "codex exec exited with status 7: codex failed",
    }

def test_codex_backend_passes_long_prompt_via_stdin_not_argv(monkeypatch):
    monkeypatch.setenv("ALPHA_POD_AGENT_BACKEND", "codex")
    long_prompt = "evidence " * 5_000
    calls: dict[str, object] = {}

    def fake_run(command, *, input, text, capture_output, timeout, check, env=None):
        calls["command"] = command
        calls["input"] = input
        output_path = Path(command[command.index("-o") + 1])
        output_path.write_text("long prompt answer", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("src.stage_03_judgment.base_agent.subprocess.run", fake_run)

    result = BaseAgent().run(long_prompt)

    command = calls["command"]
    prompt = calls["input"]
    assert result == "long prompt answer"
    assert command[-1] == "-"
    assert long_prompt not in command
    assert long_prompt in prompt
    assert "Do not use tools, do not read or write files, do not run commands." in prompt


def test_codex_backend_skips_structured_parse(monkeypatch):
    monkeypatch.setenv("ALPHA_POD_AGENT_BACKEND", "codex")

    agent = BaseAgent()

    assert agent.run_structured_payload("format this", dict) == (None, None)


def test_codex_backend_falls_back_to_openai_client_with_provenance(monkeypatch):
    monkeypatch.setenv("ALPHA_POD_AGENT_BACKEND", "codex")
    monkeypatch.setenv("ALPHA_POD_CODEX_MODEL", "gpt-5.6-luna")
    monkeypatch.setenv("ALPHA_POD_CODEX_EFFORT", "low")
    monkeypatch.setenv("LLM_MODEL", "openrouter/free")

    def fake_run(command, *, input, text, capture_output, timeout, check, env=None):
        return SimpleNamespace(returncode=7, stdout="", stderr="codex failed")

    monkeypatch.setattr("src.stage_03_judgment.base_agent.subprocess.run", fake_run)
    agent = BaseAgent()
    agent.client = MagicMock()
    agent.client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content="fallback answer"))],
        usage=None,
        model="openrouter/free",
    )

    assert agent.run("use the fallback") == "fallback answer"
    assert agent.last_used_model == "openrouter/free (fallback)"
    assert agent.last_run_artifact["api_trace"][0]["model"] == "openrouter/free (fallback)"
    assert agent.client.chat.completions.create.call_args.kwargs["model"] == "openrouter/free"


@pytest.mark.parametrize("failure", ["empty", "timeout"])
def test_codex_backend_empty_or_timed_out_process_falls_back(monkeypatch, failure):
    monkeypatch.setenv("ALPHA_POD_AGENT_BACKEND", "codex")
    monkeypatch.setenv("LLM_MODEL", "openrouter/free")

    def fake_run(command, *, input, text, capture_output, timeout, check, env=None):
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, timeout)
        output_path = Path(command[command.index("-o") + 1])
        output_path.write_text("", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("src.stage_03_judgment.base_agent.subprocess.run", fake_run)
    agent = BaseAgent()
    agent.client = MagicMock()
    agent.client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content="fallback answer"))],
        usage=None,
        model="openrouter/free",
    )

    assert agent.run("use fallback after process failure") == "fallback answer"
    assert agent.last_used_model == "openrouter/free (fallback)"


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
