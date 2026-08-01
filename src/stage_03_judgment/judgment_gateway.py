"""One strict structured-output boundary for every judgment provider."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from collections.abc import Callable
from typing import Any, Protocol, cast
from uuid import uuid4

from pydantic import BaseModel, ValidationError

from src.contracts.judgment_runs import (
    AgentAttemptStatus,
    AgentRunAttempt,
    AgentRunEnvelope,
    AgentRunStatus,
    AgentTraceMetadata,
    JudgmentTask,
    ProviderRoute,
    canonical_semantic_hash,
    invocation_hash,
)


@dataclass(frozen=True, slots=True)
class JudgmentBackendRequest:
    task: JudgmentTask
    route: ProviderRoute
    output_schema: dict[str, Any]
    attempt_number: int
    transport_timeout_seconds: float = 120.0
    validation_errors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (
            not math.isfinite(self.transport_timeout_seconds)
            or self.transport_timeout_seconds <= 0
        ):
            raise ValueError(
                "transport_timeout_seconds must be finite and positive"
            )


@dataclass(frozen=True, slots=True)
class JudgmentBackendResponse:
    output: Any
    actual_model: str
    provider_request_id: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    cost_usd: float | None = None
    finish_reason: str | None = None


class StructuredJudgmentBackend(Protocol):
    def generate(
        self,
        request: JudgmentBackendRequest,
    ) -> JudgmentBackendResponse: ...


class JudgmentInvocationInProgressError(RuntimeError):
    """An identical provider invocation already owns the execution lease."""


def _parse_output(output: Any) -> dict[str, Any]:
    if isinstance(output, dict):
        return dict(output)
    if not isinstance(output, str):
        raise ValueError("provider output must be a JSON object or JSON text")
    text = output.strip()
    if not text:
        raise ValueError("provider output is empty")
    if text.startswith("```") and text.endswith("```"):
        lines = text.splitlines()
        if len(lines) < 3:
            raise ValueError("provider output contains an invalid JSON fence")
        if lines[0].strip().lower() not in {"```", "```json"}:
            raise ValueError("provider output contains an unsupported code fence")
        text = "\n".join(lines[1:-1]).strip()
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("provider output must decode to a JSON object")
    return parsed


def _validation_messages(exc: Exception) -> tuple[str, ...]:
    if isinstance(exc, ValidationError):
        return tuple(
            f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
            for item in cast(Any, exc).errors(include_url=False)
        )
    return (str(exc),)


def _response_hash(output: Any) -> str:
    try:
        return canonical_semantic_hash(output)
    except ValueError:
        return hashlib.sha256(repr(output).encode("utf-8")).hexdigest()


def _raw_response(output: Any) -> Any:
    try:
        return json.loads(
            json.dumps(
                output,
                allow_nan=False,
                ensure_ascii=False,
            )
        )
    except (TypeError, ValueError):
        return repr(output)


class JudgmentGateway:
    """Normalize native and text JSON through the same Pydantic contract."""

    def __init__(
        self,
        *,
        envelope_sink: Callable[[AgentRunEnvelope], None] | None = None,
        successful_envelope_lookup: (
            Callable[[str], AgentRunEnvelope | None] | None
        ) = None,
        invocation_reservation: (
            Callable[[str, str], bool] | None
        ) = None,
        invocation_release: (
            Callable[[str, str], None] | None
        ) = None,
    ) -> None:
        if (invocation_reservation is None) != (invocation_release is None):
            raise ValueError(
                "invocation reservation and release callbacks must be paired"
            )
        self._envelope_sink = envelope_sink
        self._successful_envelope_lookup = successful_envelope_lookup
        self._invocation_reservation = invocation_reservation
        self._invocation_release = invocation_release

    def _emit(self, envelope: AgentRunEnvelope) -> AgentRunEnvelope:
        if self._envelope_sink is not None:
            self._envelope_sink(envelope)
        return envelope

    def execute_structured(
        self,
        *,
        task: JudgmentTask,
        route: ProviderRoute,
        backend: StructuredJudgmentBackend,
        output_model: type[BaseModel],
        run_id: str | None = None,
        force_refresh: bool = False,
        transport_timeout_seconds: float = 120.0,
    ) -> AgentRunEnvelope:
        output_schema = output_model.model_json_schema()
        expected_schema_id = output_model.__name__
        expected_schema_hash = canonical_semantic_hash(output_schema)
        if (
            task.schema_id != expected_schema_id
            or task.schema_hash != expected_schema_hash
        ):
            raise ValueError(
                "output model schema identity does not match judgment task: "
                f"task=({task.schema_id}, {task.schema_hash}), "
                f"model=({expected_schema_id}, {expected_schema_hash})"
            )

        expected_invocation_hash = invocation_hash(task, route)
        if (
            not force_refresh
            and self._successful_envelope_lookup is not None
        ):
            cached = self._successful_envelope_lookup(expected_invocation_hash)
            if cached is not None:
                if (
                    cached.status != AgentRunStatus.succeeded
                    or cached.idempotency_key != expected_invocation_hash
                    or cached.task != task
                    or cached.route != route
                    or cached.validated_payload is None
                    or not str(
                        cached.attempts[-1].trace.actual_model or ""
                    ).strip()
                ):
                    raise ValueError(
                        "cached successful envelope does not match invocation identity"
                    )
                output_model.model_validate(cached.validated_payload)
                return self._emit(cached)

        resolved_run_id = run_id or str(uuid4())
        acquired = False
        if self._invocation_reservation is not None:
            acquired = self._invocation_reservation(
                expected_invocation_hash,
                resolved_run_id,
            )
            if not acquired:
                if (
                    not force_refresh
                    and self._successful_envelope_lookup is not None
                ):
                    cached = self._successful_envelope_lookup(
                        expected_invocation_hash
                    )
                    if cached is not None:
                        if (
                            cached.status != AgentRunStatus.succeeded
                            or cached.idempotency_key
                            != expected_invocation_hash
                            or cached.task != task
                            or cached.route != route
                            or cached.validated_payload is None
                            or not str(
                                cached.attempts[-1].trace.actual_model or ""
                            ).strip()
                        ):
                            raise ValueError(
                                "cached successful envelope does not match "
                                "invocation identity"
                            )
                        output_model.model_validate(cached.validated_payload)
                        return self._emit(cached)
                raise JudgmentInvocationInProgressError(
                    "an identical judgment invocation is already in progress: "
                    f"{expected_invocation_hash}"
                )

        try:
            return self._execute_provider(
                task=task,
                route=route,
                backend=backend,
                output_model=output_model,
                output_schema=output_schema,
                resolved_run_id=resolved_run_id,
                transport_timeout_seconds=transport_timeout_seconds,
            )
        finally:
            if acquired:
                assert self._invocation_release is not None
                self._invocation_release(
                    expected_invocation_hash,
                    resolved_run_id,
                )

    def _execute_provider(
        self,
        *,
        task: JudgmentTask,
        route: ProviderRoute,
        backend: StructuredJudgmentBackend,
        output_model: type[BaseModel],
        output_schema: dict[str, Any],
        resolved_run_id: str,
        transport_timeout_seconds: float,
    ) -> AgentRunEnvelope:
        attempts: list[AgentRunAttempt] = []
        validation_errors: tuple[str, ...] = ()
        for attempt_number in (1, 2):
            started_at = datetime.now(timezone.utc)
            request = JudgmentBackendRequest(
                task=task,
                route=route,
                output_schema=output_schema,
                attempt_number=attempt_number,
                transport_timeout_seconds=transport_timeout_seconds,
                validation_errors=validation_errors,
            )
            try:
                response = backend.generate(request)
                if not str(response.actual_model or "").strip():
                    raise ValueError(
                        "provider response actual_model must not be blank"
                    )
            except Exception as exc:
                completed_at = datetime.now(timezone.utc)
                attempts.append(
                    AgentRunAttempt(
                        attempt_number=attempt_number,
                        status=AgentAttemptStatus.provider_error,
                        trace=AgentTraceMetadata(
                            started_at=started_at,
                            completed_at=completed_at,
                            latency_ms=max(
                                0,
                                int(
                                    (
                                        completed_at - started_at
                                    ).total_seconds()
                                    * 1000
                                ),
                            ),
                        ),
                        validation_errors=_validation_messages(exc),
                        repair_of_attempt=1 if attempt_number == 2 else None,
                    )
                )
                failed_envelope = self._emit(
                    AgentRunEnvelope(
                        run_id=resolved_run_id,
                        task=task,
                        route=route,
                        status=AgentRunStatus.failed,
                        attempts=tuple(attempts),
                    )
                )
                if isinstance(exc, (ConnectionError, TimeoutError)):
                    raise
                return failed_envelope

            completed_at = datetime.now(timezone.utc)
            trace = AgentTraceMetadata(
                provider_request_id=response.provider_request_id,
                actual_model=response.actual_model,
                started_at=started_at,
                completed_at=completed_at,
                latency_ms=max(
                    0,
                    int(
                        (completed_at - started_at).total_seconds() * 1000
                    ),
                ),
                prompt_tokens=response.prompt_tokens,
                completion_tokens=response.completion_tokens,
                total_tokens=response.total_tokens,
                cost_usd=response.cost_usd,
                finish_reason=response.finish_reason,
                response_hash=_response_hash(response.output),
            )
            try:
                parsed = _parse_output(response.output)
                validated = output_model.model_validate(parsed)
            except (ValueError, ValidationError, json.JSONDecodeError) as exc:
                validation_errors = _validation_messages(exc)
                attempts.append(
                    AgentRunAttempt(
                        attempt_number=attempt_number,
                        status=AgentAttemptStatus.validation_failed,
                        trace=trace,
                        raw_response=_raw_response(response.output),
                        validation_errors=validation_errors,
                        repair_of_attempt=1 if attempt_number == 2 else None,
                    )
                )
                if attempt_number == 1:
                    continue
                return self._emit(
                    AgentRunEnvelope(
                        run_id=resolved_run_id,
                        task=task,
                        route=route,
                        status=AgentRunStatus.failed,
                        attempts=tuple(attempts),
                    )
                )

            attempts.append(
                AgentRunAttempt(
                    attempt_number=attempt_number,
                    status=AgentAttemptStatus.succeeded,
                    trace=trace,
                    raw_response=_raw_response(response.output),
                    validated_payload=validated.model_dump(mode="json"),
                    repair_of_attempt=1 if attempt_number == 2 else None,
                )
            )
            return self._emit(
                AgentRunEnvelope(
                    run_id=resolved_run_id,
                    task=task,
                    route=route,
                    status=AgentRunStatus.succeeded,
                    attempts=tuple(attempts),
                )
            )

        raise AssertionError("structured judgment loop exceeded its fixed attempt budget")
