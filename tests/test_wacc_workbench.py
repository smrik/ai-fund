from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from db.schema import create_tables
from src.stage_02_valuation.input_assembler import ValuationInputsWithLineage
from src.stage_02_valuation.professional_dcf import ForecastDrivers
from src.stage_02_valuation.wacc import WACCResult


def _drivers(**overrides) -> ForecastDrivers:
    base = ForecastDrivers(
        revenue_base=10_000_000_000,
        revenue_growth_near=0.08,
        revenue_growth_mid=0.06,
        revenue_growth_terminal=0.03,
        ebit_margin_start=0.15,
        ebit_margin_target=0.18,
        tax_rate_start=0.22,
        tax_rate_target=0.23,
        capex_pct_start=0.04,
        capex_pct_target=0.04,
        da_pct_start=0.03,
        da_pct_target=0.03,
        dso_start=50.0,
        dso_target=48.0,
        dio_start=45.0,
        dio_target=42.0,
        dpo_start=40.0,
        dpo_target=42.0,
        wacc=0.09,
        exit_multiple=12.0,
        exit_metric="ev_ebitda",
        net_debt=2_000_000_000,
        shares_outstanding=900_000_000,
        non_operating_assets=100_000_000,
        lease_liabilities=200_000_000,
        cost_of_equity=0.11,
        debt_weight=0.20,
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


def _inputs(drivers: ForecastDrivers) -> ValuationInputsWithLineage:
    return ValuationInputsWithLineage(
        ticker="IBM",
        company_name="IBM",
        sector="Technology",
        industry="IT Services",
        current_price=100.0,
        as_of_date="2026-03-15",
        model_applicability_status="dcf_applicable",
        drivers=drivers,
        source_lineage={"wacc": "yfinance_capm"},
        ciq_lineage={},
        wacc_inputs={},
        story_profile=None,
        story_adjustments=None,
    )


def _wacc_result(*, wacc: float, beta: float, method: str) -> WACCResult:
    return WACCResult(
        wacc=wacc,
        cost_of_equity=round(wacc + 0.02, 5),
        cost_of_debt_after_tax=0.04,
        equity_weight=0.75,
        debt_weight=0.25,
        risk_free_rate=0.045,
        equity_risk_premium=0.05,
        beta_relevered=beta,
        size_premium=0.005,
        beta_unlevered_median=max(beta - 0.2, 0.4),
        peers_used=[f"{method}_peer"],
        peer_betas_unlevered=[max(beta - 0.2, 0.4)],
        target_de_ratio=0.25,
        target_market_cap=100_000_000_000.0,
        target_net_debt=5_000_000_000.0,
    )


def _temp_conn_factory(db_path: Path):
    def _factory():
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        create_tables(conn)
        return conn

    return _factory


def test_build_wacc_workbench_surfaces_methods_and_current_selection(monkeypatch):
    from src.stage_04_pipeline import wacc_workbench

    monkeypatch.setattr(
        wacc_workbench,
        "build_valuation_inputs",
        lambda ticker, apply_overrides=True, as_of_date=None: _inputs(_drivers(wacc=0.083 if apply_overrides else 0.09)),
    )
    monkeypatch.setattr(
        wacc_workbench,
        "get_ciq_comps_detail",
        lambda ticker: {"peers": [{"ticker": "MSFT"}, {"ticker": "ORCL"}]},
    )
    monkeypatch.setattr(
        wacc_workbench,
        "compute_wacc_methodology_set_for_ticker",
        lambda ticker, peer_tickers=None, hist=None, market_data=None: {
            "peer_bottom_up": _wacc_result(wacc=0.09, beta=1.10, method="peer_bottom_up"),
            "industry_proxy": _wacc_result(wacc=0.085, beta=0.98, method="industry_proxy"),
            "self_hamada": _wacc_result(wacc=0.082, beta=0.93, method="self_hamada"),
        },
    )
    monkeypatch.setattr(
        wacc_workbench,
        "load_valuation_overrides",
        lambda: {
            "global": {},
            "sectors": {},
            "tickers": {
                "IBM": {
                    "wacc_methodology": {
                        "mode": "blended",
                        "weights": {
                            "peer_bottom_up": 0.50,
                            "industry_proxy": 0.25,
                            "self_hamada": 0.25,
                        },
                    }
                }
            },
        },
    )

    view = wacc_workbench.build_wacc_workbench("IBM")

    assert view["ticker"] == "IBM"
    assert view["current_selection"]["mode"] == "blended"
    assert view["current_selection"]["weights"]["peer_bottom_up"] == pytest.approx(0.50)
    assert {row["method"] for row in view["methods"]} == {
        "peer_bottom_up",
        "industry_proxy",
        "self_hamada",
    }
    assert view["effective_preview"]["wacc"] == pytest.approx(0.083)


def test_preview_wacc_methodology_selection_revalues_iv(monkeypatch):
    from src.stage_04_pipeline import wacc_workbench

    monkeypatch.setattr(
        wacc_workbench,
        "build_valuation_inputs",
        lambda ticker, apply_overrides=True, as_of_date=None: _inputs(_drivers(wacc=0.09)),
    )
    monkeypatch.setattr(
        wacc_workbench,
        "get_ciq_comps_detail",
        lambda ticker: {"peers": [{"ticker": "MSFT"}, {"ticker": "ORCL"}]},
    )
    monkeypatch.setattr(
        wacc_workbench,
        "compute_wacc_methodology_set_for_ticker",
        lambda ticker, peer_tickers=None, hist=None, market_data=None: {
            "peer_bottom_up": _wacc_result(wacc=0.09, beta=1.10, method="peer_bottom_up"),
            "industry_proxy": _wacc_result(wacc=0.10, beta=0.98, method="industry_proxy"),
            "self_hamada": _wacc_result(wacc=0.082, beta=0.93, method="self_hamada"),
        },
    )
    monkeypatch.setattr(
        wacc_workbench,
        "run_probabilistic_valuation",
        lambda drivers, scenario_specs, current_price=None: SimpleNamespace(
            scenario_results={
                spec.name: SimpleNamespace(
                    intrinsic_value_per_share=round(120 - drivers.wacc * 100 + {"bear": -8, "base": 0, "bull": 10}[spec.name], 2)
                )
                for spec in scenario_specs
            },
            expected_iv=round(120 - drivers.wacc * 100, 2),
            expected_upside_pct=None,
        ),
    )

    preview = wacc_workbench.preview_wacc_methodology_selection(
        "IBM",
        mode="single_method",
        selected_method="industry_proxy",
    )

    assert preview["current_wacc"] == pytest.approx(0.09)
    assert preview["effective_wacc"] == pytest.approx(0.10)
    assert preview["proposed_iv"]["base"] < preview["current_iv"]["base"]


def test_apply_wacc_methodology_selection_persists_yaml_and_audit(monkeypatch, tmp_path):
    from src.stage_04_pipeline import wacc_workbench

    monkeypatch.setattr(
        wacc_workbench,
        "build_valuation_inputs",
        lambda ticker, apply_overrides=True, as_of_date=None: _inputs(_drivers(wacc=0.09)),
    )
    monkeypatch.setattr(
        wacc_workbench,
        "get_ciq_comps_detail",
        lambda ticker: {"peers": [{"ticker": "MSFT"}, {"ticker": "ORCL"}]},
    )
    monkeypatch.setattr(
        wacc_workbench,
        "compute_wacc_methodology_set_for_ticker",
        lambda ticker, peer_tickers=None, hist=None, market_data=None: {
            "peer_bottom_up": _wacc_result(wacc=0.09, beta=1.10, method="peer_bottom_up"),
            "industry_proxy": _wacc_result(wacc=0.085, beta=0.98, method="industry_proxy"),
            "self_hamada": _wacc_result(wacc=0.082, beta=0.93, method="self_hamada"),
        },
    )
    monkeypatch.setattr(
        wacc_workbench,
        "run_probabilistic_valuation",
        lambda drivers, scenario_specs, current_price=None: SimpleNamespace(
            scenario_results={
                spec.name: SimpleNamespace(intrinsic_value_per_share=round(150.0 - drivers.wacc * 400.0, 2))
                for spec in scenario_specs
            },
            expected_iv=round(152.0 - drivers.wacc * 400.0, 2),
            expected_upside_pct=None,
        ),
    )

    db_path = tmp_path / "audit.db"
    monkeypatch.setattr(wacc_workbench, "get_connection", _temp_conn_factory(db_path))

    overrides_path = tmp_path / "valuation_overrides.yaml"
    overrides_path.write_text(
        yaml.dump({"global": {}, "sectors": {}, "tickers": {"IBM": {"wacc": 0.09}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(wacc_workbench, "OVERRIDES_PATH", overrides_path)
    monkeypatch.setattr(wacc_workbench, "clear_valuation_overrides_cache", lambda: None)

    result = wacc_workbench.apply_wacc_methodology_selection(
        "IBM",
        mode="blended",
        weights={"peer_bottom_up": 0.50, "industry_proxy": 0.30, "self_hamada": 0.20},
        actor="dashboard",
    )

    saved = yaml.safe_load(overrides_path.read_text(encoding="utf-8"))
    method_cfg = saved["tickers"]["IBM"]["wacc_methodology"]
    assert method_cfg["mode"] == "blended"
    assert method_cfg["weights"]["industry_proxy"] == pytest.approx(0.30)
    assert result["effective_wacc"] == pytest.approx(0.0869)

    history = wacc_workbench.load_wacc_methodology_audit_history("IBM", limit=5)
    assert len(history) == 1
    assert history[0]["actor"] == "dashboard"
    assert history[0]["mode"] == "blended"
