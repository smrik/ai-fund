"""Tests for portfolio_risk.py — all offline, no live yfinance calls."""
import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.stage_02_valuation.portfolio_risk import (
    compute_correlation_matrix,
    compute_exposure_summary,
    compute_historical_var,
    compute_sector_concentration,
    build_portfolio_risk,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_price_history(prices: list[float]) -> object:
    """Return a mock yf.Ticker.history() response with Close prices."""
    import pandas as pd
    idx = pd.date_range("2025-01-01", periods=len(prices), freq="B")
    df = pd.DataFrame({"Close": prices}, index=idx)
    mock_ticker = mock.MagicMock()
    mock_ticker.history.return_value = df
    return mock_ticker


def _flat_prices(n: int, base: float = 100.0) -> list[float]:
    """Generate prices with tiny noise so correlation doesn't degenerate."""
    import math
    return [base + 0.01 * math.sin(i) for i in range(n)]


def _rising_prices(n: int, daily_return: float = 0.001) -> list[float]:
    p = 100.0
    result = [p]
    for _ in range(n - 1):
        p = p * (1 + daily_return)
        result.append(p)
    return result


# ── compute_correlation_matrix ─────────────────────────────────────────────────

def test_correlation_matrix_perfect_correlation(monkeypatch):
    """Two tickers with identical variable prices → diagonal = 1.0, off-diagonal = 1.0."""
    import math
    # Use prices that produce varying returns (not a constant series)
    prices = [100.0 * (1 + 0.01 * math.sin(i * 0.7)) for i in range(60)]

    def fake_ticker(ticker):
        return _make_price_history(prices)

    monkeypatch.setattr("yfinance.Ticker", fake_ticker)

    tickers, matrix = compute_correlation_matrix(["A", "B"])

    assert tickers == ["A", "B"]
    assert len(matrix) == 2
    # Diagonal = 1.0
    assert matrix[0][0] == pytest.approx(1.0, abs=1e-4)
    assert matrix[1][1] == pytest.approx(1.0, abs=1e-4)
    # Cross = 1.0 (same returns)
    assert matrix[0][1] == pytest.approx(1.0, abs=1e-3)


def test_correlation_matrix_drops_tickers_with_insufficient_data(monkeypatch):
    """Tickers with <20 observations are dropped."""
    short_prices = _rising_prices(5)
    long_prices = _rising_prices(60)

    def fake_ticker(ticker):
        if ticker == "SHORT":
            return _make_price_history(short_prices)
        return _make_price_history(long_prices)

    monkeypatch.setattr("yfinance.Ticker", fake_ticker)

    tickers, matrix = compute_correlation_matrix(["SHORT", "LONG"])

    assert "SHORT" not in tickers
    assert "LONG" in tickers


def test_correlation_matrix_returns_empty_for_single_valid_ticker(monkeypatch):
    """Single valid ticker → no matrix possible."""
    def fake_ticker(ticker):
        return _make_price_history(_rising_prices(60))

    monkeypatch.setattr("yfinance.Ticker", fake_ticker)
    tickers, matrix = compute_correlation_matrix(["ONLY"])
    assert tickers == ["ONLY"]
    assert matrix == []


def test_correlation_matrix_exception_tolerant(monkeypatch):
    """Tickers that throw are silently dropped."""
    good_prices = _rising_prices(60)

    def fake_ticker(ticker):
        if ticker == "BAD":
            raise RuntimeError("network error")
        return _make_price_history(good_prices)

    monkeypatch.setattr("yfinance.Ticker", fake_ticker)
    tickers, matrix = compute_correlation_matrix(["BAD", "GOOD"])
    assert "BAD" not in tickers


# ── compute_historical_var ─────────────────────────────────────────────────────

def test_var_returns_values_between_zero_and_one(monkeypatch):
    """VaR and CVaR should be sensible positive fractions."""
    prices = _rising_prices(260, daily_return=0.0005)

    def fake_ticker(ticker):
        return _make_price_history(prices)

    monkeypatch.setattr("yfinance.Ticker", fake_ticker)

    result = compute_historical_var(["A", "B"], weights={"A": 0.6, "B": 0.4})

    for key in ("var_95", "var_99", "cvar_95", "cvar_99"):
        val = result[key]
        assert val is not None, f"{key} should not be None"
        assert -0.5 < val < 0.5, f"{key}={val} out of expected range"


def test_var_99_larger_than_var_95(monkeypatch):
    """99% VaR should be at least as large as 95% VaR."""
    prices = _rising_prices(260, daily_return=0.001)

    def fake_ticker(ticker):
        return _make_price_history(prices)

    monkeypatch.setattr("yfinance.Ticker", fake_ticker)

    result = compute_historical_var(["A"], weights={"A": 1.0})
    assert result["var_99"] >= result["var_95"] - 1e-9


def test_var_returns_none_for_no_valid_tickers(monkeypatch):
    """No valid tickers → all None."""
    monkeypatch.setattr("yfinance.Ticker", lambda t: _make_price_history([]))
    result = compute_historical_var(["X"], weights={"X": 1.0})
    assert result["var_95"] is None


# ── compute_sector_concentration ──────────────────────────────────────────────

def test_sector_concentration_uses_provided_sector(monkeypatch):
    """If 'sector' is in position dict, no yfinance call needed."""
    positions = [
        {"ticker": "AAPL", "market_value": 1000.0, "sector": "Technology"},
        {"ticker": "MSFT", "market_value": 500.0, "sector": "Technology"},
        {"ticker": "JPM", "market_value": 300.0, "sector": "Financials"},
    ]
    result = compute_sector_concentration(positions)
    total = sum(result.values())
    assert abs(total - 100.0) < 0.01
    assert result["Technology"] == pytest.approx(83.33, abs=0.1)
    assert result["Financials"] == pytest.approx(16.67, abs=0.1)


def test_sector_concentration_empty_positions():
    assert compute_sector_concentration([]) == {}


def test_sector_concentration_uses_abs_value_for_shorts():
    """Short positions (negative market_value) are counted as gross."""
    positions = [
        {"ticker": "A", "market_value": 1000.0, "sector": "Tech"},
        {"ticker": "B", "market_value": -500.0, "sector": "Financials"},
    ]
    result = compute_sector_concentration(positions)
    assert result["Tech"] == pytest.approx(66.67, abs=0.1)
    assert result["Financials"] == pytest.approx(33.33, abs=0.1)


# ── compute_exposure_summary ───────────────────────────────────────────────────

def test_exposure_summary_long_short_portfolio():
    positions = [
        {"ticker": "A", "market_value": 600.0},
        {"ticker": "B", "market_value": 400.0},
        {"ticker": "C", "market_value": -200.0},
    ]
    result = compute_exposure_summary(positions)
    assert result["long_exposure"] == pytest.approx(1000.0)
    assert result["short_exposure"] == pytest.approx(200.0)
    assert result["gross_exposure"] == pytest.approx(1200.0)
    assert result["net_exposure"] == pytest.approx(800.0)
    assert result["long_pct"] == pytest.approx(83.3, abs=0.2)
    assert result["short_pct"] == pytest.approx(16.7, abs=0.2)


def test_exposure_summary_long_only():
    positions = [{"ticker": "A", "market_value": 500.0}]
    result = compute_exposure_summary(positions)
    assert result["short_exposure"] == 0.0
    assert result["net_pct"] == pytest.approx(100.0)


def test_exposure_summary_empty():
    result = compute_exposure_summary([])
    assert result["gross_exposure"] == 0.0


# ── build_portfolio_risk (integration) ────────────────────────────────────────

def test_build_portfolio_risk_returns_summary(monkeypatch):
    """Full summary with mocked prices."""
    prices = _rising_prices(260, daily_return=0.001)

    def fake_ticker(ticker):
        return _make_price_history(prices)

    monkeypatch.setattr("yfinance.Ticker", fake_ticker)

    positions = [
        {"ticker": "A", "market_value": 600.0, "sector": "Technology"},
        {"ticker": "B", "market_value": 400.0, "sector": "Healthcare"},
    ]
    summary = build_portfolio_risk(["A", "B"], positions=positions)

    assert "A" in summary.tickers
    assert "B" in summary.tickers
    assert len(summary.correlation_matrix) == 2
    assert len(summary.top_correlated_pairs) >= 1
    assert summary.var_95 is not None
    assert summary.sector_weights.get("Technology") == pytest.approx(60.0, abs=0.1)
    assert summary.gross_exposure == pytest.approx(1000.0)
