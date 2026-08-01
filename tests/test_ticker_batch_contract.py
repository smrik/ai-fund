from __future__ import annotations

from datetime import date
from threading import Event, Lock, Thread
import time

import pytest

from src.contracts.ticker_runs import (
    EligibilityStatus,
    ReplayInputFingerprints,
    REASON_CODE_REGISTRY,
    RetryPolicy,
    SourceFingerprint,
    TerminalStatus,
    TickerIdentity,
    TickerRunContext,
    TickerReasonCode,
    TickerTerminalRecord,
)
from src.contracts.model_change_requests import (
    ValuationModelChangeRequest,
    build_model_change_request,
)
from src.contracts.valuation_readiness import ValuationReadinessEvidence
from src.stage_04_pipeline.ticker_batch import (
    TickerBatchManifest,
    run_ticker_batch,
)


def _readiness(**changes: object) -> ValuationReadinessEvidence:
    values: dict[str, object] = {
        "statement_reconciliation": "reconciled",
        "source_reconciliation": "reconciled",
        "claim_ledger_reconciliation": "reconciled",
        "operating_reconciliation": "reconciled",
        "annual_period_count": 5,
        "ltm_status": "compatible",
        "approved_family_hashes": {
            "revenue": "family-revenue",
            "profitability_tax": "family-profitability",
            "reinvestment_working_capital": "family-reinvestment",
            "terminal_capital_comps": "family-terminal",
        },
        "statement_reconciliation_hash": "statement-hash",
        "source_reconciliation_hash": "source-hash",
        "claim_ledger_hash": "claim-hash",
        "operating_reconciliation_hash": "operating-hash",
        "peer_set_fingerprint": "peer-set-hash",
        "treatment_set_fingerprint": "treatment-set-hash",
        "prompt_contract_fingerprint": "prompt-contract-hash",
        "dcf_engine_fingerprint": "dcf-v1",
        "comps_engine_fingerprint": "comps-v1",
        "bridge_engine_fingerprint": "bridge-v1",
    }
    values.update(changes)
    return ValuationReadinessEvidence.model_validate(values)


def _run_inputs(**updates: str) -> ReplayInputFingerprints:
    values = {
        "analysis_snapshot_hash": "snapshot:v1",
        "approved_case_replay_fingerprint": "approved-case:v1",
        "peer_universe_fingerprint": "peers:v1",
        "treatment_register_fingerprint": "treatments:v1",
        "judgment_contract_fingerprint": "judgment-contract:v1",
        "valuation_engine_fingerprint": "valuation-engine:v1",
    }
    values.update(updates)
    return ReplayInputFingerprints(**values)


def _model_change_request(
    *,
    ticker: str = "BANK",
    analysis_snapshot_hash: str = "snapshot:v1",
) -> ValuationModelChangeRequest:
    return build_model_change_request(
        ticker=ticker,
        analysis_snapshot_hash=analysis_snapshot_hash,
        category="methodology",
        current_model="fcff_dcf_comps_v1",
        required_capability="issuer-appropriate valuation methodology",
        rationale="The current valuation model is structurally unsuitable.",
        evidence_anchor_ids=("eligibility:classification",),
        evidence_fingerprints=("snapshot:v1",),
        created_at="2026-07-25T00:00:00Z",
    )


def _context(
    ticker: str,
    *,
    fingerprint: str | None = None,
    run_inputs: ReplayInputFingerprints | None = None,
    readiness: ValuationReadinessEvidence | None = None,
) -> TickerRunContext:
    normalized_ticker = ticker.strip().upper()
    return TickerRunContext(
        identity=TickerIdentity(ticker=ticker),
        analysis_as_of=date(2026, 7, 25),
        eligibility=EligibilityStatus.supported_v1,
        valuation_model="fcff_dcf_comps_v1",
        replay_inputs=run_inputs or _run_inputs(),
        readiness=readiness or _readiness(),
        source_fingerprints=(
            SourceFingerprint(
                source_id=f"sec:{normalized_ticker}:2025-10-k",
                fingerprint=fingerprint or f"sha256:{ticker.strip().lower()}",
            ),
        ),
    )


def _decision_grade(
    context: TickerRunContext,
    *,
    transport_timeout_seconds: float | None = None,
) -> TickerTerminalRecord:
    return TickerTerminalRecord(
        context=context,
        status=TerminalStatus.decision_grade,
        reason_code="valuation.completed",
        retryable=False,
        result_fingerprint=f"result:{context.identity.ticker}",
    )


