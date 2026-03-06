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
