from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


TICKER_DOSSIER_CONTRACT_NAME = "TickerDossier"
TICKER_DOSSIER_CONTRACT_VERSION = "1.0.0"


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class CompanyIdentity(ContractModel):
    ticker: str
    display_name: str
    sector: str | None = None
    industry: str | None = None
    exchange: str | None = None


class MarketSnapshot(ContractModel):
    as_of_date: str
    price: float | None = None
    market_cap: float | None = None
    enterprise_value: float | None = None
    beta: float | None = None
    analyst_target: float | None = None
    analyst_recommendation: str | None = None
    num_analysts: int | None = None


class ValuationSnapshot(ContractModel):
    bear_iv: float | None = None
    base_iv: float | None = None
    bull_iv: float | None = None
    expected_iv: float | None = None
    current_price: float | None = None
    upside_pct: float | None = None
    scenario_probabilities: dict[str, float | None] = Field(default_factory=dict)


class HistoricalSeries(ContractModel):
    revenue: list[dict[str, Any]] = Field(default_factory=list)
    ebit: list[dict[str, Any]] = Field(default_factory=list)
    fcff: list[dict[str, Any]] = Field(default_factory=list)
    margin: list[dict[str, Any]] = Field(default_factory=list)


class QoeSnapshot(ContractModel):
    present: bool = False
    score: float | None = None
    flags: list[str] = Field(default_factory=list)


class CompsSnapshot(ContractModel):
    peer_count: int | None = None
    primary_metric: str | None = None
    median_multiple: float | None = None
    valuation_range: dict[str, Any] = Field(default_factory=dict)
    audit_flags: list[str] = Field(default_factory=list)


class LatestSnapshot(ContractModel):
    company_identity: CompanyIdentity
    market_snapshot: MarketSnapshot
    valuation_snapshot: ValuationSnapshot
    historical_series: HistoricalSeries = Field(default_factory=HistoricalSeries)
    qoe_snapshot: QoeSnapshot = Field(default_factory=QoeSnapshot)
    comps_snapshot: CompsSnapshot = Field(default_factory=CompsSnapshot)
    source_lineage: dict[str, Any] = Field(default_factory=dict)


class BackendValidation(ContractModel):
    passed: bool = True
    warnings: list[str] = Field(default_factory=list)
    missing_required_fields: list[str] = Field(default_factory=list)


class LoadedBackendState(ContractModel):
    backend_name: str
    backend_version: str = "1.0.0"
    loaded_from: str | None = None
    loaded_at: str | None = None
    source_format: str = "json"
    source_mode: str
    normalization_mode: str = "canonical"
    validation: BackendValidation = Field(default_factory=BackendValidation)
    field_mappings: dict[str, str] = Field(default_factory=dict)
    adapter_state: dict[str, bool] = Field(default_factory=dict)


class ExportMetadata(ContractModel):
    source_mode: str
    generated_at: str | None = None
    schema_version: str | None = None
    snapshot_id: int | None = None
    source_label: str | None = None
    template_strategy: str | None = None


class TickerDossier(ContractModel):
    contract_name: Literal["TickerDossier"] = TICKER_DOSSIER_CONTRACT_NAME
    contract_version: str = TICKER_DOSSIER_CONTRACT_VERSION
    ticker: str
    as_of_date: str
    display_name: str
    currency: str = "USD"
    latest_snapshot: LatestSnapshot
    loaded_backend_state: LoadedBackendState
    source_lineage: dict[str, Any] = Field(default_factory=dict)
    export_metadata: ExportMetadata
    optional_overlays: dict[str, Any] = Field(default_factory=dict)
