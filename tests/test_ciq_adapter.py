import sys
from pathlib import Path

import pytest

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


def test_get_ciq_snapshot_includes_nwc_day_drivers_from_long_form(tmp_path, monkeypatch):
    db_path = tmp_path / "ciq_snapshot.sqlite"
    monkeypatch.setattr(ciq_adapter, "DB_PATH", db_path)

    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE ciq_valuation_snapshot (
            ticker TEXT,
            as_of_date TEXT,
            run_id INTEGER,
            source_file TEXT,
            revenue_mm REAL,
            operating_income_mm REAL,
            capex_mm REAL,
            da_mm REAL,
            total_debt_mm REAL,
            cash_mm REAL,
            shares_out_mm REAL,
            ebit_margin REAL,
            op_margin_avg_3yr REAL,
            capex_pct_avg_3yr REAL,
            da_pct_avg_3yr REAL,
            effective_tax_rate REAL,
            effective_tax_rate_avg REAL,
            revenue_cagr_3yr REAL,
            debt_to_ebitda REAL,
            roic REAL,
            fcf_yield REAL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE ciq_long_form (
            run_id INTEGER,
            ticker TEXT,
            metric_key TEXT,
            value_num REAL,
            period_date TEXT,
            column_index INTEGER
        )
        """
    )

    conn.execute(
        """
        INSERT INTO ciq_valuation_snapshot (
            ticker, as_of_date, run_id, source_file, revenue_mm, operating_income_mm,
            capex_mm, da_mm, total_debt_mm, cash_mm, shares_out_mm
        ) VALUES ('IBM', '2025-12-31', 7, 'ciq.xlsx', 1000, 200, 60, 40, 300, 100, 900)
        """
    )
    conn.executemany(
        "INSERT INTO ciq_long_form (run_id, ticker, metric_key, value_num, period_date, column_index) VALUES (?, ?, ?, ?, ?, ?)",
        [
            (7, "IBM", "dso", 50.0, "2025-12-31", 1),
            (7, "IBM", "dio", 45.0, "2025-12-31", 1),
            (7, "IBM", "dpo", 40.0, "2025-12-31", 1),
        ],
    )
    conn.commit()
    conn.close()

    out = ciq_adapter.get_ciq_snapshot("IBM")

    assert out is not None
    assert out["dso"] == 50.0
    assert out["dio"] == 45.0
    assert out["dpo"] == 40.0


def test_get_ciq_snapshot_derives_nwc_day_drivers_when_direct_metrics_missing(tmp_path, monkeypatch):
    db_path = tmp_path / "ciq_snapshot_derived.sqlite"
    monkeypatch.setattr(ciq_adapter, "DB_PATH", db_path)

    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE ciq_valuation_snapshot (
            ticker TEXT,
            as_of_date TEXT,
            run_id INTEGER,
            source_file TEXT,
            revenue_mm REAL,
            operating_income_mm REAL,
            capex_mm REAL,
            da_mm REAL,
            total_debt_mm REAL,
            cash_mm REAL,
            shares_out_mm REAL,
            ebit_margin REAL,
            op_margin_avg_3yr REAL,
            capex_pct_avg_3yr REAL,
            da_pct_avg_3yr REAL,
            effective_tax_rate REAL,
            effective_tax_rate_avg REAL,
            revenue_cagr_3yr REAL,
            debt_to_ebitda REAL,
            roic REAL,
            fcf_yield REAL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE ciq_long_form (
            run_id INTEGER,
            ticker TEXT,
            metric_key TEXT,
            value_num REAL,
            period_date TEXT,
            column_index INTEGER
        )
        """
    )

    conn.execute(
        """
        INSERT INTO ciq_valuation_snapshot (
            ticker, as_of_date, run_id, source_file, revenue_mm, operating_income_mm,
            capex_mm, da_mm, total_debt_mm, cash_mm, shares_out_mm
        ) VALUES ('IBM', '2025-12-31', 8, 'ciq.xlsx', 1000, 200, 60, 40, 300, 100, 900)
        """
    )
    conn.executemany(
        "INSERT INTO ciq_long_form (run_id, ticker, metric_key, value_num, period_date, column_index) VALUES (?, ?, ?, ?, ?, ?)",
        [
            (8, "IBM", "accounts_receivable", 120.0, "2025-12-31", 1),
            (8, "IBM", "inventory", 80.0, "2025-12-31", 1),
            (8, "IBM", "accounts_payable", 60.0, "2025-12-31", 1),
            (8, "IBM", "revenue", 1000.0, "2025-12-31", 1),
        ],
    )
    conn.commit()
    conn.close()

    out = ciq_adapter.get_ciq_snapshot("IBM")

    assert out is not None
    assert out["dso"] == 43.8
    assert out["dio"] == 29.2
    assert out["dpo"] == 21.9