def test_batch_canonicalizes_and_deduplicates_requests() -> None:
    calls: list[str] = []

    def run_one(
        context: TickerRunContext,
        *,
        transport_timeout_seconds: float,
    ) -> TickerTerminalRecord:
        calls.append(context.identity.ticker)
        return _decision_grade(context)

    manifest = run_ticker_batch(
        [_context(" msft "), _context("MSFT"), _context(" ibm")],
        run_one,
        max_workers=2,
    )

    assert calls.count("MSFT") == 1
    assert calls.count("IBM") == 1
    assert [row.context.identity.ticker for row in manifest.records] == ["IBM", "MSFT"]
    assert manifest.requested_count == 3
    assert manifest.unique_count == 2
    assert manifest.duplicate_count == 1
    assert manifest.executed_count == 2
    assert manifest.resumed_count == 0


def test_identity_key_is_structured_across_exchange_and_share_class() -> None:
    colon_left = TickerIdentity(
        ticker="B:C",
        exchange="A",
        share_class="common",
    )
    colon_right = TickerIdentity(
        ticker="C",
        exchange="A:B",
        share_class="common",
    )
    different_exchange = TickerIdentity(
        ticker="B:C",
        exchange="XNAS",
        share_class="common",
    )
    different_share_class = TickerIdentity(
        ticker="B:C",
        exchange="A",
        share_class="preferred",
    )

    assert len(
        {
            colon_left.canonical_key,
            colon_right.canonical_key,
            different_exchange.canonical_key,
            different_share_class.canonical_key,
        }
    ) == 4
    assert colon_left.share_class == "COMMON"


def test_unsupported_model_is_a_terminal_result_without_execution() -> None:
    context = TickerRunContext(
        identity=TickerIdentity(ticker="BANK"),
        analysis_as_of=date(2026, 7, 25),
        eligibility=EligibilityStatus.unsupported_model,
        eligibility_reason_code="eligibility.unsupported_model",
        valuation_model="fcff_dcf_comps_v1",
        replay_inputs=_run_inputs(),
        readiness=_readiness(),
        model_change_request=_model_change_request(),
        source_fingerprints=(),
    )

    def must_not_run(
        _: TickerRunContext,
        *,
        transport_timeout_seconds: float,
    ) -> TickerTerminalRecord:
        raise AssertionError("unsupported tickers must not enter the valuation callable")

    manifest = run_ticker_batch([context], must_not_run)

    assert manifest.executed_count == 0
    assert len(manifest.records) == 1
    record = manifest.records[0]
    assert record.context == context
    assert record.status == TerminalStatus.blocked
    assert record.reason_code == "eligibility.unsupported_model"
    assert record.retryable is False
    assert record.model_change_request == context.model_change_request


def test_conflicting_unsupported_context_keeps_a_model_change_request() -> None:
    def unsupported(snapshot_hash: str) -> TickerRunContext:
        return TickerRunContext(
            identity=TickerIdentity(ticker="BANK"),
            analysis_as_of=date(2026, 7, 25),
            eligibility=EligibilityStatus.unsupported_model,
            eligibility_reason_code="eligibility.unsupported_model",
            valuation_model="fcff_dcf_comps_v1",
            replay_inputs=_run_inputs(
                analysis_snapshot_hash=snapshot_hash,
            ),
            readiness=_readiness(),
            model_change_request=_model_change_request(
                analysis_snapshot_hash=snapshot_hash,
            ),
            source_fingerprints=(),
        )

    manifest = run_ticker_batch(
        [unsupported("snapshot:v1"), unsupported("snapshot:v2")],
        _decision_grade,
    )

    assert len(manifest.records) == 1
    assert manifest.records[0].reason_code == (
        "runner.conflicting_request_context"
    )
    assert manifest.records[0].model_change_request is not None


