from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, replace
import hashlib
import json
import sqlite3

import pytest

from db.loader import (
    insert_pm_decision_queue_event,
    insert_pm_decision_queue_item,
)
from db.schema import create_tables
from src.stage_00_data.source_reconciliation import (
    SourceReconciliationResult,
    StatementReadinessResult,
)
from src.contracts.analysis_snapshot import AnalysisSnapshot
from src.contracts.assumption_registry import DriverFamily
from src.contracts.driver_families import (
    DriverFamilyCritique,
    DriverFamilyProposal,
)
from src.contracts.judgment_runs import (
    AgentAttemptStatus,
    AgentRunAttempt,
    AgentRunEnvelope,
    AgentRunStatus,
    AgentTraceMetadata,
    JudgmentTask,
    ProviderRoute,
    canonical_semantic_hash,
)
from src.stage_02_valuation.approved_case_replay import (
    ApprovedValuationCase,
    ApprovedValuationReplayResult,
    compile_approved_valuation_case,
    replay_approved_valuation_case,
)
from src.stage_02_valuation.operating_reconciliation import (
    OperatingReconciliationResult,
)
from src.stage_04_pipeline.driver_family_queue import (
    build_driver_family_queue_item,
)
from src.stage_04_pipeline.operating_reconciliation_service import (
    TickerOperatingReconciliation,
)
from src.stage_04_pipeline.pm_decision_queue import _driver_family_review
from src.stage_04_pipeline.statement_reconciliation_service import (
    TickerStatementReconciliationRun,
)
from src.stage_04_pipeline.ticker_valuation_execution import (
    BRIDGE_ENGINE_FINGERPRINT,
    COMPS_ENGINE_FINGERPRINT,
    DCF_ENGINE_FINGERPRINT,
    VALUATION_ENGINE_FINGERPRINT,
    build_valuation_readiness,
)
from src.stage_04_pipeline.valuation_run_store import (
    load_approved_family_bundle,
    load_agent_run_envelope,
    load_analysis_snapshot,
    load_approved_valuation_replay,
    load_cached_successful_envelope,
    persist_agent_run_envelope,
    persist_analysis_snapshot,
    persist_approved_valuation_replay,
    release_judgment_invocation,
    reserve_judgment_invocation,
)
from tests.test_approved_valuation_replay import (
    _approved_packs,
    _base_drivers,
    _comps_detail,
    _engine_fingerprint,
    _readiness,
)
from tests.valuation_provenance_fixtures import (
    authoritative_snapshot,
    persist_snapshot_provenance,
)


def _connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    create_tables(conn)
    _create_support_tables(conn)
    return conn


