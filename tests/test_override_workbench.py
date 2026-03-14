from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from db.schema import create_tables
from src.stage_02_valuation.input_assembler import ValuationInputsWithLineage
from src.stage_02_valuation.professional_dcf import ForecastDrivers
from src.stage_04_pipeline.recommendations import Recommendation, TickerRecommendations


def _drivers(**overrides):
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
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


def _inputs(drivers: ForecastDrivers, source_lineage: dict[str, str]) -> ValuationInputsWithLineage:
    return ValuationInputsWithLineage(
        ticker="IBM",
        company_name="IBM",
        sector="Technology",
        industry="IT Services",
        current_price=100.0,
        as_of_date="2026-03-14",
        model_applicability_status="dcf_applicable",
        drivers=drivers,
        source_lineage=source_lineage,
        ciq_lineage={},
        wacc_inputs={},
        story_profile=None,
        story_adjustments=None,
    )


def _temp_conn_factory(db_path: Path):
    def _factory():
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        create_tables(conn)
        return conn

    return _factory


def test_build_override_workbench_includes_default_effective_and_agent_values(monkeypatch, tmp_path):
    from src.stage_04_pipeline.override_workbench import build_override_workbench

    baseline = _inputs(
        _drivers(revenue_growth_near=0.08),
        {"revenue_growth_near": "ciq_consensus", "ebit_margin_start": "ciq_margin_avg_3yr"},
    )
    effective = _inputs(
        _drivers(revenue_growth_near=0.10),
        {"revenue_growth_near": "override_ticker", "ebit_margin_start": "ciq_margin_avg_3yr"},
    )

    def _build(ticker: str, as_of_date=None, apply_overrides=True):
        return effective if apply_overrides else baseline

    monkeypatch.setattr("src.stage_04_pipeline.override_workbench.build_valuation_inputs", _build)
    monkeypatch.setattr(
        "src.stage_04_pipeline.override_workbench.load_recommendations",
        lambda ticker: TickerRecommendations(
            ticker="IBM",
            generated_at="2026-03-14T00:00:00Z",
            current_iv_base=150.0,
            recommendations=[
                Recommendation(
                    agent="filings",
                    field="revenue_growth_near",
                    current_value=0.10,
                    proposed_value=0.12,
                    confidence="high",
                    rationale="SEC/XBRL growth differs",
                    citation="SEC XBRL 10-K 2025-12-31",
                    status="pending",
                )
            ],
        ),
    )
    monkeypatch.setattr(
        "src.stage_04_pipeline.override_workbench.run_probabilistic_valuation",
        lambda drivers, scenario_specs, current_price=None: SimpleNamespace(
            scenario_results={
                "bear": SimpleNamespace(intrinsic_value_per_share=135.0),
                "base": SimpleNamespace(intrinsic_value_per_share=150.0),
                "bull": SimpleNamespace(intrinsic_value_per_share=170.0),
            },
            expected_iv=154.0,
            expected_upside_pct=None,
        ),
    )
    overrides_path = tmp_path / "valuation_overrides.yaml"
    overrides_path.write_text(
        yaml.dump({"global": {}, "sectors": {}, "tickers": {"IBM": {"revenue_growth_near": 0.10}}})
    )
    monkeypatch.setattr("src.stage_04_pipeline.override_workbench.OVERRIDES_PATH", overrides_path)

    workbench = build_override_workbench("IBM")
    row = next(r for r in workbench["fields"] if r["field"] == "revenue_growth_near")

    assert row["baseline_value"] == pytest.approx(0.08)
    assert row["effective_value"] == pytest.approx(0.10)
    assert row["agent_value"] == pytest.approx(0.12)
    assert row["effective_source"] == "override_ticker"
    assert row["initial_mode"] == "custom"


