from __future__ import annotations

from src.contracts.analysis_snapshot import AnalysisSnapshot
from src.contracts.judgment_runs import ProviderRoute
from src.stage_03_judgment.judgment_gateway import JudgmentBackendResponse
from src.stage_03_judgment.judgment_gateway import JudgmentGateway
from src.stage_04_pipeline.driver_family_workflow import (
    run_driver_family_workflow,
)


def _snapshot() -> AnalysisSnapshot:
    return AnalysisSnapshot.model_validate(
        {
            "ticker": "TEST",
            "as_of_date": "2026-07-26",
            "identity": {"cik": "0000000001", "currency": "USD"},
            "statements": {"annual_periods": 5, "ltm_status": "compatible"},
            "statement_reconciliation": {"status": "reconciled"},
            "claim_ledger": {"status": "reconciled"},
            "market_inputs": {"price": 10.0},
            "wacc_inputs": {"wacc": 0.09},
            "comps_inputs": {"peer_count": 4},
            "approved_treatments": [],
            "evidence": {
                "fact:revenue_growth_near": {"value": 0.07},
                "fact:revenue_growth_mid": {"value": 0.05},
                "fact:revenue_growth_terminal": {"value": 0.025},
            },
            "upstream_context": {
                "business": {"summary": "Recurring revenue business."},
                "industry": {"summary": "Maturing category."},
            },
            "source_fingerprints": {"xbrl": "xbrl-1", "ciq": "ciq-1"},
            "component_versions": {"evidence_compiler": "v1"},
            "captured_at": "2026-07-26T10:00:00Z",
        }
    )


def _route(role: str) -> ProviderRoute:
    return ProviderRoute.model_validate(
        {
            "route_id": f"fixture-{role}",
            "provider": "fixture",
            "adapter_id": "fixture",
            "adapter_version": "1.0.0",
            "requested_model": f"fixture-{role}-model",
            "endpoint_capability": "structured",
            "sampling": {"temperature": 0.0, "max_output_tokens": 4096},
        }
    )


def _revenue_payload() -> dict[str, object]:
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
                    "low": f"Low evidence case for {name}.",
                    "base": f"Base evidence case for {name}.",
                    "high": f"High evidence case for {name}.",
                },
                "rationale": f"Reasoned directly from {name} evidence.",
                "evidence_anchor_ids": [f"fact:{name}"],
                "what_would_change_view": f"New evidence for {name}.",
            }
        )
    return {
        "family": "revenue",
        "horizon_years": 10,
        "assumptions": assumptions,
        "family_rationale": "Direct scenarios reflect the frozen evidence.",
    }


class _Backend:
    def __init__(
        self,
        output: dict[str, object] | list[dict[str, object]],
    ) -> None:
        self.outputs = output if isinstance(output, list) else [output]
        self.requests = []

    def generate(self, request):
        self.requests.append(request)
        output_index = min(len(self.requests) - 1, len(self.outputs) - 1)
        return JudgmentBackendResponse(
            output=self.outputs[output_index],
            actual_model=request.route.requested_model,
            provider_request_id=f"request-{len(self.requests)}",
        )


def test_primary_and_critic_produce_one_atomic_queue_item_from_one_snapshot() -> None:
    primary = _Backend(_revenue_payload())
    critic = _Backend(
        {
            "family": "revenue",
            "verdict": "accept",
            "issues": [],
            "summary": "The assumptions are evidence-grounded and coherent.",
        }
    )

    result = run_driver_family_workflow(
        snapshot=_snapshot(),
        family="revenue",
        primary_route=_route("primary"),
        primary_backend=primary,
        critic_route=_route("critic"),
        critic_backend=critic,
    )

    assert result.status == "queued"
    assert result.queue_item is not None
    assert result.queue_item.proposal_pack.family.value == "revenue"
    assert result.queue_item.proposal_pack.analysis_snapshot_hash == _snapshot().snapshot_hash
    assert len(result.queue_item.proposal_pack.proposals) == 3
    assert primary.requests[0].task.frozen_snapshot_hash == _snapshot().snapshot_hash
    assert critic.requests[0].task.reviewed_output_hash


