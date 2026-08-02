"""Deterministic valuation input assembly with source lineage and manual overrides."""
from __future__ import annotations

import functools
import math
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Mapping

import yaml

from config import ROOT_DIR
from src.contracts.assumption_registry import (
    AssumptionOwner,
    AssumptionUnit,
    get_assumption_definition,
)
from src.contracts.valuation_readiness import (
    ValuationReadinessEvidence,
    ValuationTrustStatus,
)
from src.stage_00_data import market_data as md_client
from src.stage_00_data.ciq_adapter import get_ciq_comps_detail, get_ciq_comps_valuation, get_ciq_snapshot
from src.stage_00_data.sec_filing_metrics import get_bridge_items_from_xbrl
from src.stage_02_valuation.claim_ledger import (
    ClaimAllocation,
    ClaimLedger,
    EV_BRIDGE_COMPONENTS,
    ReconciledEVBridge,
    ReportedLine,
)
from src.stage_02_valuation.operating_reconciliation import ClampEvent
from src.stage_02_valuation.public_comps_fallback import build_public_market_fallback_comps_detail
from src.stage_02_valuation.story_drivers import (
    apply_story_driver_adjustments,
    resolve_story_driver_profile,
    story_authority_for_source,
)
from src.stage_02_valuation.valuation_types import ForecastDrivers
from src.stage_02_valuation.wacc import (
    blend_wacc_results,
    compute_wacc_from_yfinance,
    compute_wacc_methodology_set_for_ticker,
)


OVERRIDES_PATH = ROOT_DIR / "config" / "valuation_overrides.yaml"
QOE_PENDING_PATH = ROOT_DIR / "config" / "qoe_pending.yaml"
OPERATING_CASH_REVENUE_RATE = 0.02


SECTOR_DEFAULTS = {
    "Technology": {"growth_near": 0.12, "margin": 0.20, "capex_pct": 0.06, "da_pct": 0.04, "dso": 45.0, "dio": 35.0, "dpo": 38.0, "exit_multiple": 16.0, "ic_turnover": 1.60, "ronic_terminal": 0.15, "growth_fade_ratio": 0.70, "terminal_growth": 0.035},
    "Communication Services": {"growth_near": 0.10, "margin": 0.18, "capex_pct": 0.05, "da_pct": 0.04, "dso": 50.0, "dio": 30.0, "dpo": 42.0, "exit_multiple": 14.0, "ic_turnover": 1.50, "ronic_terminal": 0.14, "growth_fade_ratio": 0.65, "terminal_growth": 0.030},
    "Healthcare": {"growth_near": 0.09, "margin": 0.18, "capex_pct": 0.05, "da_pct": 0.04, "dso": 52.0, "dio": 45.0, "dpo": 40.0, "exit_multiple": 14.0, "ic_turnover": 1.30, "ronic_terminal": 0.13, "growth_fade_ratio": 0.65, "terminal_growth": 0.030},
    "Consumer Cyclical": {"growth_near": 0.08, "margin": 0.14, "capex_pct": 0.05, "da_pct": 0.04, "dso": 42.0, "dio": 55.0, "dpo": 48.0, "exit_multiple": 12.0, "ic_turnover": 1.80, "ronic_terminal": 0.12, "growth_fade_ratio": 0.60, "terminal_growth": 0.025},
    "Consumer Defensive": {"growth_near": 0.06, "margin": 0.14, "capex_pct": 0.04, "da_pct": 0.03, "dso": 40.0, "dio": 58.0, "dpo": 50.0, "exit_multiple": 12.0, "ic_turnover": 2.00, "ronic_terminal": 0.11, "growth_fade_ratio": 0.55, "terminal_growth": 0.025},
    "Industrials": {"growth_near": 0.06, "margin": 0.13, "capex_pct": 0.06, "da_pct": 0.04, "dso": 55.0, "dio": 60.0, "dpo": 50.0, "exit_multiple": 11.0, "ic_turnover": 1.70, "ronic_terminal": 0.11, "growth_fade_ratio": 0.55, "terminal_growth": 0.025},
    "Energy": {"growth_near": 0.05, "margin": 0.12, "capex_pct": 0.08, "da_pct": 0.06, "dso": 38.0, "dio": 45.0, "dpo": 46.0, "exit_multiple": 9.0, "ic_turnover": 1.40, "ronic_terminal": 0.10, "growth_fade_ratio": 0.50, "terminal_growth": 0.020},
    "Basic Materials": {"growth_near": 0.05, "margin": 0.12, "capex_pct": 0.07, "da_pct": 0.05, "dso": 48.0, "dio": 65.0, "dpo": 52.0, "exit_multiple": 9.0, "ic_turnover": 1.30, "ronic_terminal": 0.10, "growth_fade_ratio": 0.50, "terminal_growth": 0.020},
    "Utilities": {"growth_near": 0.04, "margin": 0.15, "capex_pct": 0.09, "da_pct": 0.07, "dso": 42.0, "dio": 20.0, "dpo": 45.0, "exit_multiple": 10.0, "ic_turnover": 1.10, "ronic_terminal": 0.09, "growth_fade_ratio": 0.55, "terminal_growth": 0.025},
    "_default": {"growth_near": 0.06, "margin": 0.14, "capex_pct": 0.05, "da_pct": 0.04, "dso": 50.0, "dio": 50.0, "dpo": 45.0, "exit_multiple": 12.0, "ic_turnover": 1.50, "ronic_terminal": 0.11, "growth_fade_ratio": 0.65, "terminal_growth": 0.030},
}


EXIT_METRIC_BY_SECTOR = {
    "Technology": "ev_ebitda",
    "Communication Services": "ev_ebitda",
    "Healthcare": "ev_ebitda",
    "Consumer Cyclical": "ev_ebitda",
    "Consumer Defensive": "ev_ebitda",
    "Industrials": "ev_ebit",
    "Energy": "ev_ebit",
    "Basic Materials": "ev_ebit",
    "Utilities": "ev_ebit",
}


EXCLUDED_SECTORS = {"Financial Services", "Real Estate"}


# Historical values are observed facts, so their bounds are only plausibility
# envelopes.  The envelopes are keyed by the registry unit instead of by
# individual driver names; judgment-owned targets continue using their
# caller-supplied forecast bounds.
_HISTORICAL_SANITY_BOUNDS: dict[AssumptionUnit, tuple[float, float]] = {
    # Operating ratios are non-negative in this model.  A 10x ceiling leaves
    # room for extreme small-revenue issuers while still catching an absurd
    # ratio or sign/unit error.
    AssumptionUnit.decimal: (0.0, 10.0),
    # Zero days is valid for an asset-light issuer; two years is a deliberately
    # broad working-capital cycle, while still catching a 900-day data error.
    AssumptionUnit.days: (0.0, 730.0),
    # Raw-dollar capital can legitimately be negative (for example, negative
    # invested capital), so the universal money envelope permits both signs
    # and is intentionally far outside normal single-issuer scale.
    AssumptionUnit.money: (-1.0e18, 1.0e18),
}

# These are the only observed operating starts that the operating statement
# ledger can author. Forward and judgment-owned targets intentionally do not
# appear here.
_RECONCILED_OPERATING_START_BY_ROLE = {
    "revenue": "revenue_base",
    "accounts_receivable": "dso_start",
    "inventory": "dio_start",
    "accounts_payable": "dpo_start",
    "capex": "capex_pct_start",
    "da": "da_pct_start",
}


@dataclass(slots=True)
class ValuationInputsWithLineage:
    ticker: str
    company_name: str
    sector: str
    industry: str
    current_price: float
    as_of_date: str | None
    model_applicability_status: str
    drivers: ForecastDrivers
    source_lineage: dict[str, str]
    ciq_lineage: dict[str, Any]
    wacc_inputs: dict[str, Any]
    story_profile: dict[str, Any] | None = None
    story_adjustments: dict[str, Any] | None = None
    wacc_method_spread_high: bool = False
    clamp_events: tuple[ClampEvent, ...] = field(default_factory=tuple)
    default_resolution: dict[str, Any] = field(default_factory=dict)
    claim_ledger: dict[str, Any] = field(default_factory=dict)
    operating_cash_policy: dict[str, Any] = field(default_factory=dict)
    bridge_cutover: dict[str, Any] = field(default_factory=dict)
    valuation_readiness: dict[str, Any] = field(default_factory=dict)
    valuation_status: str = "provisional"


class BridgeMutationPathError(ValueError):
    """A raw scalar attempted to bypass the reconciled claim-ledger queue."""

    def __init__(self, fields: list[str] | set[str] | tuple[str, ...]) -> None:
        self.fields = tuple(sorted(set(fields)))
        super().__init__(
            "EV-bridge override does not tie to an approved reconciled "
            "claim-ledger reclassification pack; raw override fields were "
            "supplied: "
            + ", ".join(self.fields)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": "blocked",
            "reason_code": (
                "bridge_mutation_requires_reconciled_claim_ledger"
            ),
            "fields": list(self.fields),
            "message": str(self),
        }


def _mm(v: float | None) -> float | None:
    """Convert raw dollar value to millions."""
    return v / 1e6 if v is not None else None


def _bounds_for_field(
    field_name: str,
    low: float,
    high: float,
) -> tuple[float, float]:
    """Use broad sanity bounds for historical registry-owned observations."""
    try:
        definition = get_assumption_definition(field_name)
    except KeyError:
        return float(low), float(high)

    if definition.owner is not AssumptionOwner.historical:
        return float(low), float(high)
    return _HISTORICAL_SANITY_BOUNDS.get(
        definition.unit,
        (float(low), float(high)),
    )


def _bounded(
    value: float | None,
    low: float,
    high: float,
    default: float,
    *,
    field_name: str,
    source: str,
    events: list[ClampEvent],
) -> float:
    effective_low, effective_high = _bounds_for_field(field_name, low, high)
    resolved = (
        float(default)
        if value is None
        else max(effective_low, min(effective_high, float(value)))
    )
    events.append(
        ClampEvent(
            field_name=field_name,
            raw_value=None if value is None else float(value),
            resolved_value=resolved,
            lower_bound=effective_low,
            upper_bound=effective_high,
            default_value=float(default),
            source=source,
        )
    )
    return resolved


