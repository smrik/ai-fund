from __future__ import annotations

import sqlite3

import pytest

from db.schema import create_tables, get_connection
from src.contracts.ticker_runs import TerminalStatus, TickerTerminalRecord
from src.stage_04_pipeline.ticker_terminal_store import (
    build_ticker_terminal_outcomes_payload,
    list_ticker_terminal_outcomes,
    load_ticker_terminal_outcome,
    persist_ticker_terminal_outcome,
)
from src.stage_04_pipeline.ticker_batch import run_ticker_batch
from tests.test_ticker_batch_contract import _context, _decision_grade


def test_terminal_outcome_checkpoint_is_idempotent_for_one_execution() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_tables(conn)
    record = _decision_grade(_context("MSFT"))

    first = persist_ticker_terminal_outcome(
        conn,
        execution_run_id="execution:001",
        batch_run_id="batch:001",
        record=record,
    )
    repeated = persist_ticker_terminal_outcome(
        conn,
        execution_run_id="execution:001",
        batch_run_id="batch:001",
        record=record,
    )

    assert repeated == first
    assert conn.execute(
        "SELECT COUNT(*) FROM ticker_terminal_outcomes"
    ).fetchone()[0] == 1
    loaded = load_ticker_terminal_outcome(conn, first.outcome_id)
    assert loaded == first
    assert loaded.record == record
    assert loaded.status == "decision_grade"
    assert loaded.reason_code == "valuation.completed"
    assert loaded.execution_run_id == "execution:001"
    assert loaded.batch_run_id == "batch:001"
    assert loaded.context_fingerprint == record.context.context_fingerprint
    assert loaded.checkpoint_fingerprint == record.checkpoint_fingerprint
    assert (
        loaded.analysis_snapshot_hash
        == record.context.replay_inputs.analysis_snapshot_hash
    )
    assert (
        loaded.readiness_fingerprint
        == record.context.readiness.readiness_fingerprint
    )


def test_terminal_outcomes_reject_same_run_divergence_and_version_new_runs() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_tables(conn)
    completed = _decision_grade(_context("MSFT"))
    first = persist_ticker_terminal_outcome(
        conn,
        execution_run_id="execution:001",
        batch_run_id="batch:001",
        record=completed,
        created_at="2026-07-26T10:00:00+00:00",
    )
    operational_retry = completed.model_copy(
        update={"attempt_count": 3, "reason_detail": "retried transport"}
    )

    assert (
        persist_ticker_terminal_outcome(
            conn,
            execution_run_id="execution:001",
            batch_run_id="batch:001",
            record=operational_retry,
        )
        == first
    )

    provisional = TickerTerminalRecord(
        context=completed.context,
        status=TerminalStatus.provisional,
        reason_code="valuation.provisional",
        retryable=False,
        result_fingerprint="provisional:MSFT",
    )
    with pytest.raises(
        ValueError,
        match="ticker terminal outcome idempotency conflict",
    ):
        persist_ticker_terminal_outcome(
            conn,
            execution_run_id="execution:001",
            batch_run_id="batch:001",
            record=provisional,
        )

    second = persist_ticker_terminal_outcome(
        conn,
        execution_run_id="execution:002",
        batch_run_id="batch:002",
        record=provisional,
        created_at="2026-07-26T11:00:00+00:00",
    )

    outcomes = list_ticker_terminal_outcomes(conn, ticker="msft", limit=10)
    assert [outcome.outcome_id for outcome in outcomes] == [
        second.outcome_id,
        first.outcome_id,
    ]
    assert [outcome.status for outcome in outcomes] == [
        "provisional",
        "decision_grade",
    ]


def test_terminal_outcome_load_fails_closed_on_tampered_status() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_tables(conn)
    stored = persist_ticker_terminal_outcome(
        conn,
        execution_run_id="execution:001",
        record=_decision_grade(_context("MSFT")),
    )
    conn.execute(
        """
        UPDATE ticker_terminal_outcomes
        SET status = 'blocked'
        WHERE outcome_id = ?
        """,
        (stored.outcome_id,),
    )
    conn.commit()

    with pytest.raises(
        ValueError,
        match="ticker terminal outcome integrity check failed",
    ):
        load_ticker_terminal_outcome(conn, stored.outcome_id)


def test_terminal_outcome_payload_reads_the_configured_database(
    tmp_path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "terminal-outcomes.db"
    with get_connection(db_path) as conn:
        create_tables(conn)
        stored = persist_ticker_terminal_outcome(
            conn,
            execution_run_id="execution:001",
            batch_run_id="batch:001",
            record=_decision_grade(_context("MSFT")),
        )
    monkeypatch.setenv("ALPHA_POD_DB_PATH", str(db_path))

    payload = build_ticker_terminal_outcomes_payload("msft", limit=5)

    assert payload["ticker"] == "MSFT"
    assert payload["count"] == 1
    assert payload["limit"] == 5
    assert payload["outcomes"][0]["outcome_id"] == stored.outcome_id
    assert payload["outcomes"][0]["execution_run_id"] == "execution:001"
    assert payload["outcomes"][0]["status"] == "decision_grade"


def test_batch_checkpoint_persists_one_terminal_row_per_requested_ticker() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_tables(conn)
    contexts = [_context("MSFT"), _context("IBM"), _context("CALM")]

    def _run_one(context, *, transport_timeout_seconds):
        if context.identity.ticker == "IBM":
            return TickerTerminalRecord(
                context=context,
                status=TerminalStatus.provisional,
                reason_code="valuation.provisional",
                retryable=False,
                result_fingerprint="provisional:IBM",
            )
        if context.identity.ticker == "CALM":
            return TickerTerminalRecord(
                context=context,
                status=TerminalStatus.blocked,
                reason_code="trust_gate.incomplete",
                retryable=False,
            )
        return _decision_grade(context)

    manifest = run_ticker_batch(
        contexts,
        _run_one,
        checkpoint_callback=lambda record: persist_ticker_terminal_outcome(
            conn,
            execution_run_id="execution:batch-001",
            batch_run_id="batch:001",
            record=record,
        ),
    )

    outcomes = list_ticker_terminal_outcomes(
        conn,
        batch_run_id="batch:001",
        limit=10,
    )
    assert len(manifest.records) == 3
    assert len(outcomes) == 3
    assert {outcome.ticker for outcome in outcomes} == {
        "MSFT",
        "IBM",
        "CALM",
    }
    assert {outcome.status for outcome in outcomes} == {
        "decision_grade",
        "provisional",
        "blocked",
    }
