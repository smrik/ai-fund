"""Provider-neutral identity contracts for judgment runs."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
import hashlib
import json
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    computed_field,
    field_validator,
    model_validator,
)


JUDGMENT_RUN_CONTRACT_VERSION = "1.0.0"


class _StrictContractModel(BaseModel):
    model_config = ConfigDict(
        allow_inf_nan=False,
        extra="forbid",
        frozen=True,
    )


class JudgmentMessage(_StrictContractModel):
    """One exact, provider-neutral message emitted by the prompt compiler."""

    role: Literal["system", "developer", "user", "assistant"]
    content: str


class SamplingControls(_StrictContractModel):
    """Normalized sampling controls that affect provider invocation identity."""

    temperature: float | None = None
    top_p: float | None = None
    max_output_tokens: int | None = Field(default=None, ge=1)
    seed: int | None = None
    reasoning_effort: str | None = None
    stop: tuple[str, ...] = ()


class JudgmentTask(_StrictContractModel):
    """Immutable semantic inputs for one focused judgment call."""

    contract_version: str = JUDGMENT_RUN_CONTRACT_VERSION
    task_version: str
    ticker: str
    family: str
    role: str
    frozen_snapshot_hash: str
    prompt_id: str
    prompt_hash: str
    schema_id: str
    schema_hash: str
    compiler_id: str
    compiler_hash: str
    messages: tuple[JudgmentMessage, ...] = Field(min_length=1)
    reviewed_output_hash: str | None = None

    @field_validator(
        "contract_version",
        "task_version",
        "ticker",
        "family",
        "role",
        "frozen_snapshot_hash",
        "prompt_id",
        "prompt_hash",
        "schema_id",
        "schema_hash",
        "compiler_id",
        "compiler_hash",
        "reviewed_output_hash",
    )
    @classmethod
    def _non_empty_identity(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.strip():
            raise ValueError("identity fields must not be empty")
        return value

    @field_validator("ticker")
    @classmethod
    def _normalize_ticker(cls, value: str) -> str:
        return value.strip().upper()

    @computed_field
    @property
    def semantic_task_hash(self) -> str:
        return semantic_task_hash(self)


class ProviderRoute(_StrictContractModel):
    """Credential-free identity of one concrete provider route."""

    contract_version: str = JUDGMENT_RUN_CONTRACT_VERSION
    route_id: str
    provider: str
    adapter_id: str
    adapter_version: str
    requested_model: str
    endpoint_capability: str
    sampling: SamplingControls
    fallback_rank: int = Field(default=0, ge=0)
    fallback_from_route_id: str | None = None

    @field_validator(
        "contract_version",
        "route_id",
        "provider",
        "adapter_id",
        "adapter_version",
        "requested_model",
        "endpoint_capability",
        "fallback_from_route_id",
    )
    @classmethod
    def _non_empty_identity(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.strip():
            raise ValueError("route identity fields must not be empty")
        return value

    @model_validator(mode="after")
    def _fallback_identity_is_complete(self) -> "ProviderRoute":
        if self.fallback_rank == 0 and self.fallback_from_route_id is not None:
            raise ValueError("primary routes must not name a fallback source")
        if self.fallback_rank > 0 and self.fallback_from_route_id is None:
            raise ValueError("fallback routes require fallback_from_route_id")
        return self


class AgentAttemptStatus(str, Enum):
    pending = "pending"
    succeeded = "succeeded"
    validation_failed = "validation_failed"
    provider_error = "provider_error"


class AgentRunStatus(str, Enum):
    pending = "pending"
    succeeded = "succeeded"
    failed = "failed"


class AgentTraceMetadata(_StrictContractModel):
    """Credential-free transport trace for one provider attempt."""

    provider_request_id: str | None = None
    actual_model: str | None = None
    started_at: datetime
    completed_at: datetime | None = None
    latency_ms: int | None = Field(default=None, ge=0)
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    cost_usd: float | None = Field(default=None, ge=0.0)
    finish_reason: str | None = None
    response_hash: str | None = None


class AgentRunAttempt(_StrictContractModel):
    """One provider call, including its validation outcome."""

    attempt_number: int = Field(ge=1)
    status: AgentAttemptStatus
    trace: AgentTraceMetadata
    raw_response: JsonValue | None = None
    validated_payload: dict[str, JsonValue] | None = None
    validation_errors: tuple[str, ...] = ()
    repair_of_attempt: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _status_matches_payload(self) -> "AgentRunAttempt":
        if self.status == AgentAttemptStatus.succeeded:
            if self.validated_payload is None:
                raise ValueError("successful attempts require validated_payload")
            if self.validation_errors:
                raise ValueError("successful attempts must not contain validation_errors")
            canonical_semantic_hash(self.validated_payload)
        elif self.validated_payload is not None:
            raise ValueError("only successful attempts may contain validated_payload")

        if self.status == AgentAttemptStatus.validation_failed and not self.validation_errors:
            raise ValueError("validation_failed attempts require validation_errors")
        return self


class AgentRunEnvelope(_StrictContractModel):
    """Replayable record of one semantic task invoked through one route."""

    contract_version: str = JUDGMENT_RUN_CONTRACT_VERSION
    run_id: str
    task: JudgmentTask
    route: ProviderRoute
    status: AgentRunStatus
    attempts: tuple[AgentRunAttempt, ...] = Field(min_length=1)

    @field_validator("run_id")
    @classmethod
    def _run_id_required(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("run_id is required")
        return value

    @model_validator(mode="after")
    def _status_matches_attempts(self) -> "AgentRunEnvelope":
        expected_numbers = tuple(range(1, len(self.attempts) + 1))
        actual_numbers = tuple(attempt.attempt_number for attempt in self.attempts)
        if actual_numbers != expected_numbers:
            raise ValueError("attempt_number values must be contiguous and ordered from 1")
        for attempt in self.attempts:
            if (
                attempt.repair_of_attempt is not None
                and attempt.repair_of_attempt >= attempt.attempt_number
            ):
                raise ValueError("repair_of_attempt must reference an earlier attempt")

        final_attempt = self.attempts[-1]
        if self.status == AgentRunStatus.succeeded:
            if final_attempt.status != AgentAttemptStatus.succeeded:
                raise ValueError("successful runs require a final successful attempt")
        elif self.status == AgentRunStatus.pending:
            if final_attempt.status != AgentAttemptStatus.pending:
                raise ValueError("pending runs require a final pending attempt")
        elif final_attempt.status in {
            AgentAttemptStatus.pending,
            AgentAttemptStatus.succeeded,
        }:
            raise ValueError("failed runs require a final failed attempt")
        return self

    @computed_field
    @property
    def semantic_task_hash(self) -> str:
        return semantic_task_hash(self.task)

    @computed_field
    @property
    def invocation_hash(self) -> str:
        return invocation_hash(self.task, self.route)

    @computed_field
    @property
    def idempotency_key(self) -> str:
        return invocation_hash(self.task, self.route)

    @computed_field
    @property
    def retry_count(self) -> int:
        return len(self.attempts) - 1

    @computed_field
    @property
    def repair_count(self) -> int:
        return sum(
            attempt.repair_of_attempt is not None
            for attempt in self.attempts
        )

    @computed_field
    @property
    def validated_payload(self) -> dict[str, JsonValue] | None:
        for attempt in reversed(self.attempts):
            if attempt.status == AgentAttemptStatus.succeeded:
                return attempt.validated_payload
        return None


def canonical_semantic_hash(value: Any) -> str:
    """Hash a JSON value with mapping order removed from its identity."""

    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json", exclude_computed_fields=True)
    try:
        canonical = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except ValueError as exc:
        raise ValueError("semantic identity requires finite JSON numbers") from exc
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def semantic_task_hash(task: JudgmentTask) -> str:
    """Return provider-neutral identity for immutable task semantics."""

    return canonical_semantic_hash(task)


def invocation_hash(task: JudgmentTask, route: ProviderRoute) -> str:
    """Return identity for executing a semantic task through one route."""

    return canonical_semantic_hash(
        {
            "semantic_task_hash": semantic_task_hash(task),
            "provider_route": route.model_dump(mode="json"),
        }
    )
