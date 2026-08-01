"""Bounded, ticker-independent orchestration for valuation runs."""

from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from collections.abc import Callable, Iterable, Mapping
import math
from threading import Event
import time
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.contracts.ticker_runs import (
    EligibilityStatus,
    RetryPolicy,
    TerminalStatus,
    TickerRunContext,
    TickerTerminalRecord,
    canonical_hash,
)


class DeadlineAwareTickerCallable(Protocol):
    """Ticker worker contract for bounded execution.

    Implementations must propagate the supplied timeout, raise
    ``ConnectionError`` or ``TimeoutError`` for transient transport failures,
    and translate permanent failures to any other exception (or a blocked
    terminal record).
    """

    def __call__(
        self,
        context: TickerRunContext,
        *,
        transport_timeout_seconds: float,
    ) -> TickerTerminalRecord: ...


class TickerBatchManifest(BaseModel):
    """Deterministically ordered terminal records for one batch request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    records: tuple[TickerTerminalRecord, ...]
    requested_count: int = Field(ge=0)
    unique_count: int = Field(ge=0)
    duplicate_count: int = Field(ge=0)
    executed_count: int = Field(ge=0)
    resumed_count: int = Field(ge=0)
    preterminated_count: int = Field(ge=0)

    @model_validator(mode="after")
    def _counts_and_records_reconcile(self) -> "TickerBatchManifest":
        if self.requested_count != self.unique_count + self.duplicate_count:
            raise ValueError(
                "requested_count must equal unique_count + duplicate_count"
            )
        if len(self.records) != self.unique_count:
            raise ValueError("manifest requires one terminal record per unique ticker")
        if self.unique_count != (
            self.executed_count
            + self.resumed_count
            + self.preterminated_count
        ):
            raise ValueError(
                "unique_count must reconcile to executed, resumed, and "
                "preterminated counts"
            )
        identity_keys = tuple(
            record.context.identity.canonical_key
            for record in self.records
        )
        if len(set(identity_keys)) != len(identity_keys):
            raise ValueError("manifest terminal identities must be unique")
        sort_keys = tuple(
            record.context.identity.sort_key
            for record in self.records
        )
        if sort_keys != tuple(sorted(sort_keys)):
            raise ValueError("manifest records must use deterministic ordering")
        return self


def run_ticker_batch(
    requests: Iterable[TickerRunContext],
    run_ticker: DeadlineAwareTickerCallable,
    *,
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
) -> TickerBatchManifest:
    """Execute each canonical ticker once and return ordered terminal records.

    ``run_ticker`` must propagate ``transport_timeout_seconds`` to every remote
    call and must not persist results itself. The coordinator may abandon an
    uncooperative worker after the batch deadline; the checkpoint callback is
    therefore the sole persistence boundary and must replace one ticker record
    atomically.
    """

    if max_workers < 1:
        raise ValueError("max_workers must be at least one")
    effective_max_in_flight = (
        max_workers if max_in_flight is None else max_in_flight
    )
    if effective_max_in_flight < 1:
        raise ValueError("max_in_flight must be at least one")
    if (
        not math.isfinite(transport_timeout_seconds)
        or transport_timeout_seconds <= 0
    ):
        raise ValueError("transport_timeout_seconds must be finite and positive")
    if not math.isfinite(batch_timeout_seconds) or batch_timeout_seconds <= 0:
        raise ValueError("batch_timeout_seconds must be finite and positive")
    lane_limits: dict[str, int] = {}
    for raw_lane, limit in (provider_lane_limits or {}).items():
        if not isinstance(raw_lane, str):
            raise ValueError("provider lane names must be strings")
        lane = raw_lane.strip()
        if (
            not lane
            or isinstance(limit, bool)
            or not isinstance(limit, int)
            or limit < 1
        ):
            raise ValueError(
                "provider lane limits require names and positive integers"
            )
        if lane in lane_limits and lane_limits[lane] != limit:
            raise ValueError("provider lane limits conflict after normalization")
        lane_limits[lane] = limit
    batch_deadline = time.monotonic() + batch_timeout_seconds

    requested = tuple(requests)
    contexts_by_key: dict[str, dict[str, TickerRunContext]] = {}
    for context in requested:
        variants = contexts_by_key.setdefault(context.identity.canonical_key, {})
        variants.setdefault(context.context_fingerprint, context)

    contexts = tuple(
        next(iter(contexts_by_key[key].values()))
        for key in sorted(contexts_by_key)
        if len(contexts_by_key[key]) == 1
    )
    conflict_records = tuple(
        TickerTerminalRecord(
            context=contexts_by_key[key][min(contexts_by_key[key])],
            status=TerminalStatus.blocked,
            reason_code="runner.conflicting_request_context",
            reason_detail=(
                f"{len(contexts_by_key[key])} distinct frozen contexts"
            ),
            retryable=False,
            model_change_request=contexts_by_key[key][
                min(contexts_by_key[key])
            ].model_change_request,
            attempt_count=0,
        )
        for key in sorted(contexts_by_key)
        if len(contexts_by_key[key]) > 1
    )
    prior_variants: dict[str, dict[str, TickerTerminalRecord]] = {}
    for record in prior_records:
        variants = prior_variants.setdefault(
            record.context.context_fingerprint,
            {},
        )
        checkpoint_fingerprint = record.checkpoint_fingerprint
        existing = variants.get(checkpoint_fingerprint)
        if (
            existing is None
            or canonical_hash(record) < canonical_hash(existing)
        ):
            variants[checkpoint_fingerprint] = record
    stable_prior_variants = {
        context_fingerprint: {
            record_hash: record
            for record_hash, record in variants.items()
            if not record.retryable
        }
        for context_fingerprint, variants in prior_variants.items()
    }
    prior_by_context = {
        context_fingerprint: next(iter(variants.values()))
        for context_fingerprint, variants in stable_prior_variants.items()
        if len(variants) == 1
    }
    conflicting_prior_contexts = {
        context_fingerprint
        for context_fingerprint, variants in stable_prior_variants.items()
        if len(variants) > 1
    }
    prior_conflict_records = tuple(
        TickerTerminalRecord(
            context=context,
            status=TerminalStatus.blocked,
            reason_code="runner.conflicting_prior_records",
            reason_detail=(
                f"{len(stable_prior_variants[context.context_fingerprint])} "
                "distinct terminal records"
            ),
            retryable=False,
            model_change_request=context.model_change_request,
            attempt_count=0,
        )
        for context in contexts
        if context.context_fingerprint in conflicting_prior_contexts
    )
    resumed_records = tuple(
        prior_by_context[context.context_fingerprint]
        for context in contexts
        if context.context_fingerprint in prior_by_context
    )
    remaining = tuple(
        context
        for context in contexts
        if (
            context.context_fingerprint not in prior_by_context
            and context.context_fingerprint not in conflicting_prior_contexts
        )
    )
    eligible = tuple(
        context
        for context in remaining
        if context.eligibility == EligibilityStatus.supported_v1
    )
    ineligible_records = tuple(
        TickerTerminalRecord(
            context=context,
            status=TerminalStatus.blocked,
            reason_code=context.eligibility_reason_code
            or "eligibility.unsupported_model",
            retryable=False,
            model_change_request=context.model_change_request,
            attempt_count=0,
        )
        for context in remaining
        if context.eligibility == EligibilityStatus.unsupported_model
    )
    resolve_lane = provider_lane or (lambda _: "default")
    runnable: list[tuple[TickerRunContext, str]] = []
    lane_failure_records: list[TickerTerminalRecord] = []
    for context in eligible:
        try:
            lane = resolve_lane(context).strip()
            if not lane:
                raise ValueError("provider lane must not be empty")
        except Exception as exc:
            lane_failure_records.append(
                TickerTerminalRecord(
                    context=context,
                    status=TerminalStatus.blocked,
                    reason_code="runner.provider_lane_resolution_failed",
                    reason_detail=type(exc).__name__,
                    retryable=False,
                    attempt_count=0,
                )
            )
        else:
            runnable.append((context, lane))
    checkpointed_preterminal_records = tuple(
        _checkpoint_record(record, checkpoint_callback)
        for record in (
            *conflict_records,
            *prior_conflict_records,
            *ineligible_records,
            *lane_failure_records,
        )
    )
    executed_records: list[TickerTerminalRecord] = []
    executor = ThreadPoolExecutor(max_workers=max_workers)
    pending = list(runnable)
    futures: dict[
        Future[TickerTerminalRecord],
        tuple[TickerRunContext, str],
    ] = {}
    lane_in_flight: dict[str, int] = {}
    submitted_context_keys: set[str] = set()
    unscheduled_deadline_count = 0
    deadline_exceeded = False
    deadline_stop = Event()

    def submit_until_capacity() -> None:
        while len(futures) < effective_max_in_flight:
            selected_index: int | None = None
            for index, (_, lane) in enumerate(pending):
                limit = lane_limits.get(lane, max_workers)
                if lane_in_flight.get(lane, 0) < limit:
                    selected_index = index
                    break
            if selected_index is None:
                return
            context, lane = pending.pop(selected_index)
            future = executor.submit(
                _run_with_retry,
                context,
                run_ticker,
                retry_policy,
                transport_timeout_seconds,
                batch_deadline,
                lane,
                rate_limiter,
                deadline_stop,
            )
            futures[future] = (context, lane)
            lane_in_flight[lane] = lane_in_flight.get(lane, 0) + 1
            submitted_context_keys.add(context.context_fingerprint)

    submit_until_capacity()
    while futures:
        remaining_seconds = batch_deadline - time.monotonic()
        if remaining_seconds <= 0:
            deadline_exceeded = True
            break
        completed, _ = wait(
            futures,
            timeout=remaining_seconds,
            return_when=FIRST_COMPLETED,
        )
        if not completed:
            deadline_exceeded = True
            break
        for future in completed:
            context, lane = futures.pop(future)
            lane_in_flight[lane] -= 1
            try:
                result = future.result()
            except Exception as exc:
                result = TickerTerminalRecord(
                    context=context,
                    status=TerminalStatus.blocked,
                    reason_code="runner.permanent_exception",
                    reason_detail=type(exc).__name__,
                    retryable=False,
                )
            executed_records.append(
                _checkpoint_record(result, checkpoint_callback)
            )
        submit_until_capacity()

    if deadline_exceeded:
        deadline_stop.set()
        timed_out_records: list[TickerTerminalRecord] = []
        for future, (context, _) in sorted(
            futures.items(),
            key=lambda item: item[1][0].identity.sort_key,
        ):
            attempt_count = 1 if future.running() else 0
            future.cancel()
            timed_out_records.append(
                TickerTerminalRecord(
                    context=context,
                    status=TerminalStatus.blocked,
                    reason_code="runner.scheduler_deadline_exceeded",
                    retryable=True,
                    attempt_count=attempt_count,
                )
            )
        unscheduled_deadline_count = len(pending)
        timed_out_records.extend(
            TickerTerminalRecord(
                context=context,
                status=TerminalStatus.blocked,
                reason_code="runner.scheduler_deadline_exceeded",
                retryable=True,
                attempt_count=0,
            )
            for context, _ in pending
        )
        executed_records.extend(
            _checkpoint_record(record, checkpoint_callback)
            for record in timed_out_records
        )
        executor.shutdown(wait=False, cancel_futures=True)
    else:
        executor.shutdown(wait=True)

    ordered_records = tuple(
        sorted(
            (
                *checkpointed_preterminal_records,
                *resumed_records,
                *executed_records,
            ),
            key=lambda row: row.context.identity.sort_key,
        )
    )
    return TickerBatchManifest(
        records=ordered_records,
        requested_count=len(requested),
        unique_count=len(contexts_by_key),
        duplicate_count=len(requested) - len(contexts_by_key),
        executed_count=len(submitted_context_keys),
        resumed_count=len(resumed_records),
        preterminated_count=(
            len(conflict_records)
            + len(prior_conflict_records)
            + len(ineligible_records)
            + len(lane_failure_records)
            + unscheduled_deadline_count
        ),
    )


def _run_with_retry(
    context: TickerRunContext,
    run_ticker: DeadlineAwareTickerCallable,
    retry_policy: RetryPolicy,
    transport_timeout_seconds: float,
    batch_deadline: float,
    provider_lane: str,
    rate_limiter: Callable[[str, TickerRunContext], None] | None,
    deadline_stop: Event,
) -> TickerTerminalRecord:
    for attempt_number in range(1, retry_policy.max_attempts + 1):
        remaining_seconds = batch_deadline - time.monotonic()
        if deadline_stop.is_set() or remaining_seconds <= 0:
            return TickerTerminalRecord(
                context=context,
                status=TerminalStatus.blocked,
                reason_code="runner.scheduler_deadline_exceeded",
                retryable=True,
                attempt_count=attempt_number - 1,
            )
        try:
            if rate_limiter is not None:
                rate_limiter(provider_lane, context)
            remaining_seconds = batch_deadline - time.monotonic()
            if deadline_stop.is_set() or remaining_seconds <= 0:
                return TickerTerminalRecord(
                    context=context,
                    status=TerminalStatus.blocked,
                    reason_code="runner.scheduler_deadline_exceeded",
                    retryable=True,
                    attempt_count=attempt_number,
                )
            result = run_ticker(
                context,
                transport_timeout_seconds=min(
                    transport_timeout_seconds,
                    remaining_seconds,
                ),
            )
        except Exception as exc:
            retryable = isinstance(exc, (ConnectionError, TimeoutError))
            result = TickerTerminalRecord(
                context=context,
                status=TerminalStatus.blocked,
                reason_code=(
                    "runner.transient_exception"
                    if retryable
                    else "runner.permanent_exception"
                ),
                reason_detail=type(exc).__name__,
                retryable=retryable,
                attempt_count=attempt_number,
            )
        else:
            if not isinstance(result, TickerTerminalRecord):
                result = TickerTerminalRecord(
                    context=context,
                    status=TerminalStatus.blocked,
                    reason_code="runner.invalid_terminal_record",
                    reason_detail=type(result).__name__,
                    retryable=False,
                    attempt_count=attempt_number,
                )
            elif (
                result.context.context_fingerprint
                != context.context_fingerprint
            ):
                result = TickerTerminalRecord(
                    context=context,
                    status=TerminalStatus.blocked,
                    reason_code="runner.result_context_mismatch",
                    retryable=False,
                    attempt_count=attempt_number,
                )
            else:
                result = result.model_copy(
                    update={"attempt_count": attempt_number}
                )

        if not result.retryable or attempt_number == retry_policy.max_attempts:
            return result

    raise AssertionError("retry loop exhausted without a terminal record")


def _checkpoint_record(
    record: TickerTerminalRecord,
    checkpoint_callback: Callable[[TickerTerminalRecord], None] | None,
) -> TickerTerminalRecord:
    """Invoke one caller-owned atomic checkpoint after terminal completion."""

    if checkpoint_callback is None:
        return record
    try:
        checkpoint_callback(record)
    except Exception as exc:
        return TickerTerminalRecord(
            context=record.context,
            status=TerminalStatus.blocked,
            reason_code="runner.checkpoint_failed",
            reason_detail=type(exc).__name__,
            retryable=True,
            model_change_request=record.context.model_change_request,
            attempt_count=record.attempt_count,
        )
    return record
