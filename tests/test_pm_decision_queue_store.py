import sqlite3

from db.schema import create_tables
from db.loader import (
    insert_evidence_packet,
    load_evidence_packet,
    insert_pm_decision_queue_item,
    list_pm_decision_queue_items,
    update_pm_decision_queue_item,
    insert_pm_decision_queue_event,
)


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_tables(conn)
    return conn


def test_evidence_packet_store_round_trip():
    conn = _conn()

    packet_id = insert_evidence_packet(
        conn,
        {
            "created_at": "2026-05-21T00:00:00Z",
            "updated_at": "2026-05-21T00:00:00Z",
            "ticker": "ibm",
            "profile_name": "earnings_update",
            "packet_kind": "earnings_update",
            "bundle_id": "bundle:1",
            "generated_at": "2026-05-21T00:00:00Z",
            "source_refs": [{"source_ref_id": "src:1"}],
            "facts": [{"fact_id": "fact:1", "value": 1}],
            "snippets": [{"snippet_id": "snippet:1"}],
            "observations": [{"observation_id": "obs:1"}],
            "run_metadata": {"run_id": "run:1"},
        },
    )

    loaded = load_evidence_packet(conn, packet_id)

    assert loaded is not None
    assert loaded["ticker"] == "IBM"
    assert loaded["packet_kind"] == "earnings_update"
    assert loaded["source_refs"][0]["source_ref_id"] == "src:1"
    assert loaded["facts"][0]["fact_id"] == "fact:1"
    assert loaded["run_metadata"]["run_id"] == "run:1"


def test_pm_decision_queue_store_insert_list_update_and_event():
    conn = _conn()

    item_id = insert_pm_decision_queue_item(
        conn,
        {
            "created_at": "2026-05-21T00:00:00Z",
            "updated_at": "2026-05-21T00:00:00Z",
            "ticker": "ibm",
            "profile_name": "company_analysis",
            "item_type": "assumption_change_pack",
            "status": "pending",
            "qualitative_importance": "high",
            "valuation_impact_bucket": "high",
            "title": "Revenue guidance raised",
            "summary": "Guidance midpoint increased.",
            "evidence_anchor_ids": ["fact:guidance:1"],
            "evidence_packet_ids": ["packet:1"],
            "proposal_pack": {"pack_id": "pack:1"},
            "pm_edited_proposal_pack": None,
            "approved_proposal_pack": None,
            "agent_confidence": "high",
            "translator_confidence": "medium",
            "pm_confidence": None,
            "valuation_impact": {"iv_delta_pct": 0.03},
            "adapter_links": {},
            "decision_history": [],
            "metadata": {},
        },
    )

    pending = list_pm_decision_queue_items(conn, ticker="IBM", status="pending")
    assert len(pending) == 1
    assert pending[0]["item_id"] == item_id
    assert pending[0]["evidence_anchor_ids"] == ["fact:guidance:1"]

    updated = update_pm_decision_queue_item(
        conn,
        item_id=item_id,
        updates={
            "status": "approved",
            "pm_confidence": "high",
            "approved_proposal_pack": {"pack_id": "pack:approved"},
            "decision_history": [{"event": "approved"}],
        },
    )
    assert updated["status"] == "approved"
    assert updated["pm_confidence"] == "high"
    assert updated["approved_proposal_pack"]["pack_id"] == "pack:approved"

    insert_pm_decision_queue_event(
        conn,
        {
            "created_at": "2026-05-21T00:01:00Z",
            "item_id": item_id,
            "ticker": "IBM",
            "event_type": "approve",
            "actor": "pm",
            "payload": {"status": "approved"},
        },
    )
    event_row = conn.execute(
        "SELECT event_type, actor, payload_json FROM pm_decision_queue_events WHERE item_id = ?",
        [item_id],
    ).fetchone()
    assert event_row is not None
    assert event_row["event_type"] == "approve"
    assert event_row["actor"] == "pm"
