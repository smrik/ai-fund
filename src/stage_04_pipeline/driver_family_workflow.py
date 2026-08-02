"""Focused primary-plus-critic workflow for valuation driver families."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
from typing import Literal

from config.llm_routing import resolve_family_projection_limit_chars
from src.contracts.analysis_snapshot import AnalysisSnapshot
from src.contracts.assumption_registry import (
    DriverFamily,
    get_assumption_definition,
    judgment_owned_fields,
)
from src.contracts.driver_families import (
    DriverFamilyCritique,
    DriverFamilyProposal,
)
from src.contracts.judgment_runs import (
    AgentRunEnvelope,
    JudgmentTask,
    ProviderRoute,
    canonical_semantic_hash,
)
from src.contracts.pm_decision_queue import PMDecisionQueueItem
from src.stage_03_judgment.judgment_gateway import (
    JudgmentGateway,
    StructuredJudgmentBackend,
)
from src.stage_04_pipeline.driver_family_queue import (
    build_driver_family_queue_item,
)


DRIVER_FAMILY_PROMPT_VERSION = "1.1.0"
DRIVER_FAMILY_COMPILER_VERSION = "1.0.0"

_FAMILY_STATEMENT_TYPES: dict[DriverFamily, tuple[str, ...]] = {
    DriverFamily.revenue: ("IncomeStatement",),
    DriverFamily.profitability_tax: ("IncomeStatement",),
    DriverFamily.reinvestment_working_capital: (
        "BalanceSheet",
        "CashFlowStatement",
    ),
    DriverFamily.terminal_capital_comps: (),
}

_PRIMARY_SYSTEM_PROMPT = """\
You are a fundamental-equity analyst authoring one focused valuation-driver family.
Use only the frozen evidence supplied in the request. Author direct low, base, and high
case values for this company; do not apply sector constants, canned deltas, score
coefficients, or mechanical averaging. Cite only evidence anchor IDs present in the
snapshot. Every evidence_anchor_ids value must be an exact string from
allowed_evidence_anchor_ids in the user payload. Nested paths into comps_inputs,
statements, or market_inputs are not evidence anchor IDs. Explain the conditions for each
case and what evidence would change the view.
Mark a conditional driver not_applicable only when the evidence establishes that fact.
Return only the requested structured contract."""

_CRITIC_SYSTEM_PROMPT = """\
You are the independent grounded critic for one valuation-driver family. Review the
primary proposal against the same frozen evidence, reconciled statements, business
analysis, industry analysis, and comps inputs. Identify unsupported leaps, internal
inconsistency, missing evidence, scenario-order errors, and reconciliation risk. Do not
replace, average, or silently edit the primary values. If deterministic WACC or another
model methodology is structurally inadequate, emit a methodology challenge with evidence
and required capability; never invent a numeric proxy. Every evidence_anchor_ids value must
be an exact string from allowed_evidence_anchor_ids in the user payload. Nested paths into
comps_inputs, statements, or market_inputs are not evidence anchor IDs. Return only the
requested structured critique contract."""

_REVISION_SYSTEM_PROMPT = """\
You are the original fundamental-equity analyst revising one focused valuation-driver
family exactly once. Reassess the entire atomic family against the same frozen evidence
and address the critic's explicit issues. Keep or change each direct low, base, and high
value based on evidence; do not copy values from the critic, mechanically average,
apply sector constants, canned deltas, or score coefficients. Return the complete
structured family contract, not a patch. Every evidence_anchor_ids value must be an exact
string from allowed_evidence_anchor_ids in the user payload. Nested paths into comps_inputs,
statements, or market_inputs are not evidence anchor IDs."""


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _family_contract_context(family: DriverFamily) -> list[dict[str, str]]:
    context = []
    for name in judgment_owned_fields(family):
        definition = get_assumption_definition(name)
        context.append(
            {
                "assumption_name": name,
                "unit": definition.unit.value,
                "applicability": definition.applicability.value,
                "scenario_direction": (
                    definition.scenario_direction.value
                    if definition.scenario_direction is not None
                    else "unordered"
                ),
            }
        )
    return context


def _family_statement_projection(
    statements: Mapping[str, object],
    family: DriverFamily,
) -> tuple[dict[str, object], dict[str, object]]:
    """Keep every relevant statement row in a compact, explicit family view.

    The authoritative snapshot retains the complete statement ledger. The request
    projection only carries the full statement classes needed by this family,
    represented columnarly so repeated JSON field names do not consume context.
    Every selected fact's value, identity, period, source, locator, and ingestion
    fingerprint remain present. Only repeated presentation-hierarchy metadata is
    omitted and recorded in the projection scope; this is not size-based truncation.
    """

    records = statements.get("consolidated_view")
    retained_types = _FAMILY_STATEMENT_TYPES[family]
    if not isinstance(records, (list, tuple)):
        return (
            dict(statements),
            {
                "format": "snapshot-native",
                "source_fact_count": None,
                "retained_fact_count": None,
                "retained_statement_types": list(retained_types),
            },
        )

    selected_records = [
        record
        for record in records
        if isinstance(record, Mapping)
        and record.get("statement") in retained_types
    ]
    all_columns = {
        str(key)
        for record in selected_records
        for key in record
    }
    omitted_record_fields = sorted(all_columns & {"hierarchy"})
    columns = sorted(
        all_columns - set(omitted_record_fields)
    )
    compact_records = {
        "format": "columnar-records-v1",
        "columns": columns,
        "rows": [
            [record.get(column) for column in columns]
            for record in selected_records
        ],
    }
    projected = {
        key: value
        for key, value in statements.items()
        if key not in {"consolidated_view", "fact_ids"}
    }
    projected["fact_ids"] = [
        record["fact_id"]
        for record in selected_records
        if record.get("fact_id")
    ]
    projected["consolidated_view"] = compact_records
    scope = {
        "format": "family-relevant-columnar-records-v1",
        "source_fact_count": len(records),
        "retained_fact_count": len(selected_records),
        "retained_statement_types": list(retained_types),
        "omitted_record_fields": omitted_record_fields,
        "omission_reason": (
            "presentation hierarchy is redundant with the fact identity and "
            "source lineage carried in this view"
            if omitted_record_fields
            else None
        ),
    }
    projected["projection_scope"] = scope
    return projected, scope


def _family_analysis_projection(
    snapshot: AnalysisSnapshot,
    family: DriverFamily,
    *,
    max_chars: int,
) -> dict[str, object]:
    """Return a deterministic family view; never silently truncate evidence."""

    if max_chars < 1:
        raise ValueError("max projection size must be positive")
    family_components = {
        DriverFamily.revenue: (
            "statements",
            "statement_reconciliation",
            "market_inputs",
            "comps_inputs",
        ),
        DriverFamily.profitability_tax: (
            "statements",
            "statement_reconciliation",
            "market_inputs",
            "wacc_inputs",
        ),
        DriverFamily.reinvestment_working_capital: (
            "statements",
            "statement_reconciliation",
            "claim_ledger",
            "market_inputs",
        ),
        DriverFamily.terminal_capital_comps: (
            "claim_ledger",
            "market_inputs",
            "wacc_inputs",
            "comps_inputs",
        ),
    }[family]
    projected_statements, statement_scope = _family_statement_projection(
        snapshot.statements,
        family,
    )
    projection: dict[str, object] = {
        "ticker": snapshot.ticker,
        "as_of_date": snapshot.as_of_date,
        "analysis_snapshot_hash": snapshot.snapshot_hash,
        "family": family.value,
        "identity": snapshot.identity,
        "approved_treatments": snapshot.approved_treatments,
        "evidence": snapshot.evidence,
        "upstream_context": snapshot.upstream_context,
        "source_fingerprints": snapshot.source_fingerprints,
        "component_versions": snapshot.component_versions,
        "projection_scope": {"statements": statement_scope},
    }
    for component in family_components:
        projection[component] = (
            projected_statements
            if component == "statements"
            else getattr(snapshot, component)
        )
    encoded = _canonical_json(projection)
    if len(encoded) > max_chars:
        raise OverflowError(
            "family projection exceeds deterministic context bound: "
            f"family={family.value}, chars={len(encoded)}, max={max_chars}"
        )
    return projection


def _proposal_unknown_anchors(
    proposal: DriverFamilyProposal,
    snapshot: AnalysisSnapshot,
) -> set[str]:
    available = set(snapshot.evidence)
    return {
        anchor
        for assumption in proposal.assumptions
        for anchor in assumption.evidence_anchor_ids
        if anchor not in available
    }


def _critique_unknown_anchors(
    critique: DriverFamilyCritique,
    snapshot: AnalysisSnapshot,
) -> set[str]:
    available = set(snapshot.evidence)
    issue_anchors = {
        anchor
        for issue in critique.issues
        for anchor in issue.evidence_anchor_ids
        if anchor not in available
    }
    challenge_anchors = {
        anchor
        for challenge in critique.methodology_challenges
        for anchor in challenge.evidence_anchor_ids
        if anchor not in available
    }
    return issue_anchors | challenge_anchors


def _task(
    *,
    snapshot: AnalysisSnapshot,
    family: DriverFamily,
    role: Literal["primary", "critic", "revision"],
    analysis_projection: dict[str, object],
    reviewed_proposal: DriverFamilyProposal | None = None,
    critique: DriverFamilyCritique | None = None,
) -> JudgmentTask:
    output_model = (
        DriverFamilyCritique if role == "critic" else DriverFamilyProposal
    )
    system_prompt = {
        "primary": _PRIMARY_SYSTEM_PROMPT,
        "critic": _CRITIC_SYSTEM_PROMPT,
        "revision": _REVISION_SYSTEM_PROMPT,
    }[role]
    static_prompt_identity = {
        "version": DRIVER_FAMILY_PROMPT_VERSION,
        "role": role,
        "system_prompt": system_prompt,
        "family_contract": _family_contract_context(family),
    }
    user_payload: dict[str, object] = {
        "ticker": snapshot.ticker,
        "as_of_date": snapshot.as_of_date,
        "family": family.value,
        "family_contract": _family_contract_context(family),
        "analysis_snapshot_hash": snapshot.snapshot_hash,
        "analysis_snapshot": analysis_projection,
        "allowed_evidence_anchor_ids": sorted(snapshot.evidence),
    }
    reviewed_identity: dict[str, object] = {}
    if reviewed_proposal is not None:
        reviewed_payload = reviewed_proposal.model_dump(mode="json")
        user_payload["primary_proposal"] = reviewed_payload
        reviewed_identity["primary_proposal"] = reviewed_payload
    if critique is not None:
        critique_payload = critique.model_dump(mode="json")
        user_payload["critic_review"] = critique_payload
        reviewed_identity["critic_review"] = critique_payload
    reviewed_hash = (
        canonical_semantic_hash(reviewed_identity)
        if reviewed_identity
        else None
    )
    schema = output_model.model_json_schema()
    return JudgmentTask(
        task_version=f"driver-family-{role}-{DRIVER_FAMILY_PROMPT_VERSION}",
        ticker=snapshot.ticker,
        family=family.value,
        role=role,
        frozen_snapshot_hash=snapshot.snapshot_hash,
        prompt_id=f"driver-family.{family.value}.{role}",
        prompt_hash=canonical_semantic_hash(static_prompt_identity),
        schema_id=output_model.__name__,
        schema_hash=canonical_semantic_hash(schema),
        compiler_id="driver-family-message-compiler",
        compiler_hash=canonical_semantic_hash(
            {"version": DRIVER_FAMILY_COMPILER_VERSION}
        ),
        messages=(
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": _canonical_json(user_payload)},
        ),
        reviewed_output_hash=reviewed_hash,
    )


@dataclass(frozen=True, slots=True)
class DriverFamilyWorkflowResult:
    status: Literal["queued", "blocked"]
    family: DriverFamily
    primary_envelope: AgentRunEnvelope | None
    critic_envelope: AgentRunEnvelope | None
    revision_envelope: AgentRunEnvelope | None
    revision_critic_envelope: AgentRunEnvelope | None
    proposal: DriverFamilyProposal | None
    critique: DriverFamilyCritique | None
    queue_item: PMDecisionQueueItem | None
    blocker_reason: str | None = None


def run_driver_family_workflow(
    *,
    snapshot: AnalysisSnapshot,
    family: DriverFamily | str,
    primary_route: ProviderRoute,
    primary_backend: StructuredJudgmentBackend,
    critic_route: ProviderRoute,
    critic_backend: StructuredJudgmentBackend,
    gateway: JudgmentGateway | None = None,
    force_refresh: bool = False,
    transport_timeout_seconds: float = 120.0,
    max_projection_chars: int | None = None,
) -> DriverFamilyWorkflowResult:
    """Run one primary and one critic against an identical frozen snapshot."""

    selected_family = DriverFamily(family)
    resolved_gateway = gateway or JudgmentGateway()
    projection_limit = (
        resolve_family_projection_limit_chars(
            primary_route.provider,
            primary_route.requested_model,
            critic_route.requested_model,
        )
        if max_projection_chars is None
        else max_projection_chars
    )
    try:
        analysis_projection = _family_analysis_projection(
            snapshot,
            selected_family,
            max_chars=projection_limit,
        )
    except OverflowError:
        return DriverFamilyWorkflowResult(
            status="blocked",
            family=selected_family,
            primary_envelope=None,
            critic_envelope=None,
            revision_envelope=None,
            revision_critic_envelope=None,
            proposal=None,
            critique=None,
            queue_item=None,
            blocker_reason="family_projection_overflow",
        )
    primary_envelope = resolved_gateway.execute_structured(
        task=_task(
            snapshot=snapshot,
            family=selected_family,
            role="primary",
            analysis_projection=analysis_projection,
        ),
        route=primary_route,
        backend=primary_backend,
        output_model=DriverFamilyProposal,
        force_refresh=force_refresh,
        transport_timeout_seconds=transport_timeout_seconds,
    )
    if primary_envelope.validated_payload is None:
        return DriverFamilyWorkflowResult(
            status="blocked",
            family=selected_family,
            primary_envelope=primary_envelope,
            critic_envelope=None,
            revision_envelope=None,
            revision_critic_envelope=None,
            proposal=None,
            critique=None,
            queue_item=None,
            blocker_reason="primary_judgment_failed",
        )
    proposal = DriverFamilyProposal.model_validate(
        primary_envelope.validated_payload
    )
    if proposal.family != selected_family:
        return DriverFamilyWorkflowResult(
            status="blocked",
            family=selected_family,
            primary_envelope=primary_envelope,
            critic_envelope=None,
            revision_envelope=None,
            revision_critic_envelope=None,
            proposal=proposal,
            critique=None,
            queue_item=None,
            blocker_reason="primary_family_mismatch",
        )
    if _proposal_unknown_anchors(proposal, snapshot):
        return DriverFamilyWorkflowResult(
            status="blocked",
            family=selected_family,
            primary_envelope=primary_envelope,
            critic_envelope=None,
            revision_envelope=None,
            revision_critic_envelope=None,
            proposal=proposal,
            critique=None,
            queue_item=None,
            blocker_reason="primary_unknown_evidence_anchors",
        )

    critic_envelope = resolved_gateway.execute_structured(
        task=_task(
            snapshot=snapshot,
            family=selected_family,
            role="critic",
            analysis_projection=analysis_projection,
            reviewed_proposal=proposal,
        ),
        route=critic_route,
        backend=critic_backend,
        output_model=DriverFamilyCritique,
        force_refresh=force_refresh,
        transport_timeout_seconds=transport_timeout_seconds,
    )
    if critic_envelope.validated_payload is None:
        return DriverFamilyWorkflowResult(
            status="blocked",
            family=selected_family,
            primary_envelope=primary_envelope,
            critic_envelope=critic_envelope,
            revision_envelope=None,
            revision_critic_envelope=None,
            proposal=proposal,
            critique=None,
            queue_item=None,
            blocker_reason="critic_judgment_failed",
        )
    critique = DriverFamilyCritique.model_validate(
        critic_envelope.validated_payload
    )
    if critique.family != selected_family:
        return DriverFamilyWorkflowResult(
            status="blocked",
            family=selected_family,
            primary_envelope=primary_envelope,
            critic_envelope=critic_envelope,
            revision_envelope=None,
            revision_critic_envelope=None,
            proposal=proposal,
            critique=critique,
            queue_item=None,
            blocker_reason="critic_family_mismatch",
        )
    if _critique_unknown_anchors(critique, snapshot):
        return DriverFamilyWorkflowResult(
            status="blocked",
            family=selected_family,
            primary_envelope=primary_envelope,
            critic_envelope=critic_envelope,
            revision_envelope=None,
            revision_critic_envelope=None,
            proposal=proposal,
            critique=critique,
            queue_item=None,
            blocker_reason="critic_unknown_evidence_anchors",
        )
    if critique.verdict == "block":
        return DriverFamilyWorkflowResult(
            status="blocked",
            family=selected_family,
            primary_envelope=primary_envelope,
            critic_envelope=critic_envelope,
            revision_envelope=None,
            revision_critic_envelope=None,
            proposal=proposal,
            critique=critique,
            queue_item=None,
            blocker_reason="critic_blocked",
        )

    revision_envelope = None
    revision_critic_envelope = None
    queue_primary_run_id = primary_envelope.run_id
    queue_critic_run_id = critic_envelope.run_id
    if critique.verdict == "revise":
        revision_envelope = resolved_gateway.execute_structured(
            task=_task(
                snapshot=snapshot,
                family=selected_family,
                role="revision",
                analysis_projection=analysis_projection,
                reviewed_proposal=proposal,
                critique=critique,
            ),
            route=primary_route,
            backend=primary_backend,
            output_model=DriverFamilyProposal,
            force_refresh=force_refresh,
            transport_timeout_seconds=transport_timeout_seconds,
        )
        if revision_envelope.validated_payload is None:
            return DriverFamilyWorkflowResult(
                status="blocked",
                family=selected_family,
                primary_envelope=primary_envelope,
                critic_envelope=critic_envelope,
                revision_envelope=revision_envelope,
                revision_critic_envelope=None,
                proposal=proposal,
                critique=critique,
                queue_item=None,
                blocker_reason="primary_revision_failed",
            )
        revised_proposal = DriverFamilyProposal.model_validate(
            revision_envelope.validated_payload
        )
        if revised_proposal.family != selected_family:
            return DriverFamilyWorkflowResult(
                status="blocked",
                family=selected_family,
                primary_envelope=primary_envelope,
                critic_envelope=critic_envelope,
                revision_envelope=revision_envelope,
                revision_critic_envelope=None,
                proposal=revised_proposal,
                critique=critique,
                queue_item=None,
                blocker_reason="primary_revision_family_mismatch",
            )
        if _proposal_unknown_anchors(revised_proposal, snapshot):
            return DriverFamilyWorkflowResult(
                status="blocked",
                family=selected_family,
                primary_envelope=primary_envelope,
                critic_envelope=critic_envelope,
                revision_envelope=revision_envelope,
                revision_critic_envelope=None,
                proposal=revised_proposal,
                critique=critique,
                queue_item=None,
                blocker_reason="primary_revision_unknown_evidence_anchors",
            )
        proposal = revised_proposal
        queue_primary_run_id = revision_envelope.run_id
        revision_critic_envelope = resolved_gateway.execute_structured(
            task=_task(
                snapshot=snapshot,
                family=selected_family,
                role="critic",
                analysis_projection=analysis_projection,
                reviewed_proposal=proposal,
                critique=critique,
            ),
            route=critic_route,
            backend=critic_backend,
            output_model=DriverFamilyCritique,
            force_refresh=force_refresh,
            transport_timeout_seconds=transport_timeout_seconds,
        )
        if revision_critic_envelope.validated_payload is None:
            return DriverFamilyWorkflowResult(
                status="blocked",
                family=selected_family,
                primary_envelope=primary_envelope,
                critic_envelope=critic_envelope,
                revision_envelope=revision_envelope,
                revision_critic_envelope=revision_critic_envelope,
                proposal=proposal,
                critique=critique,
                queue_item=None,
                blocker_reason="revision_critic_judgment_failed",
            )
        final_critique = DriverFamilyCritique.model_validate(
            revision_critic_envelope.validated_payload
        )
        if final_critique.family != selected_family:
            return DriverFamilyWorkflowResult(
                status="blocked",
                family=selected_family,
                primary_envelope=primary_envelope,
                critic_envelope=critic_envelope,
                revision_envelope=revision_envelope,
                revision_critic_envelope=revision_critic_envelope,
                proposal=proposal,
                critique=final_critique,
                queue_item=None,
                blocker_reason="revision_critic_family_mismatch",
            )
        if _critique_unknown_anchors(final_critique, snapshot):
            return DriverFamilyWorkflowResult(
                status="blocked",
                family=selected_family,
                primary_envelope=primary_envelope,
                critic_envelope=critic_envelope,
                revision_envelope=revision_envelope,
                revision_critic_envelope=revision_critic_envelope,
                proposal=proposal,
                critique=final_critique,
                queue_item=None,
                blocker_reason="revision_critic_unknown_evidence_anchors",
            )
        if final_critique.verdict != "accept":
            return DriverFamilyWorkflowResult(
                status="blocked",
                family=selected_family,
                primary_envelope=primary_envelope,
                critic_envelope=critic_envelope,
                revision_envelope=revision_envelope,
                revision_critic_envelope=revision_critic_envelope,
                proposal=proposal,
                critique=final_critique,
                queue_item=None,
                blocker_reason="revision_not_accepted",
            )
        critique = final_critique
        queue_critic_run_id = revision_critic_envelope.run_id

    queue_item = build_driver_family_queue_item(
        ticker=snapshot.ticker,
        proposal=proposal,
        critique=critique,
        analysis_snapshot_hash=snapshot.snapshot_hash,
        primary_run_id=queue_primary_run_id,
        critic_run_id=queue_critic_run_id,
    )
    if revision_envelope is not None:
        queue_item = queue_item.model_copy(
            update={
                "metadata": {
                    **queue_item.metadata,
                    "initial_primary_run_id": primary_envelope.run_id,
                    "initial_critic_run_id": critic_envelope.run_id,
                    "revision_run_id": revision_envelope.run_id,
                    "revision_critic_run_id": queue_critic_run_id,
                }
            }
        )
    return DriverFamilyWorkflowResult(
        status="queued",
        family=selected_family,
        primary_envelope=primary_envelope,
        critic_envelope=critic_envelope,
        revision_envelope=revision_envelope,
        revision_critic_envelope=revision_critic_envelope,
        proposal=proposal,
        critique=critique,
        queue_item=queue_item,
    )
