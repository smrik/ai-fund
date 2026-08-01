"""Provider/model routing for the judgment layer.

The YAML role block is the durable default. Runtime flags and environment
variables are intentionally evaluated at call time so replay metadata reflects
the process that actually ran.
"""
from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from typing import Any

import config as app_config


_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
_ROLE_FALLBACKS: dict[str, dict[str, str]] = {
    "judgment": {"provider": "openrouter", "model": "gemini-3-flash-preview"},
    "valuation": {"provider": "openrouter", "model": "gemini-3-flash-preview"},
    "accounting": {"provider": "codex", "model": "gpt-5.6-luna", "effort": "low"},
}
_PROVIDER_FALLBACKS: dict[str, dict[str, str]] = {
    "openrouter": {"model": "gemini-3-flash-preview"},
    "codex": {"model": "gpt-5.6-luna", "effort": "low"},
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _first_value(
    env: Mapping[str, str], names: Sequence[str]
) -> tuple[str | None, str | None]:
    for name in names:
        value = _text(env.get(name))
        if value:
            return value, name
    return None, None


def _role_config(role: str, config: Mapping[str, Any]) -> dict[str, Any]:
    llm_config = config.get("llm")
    if not isinstance(llm_config, Mapping):
        return {}
    roles = llm_config.get("roles")
    if not isinstance(roles, Mapping):
        return {}
    selected = roles.get(role)
    return dict(selected) if isinstance(selected, Mapping) else {}


def _provider_base_url(
    provider: str,
    *,
    env: Mapping[str, str],
    config: Mapping[str, Any],
) -> tuple[str, str]:
    env_value, env_name = _first_value(env, ("LLM_BASE_URL", "OPENAI_BASE_URL"))
    if env_value:
        return env_value, f"environment:{env_name}"
    if provider == "openrouter":
        return _OPENROUTER_BASE_URL, "provider-default"
    llm_config = config.get("llm")
    configured = llm_config.get("base_url") if isinstance(llm_config, Mapping) else None
    if _text(configured):
        return _text(configured), "config"
    return "", "fallback"


def resolve_llm_route(
    role: str,
    *,
    cli_provider: str | None = None,
    cli_model: str | None = None,
    cli_effort: str | None = None,
    env: Mapping[str, str] | None = None,
    config: Mapping[str, Any] | None = None,
    model_env_names: Sequence[str] = (),
) -> dict[str, Any]:
    """Resolve one role with CLI > environment > config > fallback precedence."""
    active_env = env if env is not None else os.environ
    active_config = config if config is not None else app_config.get_config()
    role_config = _role_config(role, active_config)
    fallback = _ROLE_FALLBACKS.get(role, _ROLE_FALLBACKS["judgment"])

    config_provider = _text(role_config.get("provider")).lower()
    cli_provider_value = _text(cli_provider).lower()
    env_provider, env_provider_name = _first_value(
        active_env,
        (
            "ALPHA_POD_AGENT_BACKEND",
            "ALPHA_POD_LLM_PROVIDER",
            "ALPHA_POD_JUDGMENT_BACKEND",
        ),
    )
    provider = cli_provider_value or _text(env_provider).lower() or config_provider or fallback["provider"]
    provider_source = (
        "cli"
        if cli_provider_value
        else f"environment:{env_provider_name}"
        if env_provider
        else "config"
        if config_provider
        else "fallback"
    )

    cli_model_value = _text(cli_model)
    model_env_candidates = (
        ("ALPHA_POD_CODEX_MODEL",) if provider == "codex" else ("OPENROUTER_FREE_MODEL",)
    )
    model_env_candidates = (*model_env_candidates, *model_env_names, "LLM_MODEL")
    env_model, env_model_name = _first_value(active_env, model_env_candidates)
    config_model = _text(role_config.get("model"))
    config_model_compatible = not config_provider or config_provider == provider
    provider_fallback = _PROVIDER_FALLBACKS.get(provider, _PROVIDER_FALLBACKS["openrouter"])
    if cli_model_value:
        model = cli_model_value
        model_source = "cli"
    elif env_model:
        model = env_model
        model_source = f"environment:{env_model_name}"
    elif config_model and config_model_compatible:
        model = config_model
        model_source = "config"
    else:
        model = provider_fallback["model"]
        model_source = "fallback"

    if provider == "codex":
        env_effort, env_effort_name = _first_value(
            active_env,
            (
                "ALPHA_POD_CODEX_EFFORT",
                "LLM_REASONING_EFFORT",
                "ALPHA_POD_JUDGMENT_REASONING_EFFORT",
            ),
        )
        config_effort = _text(role_config.get("effort")) if config_model_compatible else ""
        cli_effort_value = _text(cli_effort)
        if cli_effort_value:
            effort = cli_effort_value
            effort_source = "cli"
        elif env_effort:
            effort = env_effort
            effort_source = f"environment:{env_effort_name}"
        elif config_effort:
            effort = config_effort
            effort_source = "config"
        else:
            effort = provider_fallback.get("effort", "low")
            effort_source = "fallback"
    else:
        effort = None
        effort_source = "not_applicable"

    base_url, base_url_source = _provider_base_url(provider, env=active_env, config=active_config)
    sources = {
        "provider": provider_source,
        "model": model_source,
        "effort": effort_source,
        "base_url": base_url_source,
    }
    return {
        "role": role,
        "provider": provider,
        "backend": provider,
        "model": model,
        "effort": effort,
        "base_url": base_url,
        "sources": sources,
        "provider_source": provider_source,
        "model_source": model_source,
        "effort_source": effort_source,
        "source": model_source,
    }


def format_llm_resolution(route: Mapping[str, Any]) -> str:
    """Return a replay-oriented one-line route record."""
    sources = route.get("sources") or {}
    source_text = ",".join(
        f"{field}:{sources.get(field, 'unknown')}"
        for field in ("provider", "model", "effort")
    )
    return (
        "Agent LLM routing: "
        f"role={route.get('role') or 'unknown'} "
        f"provider={route.get('provider') or 'unknown'} "
        f"model={route.get('model') or 'not configured'} "
        f"effort={route.get('effort') or 'none'} "
        f"sources={source_text}"
    )
