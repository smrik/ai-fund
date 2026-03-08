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
    p = ProjectionYear(
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
    tb = TerminalBreakdown(
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
        terminal_breakdown=tb,
        projections=[p],
        tv_method_fallback_flag=False,
        tv_pct_of_ev=0.62,
        roic_consistency_flag=False,
        nwc_driver_quality_flag=True,
    )


def test_value_single_ticker_returns_prob_weighted_fields(monkeypatch):
    monkeypatch.setattr(batch_runner, "build_valuation_inputs", lambda ticker: _Inputs(
        drivers=ForecastDrivers(
            revenue_base=800.0,
            revenue_growth_near=0.12,
            revenue_growth_mid=0.08,
            revenue_growth_terminal=0.03,
            ebit_margin_start=0.2,
            ebit_margin_target=0.22,
            tax_rate_start=0.21,
            tax_rate_target=0.23,
            capex_pct_start=0.05,
            capex_pct_target=0.04,
            da_pct_start=0.03,
            da_pct_target=0.025,
            dso_start=45.0,
            dso_target=44.0,
            dio_start=40.0,
            dio_target=38.0,
            dpo_start=35.0,
            dpo_target=36.0,
            wacc=0.09,
            exit_multiple=14.0,
            exit_metric="ev_ebitda",
            net_debt=100.0,
            shares_outstanding=50.0,
        ),
        source_lineage={"revenue_base": "ciq", "exit_multiple": "ciq_comps", "revenue_growth_near": "ciq", "ebit_margin_start": "ciq", "capex_pct_start": "ciq", "da_pct_start": "ciq", "tax_rate_start": "ciq", "net_debt": "ciq", "shares_outstanding": "ciq"},
        ciq_lineage={"snapshot_used": True, "snapshot_run_id": 7, "snapshot_source_file": "ciq.xlsx", "snapshot_as_of_date": "2025-12-31", "comps_used": True, "comps_run_id": 8, "comps_source_file": "ciq.xlsx", "comps_as_of_date": "2025-12-31", "peer_count": 8, "peer_median_tev_ebitda_ltm": 14.0, "peer_median_pe_ltm": 20.0, "comps_iv_ev_ebitda": 130.0, "comps_iv_pe": 120.0, "comps_iv_base": 125.0},
        wacc_inputs={"wacc": 0.09, "cost_of_equity": 0.11, "beta_relevered": 1.0, "beta_unlevered_median": 0.8, "size_premium": 0.01, "equity_weight": 0.8, "peers_used": ["A", "B"]},
    ))
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
                "bear": _sample_result(80.0),
                "base": _sample_result(100.0),
                "bull": _sample_result(120.0),
            },
            expected_iv=100.0,
            expected_upside=0.0,
        ),
    )
    monkeypatch.setattr(batch_runner.md_client, "get_market_data", lambda ticker: {"name": "Test Co", "analyst_target_mean": 110.0, "analyst_recommendation": "buy", "number_of_analysts": 9, "market_cap": 1000.0, "enterprise_value": 1200.0, "pe_trailing": 15.0, "pe_forward": 12.0, "ev_ebitda": 9.0, "profit_margin": 0.1, "free_cashflow": 10.0, "beta": 1.0})

    out = batch_runner.value_single_ticker("TEST")

    assert out is not None
    assert out["expected_iv"] == 100.0
    assert out["expected_upside_pct"] == 0.0
    assert out["iv_gordon"] == 11.0
    assert out["iv_exit"] == 10.0
    assert out["iv_blended"] == 100.0
    assert out["model_applicability_status"] == "dcf_applicable"


