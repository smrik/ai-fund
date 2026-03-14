"""Unified agent recommendations — collect, persist, and apply agent suggestions
to valuation_overrides.yaml after PM approval.

Data flow:
  --full pipeline → extract_recommendations() → write config/agent_recommendations_{TICKER}.yaml
  PM reviews (CLI --review / --approve, or Streamlit tab)
  apply_approved_to_overrides() → config/valuation_overrides.yaml
  load_valuation_overrides.cache_clear() → re-run picks up changes
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field, replace as dc_replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from config import ROOT_DIR
from src.stage_00_data.sec_filing_metrics import SecFilingMetrics
from src.stage_02_valuation.professional_dcf import (
    ForecastDrivers,
    default_scenario_specs,
    run_dcf_professional,
)

RECS_DIR = ROOT_DIR / "config"
OVERRIDES_PATH = ROOT_DIR / "config" / "valuation_overrides.yaml"


# ── Data structures ────────────────────────────────────────────────────────────

@dataclass
class Recommendation:
    agent: str           # "qoe" | "accounting_recast" | "industry"
    field: str           # ForecastDrivers field name
    current_value: float | None
    proposed_value: float | dict
    confidence: str      # "high" | "medium" | "low"
    rationale: str
    citation: str | None = None
    status: str = "pending"   # "pending" | "approved" | "rejected"


@dataclass
class TickerRecommendations:
    ticker: str
    generated_at: str
    current_iv_base: float | None
    recommendations: list[Recommendation] = field(default_factory=list)


# ── Path helper ────────────────────────────────────────────────────────────────

def _recs_path(ticker: str) -> Path:
    return RECS_DIR / f"agent_recommendations_{ticker.upper()}.yaml"


# ── Serialization helpers ──────────────────────────────────────────────────────

def _recs_to_dict(recs: TickerRecommendations) -> dict:
    return {
        "ticker": recs.ticker,
        "generated_at": recs.generated_at,
        "current_iv_base": recs.current_iv_base,
        "recommendations": [
            {
                "agent": r.agent,
                "field": r.field,
                "current_value": r.current_value,
                "proposed_value": r.proposed_value,
                "confidence": r.confidence,
                "rationale": r.rationale,
                "citation": r.citation,
                "status": r.status,
            }
            for r in recs.recommendations
        ],
    }


def _recs_from_dict(data: dict) -> TickerRecommendations:
    return TickerRecommendations(
        ticker=data.get("ticker", ""),
        generated_at=data.get("generated_at", ""),
        current_iv_base=data.get("current_iv_base"),
        recommendations=[
            Recommendation(
                agent=r.get("agent", ""),
                field=r.get("field", ""),
                current_value=r.get("current_value"),
                proposed_value=r.get("proposed_value"),
                confidence=r.get("confidence", "medium"),
                rationale=r.get("rationale", ""),
                citation=r.get("citation"),
                status=r.get("status", "pending"),
            )
            for r in (data.get("recommendations") or [])
        ],
    )


# ── Main extraction ────────────────────────────────────────────────────────────

def extract_recommendations(
    ticker: str,
    qoe_result: dict,
    accounting_recast_result: dict,
    industry_result: dict,
    current_drivers: ForecastDrivers | None,
    current_iv_base: float | None = None,
    filings_metrics: SecFilingMetrics | None = None,
) -> TickerRecommendations:
    """Collect agent recommendations into a unified structure.

    Preserves existing approved/rejected status — re-runs do not reset PM decisions.
    """
    ticker = ticker.upper().strip()

    # Load existing statuses so re-runs don't reset PM decisions
    existing_statuses: dict[str, str] = {}
    existing_path = _recs_path(ticker)
    if existing_path.exists():
        try:
            raw = yaml.safe_load(existing_path.read_text(encoding="utf-8")) or {}
            for r in raw.get("recommendations", []):
                key = f"{r.get('agent')}:{r.get('field')}"
                status = r.get("status", "pending")
                if status in {"approved", "rejected"}:
                    existing_statuses[key] = status
        except Exception:
            pass

    recs: list[Recommendation] = []
    revenue_base = getattr(current_drivers, "revenue_base", None)

    # ── QoE → ebit_margin_start ───────────────────────────────────────────────
    if qoe_result:
        llm = qoe_result.get("llm") or {}
        pending = llm.get("dcf_ebit_override_pending", False)
        if pending:
            normalized_ebit = llm.get("normalized_ebit")
            haircut_pct = llm.get("ebit_haircut_pct")
            current_margin = getattr(current_drivers, "ebit_margin_start", None)
            proposed_margin = None
            if normalized_ebit and revenue_base and revenue_base > 0:
                proposed_margin = round(float(normalized_ebit) / float(revenue_base), 6)
            if proposed_margin is not None:
                adjustments = llm.get("ebit_adjustments") or []
                if adjustments:
                    rationale = (
                        f"QoE EBIT haircut {haircut_pct:+.1f}%: "
                        + "; ".join(
                            f"{a.get('item', '')} "
                            f"({a.get('direction', '')}{abs(a.get('amount') or 0):.1f}M)"
                            for a in adjustments[:3]
                        )
                    )
                else:
                    hp = f"{haircut_pct:+.1f}%" if haircut_pct is not None else "unknown"
                    rationale = f"QoE EBIT normalisation: {hp} haircut"
                key = "qoe:ebit_margin_start"
                recs.append(Recommendation(
                    agent="qoe",
                    field="ebit_margin_start",
                    current_value=current_margin,
                    proposed_value=proposed_margin,
                    confidence=llm.get("llm_confidence") or "medium",
                    rationale=rationale,
                    status=existing_statuses.get(key, "pending"),
                ))

    # ── AccountingRecast → EV bridge items + optional EBIT ───────────────────
    if accounting_recast_result:
        candidates = accounting_recast_result.get("override_candidates") or {}
        confidence = accounting_recast_result.get("confidence") or "low"
        pm_notes = accounting_recast_result.get("pm_review_notes") or ""
        reclasses = accounting_recast_result.get("balance_sheet_reclassifications") or []

        ev_bridge_fields = [
            "non_operating_assets",
            "lease_liabilities",
            "minority_interest",
            "preferred_equity",
            "pension_deficit",
        ]
        for fld in ev_bridge_fields:
            proposed = candidates.get(fld)
            if proposed is None:
                continue
            current = getattr(current_drivers, fld, None)
            if current is not None and abs(float(proposed) - float(current)) <= 1_000_000:
                continue  # immaterial delta
            field_rationale = next(
                (r.get("rationale") or "" for r in reclasses if r.get("proposed_driver_field") == fld),
                pm_notes or f"Accounting recast: {fld} reclassification",
            )
            citation = next(
                (r.get("citation_text") for r in reclasses if r.get("proposed_driver_field") == fld),
                None,
            )
            key = f"accounting_recast:{fld}"
            recs.append(Recommendation(
                agent="accounting_recast",
                field=fld,
                current_value=float(current) if current is not None else None,
                proposed_value=float(proposed),
                confidence=confidence,
                rationale=field_rationale,
                citation=citation,
                status=existing_statuses.get(key, "pending"),
            ))

        # EBIT normalisation from recast (may conflict with QoE — keep as alternative)
        recast_ebit = candidates.get("normalized_ebit")
        if recast_ebit is not None and revenue_base and revenue_base > 0:
            proposed_margin = round(float(recast_ebit) / float(revenue_base), 6)
            current_margin = getattr(current_drivers, "ebit_margin_start", None)
            if current_margin is None or abs(proposed_margin - float(current_margin)) > 0.005:
                adj_list = accounting_recast_result.get("income_statement_adjustments") or []
                if adj_list:
                    rationale = "Accounting recast EBIT: " + "; ".join(
                        f"{a.get('item', '')} "
                        f"({a.get('proposed_ebit_direction', '')}{abs(a.get('amount') or 0):.1f}M)"
                        for a in adj_list[:3]
                    )
                else:
                    rationale = pm_notes or "Accounting recast EBIT normalisation"
                key = "accounting_recast:ebit_margin_start"
                recs.append(Recommendation(
                    agent="accounting_recast",
                    field="ebit_margin_start",
                    current_value=float(current_margin) if current_margin is not None else None,
                    proposed_value=proposed_margin,
                    confidence=confidence,
                    rationale=rationale,
                    status=existing_statuses.get(key, "pending"),
                ))

    # ── Industry → growth + margin benchmarks ────────────────────────────────
    if industry_result:
        ind_growth_near = industry_result.get("consensus_growth_near")
        ind_growth_mid = industry_result.get("consensus_growth_mid")
        ind_margin = industry_result.get("margin_benchmark")
        ind_confidence = industry_result.get("confidence") or "medium"

        growth_near_current = getattr(current_drivers, "revenue_growth_near", None)
        growth_mid_current = getattr(current_drivers, "revenue_growth_mid", None)
        margin_target_current = getattr(current_drivers, "ebit_margin_target", None)

        if ind_growth_near is not None and growth_near_current is not None:
            if abs(float(ind_growth_near) - float(growth_near_current)) > 0.01:
                key = "industry:revenue_growth_near"
                recs.append(Recommendation(
                    agent="industry",
                    field="revenue_growth_near",
                    current_value=float(growth_near_current),
                    proposed_value=float(ind_growth_near),
                    confidence=ind_confidence,
                    rationale=(
                        f"Industry consensus near-term growth: {float(ind_growth_near)*100:.1f}% "
                        f"vs current {float(growth_near_current)*100:.1f}%"
                    ),
                    status=existing_statuses.get(key, "pending"),
                ))

        if ind_growth_mid is not None and growth_mid_current is not None:
            if abs(float(ind_growth_mid) - float(growth_mid_current)) > 0.01:
                key = "industry:revenue_growth_mid"
                recs.append(Recommendation(
                    agent="industry",
                    field="revenue_growth_mid",
                    current_value=float(growth_mid_current),
                    proposed_value=float(ind_growth_mid),
                    confidence=ind_confidence,
                    rationale=(
                        f"Industry consensus mid-term growth: {float(ind_growth_mid)*100:.1f}% "
                        f"vs current {float(growth_mid_current)*100:.1f}%"
                    ),
                    status=existing_statuses.get(key, "pending"),
                ))

        if ind_margin is not None and margin_target_current is not None:
            if abs(float(ind_margin) - float(margin_target_current)) > 0.01:
                key = "industry:ebit_margin_target"
                recs.append(Recommendation(
                    agent="industry",
                    field="ebit_margin_target",
                    current_value=float(margin_target_current),
                    proposed_value=float(ind_margin),
                    confidence=ind_confidence,
                    rationale=(
                        f"Industry margin benchmark: {float(ind_margin)*100:.1f}% "
                        f"vs current target {float(margin_target_current)*100:.1f}%"
                    ),
                    status=existing_statuses.get(key, "pending"),
                ))

    # ── Deterministic filings metrics → review-gated growth + start margin ──
    if filings_metrics and current_drivers is not None:
        citation = (
            f"SEC XBRL {filings_metrics.source_form} {filings_metrics.source_filing_date}"
            if filings_metrics.source_filing_date
            else f"SEC XBRL {filings_metrics.source_form}"
        )

        if (
            filings_metrics.revenue_cagr_3y is not None
            and getattr(current_drivers, "revenue_growth_near", None) is not None
            and abs(float(filings_metrics.revenue_cagr_3y) - float(current_drivers.revenue_growth_near)) > 0.02
        ):
            key = "filings:revenue_growth_near"
            recs.append(Recommendation(
                agent="filings",
                field="revenue_growth_near",
                current_value=float(current_drivers.revenue_growth_near),
                proposed_value=float(filings_metrics.revenue_cagr_3y),
                confidence="high",
                rationale=(
                    "Deterministic SEC/XBRL 3-year revenue CAGR differs materially "
                    "from the current model near-term growth assumption."
                ),
                citation=citation,
                status=existing_statuses.get(key, "pending"),
            ))

        if (
            filings_metrics.ebit_margin_avg_3y is not None
            and getattr(current_drivers, "ebit_margin_start", None) is not None
            and abs(float(filings_metrics.ebit_margin_avg_3y) - float(current_drivers.ebit_margin_start)) > 0.01
        ):
            key = "filings:ebit_margin_start"
            recs.append(Recommendation(
                agent="filings",
                field="ebit_margin_start",
                current_value=float(current_drivers.ebit_margin_start),
                proposed_value=float(filings_metrics.ebit_margin_avg_3y),
                confidence="high",
                rationale=(
                    "Deterministic SEC/XBRL 3-year average EBIT margin differs materially "
                    "from the current model starting EBIT margin."
                ),
                citation=citation,
                status=existing_statuses.get(key, "pending"),
            ))

    return TickerRecommendations(
        ticker=ticker,
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        current_iv_base=current_iv_base,
        recommendations=recs,
    )


# ── Persistence ────────────────────────────────────────────────────────────────

def write_recommendations(recs: TickerRecommendations) -> Path:
    """Serialize to config/agent_recommendations_{TICKER}.yaml."""
    path = _recs_path(recs.ticker)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.dump(
            _recs_to_dict(recs),
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


def load_recommendations(ticker: str) -> TickerRecommendations | None:
    """Load from YAML, or return None if file not found."""
    path = _recs_path(ticker.upper())
    if not path.exists():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return _recs_from_dict(data)
    except Exception:
        return None


# ── Apply to overrides ────────────────────────────────────────────────────────

def apply_approved_to_overrides(ticker: str) -> int:
    """Write all approved recommendations into config/valuation_overrides.yaml.

    Returns count of items written.
    """
    ticker = ticker.upper().strip()
    recs = load_recommendations(ticker)
    if recs is None:
        return 0
    approved = [r for r in recs.recommendations if r.status == "approved"]
    if not approved:
        return 0

    overrides: dict = {"global": {}, "sectors": {}, "tickers": {}}
    if OVERRIDES_PATH.exists():
        loaded = yaml.safe_load(OVERRIDES_PATH.read_text(encoding="utf-8")) or {}
        overrides.update(loaded)
        overrides.setdefault("global", {})
        overrides.setdefault("sectors", {})
        overrides.setdefault("tickers", {})

    ticker_overrides: dict = overrides["tickers"].setdefault(ticker, {})
    count = 0
    for rec in approved:
        if isinstance(rec.proposed_value, (int, float)):
            ticker_overrides[rec.field] = rec.proposed_value
            count += 1

    OVERRIDES_PATH.parent.mkdir(parents=True, exist_ok=True)
    OVERRIDES_PATH.write_text(
        yaml.dump(overrides, default_flow_style=False, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return count


# ── What-if preview ────────────────────────────────────────────────────────────

def preview_with_approvals(
    ticker: str,
    approved_fields: list[str],
) -> dict[str, Any]:
    """Run DCF with a temporary drivers copy that has selected field overrides applied.

    Returns:
        {
          "current_iv":  {"bear": float, "base": float, "bull": float},
          "proposed_iv": {"bear": float, "base": float, "bull": float},
          "delta_pct":   {"bear": float, "base": float, "bull": float},
        }
    Returns {} if valuation inputs cannot be assembled.
    """
    from src.stage_02_valuation.input_assembler import build_valuation_inputs  # local to avoid circular

    ticker = ticker.upper().strip()
    inputs = build_valuation_inputs(ticker)
    if inputs is None:
        return {}

    specs = default_scenario_specs()

    def _run_scenarios(drivers: ForecastDrivers) -> dict[str, float | None]:
        result: dict[str, float | None] = {}
        for spec in specs:
            try:
                dcf = run_dcf_professional(drivers, spec)
                result[spec.name] = round(dcf.intrinsic_value_per_share, 2)
            except Exception:
                result[spec.name] = None
        return result

    current_iv = _run_scenarios(inputs.drivers)

    if not approved_fields:
        return {
            "current_iv": current_iv,
            "proposed_iv": current_iv,
            "delta_pct": {k: 0.0 for k in current_iv},
        }

    recs = load_recommendations(ticker)
    if recs is None:
        return {
            "current_iv": current_iv,
            "proposed_iv": current_iv,
            "delta_pct": {k: 0.0 for k in current_iv},
        }

    override_kwargs = {
        r.field: r.proposed_value
        for r in recs.recommendations
        if r.field in approved_fields and isinstance(r.proposed_value, (int, float))
        and hasattr(inputs.drivers, r.field)
    }

    if not override_kwargs:
        return {
            "current_iv": current_iv,
            "proposed_iv": current_iv,
            "delta_pct": {k: 0.0 for k in current_iv},
        }

    drivers_proposed = dc_replace(inputs.drivers, **override_kwargs)
    proposed_iv = _run_scenarios(drivers_proposed)

    delta_pct: dict[str, float | None] = {}
    for scenario in current_iv:
        cur = current_iv.get(scenario)
        prop = proposed_iv.get(scenario)
        if cur and cur > 0 and prop is not None:
            delta_pct[scenario] = round((prop / cur - 1) * 100, 1)
        else:
            delta_pct[scenario] = None

    return {
        "current_iv": current_iv,
        "proposed_iv": proposed_iv,
        "delta_pct": delta_pct,
    }