def test_revise_verdict_allows_exactly_one_primary_revision_and_queues_it() -> None:
    original = _revenue_payload()
    revised = _revenue_payload()
    revised["assumptions"][0]["base"] = 0.08
    revised["assumptions"][0]["high"] = 0.11
    revised["assumptions"][0]["rationale"] = (
        "Revised directly from the critic-identified evidence gap."
    )
    primary = _Backend([original, revised])
    critic = _Backend(
        [
            {
                "family": "revenue",
                "verdict": "revise",
                "issues": [
                    {
                        "code": "near_growth_underweighted",
                        "severity": "warning",
                        "assumption_names": ["revenue_growth_near"],
                        "detail": "The base case underweights the cited evidence.",
                        "evidence_anchor_ids": ["fact:revenue_growth_near"],
                        "required_revision": "Reassess the near-term base and high cases.",
                    }
                ],
                "summary": "One targeted revision is required.",
            },
            {
                "family": "revenue",
                "verdict": "accept",
                "issues": [],
                "summary": "The revised complete family resolves the evidence gap.",
            },
        ]
    )

    result = run_driver_family_workflow(
        snapshot=_snapshot(),
        family="revenue",
        primary_route=_route("primary"),
        primary_backend=primary,
        critic_route=_route("critic"),
        critic_backend=critic,
        transport_timeout_seconds=17.25,
    )

    assert result.status == "queued"
    assert len(primary.requests) == 2
    assert len(critic.requests) == 2
    assert {
        request.transport_timeout_seconds
        for request in [*primary.requests, *critic.requests]
    } == {17.25}
    assert result.revision_envelope is not None
    assert result.revision_critic_envelope is not None
    assert result.primary_envelope.run_id != result.revision_envelope.run_id
    assert result.proposal is not None
    assert result.proposal.assumptions[0].base == 0.08
    assert result.queue_item is not None
    assert (
        result.queue_item.proposal_pack.primary_run_id
        == result.revision_envelope.run_id
    )
    assert result.queue_item.metadata["initial_primary_run_id"] == (
        result.primary_envelope.run_id
    )
    assert result.queue_item.metadata["initial_critic_run_id"] == (
        result.critic_envelope.run_id
    )
    assert result.queue_item.proposal_pack.critic_run_id == (
        result.revision_critic_envelope.run_id
    )
    revision_task = primary.requests[1].task
    assert revision_task.frozen_snapshot_hash == _snapshot().snapshot_hash
    assert revision_task.reviewed_output_hash
    assert "revision" in revision_task.task_version


def test_revised_family_blocks_when_final_critic_does_not_accept() -> None:
    primary = _Backend([_revenue_payload(), _revenue_payload()])
    issue = {
        "code": "still_unsupported",
        "severity": "blocking",
        "assumption_names": ["revenue_growth_near"],
        "detail": "The revision remains unsupported.",
        "evidence_anchor_ids": ["fact:revenue_growth_near"],
        "required_revision": "Do not queue the unresolved family.",
    }
    critic = _Backend(
        [
            {
                "family": "revenue",
                "verdict": "revise",
                "issues": [{**issue, "severity": "warning"}],
                "summary": "Revise once.",
            },
            {
                "family": "revenue",
                "verdict": "block",
                "issues": [issue],
                "summary": "The final family is not approvable.",
            },
        ]
    )

    result = run_driver_family_workflow(
        snapshot=_snapshot(),
        family="revenue",
        primary_route=_route("primary"),
        primary_backend=primary,
        critic_route=_route("critic"),
        critic_backend=critic,
    )

    assert result.status == "blocked"
    assert result.blocker_reason == "revision_not_accepted"
    assert len(primary.requests) == 2
    assert len(critic.requests) == 2
    assert result.queue_item is None


