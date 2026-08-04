"""Canonical projections for non-CIQ valuation input caches."""

from __future__ import annotations

import json
from typing import Any

from src.stage_00_data.unit_contract import (
    CanonicalUnit,
    UnitContractError,
    normalize_source_value,
)


_Spec = tuple[CanonicalUnit, str, float]

_MARKET_DATA_SPECS: dict[str, _Spec] = {
    "current_price": (CanonicalUnit.USD_PER_SHARE, "USD/share", 1.0),
    "market_cap": (CanonicalUnit.USD, "USD", 1.0),
    "enterprise_value": (CanonicalUnit.USD, "USD", 1.0),
    "revenue_ttm": (CanonicalUnit.USD, "USD", 1.0),
    "ebitda_ttm": (CanonicalUnit.USD, "USD", 1.0),
    "free_cashflow": (CanonicalUnit.USD, "USD", 1.0),
    "total_debt": (CanonicalUnit.USD, "USD", 1.0),
    "cash": (CanonicalUnit.USD, "USD", 1.0),
    "gross_margin": (CanonicalUnit.DECIMAL, "decimal", 1.0),
    "operating_margin": (CanonicalUnit.DECIMAL, "decimal", 1.0),
    "profit_margin": (CanonicalUnit.DECIMAL, "decimal", 1.0),
    "revenue_growth": (CanonicalUnit.DECIMAL, "decimal", 1.0),
    "earnings_growth": (CanonicalUnit.DECIMAL, "decimal", 1.0),
    "shares_outstanding": (CanonicalUnit.SHARES, "shares", 1.0),
    "52w_high": (CanonicalUnit.USD_PER_SHARE, "USD/share", 1.0),
    "52w_low": (CanonicalUnit.USD_PER_SHARE, "USD/share", 1.0),
    "analyst_target_mean": (CanonicalUnit.USD_PER_SHARE, "USD/share", 1.0),
    "analyst_target_low": (CanonicalUnit.USD_PER_SHARE, "USD/share", 1.0),
    "analyst_target_high": (CanonicalUnit.USD_PER_SHARE, "USD/share", 1.0),
    "pe_trailing": (CanonicalUnit.MULTIPLE, "multiple", 1.0),
    "pe_forward": (CanonicalUnit.MULTIPLE, "multiple", 1.0),
    "ev_ebitda": (CanonicalUnit.MULTIPLE, "multiple", 1.0),
    "ev_revenue": (CanonicalUnit.MULTIPLE, "multiple", 1.0),
    "price_to_book": (CanonicalUnit.MULTIPLE, "multiple", 1.0),
    "price_to_sales": (CanonicalUnit.MULTIPLE, "multiple", 1.0),
    "beta": (CanonicalUnit.MULTIPLE, "multiple", 1.0),
    "short_ratio": (CanonicalUnit.DAYS, "days", 1.0),
}

_HISTORICAL_FINANCIAL_SPECS: dict[str, _Spec] = {
    "revenue_cagr_3yr": (CanonicalUnit.DECIMAL, "decimal", 1.0),
    "op_margin_avg_3yr": (CanonicalUnit.DECIMAL, "decimal", 1.0),
    "capex_pct_avg_3yr": (CanonicalUnit.DECIMAL, "decimal", 1.0),
    "da_pct_avg_3yr": (CanonicalUnit.DECIMAL, "decimal", 1.0),
    "nwc_pct_avg_3yr": (CanonicalUnit.DECIMAL, "decimal", 1.0),
    "effective_tax_rate_avg": (CanonicalUnit.DECIMAL, "decimal", 1.0),
    "cost_of_debt_derived": (CanonicalUnit.DECIMAL, "decimal", 1.0),
    "cogs_pct_of_revenue": (CanonicalUnit.DECIMAL, "decimal", 1.0),
    "dso_derived": (CanonicalUnit.DAYS, "days", 1.0),
    "dio_derived": (CanonicalUnit.DAYS, "days", 1.0),
    "dpo_derived": (CanonicalUnit.DAYS, "days", 1.0),
    "minority_interest_bs": (CanonicalUnit.USD, "USD", 1.0),
    "preferred_equity_bs": (CanonicalUnit.USD, "USD", 1.0),
    "lease_liabilities_bs": (CanonicalUnit.USD, "USD", 1.0),
    "sbc": (CanonicalUnit.USD, "USD", 1.0),
    "invested_capital_derived": (CanonicalUnit.USD, "USD", 1.0),
    "diluted_shares": (CanonicalUnit.SHARES, "shares", 1.0),
}

