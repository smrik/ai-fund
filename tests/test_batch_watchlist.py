from __future__ import annotations

import builtins
import importlib
import sqlite3
import sys
from pathlib import Path

from db.schema import create_tables
from src.stage_04_pipeline import batch_funnel


def _temp_conn_factory(db_path: Path):
    def _factory():
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        create_tables(conn)
        return conn

    return _factory


def test_load_saved_watchlist_returns_ranked_full_universe_and_latest_pm_stance(monkeypatch, tmp_path):
    db_path = tmp_path / "watchlist.db"
    monkeypatch.setattr(batch_funnel, "get_connection", _temp_conn_factory(db_path))

    with batch_funnel.get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE batch_valuations_latest (
                ticker TEXT,
                company_name TEXT,
                date TEXT,
                price REAL,
                iv_bear REAL,
                iv_base REAL,
                iv_bull REAL,
                expected_iv REAL,
                expected_upside_pct REAL,
                upside_base_pct REAL,
                margin_of_safety REAL,
                analyst_target REAL,
                model_applicability_status TEXT
            )
            """
        )
        conn.executemany(
            """
            INSERT INTO batch_valuations_latest (
                ticker, company_name, date, price, iv_bear, iv_base, iv_bull,
                expected_iv, expected_upside_pct, upside_base_pct, margin_of_safety,
                analyst_target, model_applicability_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("IBM", "IBM", "2026-03-28", 100.0, 85.0, 120.0, 140.0, 125.0, 25.0, 20.0, 16.0, 130.0, "dcf_applicable"),
                ("AAPL", "Apple", "2026-03-28", 200.0, 180.0, 210.0, 240.0, 215.0, None, 5.0, 4.8, 220.0, "dcf_applicable"),
                ("XYZ", "Alt Model Co", "2026-03-28", 50.0, None, None, None, None, None, None, None, None, "alt_model_required"),
            ],
        )
        conn.executemany(
            """
            INSERT INTO pipeline_report_archive (
                ticker, created_at, action, conviction, current_price, base_iv, memo_json,
                dashboard_snapshot_json, run_trace_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("IBM", "2026-03-27T08:00:00+00:00", "WATCH", "low", 98.0, 118.0, "{}", "{}", "[]"),
                ("IBM", "2026-03-28T09:15:00+00:00", "BUY", "high", 100.0, 120.0, "{}", "{}", "[]"),
                ("AAPL", "2026-03-28T07:30:00+00:00", "PASS", "medium", 198.0, 210.0, "{}", "{}", "[]"),
            ],
        )
        conn.commit()

    watchlist = batch_funnel.load_saved_watchlist()

    assert watchlist["saved_row_count"] == 3
    assert watchlist["universe_row_count"] == 3
    assert watchlist["last_updated"] == "2026-03-28"
    assert watchlist["default_focus_ticker"] == "IBM"
    assert [row["ticker"] for row in watchlist["rows"]] == ["IBM", "AAPL", "XYZ"]

    first = watchlist["rows"][0]
    assert first["ticker"] == "IBM"
    assert first["price"] == 100.0
    assert first["iv_bear"] == 85.0
    assert first["iv_base"] == 120.0
    assert first["iv_bull"] == 140.0
    assert first["expected_iv"] == 125.0
    assert first["analyst_target"] == 130.0
    assert first["latest_action"] == "BUY"
    assert first["latest_conviction"] == "high"
    assert first["latest_snapshot_date"] == "2026-03-28T09:15:00+00:00"

    last = watchlist["rows"][-1]
    assert last["ticker"] == "XYZ"
    assert last["latest_action"] is None
    assert last["latest_conviction"] is None
    assert last["latest_snapshot_date"] is None


def test_batch_funnel_module_can_import_without_batch_runner(monkeypatch):
    module_name = "src.stage_04_pipeline.batch_funnel"
    original_import = builtins.__import__
    original_module = sys.modules.get(module_name)

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "src.stage_02_valuation.batch_runner":
            raise ModuleNotFoundError("simulated missing batch_runner")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    sys.modules.pop(module_name, None)

    try:
        module = importlib.import_module(module_name)
        assert hasattr(module, "load_saved_watchlist")
    finally:
        if original_module is not None:
            sys.modules[module_name] = original_module
        else:
            sys.modules.pop(module_name, None)


def test_load_saved_watchlist_returns_empty_payload_when_no_batch_snapshot(monkeypatch, tmp_path):
    db_path = tmp_path / "watchlist.db"
    monkeypatch.setattr(batch_funnel, "get_connection", _temp_conn_factory(db_path))

    watchlist = batch_funnel.load_saved_watchlist()

    assert watchlist["rows"] == []
    assert watchlist["saved_row_count"] == 0
    assert watchlist["universe_row_count"] == 0
    assert watchlist["default_focus_ticker"] is None
    assert watchlist["last_updated"] is None