def test_failed_single_revision_blocks_instead_of_queueing_original_values() -> None:
    primary = _Backend(
        [
            _revenue_payload(),
            {"family": "revenue", "assumptions": []},
        ]
    )
    critic = _Backend(
        {
            "family": "revenue",
            "verdict": "revise",
            "issues": [
                {
                    "code": "unsupported",
                    "severity": "warning",
                    "assumption_names": ["revenue_growth_near"],
                    "detail": "The proposal requires revision.",
                    "evidence_anchor_ids": ["fact:revenue_growth_near"],
                    "required_revision": "Ground the values in the cited evidence.",
                }
            ],
            "summary": "Revise once.",
        }
    )

    result = run_driver_family_workflow(
        snapshot=_snapshot(),
        family="revenue",
        primary_route=_route("primary"),
        primary_backend=primary,
        critic_route=_route("critic"),
        critic_backend=critic,
    )

    assert result.status == "blocked"
    assert len(primary.requests) == 3
    assert primary.requests[1].task.semantic_task_hash == (
        primary.requests[2].task.semantic_task_hash
    )
    assert result.revision_envelope is not None
    assert len(result.revision_envelope.attempts) == 2
    assert result.blocker_reason == "primary_revision_failed"
    assert result.queue_item is None


def test_hallucinated_evidence_anchor_blocks_before_critic_or_queue() -> None:
    payload = _revenue_payload()
    payload["assumptions"][0]["evidence_anchor_ids"] = [
        "fact:not-in-frozen-snapshot"
    ]
    primary = _Backend(payload)
    critic = _Backend(
        {
            "family": "revenue",
            "verdict": "accept",
            "issues": [],
            "summary": "Should not be called.",
        }
    )

    result = run_driver_family_workflow(
        snapshot=_snapshot(),
        family="revenue",
        primary_route=_route("primary"),
        primary_backend=primary,
        critic_route=_route("critic"),
        critic_backend=critic,
    )

    assert result.status == "blocked"
    assert result.blocker_reason == "primary_unknown_evidence_anchors"
    assert critic.requests == []
    assert result.queue_item is None


def test_family_projection_overflow_blocks_before_any_provider_call() -> None:
    snapshot = _snapshot().model_copy(
        update={
            "evidence": {
                **_snapshot().evidence,
                "fact:oversized": {"text": "x" * 500},
            }
        }
    )
    primary = _Backend(_revenue_payload())
    critic = _Backend(
        {
            "family": "revenue",
            "verdict": "accept",
            "issues": [],
            "summary": "Should not be called.",
        }
    )

    result = run_driver_family_workflow(
        snapshot=snapshot,
        family="revenue",
        primary_route=_route("primary"),
        primary_backend=primary,
        critic_route=_route("critic"),
        critic_backend=critic,
        max_projection_chars=100,
    )

    assert result.status == "blocked"
    assert result.blocker_reason == "family_projection_overflow"
    assert result.primary_envelope is None
    assert primary.requests == []
    assert critic.requests == []


def test_force_refresh_reaches_primary_critic_revision_and_final_critic() -> None:
    stored = {}
    gateway = JudgmentGateway(
        envelope_sink=lambda envelope: stored.__setitem__(
            envelope.idempotency_key,
            envelope,
        ),
        successful_envelope_lookup=stored.get,
    )
    revise = {
        "family": "revenue",
        "verdict": "revise",
        "issues": [
            {
                "code": "reassess",
                "severity": "warning",
                "assumption_names": ["revenue_growth_near"],
                "detail": "Reassess the cited evidence.",
                "evidence_anchor_ids": ["fact:revenue_growth_near"],
                "required_revision": "Revise the complete family.",
            }
        ],
        "summary": "One revision is required.",
    }
    accept = {
        "family": "revenue",
        "verdict": "accept",
        "issues": [],
        "summary": "The complete revised family is accepted.",
    }

    first_primary = _Backend([_revenue_payload(), _revenue_payload()])
    first_critic = _Backend([revise, accept])
    first = run_driver_family_workflow(
        snapshot=_snapshot(),
        family="revenue",
        primary_route=_route("primary"),
        primary_backend=first_primary,
        critic_route=_route("critic"),
        critic_backend=first_critic,
        gateway=gateway,
    )
    assert first.status == "queued"

    refreshed_primary = _Backend([_revenue_payload(), _revenue_payload()])
    refreshed_critic = _Backend([revise, accept])
    refreshed = run_driver_family_workflow(
        snapshot=_snapshot(),
        family="revenue",
        primary_route=_route("primary"),
        primary_backend=refreshed_primary,
        critic_route=_route("critic"),
        critic_backend=refreshed_critic,
        gateway=gateway,
        force_refresh=True,
    )

    assert refreshed.status == "queued"
    assert len(refreshed_primary.requests) == 2
    assert len(refreshed_critic.requests) == 2
