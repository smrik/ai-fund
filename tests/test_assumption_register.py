from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from src.contracts.assumption_register import (
    AssumptionApprovalState,
    AssumptionEntityType,
    AssumptionOwner,
    AssumptionRegister,
    AssumptionRegisterEntry,
    AssumptionValueType,
    FlagLevel,
    ModelTrustState,
)
from src.stage_02_valuation.assumption_register import (
    MATERIALITY_RULES,
    build_assumption_register,
    diff_assumption_register_entries,
    summarize_assumption_register,
)
from src.stage_02_valuation.valuation_types import ForecastDrivers


@dataclass
class _Inputs:
    ticker: str = "TEST"
    drivers: ForecastDrivers | None = None
    source_lineage: dict | None = None
    wacc_inputs: dict | None = None


def _drivers(**overrides) -> ForecastDrivers:
    base = dict(
        revenue_base=800_000_000.0,
        revenue_growth_near=0.08,
        revenue_growth_mid=0.05,
        revenue_growth_terminal=0.025,
        ebit_margin_start=0.18,
        ebit_margin_target=0.22,
        tax_rate_start=0.21,
        tax_rate_target=0.23,
        capex_pct_start=0.05,
        capex_pct_target=0.045,
        da_pct_start=0.03,
        da_pct_target=0.028,
        dso_start=45.0,
        dso_target=43.0,
        dio_start=35.0,
        dio_target=33.0,
        dpo_start=30.0,
        dpo_target=32.0,
        wacc=0.09,
        exit_multiple=12.0,
        exit_metric="ev_ebitda",
        net_debt=100_000_000.0,
        shares_outstanding=50_000_000.0,
        invested_capital_start=500_000_000.0,
        ronic_terminal=0.12,
        terminal_blend_gordon_weight=0.60,
        terminal_blend_exit_weight=0.40,
        cost_of_equity=0.11,
        debt_weight=0.20,
    )
    base.update(overrides)
    return ForecastDrivers(**base)


def _inputs(**driver_overrides) -> _Inputs:
    wacc_input_overrides = {}
    for key in (
        "wacc",
        "cost_of_equity",
        "risk_free_rate",
        "equity_risk_premium",
        "beta_relevered",
        "beta_unlevered_median",
        "size_premium",
        "cost_of_debt",
        "equity_weight",
        "debt_weight",
    ):
        if key in driver_overrides:
            wacc_input_overrides[key] = driver_overrides[key]
    return _Inputs(
        drivers=_drivers(**driver_overrides),
        source_lineage={
            "revenue_growth_near": "ciq_consensus",
            "ebit_margin_start": "ciq_snapshot",
            "tax_rate_start": "company_etr",
            "exit_multiple": "ciq_comps",
            "wacc": "yfinance_capm",
            "cost_of_equity": "yfinance_capm",
            "debt_weight": "yfinance_capm",
            "risk_free_rate": "config_default:0.0450",
        },
        wacc_inputs={
            "wacc": 0.09,
            "cost_of_equity": 0.11,
            "risk_free_rate": 0.045,
            "equity_risk_premium": 0.05,
            "beta_relevered": 1.05,
            "beta_unlevered_median": 0.85,
            "size_premium": 0.01,
            "cost_of_debt": 0.04,
            "equity_weight": 0.80,
            "debt_weight": 0.20,
            "selected_methodology": {"mode": "single_method", "selected_method": "peer_bottom_up"},
            **wacc_input_overrides,
        },
    )


def test_contract_round_trips_json_and_forbids_unknown_fields():
    entry = AssumptionRegisterEntry(
        entity_type=AssumptionEntityType.ticker,
        entity_id="IBM",
        ticker="IBM",
        assumption_name="revenue_growth_near",
        scope="growth",
        stage="input_assembly",
        value_type=AssumptionValueType.numeric,
        current_value=0.08,
        accepted_low=0.0,
        accepted_high=0.20,
        range_rule_id="growth_default",
        range_rule_description="Default PM review range for revenue growth.",
        source_lineage={"source": "ciq_consensus"},
        affected_forecast_lines=["revenue", "fcff", "enterprise_value", "equity_value"],
        flag_level=FlagLevel.none,
        owner=AssumptionOwner.deterministic,
        approval_state=AssumptionApprovalState.none,
    )
    register = AssumptionRegister(ticker="IBM", entries=[entry])

    restored = AssumptionRegister.model_validate_json(register.model_dump_json())

    assert restored == register
    assert restored.flag_counts["none"] == 1
    with pytest.raises(Exception):
        AssumptionRegisterEntry.model_validate({**entry.model_dump(mode="json"), "surprise": True})


def test_builder_creates_numeric_effective_ticker_entries_for_dcf_wacc_and_terminal_drivers():
    register = build_assumption_register("test", _inputs())
    by_name = {entry.assumption_name: entry for entry in register.entries}

    assert AssumptionRegister.model_validate(register.model_dump()) == register
    assert all(entry.entity_type == AssumptionEntityType.ticker for entry in register.entries)
    assert all(entry.value_type == AssumptionValueType.numeric for entry in register.entries)
    assert "revenue_growth_near" in by_name
    assert "wacc" in by_name
    assert "risk_free_rate" in by_name
    assert "beta_relevered" in by_name
    assert "cost_of_debt" in by_name
    assert "terminal_blend_gordon_weight" in by_name
    assert "terminal_blend_exit_weight" in by_name
    assert "tv_blended" not in by_name
    assert by_name["wacc"].notes["selected_methodology"]["selected_method"] == "peer_bottom_up"


