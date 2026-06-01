import sqlite3

from db.schema import create_tables
from db.loader import (
    insert_evidence_packet,
    load_evidence_packet,
    update_evidence_packet_run,
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


def test_evidence_packet_store_updates_observations_after_agent_run():
    conn = _conn()

    packet_id = insert_evidence_packet(
        conn,
        {
            "created_at": "2026-05-21T00:00:00Z",
            "updated_at": "2026-05-21T00:00:00Z",
            "ticker": "ibm",
            "profile_name": "earnings_update",
            "packet_kind": "earnings_update",
            "bundle_id": "bundle:2",
            "generated_at": "2026-05-21T00:00:00Z",
            "source_refs": [{"source_ref_id": "src:2"}],
            "facts": [{"fact_id": "fact:2", "value": 2}],
            "snippets": [],
            "observations": [],
            "run_metadata": {"source_quality": "real"},
        },
    )

    updated = update_evidence_packet_run(
        conn,
        packet_id,
        updated_at="2026-05-21T00:01:00Z",
        observations=[{"observation_id": "obs:2", "claim": "Raised guidance"}],
        run_metadata_updates={"handoff_run_status": "completed_with_items", "queue_item_count": 1},
    )

    assert updated["observations"][0]["observation_id"] == "obs:2"
    assert updated["run_metadata"]["handoff_run_status"] == "completed_with_items"
    assert updated["run_metadata"]["queue_item_count"] == 1

    loaded = load_evidence_packet(conn, packet_id)
    assert loaded is not None
    assert loaded["observations"][0]["claim"] == "Raised guidance"
    assert loaded["run_metadata"]["handoff_run_status"] == "completed_with_items"


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


def test_pm_decision_queue_store_dedupes_same_packet_observation_and_orders_by_importance():
    conn = _conn()

    first_id = insert_pm_decision_queue_item(
        conn,
        {
            "created_at": "2026-05-21T00:00:00Z",
            "updated_at": "2026-05-21T00:00:00Z",
            "ticker": "ibm",
            "profile_name": "earnings_update",
            "item_type": "assumption_change_pack",
            "status": "pending",
            "qualitative_importance": "medium",
            "valuation_impact_bucket": "medium",
            "title": "Duplicate candidate",
            "summary": "Same packet observation.",
            "evidence_anchor_ids": ["fact:guidance:1"],
            "evidence_packet_ids": ["101"],
            "proposal_pack": {"pack_id": "pack:1"},
            "pm_edited_proposal_pack": None,
            "approved_proposal_pack": None,
            "agent_confidence": "high",
            "translator_confidence": "high",
            "pm_confidence": None,
            "valuation_impact": None,
            "adapter_links": {},
            "decision_history": [],
            "metadata": {"observation_id": "obs:1"},
        },
    )
    duplicate_id = insert_pm_decision_queue_item(
        conn,
        {
            "created_at": "2026-05-21T00:01:00Z",
            "updated_at": "2026-05-21T00:01:00Z",
            "ticker": "ibm",
            "profile_name": "earnings_update",
            "item_type": "assumption_change_pack",
            "status": "pending",
            "qualitative_importance": "high",
            "valuation_impact_bucket": "high",
            "title": "Duplicate candidate",
            "summary": "Same packet observation again.",
            "evidence_anchor_ids": ["fact:guidance:1"],
            "evidence_packet_ids": ["101"],
            "proposal_pack": {"pack_id": "pack:2"},
            "pm_edited_proposal_pack": None,
            "approved_proposal_pack": None,
            "agent_confidence": "high",
            "translator_confidence": "high",
            "pm_confidence": None,
            "valuation_impact": None,
            "adapter_links": {},
            "decision_history": [],
            "metadata": {"observation_id": "obs:1"},
        },
    )
    second_packet_id = insert_pm_decision_queue_item(
        conn,
        {
            "created_at": "2026-05-21T00:02:00Z",
            "updated_at": "2026-05-21T00:02:00Z",
            "ticker": "ibm",
            "profile_name": "company_analysis",
            "item_type": "advisory_finding",
            "status": "rejected",
            "qualitative_importance": "high",
            "valuation_impact_bucket": "low",
            "title": "Fresh packet observation",
            "summary": "Different packet should insert.",
            "evidence_anchor_ids": ["snippet:2"],
            "evidence_packet_ids": ["202"],
            "proposal_pack": None,
            "pm_edited_proposal_pack": None,
            "approved_proposal_pack": None,
            "agent_confidence": "medium",
            "translator_confidence": "medium",
            "pm_confidence": None,
            "valuation_impact": None,
            "adapter_links": {},
            "decision_history": [],
            "metadata": {"observation_id": "obs:1"},
        },
    )

    assert duplicate_id == first_id
    assert second_packet_id != first_id

    all_items = list_pm_decision_queue_items(conn, ticker="IBM", status=None)
    assert len(all_items) == 2
    assert [item["item_id"] for item in all_items] == [second_packet_id, first_id]

    rejected_items = list_pm_decision_queue_items(conn, ticker="IBM", status="rejected")
    assert [item["item_id"] for item in rejected_items] == [second_packet_id]
