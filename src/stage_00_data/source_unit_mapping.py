"""Canonical projections for non-CIQ valuation input caches."""

from __future__ import annotations

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
