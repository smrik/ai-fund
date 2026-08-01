from __future__ import annotations

import sqlite3

import pytest

from db.loader import (
    insert_pm_decision_queue_item,
)
from db.schema import create_tables
from src.contracts.analysis_snapshot import AnalysisSnapshot
from src.contracts.driver_families import (
    DriverFamilyCritique,
    DriverFamilyProposal,
)
from src.contracts.pm_decision_queue import (
    AssumptionChangeProposal,
    ProposalMode,
)
from src.contracts.judgment_runs import ProviderRoute
from src.stage_03_judgment.judgment_gateway import (
    JudgmentBackendResponse,
    JudgmentGateway,
)
from src.stage_04_pipeline.driver_family_queue import (
    approved_scenario_values_from_queue_pack,
    build_driver_family_queue_item,
    driver_family_proposal_from_queue_pack,
)
from src.stage_04_pipeline.pm_decision_queue import (
    apply_pm_decision_queue_item,
    approve_pm_decision_queue_item,
    preview_pm_decision_queue_item,
)
from src.stage_04_pipeline.driver_family_workflow import (
    run_driver_family_workflow,
)
from src.stage_04_pipeline.valuation_run_store import (
    persist_agent_run_envelope,
    persist_analysis_snapshot,
)
from tests.valuation_provenance_fixtures import (
    authoritative_snapshot,
    persist_snapshot_provenance,
)


def test_queue_proposal_preserves_low_base_high_as_one_atomic_driver() -> None:
    proposal = AssumptionChangeProposal.model_validate(
        {
            "assumption_name": "revenue_growth_near",
            "proposal_mode": "scenarios",
            "scenario_values": {
                "low": 0.04,
                "base": 0.07,
                "high": 0.10,
            },
            "unit": "decimal",
            "horizon_years": 10,
            "rationale": "The range follows disclosed demand.",
            "evidence_anchor_ids": ["fact:revenue:guidance"],
            "metadata": {
                "scenario_conditions": {
                    "low": "Demand softens.",
                    "base": "Guidance holds.",
                    "high": "Share gains accelerate.",
                }
            },
        }
    )

    assert proposal.proposal_mode == ProposalMode.scenarios
    assert proposal.scenario_values.base == pytest.approx(0.07)
    assert proposal.proposed_delta is None
    assert proposal.proposed_target_value is None


def _revenue_pack() -> DriverFamilyProposal:
    assumptions = []
    for name, values in (
        ("revenue_growth_near", (0.04, 0.07, 0.10)),
        ("revenue_growth_mid", (0.03, 0.05, 0.08)),
        ("revenue_growth_terminal", (0.015, 0.025, 0.03)),
    ):
        assumptions.append(
            {
                "assumption_name": name,
                "unit": "decimal",
                "applicability": "applicable",
                "low": values[0],
                "base": values[1],
                "high": values[2],
                "conditions": {
                    "low": f"Low condition for {name}.",
                    "base": f"Base condition for {name}.",
                    "high": f"High condition for {name}.",
                },
                "rationale": f"Evidence-grounded rationale for {name}.",
                "evidence_anchor_ids": [f"fact:{name}"],
                "what_would_change_view": f"New evidence for {name}.",
            }
        )
    return DriverFamilyProposal.model_validate(
        {
            "family": "revenue",
            "horizon_years": 10,
            "assumptions": assumptions,
            "family_rationale": "The family follows disclosed demand.",
        }
    )


def _snapshot() -> AnalysisSnapshot:
    return authoritative_snapshot(
        {
            "ticker": "TEST",
            "as_of_date": "2026-07-26",
            "identity": {"cik": "0000000001"},
            "statements": {
                "annual_period_count": 5,
                "ltm_status": "constructed",
            },
            "statement_reconciliation": {"status": "decision_grade"},
            "claim_ledger": {
                "status": "reconciled",
                "fingerprint": "claim-ledger",
            },
            "market_inputs": {
                "operating_reconciliation": {
                    "status": "reconciled",
                    "fingerprint": "operating",
                }
            },
            "wacc_inputs": {"wacc": 0.09},
            "comps_inputs": {"peer_count": 4},
            "approved_treatments": [],
            "evidence": {
                f"fact:{name}": {"value": index}
                for index, name in enumerate(
                    (
                        "revenue_growth_near",
                        "revenue_growth_mid",
                        "revenue_growth_terminal",
                    ),
                    start=1,
                )
            },
            "upstream_context": {
                "business": {"status": "complete"},
                "industry": {"status": "complete"},
            },
            "source_fingerprints": {
                "xbrl": "xbrl-hash",
                "ciq": "ciq-hash",
            },
            "component_versions": {
                "valuation_model": "industrial_fcff_v1"
            },
            "captured_at": "2026-07-26T10:00:00Z",
        }
    )


