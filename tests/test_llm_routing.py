from __future__ import annotations

from config.llm_routing import format_llm_resolution, resolve_llm_route


def _config(*roles: tuple[str, dict[str, str]]) -> dict:
    return {"llm": {"roles": dict(roles)}}


def test_judgment_precedence_is_cli_then_environment_then_config_then_fallback() -> None:
    empty_config = _config()
    fallback = resolve_llm_route("judgment", config=empty_config, env={})
    assert fallback["provider"] == "openrouter"
    assert fallback["model"] == "gemini-3-flash-preview"
    assert fallback["sources"]["provider"] == "fallback"
    assert fallback["sources"]["model"] == "fallback"

    configured = resolve_llm_route(
        "judgment",
        config=_config(
            ("judgment", {"provider": "openrouter", "model": "config/judgment"})
        ),
        env={},
    )
    assert configured["model"] == "config/judgment"
    assert configured["sources"]["model"] == "config"

    environment = resolve_llm_route(
        "judgment",
        config=_config(
            ("judgment", {"provider": "codex", "model": "config/judgment"})
        ),
        env={
            "ALPHA_POD_AGENT_BACKEND": "openrouter",
            "OPENROUTER_FREE_MODEL": "env/judgment",
        },
    )
    assert environment["provider"] == "openrouter"
    assert environment["model"] == "env/judgment"
    assert environment["sources"]["provider"] == "environment:ALPHA_POD_AGENT_BACKEND"
    assert environment["sources"]["model"] == "environment:OPENROUTER_FREE_MODEL"

    cli = resolve_llm_route(
        "judgment",
        cli_provider="openrouter",
        cli_model="cli/judgment",
        config=_config(
            ("judgment", {"provider": "codex", "model": "config/judgment"})
        ),
        env={
            "ALPHA_POD_AGENT_BACKEND": "codex",
            "ALPHA_POD_CODEX_MODEL": "env/judgment",
        },
    )
    assert cli["provider"] == "openrouter"
    assert cli["model"] == "cli/judgment"
    assert cli["sources"]["provider"] == "cli"
    assert cli["sources"]["model"] == "cli"


def test_accounting_precedence_includes_codex_effort() -> None:
    empty_config = _config()
    fallback = resolve_llm_route("accounting", config=empty_config, env={})
    assert fallback["provider"] == "codex"
    assert fallback["model"] == "gpt-5.6-luna"
    assert fallback["effort"] == "low"

    configured = resolve_llm_route(
        "accounting",
        config=_config(
            (
                "accounting",
                {"provider": "codex", "model": "config/accounting", "effort": "medium"},
            )
        ),
        env={},
    )
    assert configured["model"] == "config/accounting"
    assert configured["effort"] == "medium"
    assert configured["sources"]["model"] == "config"
    assert configured["sources"]["effort"] == "config"

    environment = resolve_llm_route(
        "accounting",
        config=_config(
            (
                "accounting",
                {"provider": "openrouter", "model": "config/accounting", "effort": "medium"},
            )
        ),
        env={
            "ALPHA_POD_AGENT_BACKEND": "codex",
            "ALPHA_POD_CODEX_MODEL": "env/accounting",
            "ALPHA_POD_CODEX_EFFORT": "high",
        },
    )
    assert environment["model"] == "env/accounting"
    assert environment["effort"] == "high"
    assert environment["sources"]["model"] == "environment:ALPHA_POD_CODEX_MODEL"
    assert environment["sources"]["effort"] == "environment:ALPHA_POD_CODEX_EFFORT"

    cli = resolve_llm_route(
        "accounting",
        cli_provider="codex",
        cli_model="cli/accounting",
        cli_effort="low",
        config=_config(
            (
                "accounting",
                {"provider": "openrouter", "model": "config/accounting", "effort": "high"},
            )
        ),
        env={
            "ALPHA_POD_AGENT_BACKEND": "openrouter",
            "ALPHA_POD_CODEX_MODEL": "env/accounting",
            "ALPHA_POD_CODEX_EFFORT": "high",
        },
    )
    assert cli["provider"] == "codex"
    assert cli["model"] == "cli/accounting"
    assert cli["effort"] == "low"
    assert cli["sources"]["provider"] == "cli"
    assert cli["sources"]["model"] == "cli"
    assert cli["sources"]["effort"] == "cli"


def test_configured_model_is_not_used_for_a_different_explicit_provider() -> None:
    route = resolve_llm_route(
        "judgment",
        cli_provider="codex",
        config=_config(
            ("judgment", {"provider": "openrouter", "model": "config/openrouter"})
        ),
        env={},
    )

    assert route["provider"] == "codex"
    assert route["model"] == "gpt-5.6-luna"
    assert route["sources"]["model"] == "fallback"


def test_resolved_route_is_logged_for_a_base_agent_run(caplog, monkeypatch) -> None:
    monkeypatch.setenv("ALPHA_POD_AGENT_BACKEND", "openrouter")
    monkeypatch.setenv("OPENROUTER_FREE_MODEL", "env/logged-model")

    from src.stage_03_judgment.base_agent import BaseAgent

    with caplog.at_level("INFO", logger="src.stage_03_judgment.base_agent"):
        BaseAgent()

    assert any(
        "Agent LLM routing: role=judgment provider=openrouter" in record.message
        and "model=env/logged-model" in record.message
        and "model:environment:OPENROUTER_FREE_MODEL" in record.message
        for record in caplog.records
    )


def test_format_llm_resolution_logs_model_provider_and_each_source_layer() -> None:
    route = resolve_llm_route(
        "accounting",
        config=_config(
            (
                "accounting",
                {"provider": "codex", "model": "config/accounting", "effort": "low"},
            )
        ),
        env={},
    )

    line = format_llm_resolution(route)

    assert "role=accounting" in line
    assert "provider=codex" in line
    assert "model=config/accounting" in line
    assert "effort=low" in line
    assert "provider:config" in line
    assert "model:config" in line
    assert "effort:config" in line


def test_seeded_role_block_routes_judgment_valuation_and_accounting() -> None:
    judgment = resolve_llm_route("judgment", env={})
    valuation = resolve_llm_route("valuation", env={})
    accounting = resolve_llm_route("accounting", env={})

    assert (judgment["provider"], judgment["model"]) == (
        "openrouter",
        "deepseek/deepseek-v4-flash-0731",
    )
    assert (valuation["provider"], valuation["model"]) == (
        "openrouter",
        "deepseek/deepseek-v4-flash-0731",
    )
    assert (accounting["provider"], accounting["model"], accounting["effort"]) == (
        "codex",
        "gpt-5.6-luna",
        "low",
    )
