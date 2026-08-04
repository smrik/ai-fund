from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import sqlite3
from types import SimpleNamespace

from pydantic import BaseModel

from src.contracts.assumption_registry import DriverFamily, judgment_owned_fields
from src.contracts.judgment_runs import canonical_semantic_hash
from src.contracts.model_change_requests import build_model_change_request
from src.contracts.ticker_runs import (
    EligibilityStatus,
    ReplayInputFingerprints,
    SourceFingerprint,
    TerminalStatus,
    TickerIdentity,
    TickerReasonCode,
    TickerRunContext,
)
from src.contracts.valuation_readiness import (
    LTMStatus,
    ReconciliationGateStatus,
    ValuationReadinessEvidence,
    assess_judgment_driver_provenance,
)
from src.stage_04_pipeline.ticker_valuation_execution import (
    PreparedTickerRun,
    execute_prepared_ticker,
    prepare_ticker_run,
    run_valuation_workup_batch,
)


class _FakeApprovedPack(BaseModel):
    family: DriverFamily


def _readiness(kind: str) -> ValuationReadinessEvidence:
    approved = (
        {family: f"pack:{family.value}" for family in DriverFamily}
        if kind == "decision_grade"
        else {}
    )
    statement = (
        ReconciliationGateStatus.failed
        if kind == "blocked"
        else ReconciliationGateStatus.reconciled
    )
    return ValuationReadinessEvidence(
        statement_reconciliation=statement,
        source_reconciliation=statement,
        claim_ledger_reconciliation=statement,
        operating_reconciliation=statement,
        annual_period_count=0 if kind == "blocked" else 5,
        ltm_status=(
            LTMStatus.unavailable
            if kind == "blocked"
            else LTMStatus.compatible
        ),
        judgment_driver_verdicts=assess_judgment_driver_provenance(
            {
                field: "approved_assumption_register"
                for field in judgment_owned_fields()
            },
            used_fields=judgment_owned_fields(),
        ),
        approved_family_hashes=approved,
        statement_reconciliation_hash="statement",
        source_reconciliation_hash="source",
        claim_ledger_hash="claim",
        operating_reconciliation_hash="operating",
        peer_set_fingerprint="peers",
        treatment_set_fingerprint="treatments",
        prompt_contract_fingerprint="prompt",
        dcf_engine_fingerprint="dcf",
        comps_engine_fingerprint="comps",
        bridge_engine_fingerprint="bridge",
    )


def _context(ticker: str, kind: str) -> TickerRunContext:
    return TickerRunContext(
        identity=TickerIdentity(ticker=ticker),
        analysis_as_of=date(2026, 7, 26),
        eligibility=EligibilityStatus.supported_v1,
        valuation_model="industrial_fcff_dcf_comps_v1",
        replay_inputs=ReplayInputFingerprints(
            analysis_snapshot_hash=f"snapshot:{ticker}",
            approved_case_replay_fingerprint=f"replay:{kind}",
            peer_universe_fingerprint="peers",
            treatment_register_fingerprint="treatments",
            judgment_contract_fingerprint="prompt",
            valuation_engine_fingerprint="engines",
        ),
        readiness=_readiness(kind),
        source_fingerprints=(
            SourceFingerprint(
                source_id=f"statement:{ticker}",
                fingerprint=f"source:{ticker}",
            ),
        ),
    )


def test_hard_preparation_blocker_calls_no_provider() -> None:
    calls = []
    prepared = PreparedTickerRun(
        context=_context("MISS", "blocked"),
        snapshot=None,
        blocker_reason_codes=("preparation.statement_source_missing",),
    )

    record = execute_prepared_ticker(
        prepared,
        conn=object(),
        bindings={},
        transport_timeout_seconds=12.0,
        judgment_runner=lambda **kwargs: calls.append(kwargs),
    )

    assert calls == []
    assert record.status == TerminalStatus.blocked
    assert record.reason_code.value == "trust_gate.incomplete"
    assert "preparation.statement_source_missing" in record.reason_detail


