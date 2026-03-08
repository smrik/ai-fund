import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sqlite3

from src.stage_00_data import ciq_adapter


def test_get_ciq_comps_valuation_returns_implied_values(monkeypatch):
    fake_rows = [
        # target row metrics
        {
            "peer_ticker": "IBM",
            "metric_key": "ebitda_ltm",
            "value_num": 12000.0,
            "is_target": 1,
            "run_id": 7,
            "source_file": "ciq_cleandata.xlsx",
            "as_of_date": "2025-12-31",
        },
        {
            "peer_ticker": "IBM",
            "metric_key": "diluted_eps_ltm",
            "value_num": 10.0,
            "is_target": 1,
            "run_id": 7,
            "source_file": "ciq_cleandata.xlsx",
            "as_of_date": "2025-12-31",
        },
        {
            "peer_ticker": "IBM",
            "metric_key": "shares_out",
            "value_num": 900.0,
            "is_target": 1,
            "run_id": 7,
            "source_file": "ciq_cleandata.xlsx",
            "as_of_date": "2025-12-31",
        },
        {
            "peer_ticker": "IBM",
            "metric_key": "total_debt",
            "value_num": 65000.0,
            "is_target": 1,
            "run_id": 7,
            "source_file": "ciq_cleandata.xlsx",
            "as_of_date": "2025-12-31",
        },
        {
            "peer_ticker": "IBM",
            "metric_key": "cash",
            "value_num": 15000.0,
            "is_target": 1,
            "run_id": 7,
            "source_file": "ciq_cleandata.xlsx",
            "as_of_date": "2025-12-31",
        },
        # peers
        {"peer_ticker": "ORCL", "metric_key": "tev_ebitda_ltm", "value_num": 19.0, "is_target": 0},
        {"peer_ticker": "ACN", "metric_key": "tev_ebitda_ltm", "value_num": 10.0, "is_target": 0},
        {"peer_ticker": "ORCL", "metric_key": "pe_ltm", "value_num": 28.0, "is_target": 0},
        {"peer_ticker": "ACN", "metric_key": "pe_ltm", "value_num": 18.0, "is_target": 0},
    ]

    monkeypatch.setattr(ciq_adapter, "_fetch_ciq_comps_rows", lambda ticker, as_of_date=None: fake_rows)

    out = ciq_adapter.get_ciq_comps_valuation("IBM")

    assert out is not None
    assert out["peer_count"] == 2
    assert out["peer_median_tev_ebitda_ltm"] == 14.5
    assert out["peer_median_pe_ltm"] == 23.0
    assert out["implied_price_ev_ebitda"] is not None
    assert out["implied_price_pe"] is not None
    assert out["implied_price_base"] is not None


