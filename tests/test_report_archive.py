from __future__ import annotations

import sqlite3
from pathlib import Path

from db.schema import create_tables
from src.stage_02_valuation.templates.ic_memo import ICMemo, ValuationRange


def _temp_conn_factory(db_path: Path):
    def _factory():
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        create_tables(conn)
        return conn

    return _factory


def _build_memo(*, ticker: str = "IBM", base_iv: float = 110.0, current_price: float = 100.0) -> ICMemo:
    return ICMemo(
        ticker=ticker,
        company_name="IBM",
        sector="Technology",
        action="WATCH",
        conviction="medium",
        one_liner="Stub memo",
        valuation=ValuationRange(bear=90.0, base=base_iv, bull=130.0, current_price=current_price),
    )


def test_report_archive_round_trip(monkeypatch, tmp_path):
    from src.stage_04_pipeline import report_archive

    db_path = tmp_path / "archive.db"
    monkeypatch.setattr(report_archive, "get_connection", _temp_conn_factory(db_path))

    memo = _build_memo()
    snapshot_id = report_archive.save_report_snapshot(
        "ibm",
        memo,
        dcf_audit={"available": True},
        comps_view={"valuation_range": {"base": 108.0}},
        market_intel_view={"headlines": [{"title": "IBM signs new contract"}]},
        filings_browser_view={"filings": [{"form_type": "10-K"}]},
        run_trace=[
            {"agent": "FilingsAgent", "status": "executed"},
            {"agent": "ThesisAgent", "status": "executed", "finished_at": "2026-03-15T08:00:00Z"},
        ],
    )

    history = report_archive.list_report_snapshots("IBM")
    loaded = report_archive.load_report_snapshot(snapshot_id)

    assert len(history) == 1
    assert history[0]["ticker"] == "IBM"
    assert history[0]["action"] == "WATCH"
    assert history[0]["current_price"] == 100.0
    assert history[0]["base_iv"] == 110.0
    assert history[0]["run_group_ts"] == "2026-03-15T08:00:00Z"

    assert loaded is not None
    assert loaded["ticker"] == "IBM"
    assert loaded["company_name"] == "IBM"
    assert loaded["sector"] == "Technology"
    assert loaded["memo"]["ticker"] == "IBM"
    assert loaded["dashboard_snapshot"]["dcf_audit"]["available"] is True
    assert loaded["dashboard_snapshot"]["market_intel_view"]["headlines"][0]["title"] == "IBM signs new contract"
    assert loaded["dashboard_snapshot"]["filings_browser_view"]["filings"][0]["form_type"] == "10-K"
    assert loaded["run_trace"][0]["agent"] == "FilingsAgent"


def test_report_archive_lists_newest_first_and_returns_none_for_missing(monkeypatch, tmp_path):
    from src.stage_04_pipeline import report_archive

    db_path = tmp_path / "archive.db"
    monkeypatch.setattr(report_archive, "get_connection", _temp_conn_factory(db_path))
    timestamps = iter(
        [
            "2026-03-15T08:00:00+00:00",
            "2026-03-15T09:00:00+00:00",
        ]
    )
    monkeypatch.setattr(report_archive, "_now", lambda: next(timestamps))

    first_id = report_archive.save_report_snapshot(
        "IBM",
        _build_memo(base_iv=101.0, current_price=98.0),
        dcf_audit=None,
        comps_view=None,
        market_intel_view=None,
        filings_browser_view=None,
        run_trace=[],
    )
    second_id = report_archive.save_report_snapshot(
        "IBM",
        _build_memo(base_iv=125.0, current_price=103.0),
        dcf_audit={"view": "latest"},
        comps_view=None,
        market_intel_view=None,
        filings_browser_view=None,
        run_trace=[{"run_ts": "2026-03-15T09:05:00Z"}],
    )

    history = report_archive.list_report_snapshots("IBM", limit=10)

    assert [row["id"] for row in history] == [second_id, first_id]
    assert history[0]["base_iv"] == 125.0
    assert history[1]["base_iv"] == 101.0

    loaded = report_archive.load_report_snapshot(second_id)
    assert loaded is not None
    assert loaded["run_group_ts"] == "2026-03-15T09:05:00Z"
    assert loaded["dashboard_snapshot"]["dcf_audit"]["view"] == "latest"
    assert report_archive.load_report_snapshot(999999) is None