_MARKET_CACHE_SPECS = {
    "market_data": _MARKET_DATA_SPECS,
    "historical_financials": _HISTORICAL_FINANCIAL_SPECS,
}

_MACRO_PERCENT_SERIES = {
    "DGS1MO",
    "DGS3MO",
    "DGS6MO",
    "DGS1",
    "DGS2",
    "DGS5",
    "DGS10",
    "DGS20",
    "DGS30",
    "T10Y2Y",
    "FEDFUNDS",
    "BAMLC0A4CBBB",
    "BAMLH0A0HYM2",
    "UNRATE",
}
_MACRO_INDEX_SERIES = {"VIXCLS", "CPIAUCSL", "INDPRO"}
_MACRO_COUNT_SERIES = {"ICSA"}
_MACRO_USD_MILLIONS_SERIES = {"RSAFS"}


def macro_series_unit_spec(series_id: str) -> _Spec:
    """Return the declared FRED native unit and canonical unit for a series."""
    normalized_id = str(series_id or "").strip().upper()
    if normalized_id in _MACRO_PERCENT_SERIES:
        return CanonicalUnit.DECIMAL, "%", 0.01
    if normalized_id in _MACRO_INDEX_SERIES:
        return CanonicalUnit.INDEX, "index", 1.0
    if normalized_id in _MACRO_COUNT_SERIES:
        return CanonicalUnit.COUNT, "number", 1.0
    if normalized_id in _MACRO_USD_MILLIONS_SERIES:
        return CanonicalUnit.USD, "USD", 1_000_000.0
    raise UnitContractError(
        f"unit_contract.macro_series_unmapped:{normalized_id}"
    )


def canonicalize_macro_observation(
    *,
    series_id: str,
    series_date: str,
    value: float,
    fetched_at: str,
) -> dict[str, Any]:
    """Project one FRED native observation into a canonical global fact."""
    normalized_id = str(series_id or "").strip().upper()
    canonical_unit, raw_unit, raw_scale = macro_series_unit_spec(normalized_id)
    source_ref = f"macro_series:{normalized_id}:{series_date}"
    normalized = normalize_source_value(
        value=value,
        raw_unit=raw_unit,
        raw_scale=raw_scale,
        canonical_unit=canonical_unit,
        source_ref=source_ref,
    )
    return {
        "ticker": "__GLOBAL__",
        "subject_key": normalized_id,
        "as_of_date": series_date,
        "period_date": series_date,
        "source": "macro_series",
        "source_snapshot_id": f"fred:{normalized_id}:{fetched_at}",
        "metric_key": normalized_id.lower(),
        "canonical_value": normalized.value,
        "canonical_unit": normalized.unit.value,
        "raw_value": normalized.raw_value,
        "raw_unit": normalized.raw_unit,
        "raw_scale": normalized.raw_scale,
        "source_ref": source_ref,
        "recorded_at": fetched_at,
    }


_SEC_SCALAR_SPECS: dict[str, _Spec] = {
    "revenue_cagr_3y": (CanonicalUnit.DECIMAL, "decimal", 1.0),
    "ebit_margin_avg_3y": (CanonicalUnit.DECIMAL, "decimal", 1.0),
    "gross_margin_avg_3y": (CanonicalUnit.DECIMAL, "decimal", 1.0),
    "fcf_yield": (CanonicalUnit.DECIMAL, "decimal", 1.0),
    "net_debt_to_ebitda": (CanonicalUnit.MULTIPLE, "multiple", 1.0),
}

_NON_QUANTITATIVE_STATEMENT_CONCEPTS = {
    "financial_accounting_standard",
}


