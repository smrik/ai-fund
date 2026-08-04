"""Explicit CIQ-to-canonical unit mappings for valuation-reachable inputs."""

from __future__ import annotations

from typing import Any

from src.stage_00_data.unit_contract import (
    CanonicalUnit,
    UnitContractError,
    normalize_source_value,
)


_CIQ_VALUATION_FIELDS: dict[str, tuple[str, CanonicalUnit, str, float]] = {
    "revenue_mm": ("revenue", CanonicalUnit.USD, "USD", 1_000_000.0),
    "operating_income_mm": (
        "operating_income",
        CanonicalUnit.USD,
        "USD",
        1_000_000.0,
    ),
    "capex_mm": ("capex", CanonicalUnit.USD, "USD", 1_000_000.0),
    "da_mm": ("da", CanonicalUnit.USD, "USD", 1_000_000.0),
    "total_debt_mm": ("total_debt", CanonicalUnit.USD, "USD", 1_000_000.0),
    "cash_mm": ("cash", CanonicalUnit.USD, "USD", 1_000_000.0),
    "shares_out_mm": (
        "diluted_shares",
        CanonicalUnit.SHARES,
        "shares",
        1_000_000.0,
    ),
    "ebit_margin": ("ebit_margin", CanonicalUnit.DECIMAL, "decimal", 1.0),
    "op_margin_avg_3yr": (
        "op_margin_avg_3yr",
        CanonicalUnit.DECIMAL,
        "decimal",
        1.0,
    ),
    "capex_pct_avg_3yr": (
        "capex_pct_avg_3yr",
        CanonicalUnit.DECIMAL,
        "decimal",
        1.0,
    ),
    "da_pct_avg_3yr": (
        "da_pct_avg_3yr",
        CanonicalUnit.DECIMAL,
        "decimal",
        1.0,
    ),
    "effective_tax_rate": (
        "effective_tax_rate",
        CanonicalUnit.DECIMAL,
        "decimal",
        1.0,
    ),
    "effective_tax_rate_avg": (
        "effective_tax_rate_avg",
        CanonicalUnit.DECIMAL,
        "decimal",
        1.0,
    ),
    "revenue_cagr_3yr": (
        "revenue_cagr_3yr",
        CanonicalUnit.DECIMAL,
        "decimal",
        1.0,
    ),
    "roic": ("roic", CanonicalUnit.DECIMAL, "decimal", 1.0),
    "fcf_yield": ("fcf_yield", CanonicalUnit.DECIMAL, "decimal", 1.0),
    "debt_to_ebitda": (
        "debt_to_ebitda",
        CanonicalUnit.MULTIPLE,
        "multiple",
        1.0,
    ),
}


def canonicalize_ciq_valuation_snapshot(
    snapshot: dict[str, Any],
) -> list[dict[str, Any]]:
    """Project one legacy CIQ snapshot row into canonical Step 1 facts."""
    ticker = str(snapshot.get("ticker") or "").strip().upper()
    as_of_date = str(snapshot.get("as_of_date") or "").strip()
    run_id = snapshot.get("run_id")
    if not ticker:
        raise UnitContractError("unit_contract.ticker_missing")
    if not as_of_date:
        raise UnitContractError("unit_contract.as_of_date_missing")
    if run_id is None:
        raise UnitContractError("unit_contract.source_snapshot_missing")

    source_snapshot_id = f"ciq:{int(run_id)}"
    recorded_at = str(snapshot.get("pulled_at") or as_of_date)
    facts: list[dict[str, Any]] = []
    for raw_field, (
        metric_key,
        canonical_unit,
        raw_unit,
        raw_scale,
    ) in _CIQ_VALUATION_FIELDS.items():
        raw_value = snapshot.get(raw_field)
        if raw_value is None:
            continue
        source_ref = (
            f"ciq_valuation_snapshot:{ticker}:{as_of_date}:{raw_field}"
        )
        normalized = normalize_source_value(
            value=float(raw_value),
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
                "period_date": as_of_date,
                "source": "ciq_valuation_snapshot",
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
    return facts
