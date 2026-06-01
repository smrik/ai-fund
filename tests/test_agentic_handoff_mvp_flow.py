import sqlite3
from types import SimpleNamespace

from db.loader import (
    insert_pm_decision_queue_item,
    load_evidence_packet,
    load_approved_assumption_entries,
    load_pending_assumption_changes,
    list_pm_decision_queue_items,
)
from db.schema import create_tables
from src.contracts.evidence_packet import (
    EvidencePacketObservation,
    EvidencePacketObservationKind,
)
from src.stage_04_pipeline.evidence_packets import build_evidence_packet
from src.stage_04_pipeline.observation_translator import translate_observations_to_queue_items
from src.stage_04_pipeline.pm_decision_queue import (
    approve_pm_decision_queue_item,
    edit_pm_decision_queue_item,
    preview_pm_decision_queue_item,
)
from api.main import run_agentic_handoff_profile_payload


def test_agentic_handoff_mvp_flow_smoke(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_tables(conn)

    monkeypatch.setattr("src.stage_04_pipeline.evidence_packets.get_connection", lambda: conn)
    monkeypatch.setattr("src.stage_04_pipeline.pm_decision_queue.get_connection", lambda: conn)
    monkeypatch.setattr("src.stage_04_pipeline.pending_assumption_changes.get_connection", lambda: conn)
    monkeypatch.setattr(
        "src.stage_04_pipeline.pm_decision_queue.preview_pending_assumption_stack",
        lambda ticker, change_ids, manual_values=None: {
            "ticker": ticker,
            "change_ids": change_ids,
            "manual_values": manual_values or {},
            "proposed_iv": {"base": 120.0},
            "delta_pct": {"base": 3.5},
        },
    )
    monkeypatch.setattr(
        "src.stage_02_valuation.input_assembler.build_valuation_inputs",
        lambda ticker: SimpleNamespace(
            drivers=SimpleNamespace(revenue_growth_near=0.07, ebit_margin_target=0.20)
        ),
    )

    def _stub_collect_inputs(ticker: str, profile_name: str) -> dict:
        return {
            "source_refs": [
                {
                    "source_ref_id": f"src:{profile_name}:1",
                    "source_kind": "stub",
                    "source_label": "stub",
                    "source_locator": f"stub://{ticker}/{profile_name}",
                }
            ],
            "facts": [{"fact_id": f"fact:{profile_name}:1", "fact_name": "stub", "value": 1}],
            "snippets": [
                {
                    "snippet_id": f"snippet:{profile_name}:1",
                    "source_ref_id": f"src:{profile_name}:1",
                    "text": "stub snippet",
                }
            ],
            "source_quality": "real",
            "run_metadata": {"stubbed": True},
        }

    monkeypatch.setattr("src.stage_04_pipeline.evidence_packets._collect_profile_inputs", _stub_collect_inputs)

    earnings_packet = build_evidence_packet("IBM", "earnings_update")
    company_packet = build_evidence_packet("IBM", "company_analysis")

    earnings_obs = [
        EvidencePacketObservation(
            observation_id="obs:earnings:1",
            observation_kind=EvidencePacketObservationKind.numeric,
            observation_type="guidance_revenue_raised",
            claim="Guidance midpoint increased.",
            evidence_anchor_ids=["fact:earnings_update:1"],
            text_snippet_ids=[],
            agent_confidence="high",
            qualitative_importance="high",
        )
    ]
    company_obs = [
        EvidencePacketObservation(
            observation_id="obs:company:1",
            observation_kind=EvidencePacketObservationKind.numeric,
            observation_type="margin_target_disclosed",
            claim="Management disclosed target margin.",
            evidence_anchor_ids=["fact:company_analysis:1"],
            text_snippet_ids=[],
            metadata={"target_value": 0.22},
            agent_confidence="high",
            qualitative_importance="high",
        )
    ]

    queue_items = []
    queue_items.extend(
        translate_observations_to_queue_items(
            ticker="IBM",
            profile_name="earnings_update",
            evidence_packet_id=int(earnings_packet.packet_id or 0),
            observations=earnings_obs,
        )
    )
    queue_items.extend(
        translate_observations_to_queue_items(
            ticker="IBM",
            profile_name="company_analysis",
            evidence_packet_id=int(company_packet.packet_id or 0),
            observations=company_obs,
        )
    )

    assert len(queue_items) >= 2
    saved_ids: list[int] = []
    for item in queue_items:
        saved_ids.append(
            insert_pm_decision_queue_item(
                conn,
                {
                    **item.model_dump(),
                    "created_at": item.created_at,
                    "updated_at": item.updated_at,
                    "item_type": item.item_type.value,
                    "status": item.status.value,
                    "qualitative_importance": item.qualitative_importance.value if item.qualitative_importance else None,
                    "valuation_impact_bucket": "high",
                    "proposal_pack": item.proposal_pack.model_dump() if item.proposal_pack else None,
                    "pm_edited_proposal_pack": None,
                    "approved_proposal_pack": None,
                    "agent_confidence": item.agent_confidence.value if item.agent_confidence else None,
                    "translator_confidence": item.translator_confidence.value if item.translator_confidence else None,
                    "pm_confidence": None,
                    "valuation_impact": item.valuation_impact,
                    "evidence_anchor_ids": item.evidence_anchor_ids,
                    "evidence_packet_ids": item.evidence_packet_ids,
                    "adapter_links": item.adapter_links,
                    "decision_history": item.decision_history,
                    "metadata": item.metadata,
                },
            )
        )

    preview = preview_pm_decision_queue_item("IBM", saved_ids[0])
    assert preview["preview"]["proposed_iv"]["base"] == 120.0
    assert preview["preview"]["manual_values"]["revenue_growth_near"] == 0.08

    approved = approve_pm_decision_queue_item("IBM", saved_ids[0], actor="pm")
    assert approved["status"] == "approved"
    assert approved["adapter_links"]["pending_assumption_change_ids"]
    assert approved["approved_proposal_pack"]["proposals"][0]["proposed_target_value"] == 0.08

    edited = edit_pm_decision_queue_item(
        "IBM",
        saved_ids[1],
        {
            "pack_id": "pack:pm-edit",
            "proposals": [
                {
                    "assumption_name": "ebit_margin_target",
                    "proposal_mode": "target",
                    "proposed_target_value": 0.22,
                }
            ],
        },
        actor="pm",
    )
    assert edited["pm_edited_proposal_pack"]["pack_id"] == "pack:pm-edit"

    edited_preview = preview_pm_decision_queue_item("IBM", saved_ids[1])
    assert edited_preview["preview"]["proposed_iv"]["base"] == 120.0
    approved_edited = approve_pm_decision_queue_item("IBM", saved_ids[1], actor="pm")
    assert approved_edited["status"] == "approved"
    assert approved_edited["approved_proposal_pack"]["proposals"][0]["proposed_target_value"] == 0.22

    pending_rows = load_pending_assumption_changes(conn, ticker="IBM", status=None)
    approved_rows = load_approved_assumption_entries(conn, "IBM")
    assert len(pending_rows) >= 1
    assert len(approved_rows) >= 1
    approved_by_name = {row["assumption_name"]: row["value"] for row in approved_rows}
    assert approved_by_name["revenue_growth_near"] == 0.08
    assert approved_by_name["ebit_margin_target"] == 0.22


def test_agentic_handoff_run_blocks_placeholder_evidence(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_tables(conn)

    monkeypatch.setattr("src.stage_04_pipeline.evidence_packets.get_connection", lambda: conn)
    monkeypatch.setattr("db.schema.get_connection", lambda: conn)
    monkeypatch.setattr(
        "src.stage_04_pipeline.evidence_packets._collect_profile_inputs",
        lambda ticker, profile_name: {
            "source_refs": [
                {
                    "source_ref_id": f"src:{profile_name}:status",
                    "source_kind": "collector_status",
                    "source_label": "collector status",
                    "source_locator": f"internal://{ticker}/{profile_name}/collector-status",
                }
            ],
            "facts": [],
            "snippets": [],
            "source_quality": "placeholder",
            "run_metadata": {"reason": "collector_not_implemented"},
        },
    )
    monkeypatch.setattr(
        "src.stage_03_judgment.grounded_observation_agent.GroundedObservationAgent.analyze_evidence_packet",
        lambda self, packet, profile_name: (_ for _ in ()).throw(AssertionError("agent should not run")),
    )

    result = run_agentic_handoff_profile_payload("IBM", "earnings_update")

    assert result["status"] == "blocked"
    assert result["reason"] == "insufficient_real_evidence"
    assert result["observation_count"] == 0
    assert result["queue_item_count"] == 0
    assert result["queue_item_ids"] == []
    assert result["evidence_packet"]["run_metadata"]["source_quality"] == "placeholder"
    assert list_pm_decision_queue_items(conn, ticker="IBM", status=None) == []


def test_agentic_handoff_run_persists_observations_and_queue_results(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_tables(conn)

    monkeypatch.setattr("src.stage_04_pipeline.evidence_packets.get_connection", lambda: conn)
    monkeypatch.setattr("db.schema.get_connection", lambda: conn)
    monkeypatch.setattr(
        "src.stage_04_pipeline.evidence_packets._collect_profile_inputs",
        lambda ticker, profile_name: {
            "source_refs": [
                {
                    "source_ref_id": f"src:{profile_name}:1",
                    "source_kind": "stub",
                    "source_label": "stub source",
                    "source_locator": f"stub://{ticker}/{profile_name}",
                }
            ],
            "facts": [{"fact_id": "fact:1", "fact_name": "stub_fact", "value": 1}],
            "snippets": [],
            "source_quality": "real",
            "run_metadata": {"stubbed": True},
        },
    )
    monkeypatch.setattr(
        "src.stage_03_judgment.grounded_observation_agent.GroundedObservationAgent.analyze_evidence_packet",
        lambda self, packet, profile_name: [
            EvidencePacketObservation(
                observation_id="obs:run:1",
                observation_kind=EvidencePacketObservationKind.numeric,
                observation_type="guidance_revenue_raised",
                claim="Guidance midpoint increased.",
                evidence_anchor_ids=["fact:1"],
                text_snippet_ids=[],
                agent_confidence="high",
                qualitative_importance="high",
            )
        ],
    )

    result = run_agentic_handoff_profile_payload("IBM", "earnings_update")

    assert result["status"] == "completed_with_items"
    assert result["observation_count"] == 1
    assert result["queue_item_count"] == 1
    assert result["evidence_packet"]["observations"][0]["observation_id"] == "obs:run:1"
    assert result["evidence_packet"]["run_metadata"]["handoff_run_status"] == "completed_with_items"

    packet_id = int(result["evidence_packet"]["packet_id"])
    persisted = load_evidence_packet(conn, packet_id)
    assert persisted is not None
    assert persisted["observations"][0]["observation_id"] == "obs:run:1"
    assert persisted["run_metadata"]["handoff_run_status"] == "completed_with_items"
    assert persisted["run_metadata"]["queue_item_count"] == 1
    assert len(list_pm_decision_queue_items(conn, ticker="IBM", status=None)) == 1
