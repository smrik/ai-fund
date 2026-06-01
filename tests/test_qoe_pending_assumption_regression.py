from __future__ import annotations

import sqlite3
import sys
import types
import pytest

from db.schema import create_tables
from src.contracts.assumption_policy import PendingAssumptionChange
from src.stage_02_valuation.valuation_types import ForecastDrivers
from src.stage_04_pipeline import pending_assumption_changes as pac


def _drivers() -> ForecastDrivers:
    return ForecastDrivers(
        revenue_base=1_000.0,
        revenue_growth_near=0.08,
        revenue_growth_mid=0.06,
        revenue_growth_terminal=0.03,
        ebit_margin_start=0.20,
        ebit_margin_target=0.22,
        tax_rate_start=0.23,
        tax_rate_target=0.24,
        capex_pct_start=0.05,
        capex_pct_target=0.05,
        da_pct_start=0.04,
        da_pct_target=0.04,
        dso_start=45.0,
        dso_target=45.0,
        dio_start=35.0,
        dio_target=35.0,
        dpo_start=40.0,
        dpo_target=40.0,
        wacc=0.10,
        exit_multiple=12.0,
        exit_metric="ev_ebitda",
        net_debt=300.0,
        shares_outstanding=10.0,
        ronic_terminal=0.12,
        invested_capital_start=500.0,
        non_operating_assets=50.0,
    )


def _stub_edgar_import() -> None:
    if "edgar" not in sys.modules:
        sys.modules["edgar"] = types.SimpleNamespace(set_identity=lambda *_: None, Company=object)


def test_qoe_output_creates_pending_entry_with_numeric_confidence_and_evidence(monkeypatch):
    created: list[PendingAssumptionChange] = []

    def _capture(change: PendingAssumptionChange) -> PendingAssumptionChange:
        created.append(change)
        return change.model_copy(update={"change_id": 101})

    monkeypatch.setattr(pac, "list_pending_assumption_changes", lambda ticker: [])
    monkeypatch.setattr(pac, "create_pending_assumption_change", _capture)

    class _Rec:
        field = "ebit_margin_start"
        agent = "qoe"
        current_value = 0.2
        proposed_value = 0.16
        confidence = "high"
        rationale = "QoE normalization"
        citation = "10-K Note"
        status = "pending"

    out = pac.write_pending_changes_from_recommendations("ibm", [_Rec()])

    assert len(out) == 1
    assert created[0].proposed_value == pytest.approx(0.16)
    assert isinstance(created[0].proposed_value, float)
    assert created[0].confidence == "high"
    assert created[0].citation == "10-K Note"


def test_without_approval_deterministic_inputs_remain_unchanged(monkeypatch):
    _stub_edgar_import()
    from src.stage_02_valuation import input_assembler as ia

    monkeypatch.setattr(ia, "QOE_PENDING_PATH", type("P", (), {"exists": lambda *_: False})())
    monkeypatch.setattr(ia, "load_valuation_overrides", lambda: {"global": {}, "sectors": {}, "tickers": {}})
    monkeypatch.setattr("db.loader.get_approved_assumption_overrides", lambda ticker: {})

    d = _drivers()
    lineage = {}
    ia._apply_overrides(d, lineage, ticker="IBM", sector="Technology")

    assert d.ebit_margin_start == pytest.approx(0.20)
    assert "ebit_margin_start" not in lineage


def test_preview_computes_iv_delta_but_persists_nothing(monkeypatch):
    class _Inputs:
        drivers = _drivers()

    monkeypatch.setattr("src.stage_02_valuation.input_assembler.build_valuation_inputs", lambda ticker: _Inputs())
    monkeypatch.setattr(pac, "list_pending_assumption_changes", lambda ticker: [
        PendingAssumptionChange(
            change_id=1,
            ticker="IBM",
            assumption_name="ebit_margin_start",
            current_value=0.20,
            proposed_value=0.25,
            source_ref="qoe",
        )
    ])
    monkeypatch.setattr(pac, "_run_scenarios", lambda d: {"base": round(d.ebit_margin_start * 100, 2)})

    called = {"apply": 0}
    monkeypatch.setattr(pac, "apply_pending_assumption_stack", lambda *args, **kwargs: called.__setitem__("apply", 1))

    preview = pac.preview_pending_assumption_stack("IBM", [1])

    assert preview.current_iv["base"] == pytest.approx(20.0)
    assert preview.proposed_iv["base"] == pytest.approx(25.0)
    assert preview.delta_pct["base"] == pytest.approx(25.0)
    assert called["apply"] == 0


