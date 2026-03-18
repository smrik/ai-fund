"""Tests for Fama-French factor exposure decomposition."""
import pytest
from dataclasses import fields
from unittest.mock import MagicMock, patch

from src.stage_02_valuation.factor_model import (
    FactorExposure,
    decompose_factor_exposure,
    get_factor_summary_text,
)


# ---------------------------------------------------------------------------
# FactorExposure dataclass tests
# ---------------------------------------------------------------------------

def test_factor_exposure_dataclass_fields():
    """FactorExposure must have all required fields."""
    field_names = {f.name for f in fields(FactorExposure)}
    required = {
        "ticker",
        "market_beta",
        "size_beta",
        "value_beta",
        "momentum_beta",
        "r_squared",
        "annualized_alpha",
        "factor_attribution",
        "available",
    }
    assert required.issubset(field_names)


# ---------------------------------------------------------------------------
# decompose_factor_exposure — no-network path (mock yfinance)
# ---------------------------------------------------------------------------

def test_decompose_no_data_returns_unavailable():
    """When yfinance returns an empty DataFrame, returns FactorExposure with available=False."""
    import pandas as pd

    mock_ticker = MagicMock()
    mock_ticker.history.return_value = pd.DataFrame()

    with patch("yfinance.Ticker", return_value=mock_ticker):
        result = decompose_factor_exposure("AAPL", lookback_days=252)

    assert isinstance(result, FactorExposure)
    assert result.available is False


# ---------------------------------------------------------------------------
# get_factor_summary_text tests
# ---------------------------------------------------------------------------

def _make_available_exposure(ticker: str = "MSFT") -> FactorExposure:
    """Build a minimal FactorExposure instance with available=True."""
    return FactorExposure(
        ticker=ticker,
        market_beta=1.10,
        size_beta=-0.15,
        value_beta=0.05,
        profitability_beta=0.30,
        investment_beta=-0.08,
        momentum_beta=0.22,
        r_squared=0.72,
        annualized_alpha=0.025,
        lookback_days=252,
        as_of_date="2026-03-17",
        available=True,
        error=None,
        factor_attribution={"Mkt_RF": 0.6, "SMB": 0.2, "HML": 0.1, "Mom": 0.1},
    )


def test_factor_summary_text_returns_string():
    """get_factor_summary_text returns a non-empty string for an available exposure."""
    exposure = _make_available_exposure()
    text = get_factor_summary_text(exposure)
    assert isinstance(text, str)
    assert len(text) > 0
    assert "MSFT" in text


def test_factor_summary_text_unavailable():
    """get_factor_summary_text does not raise when exposure is unavailable."""
    unavailable = FactorExposure(
        ticker="FAIL",
        market_beta=None,
        size_beta=None,
        value_beta=None,
        profitability_beta=None,
        investment_beta=None,
        momentum_beta=None,
        r_squared=None,
        annualized_alpha=None,
        lookback_days=252,
        as_of_date="2026-03-17",
        available=False,
        error="insufficient data",
    )
    text = get_factor_summary_text(unavailable)
    assert isinstance(text, str)
    assert len(text) > 0
    assert "FAIL" in text


@pytest.mark.live
def test_decompose_exception_safe():
    """Even if yfinance raises, decompose_factor_exposure returns available=False."""
    with patch("yfinance.Ticker", side_effect=Exception("network error")):
        result = decompose_factor_exposure("AAPL", lookback_days=252)

    assert isinstance(result, FactorExposure)
    assert result.available is False
