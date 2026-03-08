from dataclasses import dataclass

from src.stage_02_valuation import batch_runner
from src.stage_02_valuation.professional_dcf import (
    DCFComputationResult,
    ForecastDrivers,
    ProjectionYear,
    ScenarioSpec,
    TerminalBreakdown,
)


@dataclass
class _Inputs:
    ticker: str = "TEST"
    company_name: str = "Test Co"
    sector: str = "Technology"
    industry: str = "Software"
    current_price: float = 100.0
    as_of_date: str | None = "2025-12-31"
    model_applicability_status: str = "dcf_applicable"
    drivers: ForecastDrivers | None = None
    source_lineage: dict | None = None
    ciq_lineage: dict | None = None
    wacc_inputs: dict | None = None


class _Prob:
    def __init__(self, results, expected_iv, expected_upside):
        self.scenario_results = results
        self.expected_iv = expected_iv
        self.expected_upside_pct = expected_upside


def _sample_result(iv: float) -> DCFComputationResult:
    projection = ProjectionYear(
        year=1,
        revenue=1_000.0,
        growth_rate=0.1,
        ebit_margin=0.2,
        tax_rate=0.22,
        capex_pct=0.05,
        da_pct=0.03,
        dso=45.0,
        dio=40.0,
        dpo=35.0,
        ebit=200.0,
        nopat=156.0,
        da=30.0,
        capex=50.0,
        ar=123.0,
        inventory=110.0,
        ap=96.0,
        nwc=137.0,
        delta_nwc=10.0,
        fcff=126.0,
        discount_factor=1.09,
        pv_fcff=115.0,
    )
    breakdown = TerminalBreakdown(
        method_used="blend",
        gordon_valid=True,
        exit_valid=True,
        tv_gordon=1800.0,
        tv_exit=1700.0,
        tv_blended=1760.0,
        pv_tv_gordon=760.0,
        pv_tv_exit=720.0,
        pv_tv_blended=744.0,
    )
    return DCFComputationResult(
        scenario="base",
        intrinsic_value_per_share=iv,
        enterprise_value=1200.0,
        equity_value=1000.0,
        pv_fcff_sum=456.0,
        iv_gordon=11.0,
        iv_exit=10.0,
        iv_blended=iv,
        terminal_breakdown=breakdown,
        projections=[projection],
        tv_method_fallback_flag=False,
        tv_pct_of_ev=0.62,
        roic_consistency_flag=False,
        nwc_driver_quality_flag=True,
    )


def _sample_inputs() -> _Inputs:
    return _Inputs(
        drivers=ForecastDrivers(
            revenue_base=800_000_000.0,
            revenue_growth_near=0.12,
            revenue_growth_mid=0.08,
            revenue_growth_terminal=0.03,
            ebit_margin_start=0.22,
            ebit_margin_target=0.23,
            tax_rate_start=0.19,
            tax_rate_target=0.23,
            capex_pct_start=0.07,
            capex_pct_target=0.06,
            da_pct_start=0.04,
            da_pct_target=0.035,
            dso_start=45.0,
            dso_target=45.0,
            dio_start=40.0,
            dio_target=40.0,
            dpo_start=35.0,
            dpo_target=35.0,
            wacc=0.09,
            exit_multiple=17.0,
            exit_metric="ev_ebitda",
            net_debt=700_000_000.0,
            shares_outstanding=50_000_000.0,
        ),
        source_lineage={
            "revenue_base": "ciq",
            "revenue_growth_near": "ciq",
            "ebit_margin_start": "ciq",
            "capex_pct_start": "ciq",
            "da_pct_start": "ciq",
            "tax_rate_start": "ciq",
            "net_debt": "ciq",
            "shares_outstanding": "ciq",
            "exit_multiple": "ciq_comps",
        },
        ciq_lineage={
            "snapshot_used": True,
            "snapshot_run_id": 42,
            "snapshot_source_file": "ciq_cleandata.xlsx",
            "snapshot_as_of_date": "2025-12-31",
            "comps_used": True,
            "comps_run_id": 9,
            "comps_source_file": "ciq_cleandata.xlsx",
            "comps_as_of_date": "2025-12-31",
            "peer_count": 8,
            "peer_median_tev_ebitda_ltm": 17.0,
            "peer_median_pe_ltm": 24.0,
            "comps_iv_ev_ebitda": 118.0,
            "comps_iv_pe": 126.0,
            "comps_iv_base": 122.0,
        },
        wacc_inputs={
            "wacc": 0.09,
            "cost_of_equity": 0.11,
            "beta_relevered": 1.1,
            "beta_unlevered_median": 0.9,
            "size_premium": 0.01,
            "equity_weight": 0.8,
            "peers_used": ["TEST"],
        },
    )


