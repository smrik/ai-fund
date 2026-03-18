"""
FRED Economic Data Client.
Fetches macro series from the Federal Reserve Bank of St. Louis via the fredapi package.
API key is read from the FRED_API_KEY environment variable.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

MACRO_SERIES: dict[str, str] = {
    "DGS10":          "10Y Treasury",
    "DGS2":           "2Y Treasury",
    "T10Y2Y":         "10Y-2Y Spread",
    "FEDFUNDS":       "Fed Funds Rate",
    "VIXCLS":         "VIX",
    "BAMLC0A4CBBB":   "IG Credit Spread (OAS)",
    "BAMLH0A0HYM2":   "HY Credit Spread (OAS)",
    "ICSA":           "Initial Jobless Claims",
    "CPIAUCSL":       "CPI",
    "INDPRO":         "Industrial Production",
    "RSAFS":          "Retail Sales",
    "UNRATE":         "Unemployment Rate",
}

YIELD_CURVE_SERIES: list[tuple[str, str, float]] = [
    # (series_id, label, years)
    ("DGS1MO",  "1M",   1/12),
    ("DGS3MO",  "3M",   0.25),
    ("DGS6MO",  "6M",   0.5),
    ("DGS1",    "1Y",   1.0),
    ("DGS2",    "2Y",   2.0),
    ("DGS5",    "5Y",   5.0),
    ("DGS10",   "10Y",  10.0),
    ("DGS20",   "20Y",  20.0),
    ("DGS30",   "30Y",  30.0),
]


def _get_fred_client():
    """
    Return a configured fredapi.Fred instance.
    Raises ImportError if fredapi is not installed.
    Raises ValueError if FRED_API_KEY is not set.
    """
    try:
        import fredapi  # noqa: F401
        from fredapi import Fred
    except ImportError as exc:
        raise ImportError(
            "fredapi is not installed. Run: pip install fredapi"
        ) from exc

    api_key = os.environ.get("FRED_API_KEY", "").strip()
    if not api_key:
        raise ValueError(
            "FRED_API_KEY environment variable is not set. "
            "Obtain a free key at https://fred.stlouisfed.org/docs/api/api_key.html"
        )
    return Fred(api_key=api_key)


def _cache_series_values(series_id: str, series_data) -> None:
    """Write series observations to macro_series table if it exists."""
    try:
        from db.schema import get_connection
        conn = get_connection()
        fetched_at = datetime.now(timezone.utc).isoformat()
        rows = []
        for date_idx, value in series_data.items():
            if value is None:
                continue
            import math
            if isinstance(value, float) and math.isnan(value):
                continue
            rows.append((series_id, str(date_idx)[:10], float(value), fetched_at))
        if rows:
            conn.executemany(
                "INSERT OR REPLACE INTO macro_series "
                "(series_id, series_date, value, fetched_at) VALUES (?,?,?,?)",
                rows,
            )
            conn.commit()
        conn.close()
    except Exception:
        pass  # Cache is best-effort; never block callers


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_macro_snapshot(lookback_days: int = 365) -> dict:
    """
    Fetch the latest value + recent history for all macro series.

    Returns
    -------
    dict with keys:
        series    : dict[series_id -> {latest_value, latest_date, values: [(date_str, value)]}]
        as_of_date: str (ISO)
        available : bool
        error     : str | None
    """
    try:
        fred = _get_fred_client()
    except (ImportError, ValueError) as exc:
        return {"series": {}, "as_of_date": None, "available": False, "error": str(exc)}

    try:
        start_date = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
        result: dict = {}

        for series_id in MACRO_SERIES:
            try:
                data = fred.get_series(series_id, observation_start=start_date)
                if data is None or len(data) == 0:
                    result[series_id] = {
                        "latest_value": None,
                        "latest_date": None,
                        "values": [],
                    }
                    continue

                data = data.dropna()
                _cache_series_values(series_id, data)

                values = [(str(d)[:10], float(v)) for d, v in zip(data.index, data.values)]
                latest_date = str(data.index[-1])[:10]
                latest_value = float(data.iloc[-1])

                result[series_id] = {
                    "latest_value": latest_value,
                    "latest_date": latest_date,
                    "values": values,
                }
            except Exception as series_exc:
                result[series_id] = {
                    "latest_value": None,
                    "latest_date": None,
                    "values": [],
                    "error": str(series_exc),
                }

        return {
            "series": result,
            "as_of_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "available": True,
            "error": None,
        }

    except Exception as exc:
        return {"series": {}, "as_of_date": None, "available": False, "error": str(exc)}


def get_yield_curve() -> dict:
    """
    Fetch the latest yield for each maturity on the US Treasury curve.

    Returns
    -------
    dict with keys:
        maturities : list of (label, years, value)
        as_of_date : str
        available  : bool
        error      : str | None
    """
    try:
        fred = _get_fred_client()
    except (ImportError, ValueError) as exc:
        return {"maturities": [], "as_of_date": None, "available": False, "error": str(exc)}

    try:
        start_date = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
        maturities: list[tuple] = []
        as_of_dates: list[str] = []

        for series_id, label, years in YIELD_CURVE_SERIES:
            try:
                data = fred.get_series(series_id, observation_start=start_date)
                if data is not None and len(data) > 0:
                    data = data.dropna()
                    if len(data) > 0:
                        value = float(data.iloc[-1])
                        as_of_dates.append(str(data.index[-1])[:10])
                        maturities.append((label, years, value))
                        continue
            except Exception:
                pass
            maturities.append((label, years, None))

        as_of = max(as_of_dates) if as_of_dates else datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return {
            "maturities": maturities,
            "as_of_date": as_of,
            "available": True,
            "error": None,
        }

    except Exception as exc:
        return {"maturities": [], "as_of_date": None, "available": False, "error": str(exc)}


def get_regime_indicators() -> dict:
    """
    Compute derived macro regime signals from FRED data.

    Returns
    -------
    dict with keys:
        slope_2s10s      : float | None  — DGS10 minus DGS2 (bps if positive = normal)
        hy_spread        : float | None  — HY OAS
        ig_spread        : float | None  — IG OAS
        real_rate_approx : float | None  — DGS10 minus CPI YoY (rough)
        vix              : float | None  — latest VIX
        available        : bool
        error            : str | None
    """
    try:
        fred = _get_fred_client()
    except (ImportError, ValueError) as exc:
        return {
            "slope_2s10s": None,
            "hy_spread": None,
            "ig_spread": None,
            "real_rate_approx": None,
            "vix": None,
            "available": False,
            "error": str(exc),
        }

    try:
        start_short = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
        start_cpi   = (datetime.now(timezone.utc) - timedelta(days=400)).strftime("%Y-%m-%d")

        def _latest(series_id: str, start: str) -> Optional[float]:
            try:
                data = fred.get_series(series_id, observation_start=start)
                if data is not None and len(data) > 0:
                    data = data.dropna()
                    if len(data) > 0:
                        return float(data.iloc[-1])
            except Exception:
                pass
            return None

        dgs10  = _latest("DGS10",          start_short)
        dgs2   = _latest("DGS2",           start_short)
        hy     = _latest("BAMLH0A0HYM2",   start_short)
        ig     = _latest("BAMLC0A4CBBB",   start_short)
        vix    = _latest("VIXCLS",         start_short)

        # CPI YoY: need last 13 months
        cpi_yoy: Optional[float] = None
        try:
            cpi_data = fred.get_series("CPIAUCSL", observation_start=start_cpi)
            if cpi_data is not None:
                cpi_data = cpi_data.dropna()
                if len(cpi_data) >= 13:
                    latest_cpi  = float(cpi_data.iloc[-1])
                    year_ago    = float(cpi_data.iloc[-13])
                    cpi_yoy     = ((latest_cpi - year_ago) / year_ago) * 100
        except Exception:
            pass

        slope = (dgs10 - dgs2) if (dgs10 is not None and dgs2 is not None) else None
        real_rate = (dgs10 - cpi_yoy) if (dgs10 is not None and cpi_yoy is not None) else None

        return {
            "slope_2s10s":      slope,
            "hy_spread":        hy,
            "ig_spread":        ig,
            "real_rate_approx": real_rate,
            "vix":              vix,
            "available":        True,
            "error":            None,
        }

    except Exception as exc:
        return {
            "slope_2s10s": None,
            "hy_spread": None,
            "ig_spread": None,
            "real_rate_approx": None,
            "vix": None,
            "available": False,
            "error": str(exc),
        }