def test_get_ciq_comps_valuation_includes_forward_multiples(monkeypatch):
    """Forward peer multiples (tev_ebitda_cy_1, tev_ebit_cy_1) are extracted and returned."""
    fake_rows = [
        # target
        {"peer_ticker": "IBM", "metric_key": "ebitda_ltm", "value_num": 12000.0, "is_target": 1,
         "run_id": 7, "source_file": "ciq.xlsx", "as_of_date": "2025-12-31"},
        {"peer_ticker": "IBM", "metric_key": "shares_out", "value_num": 900.0, "is_target": 1,
         "run_id": 7, "source_file": "ciq.xlsx", "as_of_date": "2025-12-31"},
        {"peer_ticker": "IBM", "metric_key": "total_debt", "value_num": 50000.0, "is_target": 1,
         "run_id": 7, "source_file": "ciq.xlsx", "as_of_date": "2025-12-31"},
        {"peer_ticker": "IBM", "metric_key": "cash", "value_num": 10000.0, "is_target": 1,
         "run_id": 7, "source_file": "ciq.xlsx", "as_of_date": "2025-12-31"},
        # peers with LTM and forward multiples
        {"peer_ticker": "ORCL", "metric_key": "tev_ebitda_ltm", "value_num": 20.0, "is_target": 0},
        {"peer_ticker": "ACN", "metric_key": "tev_ebitda_ltm", "value_num": 18.0, "is_target": 0},
        {"peer_ticker": "ORCL", "metric_key": "tev_ebitda_cy_1", "value_num": 16.0, "is_target": 0},
        {"peer_ticker": "ACN", "metric_key": "tev_ebitda_cy_1", "value_num": 14.0, "is_target": 0},
        {"peer_ticker": "ORCL", "metric_key": "tev_ebit_cy_1", "value_num": 22.0, "is_target": 0},
        {"peer_ticker": "ACN", "metric_key": "tev_ebit_cy_1", "value_num": 18.0, "is_target": 0},
    ]

    monkeypatch.setattr(ciq_adapter, "_fetch_ciq_comps_rows", lambda ticker, as_of_date=None: fake_rows)

    out = ciq_adapter.get_ciq_comps_valuation("IBM")

    assert out is not None
    assert out["peer_median_tev_ebitda_ltm"] == 19.0
    assert out["peer_median_tev_ebitda_fwd"] == 15.0  # median(16, 14)
    assert out["peer_median_tev_ebit_fwd"] == 20.0    # median(22, 18)


