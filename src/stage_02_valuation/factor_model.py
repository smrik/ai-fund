"""Factor exposure decomposition using Fama-French 5-factor + momentum model."""

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

_MIN_OBSERVATIONS = 60


@dataclass
class FactorExposure:
    ticker: str
    market_beta: float | None
    size_beta: float | None           # SMB
    value_beta: float | None          # HML
    profitability_beta: float | None  # RMW
    investment_beta: float | None     # CMA
    momentum_beta: float | None       # Mom
    r_squared: float | None
    annualized_alpha: float | None    # intercept annualized (daily * 252)
    lookback_days: int
    as_of_date: str
    available: bool
    error: str | None
    factor_attribution: dict[str, float] = field(default_factory=dict)
    # pct of total explained return attributable to each factor


def decompose_factor_exposure(
    ticker: str,
    lookback_days: int = 252,
) -> FactorExposure:
    """
    Run OLS regression of ticker excess returns on FF5 + momentum factors.

    Downloads ticker price history via yfinance and Fama-French factor data
    via get_fama_french_factors(), aligns dates, then fits:

        excess_return ~ Mkt_RF + SMB + HML + RMW + CMA + Mom

    Returns a FactorExposure with betas, R², annualised alpha, and a
    factor_attribution dict.  Returns available=False when fewer than
    _MIN_OBSERVATIONS aligned rows are available or on any error.
    Never raises.
    """
    from datetime import datetime, timedelta, timezone

    today = datetime.now(timezone.utc).date()
    as_of_date = today.isoformat()

    _unavailable = FactorExposure(
        ticker=ticker,
        market_beta=None,
        size_beta=None,
        value_beta=None,
        profitability_beta=None,
        investment_beta=None,
        momentum_beta=None,
        r_squared=None,
        annualized_alpha=None,
        lookback_days=lookback_days,
        as_of_date=as_of_date,
        available=False,
        error=None,
        factor_attribution={},
    )

    try:
        import numpy as np
        import pandas as pd
    except ImportError as exc:
        _unavailable.error = f"numpy/pandas not available: {exc}"
        return _unavailable

    try:
        import yfinance as yf
    except ImportError as exc:
        _unavailable.error = f"yfinance not available: {exc}"
        return _unavailable

    try:
        from src.stage_00_data.factor_data import get_fama_french_factors
    except ImportError as exc:
        _unavailable.error = f"factor_data not available: {exc}"
        return _unavailable

    try:
        # ── Download ticker returns ────────────────────────────────────────────
        start_str = (today - timedelta(days=lookback_days + 30)).isoformat()
        t = yf.Ticker(ticker)
        hist = t.history(start=start_str, auto_adjust=True)
        if hist is None or hist.empty:
            _unavailable.error = "No price history returned by yfinance"
            return _unavailable

        price_series = hist["Close"].copy()
        price_series.index = pd.to_datetime(price_series.index).tz_localize(None)
        returns = price_series.pct_change().dropna()
        returns.name = "ticker_return"

        # ── Download FF factors ────────────────────────────────────────────────
        factors = get_fama_french_factors(start_date=start_str)
        if factors is None or factors.empty:
            _unavailable.error = "Fama-French factor data unavailable"
            return _unavailable

        factors.index = pd.to_datetime(factors.index).tz_localize(None)

        # ── Align ──────────────────────────────────────────────────────────────
        df = returns.to_frame().join(factors, how="inner").dropna()

        # Trim to requested lookback window after alignment
        if len(df) > lookback_days:
            df = df.iloc[-lookback_days:]

        if len(df) < _MIN_OBSERVATIONS:
            _unavailable.error = (
                f"Insufficient observations after alignment: {len(df)} < {_MIN_OBSERVATIONS}"
            )
            return _unavailable

        # ── Build regression inputs ────────────────────────────────────────────
        rf_col = _find_col(df, "RF")
        mkt_col = _find_col(df, "Mkt_RF")
        smb_col = _find_col(df, "SMB")
        hml_col = _find_col(df, "HML")
        rmw_col = _find_col(df, "RMW")
        cma_col = _find_col(df, "CMA")
        mom_col = _find_col(df, "Mom")

        if rf_col is None or mkt_col is None:
            _unavailable.error = "Required factor columns (RF, Mkt_RF) not found"
            return _unavailable

        excess_ret = df["ticker_return"] - df[rf_col]

        factor_cols = [c for c in [mkt_col, smb_col, hml_col, rmw_col, cma_col, mom_col] if c]
        X = df[factor_cols].copy()

        # ── OLS via statsmodels ────────────────────────────────────────────────
        try:
            import statsmodels.api as sm

            X_const = sm.add_constant(X)
            model = sm.OLS(excess_ret, X_const).fit()
        except ImportError as exc:
            _unavailable.error = f"statsmodels not available: {exc}"
            return _unavailable

        params = model.params
        alpha_daily = float(params.get("const", 0.0))
        annualized_alpha = alpha_daily * 252

        def _beta(col: str | None) -> float | None:
            if col is None:
                return None
            v = params.get(col)
            return float(v) if v is not None else None

        market_beta = _beta(mkt_col)
        size_beta = _beta(smb_col)
        value_beta = _beta(hml_col)
        profitability_beta = _beta(rmw_col)
        investment_beta = _beta(cma_col)
        momentum_beta = _beta(mom_col)
        r_squared = float(model.rsquared)

        # ── Factor attribution ─────────────────────────────────────────────────
        factor_attribution: dict[str, float] = {}
        factor_name_map = {
            mkt_col: "Mkt_RF",
            smb_col: "SMB",
            hml_col: "HML",
            rmw_col: "RMW",
            cma_col: "CMA",
            mom_col: "Mom",
        }

        # Annual contribution = beta * (annualised factor mean)
        annual_contribs: dict[str, float] = {}
        for col, name in factor_name_map.items():
            if col is None:
                continue
            beta_val = params.get(col)
            if beta_val is None:
                continue
            factor_mean_annual = float(df[col].mean()) * 252
            annual_contribs[name] = float(beta_val) * factor_mean_annual

        total_explained = sum(abs(v) for v in annual_contribs.values())
        if total_explained > 1e-9:
            factor_attribution = {
                name: contrib / total_explained
                for name, contrib in annual_contribs.items()
            }

        return FactorExposure(
            ticker=ticker,
            market_beta=market_beta,
            size_beta=size_beta,
            value_beta=value_beta,
            profitability_beta=profitability_beta,
            investment_beta=investment_beta,
            momentum_beta=momentum_beta,
            r_squared=r_squared,
            annualized_alpha=annualized_alpha,
            lookback_days=lookback_days,
            as_of_date=as_of_date,
            available=True,
            error=None,
            factor_attribution=factor_attribution,
        )

    except Exception as exc:
        logger.warning("decompose_factor_exposure failed for %s: %s", ticker, exc)
        _unavailable.error = str(exc)
        return _unavailable