def test_value_single_ticker_alt_model_required(monkeypatch):
    monkeypatch.setattr(batch_runner, "build_valuation_inputs", lambda ticker: _Inputs(
        sector="Financial Services",
        industry="Banks",
        model_applicability_status="alt_model_required",
        drivers=ForecastDrivers(
            revenue_base=800.0,
            revenue_growth_near=0.1,
            revenue_growth_mid=0.07,
            revenue_growth_terminal=0.03,
            ebit_margin_start=0.2,
            ebit_margin_target=0.2,
            tax_rate_start=0.21,
            tax_rate_target=0.23,
            capex_pct_start=0.04,
            capex_pct_target=0.04,
            da_pct_start=0.02,
            da_pct_target=0.02,
            dso_start=45.0,
            dso_target=45.0,
            dio_start=40.0,
            dio_target=40.0,
            dpo_start=35.0,
            dpo_target=35.0,
            wacc=0.1,
            exit_multiple=10.0,
            exit_metric="ev_ebit",
            net_debt=100.0,
            shares_outstanding=50.0,
        ),
        source_lineage={},
        ciq_lineage={},
        wacc_inputs={},
    ))
    monkeypatch.setattr(batch_runner.md_client, "get_market_data", lambda ticker: {"name": "Bank Co", "analyst_target_mean": None, "analyst_recommendation": None, "number_of_analysts": None, "market_cap": None, "enterprise_value": None, "pe_trailing": None, "pe_forward": None, "ev_ebitda": None, "profit_margin": None, "free_cashflow": None, "beta": None})

    out = batch_runner.value_single_ticker("BANK")

    assert out is not None
    assert out["model_applicability_status"] == "alt_model_required"
    assert out["iv_base"] is None
    assert out["expected_iv"] is None


def test_value_single_ticker_implied_growth_uses_professional_reverse_dcf(monkeypatch):
    monkeypatch.setattr(batch_runner, "build_valuation_inputs", lambda ticker: _Inputs(
        drivers=ForecastDrivers(
            revenue_base=800.0,
            revenue_growth_near=0.12,
            revenue_growth_mid=0.08,
            revenue_growth_terminal=0.03,
            ebit_margin_start=0.2,
            ebit_margin_target=0.22,
            tax_rate_start=0.21,
            tax_rate_target=0.23,
            capex_pct_start=0.05,
            capex_pct_target=0.04,
            da_pct_start=0.03,
            da_pct_target=0.025,
            dso_start=45.0,
            dso_target=44.0,
            dio_start=40.0,
            dio_target=38.0,
            dpo_start=35.0,
            dpo_target=36.0,
            wacc=0.09,
            exit_multiple=14.0,
            exit_metric="ev_ebitda",
            net_debt=100.0,
            shares_outstanding=50.0,
        ),
        source_lineage={"revenue_base": "ciq", "exit_multiple": "ciq_comps", "revenue_growth_near": "ciq", "ebit_margin_start": "ciq", "capex_pct_start": "ciq", "da_pct_start": "ciq", "tax_rate_start": "ciq", "net_debt": "ciq", "shares_outstanding": "ciq"},
        ciq_lineage={"snapshot_used": True, "snapshot_run_id": 7, "snapshot_source_file": "ciq.xlsx", "snapshot_as_of_date": "2025-12-31", "comps_used": True, "comps_run_id": 8, "comps_source_file": "ciq.xlsx", "comps_as_of_date": "2025-12-31", "peer_count": 8, "peer_median_tev_ebitda_ltm": 14.0, "peer_median_pe_ltm": 20.0, "comps_iv_ev_ebitda": 130.0, "comps_iv_pe": 120.0, "comps_iv_base": 125.0},
        wacc_inputs={"wacc": 0.09, "cost_of_equity": 0.11, "beta_relevered": 1.0, "beta_unlevered_median": 0.8, "size_premium": 0.01, "equity_weight": 0.8, "peers_used": ["A", "B"]},
    ))
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
                "bear": _sample_result(80.0),
                "base": _sample_result(100.0),
                "bull": _sample_result(120.0),
            },
            expected_iv=100.0,
            expected_upside=0.0,
        ),
    )

    calls = {"count": 0}

    def _fake_reverse(drivers, target_price, scenario="base"):
        calls["count"] += 1
        assert scenario == "base"
        return 0.1234

    monkeypatch.setattr(batch_runner, "reverse_dcf_professional", _fake_reverse)
    monkeypatch.setattr(batch_runner.md_client, "get_market_data", lambda ticker: {"name": "Test Co", "analyst_target_mean": 110.0, "analyst_recommendation": "buy", "number_of_analysts": 9, "market_cap": 1000.0, "enterprise_value": 1200.0, "pe_trailing": 15.0, "pe_forward": 12.0, "ev_ebitda": 9.0, "profit_margin": 0.1, "free_cashflow": 10.0, "beta": 1.0})

    out = batch_runner.value_single_ticker("TEST")

    assert out is not None
    assert calls["count"] == 1
    assert out["implied_growth_pct"] == 12.3


