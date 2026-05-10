from __future__ import annotations

from src.stage_02_valuation.input_assembler import ValuationInputsWithLineage
from src.stage_02_valuation.professional_dcf import ForecastDrivers


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
        source_lineage={
            "revenue_growth_near": "filings_sec_xbrl",
            "ebit_margin_start": "ciq_margin_avg_3yr",
            "wacc": "wacc_peer_beta",
            "exit_multiple": "ciq_summary_comps",
            "net_debt": "yfinance_balance_sheet",
        },
        ciq_lineage={},
        wacc_inputs={},
        story_profile=None,
        story_adjustments=None,
    )


def test_build_dcf_audit_view_shapes_key_tables(monkeypatch):
    from src.stage_04_pipeline.dcf_audit import build_dcf_audit_view

    monkeypatch.setattr(
        "src.stage_04_pipeline.dcf_audit.build_valuation_inputs",
        lambda ticker, as_of_date=None, apply_overrides=True: _inputs(),
    )

    audit = build_dcf_audit_view("IBM")

    assert audit["available"] is True
    assert audit["ticker"] == "IBM"
    assert len(audit["scenario_summary"]) == 4
    assert len(audit["forecast_bridge"]) == 10
    assert audit["terminal_bridge"]["method_used"] in {"blend", "gordon_only", "exit_only"}
    assert "equity_value" in audit["ev_bridge"]
    assert len(audit["driver_rows"]) >= 5
    assert len(audit["sensitivity"]["wacc_x_terminal_growth"]) == 3
    assert len(audit["sensitivity"]["wacc_x_exit_multiple"]) == 3
    assert len(audit["sensitivity"]["long_form"]) == 18
    assert audit["sensitivity"]["metadata"]["wacc_x_terminal_growth"]["row_axis"]["key"] == "wacc"
    assert audit["sensitivity"]["metadata"]["wacc_x_terminal_growth"]["column_axis"]["key"] == "terminal_growth"
    assert audit["sensitivity"]["metadata"]["wacc_x_exit_multiple"]["column_axis"]["key"] == "exit_multiple"
    assert audit["sensitivity"]["metadata"]["wacc_x_terminal_growth"]["summary"]["cell_count"] == 9
    assert {row["grid"] for row in audit["sensitivity"]["summary"]} == {
        "wacc_x_terminal_growth",
        "wacc_x_exit_multiple",
    }
    base_cells = [cell for cell in audit["sensitivity"]["long_form"] if cell["is_base_case"]]
    assert len(base_cells) == 2
    assert "chart_series" in audit
    assert len(audit["chart_series"]["projection_curve"]) == 10
    assert len(audit["chart_series"]["fcff_curve"]) == 10
    assert len(audit["chart_series"]["scenario_iv"]) == 4
    assert len(audit["chart_series"]["ev_bridge_waterfall"]) >= 4
    assert audit["chart_series"]["risk_overlay"] == []


def test_build_dcf_audit_view_returns_unavailable_when_inputs_missing(monkeypatch):
    from src.stage_04_pipeline.dcf_audit import build_dcf_audit_view

    monkeypatch.setattr(
        "src.stage_04_pipeline.dcf_audit.build_valuation_inputs",
        lambda ticker, as_of_date=None, apply_overrides=True: None,
    )

    audit = build_dcf_audit_view("IBM")

    assert audit == {"ticker": "IBM", "available": False}