def test_unsupported_model_calls_no_provider_even_without_batch_wrapper() -> None:
    calls = []
    base_context = _context("BANK", "provisional")
    model_change_request = build_model_change_request(
        ticker="BANK",
        analysis_snapshot_hash="snapshot:BANK",
        category="applicability",
        current_model="industrial_fcff_dcf_comps_v1",
        required_capability="financial_institution_valuation",
        rationale="Industrial FCFF is not applicable.",
        evidence_anchor_ids=("filing:bank",),
        evidence_fingerprints=("evidence:bank",),
        created_at="2026-07-26T10:00:00+00:00",
    )
    context = TickerRunContext(
        identity=base_context.identity,
        analysis_as_of=base_context.analysis_as_of,
        eligibility=EligibilityStatus.unsupported_model,
        eligibility_reason_code=(
            TickerReasonCode.eligibility_unsupported_model
        ),
        valuation_model=base_context.valuation_model,
        replay_inputs=base_context.replay_inputs,
        readiness=base_context.readiness,
        model_change_request=model_change_request,
        source_fingerprints=base_context.source_fingerprints,
    )
    prepared = PreparedTickerRun(
        context=context,
        snapshot=SimpleNamespace(snapshot_hash="snapshot:BANK"),
    )

    record = execute_prepared_ticker(
        prepared,
        conn=object(),
        bindings={},
        transport_timeout_seconds=12.0,
        judgment_runner=lambda **kwargs: calls.append(kwargs),
    )

    assert calls == []
    assert record.status == TerminalStatus.blocked
    assert record.reason_code.value == "eligibility.unsupported_model"


def test_four_queued_families_are_provisional_with_stable_fingerprint() -> None:
    context = _context("TEST", "provisional")
    prepared = PreparedTickerRun(
        context=context,
        snapshot=SimpleNamespace(snapshot_hash="snapshot:TEST"),
    )

    def queued(**kwargs):
        return SimpleNamespace(
            status="queued",
            snapshot_hash="snapshot:TEST",
            queue_item_ids={
                family: index
                for index, family in enumerate(DriverFamily, start=1)
            },
            blocker_reasons={},
            model_change_request_ids={},
        )

    first = execute_prepared_ticker(
        prepared,
        conn=object(),
        bindings={},
        transport_timeout_seconds=17.0,
        judgment_runner=queued,
    )
    second = execute_prepared_ticker(
        prepared,
        conn=object(),
        bindings={},
        transport_timeout_seconds=17.0,
        judgment_runner=queued,
    )

    assert first.status == TerminalStatus.provisional
    assert first.reason_code.value == "valuation.provisional"
    assert first.result_fingerprint == second.result_fingerprint
    assert first.retryable is False


def test_approved_replay_is_provider_free_and_decision_grade(
    monkeypatch,
) -> None:
    from src.stage_04_pipeline import ticker_valuation_execution as execution

    calls = []
    context = _context("TEST", "decision_grade")
    approved_case = SimpleNamespace(
        replay_key="replay:decision_grade",
        ticker="TEST",
        analysis_snapshot_hash="snapshot:TEST",
        readiness_fingerprint=context.readiness.readiness_fingerprint,
    )
    approved_result = SimpleNamespace(
        replay_key="replay:decision_grade",
        output_hash="approved-output",
        trust_status="decision_grade",
    )
    monkeypatch.setattr(
        execution,
        "load_approved_valuation_replay",
        lambda conn, replay_key: (approved_case, approved_result),
        raising=False,
    )
    prepared = PreparedTickerRun(
        context=context,
        snapshot=SimpleNamespace(snapshot_hash="snapshot:TEST"),
        approved_replay=approved_result,
    )

    record = execute_prepared_ticker(
        prepared,
        conn=object(),
        bindings={},
        transport_timeout_seconds=9.0,
        judgment_runner=lambda **kwargs: calls.append(kwargs),
    )

    assert calls == []
    assert record.status == TerminalStatus.decision_grade
    assert record.result_fingerprint == "approved-output"
    assert record.reason_code.value == "valuation.completed"


