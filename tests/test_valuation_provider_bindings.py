from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.contracts.assumption_registry import DriverFamily
from src.stage_04_pipeline.valuation_provider_bindings import (
    ProviderBindingSettings,
    build_driver_family_bindings,
)


def test_openrouter_settings_build_explicit_schema_bound_routes() -> None:
    settings = ProviderBindingSettings.from_environment(
        {
            "ALPHA_POD_JUDGMENT_BACKEND": "openrouter",
            "ALPHA_POD_JUDGMENT_PRIMARY_MODEL": "provider/primary",
            "ALPHA_POD_JUDGMENT_CRITIC_MODEL": "provider/critic",
            "OPENROUTER_API_KEY": "secret-key",
        }
    )
    client_calls: list[dict[str, object]] = []

    def client_factory(**kwargs: object) -> object:
        client_calls.append(kwargs)
        return SimpleNamespace(chat=SimpleNamespace())

    bindings = build_driver_family_bindings(
        settings,
        openai_client_factory=client_factory,
    )

    assert set(bindings) == set(DriverFamily)
    assert client_calls == [
        {
            "api_key": "secret-key",
            "base_url": "https://openrouter.ai/api/v1",
        }
    ]
    route_ids: set[str] = set()
    backends: set[int] = set()
    for family, binding in bindings.items():
        assert binding.primary_route.provider == "openrouter"
        assert binding.critic_route.provider == "openrouter"
        assert binding.primary_route.requested_model == "provider/primary"
        assert binding.critic_route.requested_model == "provider/critic"
        assert "json-schema" in binding.primary_route.endpoint_capability
        assert family.value in binding.primary_route.route_id
        assert "openrouter.ai" in binding.primary_route.route_id
        assert "secret-key" not in str(
            binding.primary_route.model_dump(mode="json")
        )
        route_ids.update(
            {
                binding.primary_route.route_id,
                binding.critic_route.route_id,
            }
        )
        backends.update(
            {
                id(binding.primary_backend),
                id(binding.critic_backend),
            }
        )
    assert len(route_ids) == len(DriverFamily) * 2
    assert len(backends) == 1


def test_codex_settings_do_not_construct_an_api_client() -> None:
    settings = ProviderBindingSettings.from_environment(
        {
            "ALPHA_POD_JUDGMENT_BACKEND": "codex",
            "ALPHA_POD_JUDGMENT_PRIMARY_MODEL": "gpt-primary",
            "ALPHA_POD_JUDGMENT_CRITIC_MODEL": "gpt-critic",
            "ALPHA_POD_JUDGMENT_REASONING_EFFORT": "medium",
            "ALPHA_POD_CODEX_EXECUTABLE": r"C:\tools\codex.exe",
        }
    )
    constructed: list[str | None] = []
    backend = object()

    def codex_factory(*, executable: str | None = None) -> object:
        constructed.append(executable)
        return backend

    def forbidden_client_factory(**_kwargs: object) -> object:
        raise AssertionError("Codex must not construct an API client")

    bindings = build_driver_family_bindings(
        settings,
        openai_client_factory=forbidden_client_factory,
        codex_backend_factory=codex_factory,
    )

    assert constructed == [r"C:\tools\codex.exe"]
    for binding in bindings.values():
        assert binding.primary_backend is backend
        assert binding.critic_backend is backend
        assert binding.primary_route.provider == "codex"
        assert binding.primary_route.adapter_id == "codex-exec"
        assert binding.primary_route.endpoint_capability == "exec:json-schema"
        assert binding.primary_route.sampling.reasoning_effort == "medium"
        assert binding.primary_route.sampling.temperature is None
        assert binding.primary_route.sampling.max_output_tokens is None


def test_direct_openai_compatible_route_uses_explicit_endpoint() -> None:
    settings = ProviderBindingSettings.from_environment(
        {
            "ALPHA_POD_JUDGMENT_BACKEND": "openai-compatible",
            "ALPHA_POD_JUDGMENT_PRIMARY_MODEL": "model-a",
            "ALPHA_POD_JUDGMENT_CRITIC_MODEL": "model-b",
            "ALPHA_POD_JUDGMENT_BASE_URL": "https://llm.example.test/v1",
            "ALPHA_POD_JUDGMENT_API_KEY": "api-key",
        }
    )
    client_calls: list[dict[str, object]] = []

    def client_factory(**kwargs: object) -> object:
        client_calls.append(kwargs)
        return SimpleNamespace(chat=SimpleNamespace())

    bindings = build_driver_family_bindings(
        settings,
        openai_client_factory=client_factory,
    )

    assert client_calls == [
        {
            "api_key": "api-key",
            "base_url": "https://llm.example.test/v1",
        }
    ]
    route = bindings[DriverFamily.revenue].primary_route
    assert route.provider == "openai-compatible"
    assert "llm.example.test" in route.route_id


@pytest.mark.parametrize(
    ("environment", "message"),
    [
        ({}, "ALPHA_POD_JUDGMENT_BACKEND"),
        (
            {"ALPHA_POD_JUDGMENT_BACKEND": "codex"},
            "ALPHA_POD_JUDGMENT_PRIMARY_MODEL",
        ),
        (
            {
                "ALPHA_POD_JUDGMENT_BACKEND": "openrouter",
                "ALPHA_POD_JUDGMENT_PRIMARY_MODEL": "model",
            },
            "API key",
        ),
        (
            {
                "ALPHA_POD_JUDGMENT_BACKEND": "unknown",
                "ALPHA_POD_JUDGMENT_PRIMARY_MODEL": "model",
            },
            "unsupported",
        ),
    ],
)
def test_provider_settings_fail_closed(
    environment: dict[str, str],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        ProviderBindingSettings.from_environment(environment)
