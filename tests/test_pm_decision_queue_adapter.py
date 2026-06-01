import sqlite3
from types import SimpleNamespace

import pytest

from db.loader import (
    insert_pm_decision_queue_item,
    list_pm_decision_queue_items,
    load_approved_assumption_entries,
    load_pending_assumption_changes,
)
from db.schema import create_tables
from src.stage_04_pipeline.pm_decision_queue import (
    approve_pm_decision_queue_item,
    apply_pm_decision_queue_item,
    build_pm_decision_queue_conflict_groups,
    defer_pm_decision_queue_item,
    edit_pm_decision_queue_item,
    preview_pm_decision_queue_item,
    reject_pm_decision_queue_item,
)


def test_conflict_groups_require_distinct_profiles_and_keep_latest_profile_item():
    def _item(item_id: int, profile_name: str, proposed_value: float) -> dict:
        return {
            "item_id": item_id,
            "ticker": "IBM",
            "profile_name": profile_name,
            "item_type": "assumption_change_pack",
            "status": "pending",
            "proposal_pack": {
                "proposals": [
                    {
                        "assumption_name": "revenue_growth_near",
                        "proposal_mode": "target",
                        "proposed_target_value": proposed_value,
                    }
                ]
            },
            "metadata": {"packet_provenance": {"source_quality": "real"}},
        }

    same_profile_only = build_pm_decision_queue_conflict_groups(
        [_item(1, "earnings_update", 0.05), _item(2, "earnings_update", 0.06)]
    )
    cross_profile = build_pm_decision_queue_conflict_groups(
        [
            _item(1, "earnings_update", 0.05),
            _item(2, "earnings_update", 0.06),
            _item(3, "industry_analysis", 0.04),
        ]
    )
    previewed_delta = _item(4, "company_analysis", 0.06)
    previewed_delta["proposal_pack"]["proposals"][0] = {
        "assumption_name": "revenue_growth_near",
        "proposal_mode": "delta",
        "proposed_delta": 0.01,
    }
    previewed_delta["adapter_links"] = {"last_preview_manual_values": {"revenue_growth_near": 0.06}}
    equivalent_targets = build_pm_decision_queue_conflict_groups([_item(2, "earnings_update", 0.06), previewed_delta])

    assert same_profile_only == []
    assert cross_profile[0]["item_ids"] == [2, 3]
    assert cross_profile[0]["profile_names"] == ["earnings_update", "industry_analysis"]
    assert cross_profile[0]["proposal_count"] == 2
    assert equivalent_targets[0]["conflict_level"] == "cluster"


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
    driver_values = {"revenue_growth_near": 0.07}
    monkeypatch.setattr(
        "src.stage_02_valuation.input_assembler.build_valuation_inputs",
        lambda ticker: SimpleNamespace(drivers=SimpleNamespace(**driver_values)),
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

    driver_values["revenue_growth_near"] = 0.08
    with pytest.raises(ValueError, match="must be previewed"):
        approve_pm_decision_queue_item("IBM", item_id, actor="pm")
    driver_values["revenue_growth_near"] = 0.07
    preview_pm_decision_queue_item("IBM", item_id)

    approved = approve_pm_decision_queue_item("IBM", item_id, actor="pm")
    assert approved["status"] == "approved"
    assert approved["approved_proposal_pack"]["pack_id"] == "pack:1"
    proposal = approved["approved_proposal_pack"]["proposals"][0]
    assert proposal["proposal_mode"] == "target"
    assert proposal["proposed_target_value"] == 0.08
    assert approved["adapter_links"]["pending_assumption_change_ids"]
    assert approved["adapter_links"]["skipped_fields"] == []

    pending_rows = load_pending_assumption_changes(conn, ticker="IBM", status=None)
    approved_rows = load_approved_assumption_entries(conn, ticker="IBM")
    assert len(pending_rows) >= 1
    assert pending_rows[0]["status"] == "approved"
    assert approved_rows == []

    applied = apply_pm_decision_queue_item("IBM", item_id, actor="pm")
    applied_again = apply_pm_decision_queue_item("IBM", item_id, actor="pm")
    approved_rows = load_approved_assumption_entries(conn, ticker="IBM")
    assert approved_rows[0]["assumption_name"] == "revenue_growth_near"
    assert approved_rows[0]["value"] == 0.08
    assert applied["adapter_links"]["applied_assumption_change_ids"]
    assert applied_again["adapter_links"]["applied_assumption_change_ids"] == applied["adapter_links"]["applied_assumption_change_ids"]
    assert len(approved_rows) == 1
    with pytest.raises(ValueError, match="cannot be approved"):
        approve_pm_decision_queue_item("IBM", item_id, actor="pm")
    with pytest.raises(ValueError, match="cannot be edited"):
        edit_pm_decision_queue_item("IBM", item_id, approved["approved_proposal_pack"], actor="pm")
    with pytest.raises(ValueError, match="cannot be rejected"):
        reject_pm_decision_queue_item("IBM", item_id, actor="pm", reason="too late")
    with pytest.raises(ValueError, match="cannot be deferred"):
        defer_pm_decision_queue_item("IBM", item_id, actor="pm", reason="too late")

    edited_item_id = insert_pm_decision_queue_item(
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
            "title": "Margin target updated",
            "summary": "Target changed.",
            "evidence_anchor_ids": ["fact:margin:1"],
            "evidence_packet_ids": ["2"],
            "proposal_pack": {
                "pack_id": "pack:orig",
                "proposals": [
                    {
                        "assumption_name": "revenue_growth_near",
                        "proposal_mode": "delta",
                        "proposed_delta": -0.01,
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

    edited = edit_pm_decision_queue_item(
        "IBM",
        edited_item_id,
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

    edited_preview = preview_pm_decision_queue_item("IBM", edited_item_id)
    assert edited_preview["preview"]["manual_values"]["revenue_growth_near"] == 0.07
    approved_edited = approve_pm_decision_queue_item("IBM", edited_item_id, actor="pm")
    assert approved_edited["approved_proposal_pack"]["pack_id"] == "pack:edited"
    edited_proposal = approved_edited["approved_proposal_pack"]["proposals"][0]
    assert edited_proposal["proposal_mode"] == "target"
    assert edited_proposal["proposed_target_value"] == 0.07

    skipped_item_id = insert_pm_decision_queue_item(
        conn,
        {
            "created_at": "2026-05-21T00:00:00Z",
            "updated_at": "2026-05-21T00:00:00Z",
            "ticker": "ibm",
            "profile_name": "industry_analysis",
            "item_type": "assumption_change_pack",
            "status": "pending",
            "qualitative_importance": "medium",
            "valuation_impact_bucket": "medium",
            "title": "Unknown field change",
            "summary": "Proposal cannot be resolved.",
            "evidence_anchor_ids": ["fact:unknown:1"],
            "evidence_packet_ids": ["3"],
            "proposal_pack": {
                "pack_id": "pack:skip",
                "proposals": [
                    {
                        "assumption_name": "unknown_driver_field",
                        "proposal_mode": "delta",
                        "proposed_delta": 0.01,
                    }
                ],
            },
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

    skipped_preview = preview_pm_decision_queue_item("IBM", skipped_item_id)
    assert skipped_preview["preview"]["manual_values"] == {}
    assert skipped_preview["skipped_fields"] == ["unknown_driver_field"]

    with pytest.raises(ValueError, match="unresolvable proposal fields"):
        approve_pm_decision_queue_item("IBM", skipped_item_id, actor="pm")

    unpreviewed_item_id = insert_pm_decision_queue_item(
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
            "title": "Unpreviewed proposal",
            "summary": "Requires preview.",
            "evidence_anchor_ids": ["fact:preview:1"],
            "evidence_packet_ids": ["4"],
            "proposal_pack": {
                "pack_id": "pack:unpreviewed",
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
    with pytest.raises(ValueError, match="must be previewed"):
        approve_pm_decision_queue_item("IBM", unpreviewed_item_id, actor="pm")

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
    assert statuses[edited_item_id] == "approved"
    assert statuses[skipped_item_id] == "previewed"
    assert statuses[unpreviewed_item_id] == "pending"
    assert statuses[rejected_item_id] == "rejected"
    assert statuses[deferred_item_id] == "deferred"