def test_value_single_ticker_prefers_ciq_lineage(monkeypatch):
    monkeypatch.setattr(batch_runner, "build_valuation_inputs", lambda ticker: _sample_inputs())
    monkeypatch.setattr(batch_runner, "default_scenario_specs", lambda: [
        ScenarioSpec(name="bear", probability=0.2),
        ScenarioSpec(name="base", probability=0.6),
        ScenarioSpec(name="bull", probability=0.2),
    ])
    monkeypatch.setattr(
        batch_runner,
        "run_probabilistic_valuation",
        lambda drivers, scenario_specs, current_price: _Prob(
            {
                "bear": _sample_result(90.0),
                "base": _sample_result(120.0),
                "bull": _sample_result(150.0),
            },
            expected_iv=120.0,
            expected_upside=0.20,
        ),
    )
    monkeypatch.setattr(
        batch_runner.md_client,
        "get_market_data",
        lambda ticker: {
            "name": "Test Co",
            "market_cap": 5_000_000_000.0,
            "enterprise_value": 6_000_000_000.0,
            "pe_trailing": 20.0,
            "pe_forward": 18.0,
            "ev_ebitda": 12.0,
            "profit_margin": 0.10,
            "free_cashflow": 100_000_000.0,
            "beta": 1.2,
            "analyst_target_mean": 130.0,
            "analyst_recommendation": "buy",
            "number_of_analysts": 10,
        },
    )

    result = batch_runner.value_single_ticker("TEST")

    assert result is not None
    assert result["revenue_source"] == "ciq"
    assert result["growth_source"] == "ciq"
    assert result["ebit_margin_source"] == "ciq"
    assert result["capex_source"] == "ciq"
    assert result["da_source"] == "ciq"
    assert result["tax_source"] == "ciq"
    assert result["net_debt_source"] == "ciq"
    assert result["shares_source"] == "ciq"
    assert result["ciq_snapshot_used"] is True
    assert result["ciq_run_id"] == 42


def test_value_single_ticker_uses_ciq_comps_fields(monkeypatch):
    monkeypatch.setattr(batch_runner, "build_valuation_inputs", lambda ticker: _sample_inputs())
    monkeypatch.setattr(batch_runner, "default_scenario_specs", lambda: [
        ScenarioSpec(name="bear", probability=0.2),
        ScenarioSpec(name="base", probability=0.6),
        ScenarioSpec(name="bull", probability=0.2),
    ])
    monkeypatch.setattr(
        batch_runner,
        "run_probabilistic_valuation",
        lambda drivers, scenario_specs, current_price: _Prob(
            {
                "bear": _sample_result(90.0),
                "base": _sample_result(120.0),
                "bull": _sample_result(150.0),
            },
            expected_iv=120.0,
            expected_upside=0.20,
        ),
    )
    monkeypatch.setattr(
        batch_runner.md_client,
        "get_market_data",
        lambda ticker: {
            "name": "Test Co",
            "market_cap": 5_000_000_000.0,
            "enterprise_value": 6_000_000_000.0,
            "pe_trailing": 20.0,
            "pe_forward": 18.0,
            "ev_ebitda": 12.0,
            "profit_margin": 0.10,
            "free_cashflow": 100_000_000.0,
            "beta": 1.2,
            "analyst_target_mean": 130.0,
            "analyst_recommendation": "buy",
            "number_of_analysts": 10,
        },
    )

    result = batch_runner.value_single_ticker("TEST")

    assert result is not None
    assert result["exit_multiple_source"] == "ciq_comps"
    assert result["ciq_peer_count"] == 8
    assert result["peer_median_tev_ebitda_ltm"] == 17.0
    assert result["comps_iv_base"] == 122.0
    assert result["comps_upside_pct"] == 22.0