def test_unpersisted_approved_replay_cannot_claim_decision_grade(
    monkeypatch,
) -> None:
    from src.stage_04_pipeline import ticker_valuation_execution as execution

    monkeypatch.setattr(
        execution,
        "load_approved_valuation_replay",
        lambda conn, replay_key: None,
        raising=False,
    )
    calls = []
    prepared = PreparedTickerRun(
        context=_context("TEST", "decision_grade"),
        snapshot=SimpleNamespace(snapshot_hash="snapshot:TEST"),
        approved_replay=SimpleNamespace(
            replay_key="replay:decision_grade",
            output_hash="forged-output",
            trust_status="decision_grade",
        ),
    )

    record = execute_prepared_ticker(
        prepared,
        conn=object(),
        bindings={},
        transport_timeout_seconds=9.0,
        judgment_runner=lambda **kwargs: calls.append(kwargs),
    )

    assert calls == []
    assert record.status == TerminalStatus.blocked
    assert record.reason_code.value == "trust_gate.incomplete"
    assert record.reason_detail == "approved_replay.persistence_missing"


def test_judgment_result_from_another_snapshot_is_blocked() -> None:
    prepared = PreparedTickerRun(
        context=_context("TEST", "provisional"),
        snapshot=SimpleNamespace(snapshot_hash="snapshot:TEST"),
    )

    record = execute_prepared_ticker(
        prepared,
        conn=object(),
        bindings={},
        transport_timeout_seconds=9.0,
        judgment_runner=lambda **kwargs: SimpleNamespace(
            status="queued",
            snapshot_hash="snapshot:OTHER",
            queue_item_ids={
                family: index
                for index, family in enumerate(DriverFamily, start=1)
            },
            blocker_reasons={},
            model_change_request_ids={},
        ),
    )

    assert record.status == TerminalStatus.blocked
    assert record.reason_detail == "judgment.snapshot_mismatch"


def test_missing_pre_snapshot_input_still_builds_a_terminal_context() -> None:
    calls = []
    statement_run = SimpleNamespace(
        ticker="MISS",
        run_hash="statement-run",
        raw_ledger_hash="raw-ledger",
        selected_view_hash="selected-view",
        manifest_ids=(),
        selected_fact_ids=(),
        persisted_queue_item_ids=(),
        readiness=SimpleNamespace(
            status="decision_grade",
            decision_grade=True,
            annual_period_count=5,
            ltm_status="compatible",
            source_reconciliation=SimpleNamespace(status="pass"),
            reason_codes=(),
        ),
    )

    def no_inputs(*args, **kwargs):
        calls.append((args, kwargs))
        return None

    prepared = prepare_ticker_run(
        object(),
        "miss",
        analysis_as_of=date(2026, 7, 26),
        captured_at="2026-07-26T10:00:00+00:00",
        evidence={},
        upstream_context={},
        comps_inputs={},
        valuation_policy={},
        statement_reconciler=lambda *args, **kwargs: statement_run,
        input_builder=no_inputs,
    )

    assert prepared.context.identity.ticker == "MISS"
    assert prepared.context.readiness.trust_status.value == "blocked"
    assert prepared.snapshot is None
    assert "preparation.valuation_inputs_unavailable" in (
        prepared.blocker_reason_codes
    )
    assert calls[0][1]["apply_overrides"] is False
    assert calls[0][1]["apply_story_overlay"] is False
    assert calls[0][1]["allow_public_comps_fallback"] is False