def get_factor_summary_text(exposure: FactorExposure) -> str:
    """
    Return a 2-3 sentence human-readable summary of factor exposures.

    Covers market beta, the most significant style tilts, R², and alpha.
    """
    if not exposure.available:
        reason = exposure.error or "insufficient data"
        return (
            f"{exposure.ticker} factor decomposition is unavailable ({reason})."
        )

    ticker = exposure.ticker
    mkt = exposure.market_beta
    r2 = exposure.r_squared
    alpha_pct = (exposure.annualized_alpha or 0.0) * 100

    # Identify strongest style tilt
    style_map = {
        "value (HML)": exposure.value_beta,
        "size (SMB)": exposure.size_beta,
        "profitability (RMW)": exposure.profitability_beta,
        "investment (CMA)": exposure.investment_beta,
        "momentum (Mom)": exposure.momentum_beta,
    }
    style_items = [(name, b) for name, b in style_map.items() if b is not None]
    style_items.sort(key=lambda x: abs(x[1]), reverse=True)

    # Sentence 1: market beta + top style exposure
    mkt_str = f"{mkt:.2f}" if mkt is not None else "N/A"
    if style_items:
        top_name, top_beta = style_items[0]
        direction = "positive" if top_beta > 0 else "negative"
        sentence1 = (
            f"{ticker} has a market beta of {mkt_str} with a significant {direction} "
            f"{top_name} loading ({top_beta:+.2f})."
        )
    else:
        sentence1 = f"{ticker} has a market beta of {mkt_str}."

    # Sentence 2: R² and systematic factor coverage
    r2_str = f"{r2 * 100:.0f}%" if r2 is not None else "N/A"
    sentence2 = (
        f"Systematic factors explain {r2_str} of the stock's daily return variance."
    )

    # Sentence 3: alpha
    alpha_direction = "outperformed" if alpha_pct > 0 else "underperformed"
    sentence3 = (
        f"Annualised factor-adjusted alpha is {alpha_pct:+.1f}%, indicating the stock has "
        f"{alpha_direction} factor-adjusted expectations over the lookback window."
    )

    return " ".join([sentence1, sentence2, sentence3])


# ── Internal helpers ───────────────────────────────────────────────────────────

def _find_col(df: "pd.DataFrame", name: str) -> str | None:
    """
    Return the actual column name in df that matches name (case-insensitive,
    treating hyphens and underscores as equivalent).  Returns None if not found.
    """
    normalise = lambda s: s.lower().replace("-", "_")
    target = normalise(name)
    for col in df.columns:
        if normalise(str(col)) == target:
            return col
    return None