def test_manifest_counts_reconcile_and_missing_terminal_rows_are_rejected() -> None:
    supported = _context("IBM")
    unsupported = TickerRunContext(
        identity=TickerIdentity(ticker="BANK"),
        analysis_as_of=date(2026, 7, 25),
        eligibility=EligibilityStatus.unsupported_model,
        eligibility_reason_code="eligibility.unsupported_model",
        valuation_model="fcff_dcf_comps_v1",
        replay_inputs=_run_inputs(),
        readiness=_readiness(),
        model_change_request=_model_change_request(),
        source_fingerprints=(),
    )

    manifest = run_ticker_batch(
        [supported, _context(" ibm "), unsupported],
        _decision_grade,
    )

    assert len(manifest.records) == manifest.unique_count == 2
    assert manifest.requested_count == (
        manifest.unique_count + manifest.duplicate_count
    )
    assert manifest.unique_count == (
        manifest.executed_count
        + manifest.resumed_count
        + manifest.preterminated_count
    )

    with pytest.raises(
        ValueError,
        match="one terminal record per unique ticker",
    ):
        TickerBatchManifest(
            records=manifest.records[:1],
            requested_count=manifest.requested_count,
            unique_count=manifest.unique_count,
            duplicate_count=manifest.duplicate_count,
            executed_count=manifest.executed_count,
            resumed_count=manifest.resumed_count,
            preterminated_count=manifest.preterminated_count,
        )


def test_terminal_reason_codes_come_from_the_closed_registry() -> None:
    assert REASON_CODE_REGISTRY == {
        reason.value
        for reason in TickerReasonCode
    }
    with pytest.raises(ValueError, match="Input should be"):
        TickerTerminalRecord(
            context=_context("IBM"),
            status=TerminalStatus.blocked,
            reason_code="runner.ad_hoc_message",
            retryable=False,
        )


def test_100_tickers_finish_out_of_order_without_silent_drops() -> None:
    contexts = [_context(f"t{index:03d}") for index in range(100)]
    lock = Lock()
    active = 0
    peak_active = 0
    start_order: list[str] = []
    completion_order: list[str] = []

    def run_one(
        context: TickerRunContext,
        *,
        transport_timeout_seconds: float,
    ) -> TickerTerminalRecord:
        nonlocal active, peak_active
        with lock:
            start_position = len(start_order)
            start_order.append(context.identity.ticker)
            active += 1
            peak_active = max(peak_active, active)
        try:
            time.sleep((6 - (start_position % 7)) * 0.0005)
            if context.identity.ticker == "T042":
                raise ConnectionError("provider unavailable")
            return _decision_grade(context)
        finally:
            with lock:
                active -= 1
                completion_order.append(context.identity.ticker)

    manifest = run_ticker_batch(
        contexts,
        run_one,
        max_workers=7,
        retry_policy=RetryPolicy(max_attempts=1),
    )

    tickers = [row.context.identity.ticker for row in manifest.records]
    assert tickers == [f"T{index:03d}" for index in range(100)]
    assert completion_order != start_order
    assert 1 < peak_active <= 7
    assert len(manifest.records) == 100
    assert manifest.executed_count == 100

    failure = manifest.records[42]
    assert failure.context.identity.ticker == "T042"
    assert failure.status == TerminalStatus.blocked
    assert failure.reason_code == "runner.transient_exception"
    assert failure.retryable is True
    assert failure.reason_detail == "ConnectionError"
    assert all(
        row.status == TerminalStatus.decision_grade
        for index, row in enumerate(manifest.records)
        if index != 42
    )


def test_transient_failure_retries_but_permanent_failure_does_not() -> None:
    transient = _context("TRANSIENT")
    permanent = _context("PERMANENT")
    attempts = {"TRANSIENT": 0, "PERMANENT": 0}

    def run_one(
        context: TickerRunContext,
        *,
        transport_timeout_seconds: float,
    ) -> TickerTerminalRecord:
        ticker = context.identity.ticker
        attempts[ticker] += 1
        if ticker == "TRANSIENT" and attempts[ticker] == 1:
            raise ConnectionError("temporary provider outage")
        if ticker == "PERMANENT":
            raise ValueError("invalid deterministic input")
        return _decision_grade(context)

    manifest = run_ticker_batch(
        [transient, permanent],
        run_one,
        retry_policy=RetryPolicy(max_attempts=3),
    )
    by_ticker = {
        record.context.identity.ticker: record
        for record in manifest.records
    }

    assert attempts == {"TRANSIENT": 2, "PERMANENT": 1}
    assert by_ticker["TRANSIENT"].status == TerminalStatus.decision_grade
    assert by_ticker["TRANSIENT"].attempt_count == 2
    assert by_ticker["PERMANENT"].status == TerminalStatus.blocked
    assert by_ticker["PERMANENT"].reason_code == "runner.permanent_exception"
    assert by_ticker["PERMANENT"].retryable is False
    assert by_ticker["PERMANENT"].attempt_count == 1


