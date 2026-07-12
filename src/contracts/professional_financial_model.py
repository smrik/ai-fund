"""Versioned deterministic contracts for the professional financial model v2.

The module intentionally contains no data retrieval, finance calculations, or
judgment logic.  It defines frozen, replayable boundaries between those stages.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from enum import Enum
import hashlib
import json
import re
from typing import Iterable, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


PROFESSIONAL_MODEL_CONTRACT_VERSION = "1.0.0"
ContractVersion = Literal["1.0.0"]

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
A1_RE = re.compile(r"^\$?([A-Z]{1,3})\$?([1-9][0-9]*)$")
DEFINED_NAME_RE = re.compile(r"^[A-Za-z_\\][A-Za-z0-9_.\\]*$")

PROFESSIONAL_WORKBOOK_SHEETS: tuple[str, ...] = (
    "Cover",
    "Summary",
    "Sources",
    "Assumptions",
    "Historical_Data",
    "Segment_Build",
    "Income_Statement",
    "Balance_Sheet",
    "Cash_Flow",
    "Working_Capital",
    "PP&E_Intangibles",
    "Debt_Cash_Interest",
    "Capital_Allocation",
    "Taxes",
    "Shares_EPS",
    "Consensus_Bridge",
    "WACC",
    "DCF",
    "Comps",
    "SOTP",
    "Valuation",
    "Scenarios",
    "Sensitivities",
    "Accounting_QoE",
    "PM_Review_Queue",
    "Checks",
)

REQUIRED_SUPPLEMENTAL_FACTS = frozenset(
    {
        "current_price",
        "market_cap",
        "beta",
        "risk_free_rate",
        "equity_risk_premium",
        "total_debt",
        "cost_of_debt",
        "fx_rate",
    }
)

JsonScalar = str | int | float | bool | None


def _require_text(value: str, field_name: str) -> str:
    cleaned = str(value).strip()
    if not cleaned:
        raise ValueError(f"{field_name} is required")
    return cleaned


def _validate_sha256(value: str, field_name: str) -> str:
    cleaned = str(value).strip().lower()
    if not SHA256_RE.fullmatch(cleaned):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 hex digest")
    return cleaned


def _column_number(letters: str) -> int:
    number = 0
    for char in letters:
        number = number * 26 + (ord(char) - ord("A") + 1)
    return number


def _normalize_a1(value: str) -> str:
    cleaned = str(value).strip().upper()
    match = A1_RE.fullmatch(cleaned)
    if not match:
        raise ValueError("cell locator must be an A1 reference")
    return f"{match.group(1)}{match.group(2)}"


def _validate_unit_currency(unit_kind: "UnitKind", currency: str | None) -> str | None:
    cleaned = str(currency).upper().strip() if currency is not None else None
    if cleaned is not None and not re.fullmatch(r"[A-Z]{3}", cleaned):
        raise ValueError("currency must be a three-letter ISO code")
    if unit_kind is UnitKind.CURRENCY and cleaned is None:
        raise ValueError("currency is required for currency-valued data")
    if unit_kind is not UnitKind.CURRENCY and cleaned is not None:
        raise ValueError("currency is inconsistent with non-currency unit_kind")
    return cleaned


class CanonicalContract(BaseModel):
    """Strict frozen model with deterministic JSON and SHA-256 helpers."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    def canonical_json(self, *, exclude_fields: set[str] | None = None) -> str:
        payload = self.model_dump(mode="json", exclude=exclude_fields or set())
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )

    def canonical_bytes(self, *, exclude_fields: set[str] | None = None) -> bytes:
        return self.canonical_json(exclude_fields=exclude_fields).encode("utf-8")

    def canonical_hash(self, *, exclude_fields: set[str] | None = None) -> str:
        return hashlib.sha256(self.canonical_bytes(exclude_fields=exclude_fields)).hexdigest()

    def _bind_hash(self, field_name: str) -> None:
        expected = self.canonical_hash(exclude_fields={field_name})
        supplied = getattr(self, field_name)
        if supplied is not None and supplied != expected:
            raise ValueError(f"{field_name} does not match canonical content")
        object.__setattr__(self, field_name, expected)


