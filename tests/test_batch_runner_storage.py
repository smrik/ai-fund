import csv
import logging
import sqlite3
from pathlib import Path

import pandas as pd

from src.stage_02_valuation import batch_runner


def _sample_row(ticker: str, upside: float) -> dict:
    return {
        "ticker": ticker,
        "company_name": f"Company {ticker}",
        "sector": "Technology",
        "price": 10.0,
        "iv_bear": 8.0,
        "iv_base": 12.0,
        "iv_bull": 15.0,
        "upside_base_pct": upside,
        "wacc": 9.0,
        "pe_trailing": 20.0,
        "pe_forward": 15.0,
        "ev_ebitda": 11.0,
        "market_cap_mm": 1200.0,
        "ev_mm": 1400.0,
    }


def test_persist_results_to_db_writes_snapshot_and_history(tmp_path, monkeypatch):
    db_path = tmp_path / "alpha_pod.db"
    monkeypatch.setattr(batch_runner, "DB_PATH", db_path)

    df = pd.DataFrame([
        _sample_row("AAA", 20.0),
        _sample_row("BBB", 10.0),
    ])

    latest_count, history_count, _dcf_count = batch_runner.persist_results_to_db(df, snapshot_date="2026-03-06")

    assert latest_count == 2
    assert history_count == 2

    conn = sqlite3.connect(str(db_path))
    try:
        latest_rows = conn.execute("SELECT COUNT(*) FROM batch_valuations_latest").fetchone()[0]
        latest_snapshot = conn.execute(
            "SELECT ticker, snapshot_date FROM batch_valuations_latest WHERE ticker='AAA'"
        ).fetchone()
        history_rows = conn.execute("SELECT COUNT(*) FROM valuations").fetchone()[0]
        row = conn.execute(
            "SELECT ticker, date, pe_ttm, pe_fwd, ev_ebitda_ttm FROM valuations WHERE ticker='AAA'"
        ).fetchone()
    finally:
        conn.close()

    assert latest_rows == 2
    assert latest_snapshot == ("AAA", "2026-03-06")
    assert history_rows == 2
    assert row == ("AAA", "2026-03-06", 20.0, 15.0, 11.0)


def test_run_batch_default_writes_latest_csv_and_skips_xlsx(tmp_path, monkeypatch):
    output_dir = tmp_path / "valuations"
    universe_csv = tmp_path / "universe.csv"
    db_path = tmp_path / "alpha_pod.db"

    with universe_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["ticker"])
        writer.writeheader()
        writer.writerow({"ticker": "AAA"})
        writer.writerow({"ticker": "BBB"})

    monkeypatch.setattr(batch_runner, "UNIVERSE_CSV", universe_csv)
    monkeypatch.setattr(batch_runner, "OUTPUT_DIR", output_dir)
    monkeypatch.setattr(batch_runner, "DB_PATH", db_path)
    monkeypatch.setattr(batch_runner.time, "sleep", lambda _: None)
    monkeypatch.setattr(batch_runner, "value_single_ticker", lambda ticker: _sample_row(ticker, 20.0 if ticker == "AAA" else 10.0))

    xlsx_calls = {"count": 0}

    def _fake_export_to_excel(results: list[dict], output_path: Path):
        xlsx_calls["count"] += 1

    monkeypatch.setattr(batch_runner, "export_to_excel", _fake_export_to_excel)

    batch_runner.run_batch(top_n=1)

    latest_csv = output_dir / "latest.csv"
    assert latest_csv.exists()
    assert xlsx_calls["count"] == 0
    assert list(output_dir.glob("batch_*.csv")) == []
    assert list(output_dir.glob("*.xlsx")) == []

    conn = sqlite3.connect(str(db_path))
    try:
        latest_rows = conn.execute("SELECT COUNT(*) FROM batch_valuations_latest").fetchone()[0]
        history_rows = conn.execute("SELECT COUNT(*) FROM valuations").fetchone()[0]
    finally:
        conn.close()

    assert latest_rows == 2
    assert history_rows == 2


def test_run_batch_with_xlsx_flag_calls_excel_export(tmp_path, monkeypatch):
    output_dir = tmp_path / "valuations"
    db_path = tmp_path / "alpha_pod.db"

    monkeypatch.setattr(batch_runner, "OUTPUT_DIR", output_dir)
    monkeypatch.setattr(batch_runner, "DB_PATH", db_path)
    monkeypatch.setattr(batch_runner.time, "sleep", lambda _: None)
    monkeypatch.setattr(batch_runner, "value_single_ticker", lambda ticker: _sample_row(ticker, 25.0))

    calls: list[Path] = []

    def _fake_export_to_excel(results: list[dict], output_path: Path):
        calls.append(output_path)

    monkeypatch.setattr(batch_runner, "export_to_excel", _fake_export_to_excel)

    batch_runner.run_batch(tickers=["AAA"], export_xlsx=True)

    assert len(calls) == 1
    assert calls[0].name.startswith("batch_valuation_")
    assert calls[0].suffix == ".xlsx"


def test_run_batch_logs_summary_without_printing_contracts(tmp_path, monkeypatch, caplog):
    output_dir = tmp_path / "valuations"
    db_path = tmp_path / "alpha_pod.db"

    monkeypatch.setattr(batch_runner, "OUTPUT_DIR", output_dir)
    monkeypatch.setattr(batch_runner, "DB_PATH", db_path)
    monkeypatch.setattr(batch_runner.time, "sleep", lambda _: None)
    monkeypatch.setattr(batch_runner, "value_single_ticker", lambda ticker: _sample_row(ticker, 25.0))
    monkeypatch.setattr(batch_runner, "export_to_excel", lambda results, output_path: None)

    with caplog.at_level(logging.INFO, logger=batch_runner.__name__):
        batch_runner.run_batch(tickers=["AAA"], export_xlsx=False)

    assert "Completed: 1 valued, 0 skipped" in caplog.text
    assert "CSV export written to" in caplog.text
    assert "SQLite snapshot written to" in caplog.text


def test_run_batch_reports_progress_events(tmp_path, monkeypatch):
    output_dir = tmp_path / "valuations"
    db_path = tmp_path / "alpha_pod.db"
    events: list[dict] = []

    monkeypatch.setattr(batch_runner, "OUTPUT_DIR", output_dir)
    monkeypatch.setattr(batch_runner, "DB_PATH", db_path)
    monkeypatch.setattr(batch_runner.time, "sleep", lambda _: None)
    monkeypatch.setattr(
        batch_runner,
        "value_single_ticker",
        lambda ticker: _sample_row(ticker, 25.0) if ticker == "AAA" else None,
    )
    monkeypatch.setattr(batch_runner, "export_to_excel", lambda results, output_path: None)

    batch_runner.run_batch(
        tickers=["AAA", "BBB"],
        export_xlsx=False,
        progress_callback=lambda payload: events.append(dict(payload)),
    )

    assert events[0] == {"completed": 0, "status": "starting", "ticker": None, "total": 2}
    assert events[1]["ticker"] == "AAA"
    assert events[1]["status"] == "valued"
    assert events[1]["completed"] == 1
    assert events[2]["ticker"] == "BBB"
    assert events[2]["status"] == "skipped"
    assert events[-1] == {"completed": 2, "status": "complete", "ticker": None, "total": 2}
