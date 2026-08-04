"""Translate one reviewed driver family into one atomic PM queue item."""

from __future__ import annotations

from src.contracts.driver_families import (
    ApplicableDriverAssumption,
    DriverFamilyCritique,
    DriverFamilyProposal,
)
from src.contracts.judgment_runs import canonical_semantic_hash
from src.contracts.pm_decision_queue import (
    AssumptionChangePack,
    AssumptionChangeProposal,
    PMDecisionQueueItem,
    PMDecisionQueueItemType,
    ProposalMode,
    QualitativeImportance,
    QueueConfidence,
    ScenarioAssumptionValues,
)


def build_driver_family_queue_item(
    *,
    ticker: str,
    proposal: DriverFamilyProposal,
    critique: DriverFamilyCritique,
    analysis_snapshot_hash: str,
    primary_run_id: str,
    critic_run_id: str,
) -> PMDecisionQueueItem:
    """Build an auditable queue item without changing valuation inputs."""

    normalized_ticker = str(ticker).strip().upper()
    if not normalized_ticker:
        raise ValueError("ticker is required")
    if proposal.family != critique.family:
        raise ValueError("proposal and critique must cover the same family")
    if critique.verdict == "block":
        raise ValueError("blocked driver families are not approvable")

    queue_proposals: list[AssumptionChangeProposal] = []
    evidence_anchor_ids: list[str] = []
    assumption_notes: dict[str, dict[str, object]] = {}
    for assumption in proposal.assumptions:
        evidence_anchor_ids.extend(assumption.evidence_anchor_ids)
        common = {
            "assumption_name": assumption.assumption_name,
            "proposal_mode": ProposalMode.scenarios,
            "applicability": assumption.applicability,
            "unit": assumption.unit,
            "horizon_years": proposal.horizon_years,
            "rationale": assumption.rationale,
            "evidence_anchor_ids": list(assumption.evidence_anchor_ids),
            "metadata": {
                "what_would_change_view": assumption.what_would_change_view,
            },
        }
        if isinstance(assumption, ApplicableDriverAssumption):
            common["scenario_values"] = ScenarioAssumptionValues(
                low=assumption.low,
                base=assumption.base,
                high=assumption.high,
            )
            common["metadata"]["scenario_conditions"] = (
                assumption.conditions.model_dump(mode="json")
            )
        queue_proposals.append(AssumptionChangeProposal.model_validate(common))
        assumption_notes[assumption.assumption_name] = dict(common["metadata"])

    ordered_anchors = list(dict.fromkeys(evidence_anchor_ids))
    identity = canonical_semantic_hash(
        {
            "ticker": normalized_ticker,
            "analysis_snapshot_hash": analysis_snapshot_hash,
            "proposal": proposal.model_dump(mode="json"),
            "critique": critique.model_dump(mode="json"),
        }
    )
    pack = AssumptionChangePack(
        pack_id=f"driver-family:{normalized_ticker}:{proposal.family.value}:{identity[:16]}",
        proposal_scope="low_base_high",
        family=proposal.family,
        analysis_snapshot_hash=analysis_snapshot_hash,
        primary_run_id=primary_run_id,
        critic_run_id=critic_run_id,
        critic_verdict=critique.verdict,
        proposals=queue_proposals,
        notes={
            "family_rationale": proposal.family_rationale,
            "critic_summary": critique.summary,
            "critic_issues": [
                issue.model_dump(mode="json") for issue in critique.issues
            ],
            "assumption_notes": assumption_notes,
        },
    )
    return PMDecisionQueueItem(
        ticker=normalized_ticker,
        profile_name=f"driver_family_{proposal.family.value}",
        item_type=PMDecisionQueueItemType.assumption_change_pack,
        title=f"{proposal.family.value.replace('_', ' ').title()} assumptions",
        summary=proposal.family_rationale,
        evidence_anchor_ids=ordered_anchors,
        proposal_pack=pack,
        qualitative_importance=QualitativeImportance.high,
        agent_confidence=QueueConfidence.medium,
        translator_confidence=QueueConfidence.high,
        metadata={
            "analysis_snapshot_hash": analysis_snapshot_hash,
            "primary_run_id": primary_run_id,
            "critic_run_id": critic_run_id,
            "critic_verdict": critique.verdict,
            "critic_conflict_visible": critique.verdict == "revise",
        },
    )


def driver_family_proposal_from_queue_pack(
    pack: AssumptionChangePack,
) -> DriverFamilyProposal:
    """Revalidate a PM-edited scenario pack through the provider contract."""

    if pack.family is None:
        raise ValueError("queue pack is not a driver family pack")
    assumption_notes = pack.notes.get("assumption_notes") or {}
    assumptions: list[dict[str, object]] = []
    horizons: set[int] = set()
    for proposal in pack.proposals:
        if proposal.proposal_mode != ProposalMode.scenarios:
            raise ValueError("driver family pack contains a non-scenario proposal")
        if proposal.unit is None or proposal.horizon_years is None:
            raise ValueError("driver family proposal is missing unit or horizon")
        horizons.add(proposal.horizon_years)
        note = assumption_notes.get(proposal.assumption_name) or {}
        payload: dict[str, object] = {
            "assumption_name": proposal.assumption_name,
            "unit": proposal.unit,
            "applicability": proposal.applicability,
            "rationale": proposal.rationale or "",
            "evidence_anchor_ids": proposal.evidence_anchor_ids,
            "what_would_change_view": note.get("what_would_change_view") or "",
        }
        if proposal.applicability == "applicable":
            if proposal.scenario_values is None:
                raise ValueError(
                    f"{proposal.assumption_name} is missing scenario values"
                )
            payload.update(
                {
                    "low": proposal.scenario_values.low,
                    "base": proposal.scenario_values.base,
                    "high": proposal.scenario_values.high,
                    "conditions": note.get("scenario_conditions") or {},
                }
            )
        assumptions.append(payload)
    if len(horizons) != 1:
        raise ValueError("all assumptions in a family must share one horizon")
    return DriverFamilyProposal.model_validate(
        {
            "family": pack.family,
            "horizon_years": next(iter(horizons)),
            "assumptions": assumptions,
            "family_rationale": pack.notes.get("family_rationale") or "",
        }
    )


def approved_scenario_values_from_queue_pack(
    pack: AssumptionChangePack,
) -> dict[str, dict[str, float]]:
    """Return complete direct values for deterministic low/base/high replay."""

    proposal = driver_family_proposal_from_queue_pack(pack)
    values: dict[str, dict[str, float]] = {
        "low": {},
        "base": {},
        "high": {},
    }
    for assumption in proposal.assumptions:
        if isinstance(assumption, ApplicableDriverAssumption):
            for scenario in ("low", "base", "high"):
                values[scenario][assumption.assumption_name] = float(
                    getattr(assumption, scenario)
                )
        else:
            for scenario in ("low", "base", "high"):
                values[scenario][assumption.assumption_name] = 0.0
    return values
