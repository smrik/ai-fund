"""Production seam for one reconciled, provider-neutral valuation workup."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
import math
from typing import Any

from src.contracts.assumption_registry import DriverFamily
from src.contracts.judgment_runs import canonical_semantic_hash
from src.contracts.model_change_requests import (
    ValuationModelChangeRequest,
    build_model_change_request,
)
from src.contracts.ticker_runs import (
    EligibilityStatus,
    ReplayInputFingerprints,
    RetryPolicy,
    SourceFingerprint,
    TerminalStatus,
    TickerIdentity,
    TickerRunContext,
    TickerTerminalRecord,
)
from src.contracts.valuation_readiness import (
    LTMStatus,
    ReconciliationGateStatus,
    ValuationReadinessEvidence,
    assess_judgment_driver_provenance,
)
from src.stage_02_valuation.approved_case_replay import (
    ApprovedValuationReplayResult,
    compile_approved_valuation_case,
    replay_approved_valuation_case,
)
from src.stage_02_valuation.input_assembler import build_valuation_inputs
from src.stage_02_valuation.valuation_types import ForecastDrivers
from src.stage_04_pipeline.analysis_snapshot_builder import (
    build_valuation_analysis_snapshot,
)
from src.stage_04_pipeline.operating_reconciliation_service import (
    TickerOperatingReconciliation,
    adopt_reconciled_valuation_inputs,
    reconcile_ticker_operating_model,
)
from src.stage_04_pipeline.statement_reconciliation_service import (
    TickerStatementReconciliationRun,
    reconcile_ticker_statements,
)
from src.stage_04_pipeline.ticker_batch import (
    TickerBatchManifest,
    run_ticker_batch,
)
from src.stage_04_pipeline.valuation_judgment_pipeline import (
    DriverFamilyExecutionBinding,
    ValuationJudgmentPipelineResult,
    run_valuation_judgment_pipeline,
)
from src.stage_04_pipeline.valuation_run_store import (
    load_approved_family_bundle,
    load_approved_valuation_replay,
    persist_approved_valuation_replay,
)


VALUATION_EXECUTION_CONTRACT_VERSION = "1.0.0"
DCF_ENGINE_FINGERPRINT = canonical_semantic_hash(
    {"engine": "run_dcf_professional", "version": "1.0.0"}
)
COMPS_ENGINE_FINGERPRINT = canonical_semantic_hash(
    {"engine": "run_comps_model", "version": "1.0.0"}
)
BRIDGE_ENGINE_FINGERPRINT = canonical_semantic_hash(
    {"engine": "reconciled_ev_bridge", "version": "1.0.0"}
)
VALUATION_ENGINE_FINGERPRINT = canonical_semantic_hash(
    {
        "dcf": DCF_ENGINE_FINGERPRINT,
        "comps": COMPS_ENGINE_FINGERPRINT,
        "bridge": BRIDGE_ENGINE_FINGERPRINT,
    }
)
JUDGMENT_CONTRACT_FINGERPRINT = canonical_semantic_hash(
    {
        "pipeline": "driver_family_primary_critic_v1",
        "families": [family.value for family in DriverFamily],
    }
)


@dataclass(frozen=True, slots=True)
class PreparedTickerRun:
    """Frozen work handed to the bounded ticker scheduler."""

    context: TickerRunContext
    snapshot: Any | None
    blocker_reason_codes: tuple[str, ...] = ()
    approved_replay: ApprovedValuationReplayResult | None = None

    def __post_init__(self) -> None:
        if self.snapshot is not None:
            snapshot_hash = str(
                getattr(self.snapshot, "snapshot_hash", "")
            ).strip()
            if (
                not snapshot_hash
                or snapshot_hash
                != self.context.replay_inputs.analysis_snapshot_hash
            ):
                raise ValueError(
                    "prepared snapshot must match ticker context"
                )
        if self.approved_replay is not None:
            if (
                self.context.readiness.trust_status.value
                != "decision_grade"
            ):
                raise ValueError(
                    "approved replay requires decision-grade context"
                )
            if self.snapshot is None:
                raise ValueError("approved replay requires its frozen snapshot")
            replay_key = str(
                getattr(self.approved_replay, "replay_key", "")
            ).strip()
            if (
                not replay_key
                or replay_key
                != self.context.replay_inputs.approved_case_replay_fingerprint
            ):
                raise ValueError(
                    "approved replay key must match ticker context"
                )


def _gate(value: str, *, passed: set[str], failed: set[str]) -> ReconciliationGateStatus:
    normalized = str(value or "").strip().lower()
    if normalized in passed:
        return ReconciliationGateStatus.reconciled
    if normalized in failed:
        return ReconciliationGateStatus.failed
    return ReconciliationGateStatus.pending


def _ltm_status(value: str) -> LTMStatus:
    normalized = str(value or "").strip().lower()
    if normalized in {"compatible", "constructed", "source_provided"}:
        return LTMStatus.compatible
    if normalized == "incompatible":
        return LTMStatus.incompatible
    return LTMStatus.unavailable


def _treatment_hashes(
    approved_treatments: Sequence[Mapping[str, Any]],
) -> tuple[str, ...]:
    return tuple(
        sorted(
            canonical_semantic_hash(dict(treatment))
            for treatment in approved_treatments
        )
    )


def build_valuation_readiness(
    *,
    snapshot: Any,
    statement_run: TickerStatementReconciliationRun,
    operating: TickerOperatingReconciliation,
    approved_family_hashes: Mapping[DriverFamily, str] | None = None,
    prompt_contract_fingerprint: str = JUDGMENT_CONTRACT_FINGERPRINT,
) -> ValuationReadinessEvidence:
    """Build the one trust contract shared by execution and replay."""

    source_reconciliation = statement_run.readiness.source_reconciliation
    claim_reconciliation = (
        snapshot.claim_ledger.get("reconciliation") or {}
    )
    treatment_hashes = _treatment_hashes(
        tuple(snapshot.approved_treatments)
    )
    market_inputs = snapshot.market_inputs if isinstance(snapshot.market_inputs, Mapping) else {}
    source_lineage = market_inputs.get("source_lineage")
    base_drivers = market_inputs.get("base_drivers")
    judgment_driver_verdicts = assess_judgment_driver_provenance(
        source_lineage if isinstance(source_lineage, Mapping) else {},
        approved_family_hashes=approved_family_hashes,
        used_fields=(
            base_drivers.keys()
            if isinstance(base_drivers, Mapping)
            else None
        ),
    )
    return ValuationReadinessEvidence(
        statement_reconciliation=_gate(
            statement_run.readiness.status,
            passed={"decision_grade", "reconciled"},
            failed={"blocked", "failed"},
        ),
        source_reconciliation=_gate(
            source_reconciliation.status,
            passed={"pass", "reconciled"},
            failed={"not_comparable", "failed"},
        ),
        claim_ledger_reconciliation=(
            ReconciliationGateStatus.reconciled
            if bool(
                claim_reconciliation.get(
                    "is_decision_grade",
                    claim_reconciliation.get("is_reconciled", False),
                )
            )
            else ReconciliationGateStatus.failed
        ),
        operating_reconciliation=_gate(
            operating.status,
            passed={"reconciled"},
            failed={"failed"},
        ),
        annual_period_count=int(
            statement_run.readiness.annual_period_count
        ),
        ltm_status=_ltm_status(statement_run.readiness.ltm_status),
        approved_family_hashes=dict(approved_family_hashes or {}),
        statement_reconciliation_hash=canonical_semantic_hash(
            snapshot.statement_reconciliation
        ),
        source_reconciliation_hash=canonical_semantic_hash(
            snapshot.source_fingerprints
        ),
        claim_ledger_hash=(
            str(snapshot.claim_ledger.get("fingerprint") or "").strip()
            or canonical_semantic_hash(snapshot.claim_ledger)
        ),
        operating_reconciliation_hash=operating.fingerprint,
        peer_set_fingerprint=canonical_semantic_hash(
            snapshot.comps_inputs
        ),
        treatment_set_fingerprint=canonical_semantic_hash(
            list(treatment_hashes)
        ),
        prompt_contract_fingerprint=prompt_contract_fingerprint,
        dcf_engine_fingerprint=DCF_ENGINE_FINGERPRINT,
        comps_engine_fingerprint=COMPS_ENGINE_FINGERPRINT,
        bridge_engine_fingerprint=BRIDGE_ENGINE_FINGERPRINT,
        unresolved_clamp_count=operating.result.unresolved_clamp_count,
        pending_material_disagreement_count=int(
            snapshot.statement_reconciliation.get(
                "pending_material_disagreement_count",
                0,
            )
            or 0
        ),
        judgment_driver_verdicts=judgment_driver_verdicts,
    )


def _replay_inputs(
    *,
    analysis_snapshot_hash: str,
    readiness: ValuationReadinessEvidence,
    approved_replay_fingerprint: str,
) -> ReplayInputFingerprints:
    return ReplayInputFingerprints(
        analysis_snapshot_hash=analysis_snapshot_hash,
        approved_case_replay_fingerprint=approved_replay_fingerprint,
        peer_universe_fingerprint=(
            readiness.peer_set_fingerprint or "missing:peer-set"
        ),
        treatment_register_fingerprint=(
            readiness.treatment_set_fingerprint
            or "missing:treatment-set"
        ),
        judgment_contract_fingerprint=(
            readiness.prompt_contract_fingerprint
            or JUDGMENT_CONTRACT_FINGERPRINT
        ),
        valuation_engine_fingerprint=VALUATION_ENGINE_FINGERPRINT,
    )


def _blocked_prepared_run(
    *,
    ticker: str,
    analysis_as_of: date,
    reason_codes: Sequence[str],
    statement_run: TickerStatementReconciliationRun | None = None,
) -> PreparedTickerRun:
    normalized_ticker = str(ticker).strip().upper()
    blocker_payload = {
        "contract_version": VALUATION_EXECUTION_CONTRACT_VERSION,
        "ticker": normalized_ticker,
        "analysis_as_of": analysis_as_of.isoformat(),
        "reason_codes": tuple(dict.fromkeys(reason_codes)),
        "statement_run_hash": (
            statement_run.run_hash if statement_run is not None else None
        ),
    }
    blocker_hash = canonical_semantic_hash(blocker_payload)
    readiness = ValuationReadinessEvidence(
        statement_reconciliation=ReconciliationGateStatus.failed,
        source_reconciliation=ReconciliationGateStatus.failed,
        claim_ledger_reconciliation=ReconciliationGateStatus.failed,
        operating_reconciliation=ReconciliationGateStatus.failed,
        annual_period_count=(
            int(statement_run.readiness.annual_period_count)
            if statement_run is not None
            else 0
        ),
        ltm_status=(
            _ltm_status(statement_run.readiness.ltm_status)
            if statement_run is not None
            else LTMStatus.unavailable
        ),
        approved_family_hashes={},
        statement_reconciliation_hash=(
            statement_run.run_hash
            if statement_run is not None
            else blocker_hash
        ),
        source_reconciliation_hash=blocker_hash,
        claim_ledger_hash=blocker_hash,
        operating_reconciliation_hash=blocker_hash,
        peer_set_fingerprint=blocker_hash,
        treatment_set_fingerprint=blocker_hash,
        prompt_contract_fingerprint=JUDGMENT_CONTRACT_FINGERPRINT,
        dcf_engine_fingerprint=DCF_ENGINE_FINGERPRINT,
        comps_engine_fingerprint=COMPS_ENGINE_FINGERPRINT,
        bridge_engine_fingerprint=BRIDGE_ENGINE_FINGERPRINT,
    )
    source_hash = (
        statement_run.run_hash
        if statement_run is not None
        else blocker_hash
    )
    context = TickerRunContext(
        identity=TickerIdentity(ticker=normalized_ticker),
        analysis_as_of=analysis_as_of,
        eligibility=EligibilityStatus.supported_v1,
        valuation_model="industrial_fcff_dcf_comps_v1",
        replay_inputs=_replay_inputs(
            analysis_snapshot_hash=blocker_hash,
            readiness=readiness,
            approved_replay_fingerprint=blocker_hash,
        ),
        readiness=readiness,
        source_fingerprints=(
            SourceFingerprint(
                source_id=(
                    f"statement-reconciliation:{normalized_ticker}"
                ),
                fingerprint=source_hash,
            ),
        ),
    )
    return PreparedTickerRun(
        context=context,
        snapshot=None,
        blocker_reason_codes=tuple(
            dict.fromkeys(str(reason) for reason in reason_codes)
        ),
    )


def _snapshot_source_fingerprints(snapshot: Any) -> tuple[SourceFingerprint, ...]:
    return tuple(
        SourceFingerprint(
            source_id=str(source_id),
            fingerprint=str(fingerprint),
        )
        for source_id, fingerprint in sorted(
            dict(snapshot.source_fingerprints).items()
        )
    )


def _unsupported_model_request(
    *,
    snapshot: Any,
    captured_at: str,
) -> ValuationModelChangeRequest:
    if snapshot.evidence:
        anchor_id = sorted(snapshot.evidence)[0]
        anchor_fingerprint = canonical_semantic_hash(
            snapshot.evidence[anchor_id]
        )
    else:
        anchor_id = f"snapshot:{snapshot.snapshot_hash}"
        anchor_fingerprint = snapshot.snapshot_hash
    return build_model_change_request(
        ticker=snapshot.ticker,
        analysis_snapshot_hash=snapshot.snapshot_hash,
        category="applicability",
        current_model="industrial_fcff_dcf_comps_v1",
        required_capability="issuer-appropriate valuation methodology",
        rationale=(
            "The current industrial FCFF DCF/comps model is not structurally "
            "appropriate for this issuer."
        ),
        evidence_anchor_ids=(anchor_id,),
        evidence_fingerprints=(anchor_fingerprint,),
        created_at=captured_at,
    )


def prepare_ticker_run(
    conn: Any,
    ticker: str,
    *,
    analysis_as_of: date,
    captured_at: str,
    evidence: Mapping[str, Any],
    upstream_context: Mapping[str, Any],
    comps_inputs: Mapping[str, Any],
    valuation_policy: Mapping[str, Any],
    approved_treatments: Sequence[Mapping[str, Any]] | None = None,
    statement_reconciler: Callable[..., TickerStatementReconciliationRun] = (
        reconcile_ticker_statements
    ),
    input_builder: Callable[..., Any] = build_valuation_inputs,
    operating_reconciler: Callable[..., TickerOperatingReconciliation] = (
        reconcile_ticker_operating_model
    ),
    snapshot_builder: Callable[..., Any] = build_valuation_analysis_snapshot,
) -> PreparedTickerRun:
    """Prepare one ticker without allowing pre-snapshot failures to disappear."""

    normalized_ticker = str(ticker).strip().upper()
    if not normalized_ticker:
        raise ValueError("ticker is required")
    try:
        statement_run = statement_reconciler(
            conn,
            normalized_ticker,
            evidence_cutoff=analysis_as_of.isoformat(),
        )
    except Exception as exc:
        return _blocked_prepared_run(
            ticker=normalized_ticker,
            analysis_as_of=analysis_as_of,
            reason_codes=(
                "preparation.statement_reconciliation_failed",
                f"preparation.exception.{type(exc).__name__}",
            ),
        )
    statement_readiness = statement_run.readiness
    raw_statement_status = getattr(statement_readiness, "status", "")
    statement_status = str(
        getattr(raw_statement_status, "value", raw_statement_status)
    ).strip()
    statement_is_decision_grade = bool(
        getattr(
            statement_readiness,
            "decision_grade",
            statement_status == "decision_grade",
        )
    )
    if not statement_is_decision_grade:
        reported_reasons = tuple(
            str(getattr(reason, "value", reason)).strip()
            for reason in getattr(statement_readiness, "reason_codes", ())
            if str(getattr(reason, "value", reason)).strip()
        )
        return _blocked_prepared_run(
            ticker=normalized_ticker,
            analysis_as_of=analysis_as_of,
            statement_run=statement_run,
            reason_codes=(
                "preparation.statement_reconciliation_incomplete",
                *(
                    reported_reasons
                    or (
                        "preparation.statement_reconciliation_"
                        f"{statement_status or 'unknown'}",
                    )
                ),
            ),
        )

    try:
        valuation_inputs = input_builder(
            normalized_ticker,
            as_of_date=analysis_as_of.isoformat(),
            apply_overrides=False,
            apply_story_overlay=False,
            allow_public_comps_fallback=False,
        )
    except Exception as exc:
        return _blocked_prepared_run(
            ticker=normalized_ticker,
            analysis_as_of=analysis_as_of,
            statement_run=statement_run,
            reason_codes=(
                "preparation.valuation_inputs_failed",
                f"preparation.exception.{type(exc).__name__}",
            ),
        )
    if valuation_inputs is None:
        return _blocked_prepared_run(
            ticker=normalized_ticker,
            analysis_as_of=analysis_as_of,
            statement_run=statement_run,
            reason_codes=("preparation.valuation_inputs_unavailable",),
        )

    try:
        reconciled_inputs = adopt_reconciled_valuation_inputs(
            conn,
            valuation_inputs=valuation_inputs,
            statement_reconciliation_run=statement_run,
            operating_reconciler=operating_reconciler,
        )
        operating = reconciled_inputs.operating_reconciliation
    except Exception as exc:
        return _blocked_prepared_run(
            ticker=normalized_ticker,
            analysis_as_of=analysis_as_of,
            statement_run=statement_run,
            reason_codes=(
                "preparation.operating_reconciliation_failed",
                f"preparation.exception.{type(exc).__name__}",
            ),
        )

    if approved_treatments is None:
        from db.loader import load_active_treatment_decisions

        try:
            approved_treatments = load_active_treatment_decisions(
                conn,
                normalized_ticker,
            )
        except Exception as exc:
            return _blocked_prepared_run(
                ticker=normalized_ticker,
                analysis_as_of=analysis_as_of,
                statement_run=statement_run,
                reason_codes=(
                    "preparation.approved_treatments_failed",
                    f"preparation.exception.{type(exc).__name__}",
                ),
            )
    try:
        snapshot = snapshot_builder(
            conn=conn,
            valuation_inputs=valuation_inputs,
            statement_reconciliation_run=statement_run,
            operating_reconciliation=operating.to_dict(),
            comps_inputs=dict(comps_inputs),
            valuation_policy=dict(valuation_policy),
            evidence=dict(evidence),
            upstream_context=dict(upstream_context),
            captured_at=captured_at,
            approved_treatments=tuple(approved_treatments),
            component_versions={
                "valuation_execution": VALUATION_EXECUTION_CONTRACT_VERSION,
                "valuation_model": "industrial_fcff_dcf_comps_v1",
                "dcf_engine": DCF_ENGINE_FINGERPRINT,
                "comps_engine": COMPS_ENGINE_FINGERPRINT,
                "bridge_engine": BRIDGE_ENGINE_FINGERPRINT,
                "dcf_engine_fingerprint": DCF_ENGINE_FINGERPRINT,
                "comps_engine_fingerprint": COMPS_ENGINE_FINGERPRINT,
                "bridge_engine_fingerprint": BRIDGE_ENGINE_FINGERPRINT,
            },
        )
    except Exception as exc:
        return _blocked_prepared_run(
            ticker=normalized_ticker,
            analysis_as_of=analysis_as_of,
            statement_run=statement_run,
            reason_codes=(
                "preparation.analysis_snapshot_failed",
                f"preparation.exception.{type(exc).__name__}",
            ),
        )

    blockers: list[str] = []
    if not comps_inputs:
        blockers.append("preparation.comps_inputs_missing")
    if not evidence:
        blockers.append("preparation.evidence_missing")
    for context_name in ("business", "industry"):
        context_payload = upstream_context.get(context_name)
        if not isinstance(context_payload, Mapping) or not context_payload:
            blockers.append(f"preparation.{context_name}_context_missing")

    applicability = str(
        valuation_inputs.model_applicability_status
    ).strip()
    model_change_request = None
    eligibility = EligibilityStatus.supported_v1
    eligibility_reason = None
    if applicability != "dcf_applicable":
        eligibility = EligibilityStatus.unsupported_model
        eligibility_reason = "eligibility.unsupported_model"
        model_change_request = _unsupported_model_request(
            snapshot=snapshot,
            captured_at=captured_at,
        )
        from src.stage_04_pipeline.valuation_run_store import (
            persist_model_change_request,
        )

        try:
            persist_model_change_request(
                conn,
                model_change_request,
                actor="ticker_valuation_execution",
            )
        except Exception as exc:
            blockers.extend(
                (
                    "preparation.model_change_request_persistence_failed",
                    f"preparation.exception.{type(exc).__name__}",
                )
            )

    readiness = build_valuation_readiness(
        snapshot=snapshot,
        statement_run=statement_run,
        operating=operating,
    )
    approved_replay: ApprovedValuationReplayResult | None = None
    approved_replay_fingerprint = canonical_semantic_hash(
        {
            "status": "pending_pm_approval",
            "snapshot_hash": snapshot.snapshot_hash,
        }
    )
    if eligibility == EligibilityStatus.supported_v1 and not blockers:
        try:
            approved_bundle = load_approved_family_bundle(
                conn,
                snapshot=snapshot,
            )
        except Exception as exc:
            blockers.extend(
                (
                    "preparation.approved_bundle_invalid",
                    f"preparation.exception.{type(exc).__name__}",
                )
            )
        else:
            if approved_bundle is not None:
                (
                    approved_packs,
                    approval_fingerprints,
                    prompt_contract_fingerprint,
                ) = approved_bundle
                approved_hashes = {
                    pack.family: canonical_semantic_hash(pack)
                    for pack in approved_packs
                }
                readiness = build_valuation_readiness(
                    snapshot=snapshot,
                    statement_run=statement_run,
                    operating=operating,
                    approved_family_hashes=approved_hashes,
                    prompt_contract_fingerprint=(
                        prompt_contract_fingerprint
                    ),
                )
                if readiness.trust_status.value != "decision_grade":
                    blockers.extend(readiness.reason_codes)
                else:
                    try:
                        market_inputs = dict(snapshot.market_inputs)
                        base_driver_payload = market_inputs.get("base_drivers")
                        replay_policy = market_inputs.get("valuation_policy")
                        if (
                            not isinstance(base_driver_payload, Mapping)
                            or not base_driver_payload
                        ):
                            raise ValueError(
                                "approved replay requires frozen base drivers"
                            )
                        if (
                            not isinstance(replay_policy, Mapping)
                            or not replay_policy
                        ):
                            raise ValueError(
                                "approved replay requires frozen valuation policy"
                            )
                        similarity_scores = snapshot.comps_inputs.get(
                            "similarity_scores",
                            {},
                        )
                        if not isinstance(similarity_scores, Mapping):
                            raise ValueError(
                                "approved replay similarity scores are invalid"
                            )
                        approved_case = compile_approved_valuation_case(
                            ticker=normalized_ticker,
                            analysis_snapshot_hash=snapshot.snapshot_hash,
                            base_drivers=ForecastDrivers(
                                **dict(base_driver_payload)
                            ),
                            approved_packs=approved_packs,
                            approval_fingerprints=approval_fingerprints,
                            approved_treatment_hashes=_treatment_hashes(
                                tuple(snapshot.approved_treatments)
                            ),
                            frozen_comps_detail=dict(snapshot.comps_inputs),
                            valuation_policy=dict(replay_policy),
                            engine_fingerprint=VALUATION_ENGINE_FINGERPRINT,
                            readiness=readiness,
                            comps_similarity_scores={
                                str(peer): float(score)
                                for peer, score in similarity_scores.items()
                            },
                        )
                        approved_replay = replay_approved_valuation_case(
                            approved_case
                        )
                        persisted_replay_key = (
                            persist_approved_valuation_replay(
                                conn,
                                case=approved_case,
                                result=approved_replay,
                            )
                        )
                        if persisted_replay_key != approved_case.replay_key:
                            raise ValueError(
                                "persisted replay identity changed"
                            )
                        approved_replay_fingerprint = (
                            approved_case.replay_key
                        )
                    except Exception as exc:
                        approved_replay = None
                        blockers.extend(
                            (
                                "preparation.approved_replay_failed",
                                f"preparation.exception.{type(exc).__name__}",
                            )
                        )

    context = TickerRunContext(
        identity=TickerIdentity(ticker=normalized_ticker),
        analysis_as_of=analysis_as_of,
        eligibility=eligibility,
        eligibility_reason_code=eligibility_reason,
        valuation_model="industrial_fcff_dcf_comps_v1",
        replay_inputs=_replay_inputs(
            analysis_snapshot_hash=snapshot.snapshot_hash,
            readiness=readiness,
            approved_replay_fingerprint=approved_replay_fingerprint,
        ),
        readiness=readiness,
        model_change_request=model_change_request,
        source_fingerprints=_snapshot_source_fingerprints(snapshot),
    )
    return PreparedTickerRun(
        context=context,
        snapshot=snapshot,
        blocker_reason_codes=tuple(blockers),
        approved_replay=approved_replay,
    )


def _judgment_result_fingerprint(
    result: ValuationJudgmentPipelineResult,
) -> str:
    queue_ids = {
        (
            family.value
            if isinstance(family, DriverFamily)
            else str(family)
        ): int(queue_id)
        for family, queue_id in result.queue_item_ids.items()
    }
    model_change_ids = {
        (
            family.value
            if isinstance(family, DriverFamily)
            else str(family)
        ): tuple(ids)
        for family, ids in result.model_change_request_ids.items()
    }
    return canonical_semantic_hash(
        {
            "status": result.status,
            "snapshot_hash": result.snapshot_hash,
            "queue_item_ids": queue_ids,
            "blocker_reasons": {
                (
                    family.value
                    if isinstance(family, DriverFamily)
                    else str(family)
                ): reason
                for family, reason in result.blocker_reasons.items()
            },
            "model_change_request_ids": model_change_ids,
        }
    )


def execute_prepared_ticker(
    prepared: PreparedTickerRun,
    *,
    conn: Any,
    bindings: Mapping[DriverFamily, DriverFamilyExecutionBinding],
    transport_timeout_seconds: float,
    force_refresh: bool = False,
    judgment_runner: Callable[..., ValuationJudgmentPipelineResult] = (
        run_valuation_judgment_pipeline
    ),
) -> TickerTerminalRecord:
    """Execute judgment or replay for one already-frozen ticker context."""

    if (
        not math.isfinite(float(transport_timeout_seconds))
        or float(transport_timeout_seconds) <= 0
    ):
        raise ValueError(
            "transport_timeout_seconds must be finite and positive"
        )
    context = prepared.context
    if context.eligibility == EligibilityStatus.unsupported_model:
        return TickerTerminalRecord(
            context=context,
            status=TerminalStatus.blocked,
            reason_code=(
                context.eligibility_reason_code
                or "eligibility.unsupported_model"
            ),
            retryable=False,
            model_change_request=context.model_change_request,
        )
    if (
        prepared.blocker_reason_codes
        or prepared.snapshot is None
        or context.readiness.trust_status.value == "blocked"
    ):
        detail = prepared.blocker_reason_codes or context.readiness.reason_codes
        return TickerTerminalRecord(
            context=context,
            status=TerminalStatus.blocked,
            reason_code="trust_gate.incomplete",
            reason_detail=",".join(detail),
            retryable=False,
            model_change_request=context.model_change_request,
        )
    if prepared.approved_replay is not None:
        replay_key = (
            context.replay_inputs.approved_case_replay_fingerprint
        )
        try:
            persisted_replay = load_approved_valuation_replay(
                conn,
                replay_key,
            )
        except Exception as exc:
            return TickerTerminalRecord(
                context=context,
                status=TerminalStatus.blocked,
                reason_code="trust_gate.incomplete",
                reason_detail=(
                    "approved_replay.persistence_invalid."
                    f"{type(exc).__name__}"
                ),
                retryable=False,
                model_change_request=context.model_change_request,
            )
        if persisted_replay is None:
            return TickerTerminalRecord(
                context=context,
                status=TerminalStatus.blocked,
                reason_code="trust_gate.incomplete",
                reason_detail="approved_replay.persistence_missing",
                retryable=False,
                model_change_request=context.model_change_request,
            )
        approved_case, approved_result = persisted_replay
        if (
            approved_case.replay_key != replay_key
            or approved_case.ticker != context.identity.ticker
            or approved_case.analysis_snapshot_hash
            != context.replay_inputs.analysis_snapshot_hash
            or approved_case.analysis_snapshot_hash
            != prepared.snapshot.snapshot_hash
            or approved_case.readiness_fingerprint
            != context.readiness.readiness_fingerprint
            or approved_result != prepared.approved_replay
            or approved_result.trust_status != "decision_grade"
        ):
            return TickerTerminalRecord(
                context=context,
                status=TerminalStatus.blocked,
                reason_code="trust_gate.incomplete",
                reason_detail="approved_replay.context_mismatch",
                retryable=False,
                model_change_request=context.model_change_request,
            )
        return TickerTerminalRecord(
            context=context,
            status=TerminalStatus.decision_grade,
            reason_code="valuation.completed",
            result_fingerprint=approved_result.output_hash,
            retryable=False,
            model_change_request=context.model_change_request,
        )

    result = judgment_runner(
        snapshot=prepared.snapshot,
        bindings=bindings,
        conn=conn,
        force_refresh=force_refresh,
        transport_timeout_seconds=float(transport_timeout_seconds),
    )
    if (
        str(getattr(result, "snapshot_hash", "")).strip()
        != prepared.snapshot.snapshot_hash
    ):
        return TickerTerminalRecord(
            context=context,
            status=TerminalStatus.blocked,
            reason_code="trust_gate.incomplete",
            reason_detail="judgment.snapshot_mismatch",
            retryable=False,
            model_change_request=context.model_change_request,
        )
    all_families_queued = (
        result.status == "queued"
        and set(result.queue_item_ids) == set(DriverFamily)
    )
    if all_families_queued:
        return TickerTerminalRecord(
            context=context,
            status=TerminalStatus.provisional,
            reason_code="valuation.provisional",
            result_fingerprint=_judgment_result_fingerprint(result),
            reason_detail="awaiting_pm_approval",
            retryable=False,
            model_change_request=context.model_change_request,
        )
    return TickerTerminalRecord(
        context=context,
        status=TerminalStatus.blocked,
        reason_code="trust_gate.incomplete",
        reason_detail=",".join(
            str(reason)
            for reason in result.blocker_reasons.values()
        )
        or "judgment_families_incomplete",
        retryable=False,
        model_change_request=context.model_change_request,
    )


def run_valuation_workup_batch(
    prepared_runs: Iterable[PreparedTickerRun],
    *,
    bindings: Mapping[DriverFamily, DriverFamilyExecutionBinding],
    connection_factory: Callable[[], Any],
    max_workers: int = 8,
    prior_records: Iterable[TickerTerminalRecord] = (),
    retry_policy: RetryPolicy = RetryPolicy(),
    transport_timeout_seconds: float = 120.0,
    batch_timeout_seconds: float = 900.0,
    max_in_flight: int | None = None,
    provider_lane: Callable[[TickerRunContext], str] | None = None,
    provider_lane_limits: Mapping[str, int] | None = None,
    rate_limiter: Callable[[str, TickerRunContext], None] | None = None,
    checkpoint_callback: Callable[[TickerTerminalRecord], None] | None = None,
    force_refresh: bool = False,
    judgment_runner: Callable[..., ValuationJudgmentPipelineResult] = (
        run_valuation_judgment_pipeline
    ),
) -> TickerBatchManifest:
    """Run prepared names through the existing bounded no-drop scheduler."""

    prepared = tuple(prepared_runs)
    by_context = {
        item.context.context_fingerprint: item
        for item in prepared
    }

    def execute(
        context: TickerRunContext,
        *,
        transport_timeout_seconds: float,
    ) -> TickerTerminalRecord:
        item = by_context[context.context_fingerprint]
        conn = connection_factory()
        try:
            return execute_prepared_ticker(
                item,
                conn=conn,
                bindings=bindings,
                transport_timeout_seconds=transport_timeout_seconds,
                force_refresh=force_refresh,
                judgment_runner=judgment_runner,
            )
        finally:
            close = getattr(conn, "close", None)
            if callable(close):
                close()

    return run_ticker_batch(
        (item.context for item in prepared),
        execute,
        max_workers=max_workers,
        prior_records=prior_records,
        retry_policy=retry_policy,
        transport_timeout_seconds=transport_timeout_seconds,
        batch_timeout_seconds=batch_timeout_seconds,
        max_in_flight=max_in_flight,
        provider_lane=provider_lane,
        provider_lane_limits=provider_lane_limits,
        rate_limiter=rate_limiter,
        checkpoint_callback=checkpoint_callback,
    )


__all__ = [
    "BRIDGE_ENGINE_FINGERPRINT",
    "COMPS_ENGINE_FINGERPRINT",
    "DCF_ENGINE_FINGERPRINT",
    "JUDGMENT_CONTRACT_FINGERPRINT",
    "PreparedTickerRun",
    "VALUATION_ENGINE_FINGERPRINT",
    "VALUATION_EXECUTION_CONTRACT_VERSION",
    "build_valuation_readiness",
    "execute_prepared_ticker",
    "prepare_ticker_run",
    "run_valuation_workup_batch",
]
