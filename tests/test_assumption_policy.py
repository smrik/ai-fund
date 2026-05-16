import sqlite3

import pytest

from db.schema import create_tables
from src.contracts.assumption_policy import (
    PendingAssumptionChange,
    ValuationPolicy,
    ValuationPolicyGlobalDefaults,
)
from src.stage_04_pipeline.assumption_policy import parse_damodaran_drop_folder, preview_valuation_policy_edits


def test_valuation_policy_contract_round_trip():
    policy = ValuationPolicy(
        global_defaults=ValuationPolicyGlobalDefaults(risk_free_rate=0.041, equity_risk_premium=0.052),
        sector_defaults={"Technology": {"terminal_growth": 0.033}},
        source_ref="test",
    )

    restored = ValuationPolicy.model_validate(policy.model_dump())

    assert restored.global_defaults.risk_free_rate == pytest.approx(0.041)
    assert restored.global_defaults.equity_risk_premium == pytest.approx(0.052)
    assert restored.sector_defaults["Technology"]["terminal_growth"] == pytest.approx(0.033)


def test_pending_assumption_change_contract_uppercases_ticker():
    change = PendingAssumptionChange(
        ticker="ibm",
        assumption_name="wacc",
        proposed_value=0.081,
        source_ref="qoe",
    )

    assert change.ticker == "IBM"
    assert change.status.value == "pending"


def test_policy_preview_reports_changed_global_defaults(monkeypatch):
    from src.stage_04_pipeline import assumption_policy as policy_module

    current = ValuationPolicy(
        global_defaults=ValuationPolicyGlobalDefaults(risk_free_rate=0.045, equity_risk_premium=0.05),
        sector_defaults={},
    )
    monkeypatch.setattr(policy_module, "load_current_valuation_policy", lambda: current)

    preview = preview_valuation_policy_edits(global_defaults={"risk_free_rate": 0.039})

    assert preview.changed_fields["global_defaults.risk_free_rate"] == {"prior": 0.045, "new": 0.039}
    assert preview.proposed_policy.global_defaults.equity_risk_premium == pytest.approx(0.05)


def test_damodaran_drop_folder_parses_csv_drafts(tmp_path, monkeypatch):
    db_path = tmp_path / "policy.db"

    def _conn():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr("src.stage_04_pipeline.assumption_policy.get_connection", _conn)
    drop_dir = tmp_path / "damodaran_drop"
    drop_dir.mkdir()
    (drop_dir / "erp.csv").write_text("field,value,date\nERP,5.2%,2026-01-01\n", encoding="utf-8")

    payload = parse_damodaran_drop_folder(drop_dir)

    assert payload["parsed_count"] == 1
    assert payload["drafts"][0]["field"] == "equity_risk_premium"
    assert payload["drafts"][0]["value"] == pytest.approx(0.052)


def test_pending_change_apply_creates_active_approved_entry():
    from db.loader import (
        apply_pending_assumption_changes,
        insert_pending_assumption_change,
        load_approved_assumption_entries,
    )

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_tables(conn)
    change_id = insert_pending_assumption_change(
        conn,
        {
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
            "ticker": "IBM",
            "assumption_name": "ebit_margin_start",
            "current_value": 0.18,
            "proposed_value": 0.21,
            "source_type": "agent",
            "source_ref": "qoe",
            "confidence": "high",
            "rationale": "normalised EBIT",
            "citation": None,
            "status": "pending",
            "approval_ref": None,
            "applied_at": None,
            "metadata": {},
        },
    )

    applied = apply_pending_assumption_changes(
        conn,
        ticker="IBM",
        change_ids=[change_id],
        actor="api",
        applied_at="2026-01-02T00:00:00Z",
        approval_ref="assumption_register_apply:IBM:2026-01-02T00:00:00Z",
    )
    active = load_approved_assumption_entries(conn, "IBM")

    assert applied[0]["assumption_name"] == "ebit_margin_start"
    assert active[0]["value"] == pytest.approx(0.21)