class AvailabilityStatus(str, Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    BLOCKING = "blocking"
    PM_REQUIRED = "pm_required"


class WorkflowState(str, Enum):
    """Canonical fail-closed release state for a model or model module."""

    UNVERIFIED = "UNVERIFIED"
    BLOCKED = "BLOCKED"
    NEEDS_PM_REVIEW = "NEEDS_PM_REVIEW"
    PARTIAL = "PARTIAL"
    FULL = "FULL"


class AvailabilityState(CanonicalContract):
    status: AvailabilityStatus
    reason_code: str | None = None
    message: str | None = None
    queue_item_id: str | None = None

    @model_validator(mode="after")
    def _validate_reason(self) -> "AvailabilityState":
        if self.status is AvailabilityStatus.AVAILABLE:
            if self.reason_code is not None or self.message is not None or self.queue_item_id is not None:
                raise ValueError("available state cannot carry unavailable/blocking reason fields")
        else:
            if not self.reason_code or not self.message:
                raise ValueError("non-available state requires reason_code and message")
        return self


class UnitKind(str, Enum):
    CURRENCY = "currency"
    PERCENT = "percent"
    MULTIPLE = "multiple"
    COUNT = "count"
    DAYS = "days"
    TEXT = "text"
    OTHER = "other"


class PeriodType(str, Enum):
    FISCAL_YEAR = "fiscal_year"
    FISCAL_QUARTER = "fiscal_quarter"
    LTM = "ltm"
    NTM = "ntm"
    CALENDAR_YEAR = "calendar_year"
    DATE = "date"
    NONE = "none"


class EstimateStatus(str, Enum):
    ACTUAL = "actual"
    ESTIMATE = "estimate"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class FactFormulaStatus(str, Enum):
    NOT_FORMULA = "not_formula"
    CALCULATED = "calculated"
    STALE = "stale"
    ERROR = "error"
    UNAVAILABLE = "unavailable"


class SourceFact(CanonicalContract):
    contract_version: ContractVersion = PROFESSIONAL_MODEL_CONTRACT_VERSION
    fact_id: str
    ticker: str
    ciq_run_id: int = Field(gt=0)
    source_file: str
    source_path: str
    source_hash: str
    workbook_sheet: str
    section: str | None = None
    row_index: int = Field(gt=0)
    column_index: int = Field(gt=0)
    cell_locator: str
    row_label: str
    canonical_key: str | None = None
    period_end: date | None = None
    period_type: PeriodType
    estimate_status: EstimateStatus
    formula_text: str | None = None
    cached_value: JsonScalar = None
    displayed_value: str | None = None
    formula_status: FactFormulaStatus
    formula_error: str | None = None
    calculation_type: str | None = None
    unit: str
    unit_kind: UnitKind
    scale: float = Field(gt=0)
    currency: str | None = None
    dimensions: dict[str, str] = Field(default_factory=dict)
    quality_state: AvailabilityState

    @staticmethod
    def stable_fact_id(
        *,
        ticker: str,
        ciq_run_id: int,
        source_hash: str,
        workbook_sheet: str,
        row_index: int,
        column_index: int,
    ) -> str:
        identity = {
            "ticker": str(ticker).upper().strip(),
            "ciq_run_id": int(ciq_run_id),
            "source_hash": _validate_sha256(source_hash, "source_hash"),
            "workbook_sheet": str(workbook_sheet).strip(),
            "row_index": int(row_index),
            "column_index": int(column_index),
        }
        encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return "fact:" + hashlib.sha256(encoded).hexdigest()

    @field_validator("ticker")
    @classmethod
    def _ticker(cls, value: str) -> str:
        return _require_text(value, "ticker").upper()

    @field_validator("source_file", "source_path", "workbook_sheet", "row_label", "unit")
    @classmethod
    def _required_text(cls, value: str, info) -> str:
        return _require_text(value, info.field_name)

    @field_validator("source_hash")
    @classmethod
    def _source_hash(cls, value: str) -> str:
        return _validate_sha256(value, "source_hash")

    @field_validator("cell_locator")
    @classmethod
    def _cell(cls, value: str) -> str:
        return _normalize_a1(value)

    @model_validator(mode="after")
    def _validate_source_fact(self) -> "SourceFact":
        expected_locator = _normalize_a1(self.cell_locator)
        match = A1_RE.fullmatch(expected_locator)
        assert match is not None
        if int(match.group(2)) != self.row_index or _column_number(match.group(1)) != self.column_index:
            raise ValueError("cell_locator does not match row_index/column_index")

        expected_id = self.stable_fact_id(
            ticker=self.ticker,
            ciq_run_id=self.ciq_run_id,
            source_hash=self.source_hash,
            workbook_sheet=self.workbook_sheet,
            row_index=self.row_index,
            column_index=self.column_index,
        )
        if self.fact_id != expected_id:
            raise ValueError("fact_id does not match stable source identity")

        if self.period_type is PeriodType.NONE and self.period_end is not None:
            raise ValueError("period_end must be absent when period_type is none")
        if self.period_type is not PeriodType.NONE and self.period_end is None:
            raise ValueError("period_end is required for dated period types")

        if self.formula_status is FactFormulaStatus.NOT_FORMULA:
            if self.formula_text is not None or self.formula_error is not None:
                raise ValueError("not_formula facts cannot carry formula text or errors")
        elif not self.formula_text:
            raise ValueError("formula_text is required for formula facts")
        if self.formula_status is FactFormulaStatus.ERROR and not self.formula_error:
            raise ValueError("formula_error is required when formula_status is error")
        if self.formula_status is not FactFormulaStatus.ERROR and self.formula_error is not None:
            raise ValueError("formula_error is only valid for formula_status error")

        object.__setattr__(self, "currency", _validate_unit_currency(self.unit_kind, self.currency))
        object.__setattr__(self, "dimensions", dict(sorted(self.dimensions.items())))
        return self


class SourcePresentationRecord(CanonicalContract):
    """Presentation-safe separation of source, normalization, and derivation."""

    contract_version: ContractVersion = PROFESSIONAL_MODEL_CONTRACT_VERSION
    source_id: str
    canonical_key: str
    raw_value: JsonScalar = None
    normalized_value: JsonScalar = None
    derived_value: JsonScalar = None
    transform: str
    unit: str
    unit_kind: UnitKind
    scale: float = Field(gt=0)
    currency: str | None = None
    period_type: PeriodType
    period_start: date | None = None
    period_end: date | None = None
    as_of_date: date | None = None
    formula_status: FactFormulaStatus
    error_code: str | None = None
    error_message: str | None = None
    source_refs: tuple[str, ...] = ()
    downstream_dependencies: tuple[str, ...] = ()
    state: AvailabilityState

    @field_validator("source_id", "canonical_key", "transform", "unit")
    @classmethod
    def _required_text(cls, value: str, info) -> str:
        return _require_text(value, info.field_name)

    @model_validator(mode="after")
    def _validate_presentation(self) -> "SourcePresentationRecord":
        object.__setattr__(
            self,
            "currency",
            _validate_unit_currency(self.unit_kind, self.currency),
        )
        if self.period_type is PeriodType.NONE:
            if any(
                item is not None
                for item in (self.period_start, self.period_end, self.as_of_date)
            ):
                raise ValueError("non-period source presentation cannot carry dates")
        elif self.period_type is PeriodType.DATE:
            if self.as_of_date is None or self.period_start is not None or self.period_end is not None:
                raise ValueError("date source presentation requires only as_of_date")
        else:
            if self.period_start is None or self.period_end is None:
                raise ValueError("period source presentation requires exact start and end dates")
            if self.period_start > self.period_end or self.as_of_date is not None:
                raise ValueError("period source presentation dates are inconsistent")

        if (self.error_code is None) != (self.error_message is None):
            raise ValueError("source error code and message must be supplied together")
        if self.formula_status is FactFormulaStatus.ERROR and self.error_code is None:
            raise ValueError("formula error presentation requires error details")
        if self.state.status is AvailabilityStatus.AVAILABLE and all(
            value is None
            for value in (self.raw_value, self.normalized_value, self.derived_value)
        ):
            raise ValueError("available source presentation requires a presented value")

        source_refs = tuple(sorted({_require_text(item, "source_ref") for item in self.source_refs}))
        downstream = tuple(
            sorted(
                {
                    _require_text(item, "downstream_dependency")
                    for item in self.downstream_dependencies
                }
            )
        )
        object.__setattr__(self, "source_refs", source_refs)
        object.__setattr__(self, "downstream_dependencies", downstream)
        return self


class WorkbookSourceIdentity(CanonicalContract):
    contract_version: ContractVersion = PROFESSIONAL_MODEL_CONTRACT_VERSION
    ticker: str
    source_file: str
    source_path: str
    source_hash: str
    file_modified_at: datetime
    workbook_as_of_date: date
    fiscal_period_end: date
    currency: str
    unit_convention: str
    state: AvailabilityState

    @field_validator("ticker", "currency")
    @classmethod
    def _uppercase(cls, value: str, info) -> str:
        cleaned = _require_text(value, info.field_name).upper()
        if info.field_name == "currency" and not re.fullmatch(r"[A-Z]{3}", cleaned):
            raise ValueError("currency must be a three-letter ISO code")
        return cleaned

    @field_validator("source_file", "source_path", "unit_convention")
    @classmethod
    def _required_text(cls, value: str, info) -> str:
        return _require_text(value, info.field_name)

    @field_validator("source_hash")
    @classmethod
    def _hash(cls, value: str) -> str:
        return _validate_sha256(value, "source_hash")


class SourceManifest(CanonicalContract):
    manifest_version: ContractVersion = PROFESSIONAL_MODEL_CONTRACT_VERSION
    ticker: str
    fiscal_convention: str
    workbook: WorkbookSourceIdentity
    selected_ciq_run_id: int = Field(gt=0)
    parser_version: str
    fact_count: int = Field(ge=0)
    fact_status_counts: dict[str, int]
    supplemental_snapshot_hash: str
    manifest_hash: str | None = None

    @field_validator("ticker")
    @classmethod
    def _ticker(cls, value: str) -> str:
        return _require_text(value, "ticker").upper()

    @field_validator("fiscal_convention", "parser_version")
    @classmethod
    def _required_text(cls, value: str, info) -> str:
        return _require_text(value, info.field_name)

    @field_validator("supplemental_snapshot_hash")
    @classmethod
    def _supplemental_hash(cls, value: str) -> str:
        return _validate_sha256(value, "supplemental_snapshot_hash")

    @model_validator(mode="after")
    def _validate_and_hash(self) -> "SourceManifest":
        if self.workbook.ticker != self.ticker:
            raise ValueError("manifest ticker must match workbook ticker")
        if sum(self.fact_status_counts.values()) != self.fact_count:
            raise ValueError("fact_status_counts must sum to fact_count")
        if any(count < 0 for count in self.fact_status_counts.values()):
            raise ValueError("fact status counts cannot be negative")
        object.__setattr__(self, "fact_status_counts", dict(sorted(self.fact_status_counts.items())))
        self._bind_hash("manifest_hash")
        return self


class LineItemSpec(CanonicalContract):
    contract_version: ContractVersion = PROFESSIONAL_MODEL_CONTRACT_VERSION
    canonical_key: str
    display_label: str
    statement_or_schedule: str
    sign_convention: str
    source_mappings: tuple[str, ...]
    required: bool
    material: bool
    historical_aggregation_rule: str
    forecast_method: str
    dependencies: tuple[str, ...] = ()
    scenario_drivers: tuple[str, ...] = ()
    presentation_order: int = Field(ge=0)
    missing_data_policy: AvailabilityStatus

    @field_validator(
        "canonical_key",
        "display_label",
        "statement_or_schedule",
        "sign_convention",
        "historical_aggregation_rule",
        "forecast_method",
    )
    @classmethod
    def _required_text(cls, value: str, info) -> str:
        return _require_text(value, info.field_name)

    @model_validator(mode="after")
    def _sort_sets(self) -> "LineItemSpec":
        if len(set(self.source_mappings)) != len(self.source_mappings):
            raise ValueError("source_mappings contains duplicates")
        object.__setattr__(self, "source_mappings", tuple(sorted(self.source_mappings)))
        object.__setattr__(self, "dependencies", tuple(sorted(set(self.dependencies))))
        object.__setattr__(self, "scenario_drivers", tuple(sorted(set(self.scenario_drivers))))
        return self


class SupplementalInputFact(CanonicalContract):
    contract_version: ContractVersion = PROFESSIONAL_MODEL_CONTRACT_VERSION
    field_key: str
    value: JsonScalar = None
    state: AvailabilityState
    unit: str
    unit_kind: UnitKind
    currency: str | None = None
    source_name: str | None = None
    source_locator: str | None = None
    as_of_date: date | None = None
    method: str | None = None
    duration: str | None = None
    quality_flags: tuple[str, ...] = ()

    @field_validator("field_key", "unit")
    @classmethod
    def _required_text(cls, value: str, info) -> str:
        return _require_text(value, info.field_name)

    @model_validator(mode="after")
    def _validate_fact(self) -> "SupplementalInputFact":
        object.__setattr__(self, "currency", _validate_unit_currency(self.unit_kind, self.currency))
        if self.state.status is AvailabilityStatus.AVAILABLE:
            if self.value is None:
                raise ValueError("available supplemental fact requires a value")
            if not self.source_name or not self.source_locator or self.as_of_date is None:
                raise ValueError("available supplemental fact requires source name, locator, and date")
            if self.field_key == "beta" and not self.method:
                raise ValueError("available beta fact requires a method")
            if self.field_key == "risk_free_rate" and not self.duration:
                raise ValueError("available risk_free_rate fact requires a duration")
        elif self.value is not None:
            raise ValueError("non-available supplemental facts cannot carry a value")
        object.__setattr__(self, "quality_flags", tuple(sorted(set(self.quality_flags))))
        return self


class SupplementalInputSnapshot(CanonicalContract):
    schema_version: ContractVersion = PROFESSIONAL_MODEL_CONTRACT_VERSION
    ticker: str
    valuation_date: date
    currency: str
    peer_universe_version: str
    peer_tickers: tuple[str, ...] = ()
    facts: tuple[SupplementalInputFact, ...]
    snapshot_hash: str | None = None

    @field_validator("ticker", "currency")
    @classmethod
    def _uppercase(cls, value: str, info) -> str:
        cleaned = _require_text(value, info.field_name).upper()
        if info.field_name == "currency" and not re.fullmatch(r"[A-Z]{3}", cleaned):
            raise ValueError("currency must be a three-letter ISO code")
        return cleaned

    @field_validator("peer_universe_version")
    @classmethod
    def _peer_version(cls, value: str) -> str:
        return _require_text(value, "peer_universe_version")

    @model_validator(mode="after")
    def _validate_and_hash(self) -> "SupplementalInputSnapshot":
        keys = [fact.field_key for fact in self.facts]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate supplemental fact keys")
        missing = sorted(REQUIRED_SUPPLEMENTAL_FACTS - set(keys))
        if missing:
            raise ValueError(f"required supplemental facts are missing: {missing}")
        for fact in self.facts:
            if fact.currency is not None and fact.currency != self.currency:
                raise ValueError("supplemental fact currency must match snapshot currency")
        normalized_peers = tuple(ticker.upper().strip() for ticker in self.peer_tickers)
        if len(set(normalized_peers)) != len(normalized_peers):
            raise ValueError("duplicate peer tickers")
        if any(not ticker for ticker in normalized_peers):
            raise ValueError("peer tickers cannot be blank")
        object.__setattr__(self, "facts", tuple(sorted(self.facts, key=lambda fact: fact.field_key)))
        object.__setattr__(self, "peer_tickers", tuple(sorted(normalized_peers)))
        self._bind_hash("snapshot_hash")
        return self


class InputValue(CanonicalContract):
    contract_version: ContractVersion = PROFESSIONAL_MODEL_CONTRACT_VERSION
    key: str
    value: JsonScalar = None
    state: AvailabilityState
    unit: str
    unit_kind: UnitKind
    currency: str | None = None
    source_ref: str | None = None
    approval_ref: str | None = None

    @field_validator("key", "unit")
    @classmethod
    def _required_text(cls, value: str, info) -> str:
        return _require_text(value, info.field_name)

    @model_validator(mode="after")
    def _validate_value(self) -> "InputValue":
        object.__setattr__(self, "currency", _validate_unit_currency(self.unit_kind, self.currency))
        if self.state.status is AvailabilityStatus.AVAILABLE:
            if self.value is None or not self.source_ref:
                raise ValueError("available input value requires value and source_ref")
        elif self.value is not None:
            raise ValueError("non-available input value cannot carry a value")
        return self


class DriverGroup(str, Enum):
    MECHANICAL = "mechanical"
    FINANCE_SEMANTIC = "finance_semantic"


class DriverApprovalState(str, Enum):
    UNAPPROVED = "UNAPPROVED"
    APPROVED = "APPROVED"
    STALE = "STALE"
    REJECTED = "REJECTED"


class DriverApprovalRecord(CanonicalContract):
    """API-facing approval snapshot bound to the exact driver fingerprint."""

    contract_version: ContractVersion = PROFESSIONAL_MODEL_CONTRACT_VERSION
    driver_key: str
    scenario_key: str | None = None
    driver_group: DriverGroup
    current_driver_fingerprint: str
    approved_driver_fingerprint: str | None = None
    approval_state: DriverApprovalState = DriverApprovalState.UNAPPROVED
    approval_ref: str | None = None
    approved_by: str | None = None
    approved_at: datetime | None = None
    record_hash: str | None = None

    @field_validator("driver_key")
    @classmethod
    def _driver_key(cls, value: str) -> str:
        return _require_text(value, "driver_key")

    @field_validator("scenario_key")
    @classmethod
    def _scenario_key(cls, value: str | None) -> str | None:
        return _require_text(value, "scenario_key") if value is not None else None

    @field_validator("approval_ref", "approved_by")
    @classmethod
    def _optional_approval_text(cls, value: str | None, info) -> str | None:
        return _require_text(value, info.field_name) if value is not None else None

    @field_validator("current_driver_fingerprint", "approved_driver_fingerprint")
    @classmethod
    def _fingerprint(cls, value: str | None, info) -> str | None:
        if value is None:
            return None
        return _validate_sha256(value, info.field_name)

    @model_validator(mode="after")
    def _validate_and_hash(self) -> "DriverApprovalRecord":
        if (
            self.approval_state is DriverApprovalState.APPROVED
            and self.approved_driver_fingerprint is not None
            and self.approved_driver_fingerprint != self.current_driver_fingerprint
        ):
            object.__setattr__(self, "approval_state", DriverApprovalState.STALE)

        approval_metadata = (self.approval_ref, self.approved_by, self.approved_at)
        if self.approval_state in {
            DriverApprovalState.APPROVED,
            DriverApprovalState.STALE,
        }:
            if self.approved_driver_fingerprint is None or any(
                item is None for item in approval_metadata
            ):
                raise ValueError("approved/stale driver record requires fingerprint and approval metadata")
            if self.approval_state is DriverApprovalState.APPROVED and (
                self.approved_driver_fingerprint != self.current_driver_fingerprint
            ):
                raise ValueError("approved driver fingerprint must match current driver fingerprint")
        elif self.approval_state is DriverApprovalState.UNAPPROVED:
            if self.approved_driver_fingerprint is not None or any(
                item is not None for item in approval_metadata
            ):
                raise ValueError("unapproved driver record cannot carry approval metadata")
        elif any(item is None for item in approval_metadata):
            raise ValueError("rejected driver record requires decision metadata")

        if self.approved_at is not None and (
            self.approved_at.tzinfo is None or self.approved_at.utcoffset() is None
        ):
            raise ValueError("approved_at must be timezone-aware")
        self._bind_hash("record_hash")
        return self

    def with_current_fingerprint(self, fingerprint: str) -> "DriverApprovalRecord":
        """Rebind for a changed input without ever reviving or creating approval."""

        payload = self.model_dump(mode="json")
        payload["current_driver_fingerprint"] = _validate_sha256(
            fingerprint,
            "current_driver_fingerprint",
        )
        payload["record_hash"] = None
        return type(self).model_validate(payload)


class NormalizedActual(CanonicalContract):
    contract_version: ContractVersion = PROFESSIONAL_MODEL_CONTRACT_VERSION
    canonical_key: str
    period_key: str
    period_end: date
    value: JsonScalar = None
    unit: str
    unit_kind: UnitKind
    currency: str | None = None
    source_fact_ids: tuple[str, ...]
    state: AvailabilityState

    @field_validator("canonical_key", "period_key", "unit")
    @classmethod
    def _required_text(cls, value: str, info) -> str:
        return _require_text(value, info.field_name)

    @model_validator(mode="after")
    def _validate_actual(self) -> "NormalizedActual":
        object.__setattr__(self, "currency", _validate_unit_currency(self.unit_kind, self.currency))
        if len(set(self.source_fact_ids)) != len(self.source_fact_ids):
            raise ValueError("duplicate source_fact_ids in normalized actual")
        if self.state.status is AvailabilityStatus.AVAILABLE:
            if self.value is None or not self.source_fact_ids:
                raise ValueError("available normalized actual requires value and source facts")
        elif self.value is not None:
            raise ValueError("non-available normalized actual cannot carry a value")
        object.__setattr__(self, "source_fact_ids", tuple(sorted(self.source_fact_ids)))
        return self


class ModelInputSnapshot(CanonicalContract):
    schema_version: ContractVersion = PROFESSIONAL_MODEL_CONTRACT_VERSION
    ticker: str
    fiscal_calendar: str
    currency: str
    source_manifest: SourceManifest
    selected_ciq_run_id: int = Field(gt=0)
    source_facts: tuple[SourceFact, ...]
    line_item_registry_version: str
    normalized_actuals: tuple[NormalizedActual, ...]
    approved_assumptions: tuple[InputValue, ...]
    supplemental_input_snapshot: SupplementalInputSnapshot
    supplemental_input_hash: str
    content_hash: str | None = None

    @field_validator("ticker", "currency")
    @classmethod
    def _uppercase(cls, value: str, info) -> str:
        cleaned = _require_text(value, info.field_name).upper()
        if info.field_name == "currency" and not re.fullmatch(r"[A-Z]{3}", cleaned):
            raise ValueError("currency must be a three-letter ISO code")
        return cleaned

    @field_validator("fiscal_calendar", "line_item_registry_version")
    @classmethod
    def _required_text(cls, value: str, info) -> str:
        return _require_text(value, info.field_name)

    @field_validator("supplemental_input_hash")
    @classmethod
    def _supplemental_hash(cls, value: str) -> str:
        return _validate_sha256(value, "supplemental_input_hash")

    @model_validator(mode="after")
    def _validate_and_hash(self) -> "ModelInputSnapshot":
        if self.source_manifest.ticker != self.ticker:
            raise ValueError("source manifest ticker must match model ticker")
        if self.source_manifest.selected_ciq_run_id != self.selected_ciq_run_id:
            raise ValueError("source manifest must use the selected CIQ run")
        if self.supplemental_input_snapshot.ticker != self.ticker:
            raise ValueError("supplemental snapshot ticker must match model ticker")
        if self.supplemental_input_snapshot.currency != self.currency:
            raise ValueError("supplemental snapshot currency must match model currency")
        if self.supplemental_input_snapshot.snapshot_hash != self.supplemental_input_hash:
            raise ValueError("supplemental_input_hash does not match snapshot")
        if self.source_manifest.supplemental_snapshot_hash != self.supplemental_input_hash:
            raise ValueError("source manifest supplemental hash does not match snapshot")

        fact_ids = [fact.fact_id for fact in self.source_facts]
        if len(set(fact_ids)) != len(fact_ids):
            raise ValueError("duplicate source fact IDs")
        if len(self.source_facts) != self.source_manifest.fact_count:
            raise ValueError("source fact count does not match source manifest")
        observed_status_counts: dict[str, int] = {}
        for fact in self.source_facts:
            status = fact.quality_state.status.value
            observed_status_counts[status] = observed_status_counts.get(status, 0) + 1
        if observed_status_counts != self.source_manifest.fact_status_counts:
            raise ValueError("source fact quality counts do not match source manifest")
        for fact in self.source_facts:
            if fact.ticker != self.ticker or fact.ciq_run_id != self.selected_ciq_run_id:
                raise ValueError("all source facts must belong to the selected CIQ run and ticker")
            if fact.source_hash != self.source_manifest.workbook.source_hash:
                raise ValueError("source fact hash must match source manifest workbook hash")

        actual_keys: set[tuple[str, str]] = set()
        known_fact_ids = set(fact_ids)
        for actual in self.normalized_actuals:
            identity = (actual.canonical_key, actual.period_key)
            if identity in actual_keys:
                raise ValueError("duplicate normalized actual identity")
            actual_keys.add(identity)
            if not set(actual.source_fact_ids).issubset(known_fact_ids):
                raise ValueError("normalized actual references unknown source fact")
            if actual.currency is not None and actual.currency != self.currency:
                raise ValueError("normalized actual currency must match model currency")

        assumption_keys: set[str] = set()
        for assumption in self.approved_assumptions:
            if assumption.key in assumption_keys:
                raise ValueError("duplicate approved assumption keys")
            assumption_keys.add(assumption.key)
            if assumption.state.status is not AvailabilityStatus.AVAILABLE or not assumption.approval_ref:
                raise ValueError("approved assumptions must be available and carry approval_ref")
            if assumption.currency is not None and assumption.currency != self.currency:
                raise ValueError("approved assumption currency must match model currency")

        object.__setattr__(self, "source_facts", tuple(sorted(self.source_facts, key=lambda fact: fact.fact_id)))
        object.__setattr__(
            self,
            "normalized_actuals",
            tuple(sorted(self.normalized_actuals, key=lambda item: (item.canonical_key, item.period_key))),
        )
        object.__setattr__(
            self,
            "approved_assumptions",
            tuple(sorted(self.approved_assumptions, key=lambda item: item.key)),
        )
        self._bind_hash("content_hash")
        return self


class DriverYearValue(CanonicalContract):
    contract_version: ContractVersion = PROFESSIONAL_MODEL_CONTRACT_VERSION
    year: int = Field(gt=0)
    value: JsonScalar = None
    state: AvailabilityState
    source_ref: str | None = None
    approval_ref: str | None = None

    @model_validator(mode="after")
    def _validate_value(self) -> "DriverYearValue":
        if self.state.status is AvailabilityStatus.AVAILABLE:
            if self.value is None or not self.source_ref:
                raise ValueError("available driver year requires value and source_ref")
        elif self.value is not None:
            raise ValueError("non-available driver year cannot carry a value")
        return self


class ScenarioDriverPath(CanonicalContract):
    contract_version: ContractVersion = PROFESSIONAL_MODEL_CONTRACT_VERSION
    driver_key: str
    values: tuple[DriverYearValue, ...]

    @field_validator("driver_key")
    @classmethod
    def _driver_key(cls, value: str) -> str:
        return _require_text(value, "driver_key")

    @model_validator(mode="after")
    def _validate_years(self) -> "ScenarioDriverPath":
        years = [value.year for value in self.values]
        if not years or years != list(range(1, len(years) + 1)):
            raise ValueError("scenario driver years must form a complete contiguous axis starting at 1")
        return self


class ScenarioInputSet(CanonicalContract):
    schema_version: ContractVersion = PROFESSIONAL_MODEL_CONTRACT_VERSION
    scenario_key: str
    parent_scenario_key: str | None = None
    state: AvailabilityState
    required_driver_keys: tuple[str, ...]
    driver_values: tuple[InputValue, ...] = ()
    year_paths: tuple[ScenarioDriverPath, ...] = ()
    approved_overrides: tuple[InputValue, ...] = ()
    evidence_queue_ids: tuple[str, ...] = ()
    provenance: dict[str, JsonScalar] = Field(default_factory=dict)

    @field_validator("scenario_key")
    @classmethod
    def _scenario_key(cls, value: str) -> str:
        return _require_text(value, "scenario_key")

    @model_validator(mode="after")
    def _validate_scenario(self) -> "ScenarioInputSet":
        required = set(self.required_driver_keys)
        if len(required) != len(self.required_driver_keys):
            raise ValueError("required_driver_keys contains duplicates")
        scalar_keys = [item.key for item in self.driver_values]
        path_keys = [item.driver_key for item in self.year_paths]
        if len(set(scalar_keys)) != len(scalar_keys) or len(set(path_keys)) != len(path_keys):
            raise ValueError("scenario contains duplicate driver keys")
        provided = set(scalar_keys) | set(path_keys)
        if provided != required:
            raise ValueError(f"scenario driver set is incomplete or has extras: expected {sorted(required)}, got {sorted(provided)}")

        states = [item.state.status for item in self.driver_values]
        states.extend(value.state.status for path in self.year_paths for value in path.values)
        if self.state.status is AvailabilityStatus.AVAILABLE and any(
            status is not AvailabilityStatus.AVAILABLE for status in states
        ):
            raise ValueError("available scenario cannot contain PM_REQUIRED or unavailable drivers")
        if self.state.status is AvailabilityStatus.PM_REQUIRED and AvailabilityStatus.PM_REQUIRED not in states:
            raise ValueError("PM_REQUIRED scenario must identify at least one PM_REQUIRED driver")

        for override in self.approved_overrides:
            if override.state.status is not AvailabilityStatus.AVAILABLE or not override.approval_ref:
                raise ValueError("approved overrides must be available and carry approval_ref")

        if len(set(self.evidence_queue_ids)) != len(self.evidence_queue_ids):
            raise ValueError("duplicate evidence/queue IDs")
        object.__setattr__(self, "required_driver_keys", tuple(sorted(required)))
        object.__setattr__(self, "driver_values", tuple(sorted(self.driver_values, key=lambda item: item.key)))
        object.__setattr__(self, "year_paths", tuple(sorted(self.year_paths, key=lambda item: item.driver_key)))
        object.__setattr__(self, "approved_overrides", tuple(sorted(self.approved_overrides, key=lambda item: item.key)))
        object.__setattr__(self, "evidence_queue_ids", tuple(sorted(self.evidence_queue_ids)))
        object.__setattr__(self, "provenance", dict(sorted(self.provenance.items())))
        return self


class ModelPeriod(CanonicalContract):
    contract_version: ContractVersion = PROFESSIONAL_MODEL_CONTRACT_VERSION
    index: int = Field(gt=0)
    key: str
    end_date: date
    period_type: PeriodType

    @field_validator("key")
    @classmethod
    def _key(cls, value: str) -> str:
        return _require_text(value, "key")


class PeriodAxis(CanonicalContract):
    contract_version: ContractVersion = PROFESSIONAL_MODEL_CONTRACT_VERSION
    periods: tuple[ModelPeriod, ...]

    @model_validator(mode="after")
    def _validate_axis(self) -> "PeriodAxis":
        if not self.periods:
            raise ValueError("period axis must not be empty")
        indices = [period.index for period in self.periods]
        keys = [period.key for period in self.periods]
        dates = [period.end_date for period in self.periods]
        if indices != list(range(1, len(indices) + 1)):
            raise ValueError("period axis indices must be contiguous starting at 1")
        if len(set(keys)) != len(keys):
            raise ValueError("period axis contains duplicate keys")
        if dates != sorted(dates) or len(set(dates)) != len(dates):
            raise ValueError("period axis dates must be strictly increasing")
        return self


class PeriodValue(CanonicalContract):
    contract_version: ContractVersion = PROFESSIONAL_MODEL_CONTRACT_VERSION
    period_key: str
    value: JsonScalar = None
    state: AvailabilityState
    formula_id: str | None = None
    source_refs: tuple[str, ...] = ()

    @field_validator("period_key")
    @classmethod
    def _period_key(cls, value: str) -> str:
        return _require_text(value, "period_key")

    @model_validator(mode="after")
    def _validate_value(self) -> "PeriodValue":
        if self.state.status is AvailabilityStatus.AVAILABLE and self.value is None:
            raise ValueError("available period value requires a value")
        if self.state.status is not AvailabilityStatus.AVAILABLE and self.value is not None:
            raise ValueError("non-available period value cannot carry a value")
        object.__setattr__(self, "source_refs", tuple(sorted(set(self.source_refs))))
        return self


class LineSeries(CanonicalContract):
    contract_version: ContractVersion = PROFESSIONAL_MODEL_CONTRACT_VERSION
    line_key: str
    method_id: str
    values: tuple[PeriodValue, ...]

    @field_validator("line_key", "method_id")
    @classmethod
    def _required_text(cls, value: str, info) -> str:
        return _require_text(value, info.field_name)

    @model_validator(mode="after")
    def _validate_values(self) -> "LineSeries":
        keys = [value.period_key for value in self.values]
        if len(set(keys)) != len(keys):
            raise ValueError("line series contains duplicate period keys")
        return self


class StatementResult(CanonicalContract):
    contract_version: ContractVersion = PROFESSIONAL_MODEL_CONTRACT_VERSION
    statement_key: str
    lines: tuple[LineSeries, ...]

    @field_validator("statement_key")
    @classmethod
    def _key(cls, value: str) -> str:
        return _require_text(value, "statement_key")

    @model_validator(mode="after")
    def _sort_lines(self) -> "StatementResult":
        keys = [line.line_key for line in self.lines]
        if len(set(keys)) != len(keys):
            raise ValueError("statement contains duplicate line keys")
        object.__setattr__(self, "lines", tuple(sorted(self.lines, key=lambda line: line.line_key)))
        return self


class ScheduleResult(CanonicalContract):
    contract_version: ContractVersion = PROFESSIONAL_MODEL_CONTRACT_VERSION
    schedule_key: str
    lines: tuple[LineSeries, ...]

    @field_validator("schedule_key")
    @classmethod
    def _key(cls, value: str) -> str:
        return _require_text(value, "schedule_key")

    @model_validator(mode="after")
    def _sort_lines(self) -> "ScheduleResult":
        keys = [line.line_key for line in self.lines]
        if len(set(keys)) != len(keys):
            raise ValueError("schedule contains duplicate line keys")
        object.__setattr__(self, "lines", tuple(sorted(self.lines, key=lambda line: line.line_key)))
        return self


class CheckStatus(str, Enum):
    PASS = "pass"
    REVIEW = "review"
    FAIL = "fail"
    BLOCKED = "blocked"


class CheckResult(CanonicalContract):
    contract_version: ContractVersion = PROFESSIONAL_MODEL_CONTRACT_VERSION
    check_id: str
    status: CheckStatus
    difference: float | None = None
    tolerance: float | None = Field(default=None, ge=0)
    message: str | None = None

    @field_validator("check_id")
    @classmethod
    def _check_id(cls, value: str) -> str:
        return _require_text(value, "check_id")


class WorkflowGate(CanonicalContract):
    """One auditable gate; only the literal PASS token is a positive pass."""

    gate_id: str
    module_id: str
    reported_status: str | None = None
    required_for_full: bool = True
    message: str | None = None

    @field_validator("gate_id", "module_id")
    @classmethod
    def _required_text(cls, value: str, info) -> str:
        return _require_text(value, info.field_name)

    @field_validator("reported_status")
    @classmethod
    def _reported_status(cls, value: str | None) -> str | None:
        return str(value).strip() if value is not None else None


class WorkflowAggregation(CanonicalContract):
    state: WorkflowState = WorkflowState.UNVERIFIED
    required_gate_count: int = Field(ge=0)
    passed_gate_ids: tuple[str, ...] = ()
    blocked_gate_ids: tuple[str, ...] = ()
    pm_review_gate_ids: tuple[str, ...] = ()
    partial_gate_ids: tuple[str, ...] = ()
    unverified_gate_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _derive_state(self) -> "WorkflowAggregation":
        categories = (
            self.passed_gate_ids,
            self.blocked_gate_ids,
            self.pm_review_gate_ids,
            self.partial_gate_ids,
            self.unverified_gate_ids,
        )
        flattened = [gate_id for category in categories for gate_id in category]
        if len(flattened) != self.required_gate_count:
            raise ValueError("workflow gate categories must cover every required gate")
        if len(set(flattened)) != len(flattened):
            raise ValueError("workflow gate IDs must be unique across categories")
        for field_name in (
            "passed_gate_ids",
            "blocked_gate_ids",
            "pm_review_gate_ids",
            "partial_gate_ids",
            "unverified_gate_ids",
        ):
            values = tuple(
                sorted(
                    _require_text(gate_id, "gate_id")
                    for gate_id in getattr(self, field_name)
                )
            )
            object.__setattr__(self, field_name, values)

        if self.blocked_gate_ids:
            derived = WorkflowState.BLOCKED
        elif self.pm_review_gate_ids:
            derived = WorkflowState.NEEDS_PM_REVIEW
        elif self.required_gate_count == 0:
            derived = WorkflowState.UNVERIFIED
        elif len(self.passed_gate_ids) == self.required_gate_count:
            derived = WorkflowState.FULL
        elif self.passed_gate_ids or self.partial_gate_ids:
            derived = WorkflowState.PARTIAL
        else:
            derived = WorkflowState.UNVERIFIED
        object.__setattr__(self, "state", derived)
        return self


_BLOCKED_GATE_TOKENS = frozenset(
    {
        "BLOCKED",
        "BLOCKING",
        "DEGRADED",
        "ERROR",
        "FAIL",
        "INELIGIBLE",
        "REJECTED",
        "STALE",
        "UNAVAILABLE",
    }
)
_PM_REVIEW_GATE_TOKENS = frozenset(
    {"NEEDS_PM_REVIEW", "PM_REQUIRED", "REVIEW", "REVIEW_REQUIRED"}
)


def _gate_status_token(value: object) -> str:
    if isinstance(value, WorkflowGate):
        value = value.reported_status
    if isinstance(value, Enum):
        value = value.value
    if value is None:
        return ""
    token = str(value).strip().upper()
    return re.sub(r"[^A-Z0-9]+", "_", token).strip("_")


def aggregate_workflow_state(
    gates: Iterable[WorkflowGate | CheckStatus | AvailabilityStatus | str | None],
) -> WorkflowAggregation:
    """Aggregate required gates with a positive-PASS, fail-closed truth table."""

    normalized: list[WorkflowGate] = []
    for index, gate in enumerate(gates):
        if isinstance(gate, WorkflowGate):
            normalized.append(gate)
        else:
            value = gate.value if isinstance(gate, Enum) else gate
            normalized.append(
                WorkflowGate(
                    gate_id=f"gate:{index:04d}",
                    module_id="package",
                    reported_status=None if value is None else str(value),
                )
            )

    required = [gate for gate in normalized if gate.required_for_full]
    ids = [gate.gate_id for gate in required]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate required workflow gate IDs")

    passed: list[str] = []
    blocked: list[str] = []
    pm_review: list[str] = []
    partial: list[str] = []
    unverified: list[str] = []
    for gate in required:
        token = _gate_status_token(gate)
        if token == "PASS":
            passed.append(gate.gate_id)
        elif token in _BLOCKED_GATE_TOKENS:
            blocked.append(gate.gate_id)
        elif token in _PM_REVIEW_GATE_TOKENS:
            pm_review.append(gate.gate_id)
        elif token == "PARTIAL":
            partial.append(gate.gate_id)
        else:
            unverified.append(gate.gate_id)

    return WorkflowAggregation(
        required_gate_count=len(required),
        passed_gate_ids=tuple(passed),
        blocked_gate_ids=tuple(blocked),
        pm_review_gate_ids=tuple(pm_review),
        partial_gate_ids=tuple(partial),
        unverified_gate_ids=tuple(unverified),
    )


class MethodAvailability(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    UNAVAILABLE = "UNAVAILABLE"
    DEGRADED = "DEGRADED"
    AVAILABLE = "AVAILABLE"


class DecisionEligibility(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    INELIGIBLE = "INELIGIBLE"
    NEEDS_PM_REVIEW = "NEEDS_PM_REVIEW"
    ELIGIBLE = "ELIGIBLE"


class MethodDecisionStatus(CanonicalContract):
    availability: MethodAvailability
    decision_eligibility: DecisionEligibility = DecisionEligibility.UNVERIFIED
    required_gates: tuple[WorkflowGate, ...] = ()

    @model_validator(mode="after")
    def _validate_decision_status(self) -> "MethodDecisionStatus":
        gate_ids = [gate.gate_id for gate in self.required_gates]
        if len(set(gate_ids)) != len(gate_ids):
            raise ValueError("duplicate method decision gate IDs")
        object.__setattr__(
            self,
            "required_gates",
            tuple(sorted(self.required_gates, key=lambda gate: gate.gate_id)),
        )
        aggregation = aggregate_workflow_state(self.required_gates)
        if self.decision_eligibility is DecisionEligibility.ELIGIBLE:
            if self.availability is not MethodAvailability.AVAILABLE:
                raise ValueError("decision-eligible method must be fully available")
            if aggregation.state is not WorkflowState.FULL:
                raise ValueError("decision-eligible method requires every decision gate to PASS")
        if (
            self.availability in {
                MethodAvailability.UNAVAILABLE,
                MethodAvailability.UNVERIFIED,
            }
            and self.decision_eligibility is DecisionEligibility.ELIGIBLE
        ):
            raise ValueError("unavailable/unverified method cannot be decision eligible")
        return self


class ConsensusPeriodType(str, Enum):
    CY = "CY"
    FY = "FY"
    NTM = "NTM"
    QUARTER = "QUARTER"


class ConsensusStatistic(str, Enum):
    MEAN = "MEAN"
    MEDIAN = "MEDIAN"
    HIGH = "HIGH"
    LOW = "LOW"


class ConsensusMappingMethod(str, Enum):
    UNMAPPED = "UNMAPPED"
    EXACT_PERIOD_END = "EXACT_PERIOD_END"


class ConsensusObservation(CanonicalContract):
    """One source-faithful consensus statistic with explicit decision status."""

    contract_version: ContractVersion = PROFESSIONAL_MODEL_CONTRACT_VERSION
    observation_id: str
    metric: str
    source_metric: str
    statistic: ConsensusStatistic
    value: float | None = None
    value_state: AvailabilityState
    method_status: MethodDecisionStatus
    period_type: ConsensusPeriodType
    period_label: str
    period_end: date
    mapping_method: ConsensusMappingMethod = ConsensusMappingMethod.UNMAPPED
    mapped_model_period_key: str | None = None
    mapped_model_period_end: date | None = None
    unit: str
    unit_kind: UnitKind
    scale: float = Field(gt=0)
    currency: str | None = None
    analyst_count: int | None = Field(default=None, gt=0)
    analyst_count_state: AvailabilityState
    source_name: str
    source_locator: str
    source_as_of_date: date
    transformation: str = "identity"
    consensus_d_and_a_observation_id: str | None = None

    @field_validator(
        "observation_id",
        "period_label",
        "unit",
        "source_name",
        "source_locator",
        "transformation",
    )
    @classmethod
    def _required_text(cls, value: str, info) -> str:
        return _require_text(value, info.field_name)

    @field_validator("metric", "source_metric")
    @classmethod
    def _metric(cls, value: str, info) -> str:
        token = re.sub(r"[^A-Z0-9]+", "_", _require_text(value, info.field_name).upper())
        return token.strip("_")

    @field_validator("mapping_method", mode="before")
    @classmethod
    def _mapping_method(cls, value: object) -> object:
        token = str(value.value if isinstance(value, Enum) else value).strip().upper()
        if token not in {
            ConsensusMappingMethod.UNMAPPED.value,
            ConsensusMappingMethod.EXACT_PERIOD_END.value,
        }:
            if ("CY" in token and "FY" in token) or "PLUS_ONE" in token:
                raise ValueError("CY+1 to FY1 consensus aliases are prohibited")
            raise ValueError("consensus period mapping must use exact period end")
        return token

    @model_validator(mode="after")
    def _validate_observation(self) -> "ConsensusObservation":
        object.__setattr__(
            self,
            "currency",
            _validate_unit_currency(self.unit_kind, self.currency),
        )
        if self.value_state.status is AvailabilityStatus.AVAILABLE:
            if self.value is None:
                raise ValueError("available consensus observation requires a value")
            if self.method_status.availability not in {
                MethodAvailability.AVAILABLE,
                MethodAvailability.DEGRADED,
            }:
                raise ValueError("available consensus value requires method availability")
        else:
            if self.value is not None:
                raise ValueError("unavailable consensus observation cannot carry a value")
            if self.method_status.availability in {
                MethodAvailability.AVAILABLE,
                MethodAvailability.DEGRADED,
            }:
                raise ValueError("unavailable consensus value cannot claim method availability")

        if self.analyst_count_state.status is AvailabilityStatus.AVAILABLE:
            if self.analyst_count is None:
                raise ValueError("available analyst coverage requires a positive analyst count")
        elif self.analyst_count is not None:
            raise ValueError("unavailable analyst coverage cannot carry an analyst count")
        if (
            self.method_status.decision_eligibility is DecisionEligibility.ELIGIBLE
            and self.analyst_count_state.status is not AvailabilityStatus.AVAILABLE
        ):
            raise ValueError("decision-eligible consensus requires available analyst coverage")

        if self.mapping_method is ConsensusMappingMethod.UNMAPPED:
            if self.mapped_model_period_key is not None or self.mapped_model_period_end is not None:
                raise ValueError("unmapped consensus cannot carry a model-period mapping")
        else:
            if not self.mapped_model_period_key or self.mapped_model_period_end is None:
                raise ValueError("exact consensus mapping requires model period key and end date")
            if self.mapped_model_period_end != self.period_end:
                raise ValueError("consensus mapping requires the exact source period end")

        if self.source_metric == self.metric:
            if self.transformation.strip().casefold() != "identity":
                raise ValueError("identity consensus metric cannot carry a derived transform")
            if self.consensus_d_and_a_observation_id is not None:
                raise ValueError("identity consensus metric cannot reference consensus D&A")
        elif self.source_metric == "EBITDA" and self.metric == "EBIT":
            if not self.consensus_d_and_a_observation_id:
                raise ValueError("EBITDA-to-EBIT requires a consensus D&A observation")
            transform_text = self.transformation.casefold()
            normalized = re.sub(r"[^a-z0-9]+", "", transform_text)
            if (
                normalized not in {"ebitdaminusconsensusda", "ebitdaconsensusda"}
                or not any(marker in transform_text for marker in ("minus", "-", "subtract"))
            ):
                raise ValueError("EBITDA-to-EBIT transform must subtract consensus D&A")
        else:
            raise ValueError("unsupported consensus metric transformation")
        return self


class ConsensusSnapshot(CanonicalContract):
    """Immutable consensus snapshot preserving source periods and transformations."""

    contract_version: ContractVersion = PROFESSIONAL_MODEL_CONTRACT_VERSION
    ticker: str
    as_of_date: date
    source_name: str
    source_snapshot_locator: str
    observations: tuple[ConsensusObservation, ...]
    snapshot_hash: str | None = None

    @field_validator("ticker")
    @classmethod
    def _ticker(cls, value: str) -> str:
        return _require_text(value, "ticker").upper()

    @field_validator("source_name", "source_snapshot_locator")
    @classmethod
    def _required_text(cls, value: str, info) -> str:
        return _require_text(value, info.field_name)

    @model_validator(mode="after")
    def _validate_and_hash(self) -> "ConsensusSnapshot":
        observation_ids = [item.observation_id for item in self.observations]
        identities = [
            (
                item.metric,
                item.statistic,
                item.period_type,
                item.period_end,
            )
            for item in self.observations
        ]
        if len(set(observation_ids)) != len(observation_ids):
            raise ValueError("duplicate consensus observation IDs")
        if len(set(identities)) != len(identities):
            raise ValueError("duplicate consensus metric/statistic/period observations")
        if any(item.source_as_of_date > self.as_of_date for item in self.observations):
            raise ValueError("consensus observation source date cannot exceed snapshot date")

        by_id = {item.observation_id: item for item in self.observations}
        for item in self.observations:
            reference_id = item.consensus_d_and_a_observation_id
            if reference_id is None:
                continue
            d_and_a = by_id.get(reference_id)
            if d_and_a is None:
                raise ValueError("EBITDA-to-EBIT references unknown consensus D&A")
            if d_and_a.metric != "D_AND_A" or d_and_a.source_metric != "D_AND_A":
                raise ValueError("EBITDA-to-EBIT reference must identify consensus D&A")
            if d_and_a.value_state.status is not AvailabilityStatus.AVAILABLE:
                raise ValueError("EBITDA-to-EBIT requires available consensus D&A")
            if (
                d_and_a.period_type != item.period_type
                or d_and_a.period_end != item.period_end
                or d_and_a.statistic != item.statistic
            ):
                raise ValueError("EBITDA and consensus D&A periods/statistics must match")
            if (
                d_and_a.unit_kind != item.unit_kind
                or d_and_a.currency != item.currency
                or d_and_a.scale != item.scale
            ):
                raise ValueError("EBITDA and consensus D&A units must match")

        object.__setattr__(
            self,
            "observations",
            tuple(
                sorted(
                    self.observations,
                    key=lambda item: (
                        item.metric,
                        item.statistic.value,
                        item.period_end,
                        item.observation_id,
                    ),
                )
            ),
        )
        self._bind_hash("snapshot_hash")
        return self


class DCFStubBridge(CanonicalContract):
    """Exact annual FCFF bridge from reported YTD plus the dated fiscal stub."""

    contract_version: ContractVersion = PROFESSIONAL_MODEL_CONTRACT_VERSION
    bridge_id: str
    scenario_key: str
    annual_period_start: date
    annual_period_end: date
    ytd_period_start: date
    ytd_period_end: date
    stub_period_start: date
    stub_period_end: date
    annual_fcff: float
    ytd_fcff: float
    stub_fcff: float
    tolerance: float = Field(default=1e-9, ge=0)
    unit: str
    unit_kind: UnitKind
    currency: str | None = None
    source_refs: tuple[str, ...]
    reconciliation_status: CheckStatus = CheckStatus.BLOCKED

    @field_validator("bridge_id", "scenario_key", "unit")
    @classmethod
    def _required_text(cls, value: str, info) -> str:
        return _require_text(value, info.field_name)

    @model_validator(mode="after")
    def _validate_bridge(self) -> "DCFStubBridge":
        object.__setattr__(
            self,
            "currency",
            _validate_unit_currency(self.unit_kind, self.currency),
        )
        if (
            self.ytd_period_start != self.annual_period_start
            or self.stub_period_end != self.annual_period_end
            or self.ytd_period_end + timedelta(days=1) != self.stub_period_start
        ):
            raise ValueError("DCF annual period must be contiguous YTD plus fiscal stub")
        if not (
            self.annual_period_start <= self.ytd_period_end
            < self.stub_period_start <= self.stub_period_end
        ):
            raise ValueError("DCF stub bridge dates are inconsistent")
        difference = self.annual_fcff - (self.ytd_fcff + self.stub_fcff)
        if abs(difference) > self.tolerance:
            raise ValueError("annual FCFF must equal YTD FCFF plus stub FCFF")
        refs = tuple(sorted({_require_text(item, "source_ref") for item in self.source_refs}))
        if not refs:
            raise ValueError("DCF stub bridge requires source references")
        object.__setattr__(self, "source_refs", refs)
        object.__setattr__(self, "reconciliation_status", CheckStatus.PASS)
        return self


class DCFDiscountPeriodEvidence(CanonicalContract):
    """Dated ACT/365 midpoint discount period; ordinal periods are prohibited."""

    contract_version: ContractVersion = PROFESSIONAL_MODEL_CONTRACT_VERSION
    period_id: str
    scenario_key: str
    valuation_at: datetime
    cash_flow_period_start_at: datetime
    cash_flow_period_end_at: datetime
    cash_flow_midpoint_at: datetime
    day_count_convention: Literal["ACT/365"] = "ACT/365"
    discount_period_years: float = Field(gt=0)
    source_refs: tuple[str, ...]

    @field_validator("period_id", "scenario_key")
    @classmethod
    def _required_text(cls, value: str, info) -> str:
        return _require_text(value, info.field_name)

    @model_validator(mode="after")
    def _validate_period(self) -> "DCFDiscountPeriodEvidence":
        timestamps = (
            self.valuation_at,
            self.cash_flow_period_start_at,
            self.cash_flow_period_end_at,
            self.cash_flow_midpoint_at,
        )
        if any(item.tzinfo is None or item.utcoffset() is None for item in timestamps):
            raise ValueError("DCF discount-period timestamps must be timezone-aware")
        if self.cash_flow_period_end_at <= self.cash_flow_period_start_at:
            raise ValueError("DCF cash-flow period end must follow period start")
        expected_midpoint = self.cash_flow_period_start_at + (
            self.cash_flow_period_end_at - self.cash_flow_period_start_at
        ) / 2
        if abs((self.cash_flow_midpoint_at - expected_midpoint).total_seconds()) > 1e-6:
            raise ValueError("DCF cash flow must use the exact dated midpoint")
        expected_years = (
            self.cash_flow_midpoint_at - self.valuation_at
        ).total_seconds() / (365.0 * 24.0 * 60.0 * 60.0)
        if expected_years <= 0 or abs(self.discount_period_years - expected_years) > 1e-10:
            raise ValueError("DCF discount period must equal ACT/365 midpoint timing")
        refs = tuple(sorted({_require_text(item, "source_ref") for item in self.source_refs}))
        if not refs:
            raise ValueError("DCF discount period requires source references")
        object.__setattr__(self, "source_refs", refs)
        return self


class DCFParameterName(str, Enum):
    WACC = "WACC"
    TERMINAL_GROWTH = "TERMINAL_GROWTH"
    TAX_RATE = "TAX_RATE"


class DCFParameterScope(str, Enum):
    SCENARIO_SPECIFIC = "SCENARIO_SPECIFIC"
    SHARED_APPROVED = "SHARED_APPROVED"


class DCFParameterGovernance(CanonicalContract):
    contract_version: ContractVersion = PROFESSIONAL_MODEL_CONTRACT_VERSION
    parameter: DCFParameterName
    scenario_key: str
    value: float
    driver_fingerprint: str
    scope: DCFParameterScope
    shared_scenario_keys: tuple[str, ...] = ()
    approval_record: DriverApprovalRecord | None = None
    source_refs: tuple[str, ...]

    @field_validator("scenario_key")
    @classmethod
    def _scenario_key(cls, value: str) -> str:
        return _require_text(value, "scenario_key")

    @field_validator("driver_fingerprint")
    @classmethod
    def _fingerprint(cls, value: str) -> str:
        return _validate_sha256(value, "driver_fingerprint")

    @model_validator(mode="after")
    def _validate_governance(self) -> "DCFParameterGovernance":
        if self.parameter in {DCFParameterName.WACC, DCFParameterName.TAX_RATE}:
            if not 0.0 <= self.value <= 1.0:
                raise ValueError(f"{self.parameter.value} must be between zero and one")
        elif not -1.0 < self.value < 1.0:
            raise ValueError("terminal growth must be between negative and positive one")

        shared = tuple(
            sorted({_require_text(item, "shared_scenario_key") for item in self.shared_scenario_keys})
        )
        refs = tuple(sorted({_require_text(item, "source_ref") for item in self.source_refs}))
        if not refs:
            raise ValueError("DCF parameter governance requires source references")
        object.__setattr__(self, "shared_scenario_keys", shared)
        object.__setattr__(self, "source_refs", refs)

        if self.scope is DCFParameterScope.SCENARIO_SPECIFIC:
            if shared:
                raise ValueError("scenario-specific DCF parameter cannot name shared scenarios")
        else:
            if len(shared) < 2 or self.scenario_key not in shared:
                raise ValueError("shared DCF parameter must identify every governed scenario")
            approval = self.approval_record
            if (
                approval is None
                or approval.approval_state is not DriverApprovalState.APPROVED
                or approval.driver_group is not DriverGroup.FINANCE_SEMANTIC
                or approval.current_driver_fingerprint != self.driver_fingerprint
                or approval.approved_driver_fingerprint != self.driver_fingerprint
            ):
                raise ValueError("shared DCF parameter requires matching PM approval")
        if self.approval_record is not None and (
            self.approval_record.current_driver_fingerprint != self.driver_fingerprint
        ):
            raise ValueError("DCF parameter approval fingerprint mismatch")
        return self


class DCFScenarioGovernance(CanonicalContract):
    contract_version: ContractVersion = PROFESSIONAL_MODEL_CONTRACT_VERSION
    scenario_key: str
    parameters: tuple[DCFParameterGovernance, ...]
    governance_hash: str | None = None

    @field_validator("scenario_key")
    @classmethod
    def _scenario_key(cls, value: str) -> str:
        return _require_text(value, "scenario_key")

    @model_validator(mode="after")
    def _validate_and_hash(self) -> "DCFScenarioGovernance":
        by_name = {item.parameter: item for item in self.parameters}
        if len(by_name) != len(self.parameters):
            raise ValueError("duplicate governed DCF parameter")
        if set(by_name) != set(DCFParameterName):
            raise ValueError("DCF governance requires WACC, terminal growth, and tax rate")
        if any(item.scenario_key != self.scenario_key for item in self.parameters):
            raise ValueError("DCF parameter scenario must match governance scenario")
        if by_name[DCFParameterName.WACC].value <= by_name[DCFParameterName.TERMINAL_GROWTH].value:
            raise ValueError("DCF governance requires WACC greater than terminal growth")
        object.__setattr__(
            self,
            "parameters",
            tuple(sorted(self.parameters, key=lambda item: item.parameter.value)),
        )
        self._bind_hash("governance_hash")
        return self


class CurrentFullyDilutedSharesEvidence(CanonicalContract):
    contract_version: ContractVersion = PROFESSIONAL_MODEL_CONTRACT_VERSION
    shares: float = Field(gt=0)
    as_of_date: date
    valuation_date: date
    unit: str
    unit_kind: UnitKind = UnitKind.COUNT
    scale: float = Field(gt=0)
    source_name: str
    source_locator: str
    source_refs: tuple[str, ...]
    state: AvailabilityState
    method_status: MethodDecisionStatus

    @field_validator("unit", "source_name", "source_locator")
    @classmethod
    def _required_text(cls, value: str, info) -> str:
        return _require_text(value, info.field_name)

    @model_validator(mode="after")
    def _validate_shares(self) -> "CurrentFullyDilutedSharesEvidence":
        if self.unit_kind is not UnitKind.COUNT:
            raise ValueError("current FDS unit_kind must be count")
        if self.as_of_date > self.valuation_date:
            raise ValueError("current FDS as-of date cannot exceed valuation date")
        if self.state.status is not AvailabilityStatus.AVAILABLE:
            raise ValueError("current FDS evidence must be explicitly available")
        if self.method_status.availability not in {
            MethodAvailability.AVAILABLE,
            MethodAvailability.DEGRADED,
        }:
            raise ValueError("current FDS evidence requires method availability")
        refs = tuple(sorted({_require_text(item, "source_ref") for item in self.source_refs}))
        if not refs:
            raise ValueError("current FDS evidence requires source references")
        object.__setattr__(self, "source_refs", refs)
        return self


class WACCMethodologyEvidence(CanonicalContract):
    contract_version: ContractVersion = PROFESSIONAL_MODEL_CONTRACT_VERSION
    methodology_id: str
    methodology_version: str
    as_of_date: date
    output_wacc: float = Field(ge=0, le=1)
    inputs: dict[str, float]
    source_refs: tuple[str, ...]
    method_status: MethodDecisionStatus
    methodology_hash: str | None = None

    @field_validator("methodology_id", "methodology_version")
    @classmethod
    def _required_text(cls, value: str, info) -> str:
        return _require_text(value, info.field_name)

    @model_validator(mode="after")
    def _validate_and_hash(self) -> "WACCMethodologyEvidence":
        if not self.inputs:
            raise ValueError("WACC methodology requires explicit inputs")
        if self.method_status.availability not in {
            MethodAvailability.AVAILABLE,
            MethodAvailability.DEGRADED,
        }:
            raise ValueError("WACC methodology output requires method availability")
        refs = tuple(sorted({_require_text(item, "source_ref") for item in self.source_refs}))
        if not refs:
            raise ValueError("WACC methodology requires source references")
        object.__setattr__(self, "inputs", dict(sorted(self.inputs.items())))
        object.__setattr__(self, "source_refs", refs)
        self._bind_hash("methodology_hash")
        return self


class WACCParityEvidence(CanonicalContract):
    contract_version: ContractVersion = PROFESSIONAL_MODEL_CONTRACT_VERSION
    methodology_id: str
    methodology_version: str
    methodology_hash: str
    as_of_date: date
    backend_wacc: float = Field(ge=0, le=1)
    workbook_wacc: float = Field(ge=0, le=1)
    tolerance_basis_points: float = Field(default=1.0, gt=0, le=1.0)
    difference_basis_points: float = Field(default=0, ge=0)
    parity_status: CheckStatus = CheckStatus.BLOCKED
    backend_source_ref: str
    workbook_sheet: str
    workbook_cell: str

    @field_validator(
        "methodology_id",
        "methodology_version",
        "backend_source_ref",
        "workbook_sheet",
    )
    @classmethod
    def _required_text(cls, value: str, info) -> str:
        return _require_text(value, info.field_name)

    @field_validator("methodology_hash")
    @classmethod
    def _methodology_hash(cls, value: str) -> str:
        return _validate_sha256(value, "methodology_hash")

    @field_validator("workbook_cell")
    @classmethod
    def _cell(cls, value: str) -> str:
        return _normalize_a1(value)

    @model_validator(mode="after")
    def _derive_parity(self) -> "WACCParityEvidence":
        difference = abs(self.backend_wacc - self.workbook_wacc) * 10_000.0
        object.__setattr__(self, "difference_basis_points", difference)
        object.__setattr__(
            self,
            "parity_status",
            CheckStatus.PASS
            if difference <= self.tolerance_basis_points + 1e-12
            else CheckStatus.FAIL,
        )
        return self


class DependencyScope(str, Enum):
    UNPROVEN = "UNPROVEN"
    GLOBAL = "GLOBAL"
    MODULE_SCOPED = "MODULE_SCOPED"


class ModuleDependency(CanonicalContract):
    dependency_id: str
    provider_module: str
    consumer_module: str
    scope: DependencyScope = DependencyScope.UNPROVEN
    required_for_package_full: bool = True
    scope_proof_refs: tuple[str, ...] = ()

    @field_validator("dependency_id", "provider_module", "consumer_module")
    @classmethod
    def _required_text(cls, value: str, info) -> str:
        return _require_text(value, info.field_name)

    @model_validator(mode="after")
    def _validate_dependency(self) -> "ModuleDependency":
        if self.provider_module == self.consumer_module:
            raise ValueError("module dependency provider and consumer must differ")
        refs = tuple(
            sorted({_require_text(item, "scope_proof_ref") for item in self.scope_proof_refs})
        )
        object.__setattr__(self, "scope_proof_refs", refs)
        if self.scope is DependencyScope.MODULE_SCOPED and not refs:
            raise ValueError("module-scoped dependency requires deterministic scope proof")
        return self


class ModuleBlocker(CanonicalContract):
    blocker_id: str
    module_id: str
    dependency_ids: tuple[str, ...] = ()
    scope: DependencyScope = DependencyScope.UNPROVEN
    scope_proof_refs: tuple[str, ...] = ()

    @field_validator("blocker_id", "module_id")
    @classmethod
    def _required_text(cls, value: str, info) -> str:
        return _require_text(value, info.field_name)

    @model_validator(mode="after")
    def _validate_blocker(self) -> "ModuleBlocker":
        dependencies = tuple(
            sorted({_require_text(item, "dependency_id") for item in self.dependency_ids})
        )
        refs = tuple(
            sorted({_require_text(item, "scope_proof_ref") for item in self.scope_proof_refs})
        )
        object.__setattr__(self, "dependency_ids", dependencies)
        object.__setattr__(self, "scope_proof_refs", refs)
        if self.scope is DependencyScope.MODULE_SCOPED and (
            not dependencies or not refs
        ):
            raise ValueError(
                "module-scoped blocker requires dependencies and deterministic scope proof"
            )
        return self


class ModuleWorkflow(CanonicalContract):
    module_id: str
    gates: tuple[WorkflowGate, ...]
    required_for_package_full: bool = True

    @field_validator("module_id")
    @classmethod
    def _module_id(cls, value: str) -> str:
        return _require_text(value, "module_id")

    @model_validator(mode="after")
    def _validate_module(self) -> "ModuleWorkflow":
        gate_ids = [gate.gate_id for gate in self.gates]
        if len(set(gate_ids)) != len(gate_ids):
            raise ValueError("duplicate module gate IDs")
        if any(gate.module_id != self.module_id for gate in self.gates):
            raise ValueError("module workflow gates must name their containing module")
        object.__setattr__(self, "gates", tuple(sorted(self.gates, key=lambda gate: gate.gate_id)))
        return self


class PackageWorkflowAggregation(CanonicalContract):
    state: WorkflowState = WorkflowState.UNVERIFIED
    module_states: dict[str, WorkflowState]
    required_modules: tuple[str, ...]
    global_blocker_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _derive_package_state(self) -> "PackageWorkflowAggregation":
        states = dict(sorted(self.module_states.items()))
        required = tuple(sorted({_require_text(item, "required_module") for item in self.required_modules}))
        blockers = tuple(
            sorted({_require_text(item, "global_blocker_id") for item in self.global_blocker_ids})
        )
        unknown = sorted(set(required) - set(states))
        if unknown:
            raise ValueError(f"required package modules are missing: {unknown}")
        object.__setattr__(self, "module_states", states)
        object.__setattr__(self, "required_modules", required)
        object.__setattr__(self, "global_blocker_ids", blockers)

        required_states = [states[module_id] for module_id in required]
        if blockers or WorkflowState.BLOCKED in required_states:
            derived = WorkflowState.BLOCKED
        elif WorkflowState.NEEDS_PM_REVIEW in required_states:
            derived = WorkflowState.NEEDS_PM_REVIEW
        elif not required_states:
            derived = WorkflowState.UNVERIFIED
        elif all(state is WorkflowState.FULL for state in required_states):
            derived = WorkflowState.FULL
        elif any(
            state in {WorkflowState.FULL, WorkflowState.PARTIAL}
            for state in required_states
        ):
            derived = WorkflowState.PARTIAL
        else:
            derived = WorkflowState.UNVERIFIED
        object.__setattr__(self, "state", derived)
        return self


def aggregate_package_workflow(
    modules: Iterable[ModuleWorkflow],
    *,
    dependencies: Iterable[ModuleDependency] = (),
    blockers: Iterable[ModuleBlocker] = (),
) -> PackageWorkflowAggregation:
    """Apply module scoping only when matching dependency evidence proves it."""

    module_items = tuple(modules)
    module_ids = [module.module_id for module in module_items]
    if len(set(module_ids)) != len(module_ids):
        raise ValueError("duplicate module workflow IDs")
    module_by_id = {module.module_id: module for module in module_items}
    module_states = {
        module.module_id: aggregate_workflow_state(module.gates).state
        for module in module_items
    }
    required_modules = {
        module.module_id
        for module in module_items
        if module.required_for_package_full
    }

    dependency_items = tuple(dependencies)
    dependency_ids = [item.dependency_id for item in dependency_items]
    if len(set(dependency_ids)) != len(dependency_ids):
        raise ValueError("duplicate module dependency IDs")
    dependency_by_id = {item.dependency_id: item for item in dependency_items}
    global_blocker_ids: set[str] = set()
    for dependency in dependency_items:
        if (
            dependency.provider_module not in module_by_id
            or dependency.consumer_module not in module_by_id
        ):
            global_blocker_ids.add(f"dependency:{dependency.dependency_id}:unknown_module")
        elif dependency.required_for_package_full:
            required_modules.update(
                {dependency.provider_module, dependency.consumer_module}
            )

    blocker_items = tuple(blockers)
    blocker_ids = [item.blocker_id for item in blocker_items]
    if len(set(blocker_ids)) != len(blocker_ids):
        raise ValueError("duplicate module blocker IDs")
    for blocker in blocker_items:
        linked = [dependency_by_id.get(item) for item in blocker.dependency_ids]
        proven_scoped = (
            blocker.scope is DependencyScope.MODULE_SCOPED
            and blocker.module_id in module_by_id
            and bool(linked)
            and all(item is not None for item in linked)
            and all(
                item.scope is DependencyScope.MODULE_SCOPED
                and item.consumer_module == blocker.module_id
                and bool(item.scope_proof_refs)
                for item in linked
                if item is not None
            )
            and bool(blocker.scope_proof_refs)
        )
        if proven_scoped:
            module_states[blocker.module_id] = WorkflowState.BLOCKED
        else:
            global_blocker_ids.add(blocker.blocker_id)

    return PackageWorkflowAggregation(
        module_states=module_states,
        required_modules=tuple(required_modules),
        global_blocker_ids=tuple(global_blocker_ids),
    )


class CalculationVerificationRecord(CanonicalContract):
    """Native-engine calculation evidence bound to immutable workbook inputs."""

    contract_version: ContractVersion = PROFESSIONAL_MODEL_CONTRACT_VERSION
    workbook_sha256: str
    model_input_hash: str
    workbook_model_input_hash: str
    model_input_hash_parity: CheckStatus
    formula_text_hash: str
    precalculation_formula_text_hash: str
    formula_text_expectation_bound: bool
    expected_formula_text_hash: str
    formula_text_parity: CheckStatus
    formula_count: int = Field(ge=0)
    cached_formula_count: int = Field(ge=0)
    cache_population: CheckStatus
    formula_error_count: int = Field(ge=0)
    formula_errors: tuple[str, ...] = ()
    formula_error_scan: CheckStatus
    engine: str
    engine_version: str
    calculation_completed: bool
    verified_at: datetime
    verification_state: WorkflowState = WorkflowState.UNVERIFIED
    verification_hash: str | None = None

    @field_validator(
        "workbook_sha256",
        "model_input_hash",
        "formula_text_hash",
        "workbook_model_input_hash",
        "precalculation_formula_text_hash",
        "expected_formula_text_hash",
    )
    @classmethod
    def _hashes(cls, value: str, info) -> str:
        return _validate_sha256(value, info.field_name)

    @field_validator("engine", "engine_version")
    @classmethod
    def _required_text(cls, value: str, info) -> str:
        return _require_text(value, info.field_name)

    @model_validator(mode="after")
    def _validate_and_hash(self) -> "CalculationVerificationRecord":
        if self.cached_formula_count > self.formula_count:
            raise ValueError("cached_formula_count cannot exceed formula_count")
        if self.formula_error_count > self.formula_count:
            raise ValueError("formula_error_count cannot exceed formula_count")
        formula_errors = tuple(
            sorted({_require_text(item, "formula_error") for item in self.formula_errors})
        )
        object.__setattr__(self, "formula_errors", formula_errors)
        if len(formula_errors) != self.formula_error_count:
            raise ValueError("formula_error_count must match formula error details")
        if self.model_input_hash_parity is CheckStatus.PASS and (
            self.model_input_hash != self.workbook_model_input_hash
        ):
            raise ValueError("model-input PASS requires matching expected/workbook hashes")
        if self.formula_text_parity is CheckStatus.PASS and len(
            {
                self.formula_text_hash,
                self.precalculation_formula_text_hash,
                self.expected_formula_text_hash,
            }
        ) != 1:
            raise ValueError("formula-text PASS requires matching formula hashes")
        if self.cache_population is CheckStatus.PASS and (
            self.formula_count == 0
            or self.cached_formula_count != self.formula_count
        ):
            raise ValueError("cache-population PASS requires every formula cache")
        if self.formula_error_scan is CheckStatus.PASS and self.formula_error_count != 0:
            raise ValueError("formula-error PASS requires zero formula errors")
        if self.verified_at.tzinfo is None or self.verified_at.utcoffset() is None:
            raise ValueError("verified_at must be timezone-aware")

        gates = (
            WorkflowGate(
                gate_id="calculation_completed",
                module_id="calculation",
                reported_status="PASS" if self.calculation_completed else None,
            ),
            WorkflowGate(
                gate_id="model_input_hash_parity",
                module_id="calculation",
                reported_status=self.model_input_hash_parity.value,
            ),
            WorkflowGate(
                gate_id="formula_text_expectation_bound",
                module_id="calculation",
                reported_status="PASS" if self.formula_text_expectation_bound else None,
            ),
            WorkflowGate(
                gate_id="formula_text_parity",
                module_id="calculation",
                reported_status=self.formula_text_parity.value,
            ),
            WorkflowGate(
                gate_id="cache_population",
                module_id="calculation",
                reported_status=self.cache_population.value,
            ),
            WorkflowGate(
                gate_id="formula_error_scan",
                module_id="calculation",
                reported_status=self.formula_error_scan.value,
            ),
        )
        object.__setattr__(
            self,
            "verification_state",
            aggregate_workflow_state(gates).state,
        )
        self._bind_hash("verification_hash")
        return self


class ModelResult(CanonicalContract):
    schema_version: ContractVersion = PROFESSIONAL_MODEL_CONTRACT_VERSION
    scenario_key: str
    state: AvailabilityState
    period_axis: PeriodAxis
    statements: tuple[StatementResult, ...]
    supporting_schedules: tuple[ScheduleResult, ...]
    check_results: tuple[CheckResult, ...]
    tolerances: dict[str, float]
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    input_hash: str
    result_hash: str | None = None

    @field_validator("scenario_key")
    @classmethod
    def _scenario_key(cls, value: str) -> str:
        return _require_text(value, "scenario_key")

    @field_validator("input_hash")
    @classmethod
    def _input_hash(cls, value: str) -> str:
        return _validate_sha256(value, "input_hash")

    @model_validator(mode="after")
    def _validate_and_hash(self) -> "ModelResult":
        axis_keys = tuple(period.key for period in self.period_axis.periods)
        statement_keys = [statement.statement_key for statement in self.statements]
        schedule_keys = [schedule.schedule_key for schedule in self.supporting_schedules]
        check_ids = [check.check_id for check in self.check_results]
        if len(set(statement_keys)) != len(statement_keys):
            raise ValueError("duplicate statement keys")
        if len(set(schedule_keys)) != len(schedule_keys):
            raise ValueError("duplicate schedule keys")
        if len(set(check_ids)) != len(check_ids):
            raise ValueError("duplicate check IDs")
        for container in (*self.statements, *self.supporting_schedules):
            for line in container.lines:
                line_keys = tuple(value.period_key for value in line.values)
                if line_keys != axis_keys:
                    raise ValueError(f"line {line.line_key} does not cover the complete period axis")
        if set(self.tolerances) != set(check_ids):
            raise ValueError("tolerances must cover every check exactly once")
        if self.state.status is AvailabilityStatus.AVAILABLE:
            if (
                self.blockers
                or not self.check_results
                or any(check.status is not CheckStatus.PASS for check in self.check_results)
            ):
                raise ValueError("available model result requires every check to PASS")
        elif self.state.status is AvailabilityStatus.BLOCKING and not self.blockers:
            raise ValueError("blocking model result requires blockers")
        object.__setattr__(self, "statements", tuple(sorted(self.statements, key=lambda item: item.statement_key)))
        object.__setattr__(self, "supporting_schedules", tuple(sorted(self.supporting_schedules, key=lambda item: item.schedule_key)))
        object.__setattr__(self, "check_results", tuple(sorted(self.check_results, key=lambda item: item.check_id)))
        object.__setattr__(self, "tolerances", dict(sorted(self.tolerances.items())))
        object.__setattr__(self, "warnings", tuple(sorted(set(self.warnings))))
        object.__setattr__(self, "blockers", tuple(sorted(set(self.blockers))))
        self._bind_hash("result_hash")
        return self


class ValuationMethod(str, Enum):
    FCFF_DCF = "fcff_dcf"
    FCFE = "fcfe"
    REVERSE_DCF = "reverse_dcf"
    COMPS = "comps"
    HISTORICAL_RANGE = "historical_range"
    SOTP = "sotp"


class ValuationMethodResult(CanonicalContract):
    contract_version: ContractVersion = PROFESSIONAL_MODEL_CONTRACT_VERSION
    method: ValuationMethod
    state: AvailabilityState
    decision_status: MethodDecisionStatus | None = None
    value_per_share: float | None = None
    low_value_per_share: float | None = None
    high_value_per_share: float | None = None
    metrics: dict[str, JsonScalar] = Field(default_factory=dict)
    source_refs: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _validate_output(self) -> "ValuationMethodResult":
        if self.state.status is AvailabilityStatus.AVAILABLE:
            if self.value_per_share is None and not self.metrics:
                raise ValueError("available valuation method requires a value or metrics")
        elif any(value is not None for value in (self.value_per_share, self.low_value_per_share, self.high_value_per_share)):
            raise ValueError("unavailable/blocking valuation method cannot carry per-share values")
        if self.decision_status is None:
            if self.state.status is AvailabilityStatus.AVAILABLE:
                decision_status = MethodDecisionStatus(
                    availability=MethodAvailability.AVAILABLE,
                    decision_eligibility=DecisionEligibility.UNVERIFIED,
                )
            elif self.state.status is AvailabilityStatus.PM_REQUIRED:
                decision_status = MethodDecisionStatus(
                    availability=MethodAvailability.UNVERIFIED,
                    decision_eligibility=DecisionEligibility.NEEDS_PM_REVIEW,
                )
            else:
                decision_status = MethodDecisionStatus(
                    availability=MethodAvailability.UNAVAILABLE,
                    decision_eligibility=DecisionEligibility.INELIGIBLE,
                )
            object.__setattr__(self, "decision_status", decision_status)
        elif (
            self.state.status is not AvailabilityStatus.AVAILABLE
            and self.decision_status.availability
            in {MethodAvailability.AVAILABLE, MethodAvailability.DEGRADED}
        ):
            raise ValueError("non-available valuation output cannot claim method availability")
        elif self.state.status is AvailabilityStatus.AVAILABLE and (
            self.decision_status.availability in {
                MethodAvailability.UNAVAILABLE,
                MethodAvailability.UNVERIFIED,
            }
        ):
            raise ValueError("available valuation output must identify method availability")
        object.__setattr__(self, "metrics", dict(sorted(self.metrics.items())))
        object.__setattr__(self, "source_refs", tuple(sorted(set(self.source_refs))))
        return self


class WACCMethodResult(CanonicalContract):
    contract_version: ContractVersion = PROFESSIONAL_MODEL_CONTRACT_VERSION
    method_id: str
    state: AvailabilityState
    wacc: float | None = Field(default=None, ge=0, le=1)
    selected: bool = False
    source_refs: tuple[str, ...] = ()

    @field_validator("method_id")
    @classmethod
    def _method_id(cls, value: str) -> str:
        return _require_text(value, "method_id")

    @model_validator(mode="after")
    def _validate_wacc(self) -> "WACCMethodResult":
        if self.state.status is AvailabilityStatus.AVAILABLE and self.wacc is None:
            raise ValueError("available WACC method requires wacc")
        if self.state.status is not AvailabilityStatus.AVAILABLE and self.wacc is not None:
            raise ValueError("non-available WACC method cannot carry wacc")
        object.__setattr__(self, "source_refs", tuple(sorted(set(self.source_refs))))
        return self


class BridgeItem(CanonicalContract):
    contract_version: ContractVersion = PROFESSIONAL_MODEL_CONTRACT_VERSION
    key: str
    amount: float
    operation: Literal["add", "subtract"]
    source_refs: tuple[str, ...]

    @field_validator("key")
    @classmethod
    def _key(cls, value: str) -> str:
        return _require_text(value, "key")

    @model_validator(mode="after")
    def _sort_refs(self) -> "BridgeItem":
        if not self.source_refs:
            raise ValueError("bridge item requires source_refs")
        object.__setattr__(self, "source_refs", tuple(sorted(set(self.source_refs))))
        return self


class SensitivityResult(CanonicalContract):
    contract_version: ContractVersion = PROFESSIONAL_MODEL_CONTRACT_VERSION
    sensitivity_id: str
    state: AvailabilityState
    outputs: dict[str, JsonScalar] = Field(default_factory=dict)

    @field_validator("sensitivity_id")
    @classmethod
    def _id(cls, value: str) -> str:
        return _require_text(value, "sensitivity_id")

    @model_validator(mode="after")
    def _sort_outputs(self) -> "SensitivityResult":
        object.__setattr__(self, "outputs", dict(sorted(self.outputs.items())))
        return self


class ValuationBundle(CanonicalContract):
    schema_version: ContractVersion = PROFESSIONAL_MODEL_CONTRACT_VERSION
    scenario_key: str
    state: AvailabilityState
    input_hash: str
    result_hash: str
    wacc_methods: tuple[WACCMethodResult, ...]
    selected_wacc_policy: str
    valuation_methods: tuple[ValuationMethodResult, ...]
    peer_universe_version: str
    peer_tickers: tuple[str, ...]
    terminal_value_diagnostics: dict[str, JsonScalar]
    ev_equity_bridge: tuple[BridgeItem, ...]
    sensitivities: tuple[SensitivityResult, ...]
    implied_per_share_reconciliation: CheckResult
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    bundle_hash: str | None = None

    @field_validator("scenario_key", "selected_wacc_policy", "peer_universe_version")
    @classmethod
    def _required_text(cls, value: str, info) -> str:
        return _require_text(value, info.field_name)

    @field_validator("input_hash", "result_hash")
    @classmethod
    def _hashes(cls, value: str, info) -> str:
        return _validate_sha256(value, info.field_name)

    @model_validator(mode="after")
    def _validate_and_hash(self) -> "ValuationBundle":
        method_ids = [method.method_id for method in self.wacc_methods]
        if len(set(method_ids)) != len(method_ids):
            raise ValueError("duplicate WACC method IDs")
        selected = [method for method in self.wacc_methods if method.selected]
        if len(selected) != 1 or selected[0].method_id != self.selected_wacc_policy:
            raise ValueError("selected_wacc_policy must identify exactly one selected WACC method")

        valuation_methods = [result.method for result in self.valuation_methods]
        if len(set(valuation_methods)) != len(valuation_methods):
            raise ValueError("duplicate valuation methods")
        probability_keys = {
            key
            for result in self.valuation_methods
            for key in result.metrics
            if "probability" in key.lower()
        }
        probability_keys.update(
            key for key in self.terminal_value_diagnostics if "probability" in key.lower()
        )
        if probability_keys:
            raise ValueError(f"probability-weighted valuation is prohibited: {sorted(probability_keys)}")
        missing = set(ValuationMethod) - set(valuation_methods)
        extra = set(valuation_methods) - set(ValuationMethod)
        if missing or extra:
            raise ValueError(f"valuation methods must include every required method; missing={sorted(item.value for item in missing)}")

        if self.state.status is AvailabilityStatus.AVAILABLE:
            if (
                self.blockers
                or selected[0].state.status is not AvailabilityStatus.AVAILABLE
                or self.implied_per_share_reconciliation.status is not CheckStatus.PASS
            ):
                raise ValueError(
                    "available valuation bundle requires selected WACC, reconciliation PASS, and no blockers"
                )
        elif self.state.status is AvailabilityStatus.BLOCKING and not self.blockers:
            raise ValueError("blocking valuation bundle requires blockers")

        normalized_peers = tuple(ticker.upper().strip() for ticker in self.peer_tickers)
        if len(set(normalized_peers)) != len(normalized_peers):
            raise ValueError("duplicate valuation peer tickers")
        if any(not ticker for ticker in normalized_peers):
            raise ValueError("valuation peer tickers cannot be blank")
        order = {method: index for index, method in enumerate(ValuationMethod)}
        object.__setattr__(self, "wacc_methods", tuple(sorted(self.wacc_methods, key=lambda item: item.method_id)))
        object.__setattr__(self, "valuation_methods", tuple(sorted(self.valuation_methods, key=lambda item: order[item.method])))
        object.__setattr__(self, "peer_tickers", tuple(sorted(normalized_peers)))
        object.__setattr__(self, "terminal_value_diagnostics", dict(sorted(self.terminal_value_diagnostics.items())))
        object.__setattr__(self, "ev_equity_bridge", tuple(sorted(self.ev_equity_bridge, key=lambda item: item.key)))
        object.__setattr__(self, "sensitivities", tuple(sorted(self.sensitivities, key=lambda item: item.sensitivity_id)))
        object.__setattr__(self, "warnings", tuple(sorted(set(self.warnings))))
        object.__setattr__(self, "blockers", tuple(sorted(set(self.blockers))))
        self._bind_hash("bundle_hash")
        return self


class CellKind(str, Enum):
    EDITABLE = "editable"
    FORMULA = "formula"
    SOURCE = "source"
    CHECK = "check"
    STATIC = "static"
    UNAVAILABLE = "unavailable"


class LineCellMapping(CanonicalContract):
    contract_version: ContractVersion = PROFESSIONAL_MODEL_CONTRACT_VERSION
    canonical_key: str
    scenario_key: str
    period_key: str
    sheet: str
    cell: str

    @field_validator("canonical_key", "scenario_key", "period_key", "sheet")
    @classmethod
    def _required_text(cls, value: str, info) -> str:
        return _require_text(value, info.field_name)

    @field_validator("cell")
    @classmethod
    def _cell(cls, value: str) -> str:
        return _normalize_a1(value)


class CellClassification(CanonicalContract):
    contract_version: ContractVersion = PROFESSIONAL_MODEL_CONTRACT_VERSION
    sheet: str
    cell: str
    kind: CellKind

    @field_validator("sheet")
    @classmethod
    def _sheet(cls, value: str) -> str:
        return _require_text(value, "sheet")

    @field_validator("cell")
    @classmethod
    def _cell(cls, value: str) -> str:
        return _normalize_a1(value)


class DefinedNameMapping(CanonicalContract):
    contract_version: ContractVersion = PROFESSIONAL_MODEL_CONTRACT_VERSION
    name: str
    sheet: str
    cell: str

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        cleaned = _require_text(value, "name")
        if not DEFINED_NAME_RE.fullmatch(cleaned):
            raise ValueError("defined name is invalid")
        return cleaned

    @field_validator("sheet")
    @classmethod
    def _sheet(cls, value: str) -> str:
        return _require_text(value, "sheet")

    @field_validator("cell")
    @classmethod
    def _cell(cls, value: str) -> str:
        return _normalize_a1(value)


class WorkbookCheckCell(CanonicalContract):
    contract_version: ContractVersion = PROFESSIONAL_MODEL_CONTRACT_VERSION
    check_id: str
    sheet: str
    cell: str

    @field_validator("check_id", "sheet")
    @classmethod
    def _required_text(cls, value: str, info) -> str:
        return _require_text(value, info.field_name)

    @field_validator("cell")
    @classmethod
    def _cell(cls, value: str) -> str:
        return _normalize_a1(value)


class WorkbookManifest(CanonicalContract):
    workbook_schema_version: ContractVersion = PROFESSIONAL_MODEL_CONTRACT_VERSION
    ticker: str
    source_hash: str
    model_input_hash: str
    result_hash: str
    sheet_order: tuple[str, ...]
    line_cell_mappings: tuple[LineCellMapping, ...]
    cell_classifications: tuple[CellClassification, ...]
    defined_names: tuple[DefinedNameMapping, ...]
    check_cells: tuple[WorkbookCheckCell, ...]
    renderer_version: str
    recalculation_state: AvailabilityState
    parity_results: tuple[CheckResult, ...]
    calculation_verification: CalculationVerificationRecord | None = None
    expected_formula_text_hash: str | None = None
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    manifest_hash: str | None = None

    @field_validator("ticker")
    @classmethod
    def _ticker(cls, value: str) -> str:
        return _require_text(value, "ticker").upper()

    @field_validator("source_hash", "model_input_hash", "result_hash")
    @classmethod
    def _hashes(cls, value: str, info) -> str:
        return _validate_sha256(value, info.field_name)

    @field_validator("expected_formula_text_hash")
    @classmethod
    def _expected_formula_hash(cls, value: str | None) -> str | None:
        return (
            _validate_sha256(value, "expected_formula_text_hash")
            if value is not None
            else None
        )

    @field_validator("renderer_version")
    @classmethod
    def _renderer(cls, value: str) -> str:
        return _require_text(value, "renderer_version")

    @model_validator(mode="after")
    def _validate_and_hash(self) -> "WorkbookManifest":
        if self.sheet_order != PROFESSIONAL_WORKBOOK_SHEETS:
            raise ValueError("sheet_order must match the canonical professional workbook order")
        sheets = set(self.sheet_order)
        referenced_sheets = {
            *(item.sheet for item in self.line_cell_mappings),
            *(item.sheet for item in self.cell_classifications),
            *(item.sheet for item in self.defined_names),
            *(item.sheet for item in self.check_cells),
        }
        unknown_sheets = sorted(referenced_sheets - sheets)
        if unknown_sheets:
            raise ValueError(f"workbook mappings reference unknown sheets: {unknown_sheets}")

        line_ids = [(item.canonical_key, item.scenario_key, item.period_key) for item in self.line_cell_mappings]
        cell_ids = [(item.sheet, item.cell) for item in self.cell_classifications]
        names = [item.name for item in self.defined_names]
        check_ids = [item.check_id for item in self.check_cells]
        check_cells = [(item.sheet, item.cell) for item in self.check_cells]
        parity_ids = [item.check_id for item in self.parity_results]
        if len(set(line_ids)) != len(line_ids):
            raise ValueError("duplicate line-to-cell mappings")
        if len(set(cell_ids)) != len(cell_ids):
            raise ValueError("duplicate cell classifications")
        if len(set(names)) != len(names):
            raise ValueError("duplicate defined names")
        if len(set(check_ids)) != len(check_ids) or len(set(check_cells)) != len(check_cells):
            raise ValueError("duplicate workbook check registry entries")
        if len(set(parity_ids)) != len(parity_ids):
            raise ValueError("duplicate workbook parity checks")
        if self.calculation_verification is not None and (
            self.calculation_verification.model_input_hash != self.model_input_hash
        ):
            raise ValueError("calculation verification model-input hash mismatch")
        if self.calculation_verification is not None and (
            self.expected_formula_text_hash
            != self.calculation_verification.expected_formula_text_hash
        ):
            raise ValueError("calculation verification formula baseline mismatch")
        if self.recalculation_state.status is AvailabilityStatus.AVAILABLE:
            if (
                self.blockers
                or not self.parity_results
                or any(item.status is not CheckStatus.PASS for item in self.parity_results)
                or self.expected_formula_text_hash is None
                or self.calculation_verification is None
                or self.calculation_verification.verification_state
                is not WorkflowState.FULL
            ):
                raise ValueError(
                    "verified workbook availability requires positive parity PASS "
                    "and FULL calculation verification"
                )
        elif self.recalculation_state.status is AvailabilityStatus.BLOCKING and not self.blockers:
            raise ValueError("blocking workbook manifest requires blockers")

        sheet_index = {sheet: index for index, sheet in enumerate(self.sheet_order)}
        object.__setattr__(
            self,
            "line_cell_mappings",
            tuple(sorted(self.line_cell_mappings, key=lambda item: (item.canonical_key, item.scenario_key, item.period_key))),
        )
        object.__setattr__(
            self,
            "cell_classifications",
            tuple(sorted(self.cell_classifications, key=lambda item: (sheet_index[item.sheet], item.cell))),
        )
        object.__setattr__(self, "defined_names", tuple(sorted(self.defined_names, key=lambda item: item.name)))
        object.__setattr__(self, "check_cells", tuple(sorted(self.check_cells, key=lambda item: item.check_id)))
        object.__setattr__(self, "parity_results", tuple(sorted(self.parity_results, key=lambda item: item.check_id)))
        object.__setattr__(self, "warnings", tuple(sorted(set(self.warnings))))
        object.__setattr__(self, "blockers", tuple(sorted(set(self.blockers))))
        self._bind_hash("manifest_hash")
        return self


__all__ = [
    "AvailabilityState",
    "AvailabilityStatus",
    "BridgeItem",
    "CanonicalContract",
    "CellClassification",
    "CellKind",
    "CheckResult",
    "CheckStatus",
    "DefinedNameMapping",
    "DriverYearValue",
    "EstimateStatus",
    "FactFormulaStatus",
    "InputValue",
    "LineCellMapping",
    "LineItemSpec",
    "LineSeries",
    "ModelInputSnapshot",
    "ModelPeriod",
    "ModelResult",
    "NormalizedActual",
    "PeriodAxis",
    "PeriodType",
    "PeriodValue",
    "PROFESSIONAL_MODEL_CONTRACT_VERSION",
    "PROFESSIONAL_WORKBOOK_SHEETS",
    "ScenarioDriverPath",
    "ScenarioInputSet",
    "ScheduleResult",
    "SensitivityResult",
    "SourceFact",
    "SourceManifest",
    "StatementResult",
    "SupplementalInputFact",
    "SupplementalInputSnapshot",
    "UnitKind",
    "ValuationBundle",
    "ValuationMethod",
    "ValuationMethodResult",
    "WACCMethodResult",
    "WorkbookCheckCell",
    "WorkbookManifest",
    "WorkbookSourceIdentity",
    "CalculationVerificationRecord",
    "DecisionEligibility",
    "DependencyScope",
    "DriverApprovalRecord",
    "DriverApprovalState",
    "DriverGroup",
    "MethodAvailability",
    "MethodDecisionStatus",
    "ModuleBlocker",
    "ModuleDependency",
    "ModuleWorkflow",
    "PackageWorkflowAggregation",
    "SourcePresentationRecord",
    "WorkflowAggregation",
    "WorkflowGate",
    "WorkflowState",
    "aggregate_package_workflow",
    "aggregate_workflow_state",
    "ConsensusMappingMethod",
    "ConsensusObservation",
    "ConsensusPeriodType",
    "ConsensusSnapshot",
    "ConsensusStatistic",
    "CurrentFullyDilutedSharesEvidence",
    "DCFDiscountPeriodEvidence",
    "DCFParameterGovernance",
    "DCFParameterName",
    "DCFParameterScope",
    "DCFScenarioGovernance",
    "DCFStubBridge",
    "WACCMethodologyEvidence",
    "WACCParityEvidence",
]
