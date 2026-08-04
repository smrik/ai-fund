import hashlib
import sqlite3

import pytest

from db.loader import list_pm_decision_queue_items, load_active_treatment_decisions
from db.schema import create_tables
from src.contracts.pm_decision_queue import PMDecisionQueueItemType
from src.stage_04_pipeline.accounting_evidence_runner import run_accounting_evidence_trial
from src.stage_04_pipeline.pm_decision_queue import approve_pm_decision_queue_item

FOCUSED_CORPUS_HASH = hashlib.sha256(b"fixture focused accounting filing corpus").hexdigest()


def _packet() -> dict:
    return {
        "packet_id": 42,
        "ticker": "MSFT",
        "profile_name": "accounting_qoe",
        "packet_kind": "accounting",
        "generated_at": "2026-07-25T00:00:00Z",
        "source_refs": [
            {
                "source_ref_id": "filing:msft:2025",
                "source_kind": "10-K",
                "source_label": "MSFT 2025 10-K",
                "source_locator": "edgar://msft/2025",
                "metadata": {},
            }
        ],
        "facts": [
            {
                "fact_id": "ciq:contract_costs:2025",
                "fact_name": "Capitalized contract acquisition costs",
                "value": 2.4e9,
                "unit": "USD",
                "metadata": {
                    "fact_role": "xbrl_structured_fact",
                    "period": "2025-06-30",
                },
            },
            {
                "fact_id": "fact:driver:revenue-growth",
                "fact_name": "revenue_growth_near",
                "value": 0.12,
                "metadata": {
                    "fact_role": "current_model_driver",
                    "driver_field": "revenue_growth_near",
                },
            },
        ],
        "snippets": [
            {
                "snippet_id": "10k:2025:contract-costs",
                "source_ref_id": "filing:msft:2025",
                "text": "Incremental costs to obtain a contract are capitalized and amortized.",
                "metadata": {
                    "section_key": "note_revenue",
                    "filing_date": "2025-07-30",
                },
            }
        ],
        "run_metadata": {
            "accounting_topic": "qoe",
            "source_quality": "real",
            "corpus_hash": FOCUSED_CORPUS_HASH,
        },
    }


def test_focused_evidence_to_persisted_model_change_queue_item(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_tables(conn)
    seen_packet = {}

    def judgment_callable(packet):
        seen_packet.update(packet)
        return {
            "focus_key": "qoe_revenue",
            "packet_status": "complete",
            "findings": [
                {
                    "finding_id": "finding:contract-cost-recast",
                    "topic": "qoe",
                    "focus_key": "qoe_revenue",
                    "finding_status": "candidate",
                    "finding_type": "contract_cost_capitalization",
                    "line_item": "Capitalized contract acquisition costs",
                    "claim": (
                        "Historical operating expense should be recast for the "
                        "multi-period benefit of contract acquisition costs."
                    ),
                    "reported_value": 2.4e9,
                    "proposed_value": 2.4e9,
                    "period": "2025-06-30",
                    "accounting_treatment": "reclassify",
                    "valuation_treatment": "historical_recast",
                    "evidence_anchor_ids": [
                        "ciq:contract_costs:2025",
                        "10k:2025:contract-costs",
                    ],
                    "citation_text": (
                        "Incremental costs to obtain a contract are capitalized "
                        "and amortized."
                    ),
                    "confidence": "medium",
                    "pm_question": "Should the model recast historical EBIT for these costs?",
                    "what_would_change_mind": (
                        "Evidence that the CIQ historical series already reflects "
                        "the desired analytical recast."
                    ),
                    "materiality_rationale": "The balance is large enough to affect margins.",
                    "model_change_required": True,
                    "model_change_request": (
                        "Add a contract-cost asset and amortization schedule, recast "
                        "historical EBIT, and feed normalized EBIT into the forecast."
                    ),
                }
            ],
        }

    result = run_accounting_evidence_trial(
        source_packet=_packet(),
        focus_key="qoe_revenue",
        judgment_callable=judgment_callable,
        repair_callable=lambda request: request["original_finding"],
        conn=conn,
    )

    assert seen_packet["metadata"]["focus_key"] == "qoe_revenue"
    assert seen_packet["metadata"]["evidence_corpus_hash"] == FOCUSED_CORPUS_HASH
    assert result.repair_result.status == "accepted"
    assert len(result.ledger.entries) == 1
    assert len(result.queue_items) == 1
    assert result.queue_items[0].item_type == PMDecisionQueueItemType.advisory_finding
    assert result.queue_items[0].metadata["queue_reason"] == "model_change_required"
    assert result.queue_items[0].metadata["evidence_corpus_hash"] == FOCUSED_CORPUS_HASH
    assert len(result.persisted_queue_item_ids) == 1

    persisted = list_pm_decision_queue_items(conn, ticker="MSFT", status="pending")
    assert len(persisted) == 1
    assert persisted[0]["metadata"]["model_change_required"] is True
    assert persisted[0]["proposal_pack"] is None

    monkeypatch.setattr(
        "src.stage_04_pipeline.pm_decision_queue.get_connection",
        lambda: conn,
    )
    approved = approve_pm_decision_queue_item(
        "MSFT",
        result.persisted_queue_item_ids[0],
        actor="pm",
    )

    assert approved["status"] == "approved"
    treatments = load_active_treatment_decisions(conn, "MSFT")
    assert len(treatments) == 1
    assert treatments[0]["evidence_corpus_hash"] == FOCUSED_CORPUS_HASH


def test_focused_evidence_without_a_source_corpus_hash_fails_closed(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_tables(conn)
    packet = _packet()
    packet["run_metadata"].pop("corpus_hash")

    def judgment_callable(_packet_payload):
        return {
            "focus_key": "qoe_revenue",
            "packet_status": "complete",
            "findings": [
                {
                    "topic": "qoe",
                    "focus_key": "qoe_revenue",
                    "finding_status": "candidate",
                    "finding_type": "contract_cost_capitalization",
                    "line_item": "Capitalized contract acquisition costs",
                    "claim": "The reported treatment requires a model change.",
                    "accounting_treatment": "reclassify",
                    "valuation_treatment": "historical_recast",
                    "evidence_anchor_ids": ["10k:2025:contract-costs"],
                    "materiality_rationale": "The balance is material.",
                    "model_change_required": True,
                    "model_change_request": "Add a contract-cost amortization schedule.",
                }
            ],
        }

    result = run_accounting_evidence_trial(
        source_packet=packet,
        focus_key="qoe_revenue",
        judgment_callable=judgment_callable,
        repair_callable=lambda request: request["original_finding"],
        conn=conn,
    )

    monkeypatch.setattr(
        "src.stage_04_pipeline.pm_decision_queue.get_connection",
        lambda: conn,
    )
    with pytest.raises(ValueError, match="genuine evidence corpus hash"):
        approve_pm_decision_queue_item(
            "MSFT",
            result.persisted_queue_item_ids[0],
            actor="pm",
        )

    assert load_active_treatment_decisions(conn, "MSFT") == []
    pending = list_pm_decision_queue_items(conn, ticker="MSFT", status="pending")
    assert len(pending) == 1
    assert "evidence_corpus_hash" not in pending[0]["metadata"]