def test_unreconciled_statements_block_before_input_assembly() -> None:
    calls = []
    statement_run = SimpleNamespace(
        ticker="MISS",
        run_hash="statement-run",
        raw_ledger_hash="raw-ledger",
        selected_view_hash="selected-view",
        manifest_ids=(),
        selected_fact_ids=(),
        persisted_queue_item_ids=(),
        readiness=SimpleNamespace(
            status="blocked",
            decision_grade=False,
            annual_period_count=0,
            ltm_status="not_available",
            source_reconciliation=SimpleNamespace(status="not_comparable"),
            reason_codes=(
                "statement_source.manifest_missing",
                "statement_history.insufficient",
            ),
        ),
    )

    prepared = prepare_ticker_run(
        object(),
        "miss",
        analysis_as_of=date(2026, 7, 26),
        captured_at="2026-07-26T10:00:00+00:00",
        evidence={},
        upstream_context={},
        comps_inputs={},
        valuation_policy={},
        statement_reconciler=lambda *args, **kwargs: statement_run,
        input_builder=lambda *args, **kwargs: calls.append(kwargs),
    )

    assert calls == []
    assert prepared.context.readiness.trust_status.value == "blocked"
    assert (
        "preparation.statement_reconciliation_incomplete"
        in prepared.blocker_reason_codes
    )
    assert (
        "statement_source.manifest_missing"
        in prepared.blocker_reason_codes
    )


def test_batch_accounts_for_preparation_blockers_and_queued_runs() -> None:
    blocked = PreparedTickerRun(
        context=_context("MISS", "blocked"),
        snapshot=None,
        blocker_reason_codes=("preparation.statement_source_missing",),
    )
    queued = PreparedTickerRun(
        context=_context("GOOD", "provisional"),
        snapshot=SimpleNamespace(snapshot_hash="snapshot:GOOD"),
    )

    def judgment_runner(**kwargs):
        return SimpleNamespace(
            status="queued",
            snapshot_hash="snapshot:GOOD",
            queue_item_ids={
                family: index
                for index, family in enumerate(DriverFamily, start=1)
            },
            blocker_reasons={},
            model_change_request_ids={},
        )

    manifest = run_valuation_workup_batch(
        [blocked, queued],
        bindings={},
        connection_factory=lambda: sqlite3.connect(":memory:"),
        judgment_runner=judgment_runner,
        max_workers=2,
    )

    assert manifest.unique_count == 2
    assert {record.context.identity.ticker for record in manifest.records} == {
        "GOOD",
        "MISS",
    }
    assert {
        record.context.identity.ticker: record.status
        for record in manifest.records
    } == {
        "GOOD": TerminalStatus.provisional,
        "MISS": TerminalStatus.blocked,
    }


def test_batch_deduplicates_exact_repeated_ticker_contexts() -> None:
    prepared = PreparedTickerRun(
        context=_context("SAME", "provisional"),
        snapshot=SimpleNamespace(snapshot_hash="snapshot:SAME"),
    )
    provider_calls = []

    def judgment_runner(**kwargs):
        provider_calls.append(kwargs["snapshot"].snapshot_hash)
        return SimpleNamespace(
            status="queued",
            snapshot_hash="snapshot:SAME",
            queue_item_ids={
                family: index
                for index, family in enumerate(DriverFamily, start=1)
            },
            blocker_reasons={},
            model_change_request_ids={},
        )

    manifest = run_valuation_workup_batch(
        [prepared, prepared],
        bindings={},
        connection_factory=lambda: sqlite3.connect(":memory:"),
        judgment_runner=judgment_runner,
    )

    assert manifest.requested_count == 2
    assert manifest.unique_count == 1
    assert manifest.duplicate_count == 1
    assert len(manifest.records) == 1
    assert provider_calls == ["snapshot:SAME"]


