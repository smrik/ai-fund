from __future__ import annotations

from typing import Any


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _scenario_value(dcf: dict[str, Any], scenario: str, field: str) -> float | None:
    for row in _as_list(dcf.get("scenario_summary")):
        if not isinstance(row, dict):
            continue
        if str(row.get("scenario") or "").lower() == scenario:
            return _float(row.get(field))
    return None


def _field_row(assumptions: dict[str, Any], field_name: str) -> dict[str, Any]:
    for row in _as_list(assumptions.get("fields")):
        if isinstance(row, dict) and row.get("field") == field_name:
            return row
    return {}


def _gap_pct(left: float | None, right: float | None) -> float | None:
    if left is None or right in (None, 0):
        return None
    return (left / right - 1.0) * 100.0


def _flag(code: str, severity: str, title: str, detail: str, pm_check: str) -> dict[str, str]:
    return {
        "code": code,
        "severity": severity,
        "title": title,
        "detail": detail,
        "pm_check": pm_check,
    }


def build_professional_finance_review(
    *,
    summary: dict[str, Any],
    dcf: dict[str, Any],
    assumptions: dict[str, Any],
    comps: dict[str, Any],
    batch_row: dict[str, Any],
) -> dict[str, Any]:
    """Investment-committee style quality gates for a ticker valuation output."""
    flags: list[dict[str, str]] = []
    integrity = _as_dict(dcf.get("model_integrity") or summary.get("readiness"))
    terminal = _as_dict(dcf.get("terminal_bridge"))
    tv_pct = _float(integrity.get("tv_pct_of_ev") or terminal.get("tv_pct_of_ev"))
    if tv_pct is not None and tv_pct >= 75.0:
        flags.append(
            _flag(
                "terminal_value_dominance",
                "high",
                "Terminal value dominates enterprise value",
                f"Terminal value is {tv_pct:.1f}% of EV.",
                "Stress terminal growth, exit multiple, and WACC before relying on upside.",
            )
        )
    elif tv_pct is not None and tv_pct >= 65.0:
        flags.append(
            _flag(
                "terminal_value_watch",
                "medium",
                "Terminal value is a large share of EV",
                f"Terminal value is {tv_pct:.1f}% of EV.",
                "Show a downside sensitivity where terminal assumptions normalize.",
            )
        )

    base_iv = _float(summary.get("base_iv")) or _scenario_value(dcf, "base", "intrinsic_value")
    bull_iv = _float(summary.get("bull_iv")) or _scenario_value(dcf, "bull", "intrinsic_value")
    bull_to_base = bull_iv / base_iv if bull_iv is not None and base_iv not in (None, 0) else None
    if bull_to_base is not None and bull_to_base >= 2.5:
        flags.append(
            _flag(
                "bull_case_asymmetry",
                "high",
                "Bull case is extreme versus base case",
                f"Bull IV is {bull_to_base:.1f}x base IV.",
                "Explain the driver bridge from base to bull and consider capping scenario optimism.",
            )
        )
    elif bull_to_base is not None and bull_to_base >= 1.75:
        flags.append(
            _flag(
                "bull_case_watch",
                "medium",
                "Bull case materially exceeds base case",
                f"Bull IV is {bull_to_base:.1f}x base IV.",
                "Confirm bull assumptions are tied to explicit evidence, not generic upside.",
            )
        )

    valuation_range = _as_dict(comps.get("valuation_range"))
    comps_base = _float(
        batch_row.get("comps_model_blended_base")
        or batch_row.get("comps_iv_base")
        or valuation_range.get("blended_base")
        or valuation_range.get("base")
    )
    dcf_vs_comps_gap = _gap_pct(base_iv, comps_base)
    if dcf_vs_comps_gap is not None and abs(dcf_vs_comps_gap) >= 50.0:
        flags.append(
            _flag(
                "dcf_comps_divergence",
                "high",
                "DCF and comps disagree materially",
                f"DCF base IV differs from comps base by {dcf_vs_comps_gap:+.1f}%.",
                "Reconcile whether the DCF moat/growth story justifies the market-multiple gap.",
            )
        )

    near_growth = _field_row(assumptions, "revenue_growth_near")
    effective_growth = _float(near_growth.get("effective_value"))
    baseline_growth = _float(near_growth.get("baseline_value"))
    agent_growth = _float(near_growth.get("agent_value"))
    growth_source = str(near_growth.get("effective_source") or batch_row.get("growth_source") or "unknown")
    growth_gap = _gap_pct(effective_growth, baseline_growth)
    if effective_growth is not None and baseline_growth is not None:
        bps_gap = (effective_growth - baseline_growth) * 10_000.0
        if bps_gap >= 500.0 and growth_source in {"approved_assumption_register", "override_ticker"}:
            flags.append(
                _flag(
                    "growth_override_gap",
                    "high",
                    "Revenue growth override is far above baseline",
                    f"Near-term growth is {effective_growth:.1%} vs baseline {baseline_growth:.1%}; agent/historical reference is {agent_growth:.1%}."
                    if agent_growth is not None
                    else f"Near-term growth is {effective_growth:.1%} vs baseline {baseline_growth:.1%}.",
                    "Require explicit PM rationale or lower the growth path before IC-style use.",
                )
            )
        elif bps_gap >= 250.0:
            flags.append(
                _flag(
                    "growth_override_watch",
                    "medium",
                    "Revenue growth is above baseline",
                    f"Near-term growth is {effective_growth:.1%} vs baseline {baseline_growth:.1%}.",
                    "Check whether recent revenue evidence is already reflected in the model.",
                )
            )

    revenue_quality = str(integrity.get("revenue_data_quality_flag") or batch_row.get("revenue_data_quality_flag") or "")
    if revenue_quality and revenue_quality not in {"ok", "clean", "good"}:
        flags.append(
            _flag(
                "revenue_data_quality",
                "high" if revenue_quality == "needs_review" else "medium",
                "Revenue data quality needs review",
                f"Revenue data quality flag is `{revenue_quality}`.",
                "Align TTM, fiscal-year, and CAGR periods before relying on revenue-growth conclusions.",
            )
        )

    if integrity.get("roic_consistency_flag") is False:
        flags.append(
            _flag(
                "roic_consistency",
                "medium",
                "ROIC consistency flag is false",
                "The DCF reports ROIC consistency as false.",
                "Inspect reinvestment, margin, and terminal ROIC assumptions.",
            )
        )

    severity_rank = {"high": 3, "medium": 2, "low": 1}
    high_count = sum(1 for flag in flags if flag["severity"] == "high")
    medium_count = sum(1 for flag in flags if flag["severity"] == "medium")
    status = "review_required" if high_count else "watch" if medium_count else "clean"
    return {
        "status": status,
        "high_count": high_count,
        "medium_count": medium_count,
        "flags": sorted(flags, key=lambda row: severity_rank.get(row["severity"], 0), reverse=True),
    }
