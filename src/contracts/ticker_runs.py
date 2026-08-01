"""Ticker-independent contracts for repeatable valuation runs."""

from __future__ import annotations

from datetime import date
from enum import Enum
import hashlib
import json
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)

from src.contracts.valuation_readiness import (
    ValuationReadinessEvidence,
    ValuationTrustStatus,
)
from src.contracts.model_change_requests import (
    ModelChangeStatus,
    ValuationModelChangeRequest,
)


TICKER_RUN_CONTRACT_VERSION = "1.0.0"


class _StrictContractModel(BaseModel):
    model_config = ConfigDict(
        allow_inf_nan=False,
        extra="forbid",
        frozen=True,
    )


class EligibilityStatus(str, Enum):
    """Whether the current valuation methodology supports an issuer."""

    supported_v1 = "supported_v1"
    unsupported_model = "unsupported_model"


class TerminalStatus(str, Enum):
    """Every requested ticker ends in exactly one of these states."""

    decision_grade = "decision_grade"
    provisional = "provisional"
    blocked = "blocked"


class TickerReasonCode(str, Enum):
    """Closed registry of machine-readable ticker-run reasons."""

    valuation_completed = "valuation.completed"
    valuation_provisional = "valuation.provisional"
    valuation_fallback_used = "valuation.fallback_used"
    eligibility_unsupported_model = "eligibility.unsupported_model"
    model_change_required = "model_change.required"
    trust_gate_incomplete = "trust_gate.incomplete"
    runner_conflicting_request_context = "runner.conflicting_request_context"
    runner_conflicting_prior_records = "runner.conflicting_prior_records"
    runner_unhandled_exception = "runner.unhandled_exception"
    runner_transient_exception = "runner.transient_exception"
    runner_permanent_exception = "runner.permanent_exception"
    runner_invalid_terminal_record = "runner.invalid_terminal_record"
    runner_result_context_mismatch = "runner.result_context_mismatch"
    runner_provider_lane_resolution_failed = (
        "runner.provider_lane_resolution_failed"
    )
    runner_checkpoint_failed = "runner.checkpoint_failed"
    runner_scheduler_deadline_exceeded = (
        "runner.scheduler_deadline_exceeded"
    )


REASON_CODE_REGISTRY = frozenset(code.value for code in TickerReasonCode)