def canonicalize_sec_filing_metrics_snapshot(
    row: dict[str, Any],
) -> list[dict[str, Any]]:
    """Project SEC metric scalars and reported series into canonical facts."""
    ticker = str(row.get("ticker") or "").strip().upper()
    as_of_date = str(row.get("as_of_date") or "").strip()
    metric_source = str(row.get("metric_source") or "").strip()
    recorded_at = str(row.get("pulled_at") or as_of_date)
    if not ticker:
        raise UnitContractError("unit_contract.ticker_missing")
    if not as_of_date:
        raise UnitContractError("unit_contract.as_of_date_missing")
    if not metric_source:
        raise UnitContractError("unit_contract.source_snapshot_missing")

    source_snapshot_id = f"sec:{metric_source}:{as_of_date}"
    facts: list[dict[str, Any]] = []

    def append_fact(
        *,
        metric_key: str,
        raw_value: float,
        period_date: str,
        canonical_unit: CanonicalUnit,
        raw_unit: str,
        raw_scale: float,
        source_ref: str,
    ) -> None:
        normalized = normalize_source_value(
            value=raw_value,
            raw_unit=raw_unit,
            raw_scale=raw_scale,
            canonical_unit=canonical_unit,
            source_ref=source_ref,
        )
        facts.append(
            {
                "ticker": ticker,
                "subject_key": ticker,
                "as_of_date": as_of_date,
                "period_date": period_date,
                "source": "sec_filing_metrics_snapshot",
                "source_snapshot_id": source_snapshot_id,
                "metric_key": metric_key,
                "canonical_value": normalized.value,
                "canonical_unit": normalized.unit.value,
                "raw_value": normalized.raw_value,
                "raw_unit": normalized.raw_unit,
                "raw_scale": normalized.raw_scale,
                "source_ref": source_ref,
                "recorded_at": recorded_at,
            }
        )

    for metric_key, (canonical_unit, raw_unit, raw_scale) in _SEC_SCALAR_SPECS.items():
        raw_value = row.get(metric_key)
        if raw_value is None:
            continue
        append_fact(
            metric_key=metric_key,
            raw_value=float(raw_value),
            period_date=as_of_date,
            canonical_unit=canonical_unit,
            raw_unit=raw_unit,
            raw_scale=raw_scale,
            source_ref=f"sec_filing_metrics_snapshot:{ticker}:{metric_key}",
        )

    series_specs = {
        "revenue_series_json": "revenue",
        "ebit_series_json": "operating_income",
    }
    for field_name, metric_key in series_specs.items():
        payload = row.get(field_name) or "[]"
        series = json.loads(payload) if isinstance(payload, str) else payload
        for item in series:
            period_date = str(item.get("period") or "").strip()
            raw_value = item.get("value")
            if not period_date or raw_value is None:
                raise UnitContractError("unit_contract.sec_series_invalid")
            append_fact(
                metric_key=metric_key,
                raw_value=float(raw_value),
                period_date=period_date,
                canonical_unit=CanonicalUnit.USD,
                raw_unit="USD",
                raw_scale=1.0,
                source_ref=(
                    f"sec_filing_metrics_snapshot:{ticker}:{metric_key}:{period_date}"
                ),
            )
    return facts


