"""Tests for src/portfolio/tracker.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
import pandas as pd
from unittest.mock import patch, MagicMock

from src.portfolio.tracker import PortfolioTracker


@pytest.fixture()
def tracker(tmp_path):
    """Fresh tracker with an isolated in-memory-style DB per test."""
    db = tmp_path / "test_portfolio.db"
    return PortfolioTracker(db_path=db)


# ── add_position ──────────────────────────────────────────────────────────────

def test_add_long_position(tracker):
    result = tracker.add_position("IBM", "LONG", 100, 185.50)
    assert result["action"] == "added"
    df = tracker.get_positions()
    assert len(df) == 1
    assert df.iloc[0]["ticker"] == "IBM"
    assert df.iloc[0]["direction"] == "LONG"
    assert df.iloc[0]["shares"] == 100
    assert abs(df.iloc[0]["avg_cost"] - 185.50) < 0.001


def test_add_short_position(tracker):
    tracker.add_position("AAPL", "SHORT", 50, 210.00)
    df = tracker.get_positions()
    assert df.iloc[0]["direction"] == "SHORT"


def test_add_to_existing_position_computes_weighted_avg(tracker):
    tracker.add_position("IBM", "LONG", 100, 180.00)
    tracker.add_position("IBM", "LONG", 100, 200.00)
    df = tracker.get_positions()
    assert len(df) == 1
    assert df.iloc[0]["shares"] == 200
    # Weighted avg: (100×180 + 100×200) / 200 = 190
    assert abs(df.iloc[0]["avg_cost"] - 190.00) < 0.001


def test_add_multiple_tickers(tracker):
    tracker.add_position("IBM", "LONG", 100, 185.50)
    tracker.add_position("MSFT", "SHORT", 50, 415.00)
    df = tracker.get_positions()
    assert len(df) == 2
    assert set(df["ticker"]) == {"IBM", "MSFT"}


def test_add_invalid_direction_raises(tracker):
    with pytest.raises(ValueError, match="direction"):
        tracker.add_position("IBM", "HOLD", 100, 185.50)


def test_add_zero_shares_raises(tracker):
    with pytest.raises(ValueError, match="shares"):
        tracker.add_position("IBM", "LONG", 0, 185.50)


def test_add_negative_cost_raises(tracker):
    with pytest.raises(ValueError, match="cost_basis"):
        tracker.add_position("IBM", "LONG", 100, -5.0)


# ── close_position ────────────────────────────────────────────────────────────

def test_close_long_position_full(tracker):
    tracker.add_position("IBM", "LONG", 100, 180.00)
    result = tracker.close_position("IBM", 100, 200.00)
    assert result["action"] == "closed"
    assert result["realized_pnl"] == pytest.approx(100 * 20.0)
    df = tracker.get_positions()
    assert df.empty


def test_close_short_position_full(tracker):
    tracker.add_position("AAPL", "SHORT", 50, 200.00)
    result = tracker.close_position("AAPL", 50, 180.00)
    # Profit on short: (200 - 180) × 50 = 1000
    assert result["realized_pnl"] == pytest.approx(50 * 20.0)
    assert result["action"] == "closed"


def test_close_partial_position(tracker):
    tracker.add_position("IBM", "LONG", 100, 180.00)
    result = tracker.close_position("IBM", 40, 200.00)
    assert result["action"] == "partial_close"
    assert result["shares_closed"] == 40
    df = tracker.get_positions()
    assert df.iloc[0]["shares"] == 60


def test_close_nonexistent_position(tracker):
    result = tracker.close_position("ZZZZ", 100, 50.00)
    assert result["action"] == "error"


def test_closed_position_logged_to_history(tracker):
    tracker.add_position("IBM", "LONG", 100, 180.00)
    tracker.close_position("IBM", 100, 195.00)
    hist = tracker.get_position_history()
    assert len(hist) == 1
    assert hist.iloc[0]["ticker"] == "IBM"
    assert hist.iloc[0]["realized_pnl"] == pytest.approx(100 * 15.0)


# ── update_prices ─────────────────────────────────────────────────────────────

def test_update_prices_populates_fields(tracker):
    tracker.add_position("IBM", "LONG", 100, 185.00)

    mock_df = pd.DataFrame({"Close": [195.0]}, index=["IBM"])
    # yf.download returns a DataFrame; mock it
    with patch("yfinance.download") as mock_dl:
        mock_dl.return_value = pd.DataFrame({"Close": [195.0]})
        n = tracker.update_prices()

    # Just verify it runs without error
    assert n == 1


# ── get_risk_metrics ──────────────────────────────────────────────────────────

def test_risk_metrics_empty_portfolio(tracker):
    risk = tracker.get_risk_metrics()
    assert risk["position_count"] == 0
    assert risk["gross_exposure_pct"] == 0.0
    assert risk["net_exposure_pct"] == 0.0


def test_risk_metrics_long_only(tracker):
    tracker.add_position("IBM", "LONG", 1000, 100.00)

    # Manually set market value to known value for deterministic test
    conn = tracker._conn()
    conn.execute("UPDATE positions SET current_price=100, market_value=100000, unrealized_pnl=0, weight_pct=100 WHERE ticker='IBM'")
    conn.commit()
    conn.close()

    risk = tracker.get_risk_metrics()
    assert risk["position_count"] == 1
    assert risk["long_exposure_usd"] == pytest.approx(100000.0)
    assert risk["short_exposure_usd"] == pytest.approx(0.0)
    # gross_pct = 100000 / nav ≈ non-zero
    assert risk["gross_exposure_pct"] > 0


def test_risk_metrics_alerts_stop_loss(tracker):
    tracker.add_position("IBM", "LONG", 100, 200.00)

    conn = tracker._conn()
    conn.execute("UPDATE positions SET current_price=160, market_value=16000, unrealized_pnl=-4000, pnl_pct=-0.20, weight_pct=15 WHERE ticker='IBM'")
    conn.commit()
    conn.close()

    risk = tracker.get_risk_metrics()
    # pnl_pct = -0.20 = -20%, STOP_LOSS_REVIEW_PCT = -15%
    assert any("STOP-LOSS" in a for a in risk["alerts"])


# ── export_csv ────────────────────────────────────────────────────────────────

def test_export_csv_creates_file(tracker, tmp_path):
    tracker.add_position("IBM", "LONG", 100, 185.50)
    out = tmp_path / "positions.csv"
    tracker.export_csv(path=out)
    assert out.exists()
    df = pd.read_csv(out)
    assert "IBM" in df["ticker"].values


# ── position direction flip (add opposite direction) ──────────────────────────

def test_add_opposite_direction_reduces_position(tracker):
    tracker.add_position("IBM", "LONG", 100, 180.00)
    result = tracker.add_position("IBM", "SHORT", 100, 200.00)
    # Opposite direction → close trade
    assert result.get("action") in ("closed", "partial_close")