def test_transport_deadline_is_passed_to_every_attempt() -> None:
    observed_timeouts: list[float] = []

    def run_one(
        context: TickerRunContext,
        *,
        transport_timeout_seconds: float,
    ) -> TickerTerminalRecord:
        observed_timeouts.append(transport_timeout_seconds)
        return _decision_grade(context)

    manifest = run_ticker_batch(
        [_context("IBM")],
        run_one,
        transport_timeout_seconds=0.25,
        batch_timeout_seconds=1.0,
    )

    assert manifest.records[0].status == TerminalStatus.decision_grade
    assert len(observed_timeouts) == 1
    assert 0 < observed_timeouts[0] <= 0.25


def test_scheduler_bounds_in_flight_submissions() -> None:
    release = Event()
    capacity_reached = Event()
    lock = Lock()
    started: list[str] = []
    manifests: list[TickerBatchManifest] = []

    def run_one(
        context: TickerRunContext,
        *,
        transport_timeout_seconds: float,
    ) -> TickerTerminalRecord:
        with lock:
            started.append(context.identity.ticker)
            if len(started) == 3:
                capacity_reached.set()
        release.wait(timeout=1.0)
        return _decision_grade(context)

    scheduler = Thread(
        target=lambda: manifests.append(
            run_ticker_batch(
                [_context(f"T{index:02d}") for index in range(10)],
                run_one,
                max_workers=8,
                max_in_flight=3,
                batch_timeout_seconds=2.0,
            )
        )
    )
    scheduler.start()

    assert capacity_reached.wait(timeout=0.5)
    time.sleep(0.03)
    with lock:
        assert len(started) == 3

    release.set()
    scheduler.join(timeout=1.0)

    assert not scheduler.is_alive()
    assert len(manifests[0].records) == 10


def test_provider_lanes_and_rate_limiter_bound_each_provider() -> None:
    lock = Lock()
    active = {"provider-a": 0, "provider-b": 0}
    peaks = {"provider-a": 0, "provider-b": 0}
    rate_checks: list[tuple[str, str]] = []

    def lane_for(context: TickerRunContext) -> str:
        index = int(context.identity.ticker[1:])
        return "provider-a" if index % 2 == 0 else "provider-b"

    def rate_limiter(lane: str, context: TickerRunContext) -> None:
        with lock:
            rate_checks.append((lane, context.identity.ticker))

    def run_one(
        context: TickerRunContext,
        *,
        transport_timeout_seconds: float,
    ) -> TickerTerminalRecord:
        lane = lane_for(context)
        with lock:
            active[lane] += 1
            peaks[lane] = max(peaks[lane], active[lane])
        try:
            time.sleep(0.003)
            return _decision_grade(context)
        finally:
            with lock:
                active[lane] -= 1

    contexts = [_context(f"T{index:02d}") for index in range(12)]
    manifest = run_ticker_batch(
        contexts,
        run_one,
        max_workers=4,
        max_in_flight=4,
        provider_lane=lane_for,
        provider_lane_limits={"provider-a": 1, "provider-b": 2},
        rate_limiter=rate_limiter,
    )

    assert len(manifest.records) == 12
    assert peaks == {"provider-a": 1, "provider-b": 2}
    assert sorted(ticker for _, ticker in rate_checks) == [
        f"T{index:02d}" for index in range(12)
    ]
    assert all(lane == lane_for(_context(ticker)) for lane, ticker in rate_checks)


def test_provider_lane_resolution_failure_is_isolated_to_one_ticker() -> None:
    calls: list[str] = []

    def lane_for(context: TickerRunContext) -> str:
        if context.identity.ticker == "BAD":
            raise LookupError("route missing")
        return "provider-a"

    def run_one(
        context: TickerRunContext,
        *,
        transport_timeout_seconds: float,
    ) -> TickerTerminalRecord:
        calls.append(context.identity.ticker)
        return _decision_grade(context)

    manifest = run_ticker_batch(
        [_context("GOOD"), _context("BAD")],
        run_one,
        provider_lane=lane_for,
    )
    by_ticker = {
        record.context.identity.ticker: record
        for record in manifest.records
    }

    assert calls == ["GOOD"]
    assert by_ticker["GOOD"].status == TerminalStatus.decision_grade
    assert by_ticker["BAD"].status == TerminalStatus.blocked
    assert (
        by_ticker["BAD"].reason_code
        == "runner.provider_lane_resolution_failed"
    )
    assert by_ticker["BAD"].retryable is False


