"""Explicit provider bindings for the reconciled valuation judgment path."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit

from config.llm_routing import (
    resolve_family_projection_limit_chars,
    resolve_llm_route,
)
from src.contracts.assumption_registry import DriverFamily
from src.contracts.judgment_runs import ProviderRoute, SamplingControls
from src.stage_03_judgment.judgment_backends import (
    CodexCLIJudgmentBackend,
    OpenAICompatibleJudgmentBackend,
)
from src.stage_04_pipeline.valuation_judgment_pipeline import (
    DriverFamilyExecutionBinding,
)


_SUPPORTED_BACKENDS = frozenset(
    {"codex", "openrouter", "openai-compatible"}
)
_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
_SCHEMA_CAPABILITY = "chat-completions:json-schema"


def _value(environment: Mapping[str, str], name: str) -> str:
    return str(environment.get(name) or "").strip()


@dataclass(frozen=True, slots=True)
class ProviderBindingSettings:
    """Credential-bearing runtime settings; routes remain credential-free."""

    backend: str
    primary_model: str
    critic_model: str
    base_url: str | None = None
    endpoint_capability: str = _SCHEMA_CAPABILITY
    reasoning_effort: str | None = None
    codex_executable: str | None = None
    api_key: str | None = field(default=None, repr=False, compare=False)

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
    ) -> "ProviderBindingSettings":
        """Resolve one explicit provider configuration without hidden fallback."""

        source = dict(os.environ if environment is None else environment)
        if environment is None:
            route = resolve_llm_route(
                "valuation",
                env=source,
                model_env_names=("ALPHA_POD_JUDGMENT_PRIMARY_MODEL",),
            )
            source.setdefault(
                "ALPHA_POD_JUDGMENT_BACKEND", str(route["provider"])
            )
            source.setdefault(
                "ALPHA_POD_JUDGMENT_PRIMARY_MODEL", str(route["model"])
            )
            if route.get("effort"):
                source.setdefault(
                    "ALPHA_POD_JUDGMENT_REASONING_EFFORT",
                    str(route["effort"]),
                )
        backend = _value(source, "ALPHA_POD_JUDGMENT_BACKEND").lower()
        if not backend:
            raise ValueError(
                "ALPHA_POD_JUDGMENT_BACKEND is required"
            )
        if backend not in _SUPPORTED_BACKENDS:
            raise ValueError(
                f"unsupported judgment backend: {backend}"
            )

        primary_model = _value(
            source,
            "ALPHA_POD_JUDGMENT_PRIMARY_MODEL",
        )
        if not primary_model:
            raise ValueError(
                "ALPHA_POD_JUDGMENT_PRIMARY_MODEL is required"
            )
        critic_model = (
            _value(source, "ALPHA_POD_JUDGMENT_CRITIC_MODEL")
            or primary_model
        )
        reasoning_effort = (
            _value(source, "ALPHA_POD_JUDGMENT_REASONING_EFFORT")
            or None
        )

        if backend == "codex":
            return cls(
                backend=backend,
                primary_model=primary_model,
                critic_model=critic_model,
                endpoint_capability="exec:json-schema",
                reasoning_effort=reasoning_effort,
                codex_executable=(
                    _value(source, "ALPHA_POD_CODEX_EXECUTABLE")
                    or None
                ),
            )

        api_key = _value(
            source,
            "ALPHA_POD_JUDGMENT_API_KEY",
        )
        if not api_key:
            key_name = (
                "OPENROUTER_API_KEY"
                if backend == "openrouter"
                else "OPENAI_API_KEY"
            )
            api_key = _value(source, key_name)
        if not api_key:
            raise ValueError(
                f"API key is required for {backend}"
            )

        base_url = (
            _value(source, "ALPHA_POD_JUDGMENT_BASE_URL")
            or _value(source, "LLM_BASE_URL")
            or _value(source, "OPENAI_BASE_URL")
            or (
                _OPENROUTER_BASE_URL
                if backend == "openrouter"
                else ""
            )
        )
        capability = (
            _value(
                source,
                "ALPHA_POD_JUDGMENT_ENDPOINT_CAPABILITY",
            )
            or _SCHEMA_CAPABILITY
        )
        if "json-schema" not in capability.lower():
            raise ValueError(
                "judgment endpoint capability must support json-schema"
            )
        return cls(
            backend=backend,
            primary_model=primary_model,
            critic_model=critic_model,
            base_url=base_url or None,
            endpoint_capability=capability,
            reasoning_effort=reasoning_effort,
            api_key=api_key,
        )


def _endpoint_identity(settings: ProviderBindingSettings) -> str:
    if settings.backend == "codex":
        return "local"
    if settings.base_url is None:
        return "api.openai.com"
    parsed = urlsplit(settings.base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(
            "judgment base URL must be an absolute HTTP(S) URL"
        )
    port = f":{parsed.port}" if parsed.port is not None else ""
    return f"{parsed.hostname.lower()}{port}"


def _route(
    settings: ProviderBindingSettings,
    *,
    family: DriverFamily,
    role: str,
    model: str,
    endpoint_identity: str,
) -> ProviderRoute:
    is_codex = settings.backend == "codex"
    return ProviderRoute(
        route_id=(
            f"valuation:{settings.backend}:{endpoint_identity}:"
            f"{family.value}:{role}:{model}"
        ),
        provider=settings.backend,
        adapter_id=(
            "codex-exec"
            if is_codex
            else "openai-compatible-chat"
        ),
        adapter_version="1.0.0",
        requested_model=model,
        endpoint_capability=settings.endpoint_capability,
        sampling=SamplingControls(
            reasoning_effort=settings.reasoning_effort,
        ),
    )


def _default_openai_client_factory(**kwargs: Any) -> Any:
    from openai import OpenAI

    return OpenAI(**kwargs)


def build_driver_family_bindings(
    settings: ProviderBindingSettings,
    *,
    openai_client_factory: Callable[..., Any] | None = None,
    codex_backend_factory: Callable[..., Any] | None = None,
) -> dict[DriverFamily, DriverFamilyExecutionBinding]:
    """Bind every driver family to explicit primary and critic routes."""

    endpoint_identity = _endpoint_identity(settings)
    if settings.backend == "codex":
        backend_factory = (
            codex_backend_factory or CodexCLIJudgmentBackend
        )
        backend = backend_factory(
            executable=settings.codex_executable,
        )
    else:
        client_factory = (
            openai_client_factory
            or _default_openai_client_factory
        )
        client_options: dict[str, Any] = {
            "api_key": settings.api_key,
        }
        if settings.base_url is not None:
            client_options["base_url"] = settings.base_url
        backend = OpenAICompatibleJudgmentBackend(
            client_factory(**client_options)
        )

    return {
        family: DriverFamilyExecutionBinding(
            primary_route=_route(
                settings,
                family=family,
                role="primary",
                model=settings.primary_model,
                endpoint_identity=endpoint_identity,
            ),
            primary_backend=backend,
            critic_route=_route(
                settings,
                family=family,
                role="critic",
                model=settings.critic_model,
                endpoint_identity=endpoint_identity,
            ),
            critic_backend=backend,
            max_projection_chars=resolve_family_projection_limit_chars(
                settings.backend,
                settings.primary_model,
                settings.critic_model,
            ),
        )
        for family in DriverFamily
    }


__all__ = [
    "ProviderBindingSettings",
    "build_driver_family_bindings",
]