def test_value_single_ticker_emits_revenue_alignment_metadata(monkeypatch):
    monkeypatch.setattr(batch_runner, "build_valuation_inputs", lambda ticker: _Inputs(
        drivers=ForecastDrivers(
            revenue_base=800.0,
            revenue_growth_near=0.12,
            revenue_growth_mid=0.08,
            revenue_growth_terminal=0.03,
            ebit_margin_start=0.2,
            ebit_margin_target=0.22,
            tax_rate_start=0.21,
            tax_rate_target=0.23,
            capex_pct_start=0.05,
            capex_pct_target=0.04,
            da_pct_start=0.03,
            da_pct_target=0.025,
            dso_start=45.0,
            dso_target=44.0,
            dio_start=40.0,
            dio_target=38.0,
            dpo_start=35.0,
            dpo_target=36.0,
            wacc=0.09,
            exit_multiple=14.0,
            exit_metric="ev_ebitda",
            net_debt=100.0,
            shares_outstanding=50.0,
        ),
        source_lineage={
            "revenue_base": "ciq",
            "revenue_growth_near": "ciq",
            "growth_source_detail": "ciq_cagr_3yr",
            "revenue_period_type": "ttm",
            "growth_period_type": "cagr_3yr",
            "revenue_alignment_flag": "mixed_ttm_vs_cagr",
            "revenue_data_quality_flag": "needs_review",
            "ebit_margin_start": "ciq",
            "capex_pct_start": "ciq",
            "da_pct_start": "ciq",
            "tax_rate_start": "ciq",
            "exit_multiple": "ciq_comps",
            "net_debt": "ciq",
            "shares_outstanding": "ciq",
        },
        ciq_lineage={"snapshot_used": False, "comps_used": False},
        wacc_inputs={"wacc": 0.09, "cost_of_equity": 0.11, "peers_used": []},
    ))
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
                "bear": _sample_result(80.0),
                "base": _sample_result(100.0),
                "bull": _sample_result(120.0),
            },
            expected_iv=100.0,
            expected_upside=0.0,
        ),
    )
    monkeypatch.setattr(batch_runner, "reverse_dcf_professional", lambda drivers, target_price, scenario="base": 0.1)
    monkeypatch.setattr(batch_runner.md_client, "get_market_data", lambda ticker: {
        "name": "Test Co",
        "analyst_target_mean": 110.0,
        "analyst_recommendation": "buy",
        "number_of_analysts": 9,
        "market_cap": 1000.0,
        "enterprise_value": 1200.0,
        "pe_trailing": 15.0,
        "pe_forward": 12.0,
        "ev_ebitda": 9.0,
        "profit_margin": 0.1,
        "free_cashflow": 10.0,
        "beta": 1.0,
    })

    out = batch_runner.value_single_ticker("TEST")

    assert out is not None
    assert out["growth_source_detail"] == "ciq_cagr_3yr"
    assert out["revenue_period_type"] == "ttm"
    assert out["growth_period_type"] == "cagr_3yr"
    assert out["revenue_alignment_flag"] == "mixed_ttm_vs_cagr"
    assert out["revenue_data_quality_flag"] == "needs_review"


