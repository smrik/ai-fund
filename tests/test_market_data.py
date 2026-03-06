"""
Tests for get_historical_financials() in src/data/market_data.py.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.data.market_data import get_historical_financials


def test_historical_financials_returns_revenue_series():
    result = get_historical_financials("MSFT")
    assert "revenue" in result
    assert isinstance(result["revenue"], list)
    assert len(result["revenue"]) >= 1  # at least 1 year


def test_historical_financials_returns_cagr():
    result = get_historical_financials("MSFT")
    # Either a float or None (None if only 1 year of data)
    assert result["revenue_cagr_3yr"] is None or isinstance(result["revenue_cagr_3yr"], float)


def test_historical_financials_returns_averages():
    result = get_historical_financials("MSFT")
    for key in ["op_margin_avg_3yr", "capex_pct_avg_3yr", "da_pct_avg_3yr", "effective_tax_rate_avg"]:
        assert key in result
        # Must be None or a float in plausible range
        val = result[key]
        if val is not None:
            assert isinstance(val, float)
            assert -0.5 < val < 2.0  # sanity bounds


def test_historical_financials_never_raises():
    # Bad ticker should return dict of Nones, not raise
    result = get_historical_financials("INVALIDTICKER_XYZ")
    assert isinstance(result, dict)
    assert "revenue_cagr_3yr" in result


def test_capex_is_positive():
    result = get_historical_financials("MSFT")
    for v in result.get("capex", []):
        assert v >= 0, "capex should be positive"


def test_cost_of_debt_in_bounds():
    result = get_historical_financials("JPM")  # high debt company
    kd = result.get("cost_of_debt_derived")
    if kd is not None:
        assert 0.02 <= kd <= 0.15


# ── Unit tests with mocked data (no network) ──────────────────────

import unittest.mock as mock
import pandas as pd
import numpy as np


def _make_financials():
    """Build a minimal yfinance-style P&L DataFrame."""
    dates = pd.to_datetime(["2023-12-31", "2022-12-31", "2021-12-31"])
    data = {
        "Total Revenue": [200e9, 180e9, 160e9],
        "Operating Income": [60e9, 54e9, 48e9],
        "Interest Expense": [2e9, 1.8e9, 1.6e9],
        "Tax Provision": [12e9, 10e9, 9e9],
        "Pretax Income": [55e9, 50e9, 45e9],
    }
    df = pd.DataFrame(data, index=pd.Index(dates, name=""))
    return df.T  # rows=items, cols=dates


def _make_cashflow():
    """Build a minimal yfinance-style cash flow DataFrame."""
    dates = pd.to_datetime(["2023-12-31", "2022-12-31", "2021-12-31"])
    data = {
        "Capital Expenditure": [-10e9, -9e9, -8e9],
        "Depreciation And Amortization": [8e9, 7e9, 6e9],
    }
    df = pd.DataFrame(data, index=pd.Index(dates, name=""))
    return df.T


def _make_balance():
    """Build a minimal yfinance-style balance sheet DataFrame."""
    dates = pd.to_datetime(["2023-12-31", "2022-12-31", "2021-12-31"])
    data = {
        "Current Assets": [80e9, 72e9, 64e9],
        "Current Liabilities": [40e9, 36e9, 32e9],
        "Cash And Cash Equivalents": [20e9, 18e9, 16e9],
        "Total Debt": [50e9, 45e9, 40e9],
    }
    df = pd.DataFrame(data, index=pd.Index(dates, name=""))
    return df.T


def test_historical_financials_mocked_revenue():
    """Mocked: revenue series is extracted correctly."""
    ticker_mock = mock.MagicMock()
    ticker_mock.financials = _make_financials()
    ticker_mock.cashflow = _make_cashflow()
    ticker_mock.balance_sheet = _make_balance()

    with mock.patch("yfinance.Ticker", return_value=ticker_mock):
        result = get_historical_financials("FAKE")

    assert result["revenue"] == [200e9, 180e9, 160e9]


def test_historical_financials_mocked_cagr():
    """Mocked: 3yr revenue CAGR is correct: (200/160)^(1/2) - 1 ≈ 0.1180."""
    ticker_mock = mock.MagicMock()
    ticker_mock.financials = _make_financials()
    ticker_mock.cashflow = _make_cashflow()
    ticker_mock.balance_sheet = _make_balance()

    with mock.patch("yfinance.Ticker", return_value=ticker_mock):
        result = get_historical_financials("FAKE")

    expected = round((200e9 / 160e9) ** (1 / 2) - 1, 4)
    assert result["revenue_cagr_3yr"] == expected


def test_historical_financials_mocked_capex_positive():
    """Mocked: capex values are positive (abs applied to negative cashflow)."""
    ticker_mock = mock.MagicMock()
    ticker_mock.financials = _make_financials()
    ticker_mock.cashflow = _make_cashflow()
    ticker_mock.balance_sheet = _make_balance()

    with mock.patch("yfinance.Ticker", return_value=ticker_mock):
        result = get_historical_financials("FAKE")

    for v in result["capex"]:
        assert v >= 0


def test_historical_financials_mocked_op_margin():
    """Mocked: operating margin avg ≈ 0.30 (60/200 = 54/180 = 48/160 = 0.30)."""
    ticker_mock = mock.MagicMock()
    ticker_mock.financials = _make_financials()
    ticker_mock.cashflow = _make_cashflow()
    ticker_mock.balance_sheet = _make_balance()

    with mock.patch("yfinance.Ticker", return_value=ticker_mock):
        result = get_historical_financials("FAKE")

    assert result["op_margin_avg_3yr"] is not None
    assert abs(result["op_margin_avg_3yr"] - 0.30) < 0.01


def test_historical_financials_mocked_tax_rate():
    """Mocked: effective tax rate is clamped to [0.05, 0.40] bounds."""
    ticker_mock = mock.MagicMock()
    ticker_mock.financials = _make_financials()
    ticker_mock.cashflow = _make_cashflow()
    ticker_mock.balance_sheet = _make_balance()

    with mock.patch("yfinance.Ticker", return_value=ticker_mock):
        result = get_historical_financials("FAKE")

    t = result["effective_tax_rate_avg"]
    if t is not None:
        assert 0.05 <= t <= 0.40
