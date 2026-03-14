"""Tests for src/stage_01_screening/stage2_short_filter.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sqlite3
import pytest
import pandas as pd

from src.stage_01_screening.stage2_short_filter import (
    _score_roic_deterioration,
    _score_revenue_deceleration,
    _score_margin_compression,
    _score_leverage_stress,
    _score_dso_trend,
    run_stage2_short_filter,
)


# ── Scoring function unit tests ───────────────────────────────────────────────

def _row(**kwargs) -> pd.Series:
    return pd.Series(kwargs)


class TestScoreRoicDeterioration:
    def test_clear_declining_trend(self):
        row = _row(roic_y1=0.05, roic_y2=0.10, roic_y3=0.15)
        assert _score_roic_deterioration(row) == pytest.approx(1.0)

    def test_roic_below_threshold(self):
        row = _row(roic_y1=-0.02, roic_y2=float("nan"), roic_y3=float("nan"))
        score = _score_roic_deterioration(row)
        assert score > 0

    def test_roic_high_no_signal(self):
        row = _row(roic_y1=0.20, roic_y2=0.18, roic_y3=0.15)  # rising
        score = _score_roic_deterioration(row)
        assert score == 0.0

    def test_missing_roic_returns_zero(self):
        row = _row(roic_y1=float("nan"), roic_y2=float("nan"), roic_y3=float("nan"))
        assert _score_roic_deterioration(row) == 0.0

    def test_score_bounded_zero_to_one(self):
        row = _row(roic_y1=-0.50, roic_y2=0.10, roic_y3=0.20)
        assert 0.0 <= _score_roic_deterioration(row) <= 1.0


class TestScoreRevenueDeceleration:
    def test_declining_revenue_high_score(self):
        row = _row(rev_y1=800.0, rev_y4=1000.0)
        score = _score_revenue_deceleration(row)
        assert score > 0

    def test_growing_revenue_zero_score(self):
        row = _row(rev_y1=1200.0, rev_y4=1000.0)
        assert _score_revenue_deceleration(row) == 0.0

    def test_severe_decline_capped_at_one(self):
        row = _row(rev_y1=100.0, rev_y4=1000.0)  # -90%
        assert _score_revenue_deceleration(row) == pytest.approx(1.0)

    def test_missing_values_returns_zero(self):
        row = _row(rev_y1=float("nan"), rev_y4=float("nan"))
        assert _score_revenue_deceleration(row) == 0.0


class TestScoreMarginCompression:
    def test_significant_compression(self):
        # op_y1 / rev_y1 = 0.05; op_y3 / rev_y4 = 0.15 → 10pp compression
        row = _row(op_y1=50.0, op_y3=150.0, rev_y1=1000.0, rev_y4=1000.0)
        score = _score_margin_compression(row)
        assert score > 0

    def test_no_compression(self):
        row = _row(op_y1=150.0, op_y3=100.0, rev_y1=1000.0, rev_y4=1000.0)
        assert _score_margin_compression(row) == 0.0

    def test_score_bounded(self):
        row = _row(op_y1=0.0, op_y3=500.0, rev_y1=1000.0, rev_y4=1000.0)
        assert _score_margin_compression(row) <= 1.0


class TestScoreLeverageStress:
    def test_high_leverage(self):
        row = _row(debt_to_ebitda=5.0)
        assert _score_leverage_stress(row) == pytest.approx(1.0)

    def test_low_leverage(self):
        row = _row(debt_to_ebitda=1.5)
        assert _score_leverage_stress(row) == 0.0

    def test_borderline(self):
        row = _row(debt_to_ebitda=3.5)
        score = _score_leverage_stress(row)
        assert 0.0 < score < 1.0

    def test_missing_returns_zero(self):
        row = _row(debt_to_ebitda=float("nan"))
        assert _score_leverage_stress(row) == 0.0


class TestScoreDsoTrend:
    def test_rising_dso(self):
        row = _row(dso_y1=60.0, dso_y3=45.0)  # +33% rise
        score = _score_dso_trend(row)
        assert score > 0

    def test_stable_dso(self):
        row = _row(dso_y1=45.0, dso_y3=45.0)
        assert _score_dso_trend(row) == 0.0

    def test_falling_dso_zero(self):
        row = _row(dso_y1=40.0, dso_y3=50.0)
        assert _score_dso_trend(row) == 0.0

    def test_missing_returns_zero(self):
        row = _row(dso_y1=float("nan"), dso_y3=float("nan"))
        assert _score_dso_trend(row) == 0.0


# ── Integration test with in-memory SQLite ────────────────────────────────────

def _populate_test_db(conn: sqlite3.Connection):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ciq_valuation_snapshot (
            ticker TEXT, as_of_date TEXT, fcf_yield REAL, debt_to_ebitda REAL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ciq_long_form (
            ticker TEXT, metric_key TEXT, value_num REAL,
            period_date TEXT, run_id INTEGER
        )
    """)
    conn.executemany(
        "INSERT INTO ciq_valuation_snapshot VALUES (?, ?, ?, ?)",
        [
            ("BADCO",  "2025-12-31", 0.01,  4.5),  # high leverage, low FCF
            ("GOODCO", "2025-12-31", 0.08,  1.2),  # healthy
        ],
    )
    # BADCO: declining ROIC and revenue
    conn.executemany(
        "INSERT INTO ciq_long_form (ticker, metric_key, value_num, period_date) VALUES (?, ?, ?, ?)",
        [
            # BADCO revenue: declining
            ("BADCO",  "revenue",          900.0, "2024-12-31"),
            ("BADCO",  "revenue",          950.0, "2023-12-31"),
            ("BADCO",  "revenue",         1000.0, "2022-12-31"),
            ("BADCO",  "revenue",         1100.0, "2021-12-31"),
            # BADCO ROIC: declining
            ("BADCO",  "roic",              0.03,  "2024-12-31"),
            ("BADCO",  "roic",              0.06,  "2023-12-31"),
            ("BADCO",  "roic",              0.09,  "2022-12-31"),
            # BADCO operating income: compressing
            ("BADCO",  "operating_income",  36.0, "2024-12-31"),
            ("BADCO",  "operating_income",  80.0, "2022-12-31"),
            # GOODCO: growing revenue
            ("GOODCO", "revenue",          1200.0, "2024-12-31"),
            ("GOODCO", "revenue",          1100.0, "2023-12-31"),
            ("GOODCO", "revenue",          1000.0, "2022-12-31"),
            ("GOODCO", "revenue",           900.0, "2021-12-31"),
            # GOODCO ROIC: high and stable
            ("GOODCO", "roic",              0.18, "2024-12-31"),
            ("GOODCO", "roic",              0.17, "2023-12-31"),
            ("GOODCO", "roic",              0.16, "2022-12-31"),
        ],
    )
    conn.commit()


