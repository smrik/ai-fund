import sqlite3

from db.loader import (
    insert_pm_decision_queue_item,
    list_pm_decision_queue_items,
    load_pending_assumption_changes,
)
from db.schema import create_tables
from src.stage_04_pipeline.pm_decision_queue import (
    preview_pm_decision_queue_item,
    edit_pm_decision_queue_item,
    approve_pm_decision_queue_item,
    reject_pm_decision_queue_item,
    defer_pm_decision_queue_item,
)


def test_pm_decision_queue_adapter_preview_edit_approve_reject_defer(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_tables(conn)

    monkeypatch.setattr("src.stage_04_pipeline.pm_decision_queue.get_connection", lambda: conn)
    monkeypatch.setattr("src.stage_04_pipeline.pending_assumption_changes.get_connection", lambda: conn)
    monkeypatch.setattr(
        "src.stage_04_pipeline.pm_decision_queue.preview_pending_assumption_stack",
        lambda ticker, change_ids, manual_values=None: {
            "ticker": ticker,
            "change_ids": change_ids,
            "manual_values": manual_values or {},
        },
    )

    item_id = insert_pm_decision_queue_item(
        conn,
        {
            "created_at": "2026-05-21T00:00:00Z",
            "updated_at": "2026-05-21T00:00:00Z",
            "ticker": "ibm",
            "profile_name": "earnings_update",
            "item_type": "assumption_change_pack",
            "status": "pending",
            "qualitative_importance": "high",
            "valuation_impact_bucket": "high",
            "title": "Revenue guidance raised",
            "summary": "Guidance midpoint increased.",
            "evidence_anchor_ids": ["fact:guidance:1"],
            "evidence_packet_ids": ["1"],
            "proposal_pack": {
                "pack_id": "pack:1",
                "proposals": [
                    {
                        "assumption_name": "revenue_growth_near",
                        "proposal_mode": "delta",
                        "proposed_delta": 0.01,
                    }
                ],
            },
            "pm_edited_proposal_pack": None,
            "approved_proposal_pack": None,
            "agent_confidence": "high",
            "translator_confidence": "high",
            "pm_confidence": None,
            "valuation_impact": None,
            "adapter_links": {},
            "decision_history": [],
            "metadata": {},
        },
    )

    preview = preview_pm_decision_queue_item("IBM", item_id)
    assert preview["preview"]["ticker"] == "IBM"
    assert preview["preview"]["manual_values"]["revenue_growth_near"] == 0.08

    edited = edit_pm_decision_queue_item(
        "IBM",
        item_id,
        {
            "pack_id": "pack:edited",
            "proposals": [
                {
                    "assumption_name": "revenue_growth_near",
                    "proposal_mode": "target",
                    "proposed_target_value": 0.07,
                }
            ],
        },
        actor="pm",
    )
    assert edited["status"] == "pending"
    assert edited["pm_edited_proposal_pack"]["pack_id"] == "pack:edited"

    approved = approve_pm_decision_queue_item("IBM", item_id, actor="pm")
    assert approved["status"] == "approved"
    assert approved["approved_proposal_pack"]["pack_id"] == "pack:edited"
    assert approved["adapter_links"]["pending_assumption_change_ids"]

    pending_rows = load_pending_assumption_changes(conn, ticker="IBM", status=None)
    assert len(pending_rows) >= 1

    rejected_item_id = insert_pm_decision_queue_item(
        conn,
        {
            "created_at": "2026-05-21T00:00:00Z",
            "updated_at": "2026-05-21T00:00:00Z",
            "ticker": "ibm",
            "profile_name": "company_analysis",
            "item_type": "advisory_finding",
            "status": "pending",
            "qualitative_importance": "medium",
            "valuation_impact_bucket": None,
            "title": "Advisory finding",
            "summary": "Needs PM call",
            "evidence_anchor_ids": ["snippet:1"],
            "evidence_packet_ids": ["2"],
            "proposal_pack": None,
            "pm_edited_proposal_pack": None,
            "approved_proposal_pack": None,
            "agent_confidence": "medium",
            "translator_confidence": "medium",
            "pm_confidence": None,
            "valuation_impact": None,
            "adapter_links": {},
            "decision_history": [],
            "metadata": {},
        },
    )

    rejected = reject_pm_decision_queue_item("IBM", rejected_item_id, actor="pm", reason="not compelling")
    assert rejected["status"] == "rejected"

    deferred_item_id = insert_pm_decision_queue_item(
        conn,
        {
            "created_at": "2026-05-21T00:00:00Z",
            "updated_at": "2026-05-21T00:00:00Z",
            "ticker": "ibm",
            "profile_name": "industry_analysis",
            "item_type": "advisory_finding",
            "status": "pending",
            "qualitative_importance": "high",
            "valuation_impact_bucket": None,
            "title": "Deferred finding",
            "summary": "Wait for next print",
            "evidence_anchor_ids": ["snippet:2"],
            "evidence_packet_ids": ["3"],
            "proposal_pack": None,
            "pm_edited_proposal_pack": None,
            "approved_proposal_pack": None,
            "agent_confidence": "high",
            "translator_confidence": "medium",
            "pm_confidence": None,
            "valuation_impact": None,
            "adapter_links": {},
            "decision_history": [],
            "metadata": {},
        },
    )
    deferred = defer_pm_decision_queue_item("IBM", deferred_item_id, actor="pm", reason="revisit next quarter")
    assert deferred["status"] == "deferred"

    statuses = {item["item_id"]: item["status"] for item in list_pm_decision_queue_items(conn, ticker="IBM", status=None)}
    assert statuses[item_id] == "approved"
    assert statuses[rejected_item_id] == "rejected"
    assert statuses[deferred_item_id] == "deferred"