def test_completed_tickers_checkpoint_atomically_once_and_resumes_do_not() -> None:
    resumed_context = _context("T00")
    runnable = [_context("T01"), _context("T02")]
    attempts = {"T01": 0, "T02": 0}
    checkpointed: list[tuple[str, str]] = []

    def run_one(
        context: TickerRunContext,
        *,
        transport_timeout_seconds: float,
    ) -> TickerTerminalRecord:
        ticker = context.identity.ticker
        attempts[ticker] += 1
        if ticker == "T01" and attempts[ticker] == 1:
            raise TimeoutError("retry once")
        return _decision_grade(context)

    def checkpoint(record: TickerTerminalRecord) -> None:
        checkpointed.append(
            (
                record.context.identity.ticker,
                record.checkpoint_fingerprint,
            )
        )

    manifest = run_ticker_batch(
        [resumed_context, *runnable],
        run_one,
        prior_records=[_decision_grade(resumed_context)],
        retry_policy=RetryPolicy(max_attempts=2),
        checkpoint_callback=checkpoint,
    )

    assert len(manifest.records) == 3
    assert attempts == {"T01": 2, "T02": 1}
    assert sorted(ticker for ticker, _ in checkpointed) == ["T01", "T02"]
    assert len({fingerprint for _, fingerprint in checkpointed}) == 2


def test_checkpoint_failure_becomes_retryable_without_aborting_batch() -> None:
    def checkpoint(record: TickerTerminalRecord) -> None:
        if record.context.identity.ticker == "BAD":
            raise OSError("atomic replace failed")

    manifest = run_ticker_batch(
        [_context("GOOD"), _context("BAD")],
        _decision_grade,
        checkpoint_callback=checkpoint,
    )
    by_ticker = {
        record.context.identity.ticker: record
        for record in manifest.records
    }

    assert by_ticker["GOOD"].status == TerminalStatus.decision_grade
    assert by_ticker["BAD"].status == TerminalStatus.blocked
    assert by_ticker["BAD"].reason_code == "runner.checkpoint_failed"
    assert by_ticker["BAD"].retryable is True


def test_scheduler_deadline_returns_without_waiting_for_hung_transport() -> None:
    release = Event()
    observed_timeouts: list[float] = []

    def hung_transport(
        context: TickerRunContext,
        *,
        transport_timeout_seconds: float,
    ) -> TickerTerminalRecord:
        observed_timeouts.append(transport_timeout_seconds)
        release.wait(timeout=0.7)
        return _decision_grade(context)

    started_at = time.monotonic()
    manifest = run_ticker_batch(
        [_context("HUNG"), _context("QUEUED")],
        hung_transport,
        max_workers=1,
        max_in_flight=1,
        retry_policy=RetryPolicy(max_attempts=1),
        transport_timeout_seconds=0.02,
        batch_timeout_seconds=0.05,
    )
    elapsed = time.monotonic() - started_at
    release.set()

    assert elapsed < 0.25
    assert len(observed_timeouts) == 1
    assert 0 < observed_timeouts[0] <= 0.02
    assert len(manifest.records) == 2
    assert manifest.executed_count == 1
    assert manifest.preterminated_count == 1
    assert all(
        record.status == TerminalStatus.blocked
        and record.reason_code == "runner.scheduler_deadline_exceeded"
        and record.retryable
        for record in manifest.records
    )


def test_expired_rate_limit_wait_does_not_start_a_transport_call() -> None:
    limiter_started = Event()
    release_limiter = Event()
    transport_calls: list[str] = []

    def rate_limiter(_: str, __: TickerRunContext) -> None:
        limiter_started.set()
        release_limiter.wait(timeout=0.5)

    def run_one(
        context: TickerRunContext,
        *,
        transport_timeout_seconds: float,
    ) -> TickerTerminalRecord:
        transport_calls.append(context.identity.ticker)
        return _decision_grade(context)

    manifest = run_ticker_batch(
        [_context("IBM")],
        run_one,
        rate_limiter=rate_limiter,
        batch_timeout_seconds=0.04,
        transport_timeout_seconds=0.02,
    )
    assert limiter_started.is_set()
    release_limiter.set()
    time.sleep(0.03)

    assert transport_calls == []
    assert manifest.records[0].reason_code == (
        "runner.scheduler_deadline_exceeded"
    )


