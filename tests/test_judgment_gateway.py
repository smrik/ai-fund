from __future__ import annotations

import json

import pytest

from src.contracts.driver_families import DriverFamilyProposal
from src.contracts.judgment_runs import (
    JudgmentTask,
    ProviderRoute,
    canonical_semantic_hash,
)
from src.stage_03_judgment.judgment_gateway import (
    JudgmentBackendResponse,
    JudgmentGateway,
    JudgmentInvocationInProgressError,
)


def _task() -> JudgmentTask:
    output_schema = DriverFamilyProposal.model_json_schema()
    return JudgmentTask.model_validate(
        {
            "task_version": "1.0.0",
            "ticker": "TEST",
            "family": "revenue",
            "role": "primary",
            "frozen_snapshot_hash": "snapshot-1",
            "prompt_id": "driver-family.revenue",
            "prompt_hash": "prompt-hash",
            "schema_id": DriverFamilyProposal.__name__,
            "schema_hash": canonical_semantic_hash(output_schema),
            "compiler_id": "focused-message-compiler",
            "compiler_hash": "compiler-hash",
            "messages": [
                {"role": "system", "content": "Use only frozen evidence."},
                {"role": "user", "content": "Author the revenue pack."},
            ],
        }
    )


def _route(provider: str) -> ProviderRoute:
    return ProviderRoute.model_validate(
        {
            "route_id": f"{provider}-primary",
            "provider": provider,
            "adapter_id": f"{provider}-adapter",
            "adapter_version": "1.0.0",
            "requested_model": f"{provider}-model",
            "endpoint_capability": "structured",
            "sampling": {"temperature": 0.0, "max_output_tokens": 4096},
        }
    )


def _valid_revenue_payload() -> dict[str, object]:
    assumptions = []
    for name, values in (
        ("revenue_growth_near", (0.04, 0.07, 0.10)),
        ("revenue_growth_mid", (0.03, 0.05, 0.08)),
        ("revenue_growth_terminal", (0.015, 0.025, 0.03)),
    ):
        assumptions.append(
            {
                "assumption_name": name,
                "unit": "decimal",
                "applicability": "applicable",
                "low": values[0],
                "base": values[1],
                "high": values[2],
                "conditions": {
                    "low": f"Low condition for {name}.",
                    "base": f"Base condition for {name}.",
                    "high": f"High condition for {name}.",
                },
                "rationale": f"Evidence-grounded rationale for {name}.",
                "evidence_anchor_ids": [f"fact:{name}"],
                "what_would_change_view": f"New evidence for {name}.",
            }
        )
    return {
        "family": "revenue",
        "horizon_years": 10,
        "assumptions": assumptions,
        "family_rationale": "The pack follows disclosed demand evidence.",
    }


class _FixtureBackend:
    def __init__(self, provider: str, *, native: bool) -> None:
        self.provider = provider
        self.native = native
        self.call_count = 0

    def generate(self, request):
        self.call_count += 1
        payload = _valid_revenue_payload()
        return JudgmentBackendResponse(
            output=payload if self.native else json.dumps(payload),
            actual_model=f"{self.provider}-actual-model",
            provider_request_id=f"{self.provider}-request-1",
        )


def test_all_provider_adapters_pass_through_one_strict_normalization_path() -> None:
    gateway = JudgmentGateway()
    normalized = []
    for provider, native in (
        ("openai", True),
        ("openrouter", False),
        ("codex", False),
        ("generic", True),
    ):
        envelope = gateway.execute_structured(
            task=_task(),
            route=_route(provider),
            backend=_FixtureBackend(provider, native=native),
            output_model=DriverFamilyProposal,
        )
        assert envelope.status.value == "succeeded"
        assert envelope.attempts[-1].raw_response is not None
        assert envelope.attempts[-1].trace.latency_ms is not None
        normalized.append(envelope.validated_payload)

    assert normalized[1:] == normalized[:-1]


@pytest.mark.parametrize(
    "task_change",
    (
        {"schema_id": "DifferentContract"},
        {"schema_hash": "stale-schema-hash"},
    ),
)
def test_gateway_rejects_schema_identity_mismatch_before_provider_call(
    task_change: dict[str, str],
) -> None:
    backend = _FixtureBackend("openrouter", native=True)

    with pytest.raises(ValueError, match="output model schema"):
        JudgmentGateway().execute_structured(
            task=_task().model_copy(update=task_change),
            route=_route("openrouter"),
            backend=backend,
            output_model=DriverFamilyProposal,
        )

    assert backend.call_count == 0


class _RepairBackend:
    def __init__(self, *, repair_succeeds: bool) -> None:
        self.repair_succeeds = repair_succeeds
        self.requests = []

    def generate(self, request):
        self.requests.append(request)
        payload = _valid_revenue_payload()
        if len(self.requests) == 1 or not self.repair_succeeds:
            payload["unsupported_extra_field"] = "must fail"
        return JudgmentBackendResponse(
            output=payload,
            actual_model="repair-model",
            provider_request_id=f"repair-{len(self.requests)}",
        )


