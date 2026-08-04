from __future__ import annotations

import pytest

from src.contracts.judgment_runs import (
    AgentAttemptStatus,
    AgentRunAttempt,
    AgentRunEnvelope,
    AgentRunStatus,
    AgentTraceMetadata,
    JudgmentTask,
    ProviderRoute,
    SamplingControls,
    canonical_semantic_hash,
    invocation_hash,
    semantic_task_hash,
)


def _judgment_task(**changes: object) -> JudgmentTask:
    payload: dict[str, object] = {
        "task_version": "1.0.0",
        "ticker": "msft",
        "family": "revenue",
        "role": "primary",
        "frozen_snapshot_hash": canonical_semantic_hash({"revenue": [100, 120]}),
        "prompt_id": "driver-family.revenue",
        "prompt_hash": canonical_semantic_hash({"prompt": "Assess revenue."}),
        "schema_id": "driver-family-pack",
        "schema_hash": canonical_semantic_hash({"type": "object"}),
        "compiler_id": "focused-judgment-messages",
        "compiler_hash": canonical_semantic_hash({"version": 1}),
        "messages": [
            {"role": "system", "content": "Use only the frozen evidence."},
            {"role": "user", "content": "Assess MSFT revenue."},
        ],
    }
    payload.update(changes)
    return JudgmentTask.model_validate(payload)


def _provider_route(**changes: object) -> ProviderRoute:
    payload: dict[str, object] = {
        "route_id": "openrouter-primary",
        "provider": "openrouter",
        "adapter_id": "openai-compatible",
        "adapter_version": "1.0.0",
        "requested_model": "openai/gpt-oss-120b",
        "endpoint_capability": "chat-completions:json-schema",
        "sampling": {"temperature": 0.0, "max_output_tokens": 4096},
    }
    payload.update(changes)
    return ProviderRoute.model_validate(payload)


def test_canonical_semantic_hash_ignores_mapping_order() -> None:
    left = {
        "ticker": "MSFT",
        "context": {"statement": "income", "periods": ["2025", "2024"]},
    }
    right = {
        "context": {"periods": ["2025", "2024"], "statement": "income"},
        "ticker": "MSFT",
    }

    assert canonical_semantic_hash(left) == canonical_semantic_hash(right)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_canonical_semantic_hash_rejects_non_finite_numbers(value: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        canonical_semantic_hash({"value": value})


def test_semantic_task_identity_is_provider_neutral_but_invocation_identity_is_not() -> None:
    task = _judgment_task()
    openrouter = _provider_route()
    codex = _provider_route(
        route_id="codex-primary",
        provider="codex",
        adapter_id="codex-exec",
        requested_model="gpt-5.6-luna",
        endpoint_capability="exec:structured-text",
        sampling=SamplingControls(
            reasoning_effort="low",
            max_output_tokens=4096,
        ),
    )

    assert task.ticker == "MSFT"
    assert task.semantic_task_hash == semantic_task_hash(task)
    assert invocation_hash(task, openrouter) != invocation_hash(task, codex)
    assert task.semantic_task_hash == semantic_task_hash(task)


def test_provider_route_is_versioned_and_forbids_credentials() -> None:
    route = _provider_route()

    assert route.contract_version == "1.0.0"
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        _provider_route(api_key="must-not-be-persisted")


def test_successful_run_envelope_records_validated_payload_and_trace_identity() -> None:
    task = _judgment_task()
    route = _provider_route()
    validated_payload = {
        "family": "revenue",
        "base": {"revenue_growth_near": 0.12},
    }
    attempt = AgentRunAttempt(
        attempt_number=1,
        status=AgentAttemptStatus.succeeded,
        validated_payload=validated_payload,
        trace=AgentTraceMetadata(
            provider_request_id="generation-123",
            actual_model="openai/gpt-oss-120b-2026-07-01",
            started_at="2026-07-26T12:00:00Z",
            completed_at="2026-07-26T12:00:03Z",
            latency_ms=3000,
            prompt_tokens=1500,
            completion_tokens=250,
            total_tokens=1750,
            cost_usd=0.004,
            finish_reason="stop",
            response_hash=canonical_semantic_hash(validated_payload),
        ),
    )
    envelope = AgentRunEnvelope(
        run_id="run-123",
        task=task,
        route=route,
        status=AgentRunStatus.succeeded,
        attempts=[attempt],
    )

    assert envelope.validated_payload == validated_payload
    assert envelope.semantic_task_hash == task.semantic_task_hash
    assert envelope.invocation_hash == invocation_hash(task, route)
    assert envelope.idempotency_key == invocation_hash(task, route)
    assert envelope.retry_count == 0
    assert envelope.repair_count == 0
    assert envelope.attempts[0].trace.actual_model.endswith("2026-07-01")


def test_run_envelope_orders_attempts_and_repairs_only_prior_attempts() -> None:
    trace = AgentTraceMetadata(
        actual_model="openai/gpt-oss-120b",
        started_at="2026-07-26T12:00:00Z",
    )
    rejected = AgentRunAttempt(
        attempt_number=1,
        status=AgentAttemptStatus.validation_failed,
        trace=trace,
        validation_errors=("base scenario is missing",),
    )
    repaired = AgentRunAttempt(
        attempt_number=2,
        status=AgentAttemptStatus.succeeded,
        trace=trace,
        validated_payload={"base": {"revenue_growth_near": 0.12}},
        repair_of_attempt=1,
    )

    envelope = AgentRunEnvelope(
        run_id="run-with-repair",
        task=_judgment_task(),
        route=_provider_route(),
        status=AgentRunStatus.succeeded,
        attempts=[rejected, repaired],
    )

    assert [attempt.attempt_number for attempt in envelope.attempts] == [1, 2]
    assert envelope.retry_count == 1
    assert envelope.repair_count == 1

    self_referencing_repair = AgentRunAttempt(
        attempt_number=2,
        status=AgentAttemptStatus.succeeded,
        trace=trace,
        validated_payload={"base": {"revenue_growth_near": 0.12}},
        repair_of_attempt=2,
    )
    with pytest.raises(ValueError, match="earlier attempt"):
        AgentRunEnvelope(
            run_id="invalid-repair-order",
            task=_judgment_task(),
            route=_provider_route(),
            status=AgentRunStatus.succeeded,
            attempts=[rejected, self_referencing_repair],
        )
