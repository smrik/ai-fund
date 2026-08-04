"""Explicit CIQ-to-canonical unit mappings for valuation-reachable inputs."""

from __future__ import annotations

from dataclasses import dataclass
import re
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


@dataclass(frozen=True, slots=True)
class CIQUnitSpec:
    canonical_unit: CanonicalUnit
    raw_unit: str
    raw_scale: float


_COMPS_AMOUNT_KEYS = {
    "cash",
    "debt",
    "market_cap",
    "minority_int",
    "pref_stock",
    "tev",
}
_COMPS_SHARE_KEYS = {"shares_out"}
_COMPS_PRICE_KEYS = {"52w_high", "52w_low", "stock_price"}
_COMPS_DECIMAL_KEYS = {
    "of_52w_high",
    "of_52w_low",
}
_COMPS_PERCENTAGE_POINT_KEYS = {
    "ebitda_fy__2",
    "ebitda_ltm__2",
    "eps_fy",
    "eps_ltm",
    "total_debt_total_cap",
    "total_debt_total_equity",
    "total_revenue_fy__2",
    "total_revenue_ltm__2",
}
_COMPS_DAY_KEYS = {
    "avg_cash_conv_cycle",
    "avg_days_inv_out",
    "avg_days_payable_out",
    "avg_days_sales_out",
}
_COMPS_MULTIPLE_KEYS = {
    "avg_a_r",
    "avg_fixed_assets",
    "avg_inventory",
    "avg_total_assets",
    "current_ratio",
    "debt_pref_ltm_ebitda",
    "ebitda_capex_interest",
    "ebitda_interest",
    "net_debt_ltm_ebitda",
    "price_bv",
    "price_tangible_bv",
    "quick_ratio",
    "total_debt_ltm_ebitda",
    "total_debt_roa",
    "total_debt_roe",
    "total_debt_roic",
}
_COMPS_AMOUNT_PATTERN = re.compile(
    r"^(?:ebitda|ebit|total_revenue|revenue)_(?:ltm|fy|cy_1|cy_2)$"
)
_COMPS_EPS_PATTERN = re.compile(r"^diluted_eps_(?:ltm|fy|cy_1|cy_2)$")
_COMPS_PERCENTAGE_POINT_PATTERN = re.compile(
    r"^(?:ebitda|eps|total_revenue)_(?:3|5)_yr_cagr$"
    r"|^(?:gross_margin|net_income_margin)_"
)
_COMPS_MULTIPLE_PATTERN = re.compile(r"^(?:pe_|tev_|price_)")


def ciq_comps_unit_spec(metric_key: str) -> CIQUnitSpec:
    """Return the explicit native and canonical unit for a numeric comps metric."""
    key = str(metric_key or "").strip().lower()
    if key in _COMPS_AMOUNT_KEYS or _COMPS_AMOUNT_PATTERN.match(key):
        return CIQUnitSpec(CanonicalUnit.USD, "USD", 1_000_000.0)
    if key in _COMPS_SHARE_KEYS:
        return CIQUnitSpec(CanonicalUnit.SHARES, "shares", 1_000_000.0)
    if key in _COMPS_PRICE_KEYS or _COMPS_EPS_PATTERN.match(key):
        return CIQUnitSpec(CanonicalUnit.USD_PER_SHARE, "USD/share", 1.0)
    if key in _COMPS_DECIMAL_KEYS:
        return CIQUnitSpec(CanonicalUnit.DECIMAL, "decimal", 1.0)
    if (
        key in _COMPS_PERCENTAGE_POINT_KEYS
        or _COMPS_PERCENTAGE_POINT_PATTERN.match(key)
    ):
        return CIQUnitSpec(CanonicalUnit.DECIMAL, "%", 0.01)
    if key in _COMPS_DAY_KEYS:
        return CIQUnitSpec(CanonicalUnit.DAYS, "days", 1.0)
    if key in _COMPS_MULTIPLE_KEYS or _COMPS_MULTIPLE_PATTERN.match(key):
        return CIQUnitSpec(CanonicalUnit.MULTIPLE, "multiple", 1.0)
    raise UnitContractError(f"unit_contract.comps_metric_unmapped:{key}")


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


def canonicalize_ciq_comps_snapshot(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Project typed CIQ peer rows into canonical Step 1 facts."""
    facts: list[dict[str, Any]] = []
    for row in rows:
        raw_value = row.get("value_num")
        if raw_value is None:
            continue
        ticker = str(row.get("target_ticker") or "").strip().upper()
        peer_ticker = str(row.get("peer_ticker") or "").strip().upper()
        as_of_date = str(row.get("as_of_date") or "").strip()
        metric_key = str(row.get("metric_key") or "").strip().lower()
        run_id = row.get("run_id")
        if not ticker or not peer_ticker:
            raise UnitContractError("unit_contract.ticker_missing")
        if not as_of_date:
            raise UnitContractError("unit_contract.as_of_date_missing")
        if run_id is None:
            raise UnitContractError("unit_contract.source_snapshot_missing")

        spec = ciq_comps_unit_spec(metric_key)
        source_ref = (
            f"ciq_comps_snapshot:{ticker}:{peer_ticker}:{as_of_date}:{metric_key}"
        )
        normalized = normalize_source_value(
            value=float(raw_value),
            raw_unit=row.get("unit"),
            raw_scale=float(row.get("scale_factor") or 0.0),
            canonical_unit=spec.canonical_unit,
            source_ref=source_ref,
        )
        if normalized.raw_unit != spec.raw_unit or normalized.raw_scale != spec.raw_scale:
            raise UnitContractError("unit_contract.comps_unit_spec_mismatch")
        facts.append(
            {
                "ticker": ticker,
                "subject_key": peer_ticker,
                "as_of_date": as_of_date,
                "period_date": as_of_date,
                "source": "ciq_comps_snapshot",
                "source_snapshot_id": f"ciq:{int(run_id)}",
                "metric_key": metric_key,
                "canonical_value": normalized.value,
                "canonical_unit": normalized.unit.value,
                "raw_value": normalized.raw_value,
                "raw_unit": normalized.raw_unit,
                "raw_scale": normalized.raw_scale,
                "source_ref": source_ref,
                "recorded_at": str(
                    row.get("recorded_at") or row.get("pulled_at") or as_of_date
                ),
            }
        )
    return facts