def test_heterogeneous_universe_exit_contract_has_no_dropped_names() -> None:
    blocked_reasons = {
        "CALM": "source.presentation_xbrl_missing",
        "IBM": "source.ciq_template_incompatible",
        "BAH": "source.statement_manifests_missing",
        "LYFT": "readiness.history_insufficient",
        "IESC": "source.authoritative_statements_missing",
    }
    prepared = [
        PreparedTickerRun(
            context=_context(ticker, "blocked"),
            snapshot=None,
            blocker_reason_codes=(reason,),
        )
        for ticker, reason in blocked_reasons.items()
    ]
    prepared.append(
        PreparedTickerRun(
            context=_context("MSFT", "provisional"),
            snapshot=SimpleNamespace(snapshot_hash="snapshot:MSFT"),
        )
    )
    provider_calls: list[str] = []

    def judgment_runner(**kwargs):
        provider_calls.append(kwargs["snapshot"].snapshot_hash)
        return SimpleNamespace(
            status="queued",
            snapshot_hash="snapshot:MSFT",
            queue_item_ids={
                family: index
                for index, family in enumerate(DriverFamily, start=1)
            },
            blocker_reasons={},
            model_change_request_ids={},
        )

    manifest = run_valuation_workup_batch(
        prepared,
        bindings={},
        connection_factory=lambda: sqlite3.connect(":memory:"),
        judgment_runner=judgment_runner,
        max_workers=3,
        max_in_flight=3,
    )

    assert manifest.requested_count == 6
    assert manifest.unique_count == 6
    assert len(manifest.records) == 6
    assert provider_calls == ["snapshot:MSFT"]
    by_ticker = {
        record.context.identity.ticker: record
        for record in manifest.records
    }
    assert set(by_ticker) == {
        "MSFT",
        "CALM",
        "IBM",
        "BAH",
        "LYFT",
        "IESC",
    }
    assert by_ticker["MSFT"].status == TerminalStatus.provisional
    for ticker, reason in blocked_reasons.items():
        record = by_ticker[ticker]
        assert record.status == TerminalStatus.blocked
        assert reason in record.reason_detail


def test_official_valuation_path_contains_no_symbol_specific_finance_branch() -> None:
    from pathlib import Path

    official_path = (
        "src/stage_04_pipeline/ticker_valuation_execution.py",
        "src/stage_04_pipeline/operating_reconciliation_service.py",
        "src/stage_04_pipeline/statement_reconciliation_service.py",
        "src/stage_04_pipeline/analysis_snapshot_builder.py",
        "src/stage_04_pipeline/valuation_judgment_pipeline.py",
        "src/stage_02_valuation/approved_case_replay.py",
    )
    for relative_path in official_path:
        source = Path(relative_path).read_text(encoding="utf-8")
        for symbol in ("MSFT", "IBM", "CALM"):
            assert f'"{symbol}"' not in source
            assert f"'{symbol}'" not in source


