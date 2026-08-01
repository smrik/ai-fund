"""Immutable semantic snapshot consumed by valuation judgment and replay."""

from __future__ import annotations

from typing import Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    computed_field,
    field_validator,
    model_validator,
)

from src.contracts.judgment_runs import canonical_semantic_hash


ANALYSIS_SNAPSHOT_CONTRACT_VERSION = "1.0.0"


class FrozenDict(dict):
    """JSON-compatible mapping that rejects mutation after construction."""

    def _immutable(self, *args: object, **kwargs: object) -> None:
        raise TypeError("analysis snapshot mappings are immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    __ior__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable


class FrozenList(list):
    """JSON-compatible sequence that rejects mutation after construction."""

    def _immutable(self, *args: object, **kwargs: object) -> None:
        raise TypeError("analysis snapshot sequences are immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    __iadd__ = _immutable
    __imul__ = _immutable
    append = _immutable
    clear = _immutable
    extend = _immutable
    insert = _immutable
    pop = _immutable
    remove = _immutable
    reverse = _immutable
    sort = _immutable


def _deep_freeze(value: JsonValue) -> JsonValue:
    if isinstance(value, dict):
        return FrozenDict(
            {
                str(key): _deep_freeze(item)
                for key, item in value.items()
            }
        )
    if isinstance(value, list):
        return FrozenList(_deep_freeze(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_deep_freeze(item) for item in value)  # type: ignore[return-value]
    return value


class AnalysisSnapshot(BaseModel):
    model_config = ConfigDict(
        allow_inf_nan=False,
        extra="forbid",
        frozen=True,
    )

    contract_version: str = ANALYSIS_SNAPSHOT_CONTRACT_VERSION
    ticker: str
    as_of_date: str
    identity: dict[str, JsonValue]
    statements: dict[str, JsonValue]
    statement_reconciliation: dict[str, JsonValue]
    claim_ledger: dict[str, JsonValue]
    market_inputs: dict[str, JsonValue]
    wacc_inputs: dict[str, JsonValue]
    comps_inputs: dict[str, JsonValue]
    approved_treatments: tuple[dict[str, JsonValue], ...] = ()
    evidence: dict[str, JsonValue]
    upstream_context: dict[str, JsonValue]
    source_fingerprints: dict[str, str] = Field(min_length=1)
    component_versions: dict[str, str] = Field(min_length=1)
    captured_at: str

    @field_validator(
        "contract_version",
        "ticker",
        "as_of_date",
        "captured_at",
    )
    @classmethod
    def _require_text(cls, value: str) -> str:
        cleaned = str(value).strip()
        if not cleaned:
            raise ValueError("identity fields must not be empty")
        return cleaned

    @field_validator("ticker")
    @classmethod
    def _uppercase_ticker(cls, value: str) -> str:
        return value.upper()

    @field_validator("source_fingerprints", "component_versions")
    @classmethod
    def _require_non_empty_mapping_values(
        cls,
        values: dict[str, str],
    ) -> dict[str, str]:
        cleaned = {
            str(key).strip(): str(value).strip()
            for key, value in values.items()
        }
        if any(not key or not value for key, value in cleaned.items()):
            raise ValueError("fingerprint/version mappings cannot contain blanks")
        return cleaned

    @model_validator(mode="after")
    def _freeze_nested_payloads(self) -> "AnalysisSnapshot":
        for field_name in (
            "identity",
            "statements",
            "statement_reconciliation",
            "claim_ledger",
            "market_inputs",
            "wacc_inputs",
            "comps_inputs",
            "approved_treatments",
            "evidence",
            "upstream_context",
            "source_fingerprints",
            "component_versions",
        ):
            object.__setattr__(
                self,
                field_name,
                _deep_freeze(getattr(self, field_name)),
            )
        return self

    def semantic_payload(self) -> dict[str, JsonValue]:
        return self.model_dump(
            mode="json",
            exclude={"captured_at", "snapshot_hash"},
            exclude_computed_fields=True,
        )

    def model_copy(
        self,
        *,
        update: dict[str, object] | None = None,
        deep: bool = False,
    ) -> Self:
        """Return a revalidated copy so nested updates remain immutable."""

        payload = self.model_dump(
            mode="python",
            exclude_computed_fields=True,
        )
        payload.update(update or {})
        return type(self).model_validate(payload)

    @computed_field
    @property
    def snapshot_hash(self) -> str:
        return canonical_semantic_hash(self.semantic_payload())