def test_exact_prior_terminal_record_is_resumed_without_reexecution() -> None:
    ibm = _context("IBM")
    msft = _context("MSFT")
    prior_ibm = _decision_grade(ibm)
    calls: list[str] = []

    def run_one(
        context: TickerRunContext,
        *,
        transport_timeout_seconds: float,
    ) -> TickerTerminalRecord:
        calls.append(context.identity.ticker)
        return _decision_grade(context)

    manifest = run_ticker_batch(
        [msft, ibm],
        run_one,
        prior_records=[prior_ibm],
    )

    assert calls == ["MSFT"]
    assert manifest.records == (prior_ibm, _decision_grade(msft))
    assert manifest.executed_count == 1
    assert manifest.resumed_count == 1


def test_retryable_prior_record_is_reexecuted_under_current_retry_budget() -> None:
    context = _context("IBM")
    prior = TickerTerminalRecord(
        context=context,
        status=TerminalStatus.blocked,
        reason_code="runner.transient_exception",
        retryable=True,
        reason_detail="TimeoutError",
        attempt_count=2,
    )
    calls: list[str] = []

    manifest = run_ticker_batch(
        [context],
        lambda item, *, transport_timeout_seconds: (
            calls.append(item.identity.ticker) or _decision_grade(item)
        ),
        prior_records=[prior],
        retry_policy=RetryPolicy(max_attempts=2),
    )

    assert calls == ["IBM"]
    assert manifest.resumed_count == 0
    assert manifest.executed_count == 1
    assert manifest.records[0].status == TerminalStatus.decision_grade


def test_changed_source_fingerprint_invalidates_prior_terminal_record() -> None:
    prior = _decision_grade(_context("IBM", fingerprint="sha256:old-filing"))
    current = _context("IBM", fingerprint="sha256:restated-filing")
    calls: list[TickerRunContext] = []

    def run_one(
        context: TickerRunContext,
        *,
        transport_timeout_seconds: float,
    ) -> TickerTerminalRecord:
        calls.append(context)
        return _decision_grade(context)

    manifest = run_ticker_batch(
        [current],
        run_one,
        prior_records=[prior],
    )

    assert calls == [current]
    assert manifest.records[0].context == current
    assert manifest.executed_count == 1
    assert manifest.resumed_count == 0


@pytest.mark.parametrize(
    "field_name",
    [
        "analysis_snapshot_hash",
        "approved_case_replay_fingerprint",
        "peer_universe_fingerprint",
        "treatment_register_fingerprint",
        "judgment_contract_fingerprint",
        "valuation_engine_fingerprint",
    ],
)
def test_every_replay_input_invalidates_a_prior_checkpoint(
    field_name: str,
) -> None:
    prior_context = _context("IBM")
    current_inputs = _run_inputs(**{field_name: f"{field_name}:v2"})
    current_context = _context("IBM", run_inputs=current_inputs)
    calls: list[TickerRunContext] = []

    manifest = run_ticker_batch(
        [current_context],
        lambda context, *, transport_timeout_seconds: (
            calls.append(context) or _decision_grade(context)
        ),
        prior_records=[_decision_grade(prior_context)],
    )

    assert prior_context.context_fingerprint != current_context.context_fingerprint
    assert calls == [current_context]
    assert manifest.executed_count == 1
    assert manifest.resumed_count == 0


def test_conflicting_duplicate_contexts_block_deterministically() -> None:
    first = _context("IBM", fingerprint="sha256:first")
    second = _context(" ibm ", fingerprint="sha256:second")
    calls: list[str] = []

    def run_one(
        context: TickerRunContext,
        *,
        transport_timeout_seconds: float,
    ) -> TickerTerminalRecord:
        calls.append(context.identity.ticker)
        return _decision_grade(context)

    forward = run_ticker_batch([first, second], run_one)
    reverse = run_ticker_batch([second, first], run_one)

    assert calls == []
    assert forward == reverse
    assert forward.unique_count == 1
    assert forward.duplicate_count == 1
    assert len(forward.records) == 1
    conflict = forward.records[0]
    assert conflict.status == TerminalStatus.blocked
    assert conflict.reason_code == "runner.conflicting_request_context"
    assert conflict.retryable is False


