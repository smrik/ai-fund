"""
Portfolio-level risk analytics (deterministic, no LLM).
Provides correlation, VaR/CVaR, sector concentration, and exposure summaries.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import yfinance as yf


@dataclass
class FactorExposureSummary:
    tickers: list[str]
    correlation_matrix: list[list[float]]  # n x n, same order as tickers
    corr_pairs: list[dict]                 # [{ticker_a, ticker_b, correlation}]
    top_correlated_pairs: list[dict]       # top 5 by |correlation|

    var_95: Optional[float] = None         # 1-day 95% parametric VaR (portfolio %)
    var_99: Optional[float] = None
    cvar_95: Optional[float] = None        # 1-day 95% historical CVaR (portfolio %)
    cvar_99: Optional[float] = None

    sector_weights: dict[str, float] = field(default_factory=dict)  # sector → weight_pct
    gross_exposure: Optional[float] = None
    net_exposure: Optional[float] = None
    long_exposure: Optional[float] = None
    short_exposure: Optional[float] = None


def _fetch_returns(tickers: list[str], period: str = "1y") -> dict[str, list[float]]:
    """Fetch daily log-returns for each ticker. Returns {ticker: [returns]}."""
    result: dict[str, list[float]] = {}
    for ticker in tickers:
        try:
            hist = yf.Ticker(ticker).history(period=period)
            if hist.empty or len(hist) < 20:
                continue
            closes = hist["Close"].dropna().tolist()
            returns = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
            result[ticker] = returns
        except Exception:
            continue
    return result


def _align_returns(returns_by_ticker: dict[str, list[float]]) -> tuple[list[str], list[list[float]]]:
    """Align all return series to the same (minimum) length and return (tickers, matrix)."""
    if not returns_by_ticker:
        return [], []
    tickers = list(returns_by_ticker.keys())
    min_len = min(len(v) for v in returns_by_ticker.values())
    matrix = [returns_by_ticker[t][-min_len:] for t in tickers]
    return tickers, matrix


def compute_correlation_matrix(
    tickers: list[str],
    period: str = "1y",
) -> tuple[list[str], list[list[float]]]:
    """
    Compute pairwise return correlations for a list of tickers.
    Returns (tickers_used, correlation_matrix) where missing tickers are dropped.
    """
    returns_by_ticker = _fetch_returns(tickers, period=period)
    valid_tickers, matrix = _align_returns(returns_by_ticker)
    if len(valid_tickers) < 2:
        return valid_tickers, []

    n = len(valid_tickers)
    arr = np.array(matrix, dtype=float)  # shape: (n, T)
    corr = np.corrcoef(arr)  # shape: (n, n)

    # Convert to plain Python lists
    corr_list = [[round(float(corr[i][j]), 4) for j in range(n)] for i in range(n)]
    return valid_tickers, corr_list


def compute_historical_var(
    tickers: list[str],
    weights: dict[str, float],
    period: str = "1y",
) -> dict[str, Optional[float]]:
    """
    Compute 1-day parametric VaR and historical CVaR for a portfolio.

    weights: {ticker: weight} where weights sum to 1.0 (longs positive, shorts negative).
    Returns {'var_95', 'var_99', 'cvar_95', 'cvar_99'} as portfolio return fractions.
    """
    returns_by_ticker = _fetch_returns(tickers, period=period)
    valid_tickers, matrix = _align_returns(
        {t: v for t, v in returns_by_ticker.items() if t in weights}
    )
    if len(valid_tickers) < 1:
        return {"var_95": None, "var_99": None, "cvar_95": None, "cvar_99": None}

    # Weight vector
    w = np.array([weights.get(t, 0.0) for t in valid_tickers], dtype=float)
    total_w = abs(w).sum()
    if total_w > 0:
        w = w / total_w  # normalize

    arr = np.array(matrix, dtype=float)  # (n, T)
    # Portfolio daily returns: weighted sum of individual returns
    port_returns = w @ arr  # shape: (T,)

    # Parametric VaR (normal distribution)
    mu = float(port_returns.mean())
    sigma = float(port_returns.std())
    var_95_param = -(mu - 1.645 * sigma)
    var_99_param = -(mu - 2.326 * sigma)

    # Historical CVaR (expected shortfall at given confidence)
    sorted_ret = np.sort(port_returns)
    n_obs = len(sorted_ret)
    cutoff_95 = int(math.floor(n_obs * 0.05))
    cutoff_99 = int(math.floor(n_obs * 0.01))
    cvar_95_hist = float(-sorted_ret[: max(cutoff_95, 1)].mean()) if cutoff_95 > 0 else None
    cvar_99_hist = float(-sorted_ret[: max(cutoff_99, 1)].mean()) if cutoff_99 > 0 else None

    return {
        "var_95": round(var_95_param, 5),
        "var_99": round(var_99_param, 5),
        "cvar_95": round(cvar_95_hist, 5) if cvar_95_hist is not None else None,
        "cvar_99": round(cvar_99_hist, 5) if cvar_99_hist is not None else None,
    }


def compute_sector_concentration(positions: list[dict]) -> dict[str, float]:
    """
    Compute sector weight breakdown from a list of position dicts.
    Each position dict needs 'ticker', 'market_value', 'sector' (optional) keys.
    Returns {sector: weight_pct} where weights sum to 100% (gross basis).

    If 'sector' is not in the position dict, looks it up via yfinance (cached in-process).
    """
    _sector_cache: dict[str, str] = {}
    total_gross = sum(abs(p.get("market_value", 0) or 0) for p in positions)
    if total_gross == 0:
        return {}

    sector_values: dict[str, float] = {}
    for pos in positions:
        ticker = (pos.get("ticker") or "").upper()
        sector = pos.get("sector") or ""
        if not sector:
            if ticker not in _sector_cache:
                try:
                    info = yf.Ticker(ticker).info or {}
                    _sector_cache[ticker] = info.get("sector", "Unknown") or "Unknown"
                except Exception:
                    _sector_cache[ticker] = "Unknown"
            sector = _sector_cache[ticker]
        mv = abs(pos.get("market_value", 0) or 0)
        sector_values[sector] = sector_values.get(sector, 0.0) + mv

    return {s: round(v / total_gross * 100, 2) for s, v in sorted(sector_values.items(), key=lambda x: -x[1])}


def compute_exposure_summary(positions: list[dict]) -> dict[str, float]:
    """
    Compute gross/net/long/short exposure from a list of position dicts.
    Each dict needs 'market_value' (positive = long, negative = short).
    """
    long_mv = sum(p.get("market_value", 0) or 0 for p in positions if (p.get("market_value") or 0) > 0)
    short_mv = sum(abs(p.get("market_value", 0) or 0) for p in positions if (p.get("market_value") or 0) < 0)
    gross = long_mv + short_mv
    net = long_mv - short_mv
    return {
        "gross_exposure": round(gross, 2),
        "net_exposure": round(net, 2),
        "long_exposure": round(long_mv, 2),
        "short_exposure": round(short_mv, 2),
        "long_pct": round(long_mv / gross * 100, 1) if gross else 0.0,
        "short_pct": round(short_mv / gross * 100, 1) if gross else 0.0,
        "net_pct": round(net / gross * 100, 1) if gross else 0.0,
    }


def build_portfolio_risk(
    tickers: list[str],
    weights: dict[str, float] | None = None,
    positions: list[dict] | None = None,
    period: str = "1y",
) -> FactorExposureSummary:
    """
    Full portfolio risk summary.

    tickers: list of tickers to include in correlation analysis.
    weights: {ticker: weight} for VaR. If None, equal-weights long-only assumed.
    positions: list of position dicts for sector/exposure analysis.
    """
    valid_tickers, corr_list = compute_correlation_matrix(tickers, period=period)

    # Build pair list
    corr_pairs: list[dict] = []
    for i, ti in enumerate(valid_tickers):
        for j, tj in enumerate(valid_tickers):
            if j <= i:
                continue
            c = corr_list[i][j] if corr_list else 0.0
            corr_pairs.append({"ticker_a": ti, "ticker_b": tj, "correlation": c})

    top_pairs = sorted(corr_pairs, key=lambda x: abs(x["correlation"]), reverse=True)[:5]

    # VaR/CVaR
    if weights is None and valid_tickers:
        w = {t: 1.0 / len(valid_tickers) for t in valid_tickers}
    else:
        w = weights or {}
    var_result = compute_historical_var(valid_tickers, w, period=period) if valid_tickers else {}

    # Sector + exposure
    sector_weights: dict[str, float] = {}
    exposure: dict[str, float] = {}
    if positions:
        sector_weights = compute_sector_concentration(positions)
        exposure = compute_exposure_summary(positions)

    return FactorExposureSummary(
        tickers=valid_tickers,
        correlation_matrix=corr_list,
        corr_pairs=corr_pairs,
        top_correlated_pairs=top_pairs,
        var_95=var_result.get("var_95"),
        var_99=var_result.get("var_99"),
        cvar_95=var_result.get("cvar_95"),
        cvar_99=var_result.get("cvar_99"),
        sector_weights=sector_weights,
        gross_exposure=exposure.get("gross_exposure"),
        net_exposure=exposure.get("net_exposure"),
        long_exposure=exposure.get("long_exposure"),
        short_exposure=exposure.get("short_exposure"),
    )