def test_get_ciq_comps_valuation_uses_latest_run_only(tmp_path, monkeypatch):
    db_path = tmp_path / "ciq_adapter.sqlite"
    monkeypatch.setattr(ciq_adapter, "DB_PATH", db_path)

    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE ciq_comps_snapshot (
            target_ticker TEXT NOT NULL,
            peer_ticker TEXT NOT NULL,
            as_of_date TEXT NOT NULL,
            run_id INTEGER NOT NULL,
            source_file TEXT NOT NULL,
            metric_key TEXT NOT NULL,
            value_num REAL,
            is_target INTEGER DEFAULT 0
        )
        """
    )

    rows = [
        # older run: stale peers
        ("IBM", "OLD1", "2025-12-31", 1, "old.xlsx", "tev_ebitda_ltm", 30.0, 0),
        ("IBM", "OLD1", "2025-12-31", 1, "old.xlsx", "pe_ltm", 35.0, 0),
        ("IBM", "OLD2", "2025-12-31", 1, "old.xlsx", "tev_ebitda_ltm", 24.0, 0),
        ("IBM", "OLD2", "2025-12-31", 1, "old.xlsx", "pe_ltm", 31.0, 0),
        # latest run: target + current peers
        ("IBM", "IBM", "2025-12-31", 2, "new.xlsx", "ebitda_ltm", 120.0, 1),
        ("IBM", "IBM", "2025-12-31", 2, "new.xlsx", "diluted_eps_ltm", 10.0, 1),
        ("IBM", "IBM", "2025-12-31", 2, "new.xlsx", "shares_out", 100.0, 1),
        ("IBM", "IBM", "2025-12-31", 2, "new.xlsx", "total_debt", 1000.0, 1),
        ("IBM", "IBM", "2025-12-31", 2, "new.xlsx", "cash", 100.0, 1),
        ("IBM", "ORCL", "2025-12-31", 2, "new.xlsx", "tev_ebitda_ltm", 10.0, 0),
        ("IBM", "ORCL", "2025-12-31", 2, "new.xlsx", "pe_ltm", 20.0, 0),
        ("IBM", "ACN", "2025-12-31", 2, "new.xlsx", "tev_ebitda_ltm", 12.0, 0),
        ("IBM", "ACN", "2025-12-31", 2, "new.xlsx", "pe_ltm", 22.0, 0),
    ]

    conn.executemany(
        """
        INSERT INTO ciq_comps_snapshot (
            target_ticker, peer_ticker, as_of_date, run_id, source_file,
            metric_key, value_num, is_target
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()
    conn.close()

    out = ciq_adapter.get_ciq_comps_valuation("IBM")

    assert out is not None
    assert out["run_id"] == 2
    assert out["source_file"] == "new.xlsx"
    assert out["peer_count"] == 2
    assert out["peer_median_tev_ebitda_ltm"] == 11.0
    assert out["peer_median_pe_ltm"] == 21.0

def test_get_ciq_comps_valuation_prioritizes_diluted_eps_and_maps_debt_alias(monkeypatch):
    fake_rows = [
        {"peer_ticker": "IBM", "metric_key": "ebitda_ltm", "value_num": 120.0, "is_target": 1},
        {"peer_ticker": "IBM", "metric_key": "diluted_eps_ltm", "value_num": 10.0, "is_target": 1},
        {"peer_ticker": "IBM", "metric_key": "eps_ltm", "value_num": 70.0, "is_target": 1},
        {"peer_ticker": "IBM", "metric_key": "shares_out", "value_num": 100.0, "is_target": 1},
        {"peer_ticker": "IBM", "metric_key": "debt", "value_num": 1000.0, "is_target": 1},
        {"peer_ticker": "IBM", "metric_key": "cash", "value_num": 100.0, "is_target": 1},
        {"peer_ticker": "ORCL", "metric_key": "tev_ebitda_ltm", "value_num": 10.0, "is_target": 0},
        {"peer_ticker": "ACN", "metric_key": "tev_ebitda_ltm", "value_num": 12.0, "is_target": 0},
        {"peer_ticker": "ORCL", "metric_key": "pe_ltm", "value_num": 20.0, "is_target": 0},
        {"peer_ticker": "ACN", "metric_key": "pe_ltm", "value_num": 22.0, "is_target": 0},
    ]

    monkeypatch.setattr(ciq_adapter, "_fetch_ciq_comps_rows", lambda ticker, as_of_date=None: fake_rows)

    out = ciq_adapter.get_ciq_comps_valuation("IBM")

    assert out is not None
    assert out["target_eps_ltm"] == 10.0
    assert out["target_net_debt"] == 900.0
    assert out["implied_price_pe"] == 210.0

def test_get_ciq_comps_valuation_includes_ev_ebit_outputs(monkeypatch):
    fake_rows = [
        {"peer_ticker": "XOM", "metric_key": "ebit_ltm", "value_num": 5000.0, "is_target": 1},
        {"peer_ticker": "XOM", "metric_key": "shares_out", "value_num": 4000.0, "is_target": 1},
        {"peer_ticker": "XOM", "metric_key": "total_debt", "value_num": 20000.0, "is_target": 1},
        {"peer_ticker": "XOM", "metric_key": "cash", "value_num": 5000.0, "is_target": 1},
        {"peer_ticker": "CVX", "metric_key": "tev_ebit_ltm", "value_num": 8.0, "is_target": 0},
        {"peer_ticker": "BP", "metric_key": "tev_ebit_ltm", "value_num": 12.0, "is_target": 0},
    ]

    monkeypatch.setattr(ciq_adapter, "_fetch_ciq_comps_rows", lambda ticker, as_of_date=None: fake_rows)

    out = ciq_adapter.get_ciq_comps_valuation("XOM")

    assert out is not None
    assert out["peer_median_tev_ebit_ltm"] == 10.0
    assert out["implied_price_ev_ebit"] == 8.75