def test_preparation_compiles_and_persists_exact_approved_replay(
    monkeypatch,
) -> None:
    from src.stage_04_pipeline import ticker_valuation_execution as execution

    @dataclass(frozen=True)
    class SourceReadiness:
        status: str = "pass"

    @dataclass(frozen=True)
    class StatementReadiness:
        status: str = "decision_grade"
        annual_period_count: int = 5
        ltm_status: str = "compatible"
        source_reconciliation: SourceReadiness = SourceReadiness()

    statement_run = SimpleNamespace(
        ticker="TEST",
        run_hash="statement-run",
        raw_ledger_hash="raw-ledger",
        selected_view_hash="selected-view",
        manifest_ids=("manifest:xbrl", "manifest:ciq"),
        selected_fact_ids=("fact:1",),
        persisted_queue_item_ids=(),
        readiness=StatementReadiness(),
    )
    operating = SimpleNamespace(
        status="reconciled",
        fingerprint="operating",
        result=SimpleNamespace(unresolved_clamp_count=0),
        to_dict=lambda: {"fingerprint": "operating"},
    )
    snapshot = SimpleNamespace(
        snapshot_hash="snapshot:TEST",
        statement_reconciliation={
            "status": "decision_grade",
            "source_reconciliation": {"status": "pass"},
            "pending_material_disagreement_count": 0,
        },
        claim_ledger={
            "fingerprint": "claim",
            "reconciliation": {"is_decision_grade": True},
        },
        approved_treatments=({"decision_id": "treatment:1"},),
        comps_inputs={
            "peer": {"ev_ebitda": 12.0},
            "similarity_scores": {"peer": 0.9},
        },
        market_inputs={
            "base_drivers": {"revenue_base": 100.0},
            "valuation_policy": {
                "scenario_probabilities": {
                    "bear": 0.2,
                    "base": 0.6,
                    "bull": 0.2,
                }
            },
        },
        source_fingerprints={
            "xbrl": "xbrl-fingerprint",
            "ciq": "ciq-fingerprint",
        },
    )
    valuation_inputs = SimpleNamespace(
        model_applicability_status="dcf_applicable",
    )
    packs = tuple(
        _FakeApprovedPack(family=family) for family in DriverFamily
    )
    expected_hashes = {
        pack.family: canonical_semantic_hash(pack) for pack in packs
    }
    approval_fingerprints = tuple(
        f"approval:{family.value}" for family in DriverFamily
    )
    calls: dict[str, object] = {}

    def load_bundle(conn, *, snapshot):
        calls["loaded_snapshot"] = snapshot
        return packs, approval_fingerprints, "prompt:approved"

    def compile_case(**kwargs):
        calls["compile"] = kwargs
        return SimpleNamespace(replay_key="replay:approved")

    approved_result = SimpleNamespace(
        replay_key="replay:approved",
        output_hash="output:approved",
        trust_status="decision_grade",
    )

    def replay_case(case):
        calls["replayed_case"] = case
        return approved_result

    def persist_replay(conn, *, case, result):
        calls["persisted"] = (case, result)
        return case.replay_key

    def snapshot_builder(**kwargs):
        calls["snapshot_builder"] = kwargs
        return snapshot

    monkeypatch.setattr(
        execution,
        "load_approved_family_bundle",
        load_bundle,
        raising=False,
    )
    monkeypatch.setattr(
        execution,
        "compile_approved_valuation_case",
        compile_case,
        raising=False,
    )
    monkeypatch.setattr(
        execution,
        "replay_approved_valuation_case",
        replay_case,
        raising=False,
    )
    monkeypatch.setattr(
        execution,
        "persist_approved_valuation_replay",
        persist_replay,
        raising=False,
    )
    monkeypatch.setattr(
        execution,
        "ForecastDrivers",
        lambda **values: ("drivers", values),
        raising=False,
    )

    prepared = prepare_ticker_run(
        object(),
        "test",
        analysis_as_of=date(2026, 7, 26),
        captured_at="2026-07-26T10:00:00+00:00",
        evidence={"filing": {"id": "10-k"}},
        upstream_context={
            "business": {"summary": "business"},
            "industry": {"summary": "industry"},
        },
        comps_inputs=snapshot.comps_inputs,
        valuation_policy=snapshot.market_inputs["valuation_policy"],
        approved_treatments=snapshot.approved_treatments,
        statement_reconciler=lambda *args, **kwargs: statement_run,
        input_builder=lambda *args, **kwargs: valuation_inputs,
        operating_reconciler=lambda *args, **kwargs: operating,
        snapshot_builder=snapshot_builder,
    )

    assert prepared.blocker_reason_codes == ()
    assert prepared.approved_replay is approved_result
    assert prepared.context.readiness.approved_family_hashes == expected_hashes
    assert prepared.context.readiness.trust_status.value == "decision_grade"
    assert (
        prepared.context.replay_inputs.approved_case_replay_fingerprint
        == "replay:approved"
    )
    assert calls["loaded_snapshot"] is snapshot
    compile_kwargs = calls["compile"]
    assert compile_kwargs["approved_packs"] == packs
    assert compile_kwargs["approval_fingerprints"] == approval_fingerprints
    assert compile_kwargs["readiness"] is prepared.context.readiness
    assert compile_kwargs["comps_similarity_scores"] == {"peer": 0.9}
    assert (
        prepared.context.readiness.statement_reconciliation_hash
        == canonical_semantic_hash(snapshot.statement_reconciliation)
    )
    assert (
        prepared.context.readiness.source_reconciliation_hash
        == canonical_semantic_hash(snapshot.source_fingerprints)
    )
    component_versions = calls["snapshot_builder"]["component_versions"]
    assert (
        component_versions["dcf_engine_fingerprint"]
        == execution.DCF_ENGINE_FINGERPRINT
    )
    assert (
        component_versions["comps_engine_fingerprint"]
        == execution.COMPS_ENGINE_FINGERPRINT
    )
    assert (
        component_versions["bridge_engine_fingerprint"]
        == execution.BRIDGE_ENGINE_FINGERPRINT
    )
    assert calls["persisted"][1] is approved_result