def apply_reconciled_operating_starts(
    valuation_inputs: ValuationInputsWithLineage,
    *,
    selected_amounts: Mapping[str, Any],
    inventory_applicable: bool,
) -> None:
    """Apply the existing selected statement roles to observed model starts.

    The operating reconciliation service owns statement selection. This seam
    only consumes that frozen selection; it never looks up CIQ or yfinance and
    never supplies a fallback when a role is absent.
    """

    required_roles = [
        "revenue",
        "cost_of_revenue",
        "accounts_receivable",
        "accounts_payable",
        "capex",
        "da",
    ]
    if inventory_applicable:
        required_roles.append("inventory")
    missing_roles = [
        role for role in required_roles if role not in selected_amounts
    ]
    if missing_roles:
        raise ValueError(
            "operating.reconciled_start_missing:"
            + ",".join(missing_roles)
        )
    for driver_name in _RECONCILED_OPERATING_START_BY_ROLE.values():
        if get_assumption_definition(driver_name).owner is not AssumptionOwner.historical:
            raise ValueError(
                "operating.reconciled_driver_not_historical:"
                + driver_name
            )

    unit_scale = float(
        (getattr(valuation_inputs, "claim_ledger", {}) or {}).get(
            "unit_scale"
        )
        or 0.0
    )
    if not math.isfinite(unit_scale) or unit_scale <= 0:
        raise ValueError("operating.valuation_unit_scale_invalid")

    def _base_value(role: str) -> float:
        amount = selected_amounts[role]
        try:
            value = abs(float(amount.base_value))
        except (AttributeError, TypeError, ValueError) as exc:
            raise ValueError(f"operating.{role}_invalid") from exc
        if not math.isfinite(value):
            raise ValueError(f"operating.{role}_invalid")
        if not str(getattr(amount, "fact_id", "")).strip():
            raise ValueError(f"operating.{role}_fact_id_missing")
        return value

    revenue = _base_value("revenue")
    cost_of_revenue = _base_value("cost_of_revenue")
    if revenue <= 0:
        raise ValueError("operating.reconciled_revenue_non_positive")
    if cost_of_revenue <= 0:
        raise ValueError(
            "operating.reconciled_cost_of_revenue_non_positive"
        )

    reconciled_values = {
        _RECONCILED_OPERATING_START_BY_ROLE["revenue"]: revenue / unit_scale,
        _RECONCILED_OPERATING_START_BY_ROLE["accounts_receivable"]: (
            _base_value("accounts_receivable") / revenue * 365.0
        ),
        _RECONCILED_OPERATING_START_BY_ROLE["accounts_payable"]: (
            _base_value("accounts_payable") / cost_of_revenue * 365.0
        ),
        _RECONCILED_OPERATING_START_BY_ROLE["capex"]: (
            _base_value("capex") / revenue
        ),
        _RECONCILED_OPERATING_START_BY_ROLE["da"]: (
            _base_value("da") / revenue
        ),
    }
    if inventory_applicable:
        reconciled_values[_RECONCILED_OPERATING_START_BY_ROLE["inventory"]] = (
            _base_value("inventory") / cost_of_revenue * 365.0
        )

    valuation_inputs.drivers = replace(
        valuation_inputs.drivers,
        **reconciled_values,
    )

    source_lineage = getattr(valuation_inputs, "source_lineage", None)
    if not isinstance(source_lineage, dict):
        source_lineage = {}
        valuation_inputs.source_lineage = source_lineage

    def _source_ref(*roles: str) -> str:
        return "reconciled_statement:" + ",".join(
            f"{role}={selected_amounts[role].fact_id}"
            for role in roles
        )

    source_lineage[_RECONCILED_OPERATING_START_BY_ROLE["revenue"]] = _source_ref(
        "revenue"
    )
    source_lineage[_RECONCILED_OPERATING_START_BY_ROLE["accounts_receivable"]] = _source_ref(
        "revenue", "accounts_receivable"
    )
    source_lineage[_RECONCILED_OPERATING_START_BY_ROLE["accounts_payable"]] = _source_ref(
        "cost_of_revenue", "accounts_payable"
    )
    source_lineage[_RECONCILED_OPERATING_START_BY_ROLE["capex"]] = _source_ref(
        "revenue", "capex"
    )
    source_lineage[_RECONCILED_OPERATING_START_BY_ROLE["da"]] = _source_ref(
        "revenue", "da"
    )
    if inventory_applicable:
        source_lineage[_RECONCILED_OPERATING_START_BY_ROLE["inventory"]] = _source_ref(
            "cost_of_revenue", "inventory"
        )


def _pick(values: list[tuple[Any, str]], default_value: Any, default_source: str) -> tuple[Any, str]:
    for value, source in values:
        if value is not None:
            return value, source
    return default_value, default_source


def _detail_median(comps_detail: dict[str, Any] | None, metric: str) -> Any:
    medians = (comps_detail or {}).get("medians") or {}
    return medians.get(metric)


def _detail_source(comps_detail: dict[str, Any] | None, metric: str) -> str:
    source_lineage = (comps_detail or {}).get("source_lineage") or {}
    source = source_lineage.get("source") or source_lineage.get("source_file") or "comps_detail"
    return f"{source}_{metric}"


def _reprice_ciq_comps_with_bridge(
    comps: dict[str, Any] | None,
    *,
    bridge: ReconciledEVBridge,
) -> dict[str, Any] | None:
    """Replace every EV-based legacy preview with the reconciled bridge.

    CIQ financial and share fields in this payload are already expressed in
    USD millions. P/E is retained because it does not cross the EV-to-equity
    bridge; the blended value is rebuilt from only the prices supported by the
    current payload.
    """

    if comps is None:
        return None
    updated = dict(comps)
    adjustment_mm = float(bridge.ev_to_equity_adjustment)

    def _positive(key: str) -> float | None:
        value = updated.get(key)
        if value is None:
            return None
        numeric = float(value)
        return numeric if numeric > 0 else None

    shares_mm = _positive("target_shares_out")
    ebitda_mm = _positive("target_ebitda_ltm")
    ebit_mm = _positive("target_ebit_ltm")
    ebitda_multiple = _positive("peer_median_tev_ebitda_ltm")
    ebit_multiple = _positive("peer_median_tev_ebit_ltm")

    def _ev_price(
        multiple: float | None,
        target_metric_mm: float | None,
    ) -> float | None:
        if multiple is None or target_metric_mm is None or shares_mm is None:
            return None
        return round(
            (
                multiple * target_metric_mm
                - adjustment_mm
            )
            / shares_mm,
            4,
        )

    updated["implied_price_ev_ebitda"] = _ev_price(
        ebitda_multiple,
        ebitda_mm,
    )
    updated["implied_price_ev_ebit"] = _ev_price(
        ebit_multiple,
        ebit_mm,
    )
    prices = [
        value
        for value in (
            updated["implied_price_ev_ebitda"],
            updated["implied_price_ev_ebit"],
            updated.get("implied_price_pe"),
        )
        if value is not None
    ]
    updated["implied_price_base"] = (
        round(sum(float(value) for value in prices) / len(prices), 4)
        if prices
        else None
    )
    updated["target_ev_to_equity_adjustment"] = adjustment_mm
    updated["bridge_basis"] = "reconciled_claim_ledger"
    return updated


def _public_comps_fallback_enabled(ticker: str, sector: str) -> bool:
    overrides = load_valuation_overrides()
    ticker_blob = overrides.get("tickers", {}).get(ticker.upper(), {}) or {}
    sector_blob = overrides.get("sectors", {}).get(sector, {}) or {}
    global_blob = overrides.get("global", {}) or {}
    return bool(
        ticker_blob.get("public_comps_fallback")
        or ticker_blob.get("peers")
        or sector_blob.get("public_comps_fallback")
        or global_blob.get("public_comps_fallback")
    )


def _public_comps_fallback_peers(ticker: str) -> list[str] | None:
    overrides = load_valuation_overrides()
    ticker_blob = overrides.get("tickers", {}).get(ticker.upper(), {}) or {}
    peers = ticker_blob.get("peers")
    return [str(peer).upper() for peer in peers] if peers is not None else None


def _build_public_market_fallback_comps_detail(ticker: str, sector: str, market: dict[str, Any]) -> dict[str, Any] | None:
    if not _public_comps_fallback_enabled(ticker, sector):
        return None
    comps_detail = build_public_market_fallback_comps_detail(
        ticker,
        market=market,
        sector=sector,
        explicit_peers=_public_comps_fallback_peers(ticker),
        market_data_client=md_client,
    )
    return comps_detail


def _classify_source(source: Any) -> str:
    text = str(source or "").lower()
    if not text:
        return "missing"
    if "override" in text or "approved" in text:
        return "pm_override"
    if "ciq" in text:
        return "ciq"
    if "edgar" in text or "xbrl" in text:
        return "filing"
    if "yfinance" in text:
        return "public_market"
    if "comps" in text or "peer" in text:
        return "peer_prior"
    if "story" in text:
        return "story_prior"
    if "default" in text:
        return "missing_default"
    return "other"


