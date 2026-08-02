"""Provider-neutral orchestration for one ticker's valuation judgment."""

from __future__ import annotations

from dataclasses import dataclass
import math
import sqlite3
from typing import Literal, Mapping

from db.loader import (
    insert_pm_decision_queue_item,
    list_pm_decision_queue_items,
)
from src.contracts.analysis_snapshot import AnalysisSnapshot
from src.contracts.assumption_registry import DriverFamily
from src.contracts.judgment_runs import (
    AgentRunEnvelope,
    ProviderRoute,
    canonical_semantic_hash,
)
from src.contracts.model_change_requests import build_model_change_request
from src.stage_03_judgment.judgment_gateway import (
    JudgmentGateway,
    StructuredJudgmentBackend,
)
from src.stage_04_pipeline.driver_family_workflow import (
    DriverFamilyWorkflowResult,
    run_driver_family_workflow,
)
from src.stage_04_pipeline.valuation_run_store import (
    load_cached_successful_envelope,
    persist_agent_run_envelope,
    persist_analysis_snapshot,
    persist_model_change_request,
    release_judgment_invocation,
    reserve_judgment_invocation,
)


@dataclass(frozen=True, slots=True)
class DriverFamilyExecutionBinding:
    """Explicit provider routes and adapters for one driver family."""

    primary_route: ProviderRoute
    primary_backend: StructuredJudgmentBackend
    critic_route: ProviderRoute
    critic_backend: StructuredJudgmentBackend
    max_projection_chars: int | None = None


@dataclass(frozen=True, slots=True)
class ValuationJudgmentPipelineResult:
    """Terminal judgment state for every required driver family."""

    status: Literal["queued", "partial", "blocked"]
    snapshot_hash: str
    family_results: dict[DriverFamily, DriverFamilyWorkflowResult]
    queue_item_ids: dict[DriverFamily, int]
    blocker_reasons: dict[DriverFamily, str]
    model_change_request_ids: dict[DriverFamily, tuple[str, ...]]


def _validate_bindings(
    bindings: Mapping[DriverFamily, DriverFamilyExecutionBinding],
) -> None:
    supplied = set(bindings)
    required = set(DriverFamily)
    if supplied == required:
        return
    missing = sorted(family.value for family in required - supplied)
    unexpected = sorted(str(family) for family in supplied - required)
    raise ValueError(
        "driver family bindings must be complete; "
        f"missing={missing}, unexpected={unexpected}"
    )


def _existing_queue_item_ids_by_pack(
    conn: sqlite3.Connection,
    *,
    ticker: str,
) -> dict[str, int]:
    existing: dict[str, int] = {}
    for row in list_pm_decision_queue_items(conn, ticker=ticker):
        proposal_pack = row.get("proposal_pack") or {}
        pack_id = str(proposal_pack.get("pack_id") or "").strip()
        if pack_id:
            existing[pack_id] = int(row["item_id"])
    return existing


def _judgment_snapshot_blockers(
    snapshot: AnalysisSnapshot,
) -> tuple[str, ...]:
    blockers: list[str] = []
    statements = snapshot.statements
    annual_count = int(
        statements.get(
            "annual_period_count",
            statements.get("annual_periods", 0),
        )
        or 0
    )
    if annual_count < 3:
        blockers.append("snapshot.history_insufficient")
    if str(statements.get("ltm_status") or "") not in {
        "compatible",
        "constructed",
        "source_provided",
    }:
        blockers.append("snapshot.ltm_not_ready")

    statement_reconciliation = snapshot.statement_reconciliation
    statement_status = str(
        statement_reconciliation.get("status")
        or (statement_reconciliation.get("statements") or {}).get("status")
        or ""
    )
    if statement_status not in {"reconciled", "decision_grade"}:
        blockers.append("snapshot.statement_reconciliation_not_ready")

    claim = snapshot.claim_ledger
    claim_reconciliation = claim.get("reconciliation") or {}
    claim_ready = (
        str(claim.get("status") or "") == "reconciled"
        or bool(
            claim_reconciliation.get(
                "is_decision_grade",
                claim_reconciliation.get("is_reconciled", False),
            )
        )
    )
    if not claim_ready:
        blockers.append("snapshot.claim_ledger_not_ready")

    operating = (
        snapshot.market_inputs.get("operating_reconciliation") or {}
    )
    if str(operating.get("status") or "") != "reconciled":
        blockers.append("snapshot.operating_reconciliation_not_ready")
    if int(operating.get("unresolved_clamp_count") or 0):
        blockers.append("snapshot.unresolved_clamps")

    for context_name in ("business", "industry"):
        context = snapshot.upstream_context.get(context_name)
        if not isinstance(context, dict) or not context:
            blockers.append(f"snapshot.{context_name}_context_missing")
    if not snapshot.evidence:
        blockers.append("snapshot.evidence_missing")
    return tuple(blockers)


def _persist_queue_item(
    conn: sqlite3.Connection,
    *,
    result: DriverFamilyWorkflowResult,
    existing_ids: dict[str, int],
) -> int:
    if result.queue_item is None or result.queue_item.proposal_pack is None:
        raise ValueError("queued family result is missing its atomic proposal pack")
    pack_id = result.queue_item.proposal_pack.pack_id
    existing_id = existing_ids.get(pack_id)
    if existing_id is not None:
        return existing_id
    row = result.queue_item.model_dump(mode="json")
    row["valuation_impact_bucket"] = "high"
    item_id = insert_pm_decision_queue_item(conn, row)
    existing_ids[pack_id] = item_id
    return item_id


