from __future__ import annotations

from src.stage_02_valuation.input_assembler import ValuationInputsWithLineage
from src.stage_02_valuation.professional_dcf import ForecastDrivers
from src.stage_02_valuation.templates.ic_memo import RiskImpactOutput, RiskScenarioOverlay


def _drivers() -> ForecastDrivers:
    return ForecastDrivers(
        revenue_base=12_000_000_000,
        revenue_growth_near=0.08,
        revenue_growth_mid=0.05,
        revenue_growth_terminal=0.025,
        ebit_margin_start=0.16,
        ebit_margin_target=0.19,
        tax_rate_start=0.22,
        tax_rate_target=0.23,
        capex_pct_start=0.04,
        capex_pct_target=0.04,
        da_pct_start=0.03,
        da_pct_target=0.03,
        dso_start=52.0,
        dso_target=50.0,
        dio_start=44.0,
        dio_target=42.0,
        dpo_start=39.0,
        dpo_target=41.0,
        wacc=0.09,
        exit_multiple=11.0,
        exit_metric="ev_ebitda",
        net_debt=2_200_000_000,
        shares_outstanding=910_000_000,
        non_operating_assets=150_000_000,
        lease_liabilities=250_000_000,
    )


def _inputs() -> ValuationInputsWithLineage:
    return ValuationInputsWithLineage(
        ticker="IBM",
        company_name="IBM",
        sector="Technology",
        industry="IT Services",
        current_price=105.0,
        as_of_date="2026-03-14",
        model_applicability_status="dcf_applicable",
        drivers=_drivers(),
        source_lineage={},
        ciq_lineage={},
        wacc_inputs={},
        story_profile=None,
        story_adjustments=None,
    )


def test_quantify_risk_impact_revalues_overlays_and_expected_iv(monkeypatch):
    from src.stage_04_pipeline.risk_impact import quantify_risk_impact

    monkeypatch.setattr(
        "src.stage_04_pipeline.risk_impact.build_valuation_inputs",
        lambda ticker, as_of_date=None, apply_overrides=True: _inputs(),
    )

    risk_output = RiskImpactOutput(
        overlays=[
            RiskScenarioOverlay(
                risk_name="Competitive Displacement",
                source_type="sentiment_risk_narrative",
                source_text="Frontier AI vendors compress pricing.",
                probability=0.25,
                horizon="24m",
                revenue_growth_near_bps=-400,
                revenue_growth_mid_bps=-300,
                ebit_margin_bps=-250,
                wacc_bps=75,
                exit_multiple_pct=-10.0,
                rationale="Moat erosion would hit growth, margin, and terminal multiple.",
                confidence="medium",
            )
        ]
    )

    out = quantify_risk_impact("IBM", risk_output)

    assert out["available"] is True
    assert out["base_iv"] > 0
    assert out["risk_adjusted_expected_iv"] < out["base_iv"]
    assert out["residual_base_probability"] == 0.75
    assert len(out["overlay_results"]) == 1
    overlay = out["overlay_results"][0]
    assert overlay["risk_name"] == "Competitive Displacement"
    assert overlay["stressed_iv"] < out["base_iv"]
    assert overlay["iv_delta_pct"] < 0


def test_quantify_risk_impact_clamps_extreme_inputs(monkeypatch):
    from src.stage_04_pipeline.risk_impact import quantify_risk_impact

    monkeypatch.setattr(
        "src.stage_04_pipeline.risk_impact.build_valuation_inputs",
        lambda ticker, as_of_date=None, apply_overrides=True: _inputs(),
    )

    risk_output = RiskImpactOutput(
        overlays=[
            RiskScenarioOverlay(
                risk_name="Extreme Downside",
                source_type="filings_red_flag",
                source_text="Everything breaks.",
                probability=0.5,
                horizon="12m",
                revenue_growth_near_bps=-9999,
                revenue_growth_mid_bps=-9999,
                ebit_margin_bps=-9999,
                wacc_bps=9999,
                exit_multiple_pct=-99.0,
                rationale="Stress test",
                confidence="low",
            )
        ]
    )

    out = quantify_risk_impact("IBM", risk_output)
    overlay = out["overlay_results"][0]

    assert overlay["applied_shifts"]["revenue_growth_near_bps"] == -1500
    assert overlay["applied_shifts"]["revenue_growth_mid_bps"] == -1000
    assert overlay["applied_shifts"]["ebit_margin_bps"] == -1500
    assert overlay["applied_shifts"]["wacc_bps"] == 300
    assert overlay["applied_shifts"]["exit_multiple_pct"] == -50.0


def test_quantify_risk_impact_returns_base_when_no_overlays(monkeypatch):
    from src.stage_04_pipeline.risk_impact import quantify_risk_impact

    monkeypatch.setattr(
        "src.stage_04_pipeline.risk_impact.build_valuation_inputs",
        lambda ticker, as_of_date=None, apply_overrides=True: _inputs(),
    )

    out = quantify_risk_impact("IBM", RiskImpactOutput())

    assert out["available"] is True
    assert out["overlay_results"] == []
    assert out["risk_adjusted_expected_iv"] == out["base_iv"]
    assert out["risk_adjusted_delta_pct"] == 0.0
