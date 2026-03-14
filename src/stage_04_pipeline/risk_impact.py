from __future__ import annotations

from dataclasses import asdict, replace

from src.stage_02_valuation.input_assembler import build_valuation_inputs
from src.stage_02_valuation.professional_dcf import ForecastDrivers, ScenarioSpec, run_dcf_professional
from src.stage_02_valuation.templates.ic_memo import RiskImpactOutput


_SHIFT_BOUNDS = {
    "revenue_growth_near_bps": (-1500, 0),
    "revenue_growth_mid_bps": (-1000, 0),
    "ebit_margin_bps": (-1500, 0),
    "wacc_bps": (0, 300),
    "exit_multiple_pct": (-50.0, 0.0),
}


def _clamp(value, low, high):
    return max(low, min(high, value))


def _apply_overlay(drivers: ForecastDrivers, overlay) -> tuple[ForecastDrivers, dict[str, float]]:
    shifts = {
        "revenue_growth_near_bps": int(_clamp(int(overlay.revenue_growth_near_bps), *_SHIFT_BOUNDS["revenue_growth_near_bps"])),
        "revenue_growth_mid_bps": int(_clamp(int(overlay.revenue_growth_mid_bps), *_SHIFT_BOUNDS["revenue_growth_mid_bps"])),
        "ebit_margin_bps": int(_clamp(int(overlay.ebit_margin_bps), *_SHIFT_BOUNDS["ebit_margin_bps"])),
        "wacc_bps": int(_clamp(int(overlay.wacc_bps), *_SHIFT_BOUNDS["wacc_bps"])),
        "exit_multiple_pct": float(_clamp(float(overlay.exit_multiple_pct), *_SHIFT_BOUNDS["exit_multiple_pct"])),
    }
    updated = replace(
        drivers,
        revenue_growth_near=drivers.revenue_growth_near + shifts["revenue_growth_near_bps"] / 10_000.0,
        revenue_growth_mid=drivers.revenue_growth_mid + shifts["revenue_growth_mid_bps"] / 10_000.0,
        ebit_margin_start=drivers.ebit_margin_start + shifts["ebit_margin_bps"] / 10_000.0,
        ebit_margin_target=drivers.ebit_margin_target + shifts["ebit_margin_bps"] / 10_000.0,
        wacc=drivers.wacc + shifts["wacc_bps"] / 10_000.0,
        exit_multiple=drivers.exit_multiple * (1.0 + shifts["exit_multiple_pct"] / 100.0),
    )
    return updated, shifts


def quantify_risk_impact(
    ticker: str,
    risk_output: RiskImpactOutput,
    *,
    as_of_date: str | None = None,
    apply_overrides: bool = True,
) -> dict:
    ticker = ticker.upper().strip()
    inputs = build_valuation_inputs(ticker, as_of_date=as_of_date, apply_overrides=apply_overrides)
    if inputs is None:
        return {"ticker": ticker, "available": False, "overlay_results": []}

    base_spec = ScenarioSpec(name="base", probability=1.0)
    base_result = run_dcf_professional(inputs.drivers, base_spec)
    base_iv = round(base_result.intrinsic_value_per_share, 2)

    overlays = list((risk_output.overlays or [])[:3])
    overlay_probability_sum = sum(max(0.0, min(1.0, float(overlay.probability))) for overlay in overlays)
    residual_base_probability = round(max(0.0, 1.0 - overlay_probability_sum), 4)

    overlay_results: list[dict] = []
    weighted_iv = residual_base_probability * base_iv

    for overlay in overlays:
        adjusted_drivers, applied_shifts = _apply_overlay(inputs.drivers, overlay)
        result = run_dcf_professional(adjusted_drivers, ScenarioSpec(name="risk_overlay", probability=1.0))
        stressed_iv = round(result.intrinsic_value_per_share, 2)
        iv_delta = round(stressed_iv - base_iv, 2)
        iv_delta_pct = round((stressed_iv / base_iv - 1.0) * 100.0, 2) if base_iv else None
        probability = max(0.0, min(1.0, float(overlay.probability)))
        weighted_iv += probability * stressed_iv
        overlay_results.append(
            {
                "risk_name": overlay.risk_name,
                "source_type": overlay.source_type,
                "source_text": overlay.source_text,
                "probability": probability,
                "horizon": overlay.horizon,
                "confidence": overlay.confidence,
                "rationale": overlay.rationale,
                "applied_shifts": applied_shifts,
                "stressed_iv": stressed_iv,
                "iv_delta": iv_delta,
                "iv_delta_pct": iv_delta_pct,
            }
        )

    risk_adjusted_expected_iv = round(weighted_iv, 2)
    risk_adjusted_delta_pct = round((risk_adjusted_expected_iv / base_iv - 1.0), 4) if base_iv else None

    return {
        "ticker": ticker,
        "available": True,
        "company_name": inputs.company_name,
        "base_iv": base_iv,
        "current_price": inputs.current_price,
        "residual_base_probability": residual_base_probability,
        "risk_adjusted_expected_iv": risk_adjusted_expected_iv,
        "risk_adjusted_delta_pct": risk_adjusted_delta_pct,
        "overlay_results": overlay_results,
        "driver_snapshot": asdict(inputs.drivers),
    }