class TickerIdentity(_StrictContractModel):
    """Canonical security identity without provider-specific ticker aliases."""

    ticker: str
    exchange: str | None = None
    share_class: str | None = None
    cik: str | None = None

    @field_validator("ticker")
    @classmethod
    def _normalize_ticker(cls, value: str) -> str:
        ticker = value.strip().upper()
        if not ticker or any(character.isspace() for character in ticker):
            raise ValueError("ticker must be a non-empty symbol without whitespace")
        return ticker

    @field_validator("exchange", "share_class")
    @classmethod
    def _normalize_identity_component(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("identity components must not be empty")
        return normalized

    @field_validator("cik")
    @classmethod
    def _normalize_cik(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cik = value.strip()
        if not cik.isdigit() or len(cik) > 10:
            raise ValueError("cik must contain at most ten digits")
        return cik.zfill(10)

    @computed_field
    @property
    def canonical_key(self) -> str:
        return canonical_hash(
            {
                "ticker": self.ticker,
                "exchange": self.exchange,
                "share_class": self.share_class,
                "cik": self.cik,
            }
        )

    @property
    def sort_key(self) -> tuple[str, str, str, str]:
        """Human-stable ordering that is separate from identity encoding."""

        return (
            self.ticker,
            self.exchange or "",
            self.share_class or "",
            self.cik or "",
        )


class SourceFingerprint(_StrictContractModel):
    """Immutable identity of one source included in an analysis snapshot."""

    source_id: str
    fingerprint: str

    @field_validator("source_id", "fingerprint")
    @classmethod
    def _required(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("source fingerprint fields must not be empty")
        return normalized


class ReplayInputFingerprints(_StrictContractModel):
    """All non-source inputs that determine an exact valuation replay."""

    analysis_snapshot_hash: str
    approved_case_replay_fingerprint: str
    peer_universe_fingerprint: str
    treatment_register_fingerprint: str
    judgment_contract_fingerprint: str
    valuation_engine_fingerprint: str

    @field_validator(
        "analysis_snapshot_hash",
        "approved_case_replay_fingerprint",
        "peer_universe_fingerprint",
        "treatment_register_fingerprint",
        "judgment_contract_fingerprint",
        "valuation_engine_fingerprint",
    )
    @classmethod
    def _required_fingerprint(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("replay input fingerprints must not be empty")
        return normalized


class RetryPolicy(_StrictContractModel):
    """Bounded retry budget for one ticker within one batch."""

    max_attempts: int = Field(default=2, ge=1, le=10)


class TickerRunContext(_StrictContractModel):
    """Frozen inputs and eligibility decision for one ticker valuation."""

    contract_version: str = TICKER_RUN_CONTRACT_VERSION
    identity: TickerIdentity
    analysis_as_of: date
    eligibility: EligibilityStatus
    eligibility_reason_code: TickerReasonCode | None = None
    valuation_model: str
    replay_inputs: ReplayInputFingerprints
    readiness: ValuationReadinessEvidence
    model_change_request: ValuationModelChangeRequest | None = None
    source_fingerprints: tuple[SourceFingerprint, ...] = Field(default=())

    @field_validator("contract_version", "valuation_model")
    @classmethod
    def _required(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("context identity fields must not be empty")
        return normalized

    @field_validator("source_fingerprints")
    @classmethod
    def _canonicalize_sources(
        cls,
        value: tuple[SourceFingerprint, ...],
    ) -> tuple[SourceFingerprint, ...]:
        fingerprints_by_source: dict[str, str] = {}
        for source in value:
            previous = fingerprints_by_source.setdefault(
                source.source_id,
                source.fingerprint,
            )
            if previous != source.fingerprint:
                raise ValueError(
                    "source_id must resolve to exactly one fingerprint"
                )
        unique = {
            (source.source_id, source.fingerprint): source
            for source in value
        }
        return tuple(unique[key] for key in sorted(unique))

    @model_validator(mode="after")
    def _eligibility_is_complete(self) -> "TickerRunContext":
        if (
            self.eligibility == EligibilityStatus.unsupported_model
            and self.eligibility_reason_code is None
        ):
            raise ValueError(
                "unsupported_model contexts require eligibility_reason_code"
            )
        if self.eligibility == EligibilityStatus.unsupported_model:
            if (
                self.eligibility_reason_code
                != TickerReasonCode.eligibility_unsupported_model
            ):
                raise ValueError(
                    "unsupported_model contexts require "
                    "eligibility.unsupported_model"
                )
            if self.model_change_request is None:
                raise ValueError(
                    "unsupported_model contexts require model_change_request"
                )
            if (
                self.model_change_request.ticker != self.identity.ticker
                or self.model_change_request.analysis_snapshot_hash
                != self.replay_inputs.analysis_snapshot_hash
                or self.model_change_request.current_model
                != self.valuation_model
            ):
                raise ValueError(
                    "model_change_request must match ticker, snapshot, and model"
                )
            if self.model_change_request.status != ModelChangeStatus.pending:
                raise ValueError(
                    "unsupported_model requires a pending model_change_request"
                )
        if (
            self.eligibility == EligibilityStatus.supported_v1
            and not self.source_fingerprints
        ):
            raise ValueError(
                "supported_v1 contexts require source_fingerprints"
            )
        return self

    @computed_field
    @property
    def context_fingerprint(self) -> str:
        return canonical_hash(self)


class TickerTerminalRecord(_StrictContractModel):
    """One final, resume-safe outcome for a requested ticker."""

    context: TickerRunContext
    status: TerminalStatus
    reason_code: TickerReasonCode
    retryable: bool
    result_fingerprint: str | None = None
    reason_detail: str | None = None
    model_change_request: ValuationModelChangeRequest | None = None
    attempt_count: int = Field(default=1, ge=0)

    @field_validator("result_fingerprint", "reason_detail")
    @classmethod
    def _normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def _eligibility_matches_terminal_status(self) -> "TickerTerminalRecord":
        if (
            self.status
            in {TerminalStatus.decision_grade, TerminalStatus.provisional}
            and self.result_fingerprint is None
        ):
            raise ValueError(
                "valuation outcomes require result_fingerprint"
            )
        if self.status == TerminalStatus.decision_grade and self.retryable:
            raise ValueError("decision_grade must be non-retryable")
        if (
            self.status == TerminalStatus.decision_grade
            and self.reason_code != TickerReasonCode.valuation_completed
        ):
            raise ValueError(
                "decision_grade requires valuation.completed"
            )
        if (
            self.status == TerminalStatus.decision_grade
            and self.context.readiness.trust_status
            != ValuationTrustStatus.decision_grade
        ):
            raise ValueError(
                "decision_grade requires decision-grade readiness"
            )
        if (
            self.context.readiness.trust_status
            == ValuationTrustStatus.blocked
            and self.status != TerminalStatus.blocked
        ):
            raise ValueError(
                "blocked readiness requires blocked terminal status"
            )
        if (
            self.context.eligibility == EligibilityStatus.unsupported_model
            and self.status != TerminalStatus.blocked
        ):
            raise ValueError(
                "unsupported_model contexts must terminate as blocked"
            )
        if self.context.eligibility == EligibilityStatus.unsupported_model:
            if self.model_change_request is None:
                raise ValueError(
                    "unsupported_model blockers require model_change_request"
                )
            if self.model_change_request != self.context.model_change_request:
                raise ValueError(
                    "terminal model_change_request must match run context"
                )
        return self

    @computed_field
    @property
    def reason_codes(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                (
                    self.reason_code.value,
                    *self.context.readiness.reason_codes,
                )
            )
        )

    @computed_field
    @property
    def checkpoint_fingerprint(self) -> str:
        return canonical_hash(
            {
                "context_fingerprint": self.context.context_fingerprint,
                "readiness_fingerprint": (
                    self.context.readiness.readiness_fingerprint
                ),
                "status": self.status.value,
                "reason_code": self.reason_code.value,
                "retryable": self.retryable,
                "result_fingerprint": self.result_fingerprint,
                "model_change_request": (
                    self.model_change_request.model_dump(mode="json")
                    if self.model_change_request is not None
                    else None
                ),
            }
        )


def canonical_hash(value: Any) -> str:
    """Return a stable hash for a JSON-serializable contract value."""

    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json", exclude_computed_fields=True)
    payload = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
