from __future__ import annotations

from pathlib import Path
import sqlite3
from types import SimpleNamespace

from src.stage_04_pipeline.statement_source_refresh import (
    refresh_statement_sources,
)


def _reconciliation(
    ticker: str,
    *,
    status: str,
    reason_codes: tuple[str, ...] = (),
):
    return SimpleNamespace(
        ticker=ticker,
        run_hash=f"run:{ticker}",
        as_of_date="2026-03-31",
        manifest_ids=(f"manifest:{ticker}",),
        selected_fact_ids=(f"fact:{ticker}",),
        readiness=SimpleNamespace(
            status=status,
            reason_codes=reason_codes,
            annual_period_count=5,
            ltm_status="constructed",
        ),
    )


def test_statement_source_refresh_accounts_for_every_request_and_isolates_failures(
    tmp_path: Path,
):
    msft_workbook = tmp_path / "MSFT_Standard.xlsx"
    bah_workbook = tmp_path / "BAH_Standard.xlsx"
    msft_workbook.touch()
    bah_workbook.touch()
    conn = sqlite3.connect(":memory:")
    xbrl_calls: list[str] = []
    ciq_calls: list[str] = []
    reconcile_calls: list[str] = []

    def fake_xbrl(connection, ticker, **kwargs):
        xbrl_calls.append(ticker)
        if ticker == "BAH":
            raise RuntimeError("SEC filing bundle unavailable")
        return {
            "status": "completed",
            "inserted_count": 100,
            "manifest_ids": [f"xbrl:{ticker}"],
            "errors": [],
        }

    def fake_ciq(folder_path, **kwargs):
        workbook = Path(next(iter(kwargs["workbook_paths"])))
        ticker = workbook.stem.split("_", 1)[0]
        ciq_calls.append(ticker)
        if ticker == "BAH":
            result = SimpleNamespace(
                file=workbook.name,
                status="failed",
                ticker=ticker,
                run_id=22,
                rows_parsed=0,
                error="workbook validation failed",
            )
            return SimpleNamespace(
                processed=0,
                skipped=0,
                failed=1,
                results=[result],
            )
        result = SimpleNamespace(
            file=workbook.name,
            status="processed",
            ticker=ticker,
            run_id=21,
            rows_parsed=8601,
            error=None,
        )
        return SimpleNamespace(
            processed=1,
            skipped=0,
            failed=0,
            results=[result],
        )

    def fake_reconcile(connection, ticker, **kwargs):
        reconcile_calls.append(ticker)
        return _reconciliation(
            ticker,
            status="decision_grade" if ticker == "MSFT" else "provisional",
            reason_codes=(
                () if ticker == "MSFT" else ("source_coverage_not_attested",)
            ),
        )

    batch = refresh_statement_sources(
        ["msft", "BAH", "MSFT"],
        connection=conn,
        evidence_cutoff="2026-07-26",
        ciq_workbooks={
            "MSFT": msft_workbook,
            "BAH": bah_workbook,
        },
        xbrl_refresh=fake_xbrl,
        ciq_ingest=fake_ciq,
        reconcile=fake_reconcile,
    )

    assert batch.requested_count == 3
    assert [result.request_index for result in batch.results] == [0, 1, 2]
    assert [result.ticker for result in batch.results] == [
        "MSFT",
        "BAH",
        "MSFT",
    ]
    assert [result.status for result in batch.results] == [
        "decision_grade",
        "blocked",
        "decision_grade",
    ]
    assert "xbrl_refresh_failed" in batch.results[1].reason_codes
    assert "ciq_ingest_failed" in batch.results[1].reason_codes
    assert batch.results[1].errors == (
        "SEC filing bundle unavailable",
        "workbook validation failed",
    )
    assert xbrl_calls == ["MSFT", "BAH"]
    assert ciq_calls == ["MSFT", "BAH"]
    assert reconcile_calls == ["MSFT", "BAH"]
    assert batch.status_counts == {
        "decision_grade": 2,
        "provisional": 0,
        "blocked": 1,
    }


def test_statement_source_refresh_replays_idempotently_with_injected_sources(
    tmp_path: Path,
):
    workbook = tmp_path / "MSFT_Standard.xlsx"
    workbook.touch()
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE source_effects (source TEXT, ticker TEXT, PRIMARY KEY (source, ticker))"
    )

    def fake_xbrl(connection, ticker, **kwargs):
        before = connection.total_changes
        connection.execute(
            "INSERT OR IGNORE INTO source_effects VALUES ('xbrl', ?)",
            (ticker,),
        )
        connection.commit()
        return {
            "status": "completed",
            "inserted_count": connection.total_changes - before,
            "manifest_ids": [f"xbrl:{ticker}"],
            "errors": [],
        }

    def fake_ciq(folder_path, **kwargs):
        connection = kwargs["connection"]
        before = connection.total_changes
        connection.execute(
            "INSERT OR IGNORE INTO source_effects VALUES ('ciq', 'MSFT')"
        )
        connection.commit()
        inserted = connection.total_changes - before
        return SimpleNamespace(
            processed=int(bool(inserted)),
            skipped=int(not inserted),
            failed=0,
            results=[
                SimpleNamespace(
                    file=workbook.name,
                    status="processed" if inserted else "skipped",
                    ticker="MSFT",
                    run_id=1,
                    rows_parsed=8601 if inserted else 0,
                    error=None,
                )
            ],
        )

    def fake_reconcile(connection, ticker, **kwargs):
        return _reconciliation(ticker, status="decision_grade")

    first = refresh_statement_sources(
        ["MSFT"],
        connection=conn,
        ciq_workbooks={"MSFT": workbook},
        xbrl_refresh=fake_xbrl,
        ciq_ingest=fake_ciq,
        reconcile=fake_reconcile,
    )
    second = refresh_statement_sources(
        ["MSFT"],
        connection=conn,
        ciq_workbooks={"MSFT": workbook},
        xbrl_refresh=fake_xbrl,
        ciq_ingest=fake_ciq,
        reconcile=fake_reconcile,
    )

    assert conn.execute(
        "SELECT COUNT(*) FROM source_effects"
    ).fetchone()[0] == 2
    assert first.results[0].status == second.results[0].status == (
        "decision_grade"
    )
    assert first.results[0].reason_codes == second.results[0].reason_codes == ()
    assert first.results[0].reconciliation_run_hash == (
        second.results[0].reconciliation_run_hash
    )