def test_builder_flags_out_of_range_without_blocking_register_generation():
    register = build_assumption_register("TEST", _inputs(revenue_growth_near=0.45))
    growth = next(entry for entry in register.entries if entry.assumption_name == "revenue_growth_near")

    assert growth.out_of_range is True
    assert growth.flag_level == FlagLevel.review_required
    assert register.model_trust_state == ModelTrustState.review_required


def test_model_trust_rolls_up_critical_diagnostics():
    register = build_assumption_register(
        "TEST",
        _inputs(),
        diagnostics={"health_terminal_denominator_guardrail_flag": True},
    )

    assert register.max_flag_level == FlagLevel.critical
    assert register.model_trust_state == ModelTrustState.critical_review_required


def test_summary_is_compact_and_includes_flagged_entries_only():
    register = build_assumption_register("TEST", _inputs(exit_multiple=55.0))

    summary = summarize_assumption_register(register)

    assert summary["model_trust_state"] == "review_required"
    assert summary["flag_counts"]["review_required"] >= 1
    assert all(entry["flag_level"] != "none" for entry in summary["flagged_entries"])
    assert any(entry["assumption_name"] == "exit_multiple" for entry in summary["flagged_entries"])
    assert len(summary["flagged_entries"]) < len(register.entries)


def test_material_diff_ignores_tiny_changes_and_logs_material_changes():
    previous = build_assumption_register("TEST", _inputs())
    tiny = build_assumption_register("TEST", _inputs(wacc=0.091))
    material = build_assumption_register("TEST", _inputs(wacc=0.096))

    assert MATERIALITY_RULES["wacc"]["threshold"] == pytest.approx(0.0025)
    assert not [
        diff for diff in diff_assumption_register_entries(previous, tiny)
        if diff.assumption_name == "wacc" and diff.event_type == "value_changed"
    ]
    assert any(
        diff.assumption_name == "wacc" and diff.event_type == "value_changed"
        for diff in diff_assumption_register_entries(previous, material)
    )


def test_material_diff_logs_flag_and_approval_changes_with_concise_payloads():
    previous = build_assumption_register("TEST", _inputs())
    current = build_assumption_register("TEST", _inputs(revenue_growth_near=0.45))

    diffs = diff_assumption_register_entries(previous, current)
    growth_diff = next(diff for diff in diffs if diff.assumption_name == "revenue_growth_near")
    payload = growth_diff.model_dump(mode="json")

    assert growth_diff.event_type in {"value_changed", "flag_changed"}
    assert "flag_level" in growth_diff.changed_fields
    assert "prior_entry" not in json.dumps(payload)
    assert "current_entry" not in json.dumps(payload)


def test_material_diff_surfaces_stale_pm_approval_after_value_change():
    previous = build_assumption_register("TEST", _inputs(wacc=0.09))
    current = build_assumption_register("TEST", _inputs(wacc=0.096))
    previous_payload = previous.model_dump(mode="json")
    current_payload = current.model_dump(mode="json")
    for payload in (previous_payload, current_payload):
        for entry in payload["entries"]:
            if entry["assumption_name"] == "wacc":
                entry["owner"] = "pm_override"
                entry["approval_state"] = "pm_approved"
                entry["approval_ref"] = "valuation_override_audit:123"

    diffs = diff_assumption_register_entries(previous_payload, current_payload)
    wacc = next(diff for diff in diffs if diff.assumption_name == "wacc")

    assert wacc.changed_fields["approval_state"]["prior"] == "pm_approved"
    assert wacc.changed_fields["approval_state"]["new"] == "stale_approval"
    assert wacc.reason == "approval_state_changed"


def test_assumption_register_audit_schema_and_loader_store_concise_rows():
    import sqlite3

    from db.loader import insert_assumption_register_audit, load_assumption_register_audit_history
    from db.schema import create_tables

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_tables(conn)
    columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(assumption_register_audit)").fetchall()
    }
    assert {"prior_diff_json", "new_diff_json", "event_type", "assumption_name"} <= columns

    previous = build_assumption_register("TEST", _inputs())
    current = build_assumption_register("TEST", _inputs(wacc=0.096))
    diff = next(
        item for item in diff_assumption_register_entries(previous, current)
        if item.assumption_name == "wacc"
    )
    insert_assumption_register_audit(conn, [diff.model_dump(mode="json")])

    rows = load_assumption_register_audit_history(conn, "test")

    assert len(rows) == 1
    assert rows[0]["ticker"] == "TEST"
    assert rows[0]["event_type"] == "value_changed"
    assert rows[0]["prior_diff"]["current_value"] == pytest.approx(0.09)
    assert rows[0]["new_diff"]["current_value"] == pytest.approx(0.096)
    assert "entries" not in rows[0]["prior_diff_json"]