def test_get_ciq_comps_valuation_fwd_multiples_none_when_absent(monkeypatch):
    """No forward metric keys in peer rows → fwd medians are None."""
    fake_rows = [
        {"peer_ticker": "IBM", "metric_key": "ebitda_ltm", "value_num": 5000.0, "is_target": 1,
         "run_id": 1, "source_file": "ciq.xlsx", "as_of_date": "2025-12-31"},
        {"peer_ticker": "IBM", "metric_key": "shares_out", "value_num": 100.0, "is_target": 1,
         "run_id": 1, "source_file": "ciq.xlsx", "as_of_date": "2025-12-31"},
        {"peer_ticker": "IBM", "metric_key": "total_debt", "value_num": 0.0, "is_target": 1,
         "run_id": 1, "source_file": "ciq.xlsx", "as_of_date": "2025-12-31"},
        {"peer_ticker": "IBM", "metric_key": "cash", "value_num": 0.0, "is_target": 1,
         "run_id": 1, "source_file": "ciq.xlsx", "as_of_date": "2025-12-31"},
        {"peer_ticker": "ORCL", "metric_key": "tev_ebitda_ltm", "value_num": 12.0, "is_target": 0},
        {"peer_ticker": "ACN", "metric_key": "tev_ebitda_ltm", "value_num": 10.0, "is_target": 0},
    ]

    monkeypatch.setattr(ciq_adapter, "_fetch_ciq_comps_rows", lambda ticker, as_of_date=None: fake_rows)

    out = ciq_adapter.get_ciq_comps_valuation("IBM")

    assert out is not None
    assert out["peer_median_tev_ebitda_fwd"] is None
    assert out["peer_median_tev_ebit_fwd"] is None


def test_get_ciq_snapshot_includes_forward_revenue_from_comps(tmp_path, monkeypatch):
    """revenue_fy1 / revenue_fy2 are extracted from comps target row and added to snapshot."""
    db_path = tmp_path / "ciq_fwd_rev.sqlite"
    monkeypatch.setattr(ciq_adapter, "DB_PATH", db_path)

    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE ciq_valuation_snapshot (
            ticker TEXT, as_of_date TEXT, run_id INTEGER, source_file TEXT,
            revenue_mm REAL, operating_income_mm REAL, capex_mm REAL, da_mm REAL,
            total_debt_mm REAL, cash_mm REAL, shares_out_mm REAL,
            ebit_margin REAL, op_margin_avg_3yr REAL, capex_pct_avg_3yr REAL,
            da_pct_avg_3yr REAL, effective_tax_rate REAL, effective_tax_rate_avg REAL,
            revenue_cagr_3yr REAL, debt_to_ebitda REAL, roic REAL, fcf_yield REAL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE ciq_long_form (
            run_id INTEGER, ticker TEXT, metric_key TEXT, value_num REAL,
            period_date TEXT, column_index INTEGER
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE ciq_comps_snapshot (
            target_ticker TEXT, peer_ticker TEXT, as_of_date TEXT, run_id INTEGER,
            source_file TEXT, metric_key TEXT, value_num REAL, is_target INTEGER DEFAULT 0
        )
        """
    )

    conn.execute(
        """INSERT INTO ciq_valuation_snapshot
           (ticker, as_of_date, run_id, source_file, revenue_mm, operating_income_mm,
            capex_mm, da_mm, total_debt_mm, cash_mm, shares_out_mm)
           VALUES ('IBM', '2025-12-31', 5, 'ciq.xlsx', 1000, 200, 60, 40, 300, 100, 900)"""
    )
    conn.executemany(
        """INSERT INTO ciq_comps_snapshot
           (target_ticker, peer_ticker, as_of_date, run_id, source_file, metric_key, value_num, is_target)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            ("IBM", "IBM", "2025-12-31", 3, "ciq.xlsx", "total_revenue_cy_1", 1100.0, 1),
            ("IBM", "IBM", "2025-12-31", 3, "ciq.xlsx", "total_revenue_cy_2", 1200.0, 1),
        ],
    )
    conn.commit()
    conn.close()

    out = ciq_adapter.get_ciq_snapshot("IBM")

    assert out is not None
    assert out["revenue_fy1"] == pytest.approx(1_100_000_000.0)
    assert out["revenue_fy2"] == pytest.approx(1_200_000_000.0)