def run_valuation_judgment_pipeline(
    *,
    snapshot: AnalysisSnapshot,
    bindings: Mapping[DriverFamily, DriverFamilyExecutionBinding],
    conn: sqlite3.Connection,
    force_refresh: bool = False,
    transport_timeout_seconds: float = 120.0,
) -> ValuationJudgmentPipelineResult:
    """Run every required family against one frozen snapshot.

    The provider adapters are injected explicitly. The deterministic pipeline
    persists every terminal run envelope but does not apply any proposed value
    to the valuation model; successful families stop at the PM decision queue.
    """

    if (
        not math.isfinite(transport_timeout_seconds)
        or transport_timeout_seconds <= 0
    ):
        raise ValueError(
            "transport_timeout_seconds must be finite and positive"
        )
    _validate_bindings(bindings)
    persist_analysis_snapshot(conn, snapshot)
    snapshot_blockers = _judgment_snapshot_blockers(snapshot)
    if snapshot_blockers:
        reason = ",".join(snapshot_blockers)
        return ValuationJudgmentPipelineResult(
            status="blocked",
            snapshot_hash=snapshot.snapshot_hash,
            family_results={},
            queue_item_ids={},
            blocker_reasons={
                family: reason for family in DriverFamily
            },
            model_change_request_ids={},
        )

    def _persist_envelope(envelope: AgentRunEnvelope) -> None:
        persist_agent_run_envelope(conn, envelope)

    def _release_invocation(
        invocation_hash: str,
        owner_run_id: str,
    ) -> None:
        release_judgment_invocation(
            conn,
            invocation_hash=invocation_hash,
            owner_run_id=owner_run_id,
        )

    gateway = JudgmentGateway(
        envelope_sink=_persist_envelope,
        successful_envelope_lookup=lambda idempotency_key: (
            load_cached_successful_envelope(conn, idempotency_key)
        ),
        invocation_reservation=lambda invocation_hash, owner_run_id: (
            reserve_judgment_invocation(
                conn,
                invocation_hash=invocation_hash,
                owner_run_id=owner_run_id,
            )
        ),
        invocation_release=_release_invocation,
    )
    existing_ids = _existing_queue_item_ids_by_pack(
        conn,
        ticker=snapshot.ticker,
    )

    family_results: dict[DriverFamily, DriverFamilyWorkflowResult] = {}
    queue_item_ids: dict[DriverFamily, int] = {}
    blocker_reasons: dict[DriverFamily, str] = {}
    model_change_request_ids: dict[DriverFamily, tuple[str, ...]] = {}
    for family in DriverFamily:
        binding = bindings[family]
        result = run_driver_family_workflow(
            snapshot=snapshot,
            family=family,
            primary_route=binding.primary_route,
            primary_backend=binding.primary_backend,
            critic_route=binding.critic_route,
            critic_backend=binding.critic_backend,
            gateway=gateway,
            force_refresh=force_refresh,
            transport_timeout_seconds=transport_timeout_seconds,
            **(
                {"max_projection_chars": binding.max_projection_chars}
                if binding.max_projection_chars is not None
                else {}
            ),
        )
        family_results[family] = result
        challenges = (
            result.critique.methodology_challenges
            if result.critique is not None
            else ()
        )
        request_ids: list[str] = []
        for challenge in challenges:
            evidence_fingerprints = tuple(
                canonical_semantic_hash(snapshot.evidence[anchor])
                for anchor in challenge.evidence_anchor_ids
            )
            request = build_model_change_request(
                ticker=snapshot.ticker,
                analysis_snapshot_hash=snapshot.snapshot_hash,
                category=challenge.category,
                current_model=(
                    snapshot.component_versions.get("valuation_model")
                    or "industrial_fcff_v1"
                ),
                required_capability=challenge.required_capability,
                rationale=challenge.rationale,
                evidence_anchor_ids=challenge.evidence_anchor_ids,
                evidence_fingerprints=evidence_fingerprints,
                created_at=snapshot.captured_at,
            )
            persist_model_change_request(
                conn,
                request,
                actor=f"critic:{family.value}",
            )
            request_ids.append(request.request_id)
        if request_ids:
            model_change_request_ids[family] = tuple(request_ids)
        if result.status == "queued":
            queue_item_ids[family] = _persist_queue_item(
                conn,
                result=result,
                existing_ids=existing_ids,
            )
        else:
            blocker_reasons[family] = (
                result.blocker_reason or "driver_family_blocked"
            )

    queued_count = len(queue_item_ids)
    status: Literal["queued", "partial", "blocked"]
    if queued_count == len(DriverFamily):
        status = "queued"
    elif queued_count:
        status = "partial"
    else:
        status = "blocked"
    return ValuationJudgmentPipelineResult(
        status=status,
        snapshot_hash=snapshot.snapshot_hash,
        family_results=family_results,
        queue_item_ids=queue_item_ids,
        blocker_reasons=blocker_reasons,
        model_change_request_ids=model_change_request_ids,
    )


__all__ = [
    "DriverFamilyExecutionBinding",
    "ValuationJudgmentPipelineResult",
    "run_valuation_judgment_pipeline",
]