def _default_resolution_report(
    *,
    drivers: ForecastDrivers,
    source_lineage: dict[str, str],
    defaults: dict[str, float],
    ciq_comps_detail: dict[str, Any] | None,
) -> dict[str, Any]:
    field_specs: dict[str, dict[str, Any]] = {
        "exit_multiple": {
            "value": drivers.exit_multiple,
            "fallback_value": defaults["exit_multiple"],
            "severity": "high",
            "preferred_sources": ["ciq_comps_forward", "ciq_comps_ltm", "comps_detail_median", "pm_override"],
            "why_it_matters": "Directly affects terminal value and equity value.",
        },
        "dso_start": {
            "value": drivers.dso_start,
            "fallback_value": defaults["dso"],
            "severity": "medium",
            "preferred_sources": ["ciq", "statement_derived", "yfinance", "peer_prior"],
            "why_it_matters": "Affects working-capital cash drag.",
        },
        "dio_start": {
            "value": drivers.dio_start,
            "fallback_value": defaults["dio"],
            "severity": "medium",
            "preferred_sources": ["ciq", "statement_derived", "yfinance", "peer_prior", "not_applicable"],
            "why_it_matters": "Affects inventory investment and working-capital cash drag.",
        },
        "dpo_start": {
            "value": drivers.dpo_start,
            "fallback_value": defaults["dpo"],
            "severity": "medium",
            "preferred_sources": ["ciq", "statement_derived", "yfinance", "peer_prior"],
            "why_it_matters": "Affects supplier financing and working-capital cash drag.",
        },
        "pension_deficit": {
            "value": drivers.pension_deficit,
            "fallback_value": 0.0,
            "severity": "medium",
            "preferred_sources": ["ciq", "edgar_xbrl", "explicit_structural_zero"],
            "why_it_matters": "Can be a non-equity claim in the equity bridge.",
        },
        "minority_interest": {
            "value": drivers.minority_interest,
            "fallback_value": 0.0,
            "severity": "low",
            "preferred_sources": ["ciq", "yfinance", "edgar_xbrl", "explicit_structural_zero"],
            "why_it_matters": "Can be a non-equity claim in the equity bridge.",
        },
        "preferred_equity": {
            "value": drivers.preferred_equity,
            "fallback_value": 0.0,
            "severity": "low",
            "preferred_sources": ["ciq", "yfinance", "edgar_xbrl", "explicit_structural_zero"],
            "why_it_matters": "Can be a non-equity claim in the equity bridge.",
        },
    }

    fields: list[dict[str, Any]] = []
    counts = {"resolved": 0, "review_required": 0}
    high_review = 0
    fallback_medians = (ciq_comps_detail or {}).get("medians") or {}
    for name, spec in field_specs.items():
        source = source_lineage.get(name)
        source_class = _classify_source(source)
        source_text = str(source or "")
        is_default = source_class == "missing_default" or "default" in source_text.lower()
        is_story_only = source_class == "story_prior" and name in {"exit_multiple"}
        needs_review = bool(is_default or is_story_only)
        if source_text == "default" and spec["fallback_value"] == 0.0 and float(spec["value"] or 0.0) == 0.0:
            source_class = "unproven_zero"
        if needs_review and spec["severity"] == "high":
            high_review += 1
        counts["review_required" if needs_review else "resolved"] += 1
        fields.append(
            {
                "field": name,
                "value": spec["value"],
                "source": source,
                "source_class": source_class,
                "fallback_value": spec["fallback_value"],
                "severity": spec["severity"],
                "needs_pm_review": needs_review,
                "preferred_sources": spec["preferred_sources"],
                "why_it_matters": spec["why_it_matters"],
                "available_comps_medians": fallback_medians if name == "exit_multiple" and fallback_medians else None,
            }
        )

    status = "ok"
    if high_review:
        status = "review_required_high"
    elif counts["review_required"]:
        status = "review_required"
    return {
        "status": status,
        "counts": counts,
        "fields": fields,
    }


def _canonical_source(source_detail: str) -> str:
    if source_detail.startswith("ciq"):
        return "ciq"
    if source_detail.startswith("yfinance"):
        return "yfinance"
    return source_detail


def _get_market_data_cached(ticker: str) -> dict[str, Any]:
    try:
        return md_client.get_market_data(ticker, use_cache=True)
    except TypeError:
        return md_client.get_market_data(ticker)


def _get_historical_financials_cached(ticker: str) -> dict[str, Any]:
    try:
        return md_client.get_historical_financials(ticker, use_cache=True)
    except TypeError:
        return md_client.get_historical_financials(ticker)


def _growth_period_type(source_detail: str) -> str:
    if source_detail == "ciq_consensus":
        return "consensus_fy1"
    if source_detail in {"ciq_cagr_3yr", "yfinance_cagr_3yr"}:
        return "cagr_3yr"
    if source_detail == "yfinance_ttm_yoy":
        return "ttm_yoy"
    if source_detail == "default":
        return "default"
    return "unknown"


def select_exit_metric_for_sector(sector: str) -> str:
    return EXIT_METRIC_BY_SECTOR.get(sector, "ev_ebitda")


def determine_model_applicability(sector: str, industry: str) -> str:
    if sector in EXCLUDED_SECTORS:
        return "alt_model_required"
    if "REIT" in (industry or "").upper():
        return "alt_model_required"
    return "dcf_applicable"


def clear_valuation_overrides_cache() -> None:
    """Invalidate the lru_cache on load_valuation_overrides so a re-run picks up new writes."""
    load_valuation_overrides.cache_clear()


@functools.lru_cache(maxsize=1)
def load_valuation_overrides() -> dict[str, Any]:
    if not OVERRIDES_PATH.exists():
        return {"global": {}, "sectors": {}, "tickers": {}}
    with OVERRIDES_PATH.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    data.setdefault("global", {})
    data.setdefault("sectors", {})
    data.setdefault("tickers", {})
    return data


def _apply_overrides(
    drivers: ForecastDrivers,
    source_lineage: dict[str, str],
    ticker: str,
    sector: str,
) -> None:
    overrides = load_valuation_overrides()

    def _apply(blob: dict[str, Any], source: str) -> None:
        for key, value in blob.items():
            if hasattr(drivers, key):
                setattr(drivers, key, value)
                source_lineage[key] = source

    override_blobs: list[tuple[dict[str, Any], str]] = [
        (overrides.get("global", {}) or {}, "override_global"),
        (
            overrides.get("sectors", {}).get(sector, {}) or {},
            "override_sector",
        ),
        (
            overrides.get("tickers", {}).get(ticker.upper(), {}) or {},
            "override_ticker",
        ),
    ]

    # ── QoE LLM approved overrides ───────────────────────────────────────────
    # PM sets status → 'approved' in config/qoe_pending.yaml to activate.
    # override_ticker entries still take final precedence if also set.
    if QOE_PENDING_PATH.exists():
        with QOE_PENDING_PATH.open("r", encoding="utf-8") as f:
            qoe_pending = yaml.safe_load(f) or {}
        entry = qoe_pending.get(ticker.upper(), {})
        if entry.get("status") == "approved":
            override_blobs.append(
                (
                    entry.get("suggested_override") or {},
                    "qoe_llm_approved",
                )
            )

    try:
        from db.loader import get_approved_assumption_overrides

        approved_register_entries = get_approved_assumption_overrides(ticker)
    except Exception:
        approved_register_entries = {}
    override_blobs.append(
        (
            approved_register_entries,
            "approved_assumption_register",
        )
    )

    blocked_fields = {
        key
        for blob, _source in override_blobs
        for key, value in blob.items()
        if key in EV_BRIDGE_COMPONENTS and value is not None
    }
    if blocked_fields:
        raise BridgeMutationPathError(blocked_fields)
    for blob, source in override_blobs:
        _apply(blob, source)


def _load_wacc_methodology_override(ticker: str) -> dict[str, Any] | None:
    overrides = load_valuation_overrides()
    ticker_blob = overrides.get("tickers", {}).get(ticker.upper(), {})
    method_blob = ticker_blob.get("wacc_methodology")
    if not isinstance(method_blob, dict):
        return None
    mode = str(method_blob.get("mode") or "").strip()
    if mode not in {"single_method", "blended"}:
        return None
    selected_method = method_blob.get("selected_method")
    weights = method_blob.get("weights") if isinstance(method_blob.get("weights"), dict) else None
    return {
        "mode": mode,
        "selected_method": selected_method,
        "weights": weights or {},
    }


def _derive_invested_capital_start(
    revenue_base: float,
    tax_start: float,
    ciq: dict[str, Any] | None,
    defaults: dict[str, float],
    clamp_events: list[ClampEvent],
    hist: dict[str, Any] | None = None,
) -> tuple[float, str]:
    ciq_roic = (ciq or {}).get("roic")
    ciq_ebit = (ciq or {}).get("operating_income_ttm")
    ciq_ic_from_roic = None
    if ciq_roic and ciq_roic > 0.03 and ciq_ebit is not None:
        ciq_ic_from_roic = float(ciq_ebit) * (1.0 - tax_start) / float(ciq_roic)

    raw, source = _pick(
        [
            ((ciq or {}).get("invested_capital"), "ciq"),
            (ciq_ic_from_roic, "ciq_derived_nopat_over_roic"),
            # Gap 4: IC from yfinance balance sheet (Total Assets - Current Liabilities - Cash)
            ((hist or {}).get("invested_capital_derived"), "yfinance_derived"),
        ],
        revenue_base / defaults["ic_turnover"],
        "default",
    )
    value = _bounded(
        raw,
        revenue_base * 0.15,
        revenue_base * 4.0,
        revenue_base / defaults["ic_turnover"],
        field_name="invested_capital_start",
        source=source,
        events=clamp_events,
    )
    return float(value), source


def _split_cash(revenue_base: float, total_cash: float) -> tuple[float, float]:
    operating_cash = min(
        max(float(total_cash), 0.0),
        max(float(revenue_base), 0.0) * OPERATING_CASH_REVENUE_RATE,
    )
    return operating_cash, max(float(total_cash) - operating_cash, 0.0)


def _source_ref(field_name: str, source: str) -> str:
    return f"{source}:{field_name}"