def test_preview_override_selections_resolves_agent_and_custom(monkeypatch):
    from src.stage_04_pipeline.override_workbench import preview_override_selections

    baseline = _inputs(
        _drivers(revenue_growth_near=0.08, ebit_margin_start=0.15),
        {"revenue_growth_near": "ciq_consensus", "ebit_margin_start": "ciq_margin_avg_3yr"},
    )
    effective = _inputs(
        _drivers(revenue_growth_near=0.10, ebit_margin_start=0.15),
        {"revenue_growth_near": "override_ticker", "ebit_margin_start": "ciq_margin_avg_3yr"},
    )

    def _build(ticker: str, as_of_date=None, apply_overrides=True):
        return effective if apply_overrides else baseline

    def _run(drivers, scenario_specs, current_price=None):
        base_iv = round(100 + drivers.revenue_growth_near * 100 + drivers.ebit_margin_start * 100, 2)
        scenario_results = {
            spec.name: SimpleNamespace(
                intrinsic_value_per_share=round(base_iv + {"bear": -10, "base": 0, "bull": 15}[spec.name], 2)
            )
            for spec in scenario_specs
        }
        expected_iv = round(sum(v.intrinsic_value_per_share * w for v, w in zip(scenario_results.values(), [0.2, 0.6, 0.2])), 2)
        return SimpleNamespace(scenario_results=scenario_results, expected_iv=expected_iv, expected_upside_pct=None)

    monkeypatch.setattr("src.stage_04_pipeline.override_workbench.build_valuation_inputs", _build)
    monkeypatch.setattr(
        "src.stage_04_pipeline.override_workbench.load_recommendations",
        lambda ticker: TickerRecommendations(
            ticker="IBM",
            generated_at="2026-03-14T00:00:00Z",
            current_iv_base=150.0,
            recommendations=[
                Recommendation("filings", "revenue_growth_near", 0.10, 0.12, "high", "growth"),
                Recommendation("qoe", "ebit_margin_start", 0.15, 0.16, "high", "margin"),
            ],
        ),
    )
    monkeypatch.setattr("src.stage_04_pipeline.override_workbench.run_probabilistic_valuation", _run)

    preview = preview_override_selections(
        "IBM",
        selections={"revenue_growth_near": "agent", "ebit_margin_start": "custom"},
        custom_values={"ebit_margin_start": 0.17},
    )

    assert preview["resolved_values"]["revenue_growth_near"]["value"] == pytest.approx(0.12)
    assert preview["resolved_values"]["ebit_margin_start"]["value"] == pytest.approx(0.17)
    assert preview["proposed_iv"]["base"] > preview["current_iv"]["base"]


def test_apply_override_selections_updates_yaml_and_writes_sql_audit(monkeypatch, tmp_path):
    from src.stage_04_pipeline.override_workbench import apply_override_selections, load_override_audit_history

    baseline = _inputs(
        _drivers(revenue_growth_near=0.08, ebit_margin_start=0.15),
        {"revenue_growth_near": "ciq_consensus", "ebit_margin_start": "ciq_margin_avg_3yr"},
    )
    effective = _inputs(
        _drivers(revenue_growth_near=0.10, ebit_margin_start=0.15),
        {"revenue_growth_near": "override_ticker", "ebit_margin_start": "ciq_margin_avg_3yr"},
    )

    def _build(ticker: str, as_of_date=None, apply_overrides=True):
        return effective if apply_overrides else baseline

    def _run(drivers, scenario_specs, current_price=None):
        base_iv = round(100 + drivers.revenue_growth_near * 100 + drivers.ebit_margin_start * 100, 2)
        scenario_results = {
            spec.name: SimpleNamespace(
                intrinsic_value_per_share=round(base_iv + {"bear": -10, "base": 0, "bull": 15}[spec.name], 2)
            )
            for spec in scenario_specs
        }
        expected_iv = round(sum(v.intrinsic_value_per_share * w for v, w in zip(scenario_results.values(), [0.2, 0.6, 0.2])), 2)
        return SimpleNamespace(scenario_results=scenario_results, expected_iv=expected_iv, expected_upside_pct=None)

    monkeypatch.setattr("src.stage_04_pipeline.override_workbench.build_valuation_inputs", _build)
    monkeypatch.setattr(
        "src.stage_04_pipeline.override_workbench.load_recommendations",
        lambda ticker: TickerRecommendations(
            ticker="IBM",
            generated_at="2026-03-14T00:00:00Z",
            current_iv_base=150.0,
            recommendations=[
                Recommendation("filings", "revenue_growth_near", 0.10, 0.12, "high", "growth"),
            ],
        ),
    )
    monkeypatch.setattr("src.stage_04_pipeline.override_workbench.run_probabilistic_valuation", _run)

    db_path = tmp_path / "audit.db"
    monkeypatch.setattr("src.stage_04_pipeline.override_workbench.get_connection", _temp_conn_factory(db_path))

    overrides_path = tmp_path / "valuation_overrides.yaml"
    overrides_path.write_text(
        yaml.dump({"global": {}, "sectors": {}, "tickers": {"IBM": {"revenue_growth_near": 0.10, "wacc": 0.09}}})
    )
    monkeypatch.setattr("src.stage_04_pipeline.override_workbench.OVERRIDES_PATH", overrides_path)
    monkeypatch.setattr("src.stage_04_pipeline.override_workbench.clear_valuation_overrides_cache", lambda: None)

    result = apply_override_selections(
        "IBM",
        selections={"revenue_growth_near": "default", "ebit_margin_start": "custom"},
        custom_values={"ebit_margin_start": 0.17},
        actor="dashboard",
    )

    saved = yaml.safe_load(overrides_path.read_text())
    assert saved["tickers"]["IBM"]["revenue_growth_near"] == pytest.approx(0.08)
    assert saved["tickers"]["IBM"]["ebit_margin_start"] == pytest.approx(0.17)
    assert saved["tickers"]["IBM"]["wacc"] == pytest.approx(0.09)
    assert result["applied_count"] == 2

    history = load_override_audit_history("IBM", limit=10)
    assert len(history) == 2
    fields = {row["field"] for row in history}
    assert fields == {"revenue_growth_near", "ebit_margin_start"}
    assert all(row["actor"] == "dashboard" for row in history)
    assert all(row["proposed_iv_base"] is not None for row in history)