def test_run_stage2_short_filter_identifies_badco(monkeypatch, tmp_path):
    """BADCO (declining ROIC, shrinking revenue, high leverage) should be surfaced."""
    import src.stage_01_screening.stage2_short_filter as module

    test_db = tmp_path / "test.db"
    conn = sqlite3.connect(str(test_db))
    _populate_test_db(conn)
    conn.close()

    # Patch DB_PATH and OUTPUT_DIR
    monkeypatch.setattr(module, "DB_PATH", test_db)
    monkeypatch.setattr(module, "OUTPUT_DIR", tmp_path)

    result = run_stage2_short_filter(export_csv=False)
    assert result is not None
    assert not result.empty
    assert "BADCO" in result["ticker"].values
    # GOODCO should NOT appear (growing revenue, high ROIC)
    assert "GOODCO" not in result["ticker"].values


def test_run_stage2_short_filter_sorted_by_score(monkeypatch, tmp_path):
    """Results should be sorted by short_score descending."""
    import src.stage_01_screening.stage2_short_filter as module

    test_db = tmp_path / "test.db"
    conn = sqlite3.connect(str(test_db))
    _populate_test_db(conn)
    conn.close()

    monkeypatch.setattr(module, "DB_PATH", test_db)
    monkeypatch.setattr(module, "OUTPUT_DIR", tmp_path)

    result = run_stage2_short_filter(export_csv=False)
    if result is not None and len(result) > 1:
        scores = result["short_score"].tolist()
        assert scores == sorted(scores, reverse=True)


def test_run_stage2_short_filter_csv_export(monkeypatch, tmp_path):
    """When export_csv=True, a CSV should be written."""
    import src.stage_01_screening.stage2_short_filter as module

    test_db = tmp_path / "test.db"
    conn = sqlite3.connect(str(test_db))
    _populate_test_db(conn)
    conn.close()

    monkeypatch.setattr(module, "DB_PATH", test_db)
    monkeypatch.setattr(module, "OUTPUT_DIR", tmp_path)

    run_stage2_short_filter(export_csv=True)
    out = tmp_path / "screens" / "stage2_short_list.csv"
    assert out.exists()


def test_run_stage2_short_filter_empty_db(monkeypatch, tmp_path):
    """Should return None gracefully when no snapshot data exists."""
    import src.stage_01_screening.stage2_short_filter as module

    test_db = tmp_path / "empty.db"
    conn = sqlite3.connect(str(test_db))
    conn.execute("CREATE TABLE IF NOT EXISTS ciq_valuation_snapshot (ticker TEXT, as_of_date TEXT, fcf_yield REAL, debt_to_ebitda REAL)")
    conn.execute("CREATE TABLE IF NOT EXISTS ciq_long_form (ticker TEXT, metric_key TEXT, value_num REAL, period_date TEXT, run_id INTEGER)")
    conn.commit()
    conn.close()

    monkeypatch.setattr(module, "DB_PATH", test_db)
    monkeypatch.setattr(module, "OUTPUT_DIR", tmp_path)

    result = run_stage2_short_filter(export_csv=False)
    assert result is None or result.empty