def _unclaimed_bridge_lines_from_snapshots(
    ciq: dict[str, Any] | None,
    edgar_bridge: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Normalize source-provided bridge assets without classifying them.

    Broad aggregate investment fields take precedence over their narrower
    aliases so a provider snapshot cannot create a double claim merely by
    exposing both a total and its components.
    """

    lines: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _append(
        raw: Mapping[str, Any],
        *,
        default_source: str,
        default_period_end: str | None,
        default_currency: str,
    ) -> None:
        line_id = str(raw.get("line_id") or "").strip()
        value = raw.get("value_usd", raw.get("value"))
        try:
            numeric = abs(float(value))
        except (TypeError, ValueError):
            return
        if not line_id or not numeric or line_id in seen:
            return
        seen.add(line_id)
        lines.append(
            {
                "line_id": line_id,
                "value": numeric,
                "source_ref": str(
                    raw.get("source_ref") or f"{default_source}:{line_id}"
                ),
                "currency": str(
                    raw.get("currency") or default_currency
                ).upper(),
                "period_end": (
                    str(raw.get("period_end") or default_period_end)
                    if raw.get("period_end") or default_period_end
                    else None
                ),
                "period_type": str(
                    raw.get("period_type") or "instant"
                ).lower(),
                "semantic_type": str(
                    raw.get("semantic_type") or "asset"
                ).lower(),
            }
        )

    for source, source_name in (
        (ciq or {}, "ciq"),
        (edgar_bridge or {}, "edgar_xbrl"),
    ):
        default_period_end = source.get("as_of_date") or source.get(
            "period_end"
        )
        default_currency = str(source.get("currency") or "USD")
        explicit = source.get("bridge_unclaimed_lines")
        if isinstance(explicit, list):
            for item in explicit:
                if isinstance(item, Mapping):
                    _append(
                        item,
                        default_source=source_name,
                        default_period_end=default_period_end,
                        default_currency=default_currency,
                    )

        broad_value = source.get("investments")
        if broad_value is not None:
            _append(
                {
                    "line_id": f"{source_name}:investments",
                    "value": broad_value,
                    "source_ref": f"{source_name}:investments",
                    "semantic_type": "asset",
                },
                default_source=source_name,
                default_period_end=default_period_end,
                default_currency=default_currency,
            )
            continue
        for field_name in (
            "marketable_securities",
            "short_term_investments",
            "long_term_investments",
            "equity_investments",
        ):
            if source.get(field_name) is None:
                continue
            _append(
                {
                    "line_id": f"{source_name}:{field_name}",
                    "value": source[field_name],
                    "source_ref": f"{source_name}:{field_name}",
                    "semantic_type": "asset",
                },
                default_source=source_name,
                default_period_end=default_period_end,
                default_currency=default_currency,
            )
    return lines


def _bridge_payload(
    bridge: ReconciledEVBridge,
    *,
    unit_scale: float,
) -> dict[str, Any]:
    components = {
        component: float(getattr(bridge, component)) * unit_scale
        for component in EV_BRIDGE_COMPONENTS
    }
    return {
        "components_usd": components,
        "ev_to_equity_adjustment_usd": (
            bridge.ev_to_equity_adjustment * unit_scale
        ),
    }


def _bridge_cutover_and_readiness(
    *,
    ledger: ClaimLedger,
    legacy_bridge: ReconciledEVBridge,
    reconciled_bridge: ReconciledEVBridge,
    readiness: ValuationReadinessEvidence | None,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    reconciliation = ledger.reconcile()
    reason_codes: list[str] = []
    if not reconciliation.is_reconciled:
        reason_codes.append("claim_ledger.reconciliation_failed")
    reason_codes.extend(
        "claim_ledger.material_unclaimed:" + allocation_id
        for allocation_id in reconciliation.material_unclaimed_allocation_ids
    )

    shared_payload: dict[str, Any] | None = None
    if readiness is None:
        reason_codes.append("readiness.not_supplied")
        shared_status = ValuationTrustStatus.provisional
    else:
        shared_payload = readiness.model_dump(mode="json")
        reason_codes.extend(readiness.reason_codes)
        shared_status = readiness.trust_status
        if readiness.claim_ledger_hash != ledger.fingerprint:
            reason_codes.append("readiness.claim_ledger_fingerprint_stale")

    if not reconciliation.is_decision_grade:
        valuation_status = ValuationTrustStatus.blocked
    elif "readiness.claim_ledger_fingerprint_stale" in reason_codes:
        valuation_status = ValuationTrustStatus.blocked
    else:
        valuation_status = shared_status

    cutover_ready = (
        valuation_status == ValuationTrustStatus.decision_grade
        and not reason_codes
    )
    bridge_cutover = {
        "mode": "official" if cutover_ready else "shadow",
        "selected_bridge": (
            "reconciled_official"
            if cutover_ready
            else "reconciled_shadow"
        ),
        "reason_codes": list(dict.fromkeys(reason_codes)),
        "claim_ledger_fingerprint": ledger.fingerprint,
        "legacy": _bridge_payload(
            legacy_bridge,
            unit_scale=ledger.unit_scale,
        ),
        "reconciled": _bridge_payload(
            reconciled_bridge,
            unit_scale=ledger.unit_scale,
        ),
        "equity_value_delta_usd": (
            (
                legacy_bridge.ev_to_equity_adjustment
                - reconciled_bridge.ev_to_equity_adjustment
            )
            * ledger.unit_scale
        ),
    }
    readiness_payload = {
        "trust_status": valuation_status.value,
        "reason_codes": list(dict.fromkeys(reason_codes)),
        "claim_ledger": {
            "is_reconciled": reconciliation.is_reconciled,
            "is_decision_grade": reconciliation.is_decision_grade,
            "material_unclaimed_allocation_ids": list(
                reconciliation.material_unclaimed_allocation_ids
            ),
            "fingerprint": ledger.fingerprint,
        },
        "shared_readiness": shared_payload,
    }
    return bridge_cutover, readiness_payload, valuation_status.value


def _build_ev_bridge_claim_ledger(
    *,
    total_debt: float,
    total_debt_source: str,
    total_cash: float,
    cash_source: str,
    debt_includes_leases: bool,
    lease_liabilities: float,
    lease_liabilities_source: str,
    component_values_usd: dict[str, float],
    reported_component_values_usd: dict[str, float],
    component_sources: dict[str, str],
    unclaimed_reported_lines_usd: list[dict[str, Any]] | None = None,
    currency: str = "USD",
    period_end: str | None = None,
) -> ClaimLedger:
    """Build the exact-once bridge ledger in USD millions.

    CIQ's total-debt fact is lease-inclusive, so its parent line is split between
    funded debt and leases. Public-market debt is treated as debt ex operating
    leases and the separately sourced lease line gets its own parent.
    """

    scale = 1_000_000.0
    reported_lines: list[ReportedLine] = []
    allocations: list[ClaimAllocation] = []

    total_debt_mm = float(total_debt) / scale
    total_cash_mm = float(total_cash) / scale
    lease_mm = float(lease_liabilities) / scale
    operating_cash_usd, excess_cash_usd = _split_cash(
        component_values_usd["revenue_base"],
        total_cash,
    )
    operating_cash_mm = operating_cash_usd / scale
    excess_cash_mm = excess_cash_usd / scale

    reported_lines.append(
        ReportedLine(
            "total_debt",
            total_debt_mm,
            _source_ref("total_debt", total_debt_source),
            currency=currency,
            period_end=period_end,
            period_type="instant",
            semantic_type="liability",
            unit_scale=scale,
        )
    )
    debt_ex_leases_mm = (
        total_debt_mm - lease_mm if debt_includes_leases else total_debt_mm
    )
    allocations.append(
        ClaimAllocation(
            parent_line_id="total_debt",
            allocation_id="total_debt:funded",
            component="net_debt",
            sign=1,
            value=debt_ex_leases_mm,
        )
    )
    if debt_includes_leases and lease_mm:
        allocations.append(
            ClaimAllocation(
                parent_line_id="total_debt",
                allocation_id="total_debt:leases",
                component="lease_liabilities",
                sign=1,
                value=lease_mm,
            )
        )
    elif lease_mm:
        reported_lines.append(
            ReportedLine(
                "lease_liabilities",
                lease_mm,
                _source_ref(
                    "lease_liabilities",
                    lease_liabilities_source,
                ),
                currency=currency,
                period_end=period_end,
                period_type="instant",
                semantic_type="lease_liability",
                unit_scale=scale,
            )
        )
        allocations.append(
            ClaimAllocation(
                parent_line_id="lease_liabilities",
                allocation_id="lease_liabilities",
                component="lease_liabilities",
                sign=1,
                value=lease_mm,
            )
        )

    reported_lines.append(
        ReportedLine(
            "cash",
            total_cash_mm,
            _source_ref("cash", cash_source),
            currency=currency,
            period_end=period_end,
            period_type="instant",
            semantic_type="asset",
            unit_scale=scale,
        )
    )
    allocations.extend(
        [
            ClaimAllocation(
                parent_line_id="cash",
                allocation_id="cash:operating",
                component="net_debt",
                sign=-1,
                value=operating_cash_mm,
            ),
            ClaimAllocation(
                parent_line_id="cash",
                allocation_id="cash:excess",
                component="non_operating_assets",
                sign=1,
                value=excess_cash_mm,
            ),
        ]
    )

    for component in (
        "minority_interest",
        "preferred_equity",
        "pension_deficit",
        "options_value",
        "convertibles_value",
    ):
        reported_value_mm = (
            float(reported_component_values_usd.get(component, 0.0)) / scale
        )
        if not reported_value_mm:
            continue
        reported_lines.append(
            ReportedLine(
                component,
                reported_value_mm,
                _source_ref(component, component_sources.get(component, "unknown")),
                currency=currency,
                period_end=period_end,
                period_type="instant",
                semantic_type=(
                    "liability"
                    if component
                    in {"pension_deficit", "convertibles_value"}
                    else "equity_claim"
                ),
                unit_scale=scale,
            )
        )
        allocations.append(
            ClaimAllocation(
                parent_line_id=component,
                allocation_id=component,
                component=component,
                sign=1,
                value=reported_value_mm,
            )
        )

    unclaimed_total_mm = 0.0
    for raw_line in unclaimed_reported_lines_usd or []:
        line_id = str(raw_line.get("line_id") or "").strip()
        if not line_id:
            continue
        value_mm = abs(float(raw_line.get("value") or 0.0)) / scale
        if not value_mm:
            continue
        reported_lines.append(
            ReportedLine(
                line_id=line_id,
                value=value_mm,
                source_ref=str(raw_line.get("source_ref") or line_id),
                currency=str(raw_line.get("currency") or currency),
                period_end=(
                    str(raw_line["period_end"])
                    if raw_line.get("period_end") is not None
                    else period_end
                ),
                period_type=str(
                    raw_line.get("period_type") or "instant"
                ),
                semantic_type=str(
                    raw_line.get("semantic_type") or "unknown"
                ),
                unit_scale=scale,
            )
        )
        allocations.append(
            ClaimAllocation(
                parent_line_id=line_id,
                allocation_id=line_id,
                component="unclaimed",
                sign=1,
                value=value_mm,
            )
        )
        unclaimed_total_mm += value_mm

    resolved_component_values = {
        component: float(value) / scale
        for component, value in component_values_usd.items()
        if component != "revenue_base"
    }
    if unclaimed_total_mm or unclaimed_reported_lines_usd:
        resolved_component_values["unclaimed"] = unclaimed_total_mm

    ledger = ClaimLedger(
        reported_lines=reported_lines,
        allocations=allocations,
        component_values=resolved_component_values,
        unit="USD millions",
        unit_scale=scale,
        currency=currency,
        period_end=period_end,
        period_type="instant",
    )
    ledger.require_reconciled()
    return ledger


def build_valuation_inputs(
    ticker: str,
    as_of_date: str | None = None,
    apply_overrides: bool = True,
    readiness: ValuationReadinessEvidence | None = None,
    apply_story_overlay: bool = False,
    allow_public_comps_fallback: bool = False,
) -> ValuationInputsWithLineage | None:
    ticker = ticker.upper().strip()
    clamp_events: list[ClampEvent] = []
    mkt = _get_market_data_cached(ticker)
    hist = _get_historical_financials_cached(ticker)
    ciq = get_ciq_snapshot(ticker, as_of_date=as_of_date)
    ciq_comps = get_ciq_comps_valuation(ticker, as_of_date=as_of_date)
    ciq_comps_detail = get_ciq_comps_detail(ticker, as_of_date=as_of_date)
    edgar_bridge = get_bridge_items_from_xbrl(ticker)

    price = float(mkt.get("current_price") or 0)
    sector = mkt.get("sector", "") or ""
    industry = mkt.get("industry", "") or ""
    defaults = SECTOR_DEFAULTS.get(sector, SECTOR_DEFAULTS["_default"])
    public_comps_fallback_used = False
    if (
        allow_public_comps_fallback
        and not ciq_comps
        and not ciq_comps_detail
    ):
        ciq_comps_detail = _build_public_market_fallback_comps_detail(ticker, sector, mkt)
        public_comps_fallback_used = bool(ciq_comps_detail)

    # FRED live Rf override (best-effort — falls back to config if unavailable)
    _fred_rf: float | None = None
    try:
        from src.stage_00_data.fred_client import get_macro_snapshot
        _snap = get_macro_snapshot(lookback_days=5)
        if _snap.get("available"):
            _dgs10_series = _snap.get("series", {}).get("DGS10", {})
            _fred_rf = _dgs10_series.get("latest_value")
            if _fred_rf is not None:
                _fred_rf = _fred_rf / 100.0  # FRED returns as percent
    except Exception:
        pass

    try:
        from db.loader import get_valuation_policy_rf_erp, get_valuation_policy_sector_defaults

        policy_rf, policy_erp = get_valuation_policy_rf_erp()
        saved_sector = get_valuation_policy_sector_defaults(sector)
        if saved_sector:
            defaults = {**defaults, **saved_sector}
    except Exception:
        policy_rf = 0.045
        policy_erp = 0.05

    # Use FRED live 10Y rate if available, else the editable valuation policy.
    rf_override = _fred_rf if _fred_rf is not None else policy_rf

    if price <= 0:
        return None

    revenue_base, revenue_source = _pick(
        [
            ((ciq or {}).get("revenue_ttm"), "ciq"),
            (mkt.get("revenue_ttm"), "yfinance"),
        ],
        None,
        "missing",
    )
    if not revenue_base or revenue_base <= 0:
        return None

    ciq_rev_fy1 = (ciq or {}).get("revenue_fy1")
    ciq_rev_ltm = (ciq or {}).get("revenue_ttm")
    consensus_growth = None
    if ciq_rev_fy1 and ciq_rev_ltm and float(ciq_rev_ltm) > 0:
        consensus_growth = (float(ciq_rev_fy1) / float(ciq_rev_ltm)) - 1

    growth_near_raw, growth_source_detail = _pick(
        [
            (consensus_growth, "ciq_consensus"),
            ((ciq or {}).get("revenue_cagr_3yr"), "ciq_cagr_3yr"),
            (hist.get("revenue_cagr_3yr"), "yfinance_cagr_3yr"),
            (mkt.get("revenue_growth"), "yfinance_ttm_yoy"),
        ],
        defaults["growth_near"],
        "default",
    )
    growth_source = _canonical_source(growth_source_detail)
    growth_period_type = _growth_period_type(growth_source_detail)
    revenue_period_type = "ttm" if revenue_source in {"ciq", "yfinance"} else "unknown"

    if revenue_period_type == "ttm" and growth_period_type == "consensus_fy1":
        revenue_alignment_flag = "aligned_consensus"
    elif revenue_period_type == "ttm" and growth_period_type == "ttm_yoy":
        revenue_alignment_flag = "aligned_ttm"
    elif revenue_period_type == "ttm" and growth_period_type == "cagr_3yr":
        revenue_alignment_flag = "mixed_ttm_vs_cagr"
    elif growth_period_type == "default":
        revenue_alignment_flag = "default_growth"
    else:
        revenue_alignment_flag = "unknown"

    if revenue_source == "default" or growth_source == "default":
        revenue_data_quality_flag = "low_quality"
    elif revenue_alignment_flag in {"aligned_consensus", "aligned_ttm"}:
        revenue_data_quality_flag = "ok"
    elif revenue_alignment_flag == "mixed_ttm_vs_cagr":
        revenue_data_quality_flag = "needs_review"
    else:
        revenue_data_quality_flag = "needs_review"

    growth_near = _bounded(
        growth_near_raw,
        -0.10,
        0.35,
        defaults["growth_near"],
        field_name="revenue_growth_near",
        source=growth_source,
        events=clamp_events,
    )

    # Revision momentum bias (bounded ±2%)
    try:
        from src.stage_02_valuation.revision_signals import get_revision_growth_bias
        _rev_bias, _rev_source = get_revision_growth_bias(ticker)
        if abs(_rev_bias) > 0.001:
            growth_near = max(0.0, min(0.40, growth_near + _rev_bias))
            growth_source_detail = growth_source_detail + f"|{_rev_source}"
    except Exception:
        pass

    fade = defaults.get("growth_fade_ratio", 0.65)
    growth_mid = _bounded(
        growth_near * fade,
        -0.08,
        0.25,
        defaults["growth_near"] * fade,
        field_name="revenue_growth_mid",
        source=growth_source,
        events=clamp_events,
    )

    margin_start_raw, margin_source = _pick(
        [
            ((ciq or {}).get("op_margin_avg_3yr") or (ciq or {}).get("ebit_margin"), "ciq"),
            (hist.get("op_margin_avg_3yr"), "yfinance"),
            (mkt.get("operating_margin"), "yfinance"),
        ],
        defaults["margin"],
        "default",
    )
    margin_start = _bounded(
        margin_start_raw,
        0.02,
        0.60,
        defaults["margin"],
        field_name="ebit_margin_start",
        source=margin_source,
        events=clamp_events,
    )
    # #3: Blend company margin with sector default — halves reversion speed for outliers
    margin_target = _bounded(
        0.5 * margin_start + 0.5 * defaults["margin"],
        0.03,
        0.65,
        defaults["margin"],
        field_name="ebit_margin_target",
        source="default",
        events=clamp_events,
    )

    tax_start_raw, tax_source = _pick(
        [
            ((ciq or {}).get("effective_tax_rate_avg"), "ciq"),
            (hist.get("effective_tax_rate_avg"), "yfinance"),
        ],
        0.21,
        "default",
    )
    tax_start = _bounded(
        tax_start_raw,
        0.05,
        0.40,
        0.21,
        field_name="tax_rate_start",
        source=tax_source,
        events=clamp_events,
    )
    tax_target = _bounded(
        tax_start,
        0.15,
        0.30,
        0.23,
        field_name="tax_rate_target",
        source=tax_source,
        events=clamp_events,
    )

    capex_raw, capex_source = _pick(
        [
            ((ciq or {}).get("capex_pct_avg_3yr"), "ciq"),
            (hist.get("capex_pct_avg_3yr"), "yfinance"),
        ],
        defaults["capex_pct"],
        "default",
    )
    capex_start = _bounded(
        capex_raw,
        0.01,
        0.25,
        defaults["capex_pct"],
        field_name="capex_pct_start",
        source=capex_source,
        events=clamp_events,
    )
    capex_target = _bounded(
        max(0.005, capex_start * 0.95),
        0.005,
        0.25,
        capex_start,
        field_name="capex_pct_target",
        source=capex_source,
        events=clamp_events,
    )

    da_raw, da_source = _pick(
        [
            ((ciq or {}).get("da_pct_avg_3yr"), "ciq"),
            (hist.get("da_pct_avg_3yr"), "yfinance"),
        ],
        defaults["da_pct"],
        "default",
    )
    da_start = _bounded(
        da_raw,
        0.005,
        0.20,
        defaults["da_pct"],
        field_name="da_pct_start",
        source=da_source,
        events=clamp_events,
    )
    da_target = _bounded(
        max(0.003, da_start * 0.95),
        0.003,
        0.20,
        da_start,
        field_name="da_pct_target",
        source=da_source,
        events=clamp_events,
    )

    peer_tickers = [
        str(peer.get("ticker") or "").upper()
        for peer in (ciq_comps_detail or {}).get("peers", [])
        if peer.get("ticker")
    ]
    if getattr(compute_wacc_from_yfinance, "__module__", "") != "src.stage_02_valuation.wacc":
        # Compatibility seam for older tests/callers that monkeypatch the
        # single-method helper instead of the newer methodology set.
        wacc_result = compute_wacc_from_yfinance(ticker, hist=hist)
        wacc_method_results = {"peer_bottom_up": wacc_result}
    else:
        wacc_method_results = compute_wacc_methodology_set_for_ticker(
            ticker,
            peer_tickers=peer_tickers,
            hist=hist,
            market_data=mkt,
            risk_free_rate=rf_override,
            equity_risk_premium=policy_erp,
        )
        wacc_result = wacc_method_results["peer_bottom_up"]
    _wacc_meta = wacc_method_results.get("_meta") or {}
    _wacc_spread_high = bool(_wacc_meta.get("wacc_method_spread_high", False))
    wacc = _bounded(
        getattr(wacc_result, "wacc", 0.09),
        0.04,
        0.20,
        0.09,
        field_name="wacc",
        source="yfinance_capm",
        events=clamp_events,
    )
    cost_of_equity = _bounded(
        getattr(wacc_result, "cost_of_equity", None),
        0.04,
        0.30,
        max(0.06, wacc + 0.015),
        field_name="cost_of_equity",
        source="yfinance_capm",
        events=clamp_events,
    )
    equity_weight = getattr(wacc_result, "equity_weight", None)
    debt_weight_raw = (1.0 - equity_weight) if equity_weight is not None else getattr(wacc_result, "debt_weight", None)
    debt_weight = _bounded(
        debt_weight_raw,
        0.00,
        0.80,
        0.20,
        field_name="debt_weight",
        source="yfinance_capm",
        events=clamp_events,
    )

    exit_metric = select_exit_metric_for_sector(sector)
    if exit_metric == "ev_ebit":
        exit_multiple_raw, exit_source = _pick(
            [
                ((ciq_comps or {}).get("peer_median_tev_ebit_fwd"), "ciq_comps_tev_ebit_fwd"),
                ((ciq_comps or {}).get("peer_median_tev_ebit_ltm"), "ciq_comps_tev_ebit_ltm"),
                (_detail_median(ciq_comps_detail, "tev_ebit_fwd"), _detail_source(ciq_comps_detail, "tev_ebit_fwd")),
                (_detail_median(ciq_comps_detail, "tev_ebit_ltm"), _detail_source(ciq_comps_detail, "tev_ebit_ltm")),
                ((ciq_comps or {}).get("peer_median_tev_ebitda_fwd"), "ciq_comps_tev_ebitda_fwd_fallback"),
                ((ciq_comps or {}).get("peer_median_tev_ebitda_ltm"), "ciq_comps_tev_ebitda_fallback"),
                (_detail_median(ciq_comps_detail, "tev_ebitda_fwd"), _detail_source(ciq_comps_detail, "tev_ebitda_fwd_fallback")),
                (_detail_median(ciq_comps_detail, "tev_ebitda_ltm"), _detail_source(ciq_comps_detail, "tev_ebitda_ltm_fallback")),
            ],
            defaults["exit_multiple"],
            "default",
        )
    else:
        exit_multiple_raw, exit_source = _pick(
            [
                ((ciq_comps or {}).get("peer_median_tev_ebitda_fwd"), "ciq_comps_tev_ebitda_fwd"),
                ((ciq_comps or {}).get("peer_median_tev_ebitda_ltm"), "ciq_comps_tev_ebitda_ltm"),
                (_detail_median(ciq_comps_detail, "tev_ebitda_fwd"), _detail_source(ciq_comps_detail, "tev_ebitda_fwd")),
                (_detail_median(ciq_comps_detail, "tev_ebitda_ltm"), _detail_source(ciq_comps_detail, "tev_ebitda_ltm")),
                ((ciq_comps or {}).get("peer_median_tev_ebit_fwd"), "ciq_comps_tev_ebit_fwd_fallback"),
                ((ciq_comps or {}).get("peer_median_tev_ebit_ltm"), "ciq_comps_tev_ebit_fallback"),
                (_detail_median(ciq_comps_detail, "tev_ebit_fwd"), _detail_source(ciq_comps_detail, "tev_ebit_fwd_fallback")),
                (_detail_median(ciq_comps_detail, "tev_ebit_ltm"), _detail_source(ciq_comps_detail, "tev_ebit_ltm_fallback")),
            ],
            defaults["exit_multiple"],
            "default",
        )
    exit_multiple = _bounded(
        exit_multiple_raw,
        4.0,
        30.0,
        defaults["exit_multiple"],
        field_name="exit_multiple",
        source=exit_source,
        events=clamp_events,
    )

    total_debt_raw, total_debt_source = _pick(
        [
            ((ciq or {}).get("total_debt"), "ciq"),
            (mkt.get("total_debt"), "yfinance"),
        ],
        0.0,
        "default",
    )
    cash_raw, cash_source = _pick(
        [
            ((ciq or {}).get("cash"), "ciq"),
            (mkt.get("cash"), "yfinance"),
        ],
        0.0,
        "default",
    )
    shares_raw, shares_source = _pick(
        [
            ((ciq or {}).get("shares_outstanding"), "ciq"),
            (hist.get("diluted_shares"), "yfinance_diluted"),
            (mkt.get("shares_outstanding"), "yfinance_basic"),
        ],
        1.0,
        "default",
    )

    dso_raw, dso_source = _pick(
        [
            ((ciq or {}).get("dso"), "ciq"),
            (hist.get("dso_derived"), "yfinance"),
        ],
        defaults["dso"],
        "default",
    )
    dso_start = _bounded(
        dso_raw,
        5.0,
        180.0,
        defaults["dso"],
        field_name="dso_start",
        source=dso_source,
        events=clamp_events,
    )
    if dso_source != "default":
        dso_target_source = f"{dso_source}_blend"
        dso_target = _bounded(
            defaults["dso"] * 0.7 + dso_start * 0.3,
            5.0,
            180.0,
            defaults["dso"],
            field_name="dso_target",
            source=dso_target_source,
            events=clamp_events,
        )
    else:
        dso_target_source = "default"
        dso_target = _bounded(
            defaults["dso"],
            5.0,
            180.0,
            defaults["dso"],
            field_name="dso_target",
            source=dso_target_source,
            events=clamp_events,
        )

    dio_raw, dio_source = _pick(
        [
            ((ciq or {}).get("dio"), "ciq"),
            (hist.get("dio_derived"), "yfinance"),
        ],
        defaults["dio"],
        "default",
    )
    dio_start = _bounded(
        dio_raw,
        5.0,
        220.0,
        defaults["dio"],
        field_name="dio_start",
        source=dio_source,
        events=clamp_events,
    )
    if dio_source != "default":
        dio_target_source = f"{dio_source}_blend"
        dio_target = _bounded(
            defaults["dio"] * 0.7 + dio_start * 0.3,
            5.0,
            220.0,
            defaults["dio"],
            field_name="dio_target",
            source=dio_target_source,
            events=clamp_events,
        )
    else:
        dio_target_source = "default"
        dio_target = _bounded(
            defaults["dio"],
            5.0,
            220.0,
            defaults["dio"],
            field_name="dio_target",
            source=dio_target_source,
            events=clamp_events,
        )

    dpo_raw, dpo_source = _pick(
        [
            ((ciq or {}).get("dpo"), "ciq"),
            (hist.get("dpo_derived"), "yfinance"),
        ],
        defaults["dpo"],
        "default",
    )
    dpo_start = _bounded(
        dpo_raw,
        5.0,
        180.0,
        defaults["dpo"],
        field_name="dpo_start",
        source=dpo_source,
        events=clamp_events,
    )
    if dpo_source != "default":
        dpo_target_source = f"{dpo_source}_blend"
        dpo_target = _bounded(
            defaults["dpo"] * 0.7 + dpo_start * 0.3,
            5.0,
            180.0,
            defaults["dpo"],
            field_name="dpo_target",
            source=dpo_target_source,
            events=clamp_events,
        )
    else:
        dpo_target_source = "default"
        dpo_target = _bounded(
            defaults["dpo"],
            5.0,
            180.0,
            defaults["dpo"],
            field_name="dpo_target",
            source=dpo_target_source,
            events=clamp_events,
        )

    invested_capital_start, invested_capital_source = _derive_invested_capital_start(
        revenue_base=float(revenue_base),
        tax_start=float(tax_start),
        ciq=ciq,
        defaults=defaults,
        clamp_events=clamp_events,
        hist=hist,
    )

    ronic_terminal_raw, ronic_terminal_source = _pick(
        [
            ((ciq or {}).get("roic"), "ciq_roic"),
        ],
        defaults["ronic_terminal"],
        "default",
    )
    ronic_terminal = _bounded(
        ronic_terminal_raw,
        0.06,
        0.30,
        defaults["ronic_terminal"],
        field_name="ronic_terminal",
        source=ronic_terminal_source,
        events=clamp_events,
    )

    operating_cash_buffer, non_operating_assets = _split_cash(
        float(revenue_base),
        float(cash_raw),
    )
    non_operating_assets_source = (
        f"{cash_source}_cash_excess" if cash_source != "default" else "default"
    )

    minority_interest_raw, minority_interest_source = _pick(
        [
            ((ciq or {}).get("minority_interest"), "ciq"),
            (hist.get("minority_interest_bs"), "yfinance"),
            (edgar_bridge.get("minority_interest"), "edgar_xbrl"),
        ],
        0.0,
        "default",
    )
    preferred_equity_raw, preferred_equity_source = _pick(
        [
            ((ciq or {}).get("preferred_equity"), "ciq"),
            (hist.get("preferred_equity_bs"), "yfinance"),
            (edgar_bridge.get("preferred_equity"), "edgar_xbrl"),
        ],
        0.0,
        "default",
    )
    pension_deficit_raw, pension_deficit_source = _pick(
        [
            ((ciq or {}).get("pension_deficit"), "ciq"),
            (edgar_bridge.get("pension_deficit"), "edgar_xbrl"),
        ],
        0.0,
        "default",
    )
    lease_liabilities_raw, lease_liabilities_source = _pick(
        [
            ((ciq or {}).get("lease_liabilities"), "ciq"),
            (hist.get("lease_liabilities_bs"), "yfinance"),
            (edgar_bridge.get("lease_liabilities"), "edgar_xbrl"),
        ],
        0.0,
        "default",
    )
    # PM bridge convention (2026-07-25): CIQ debt is lease-inclusive and is split
    # into debt ex leases plus a live standalone lease claim. Public-market debt is
    # treated as debt ex operating leases. Only the operating cash buffer is netted
    # in net debt; excess cash is a non-operating asset.
    debt_includes_leases = total_debt_source == "ciq"
    debt_ex_leases = float(total_debt_raw) - (
        float(lease_liabilities_raw) if debt_includes_leases else 0.0
    )
    net_debt_raw = debt_ex_leases - operating_cash_buffer
    net_debt_source = (
        f"{total_debt_source}_debt_ex_leases_minus_operating_cash"
        if total_debt_source != "default" or cash_source != "default"
        else "default"
    )
    if lease_liabilities_raw > 0:
        lease_liabilities_source = f"{lease_liabilities_source}_separate_claim"

    _sbc_raw = hist.get("sbc") or edgar_bridge.get("sbc")
    _options_proxy = _sbc_raw * 3.0 if _sbc_raw else None
    options_value_raw, options_value_source = _pick(
        [
            ((ciq or {}).get("options_value"), "ciq"),
            (_options_proxy, "sbc_proxy"),
        ],
        0.0,
        "default",
    )
    convertibles_value_raw, convertibles_value_source = _pick(
        [
            ((ciq or {}).get("convertibles_value"), "ciq"),
        ],
        0.0,
        "default",
    )

    terminal_growth = float(defaults.get("terminal_growth", 0.030))

    # Gap 1: COGS ratio for accurate DIO/DPO projection (denominator fix)
    cogs_pct_raw, cogs_pct_source = _pick(
        [(hist.get("cogs_pct_of_revenue"), "yfinance")],
        0.60,
        "default",
    )
    cogs_pct_of_revenue = _bounded(
        cogs_pct_raw,
        0.10,
        0.95,
        0.60,
        field_name="cogs_pct_of_revenue",
        source=cogs_pct_source,
        events=clamp_events,
    )

    drivers = ForecastDrivers(
        revenue_base=float(revenue_base),
        revenue_growth_near=float(growth_near),
        revenue_growth_mid=float(growth_mid),
        revenue_growth_terminal=terminal_growth,
        ebit_margin_start=float(margin_start),
        ebit_margin_target=float(margin_target),
        tax_rate_start=float(tax_start),
        tax_rate_target=float(tax_target),
        capex_pct_start=float(capex_start),
        capex_pct_target=float(capex_target),
        da_pct_start=float(da_start),
        da_pct_target=float(da_target),
        dso_start=float(dso_start),
        dso_target=float(dso_target),
        dio_start=float(dio_start),
        dio_target=float(dio_target),
        dpo_start=float(dpo_start),
        dpo_target=float(dpo_target),
        wacc=float(wacc),
        exit_multiple=float(exit_multiple),
        exit_metric=exit_metric,
        net_debt=float(net_debt_raw),
        shares_outstanding=float(max(shares_raw, 1.0)),
        terminal_blend_gordon_weight=0.60,
        terminal_blend_exit_weight=0.40,
        invested_capital_start=float(invested_capital_start),
        ronic_terminal=float(ronic_terminal),
        non_operating_assets=float(non_operating_assets),
        minority_interest=float(
            _bounded(
                minority_interest_raw,
                0.0,
                float(revenue_base) * 2.0,
                0.0,
                field_name="minority_interest",
                source=minority_interest_source,
                events=clamp_events,
            )
        ),
        preferred_equity=float(
            _bounded(
                preferred_equity_raw,
                0.0,
                float(revenue_base) * 2.0,
                0.0,
                field_name="preferred_equity",
                source=preferred_equity_source,
                events=clamp_events,
            )
        ),
        pension_deficit=float(
            _bounded(
                pension_deficit_raw,
                0.0,
                float(revenue_base) * 2.0,
                0.0,
                field_name="pension_deficit",
                source=pension_deficit_source,
                events=clamp_events,
            )
        ),
        lease_liabilities=float(
            _bounded(
                lease_liabilities_raw,
                0.0,
                float(revenue_base) * 2.0,
                0.0,
                field_name="lease_liabilities",
                source=lease_liabilities_source,
                events=clamp_events,
            )
        ),
        options_value=float(
            _bounded(
                options_value_raw,
                0.0,
                float(revenue_base) * 2.0,
                0.0,
                field_name="options_value",
                source=options_value_source,
                events=clamp_events,
            )
        ),
        convertibles_value=float(
            _bounded(
                convertibles_value_raw,
                0.0,
                float(revenue_base) * 2.0,
                0.0,
                field_name="convertibles_value",
                source=convertibles_value_source,
                events=clamp_events,
            )
        ),
        cost_of_equity=float(cost_of_equity),
        debt_weight=float(debt_weight),
        cogs_pct_of_revenue=float(cogs_pct_of_revenue),
    )

    source_lineage = {
        "revenue_base": revenue_source,
        "revenue_growth_near": growth_source,
        "revenue_growth_mid": growth_source,
        "revenue_growth_terminal": "default",
        "growth_source_detail": growth_source_detail,
        "revenue_period_type": revenue_period_type,
        "growth_period_type": growth_period_type,
        "revenue_alignment_flag": revenue_alignment_flag,
        "revenue_data_quality_flag": revenue_data_quality_flag,
        "ebit_margin_start": margin_source,
        "ebit_margin_target": "default",
        "tax_rate_start": tax_source,
        "tax_rate_target": tax_source,
        "capex_pct_start": capex_source,
        "capex_pct_target": capex_source,
        "da_pct_start": da_source,
        "da_pct_target": da_source,
        "dso_start": dso_source,
        "dso_target": dso_target_source,
        "dio_start": dio_source,
        "dio_target": dio_target_source,
        "dpo_start": dpo_source,
        "dpo_target": dpo_target_source,
        "wacc": "yfinance_capm",
        "cost_of_equity": "yfinance_capm",
        "debt_weight": "yfinance_capm",
        "exit_multiple": exit_source,
        "exit_metric": "sector_policy",
        "net_debt": net_debt_source,
        "shares_outstanding": shares_source,
        "invested_capital_start": invested_capital_source,
        "ronic_terminal": ronic_terminal_source,
        "non_operating_assets": non_operating_assets_source,
        "minority_interest": minority_interest_source,
        "preferred_equity": preferred_equity_source,
        "pension_deficit": pension_deficit_source,
        "lease_liabilities": lease_liabilities_source,
        "options_value": options_value_source,
        "convertibles_value": convertibles_value_source,
        "cogs_pct_of_revenue": cogs_pct_source,
        "annual_dilution_pct": "default",
        "risk_free_rate": f"fred_live:{rf_override:.4f}" if _fred_rf is not None else f"valuation_policy:{rf_override:.4f}",
        "equity_risk_premium": f"valuation_policy:{policy_erp:.4f}",
    }

    story_profile, story_profile_source = resolve_story_driver_profile(
        ticker=ticker,
        sector=sector,
    )
    story_adjustments: dict[str, Any] | None = None
    source_lineage["story_profile"] = story_profile_source
    source_lineage["story_driver_mode"] = "judgment_context_only"
    if apply_story_overlay:
        # Legacy diagnostic only. Official forward assumptions are authored by
        # the judgment layer and reach the model solely through PM approval.
        story_adjustments = apply_story_driver_adjustments(
            drivers,
            story_profile,
            authority=story_authority_for_source(story_profile_source),
        )
        source_lineage["story_driver_mode"] = "legacy_provisional_overlay"

        growth_story_active = (
            abs(float(story_adjustments.get("growth_add", 0.0))) > 1e-12
            or abs(
                float(
                    story_adjustments.get(
                        "cyclicality_growth_multiplier",
                        1.0,
                    )
                )
                - 1.0
            )
            > 1e-12
        )
        if growth_story_active:
            source_lineage["revenue_growth_near"] = (
                f"{source_lineage['revenue_growth_near']}|"
                f"{story_profile_source}"
            )
            source_lineage["revenue_growth_mid"] = (
                f"{source_lineage['revenue_growth_mid']}|"
                f"{story_profile_source}"
            )

        margin_story_active = (
            abs(float(story_adjustments.get("margin_add", 0.0))) > 1e-12
        )
        if margin_story_active:
            source_lineage["ebit_margin_target"] = story_profile_source

        wacc_story_active = (
            abs(
                float(
                    story_adjustments.get(
                        "cyclicality_wacc_add",
                        0.0,
                    )
                )
                + float(
                    story_adjustments.get(
                        "governance_wacc_add",
                        0.0,
                    )
                )
            )
            > 1e-12
        )
        if wacc_story_active:
            source_lineage["wacc"] = (
                f"{source_lineage['wacc']}|{story_profile_source}"
            )
            source_lineage["cost_of_equity"] = (
                f"{source_lineage['cost_of_equity']}|"
                f"{story_profile_source}"
            )

        capex_story_active = (
            abs(
                float(
                    story_adjustments.get(
                        "capex_target_add",
                        0.0,
                    )
                )
            )
            > 1e-12
        )
        da_story_active = (
            abs(
                float(
                    story_adjustments.get(
                        "da_target_add",
                        0.0,
                    )
                )
            )
            > 1e-12
        )
        if capex_story_active:
            source_lineage["capex_pct_target"] = story_profile_source
        if da_story_active:
            source_lineage["da_pct_target"] = story_profile_source

        exit_cyc_mult = float(
            story_adjustments.get(
                "exit_multiple_cyclicality_multiplier",
                1.0,
            )
        )
        exit_gov_mult = float(
            story_adjustments.get(
                "exit_multiple_governance_multiplier",
                1.0,
            )
        )
        exit_mult_story_active = (
            abs(exit_cyc_mult * exit_gov_mult - 1.0) > 1e-12
        )
        if exit_mult_story_active:
            source_lineage["exit_multiple"] = (
                f"{source_lineage['exit_multiple']}|"
                f"{story_profile_source}"
            )

    if apply_overrides:
        _apply_overrides(drivers, source_lineage, ticker=ticker, sector=sector)
        method_override = _load_wacc_methodology_override(ticker)
        if method_override:
            mode = method_override["mode"]
            selected_method = method_override.get("selected_method")
            weights = method_override.get("weights") or {}
            try:
                if mode == "single_method" and selected_method in wacc_method_results:
                    selected_wacc_result = wacc_method_results[selected_method]
                    selected_label = selected_method
                elif mode == "blended":
                    selected_wacc_result = blend_wacc_results(wacc_method_results, weights)
                    selected_label = "blended"
                else:
                    selected_wacc_result = None
                    selected_label = None
                if selected_wacc_result is not None:
                    drivers.wacc = float(
                        _bounded(
                            getattr(selected_wacc_result, "wacc", 0.09),
                            0.04,
                            0.20,
                            float(drivers.wacc),
                            field_name="wacc",
                            source=f"wacc_methodology:{selected_label}",
                            events=clamp_events,
                        )
                    )
                    drivers.cost_of_equity = float(
                        _bounded(
                            getattr(selected_wacc_result, "cost_of_equity", None),
                            0.04,
                            0.30,
                            float(getattr(drivers, "cost_of_equity", drivers.wacc + 0.015)),
                            field_name="cost_of_equity",
                            source=f"wacc_methodology:{selected_label}",
                            events=clamp_events,
                        )
                    )
                    selected_equity_weight = getattr(selected_wacc_result, "equity_weight", None)
                    selected_debt_weight = getattr(selected_wacc_result, "debt_weight", None)
                    if selected_debt_weight is None and selected_equity_weight is not None:
                        selected_debt_weight = 1.0 - selected_equity_weight
                    drivers.debt_weight = float(
                        _bounded(
                            selected_debt_weight,
                            0.00,
                            0.80,
                            float(getattr(drivers, "debt_weight", 0.20)),
                            field_name="debt_weight",
                            source=f"wacc_methodology:{selected_label}",
                            events=clamp_events,
                        )
                    )
                    source_lineage["wacc"] = f"wacc_methodology:{selected_label}"
                    source_lineage["cost_of_equity"] = f"wacc_methodology:{selected_label}"
                    source_lineage["debt_weight"] = f"wacc_methodology:{selected_label}"
                    wacc_result = selected_wacc_result
            except Exception:
                pass

    ledger_operating_cash, ledger_excess_cash = _split_cash(
        float(drivers.revenue_base),
        float(cash_raw),
    )
    ledger_debt_ex_leases = float(total_debt_raw) - (
        float(lease_liabilities_raw) if debt_includes_leases else 0.0
    )
    unclaimed_bridge_lines = _unclaimed_bridge_lines_from_snapshots(
        ciq,
        edgar_bridge,
    )
    bridge_period_end = (
        str((ciq or {}).get("as_of_date") or as_of_date)
        if (ciq or {}).get("as_of_date") or as_of_date
        else None
    )
    bridge_currency = str((ciq or {}).get("currency") or "USD").upper()
    claim_ledger = _build_ev_bridge_claim_ledger(
        total_debt=float(total_debt_raw),
        total_debt_source=total_debt_source,
        total_cash=float(cash_raw),
        cash_source=cash_source,
        debt_includes_leases=debt_includes_leases,
        lease_liabilities=float(lease_liabilities_raw),
        lease_liabilities_source=lease_liabilities_source,
        component_values_usd={
            "revenue_base": float(drivers.revenue_base),
            "net_debt": ledger_debt_ex_leases - ledger_operating_cash,
            "non_operating_assets": ledger_excess_cash,
            "lease_liabilities": float(drivers.lease_liabilities),
            "minority_interest": float(drivers.minority_interest),
            "preferred_equity": float(drivers.preferred_equity),
            "pension_deficit": float(drivers.pension_deficit),
            "options_value": float(drivers.options_value),
            "convertibles_value": float(drivers.convertibles_value),
        },
        reported_component_values_usd={
            "minority_interest": float(minority_interest_raw),
            "preferred_equity": float(preferred_equity_raw),
            "pension_deficit": float(pension_deficit_raw),
            "options_value": float(options_value_raw),
            "convertibles_value": float(convertibles_value_raw),
        },
        component_sources={
            "minority_interest": minority_interest_source,
            "preferred_equity": preferred_equity_source,
            "pension_deficit": pension_deficit_source,
            "options_value": options_value_source,
            "convertibles_value": convertibles_value_source,
        },
        unclaimed_reported_lines_usd=unclaimed_bridge_lines,
        currency=bridge_currency,
        period_end=bridge_period_end,
    )
    reconciled_bridge = ReconciledEVBridge.from_ledger(claim_ledger)
    legacy_bridge = ReconciledEVBridge(
        net_debt=(
            float(total_debt_raw) - float(cash_raw)
        )
        / claim_ledger.unit_scale,
        lease_liabilities=(
            0.0
            if debt_includes_leases
            else float(lease_liabilities_raw) / claim_ledger.unit_scale
        ),
        non_operating_assets=(
            ledger_excess_cash / claim_ledger.unit_scale
        ),
        minority_interest=reconciled_bridge.minority_interest,
        preferred_equity=reconciled_bridge.preferred_equity,
        pension_deficit=reconciled_bridge.pension_deficit,
        options_value=reconciled_bridge.options_value,
        convertibles_value=reconciled_bridge.convertibles_value,
    )
    (
        bridge_cutover,
        valuation_readiness,
        valuation_status,
    ) = _bridge_cutover_and_readiness(
        ledger=claim_ledger,
        legacy_bridge=legacy_bridge,
        reconciled_bridge=reconciled_bridge,
        readiness=readiness,
    )
    for component in EV_BRIDGE_COMPONENTS:
        setattr(
            drivers,
            component,
            float(getattr(reconciled_bridge, component)) * claim_ledger.unit_scale,
        )
    ciq_comps = _reprice_ciq_comps_with_bridge(
        ciq_comps,
        bridge=reconciled_bridge,
    )
    operating_cash_policy = {
        "policy": "min(total_cash, revenue_base * rate)",
        "rate": OPERATING_CASH_REVENUE_RATE,
        "source": "pm_decision_2026-07-25",
        "operating_cash_usd": float(ledger_operating_cash),
        "classification_range_usd": [0.0, float(ledger_operating_cash)],
        # Reallocating cash between operating and excess classifications does not
        # change equity while every dollar remains consumed exactly once.
        "equity_value_effect_range_usd": [0.0, 0.0],
    }

    default_resolution = _default_resolution_report(
        drivers=drivers,
        source_lineage=source_lineage,
        defaults=defaults,
        ciq_comps_detail=ciq_comps_detail,
    )
    source_lineage["default_resolution_status"] = default_resolution["status"]

    return ValuationInputsWithLineage(
        ticker=ticker,
        company_name=mkt.get("name", ""),
        sector=sector,
        industry=industry,
        current_price=price,
        as_of_date=(ciq or {}).get("as_of_date") if ciq else as_of_date,
        model_applicability_status=determine_model_applicability(sector, industry),
        drivers=drivers,
        source_lineage=source_lineage,
        ciq_lineage={
            "snapshot_used": bool(ciq),
            "snapshot_run_id": (ciq or {}).get("run_id") if ciq else None,
            "snapshot_source_file": (ciq or {}).get("source_file") if ciq else None,
            "snapshot_as_of_date": (ciq or {}).get("as_of_date") if ciq else None,
            "comps_used": bool(ciq_comps),
            "comps_run_id": (ciq_comps or {}).get("run_id") if ciq_comps else None,
            "comps_source_file": (ciq_comps or {}).get("source_file") if ciq_comps else None,
            "comps_as_of_date": (ciq_comps or {}).get("as_of_date") if ciq_comps else None,
            "peer_count": (ciq_comps or {}).get("peer_count") if ciq_comps else None,
            "peer_median_tev_ebitda_ltm": (ciq_comps or {}).get("peer_median_tev_ebitda_ltm") if ciq_comps else None,
            "peer_median_tev_ebit_ltm": (ciq_comps or {}).get("peer_median_tev_ebit_ltm") if ciq_comps else None,
            "peer_median_pe_ltm": (ciq_comps or {}).get("peer_median_pe_ltm") if ciq_comps else None,
            "comps_iv_ev_ebitda": (ciq_comps or {}).get("implied_price_ev_ebitda") if ciq_comps else None,
            "comps_iv_ev_ebit": (ciq_comps or {}).get("implied_price_ev_ebit") if ciq_comps else None,
            "comps_iv_pe": (ciq_comps or {}).get("implied_price_pe") if ciq_comps else None,
            "comps_iv_base": (ciq_comps or {}).get("implied_price_base") if ciq_comps else None,
            "comps_bridge_basis": (ciq_comps or {}).get("bridge_basis") if ciq_comps else None,
            "comps_ev_to_equity_adjustment_mm": (ciq_comps or {}).get("target_ev_to_equity_adjustment") if ciq_comps else None,
            "public_comps_fallback_used": public_comps_fallback_used,
            "public_comps_fallback_source_file": ((ciq_comps_detail or {}).get("source_lineage") or {}).get("source_file") if public_comps_fallback_used else None,
            "public_comps_fallback_peer_count": len((ciq_comps_detail or {}).get("peers") or []) if public_comps_fallback_used else None,
        },
        wacc_inputs={
            # Top-level WACC values are the effective drivers used by DCF after
            # story adjustments, PM overrides, or methodology selection.
            "wacc": drivers.wacc,
            "cost_of_equity": drivers.cost_of_equity,
            "beta_relevered": getattr(wacc_result, "beta_relevered", None),
            "beta_unlevered_median": getattr(wacc_result, "beta_unlevered_median", None),
            "size_premium": getattr(wacc_result, "size_premium", None),
            "equity_weight": getattr(wacc_result, "equity_weight", None),
            "debt_weight": drivers.debt_weight,
            "peers_used": getattr(wacc_result, "peers_used", None),
            "risk_free_rate": rf_override,
            "equity_risk_premium": policy_erp,
            "selected_method_wacc": getattr(wacc_result, "wacc", None),
            "selected_method_cost_of_equity": getattr(wacc_result, "cost_of_equity", None),
            "method_results": {
                method: {
                    "wacc": getattr(result, "wacc", None),
                    "cost_of_equity": getattr(result, "cost_of_equity", None),
                    "beta_relevered": getattr(result, "beta_relevered", None),
                    "equity_weight": getattr(result, "equity_weight", None),
                    "debt_weight": getattr(result, "debt_weight", None),
                    "peers_used": getattr(result, "peers_used", None),
                }
                for method, result in wacc_method_results.items()
            },
            "selected_methodology": _load_wacc_methodology_override(ticker) if apply_overrides else None,
        },
        story_profile=asdict(story_profile),
        story_adjustments=story_adjustments,
        wacc_method_spread_high=_wacc_spread_high,
        clamp_events=tuple(clamp_events),
        default_resolution=default_resolution,
        claim_ledger=claim_ledger.to_dict(),
        operating_cash_policy=operating_cash_policy,
        bridge_cutover=bridge_cutover,
        valuation_readiness=valuation_readiness,
        valuation_status=valuation_status,
    )