def test_callable_cannot_replace_the_requested_ticker_context() -> None:
    requested = _context("AAA")
    wrong = _context("BBB")

    manifest = run_ticker_batch(
        [requested],
        lambda _, *, transport_timeout_seconds: _decision_grade(wrong),
    )

    assert len(manifest.records) == 1
    record = manifest.records[0]
    assert record.context == requested
    assert record.status == TerminalStatus.blocked
    assert record.reason_code == "runner.result_context_mismatch"
    assert record.retryable is False


def test_unsupported_context_requires_a_stable_reason_code() -> None:
    with pytest.raises(
        ValueError,
        match="unsupported_model contexts require eligibility_reason_code",
    ):
        TickerRunContext(
            identity=TickerIdentity(ticker="BANK"),
            analysis_as_of=date(2026, 7, 25),
            eligibility=EligibilityStatus.unsupported_model,
            valuation_model="fcff_dcf_comps_v1",
            replay_inputs=_run_inputs(),
            readiness=_readiness(),
            model_change_request=_model_change_request(),
            source_fingerprints=(),
        )


def test_supported_context_requires_a_frozen_source_snapshot() -> None:
    with pytest.raises(
        ValueError,
        match="supported_v1 contexts require source_fingerprints",
    ):
        TickerRunContext(
            identity=TickerIdentity(ticker="IBM"),
            analysis_as_of=date(2026, 7, 25),
            eligibility=EligibilityStatus.supported_v1,
            valuation_model="fcff_dcf_comps_v1",
            replay_inputs=_run_inputs(),
            readiness=_readiness(),
            source_fingerprints=(),
        )


def test_frozen_snapshot_rejects_two_versions_of_the_same_source() -> None:
    with pytest.raises(
        ValueError,
        match="source_id must resolve to exactly one fingerprint",
    ):
        TickerRunContext(
            identity=TickerIdentity(ticker="IBM"),
            analysis_as_of=date(2026, 7, 25),
            eligibility=EligibilityStatus.supported_v1,
            valuation_model="fcff_dcf_comps_v1",
            replay_inputs=_run_inputs(),
            readiness=_readiness(),
            source_fingerprints=(
                SourceFingerprint(
                    source_id="sec:IBM:2025-10-k",
                    fingerprint="sha256:original",
                ),
                SourceFingerprint(
                    source_id="sec:IBM:2025-10-k",
                    fingerprint="sha256:restatement",
                ),
            ),
        )


def test_unsupported_model_cannot_be_marked_decision_grade() -> None:
    context = TickerRunContext(
        identity=TickerIdentity(ticker="BANK"),
        analysis_as_of=date(2026, 7, 25),
        eligibility=EligibilityStatus.unsupported_model,
        eligibility_reason_code="eligibility.unsupported_model",
        valuation_model="fcff_dcf_comps_v1",
        replay_inputs=_run_inputs(),
        readiness=_readiness(),
        model_change_request=_model_change_request(),
        source_fingerprints=(),
    )

    with pytest.raises(
        ValueError,
        match="unsupported_model contexts must terminate as blocked",
    ):
        TickerTerminalRecord(
            context=context,
            status=TerminalStatus.decision_grade,
            reason_code="valuation.completed",
            retryable=False,
            result_fingerprint="result:invalid",
        )


@pytest.mark.parametrize(
    "status",
    [TerminalStatus.decision_grade, TerminalStatus.provisional],
)
def test_valuation_outcome_requires_a_result_fingerprint(
    status: TerminalStatus,
) -> None:
    with pytest.raises(
        ValueError,
        match="valuation outcomes require result_fingerprint",
    ):
        TickerTerminalRecord(
            context=_context("IBM"),
            status=status,
            reason_code="valuation.completed",
            retryable=False,
        )


def test_decision_grade_is_non_retryable_and_uses_completed_reason() -> None:
    with pytest.raises(
        ValueError,
        match="decision_grade must be non-retryable",
    ):
        TickerTerminalRecord(
            context=_context("IBM"),
            status=TerminalStatus.decision_grade,
            reason_code="valuation.completed",
            retryable=True,
            result_fingerprint="result:IBM",
        )

    with pytest.raises(
        ValueError,
        match="decision_grade requires valuation.completed",
    ):
        TickerTerminalRecord(
            context=_context("IBM"),
            status=TerminalStatus.decision_grade,
            reason_code="runner.permanent_exception",
            retryable=False,
            result_fingerprint="result:IBM",
        )