def test_value_single_ticker_emits_professional_bridge_and_health_fields(monkeypatch):
    monkeypatch.setattr(batch_runner, "build_valuation_inputs", lambda ticker: _Inputs(
        drivers=ForecastDrivers(
            revenue_base=800.0,
            revenue_growth_near=0.12,
            revenue_growth_mid=0.08,
            revenue_growth_terminal=0.03,
            ebit_margin_start=0.2,
            ebit_margin_target=0.22,
            tax_rate_start=0.21,
            tax_rate_target=0.23,
            capex_pct_start=0.05,
            capex_pct_target=0.04,
            da_pct_start=0.03,
            da_pct_target=0.025,
            dso_start=45.0,
            dso_target=44.0,
            dio_start=40.0,
            dio_target=38.0,
            dpo_start=35.0,
            dpo_target=36.0,
            wacc=0.09,
            exit_multiple=14.0,
            exit_metric="ev_ebitda",
            net_debt=100.0,
            shares_outstanding=50.0,
            non_operating_assets=12.0,
            minority_interest=2.0,
            preferred_equity=1.0,
            pension_deficit=0.5,
            lease_liabilities=0.25,
            options_value=0.1,
            convertibles_value=0.2,
            cost_of_equity=0.11,
        ),
        source_lineage={"revenue_base": "ciq", "exit_multiple": "ciq_comps", "revenue_growth_near": "ciq", "ebit_margin_start": "ciq", "capex_pct_start": "ciq", "da_pct_start": "ciq", "tax_rate_start": "ciq", "net_debt": "ciq", "shares_outstanding": "ciq"},
        ciq_lineage={"snapshot_used": True, "snapshot_run_id": 7, "snapshot_source_file": "ciq.xlsx", "snapshot_as_of_date": "2025-12-31", "comps_used": True, "comps_run_id": 8, "comps_source_file": "ciq.xlsx", "comps_as_of_date": "2025-12-31", "peer_count": 8, "peer_median_tev_ebitda_ltm": 14.0, "peer_median_pe_ltm": 20.0, "comps_iv_ev_ebitda": 130.0, "comps_iv_pe": 120.0, "comps_iv_base": 125.0},
        wacc_inputs={"wacc": 0.09, "cost_of_equity": 0.11, "beta_relevered": 1.0, "beta_unlevered_median": 0.8, "size_premium": 0.01, "equity_weight": 0.8, "peers_used": ["A", "B"]},
    ))
    monkeypatch.setattr(batch_runner, "default_scenario_specs", lambda: [
        ScenarioSpec(name="bear", probability=0.2),
        ScenarioSpec(name="base", probability=0.6),
        ScenarioSpec(name="bull", probability=0.2),
    ])

    def _rich_result(iv: float):
        result = _sample_result(iv)
        result.enterprise_value_operations = 1_500.0
        result.enterprise_value_total = 1_540.0
        result.non_operating_assets = 80.0
        result.non_equity_claims = 40.0
        result.ep_enterprise_value = 1_510.0
        result.ep_intrinsic_value_per_share = 99.0
        result.dcf_ep_gap_pct = 0.0067
        result.ep_reconcile_flag = True
        result.fcfe_intrinsic_value_per_share = 101.0
        result.fcfe_equity_value = 1_010.0
        result.fcfe_pv_sum = 550.0
        result.fcfe_terminal_value = 460.0
        result.cost_of_equity_used = 0.11
        result.health_flags = {
            "tv_high_flag": False,
            "tv_extreme_flag": False,
            "terminal_growth_guardrail_flag": False,
            "terminal_ronic_guardrail_flag": False,
            "terminal_denominator_guardrail_flag": False,
            "tv_method_fallback_flag": False,
            "fcff_interest_contamination_flag": False,
            "ep_reconcile_flag": True,
        }
        result.terminal_breakdown.terminal_growth = 0.03
        result.terminal_breakdown.ronic_terminal = 0.12
        result.terminal_breakdown.fcff_11_bridge = 140.0
        result.terminal_breakdown.fcff_11_value_driver = 135.0
        result.terminal_breakdown.gordon_formula_mode = "value_driver"
        return result

    monkeypatch.setattr(
        batch_runner,
        "run_probabilistic_valuation",
        lambda drivers, scenario_specs, current_price: _Prob(
            {
                "bear": _rich_result(80.0),
                "base": _rich_result(100.0),
                "bull": _rich_result(120.0),
            },
            expected_iv=100.0,
            expected_upside=0.0,
        ),
    )
    monkeypatch.setattr(batch_runner, "reverse_dcf_professional", lambda drivers, target_price, scenario="base": 0.1)
    monkeypatch.setattr(batch_runner.md_client, "get_market_data", lambda ticker: {
        "name": "Test Co",
        "analyst_target_mean": 110.0,
        "analyst_recommendation": "buy",
        "number_of_analysts": 9,
        "market_cap": 1000.0,
        "enterprise_value": 1200.0,
        "pe_trailing": 15.0,
        "pe_forward": 12.0,
        "ev_ebitda": 9.0,
        "profit_margin": 0.1,
        "free_cashflow": 10.0,
        "beta": 1.0,
    })

    out = batch_runner.value_single_ticker("TEST")

    assert out is not None
    assert out["ev_operations_mm"] == 0.0
    assert out["ev_total_mm"] == 0.0
    assert out["non_operating_assets_mm"] == 0.0
    assert out["non_equity_claims_mm"] == 0.0
    assert out["ep_iv_base"] == 99.0
    assert out["ep_reconcile_flag"] is True
    assert out["fcfe_iv_base"] == 101.0
    assert out["fcfe_equity_mm"] == 0.0
    assert out["cost_of_equity_model"] == 11.0
    assert out["tv_gordon_mm"] == 0.0
    assert out["tv_exit_mm"] == 0.0
    assert out["tv_blended_mm"] == 0.0
    assert out["pv_tv_gordon_mm"] == 0.0
    assert out["pv_tv_exit_mm"] == 0.0
    assert out["pv_tv_blended_mm"] == 0.0
    assert out["terminal_growth_pct"] == 3.0
    assert out["terminal_ronic_pct"] == 12.0
    assert out["terminal_fcff_11_bridge_mm"] == 0.0
    assert out["terminal_fcff_11_value_driver_mm"] == 0.0
    assert out["gordon_formula_mode"] == "value_driver"
    assert out["health_tv_extreme_flag"] is False
    assert out["health_terminal_growth_guardrail_flag"] is False
    assert out["health_terminal_ronic_guardrail_flag"] is False
    assert out["health_terminal_denominator_guardrail_flag"] is False
    assert out["health_fcff_interest_contamination_flag"] is False