def test_gateway_allows_exactly_one_schema_repair_with_validator_feedback() -> None:
    backend = _RepairBackend(repair_succeeds=True)

    envelope = JudgmentGateway().execute_structured(
        task=_task(),
        route=_route("openrouter"),
        backend=backend,
        output_model=DriverFamilyProposal,
        transport_timeout_seconds=9.75,
    )

    assert envelope.status.value == "succeeded"
    assert len(envelope.attempts) == 2
    assert envelope.attempts[0].status.value == "validation_failed"
    assert envelope.attempts[0].raw_response is not None
    assert envelope.attempts[1].repair_of_attempt == 1
    assert backend.requests[1].validation_errors
    assert {
        request.transport_timeout_seconds for request in backend.requests
    } == {9.75}


def test_second_invalid_response_fails_closed_without_a_third_call() -> None:
    backend = _RepairBackend(repair_succeeds=False)

    envelope = JudgmentGateway().execute_structured(
        task=_task(),
        route=_route("openrouter"),
        backend=backend,
        output_model=DriverFamilyProposal,
    )

    assert envelope.status.value == "failed"
    assert envelope.validated_payload is None
    assert len(envelope.attempts) == len(backend.requests) == 2
    assert all(
        attempt.status.value == "validation_failed"
        for attempt in envelope.attempts
    )


def test_gateway_emits_every_terminal_envelope_to_the_persistence_sink() -> None:
    persisted = []
    gateway = JudgmentGateway(envelope_sink=persisted.append)

    envelope = gateway.execute_structured(
        task=_task(),
        route=_route("openai"),
        backend=_FixtureBackend("openai", native=True),
        output_model=DriverFamilyProposal,
    )

    assert persisted == [envelope]


@pytest.mark.parametrize("error_type", [ConnectionError, TimeoutError])
def test_gateway_persists_failed_envelope_before_retryable_error_bubbles(
    error_type: type[Exception],
) -> None:
    persisted = []
    gateway = JudgmentGateway(envelope_sink=persisted.append)

    class _RetryableFailureBackend:
        def generate(self, request):
            raise error_type("retryable transport failure")

    with pytest.raises(error_type, match="retryable transport failure"):
        gateway.execute_structured(
            task=_task(),
            route=_route("openrouter"),
            backend=_RetryableFailureBackend(),
            output_model=DriverFamilyProposal,
            transport_timeout_seconds=7.5,
        )

    assert len(persisted) == 1
    assert persisted[0].status.value == "failed"
    assert len(persisted[0].attempts) == 1
    assert persisted[0].attempts[0].status.value == "provider_error"


def test_gateway_rejects_blank_actual_model_as_a_provider_failure() -> None:
    class _BlankModelBackend:
        call_count = 0

        def generate(self, request):
            self.call_count += 1
            return JudgmentBackendResponse(
                output=_valid_revenue_payload(),
                actual_model="   ",
            )

    backend = _BlankModelBackend()
    envelope = JudgmentGateway().execute_structured(
        task=_task(),
        route=_route("openrouter"),
        backend=backend,
        output_model=DriverFamilyProposal,
    )

    assert backend.call_count == 1
    assert envelope.status.value == "failed"
    assert envelope.attempts[-1].status.value == "provider_error"
    assert "actual_model" in envelope.attempts[-1].validation_errors[0]


def test_force_refresh_bypasses_a_matching_successful_cache() -> None:
    backend = _FixtureBackend("openrouter", native=True)
    cached = JudgmentGateway().execute_structured(
        task=_task(),
        route=_route("openrouter"),
        backend=backend,
        output_model=DriverFamilyProposal,
        run_id="cached-run",
    )
    refreshing_backend = _FixtureBackend("openrouter", native=True)
    gateway = JudgmentGateway(
        successful_envelope_lookup=lambda _: cached,
    )

    refreshed = gateway.execute_structured(
        task=_task(),
        route=_route("openrouter"),
        backend=refreshing_backend,
        output_model=DriverFamilyProposal,
        run_id="refreshed-run",
        force_refresh=True,
    )

    assert refreshed.run_id == "refreshed-run"
    assert refreshing_backend.call_count == 1


def test_gateway_fails_fast_when_an_identical_invocation_is_reserved() -> None:
    backend = _FixtureBackend("openrouter", native=True)
    releases: list[tuple[str, str]] = []
    gateway = JudgmentGateway(
        invocation_reservation=lambda invocation_key, owner: False,
        invocation_release=lambda invocation_key, owner: releases.append(
            (invocation_key, owner)
        ),
    )

    with pytest.raises(JudgmentInvocationInProgressError):
        gateway.execute_structured(
            task=_task(),
            route=_route("openrouter"),
            backend=backend,
            output_model=DriverFamilyProposal,
            run_id="competing-run",
        )

    assert backend.call_count == 0
    assert releases == []


def test_gateway_releases_reservation_only_after_terminal_envelope_is_emitted() -> None:
    events: list[str] = []

    gateway = JudgmentGateway(
        envelope_sink=lambda envelope: events.append(
            f"emit:{envelope.run_id}"
        ),
        invocation_reservation=lambda invocation_key, owner: (
            events.append(f"reserve:{owner}") or True
        ),
        invocation_release=lambda invocation_key, owner: events.append(
            f"release:{owner}"
        ),
    )

    gateway.execute_structured(
        task=_task(),
        route=_route("openrouter"),
        backend=_FixtureBackend("openrouter", native=True),
        output_model=DriverFamilyProposal,
        run_id="reserved-run",
    )

    assert events == [
        "reserve:reserved-run",
        "emit:reserved-run",
        "release:reserved-run",
    ]
