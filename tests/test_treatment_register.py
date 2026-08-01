import sqlite3

from db.loader import (
    insert_treatment_decision,
    load_active_treatment_decisions,
    load_treatment_decision_history,
)
from db.schema import create_tables
from src.stage_04_pipeline.treatment_register import assess_treatment_revalidation


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_tables(conn)
    return conn


def _decision(**overrides):
    decision = {
        "ticker": "MSFT",
        "topic": "cloud_contract_costs",
        "focus_key": "contract_cost_capitalization",
        "treatment": "capitalize_and_amortize",
        "valuation_treatment": "historical_recast",
        "driver_field": None,
        "model_change_request": (
            "Add a historical operating-expense recast schedule and carry the "
            "resulting normalized margin into the forecast starting point."
        ),
        "evidence_anchor_ids": ["10k:2025:note-2:p17", "ciq:contract_costs:2025"],
        "rationale": "The costs create multi-period economic benefits.",
        "decided_at": "2026-07-25T10:00:00Z",
        "approved_by": "pm",
        "evidence_corpus_hash": "hash-v1",
    }
    decision.update(overrides)
    return decision


def test_treatment_register_schema_and_novel_model_change_round_trip():
    conn = _conn()

    columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(treatment_decisions)").fetchall()
    }
    assert {
        "ticker",
        "topic",
        "focus_key",
        "treatment",
        "valuation_treatment",
        "driver_field",
        "model_change_request",
        "evidence_anchor_ids_json",
        "rationale",
        "approved_by",
        "active",
        "superseded_by",
        "evidence_corpus_hash",
    } <= columns

    decision_id = insert_treatment_decision(conn, _decision())
    active = load_active_treatment_decisions(conn, "msft")

    assert active == [
        {
            "id": decision_id,
            **_decision(),
            "active": True,
            "superseded_by": None,
            "created_at": "2026-07-25T10:00:00Z",
            "updated_at": "2026-07-25T10:00:00Z",
        }
    ]


def test_new_approval_supersedes_prior_decision_for_the_same_focus():
    conn = _conn()
    first_id = insert_treatment_decision(conn, _decision())
    second_id = insert_treatment_decision(
        conn,
        _decision(
            treatment="expense_as_incurred",
            valuation_treatment="forecast_driver",
            driver_field="ebit_margin_start",
            model_change_request=None,
            rationale="New disclosure shows the benefit is consumed within the year.",
            decided_at="2026-10-25T10:00:00Z",
            evidence_corpus_hash="hash-v2",
        ),
    )

    active = load_active_treatment_decisions(conn, "MSFT")
    history = load_treatment_decision_history(conn, "MSFT")

    assert [row["id"] for row in active] == [second_id]
    prior = next(row for row in history if row["id"] == first_id)
    assert prior["active"] is False
    assert prior["superseded_by"] == second_id


def test_revalidation_is_hash_driven_and_contradictions_return_to_the_queue():
    decision = {"id": 42, "evidence_corpus_hash": "hash-v1"}

    unchanged = assess_treatment_revalidation(
        decision,
        current_evidence_corpus_hash="hash-v1",
    )
    changed = assess_treatment_revalidation(
        decision,
        current_evidence_corpus_hash="hash-v2",
    )
    contradicted = assess_treatment_revalidation(
        decision,
        current_evidence_corpus_hash="hash-v2",
        contradiction_reason="The new 10-K says the costs are expensed immediately.",
    )

    assert unchanged.status == "revalidated"
    assert unchanged.queue_required is False
    assert changed.status == "revalidation_required"
    assert changed.queue_required is False
    assert contradicted.status == "contradicted"
    assert contradicted.queue_required is True
    assert "expensed immediately" in contradicted.reason
