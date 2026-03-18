"""Tests for FRED macro data client."""
import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# test_get_macro_snapshot_no_api_key
# ---------------------------------------------------------------------------

def test_get_macro_snapshot_no_api_key():
    """When FRED_API_KEY is not set, returns available=False with meaningful error."""
    with patch.dict("os.environ", {}, clear=True):
        # Ensure the key is absent
        import os
        os.environ.pop("FRED_API_KEY", None)

        from src.stage_00_data.fred_client import get_macro_snapshot
        result = get_macro_snapshot()

    assert result["available"] is False
    assert result["error"] is not None
    assert len(result["error"]) > 0
    assert result["series"] == {}


def test_get_macro_snapshot_fredapi_not_installed():
    """When fredapi is not installed (ImportError), returns available=False."""
    import builtins
    real_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "fredapi":
            raise ImportError("No module named 'fredapi'")
        return real_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=mock_import):
        with patch.dict("os.environ", {"FRED_API_KEY": "testkey"}):
            from src.stage_00_data import fred_client
            import importlib
            importlib.reload(fred_client)
            result = fred_client.get_macro_snapshot()

    assert result["available"] is False
    assert result["error"] is not None


def test_get_yield_curve_no_api_key():
    """get_yield_curve returns available=False gracefully when no API key."""
    import os
    os.environ.pop("FRED_API_KEY", None)

    with patch.dict("os.environ", {}, clear=True):
        from src.stage_00_data.fred_client import get_yield_curve
        result = get_yield_curve()

    assert result["available"] is False
    assert result["maturities"] == []
    assert result["error"] is not None


def test_get_regime_indicators_no_api_key():
    """get_regime_indicators returns available=False gracefully when no API key."""
    import os
    os.environ.pop("FRED_API_KEY", None)

    with patch.dict("os.environ", {}, clear=True):
        from src.stage_00_data.fred_client import get_regime_indicators
        result = get_regime_indicators()

    assert result["available"] is False
    assert result["error"] is not None
    # Structural keys must be present even on failure
    assert "slope_2s10s" in result
    assert "vix" in result


@pytest.mark.live
def test_get_macro_snapshot_with_mock_fred():
    """Mock fredapi.Fred so no network call is made; verify structure."""
    import pandas as pd

    mock_series = pd.Series([4.2, 4.3], index=["2025-01-01", "2025-01-02"])

    mock_fred_instance = MagicMock()
    mock_fred_instance.get_series.return_value = mock_series

    mock_fred_class = MagicMock(return_value=mock_fred_instance)

    mock_fredapi_module = MagicMock()
    mock_fredapi_module.Fred = mock_fred_class

    with patch.dict("os.environ", {"FRED_API_KEY": "dummy_key_for_test"}):
        with patch.dict("sys.modules", {"fredapi": mock_fredapi_module}):
            # Reload to pick up the patched import
            import importlib
            from src.stage_00_data import fred_client
            importlib.reload(fred_client)

            result = fred_client.get_macro_snapshot()

    assert result["available"] is True
    assert result["error"] is None
    assert isinstance(result["series"], dict)
    assert len(result["series"]) > 0

    # Spot-check at least one expected series key is present
    expected_keys = {"DGS10", "FEDFUNDS", "VIXCLS"}
    assert expected_keys.issubset(result["series"].keys())