def test_alt_model_required_emits_empty_professional_fields(monkeypatch):
    monkeypatch.setattr(batch_runner, "build_valuation_inputs", lambda ticker: _Inputs(
        sector="Financial Services",
        industry="Banks",
        model_applicability_status="alt_model_required",
        drivers=ForecastDrivers(
            revenue_base=800.0,
            revenue_growth_near=0.1,
            revenue_growth_mid=0.07,
            revenue_growth_terminal=0.03,
            ebit_margin_start=0.2,
            ebit_margin_target=0.2,
            tax_rate_start=0.21,
            tax_rate_target=0.23,
            capex_pct_start=0.04,
            capex_pct_target=0.04,
            da_pct_start=0.02,
            da_pct_target=0.02,
            dso_start=45.0,
            dso_target=45.0,
            dio_start=40.0,
            dio_target=40.0,
            dpo_start=35.0,
            dpo_target=35.0,
            wacc=0.1,
            exit_multiple=10.0,
            exit_metric="ev_ebit",
            net_debt=100.0,
            shares_outstanding=50.0,
        ),
        source_lineage={},
        ciq_lineage={},
        wacc_inputs={},
    ))
    monkeypatch.setattr(batch_runner.md_client, "get_market_data", lambda ticker: {
        "name": "Bank Co",
        "analyst_target_mean": None,
        "analyst_recommendation": None,
        "number_of_analysts": None,
        "market_cap": None,
        "enterprise_value": None,
        "pe_trailing": None,
        "pe_forward": None,
        "ev_ebitda": None,
        "profit_margin": None,
        "free_cashflow": None,
        "beta": None,
    })

    out = batch_runner.value_single_ticker("BANK")

    assert out is not None
    assert out["model_applicability_status"] == "alt_model_required"
    assert out["ep_iv_base"] is None
    assert out["fcfe_iv_base"] is None
    assert out["ev_operations_mm"] is None
    assert out["ev_total_mm"] is None
    assert out["health_tv_extreme_flag"] is None
    assert out["terminal_growth_pct"] is None