def _route(role: str) -> ProviderRoute:
    return ProviderRoute.model_validate(
        {
            "route_id": f"fixture-{role}",
            "provider": "fixture",
            "adapter_id": "fixture",
            "adapter_version": "v1",
            "requested_model": f"fixture-{role}",
            "endpoint_capability": "structured",
            "sampling": {"temperature": 0.0},
        }
    )


class _Backend:
    def generate(self, request):
        output = (
            {
                "family": "revenue",
                "verdict": "accept",
                "issues": [],
                "summary": "The pack is coherent.",
            }
            if request.task.role == "critic"
            else _revenue_pack().model_dump(mode="json")
        )
        return JudgmentBackendResponse(
            output=output,
            actual_model=request.route.requested_model,
            provider_request_id=f"{request.task.role}-request",
        )


def test_family_pack_becomes_one_traceable_atomic_pm_queue_item() -> None:
    critique = DriverFamilyCritique.model_validate(
        {
            "family": "revenue",
            "verdict": "accept",
            "issues": [],
            "summary": "The scenario pack is evidence-grounded and internally coherent.",
        }
    )

    item = build_driver_family_queue_item(
        ticker="test",
        proposal=_revenue_pack(),
        critique=critique,
        analysis_snapshot_hash="snapshot-123",
        primary_run_id="primary-run-1",
        critic_run_id="critic-run-1",
    )

    assert item.ticker == "TEST"
    assert item.item_type.value == "assumption_change_pack"
    assert item.proposal_pack.family.value == "revenue"
    assert item.proposal_pack.analysis_snapshot_hash == "snapshot-123"
    assert item.proposal_pack.primary_run_id == "primary-run-1"
    assert item.proposal_pack.critic_run_id == "critic-run-1"
    assert item.proposal_pack.critic_verdict == "accept"
    assert all(
        proposal.proposal_mode == ProposalMode.scenarios
        for proposal in item.proposal_pack.proposals
    )
    assert set(item.evidence_anchor_ids) == {
        "fact:revenue_growth_near",
        "fact:revenue_growth_mid",
        "fact:revenue_growth_terminal",
    }
    assert (
        driver_family_proposal_from_queue_pack(item.proposal_pack).model_dump(
            mode="json"
        )
        == _revenue_pack().model_dump(mode="json")
    )
    assert approved_scenario_values_from_queue_pack(item.proposal_pack) == {
        "low": {
            "revenue_growth_near": 0.04,
            "revenue_growth_mid": 0.03,
            "revenue_growth_terminal": 0.015,
        },
        "base": {
            "revenue_growth_near": 0.07,
            "revenue_growth_mid": 0.05,
            "revenue_growth_terminal": 0.025,
        },
        "high": {
            "revenue_growth_near": 0.10,
            "revenue_growth_mid": 0.08,
            "revenue_growth_terminal": 0.03,
        },
    }


def test_pm_preview_and_approval_preserve_atomic_scenarios_without_scalar_rows(
    monkeypatch,
) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_tables(conn)
    monkeypatch.setattr(
        "src.stage_04_pipeline.pm_decision_queue.get_connection",
        lambda: conn,
    )
    snapshot = _snapshot()
    persist_snapshot_provenance(conn, snapshot)
    persist_analysis_snapshot(conn, snapshot)
    result = run_driver_family_workflow(
        snapshot=snapshot,
        family="revenue",
        primary_route=_route("primary"),
        primary_backend=_Backend(),
        critic_route=_route("critic"),
        critic_backend=_Backend(),
        gateway=JudgmentGateway(
            envelope_sink=lambda envelope: persist_agent_run_envelope(
                conn,
                envelope,
            )
        ),
    )
    assert result.queue_item is not None
    stored_item = result.queue_item.model_dump(mode="json")
    stored_item["valuation_impact_bucket"] = "high"
    item_id = insert_pm_decision_queue_item(conn, stored_item)

    preview = preview_pm_decision_queue_item("TEST", item_id)
    assert preview["preview"]["proposal_scope"] == "low_base_high"
    assert preview["preview"]["scenario_values"]["base"] == {
        "revenue_growth_near": 0.07,
        "revenue_growth_mid": 0.05,
        "revenue_growth_terminal": 0.025,
    }
    approved = approve_pm_decision_queue_item("TEST", item_id, actor="pm")
    assert {
        proposal["proposal_mode"]
        for proposal in approved["approved_proposal_pack"]["proposals"]
    } == {"scenarios"}
    assert conn.execute(
        "SELECT COUNT(*) FROM pending_assumption_changes"
    ).fetchone()[0] == 0
    assert approved["adapter_links"]["scalar_pending_rows_created"] == 0
    with pytest.raises(ValueError, match="scalar apply is not supported"):
        apply_pm_decision_queue_item("TEST", item_id, actor="pm")