def test_after_approval_input_assembly_consumes_approved_entry(monkeypatch):
    _stub_edgar_import()
    from src.stage_02_valuation import input_assembler as ia

    monkeypatch.setattr(ia, "QOE_PENDING_PATH", type("P", (), {"exists": lambda *_: False})())
    monkeypatch.setattr(ia, "load_valuation_overrides", lambda: {"global": {}, "sectors": {}, "tickers": {}})
    monkeypatch.setattr("db.loader.get_approved_assumption_overrides", lambda ticker: {"ebit_margin_start": 0.13})

    d = _drivers()
    lineage = {}
    ia._apply_overrides(d, lineage, ticker="IBM", sector="Technology")

    assert d.ebit_margin_start == pytest.approx(0.13)
    assert lineage["ebit_margin_start"] == "approved_assumption_register"


def test_api_transition_rules_and_audit_writes_for_approve_reject():
    from db.loader import (
        approve_pending_assumption_changes,
        insert_assumption_register_audit,
        insert_pending_assumption_change,
        load_assumption_register_audit_history,
        reject_pending_assumption_changes,
    )

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_tables(conn)

    cid = insert_pending_assumption_change(conn, {
        "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z",
        "ticker": "IBM", "assumption_name": "ebit_margin_start", "current_value": 0.2,
        "proposed_value": 0.19, "source_type": "agent", "source_ref": "qoe",
        "confidence": "high", "rationale": "r", "citation": "c", "status": "pending",
        "approval_ref": None, "applied_at": None, "metadata": {},
    })

    rejected = reject_pending_assumption_changes(conn, ticker="IBM", change_ids=[cid], actor="api", rejected_at="2026-01-02T00:00:00Z")
    assert rejected == 1

    # cannot approve once rejected
    applied = approve_pending_assumption_changes(conn, ticker="IBM", change_ids=[cid], actor="api", applied_at="2026-01-03T00:00:00Z", approval_ref="ref")
    assert applied == []

    insert_assumption_register_audit(conn, [{
        "event_ts": "2026-01-03T00:00:00Z", "actor": "api", "actor_type": "pm", "entity_type": "ticker",
        "entity_id": "IBM", "ticker": "IBM", "assumption_name": "ebit_margin_start", "scope": "dcf",
        "event_type": "pm_override_rejected", "changed_fields": {"status": {"prior": "pending", "new": "rejected"}},
        "valuation_impact": None, "reason": "qoe",
    }])
    audit_rows = load_assumption_register_audit_history(conn, "IBM")
    assert any(r["event_type"] == "pm_override_rejected" for r in audit_rows)


def test_no_silent_override_every_delta_traces_to_approved_record_id(monkeypatch):
    _stub_edgar_import()
    from src.stage_02_valuation import input_assembler as ia

    monkeypatch.setattr(ia, "QOE_PENDING_PATH", type("P", (), {"exists": lambda *_: False})())
    monkeypatch.setattr(ia, "load_valuation_overrides", lambda: {"global": {}, "sectors": {}, "tickers": {}})
    monkeypatch.setattr("db.loader.get_approved_assumption_overrides", lambda ticker: {"ebit_margin_start": 0.12})

    d = _drivers()
    lineage = {}
    ia._apply_overrides(d, lineage, ticker="IBM", sector="Technology")

    assert d.ebit_margin_start != pytest.approx(0.20)
    assert lineage.get("ebit_margin_start") == "approved_assumption_register"