def test_decision_grade_requires_shared_readiness_and_binds_checkpoint() -> None:
    ready_context = _context("IBM")
    provisional_context = _context(
        "IBM",
        readiness=_readiness(unresolved_clamp_count=1),
    )

    with pytest.raises(
        ValueError,
        match="decision_grade requires decision-grade readiness",
    ):
        _decision_grade(provisional_context)

    provisional = TickerTerminalRecord(
        context=provisional_context,
        status=TerminalStatus.provisional,
        reason_code="trust_gate.incomplete",
        retryable=True,
        result_fingerprint="result:IBM",
    )

    assert "readiness.unresolved_clamps" in provisional.reason_codes
    assert (
        provisional.checkpoint_fingerprint
        != _decision_grade(ready_context).checkpoint_fingerprint
    )


def test_hard_readiness_failure_cannot_be_labeled_provisional() -> None:
    blocked_context = _context(
        "IBM",
        readiness=_readiness(annual_period_count=2),
    )

    with pytest.raises(
        ValueError,
        match="blocked readiness requires blocked terminal status",
    ):
        TickerTerminalRecord(
            context=blocked_context,
            status=TerminalStatus.provisional,
            reason_code="trust_gate.incomplete",
            retryable=False,
            result_fingerprint="result:IBM",
        )


def test_readiness_change_invalidates_prior_checkpoint_and_preserves_reasons() -> None:
    prior = _decision_grade(_context("IBM"))
    current = _context(
        "IBM",
        readiness=_readiness(unresolved_clamp_count=1),
    )
    calls: list[str] = []

    def run_one(
        context: TickerRunContext,
        *,
        transport_timeout_seconds: float,
    ) -> TickerTerminalRecord:
        calls.append(context.identity.ticker)
        return TickerTerminalRecord(
            context=context,
            status=TerminalStatus.provisional,
            reason_code="trust_gate.incomplete",
            retryable=False,
            result_fingerprint="result:IBM:provisional",
        )

    manifest = run_ticker_batch(
        [current],
        run_one,
        prior_records=[prior],
    )

    assert calls == ["IBM"]
    assert manifest.resumed_count == 0
    assert manifest.records[0].reason_codes == (
        "trust_gate.incomplete",
        "readiness.unresolved_clamps",
    )


def test_conflicting_prior_terminal_records_do_not_resume_arbitrarily() -> None:
    context = _context("IBM")
    prior_decision_grade = _decision_grade(context)
    prior_provisional = TickerTerminalRecord(
        context=context,
        status=TerminalStatus.provisional,
        reason_code="valuation.fallback_used",
        retryable=False,
        result_fingerprint="result:provisional",
    )
    calls: list[str] = []

    manifest = run_ticker_batch(
        [context],
        lambda item, *, transport_timeout_seconds: (
            calls.append(item.identity.ticker) or _decision_grade(item)
        ),
        prior_records=[prior_provisional, prior_decision_grade],
    )

    assert calls == []
    assert manifest.executed_count == 0
    assert manifest.resumed_count == 0
    assert len(manifest.records) == 1
    conflict = manifest.records[0]
    assert conflict.context == context
    assert conflict.status == TerminalStatus.blocked
    assert conflict.reason_code == "runner.conflicting_prior_records"
    assert conflict.retryable is False


def test_operational_attempt_metadata_does_not_split_checkpoint_identity() -> None:
    context = _context("IBM")
    first = _decision_grade(context).model_copy(
        update={"attempt_count": 1}
    )
    retried = _decision_grade(context).model_copy(
        update={"attempt_count": 2}
    )
    calls: list[str] = []

    manifest = run_ticker_batch(
        [context],
        lambda item, *, transport_timeout_seconds: (
            calls.append(item.identity.ticker) or _decision_grade(item)
        ),
        prior_records=[first, retried],
    )
    reverse = run_ticker_batch(
        [context],
        lambda item, *, transport_timeout_seconds: _decision_grade(item),
        prior_records=[retried, first],
    )

    assert calls == []
    assert manifest.resumed_count == 1
    assert manifest == reverse
    assert manifest.records[0].checkpoint_fingerprint == (
        first.checkpoint_fingerprint
    )