def canonicalize_statement_facts(
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Project numeric statement facts into canonical values at ingestion."""
    facts: list[dict[str, Any]] = []
    unit_specs: dict[str, _Spec] = {
        "usd": (CanonicalUnit.USD, "USD", 1.0),
        "shares": (CanonicalUnit.SHARES, "shares", 1.0),
        "%": (CanonicalUnit.DECIMAL, "%", 0.01),
        "usd/share": (CanonicalUnit.USD_PER_SHARE, "USD/share", 1.0),
        "months": (CanonicalUnit.MONTHS, "months", 1.0),
    }
    for record in records:
        raw_value = record.get("numeric_value")
        if raw_value is None:
            continue
        ticker = str(record.get("ticker") or "").strip().upper()
        source = str(record.get("source") or "").strip()
        concept = str(record.get("concept") or "").strip()
        if concept.casefold() in _NON_QUANTITATIVE_STATEMENT_CONCEPTS:
            continue
        period_date = str(
            record.get("period_end") or record.get("period_label") or ""
        ).strip()[:10]
        raw_unit_value = record.get("unit")
        raw_unit_key = str(raw_unit_value or "").strip().casefold()
        if not ticker:
            raise UnitContractError("unit_contract.ticker_missing")
        if not source or not concept:
            raise UnitContractError("unit_contract.statement_identity_missing")
        if not period_date:
            raise UnitContractError("unit_contract.statement_period_missing")
        if not raw_unit_key:
            raise UnitContractError("unit_contract.raw_unit_missing")
        spec = unit_specs.get(raw_unit_key)
        if spec is None:
            raise UnitContractError(
                f"unit_contract.statement_unit_unmapped:{raw_unit_key}"
            )
        canonical_unit, expected_raw_unit, fixed_scale = spec
        raw_scale = float(record.get("scale_factor") or 0.0)
        if canonical_unit in {CanonicalUnit.USD, CanonicalUnit.SHARES}:
            fixed_scale = raw_scale
        fact_id = str(record.get("fact_id") or "").strip()
        fingerprint = str(record.get("ingestion_fingerprint") or "").strip()
        if not fact_id or not fingerprint:
            raise UnitContractError("unit_contract.statement_identity_missing")
        source_ref = f"statement_fact:{fact_id}:{fingerprint}"
        normalized = normalize_source_value(
            value=float(raw_value),
            raw_unit=expected_raw_unit,
            raw_scale=fixed_scale,
            canonical_unit=canonical_unit,
            source_ref=source_ref,
        )
        source_identity = (
            record.get("source_run_id")
            or record.get("accession")
            or fingerprint
        )
        recorded_at = str(record.get("ingested_at") or period_date)
        as_of_date = str(
            record.get("filing_date") or recorded_at[:10] or period_date
        )[:10]
        facts.append(
            {
                "ticker": ticker,
                "subject_key": ticker,
                "as_of_date": as_of_date,
                "period_date": period_date,
                "source": f"statement_facts:{source}",
                "source_snapshot_id": f"{source}:{source_identity}",
                "metric_key": concept,
                "canonical_value": normalized.value,
                "canonical_unit": normalized.unit.value,
                "raw_value": normalized.raw_value,
                "raw_unit": normalized.raw_unit,
                "raw_scale": normalized.raw_scale,
                "source_ref": source_ref,
                "recorded_at": recorded_at,
            }
        )
    return facts


def canonicalize_market_cache(
    *,
    ticker: str,
    data_type: str,
    data: dict[str, Any],
    fetched_at: str,
) -> list[dict[str, Any]]:
    """Project valuation-reachable market cache fields into canonical facts."""
    normalized_ticker = str(ticker or "").strip().upper()
    if not normalized_ticker:
        raise UnitContractError("unit_contract.ticker_missing")
    specs = _MARKET_CACHE_SPECS.get(data_type)
    if specs is None:
        raise UnitContractError(
            f"unit_contract.market_cache_type_unmapped:{data_type}"
        )
    as_of_date = str(fetched_at)[:10]
    source_snapshot_id = f"market_cache:{data_type}:{fetched_at}"
    facts: list[dict[str, Any]] = []
    for metric_key, (canonical_unit, raw_unit, raw_scale) in specs.items():
        raw_value = data.get(metric_key)
        if raw_value is None:
            continue
        source_ref = f"market_data_cache:{normalized_ticker}:{data_type}:{metric_key}"
        normalized = normalize_source_value(
            value=float(raw_value),
            raw_unit=raw_unit,
            raw_scale=raw_scale,
            canonical_unit=canonical_unit,
            source_ref=source_ref,
        )
        facts.append(
            {
                "ticker": normalized_ticker,
                "subject_key": normalized_ticker,
                "as_of_date": as_of_date,
                "period_date": as_of_date,
                "source": f"market_data_cache:{data_type}",
                "source_snapshot_id": source_snapshot_id,
                "metric_key": metric_key,
                "canonical_value": normalized.value,
                "canonical_unit": normalized.unit.value,
                "raw_value": normalized.raw_value,
                "raw_unit": normalized.raw_unit,
                "raw_scale": normalized.raw_scale,
                "source_ref": source_ref,
                "recorded_at": fetched_at,
            }
        )
    return facts