def _create_support_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS valuation_artifact_integrity (
            artifact_type TEXT NOT NULL,
            artifact_key TEXT NOT NULL,
            payload_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (artifact_type, artifact_key)
        );
        CREATE TABLE IF NOT EXISTS judgment_invocation_reservations (
            invocation_hash TEXT PRIMARY KEY,
            owner_run_id TEXT NOT NULL,
            reserved_at_epoch REAL NOT NULL,
            lease_expires_at_epoch REAL NOT NULL
        );
        """
    )


def _snapshot(captured_at: str = "2026-07-26T10:00:00Z") -> AnalysisSnapshot:
    treatments = (
        {
            "treatment_id": "treatment-1",
            "topic": "operating_cash",
            "valuation_treatment": "exclude_excess_cash",
            "evidence_anchor_ids": ["fact:cash"],
        },
    )
    evidence: dict[str, dict[str, float | int]] = {
        anchor: {"value": index}
        for index, anchor in enumerate(
            (
                anchor
                for pack in _approved_packs()
                for assumption in pack.assumptions
                for anchor in assumption.evidence_anchor_ids
            ),
            start=1,
        )
    }
    evidence["fact:cash"] = {"value": 25.0}
    comps = _comps_detail()
    return authoritative_snapshot(
        {
            "ticker": "TEST",
            "as_of_date": "2026-07-26",
            "identity": {"cik": "0000000001"},
            "statements": {
                "annual_period_count": 5,
                "ltm_status": "compatible",
            },
            "statement_reconciliation": {"status": "reconciled"},
            "claim_ledger": {
                "status": "reconciled",
                "fingerprint": "claim-hash",
            },
            "market_inputs": {
                "price": 10.0,
                "base_drivers": asdict(_base_drivers()),
                "valuation_policy": {
                    "scenario_probabilities": {
                        "low": 0.25,
                        "base": 0.50,
                        "high": 0.25,
                    }
                },
                "operating_reconciliation": {
                    "status": "reconciled",
                    "fingerprint": "operating-hash",
                },
            },
            "wacc_inputs": {"wacc": 0.09},
            "comps_inputs": comps,
            "approved_treatments": treatments,
            "evidence": evidence,
            "upstream_context": {"business": {}, "industry": {}},
            "source_fingerprints": {
                "xbrl": "xbrl-hash",
                "claim_ledger": "claim-hash",
                "operating_reconciliation": "operating-hash",
                "comps": canonical_semantic_hash(comps),
                "approved_treatments": canonical_semantic_hash(treatments),
                "evidence": canonical_semantic_hash(evidence),
                "valuation_policy": canonical_semantic_hash(
                    {
                        "scenario_probabilities": {
                            "low": 0.25,
                            "base": 0.50,
                            "high": 0.25,
                        }
                    }
                ),
            },
            "component_versions": {
                "snapshot_builder": "v1",
                "dcf_engine_fingerprint": "dcf-test-v1",
                "comps_engine_fingerprint": "comps-test-v1",
                "bridge_engine_fingerprint": "bridge-test-v1",
            },
            "captured_at": captured_at,
        }
    )


def _persist_snapshot(
    conn: sqlite3.Connection,
    snapshot: AnalysisSnapshot | None = None,
) -> AnalysisSnapshot:
    resolved = snapshot or _snapshot()
    persist_snapshot_provenance(conn, resolved)
    persist_analysis_snapshot(conn, resolved)
    return resolved


def _envelope() -> AgentRunEnvelope:
    task = JudgmentTask.model_validate(
        {
            "task_version": "v1",
            "ticker": "TEST",
            "family": "revenue",
            "role": "primary",
            "frozen_snapshot_hash": _snapshot().snapshot_hash,
            "prompt_id": "driver-family.revenue.primary",
            "prompt_hash": "prompt-hash",
            "schema_id": "DriverFamilyProposal",
            "schema_hash": "schema-hash",
            "compiler_id": "message-compiler",
            "compiler_hash": "compiler-hash",
            "messages": [{"role": "user", "content": "Return JSON."}],
        }
    )
    route = ProviderRoute.model_validate(
        {
            "route_id": "fixture",
            "provider": "fixture",
            "adapter_id": "fixture",
            "adapter_version": "v1",
            "requested_model": "fixture-model",
            "endpoint_capability": "structured",
            "sampling": {"temperature": 0.0},
        }
    )
    return AgentRunEnvelope(
        run_id="run-1",
        task=task,
        route=route,
        status=AgentRunStatus.succeeded,
        attempts=(
            AgentRunAttempt(
                attempt_number=1,
                status=AgentAttemptStatus.succeeded,
                raw_response={"family": "revenue"},
                validated_payload={"family": "revenue"},
                trace=AgentTraceMetadata(
                    started_at="2026-07-26T10:00:00Z",
                    completed_at="2026-07-26T10:00:01Z",
                    actual_model="fixture-model-v2",
                    response_hash="response-hash",
                ),
            ),
        ),
    )


def _accepted_critique(family: DriverFamily) -> DriverFamilyCritique:
    return DriverFamilyCritique.model_validate(
        {
            "family": family.value,
            "verdict": "accept",
            "issues": [],
            "summary": f"{family.value} is evidence-grounded.",
        }
    )


def _family_envelope(
    snapshot: AnalysisSnapshot,
    pack: DriverFamilyProposal,
    role: str,
) -> AgentRunEnvelope:
    critique = _accepted_critique(pack.family)
    payload = (
        critique.model_dump(mode="json")
        if role == "critic"
        else pack.model_dump(mode="json")
    )
    task = JudgmentTask.model_validate(
        {
            "task_version": "driver-family-v1",
            "ticker": snapshot.ticker,
            "family": pack.family.value,
            "role": role,
            "frozen_snapshot_hash": snapshot.snapshot_hash,
            "prompt_id": f"driver-family.{pack.family.value}.{role}",
            "prompt_hash": f"prompt:{pack.family.value}:{role}:v1",
            "schema_id": (
                "DriverFamilyCritique"
                if role == "critic"
                else "DriverFamilyProposal"
            ),
            "schema_hash": f"schema:{role}:v1",
            "compiler_id": "message-compiler",
            "compiler_hash": "compiler:v1",
            "messages": [
                {
                    "role": "user",
                    "content": (
                        f"Review {pack.family.value}."
                        if role == "critic"
                        else f"Set {pack.family.value}."
                    ),
                }
            ],
            "reviewed_output_hash": (
                canonical_semantic_hash(pack)
                if role == "critic"
                else None
            ),
        }
    )
    route = ProviderRoute.model_validate(
        {
            "route_id": f"fixture-{pack.family.value}-{role}",
            "provider": "fixture",
            "adapter_id": "fixture",
            "adapter_version": "v1",
            "requested_model": f"fixture-{role}",
            "endpoint_capability": "structured",
            "sampling": {"temperature": 0.0},
        }
    )
    return AgentRunEnvelope(
        run_id=f"run-{pack.family.value}-{role}",
        task=task,
        route=route,
        status=AgentRunStatus.succeeded,
        attempts=(
            AgentRunAttempt(
                attempt_number=1,
                status=AgentAttemptStatus.succeeded,
                raw_response=payload,
                validated_payload=payload,
                trace=AgentTraceMetadata(
                    started_at="2026-07-26T10:00:00Z",
                    completed_at="2026-07-26T10:00:01Z",
                    actual_model=f"fixture-{role}-resolved",
                    response_hash=canonical_semantic_hash(payload),
                ),
            ),
        ),
    )


def _family_envelopes(
    snapshot: AnalysisSnapshot,
    packs: tuple[DriverFamilyProposal, ...],
) -> tuple[AgentRunEnvelope, ...]:
    return tuple(
        _family_envelope(snapshot, pack, role)
        for pack in packs
        for role in ("primary", "critic")
    )


def _prompt_contract_fingerprint(
    snapshot: AnalysisSnapshot,
    envelopes: tuple[AgentRunEnvelope, ...],
) -> str:
    return canonical_semantic_hash(
        {
            "contract_version": "approved_replay_prompt_contract_v1",
            "analysis_snapshot_hash": snapshot.snapshot_hash,
            "runs": [
                {
                    "family": envelope.task.family,
                    "run_role": (
                        "critic"
                        if envelope.task.role == "critic"
                        else "primary"
                    ),
                    "semantic_task_hash": envelope.semantic_task_hash,
                    "task_version": envelope.task.task_version,
                    "prompt_id": envelope.task.prompt_id,
                    "prompt_hash": envelope.task.prompt_hash,
                    "schema_id": envelope.task.schema_id,
                    "schema_hash": envelope.task.schema_hash,
                    "compiler_id": envelope.task.compiler_id,
                    "compiler_hash": envelope.task.compiler_hash,
                    "reviewed_output_hash": (
                        envelope.task.reviewed_output_hash
                    ),
                }
                for envelope in envelopes
            ],
        }
    )


def _family_approval_fingerprints(
    snapshot: AnalysisSnapshot,
    packs: tuple[DriverFamilyProposal, ...],
    envelopes: tuple[AgentRunEnvelope, ...],
) -> tuple[str, ...]:
    by_identity = {
        (envelope.task.family, envelope.task.role): envelope
        for envelope in envelopes
    }
    fingerprints: list[str] = []
    for pack in packs:
        primary = by_identity[(pack.family.value, "primary")]
        critic = by_identity[(pack.family.value, "critic")]
        queue_pack = build_driver_family_queue_item(
            ticker=snapshot.ticker,
            proposal=pack,
            critique=_accepted_critique(pack.family),
            analysis_snapshot_hash=snapshot.snapshot_hash,
            primary_run_id=primary.run_id,
            critic_run_id=critic.run_id,
        ).proposal_pack
        assert queue_pack is not None
        envelope_identities = []
        for run_role, envelope in (
            ("primary", primary),
            ("critic", critic),
        ):
            trace = envelope.attempts[-1].trace
            envelope_identities.append(
                {
                    "run_role": run_role,
                    "run_id": envelope.run_id,
                    "semantic_task_hash": envelope.semantic_task_hash,
                    "invocation_hash": envelope.invocation_hash,
                    "prompt_hash": envelope.task.prompt_hash,
                    "schema_hash": envelope.task.schema_hash,
                    "compiler_hash": envelope.task.compiler_hash,
                    "provider": envelope.route.provider,
                    "adapter_id": envelope.route.adapter_id,
                    "adapter_version": envelope.route.adapter_version,
                    "requested_model": envelope.route.requested_model,
                    "actual_model": trace.actual_model,
                    "validated_payload_hash": canonical_semantic_hash(
                        envelope.validated_payload
                    ),
                }
            )
        fingerprints.append(
            canonical_semantic_hash(
                {
                    "ticker": snapshot.ticker,
                    "analysis_snapshot_hash": snapshot.snapshot_hash,
                    "source_fingerprints": snapshot.source_fingerprints,
                    "component_versions": snapshot.component_versions,
                    "statement_reconciliation": (
                        snapshot.statement_reconciliation
                    ),
                    "claim_ledger": snapshot.claim_ledger,
                    "operating_reconciliation": (
                        snapshot.market_inputs.get(
                            "operating_reconciliation"
                        )
                    ),
                    "peer_set": snapshot.comps_inputs,
                    "approved_treatments": (
                        snapshot.approved_treatments
                    ),
                    "proposal_pack": queue_pack.model_dump(mode="json"),
                    "run_envelopes": envelope_identities,
                }
            )
        )
    return tuple(fingerprints)


def _persist_approved_family_bundle(
    conn: sqlite3.Connection,
    snapshot: AnalysisSnapshot,
    packs: tuple[DriverFamilyProposal, ...],
    envelopes: tuple[AgentRunEnvelope, ...],
) -> None:
    by_identity = {
        (envelope.task.family, envelope.task.role): envelope
        for envelope in envelopes
    }
    expected_fingerprints = _family_approval_fingerprints(
        snapshot,
        packs,
        envelopes,
    )
    for pack in packs:
        primary = by_identity[(pack.family.value, "primary")]
        critic = by_identity[(pack.family.value, "critic")]
        persist_agent_run_envelope(conn, primary)
        persist_agent_run_envelope(conn, critic)
        queue_item = build_driver_family_queue_item(
            ticker=snapshot.ticker,
            proposal=pack,
            critique=_accepted_critique(pack.family),
            analysis_snapshot_hash=snapshot.snapshot_hash,
            primary_run_id=primary.run_id,
            critic_run_id=critic.run_id,
        )
        assert queue_item.proposal_pack is not None
        approval_fingerprint, _ = _driver_family_review(
            conn,
            ticker=snapshot.ticker,
            pack=queue_item.proposal_pack,
        )
        assert (
            approval_fingerprint
            == expected_fingerprints[
                tuple(DriverFamily).index(pack.family)
            ]
        )
        approved_pack = queue_item.proposal_pack.model_dump(mode="json")
        stored = queue_item.model_dump(mode="json")
        stored.update(
            {
                "status": "approved",
                "approved_proposal_pack": approved_pack,
                "valuation_impact_bucket": "high",
                "adapter_links": {
                    "approval_fingerprint": approval_fingerprint,
                    "approval_ref": (
                        f"driver-family:{snapshot.ticker}:"
                        f"{pack.family.value}"
                    ),
                    "scalar_pending_rows_created": 0,
                },
                "decision_history": [
                    {
                        "event": "approve",
                        "actor": "pm",
                        "event_ts": "2026-07-26T10:02:00Z",
                        "approved_proposal_pack": approved_pack,
                        "approval_fingerprint": approval_fingerprint,
                    }
                ],
            }
        )
        item_id = insert_pm_decision_queue_item(conn, stored)
        insert_pm_decision_queue_event(
            conn,
            {
                "created_at": "2026-07-26T10:02:00Z",
                "item_id": item_id,
                "ticker": snapshot.ticker,
                "event_type": "approve",
                "actor": "pm",
                "payload": {
                    "approval_fingerprint": approval_fingerprint,
                    "approved_proposal_pack": approved_pack,
                },
            },
        )


def _replay(
    *,
    snapshot: AnalysisSnapshot | None = None,
) -> tuple[ApprovedValuationCase, ApprovedValuationReplayResult]:
    resolved_snapshot = snapshot or _snapshot()
    packs = _approved_packs()
    envelopes = _family_envelopes(resolved_snapshot, packs)
    approval_fingerprints = _family_approval_fingerprints(
        resolved_snapshot,
        packs,
        envelopes,
    )
    treatment_hashes = tuple(
        sorted(
            canonical_semantic_hash(treatment)
            for treatment in resolved_snapshot.approved_treatments
        )
    )
    readiness = _readiness(
        packs,
        comps_detail=dict(resolved_snapshot.comps_inputs),
        treatments=treatment_hashes,
    ).model_copy(
        update={
            "statement_reconciliation_hash": canonical_semantic_hash(
                resolved_snapshot.statement_reconciliation
            ),
            "source_reconciliation_hash": canonical_semantic_hash(
                resolved_snapshot.source_fingerprints
            ),
            "claim_ledger_hash": (
                resolved_snapshot.source_fingerprints["claim_ledger"]
            ),
            "operating_reconciliation_hash": (
                resolved_snapshot.source_fingerprints[
                    "operating_reconciliation"
                ]
            ),
            "prompt_contract_fingerprint": (
                _prompt_contract_fingerprint(
                    resolved_snapshot,
                    envelopes,
                )
            ),
            "dcf_engine_fingerprint": (
                resolved_snapshot.component_versions[
                    "dcf_engine_fingerprint"
                ]
            ),
            "comps_engine_fingerprint": (
                resolved_snapshot.component_versions[
                    "comps_engine_fingerprint"
                ]
            ),
            "bridge_engine_fingerprint": (
                resolved_snapshot.component_versions[
                    "bridge_engine_fingerprint"
                ]
            ),
        }
    )
    case = compile_approved_valuation_case(
        ticker="TEST",
        analysis_snapshot_hash=resolved_snapshot.snapshot_hash,
        base_drivers=_base_drivers(),
        approved_packs=packs,
        approval_fingerprints=approval_fingerprints,
        approved_treatment_hashes=treatment_hashes,
        frozen_comps_detail=dict(resolved_snapshot.comps_inputs),
        valuation_policy={
            "scenario_probabilities": {
                "low": 0.25,
                "base": 0.50,
                "high": 0.25,
            }
        },
        engine_fingerprint=_engine_fingerprint(),
        readiness=readiness,
    )
    return case, replay_approved_valuation_case(case)


def test_snapshot_and_envelope_round_trip_with_exact_cache_identity() -> None:
    conn = _connection()
    snapshot = _snapshot()
    envelope = _envelope()

    persist_snapshot_provenance(conn, snapshot)
    assert persist_analysis_snapshot(conn, snapshot) == snapshot.snapshot_hash
    assert load_analysis_snapshot(conn, snapshot.snapshot_hash) == snapshot
    # Capture time is provenance, not semantic identity; the first immutable
    # capture remains canonical for the same semantic snapshot.
    assert (
        persist_analysis_snapshot(
            conn,
            _snapshot("2026-07-26T10:01:00Z"),
        )
        == snapshot.snapshot_hash
    )
    assert persist_agent_run_envelope(conn, envelope) == "run-1"
    assert load_agent_run_envelope(conn, "run-1") == envelope
    assert (
        load_cached_successful_envelope(conn, envelope.idempotency_key)
        == envelope
    )
    assert (
        load_cached_successful_envelope(conn, "different-invocation") is None
    )


def test_load_approved_family_bundle_returns_none_until_complete() -> None:
    conn = _connection()
    snapshot = _persist_snapshot(conn)

    assert (
        load_approved_family_bundle(
            conn,
            snapshot=snapshot,
        )
        is None
    )


def test_load_approved_family_bundle_returns_validated_family_order() -> None:
    conn = _connection()
    snapshot = _persist_snapshot(conn)
    packs = _approved_packs()
    envelopes = _family_envelopes(snapshot, packs)
    _persist_approved_family_bundle(conn, snapshot, packs, envelopes)

    assert load_approved_family_bundle(
        conn,
        snapshot=snapshot,
    ) == (
        packs,
        _family_approval_fingerprints(snapshot, packs, envelopes),
        _prompt_contract_fingerprint(snapshot, envelopes),
    )


def test_load_approved_family_bundle_returns_none_for_three_families() -> None:
    conn = _connection()
    snapshot = _persist_snapshot(conn)
    packs = _approved_packs()[:-1]
    envelopes = _family_envelopes(snapshot, packs)
    _persist_approved_family_bundle(conn, snapshot, packs, envelopes)

    assert (
        load_approved_family_bundle(
            conn,
            snapshot=snapshot,
        )
        is None
    )


def test_load_approved_family_bundle_rejects_duplicate_family() -> None:
    conn = _connection()
    snapshot = _persist_snapshot(conn)
    packs = _approved_packs()
    envelopes = _family_envelopes(snapshot, packs)
    _persist_approved_family_bundle(conn, snapshot, packs, envelopes)
    _persist_approved_family_bundle(
        conn,
        snapshot,
        packs[:1],
        envelopes[:2],
    )

    with pytest.raises(
        ValueError,
        match="exactly one matching approval per family",
    ):
        load_approved_family_bundle(
            conn,
            snapshot=snapshot,
        )


def test_execution_readiness_round_trips_exact_approved_replay() -> None:
    conn = _connection()
    base_snapshot = _snapshot()
    similarity_scores = {
        "AAA": 0.95,
        "BBB": 0.80,
        "CCC": 0.65,
        "DDD": 0.50,
    }
    comps_inputs = {
        **dict(base_snapshot.comps_inputs),
        "similarity_scores": similarity_scores,
    }
    operating = TickerOperatingReconciliation(
        result=OperatingReconciliationResult(
            status="reconciled",
            tie_outs=(),
            clamp_events=(),
            reason_codes=(),
        ),
        selected_fact_ids_by_role={},
        period_start="2025-07-01",
        period_end=base_snapshot.as_of_date,
        period_kind="ltm",
        reporting_currency="USD",
        inventory_applicable=False,
    )
    claim_ledger = {
        **dict(base_snapshot.claim_ledger),
        "reconciliation": {"is_decision_grade": True},
    }
    market_inputs = {
        **dict(base_snapshot.market_inputs),
        "operating_reconciliation": json.loads(
            json.dumps(operating.to_dict())
        ),
    }
    source_fingerprints = {
        **dict(base_snapshot.source_fingerprints),
        "claim_ledger": str(claim_ledger["fingerprint"]),
        "operating_reconciliation": operating.fingerprint,
        "comps": canonical_semantic_hash(comps_inputs),
    }
    component_versions = {
        **dict(base_snapshot.component_versions),
        "dcf_engine_fingerprint": DCF_ENGINE_FINGERPRINT,
        "comps_engine_fingerprint": COMPS_ENGINE_FINGERPRINT,
        "bridge_engine_fingerprint": BRIDGE_ENGINE_FINGERPRINT,
    }
    snapshot = base_snapshot.model_copy(
        update={
            "claim_ledger": claim_ledger,
            "market_inputs": market_inputs,
            "comps_inputs": comps_inputs,
            "source_fingerprints": source_fingerprints,
            "component_versions": component_versions,
        }
    )
    _persist_snapshot(conn, snapshot)

    source_reconciliation = SourceReconciliationResult(
        status="pass",
        decision_grade=True,
        comparisons=(),
        findings=(),
        overlap_count=1,
        coverage_attested=True,
        expected_quantity_count=1,
        missing_expected_count=0,
    )
    statement_run = TickerStatementReconciliationRun(
        ticker=snapshot.ticker,
        facts_fingerprint="fixture-facts",
        readiness=StatementReadinessResult(
            status="decision_grade",
            decision_grade=True,
            annual_period_count=5,
            ltm_status="compatible",
            source_reconciliation=source_reconciliation,
            checks=(),
            findings=(),
            reason_codes=(),
        ),
        persisted_queue_item_ids=(),
        run_hash=str(
            snapshot.statement_reconciliation[
                "reconciliation_run_hash"
            ]
        ),
        as_of_date=snapshot.as_of_date,
        raw_ledger_hash="fixture-raw-ledger",
        selected_view_hash="fixture-selected-view",
        manifest_ids=(),
        selected_fact_ids=tuple(
            str(fact_id)
            for fact_id in snapshot.statements["fact_ids"]
        ),
    )
    packs = _approved_packs()
    envelopes = _family_envelopes(snapshot, packs)
    _persist_approved_family_bundle(conn, snapshot, packs, envelopes)
    approved_bundle = load_approved_family_bundle(
        conn,
        snapshot=snapshot,
    )
    assert approved_bundle is not None
    approved_packs, approval_fingerprints, prompt_fingerprint = (
        approved_bundle
    )
    approved_hashes = {
        pack.family: canonical_semantic_hash(pack)
        for pack in approved_packs
    }
    readiness = build_valuation_readiness(
        snapshot=snapshot,
        statement_run=statement_run,
        operating=operating,
        approved_family_hashes=approved_hashes,
        prompt_contract_fingerprint=prompt_fingerprint,
    )
    assert readiness.trust_status.value == "decision_grade"

    treatment_hashes = tuple(
        sorted(
            canonical_semantic_hash(treatment)
            for treatment in snapshot.approved_treatments
        )
    )
    case = compile_approved_valuation_case(
        ticker=snapshot.ticker,
        analysis_snapshot_hash=snapshot.snapshot_hash,
        base_drivers=_base_drivers(),
        approved_packs=approved_packs,
        approval_fingerprints=approval_fingerprints,
        approved_treatment_hashes=treatment_hashes,
        frozen_comps_detail=dict(snapshot.comps_inputs),
        valuation_policy=dict(
            snapshot.market_inputs["valuation_policy"]
        ),
        engine_fingerprint=VALUATION_ENGINE_FINGERPRINT,
        readiness=readiness,
        comps_similarity_scores=similarity_scores,
    )
    result = replay_approved_valuation_case(case)

    assert (
        persist_approved_valuation_replay(
            conn,
            case=case,
            result=result,
        )
        == case.replay_key
    )
    assert load_approved_valuation_replay(
        conn,
        case.replay_key,
    ) == (case, result)
    assert case.similarity_scores() == similarity_scores
    assert result.comps_result["peer_similarity_scores"] == similarity_scores


def test_run_id_and_replay_key_are_immutable() -> None:
    conn = _connection()
    envelope = _envelope()
    snapshot = _persist_snapshot(conn)
    persist_agent_run_envelope(conn, envelope)
    changed = envelope.model_copy(
        update={
            "attempts": (
                envelope.attempts[0].model_copy(
                    update={"raw_response": {"family": "different"}}
                ),
            )
        }
    )
    with pytest.raises(ValueError, match="divergent payloads"):
        persist_agent_run_envelope(conn, changed)

    packs = _approved_packs()
    family_envelopes = _family_envelopes(snapshot, packs)
    _persist_approved_family_bundle(
        conn,
        snapshot,
        packs,
        family_envelopes,
    )
    case, result = _replay(snapshot=snapshot)
    persist_approved_valuation_replay(conn, case=case, result=result)
    assert load_approved_valuation_replay(conn, case.replay_key) == (case, result)
    changed_output = '{"trust_status":"provisional"}'
    changed_result = replace(
        result,
        canonical_output=changed_output,
        output_hash=hashlib.sha256(changed_output.encode("utf-8")).hexdigest(),
        trust_status="provisional",
    )
    with pytest.raises(ValueError, match="deterministic replay"):
        persist_approved_valuation_replay(
            conn,
            case=case,
            result=changed_result,
        )


def test_replay_store_requires_snapshot_and_all_four_approved_families() -> None:
    conn = _connection()
    snapshot = _snapshot()
    case, result = _replay(snapshot=snapshot)

    with pytest.raises(ValueError, match="analysis snapshot"):
        persist_approved_valuation_replay(
            conn,
            case=case,
            result=result,
        )

    _persist_snapshot(conn, snapshot)
    with pytest.raises(ValueError, match="approved driver-family"):
        persist_approved_valuation_replay(
            conn,
            case=case,
            result=result,
        )


def test_replay_store_recomputes_each_pm_approval_fingerprint() -> None:
    conn = _connection()
    snapshot = _persist_snapshot(conn)
    packs = _approved_packs()
    envelopes = _family_envelopes(snapshot, packs)
    _persist_approved_family_bundle(conn, snapshot, packs, envelopes)
    case, result = _replay(snapshot=snapshot)
    row = conn.execute(
        """
        SELECT id, adapter_links_json
        FROM pm_decision_queue_items
        WHERE ticker = ? AND status = 'approved'
        ORDER BY id
        LIMIT 1
        """,
        (snapshot.ticker,),
    ).fetchone()
    adapter_links = json.loads(row[1])
    adapter_links["approval_fingerprint"] = "forged"
    conn.execute(
        """
        UPDATE pm_decision_queue_items
        SET adapter_links_json = ?
        WHERE id = ?
        """,
        (
            json.dumps(adapter_links, separators=(",", ":")),
            row[0],
        ),
    )
    conn.commit()

    with pytest.raises(ValueError, match="approval fingerprint"):
        load_approved_family_bundle(
            conn,
            snapshot=snapshot,
        )
    with pytest.raises(ValueError, match="approval fingerprint"):
        persist_approved_valuation_replay(
            conn,
            case=case,
            result=result,
        )


def test_replay_store_ignores_approval_for_a_different_snapshot() -> None:
    conn = _connection()
    snapshot = _persist_snapshot(conn)
    packs = _approved_packs()
    envelopes = _family_envelopes(snapshot, packs)
    _persist_approved_family_bundle(conn, snapshot, packs, envelopes)
    case, result = _replay(snapshot=snapshot)

    changed_payload = deepcopy(packs[0].model_dump(mode="json"))
    changed_payload["assumptions"][0]["base"] = 0.081
    changed_pack = DriverFamilyProposal.model_validate(changed_payload)
    historical_item = build_driver_family_queue_item(
        ticker=snapshot.ticker,
        proposal=changed_pack,
        critique=_accepted_critique(changed_pack.family),
        analysis_snapshot_hash="historical-snapshot",
        primary_run_id="historical-primary",
        critic_run_id="historical-critic",
    )
    assert historical_item.proposal_pack is not None
    historical_pack = historical_item.proposal_pack.model_dump(mode="json")
    stored = historical_item.model_dump(mode="json")
    stored.update(
        {
            "status": "approved",
            "approved_proposal_pack": historical_pack,
            "valuation_impact_bucket": "high",
            "adapter_links": {
                "approval_fingerprint": "historical-fingerprint"
            },
            "decision_history": [],
        }
    )
    insert_pm_decision_queue_item(conn, stored)

    assert (
        persist_approved_valuation_replay(
            conn,
            case=case,
            result=result,
        )
        == case.replay_key
    )


@pytest.mark.parametrize(
    "field_name",
    (
        "statement_reconciliation_hash",
        "source_reconciliation_hash",
        "claim_ledger_hash",
        "operating_reconciliation_hash",
        "prompt_contract_fingerprint",
    ),
)
def test_replay_store_recomputes_readiness_fingerprints(
    field_name: str,
) -> None:
    conn = _connection()
    snapshot = _persist_snapshot(conn)
    packs = _approved_packs()
    envelopes = _family_envelopes(snapshot, packs)
    _persist_approved_family_bundle(conn, snapshot, packs, envelopes)
    original_case, _ = _replay(snapshot=snapshot)
    forged_readiness = original_case.readiness().model_copy(
        update={field_name: f"forged:{field_name}"}
    )
    forged_case = compile_approved_valuation_case(
        ticker=snapshot.ticker,
        analysis_snapshot_hash=snapshot.snapshot_hash,
        base_drivers=_base_drivers(),
        approved_packs=packs,
        approval_fingerprints=original_case.approval_fingerprints,
        approved_treatment_hashes=(
            original_case.approved_treatment_hashes
        ),
        frozen_comps_detail=snapshot.comps_inputs,
        valuation_policy=snapshot.market_inputs["valuation_policy"],
        engine_fingerprint=original_case.engine_fingerprint,
        readiness=forged_readiness,
    )

    with pytest.raises(ValueError, match=field_name):
        persist_approved_valuation_replay(
            conn,
            case=forged_case,
            result=replay_approved_valuation_case(forged_case),
        )


@pytest.mark.parametrize(
    ("tamper", "message"),
    (
        ("peer", "peer_set_fingerprint"),
        ("treatment", "treatment fingerprint"),
        ("engine", "dcf_engine_fingerprint"),
    ),
)
def test_replay_store_recomputes_frozen_input_fingerprints(
    tamper: str,
    message: str,
) -> None:
    conn = _connection()
    snapshot = _persist_snapshot(conn)
    packs = _approved_packs()
    envelopes = _family_envelopes(snapshot, packs)
    _persist_approved_family_bundle(conn, snapshot, packs, envelopes)
    original_case, _ = _replay(snapshot=snapshot)
    readiness = original_case.readiness()
    comps = dict(snapshot.comps_inputs)
    treatment_hashes = original_case.approved_treatment_hashes
    engine_fingerprint = original_case.engine_fingerprint
    if tamper == "peer":
        comps = json.loads(json.dumps(snapshot.comps_inputs))
        comps["target"]["market_cap_mm"] = 901.0
        readiness = readiness.model_copy(
            update={
                "peer_set_fingerprint": canonical_semantic_hash(comps)
            }
        )
    elif tamper == "treatment":
        treatment_hashes = ()
        readiness = readiness.model_copy(
            update={
                "treatment_set_fingerprint": canonical_semantic_hash([])
            }
        )
    else:
        readiness = readiness.model_copy(
            update={"dcf_engine_fingerprint": "dcf-forged-v2"}
        )
        engine_fingerprint = canonical_semantic_hash(
            {
                "dcf": readiness.dcf_engine_fingerprint,
                "comps": readiness.comps_engine_fingerprint,
                "bridge": readiness.bridge_engine_fingerprint,
            }
        )
    forged_case = compile_approved_valuation_case(
        ticker=snapshot.ticker,
        analysis_snapshot_hash=snapshot.snapshot_hash,
        base_drivers=_base_drivers(),
        approved_packs=packs,
        approval_fingerprints=original_case.approval_fingerprints,
        approved_treatment_hashes=treatment_hashes,
        frozen_comps_detail=comps,
        valuation_policy=snapshot.market_inputs["valuation_policy"],
        engine_fingerprint=engine_fingerprint,
        readiness=readiness,
    )

    with pytest.raises(ValueError, match=message):
        persist_approved_valuation_replay(
            conn,
            case=forged_case,
            result=replay_approved_valuation_case(forged_case),
        )


def test_replay_store_recomputes_snapshot_evidence_fingerprint() -> None:
    conn = _connection()
    snapshot = _snapshot()
    source_fingerprints = dict(snapshot.source_fingerprints)
    source_fingerprints["evidence"] = "forged-evidence"
    snapshot = snapshot.model_copy(
        update={"source_fingerprints": source_fingerprints}
    )
    _persist_snapshot(conn, snapshot)
    packs = _approved_packs()
    envelopes = _family_envelopes(snapshot, packs)
    _persist_approved_family_bundle(conn, snapshot, packs, envelopes)
    case, result = _replay(snapshot=snapshot)

    with pytest.raises(
        ValueError,
        match="snapshot component fingerprint",
    ):
        persist_approved_valuation_replay(
            conn,
            case=case,
            result=result,
        )


def test_replay_load_fails_closed_on_payload_or_index_tamper() -> None:
    conn = _connection()
    snapshot = _persist_snapshot(conn)
    packs = _approved_packs()
    envelopes = _family_envelopes(snapshot, packs)
    _persist_approved_family_bundle(conn, snapshot, packs, envelopes)
    case, result = _replay(snapshot=snapshot)
    persist_approved_valuation_replay(conn, case=case, result=result)

    conn.execute(
        """
        UPDATE approved_valuation_replays
        SET result_json = replace(
            result_json,
            '"trust_status":"decision_grade"',
            '"trust_status":"provisional"'
        )
        WHERE replay_key = ?
        """,
        (case.replay_key,),
    )
    conn.commit()
    with pytest.raises(ValueError, match="integrity"):
        load_approved_valuation_replay(conn, case.replay_key)

    conn = _connection()
    snapshot = _persist_snapshot(conn)
    packs = _approved_packs()
    envelopes = _family_envelopes(snapshot, packs)
    _persist_approved_family_bundle(conn, snapshot, packs, envelopes)
    case, result = _replay(snapshot=snapshot)
    persist_approved_valuation_replay(conn, case=case, result=result)
    conn.execute(
        """
        UPDATE approved_valuation_replays
        SET ticker = 'OTHER'
        WHERE replay_key = ?
        """,
        (case.replay_key,),
    )
    conn.commit()
    with pytest.raises(ValueError, match="indexed columns"):
        load_approved_valuation_replay(conn, case.replay_key)


def test_envelope_store_rejects_an_orphan_snapshot() -> None:
    conn = _connection()

    with pytest.raises(ValueError, match="analysis snapshot"):
        persist_agent_run_envelope(conn, _envelope())


def test_envelope_store_rejects_success_with_blank_actual_model() -> None:
    conn = _connection()
    _persist_snapshot(conn)
    envelope = _envelope()
    blank_trace = envelope.attempts[-1].trace.model_copy(
        update={"actual_model": " "}
    )
    blank_attempt = envelope.attempts[-1].model_copy(
        update={"trace": blank_trace}
    )
    forged = envelope.model_copy(update={"attempts": (blank_attempt,)})

    with pytest.raises(ValueError, match="nonblank actual_model"):
        persist_agent_run_envelope(conn, forged)


def test_snapshot_and_envelope_loads_fail_closed_on_payload_or_index_tamper() -> None:
    conn = _connection()
    snapshot = _snapshot()
    envelope = _envelope()
    _persist_snapshot(conn, snapshot)
    persist_agent_run_envelope(conn, envelope)

    conn.execute(
        """
        UPDATE analysis_snapshots
        SET payload_json = replace(payload_json, 'xbrl-hash', 'forged-hash')
        WHERE snapshot_hash = ?
        """,
        (snapshot.snapshot_hash,),
    )
    conn.commit()
    with pytest.raises(ValueError, match="integrity"):
        load_analysis_snapshot(conn, snapshot.snapshot_hash)

    conn.execute(
        """
        UPDATE analysis_snapshots SET payload_json = ?
        WHERE snapshot_hash = ?
        """,
        (
            json.dumps(
                snapshot.model_dump(
                    mode="json",
                    exclude_computed_fields=True,
                ),
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ),
            snapshot.snapshot_hash,
        ),
    )
    conn.execute(
        """
        UPDATE judgment_run_envelopes SET ticker = 'OTHER'
        WHERE run_id = ?
        """,
        (envelope.run_id,),
    )
    conn.commit()
    with pytest.raises(ValueError, match="indexed columns"):
        load_agent_run_envelope(conn, envelope.run_id)


def test_replay_store_rejects_a_forged_case_identity() -> None:
    conn = _connection()
    case, result = _replay()
    forged_key = "forged-replay-key"

    with pytest.raises(ValueError, match="replay identity"):
        persist_approved_valuation_replay(
            conn,
            case=replace(case, replay_key=forged_key),
            result=replace(result, replay_key=forged_key),
        )


def test_replay_store_requires_exactly_low_base_and_high_scenarios() -> None:
    conn = _connection()
    case, result = _replay()

    with pytest.raises(ValueError, match="exactly low, base, and high"):
        persist_approved_valuation_replay(
            conn,
            case=replace(case, scenario_drivers=case.scenario_drivers[:2]),
            result=result,
        )


def test_replay_store_rejects_non_decision_grade_readiness() -> None:
    conn = _connection()
    case, result = _replay()
    provisional = case.readiness().model_copy(
        update={"pending_model_change_count": 1}
    )
    provisional_json = json.dumps(
        provisional.model_dump(mode="json", exclude_computed_fields=True),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )

    with pytest.raises(ValueError, match="not decision-grade"):
        persist_approved_valuation_replay(
            conn,
            case=replace(case, readiness_json=provisional_json),
            result=result,
        )


def test_replay_store_recomputes_readiness_fingerprint() -> None:
    conn = _connection()
    case, result = _replay()

    with pytest.raises(ValueError, match="readiness fingerprint"):
        persist_approved_valuation_replay(
            conn,
            case=replace(case, readiness_fingerprint="forged-readiness"),
            result=result,
        )


def test_replay_store_rejects_result_fields_that_do_not_match_recomputation() -> None:
    conn = _connection()
    case, result = _replay()

    with pytest.raises(ValueError, match="deterministic replay"):
        persist_approved_valuation_replay(
            conn,
            case=case,
            result=replace(
                result,
                expected_intrinsic_value=(
                    result.expected_intrinsic_value + 1.0
                ),
            ),
        )


def test_replay_store_rejects_self_consistent_tampered_canonical_output() -> None:
    conn = _connection()
    case, result = _replay()
    tampered_value = result.expected_intrinsic_value + 1.0
    tampered_payload = json.loads(result.canonical_output)
    tampered_payload["expected_intrinsic_value"] = tampered_value
    tampered_output = json.dumps(
        tampered_payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )

    with pytest.raises(ValueError, match="deterministic replay"):
        persist_approved_valuation_replay(
            conn,
            case=case,
            result=replace(
                result,
                expected_intrinsic_value=tampered_value,
                canonical_output=tampered_output,
                output_hash=hashlib.sha256(
                    tampered_output.encode("utf-8")
                ).hexdigest(),
            ),
        )


def test_identical_invocation_lease_is_durable_and_expiry_is_compare_and_set(
    tmp_path,
) -> None:
    db_path = tmp_path / "judgment-reservation.sqlite"
    first = sqlite3.connect(db_path)
    second = sqlite3.connect(db_path)
    create_tables(first)
    _create_support_tables(first)

    assert reserve_judgment_invocation(
        first,
        invocation_hash="invocation-1",
        owner_run_id="run-a",
        lease_seconds=10,
        now_epoch=100,
    )
    assert not reserve_judgment_invocation(
        second,
        invocation_hash="invocation-1",
        owner_run_id="run-b",
        lease_seconds=10,
        now_epoch=105,
    )
    assert reserve_judgment_invocation(
        second,
        invocation_hash="invocation-1",
        owner_run_id="run-b",
        lease_seconds=10,
        now_epoch=110,
    )
    assert not release_judgment_invocation(
        first,
        invocation_hash="invocation-1",
        owner_run_id="run-a",
    )
    assert release_judgment_invocation(
        second,
        invocation_hash="invocation-1",
        owner_run_id="run-b",
    )
