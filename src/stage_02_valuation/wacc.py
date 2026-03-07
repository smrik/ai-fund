"""
WACC Calculator — proper CAPM with unlevered/relevered beta.

Process:
1. Gather peer betas and capital structures (yfinance or CIQ)
2. Unlever each peer's beta (Hamada equation)
3. Take median unlevered beta
4. Relever to target company's capital structure
5. CAPM: Ke = Rf + β_relevered × ERP + size_premium
6. WACC = Ke × (E/V) + Kd × (1-t) × (D/V)

All deterministic — no LLM needed.
"""

import numpy as np
from dataclasses import dataclass, field
from typing import Optional


# ── Market Parameters ───────────────────────────────────
# Updated periodically — these are reasonable defaults
RISK_FREE_RATE = 0.045       # 10Y US Treasury
EQUITY_RISK_PREMIUM = 0.05   # Damodaran long-run ERP
DEFAULT_TAX_RATE = 0.21      # US corporate
DEFAULT_COST_OF_DEBT = 0.06  # BBB-ish spread

# Size premia (Duff & Phelps / Kroll)
SIZE_PREMIA = {
    "mega":  0.000,   # > $50B
    "large": 0.005,   # $10B - $50B
    "mid":   0.010,   # $2B - $10B
    "small": 0.015,   # $500M - $2B
    "micro": 0.025,   # < $500M
}


@dataclass
class PeerData:
    """Financial data for a single peer company."""
    ticker: str
    beta: Optional[float] = None
    market_cap: Optional[float] = None
    total_debt: Optional[float] = None
    cash: Optional[float] = None
    tax_rate: float = DEFAULT_TAX_RATE
    cost_of_debt: float = DEFAULT_COST_OF_DEBT


@dataclass
class WACCResult:
    """Full WACC computation result with audit trail."""
    wacc: float
    cost_of_equity: float
    cost_of_debt_after_tax: float
    equity_weight: float
    debt_weight: float

    # CAPM components
    risk_free_rate: float
    equity_risk_premium: float
    beta_relevered: float
    size_premium: float

    # Beta derivation
    beta_unlevered_median: float
    peers_used: list[str] = field(default_factory=list)
    peer_betas_unlevered: list[float] = field(default_factory=list)

    # Target capital structure
    target_de_ratio: float = 0.0
    target_market_cap: float = 0.0
    target_net_debt: float = 0.0

    def summary(self) -> str:
        """Human-readable WACC summary."""
        lines = [
            f"WACC: {self.wacc*100:.2f}%",
            f"  Ke: {self.cost_of_equity*100:.2f}% (Rf {self.risk_free_rate*100:.1f}% + β {self.beta_relevered:.2f} × ERP {self.equity_risk_premium*100:.1f}% + size {self.size_premium*100:.1f}%)",
            f"  Kd(1-t): {self.cost_of_debt_after_tax*100:.2f}%",
            f"  Weights: E {self.equity_weight*100:.0f}% / D {self.debt_weight*100:.0f}%",
            f"  β unlevered (median of {len(self.peers_used)} peers): {self.beta_unlevered_median:.2f}",
            f"  β relevered (target D/E {self.target_de_ratio:.2f}): {self.beta_relevered:.2f}",
        ]
        return "\n".join(lines)


def _get_size_premium(market_cap: float) -> float:
    """Determine size premium based on market capitalization."""
    if market_cap is None or market_cap <= 0:
        return SIZE_PREMIA["mid"]  # Default
    mcap_b = market_cap / 1e9
    if mcap_b > 50:
        return SIZE_PREMIA["mega"]
    elif mcap_b > 10:
        return SIZE_PREMIA["large"]
    elif mcap_b > 2:
        return SIZE_PREMIA["mid"]
    elif mcap_b > 0.5:
        return SIZE_PREMIA["small"]
    else:
        return SIZE_PREMIA["micro"]


def unlever_beta(beta_levered: float, de_ratio: float, tax_rate: float = DEFAULT_TAX_RATE) -> float:
    """
    Hamada equation: unlever observed beta.
    β_unlevered = β_levered / (1 + (1 - t) × D/E)
    """
    if beta_levered is None or de_ratio < 0:
        return 1.0  # Market beta fallback
    return beta_levered / (1 + (1 - tax_rate) * de_ratio)


def relever_beta(beta_unlevered: float, de_ratio: float, tax_rate: float = DEFAULT_TAX_RATE) -> float:
    """
    Hamada equation: relever to target capital structure.
    β_relevered = β_unlevered × (1 + (1 - t) × D/E)
    """
    return beta_unlevered * (1 + (1 - tax_rate) * de_ratio)


def compute_wacc(
    target: PeerData,
    peers: list[PeerData],
    risk_free_rate: float = RISK_FREE_RATE,
    equity_risk_premium: float = EQUITY_RISK_PREMIUM,
) -> WACCResult:
    """
    Compute WACC using CAPM with unlevered/relevered beta from peers.

    Args:
        target: Target company financial data
        peers: List of peer company data (for beta derivation)
        risk_free_rate: Risk-free rate (default: 10Y Treasury)
        equity_risk_premium: Equity risk premium (default: Damodaran)

    Returns:
        WACCResult with full audit trail
    """
    # ── Step 1: Unlever peer betas ──
    peer_betas_unlevered = []
    peers_used = []

    for peer in peers:
        if peer.beta is None or peer.beta <= 0:
            continue
        if peer.market_cap is None or peer.market_cap <= 0:
            continue

        net_debt = (peer.total_debt or 0) - (peer.cash or 0)
        de_ratio = max(net_debt, 0) / peer.market_cap  # Floor at 0 (no negative D/E)

        beta_u = unlever_beta(peer.beta, de_ratio, peer.tax_rate)

        # Sanity check: unlevered beta should be between 0.2 and 3.0
        if 0.2 <= beta_u <= 3.0:
            peer_betas_unlevered.append(beta_u)
            peers_used.append(peer.ticker)

    # ── Step 2: Median unlevered beta ──
    if peer_betas_unlevered:
        beta_unlevered_median = float(np.median(peer_betas_unlevered))
    elif target.beta and target.beta > 0:
        # Fallback: use target's own beta (unlevered)
        target_net_debt = (target.total_debt or 0) - (target.cash or 0)
        target_de = max(target_net_debt, 0) / max(target.market_cap or 1, 1)
        beta_unlevered_median = unlever_beta(target.beta, target_de, target.tax_rate)
        peers_used = [f"{target.ticker} (self)"]
        peer_betas_unlevered = [beta_unlevered_median]
    else:
        # Last resort: market beta
        beta_unlevered_median = 1.0
        peers_used = ["market (fallback)"]
        peer_betas_unlevered = [1.0]

    # ── Step 3: Relever to target capital structure ──
    target_net_debt = (target.total_debt or 0) - (target.cash or 0)
    target_mcap = target.market_cap or 1
    target_de_ratio = max(target_net_debt, 0) / target_mcap

    beta_relevered = relever_beta(beta_unlevered_median, target_de_ratio, target.tax_rate)

    # ── Step 4: CAPM → Cost of Equity ──
    size_premium = _get_size_premium(target.market_cap)
    cost_of_equity = risk_free_rate + beta_relevered * equity_risk_premium + size_premium

    # ── Step 5: Cost of Debt (after tax) ──
    cost_of_debt_after_tax = target.cost_of_debt * (1 - target.tax_rate)

    # ── Step 6: Capital structure weights ──
    total_capital = target_mcap + max(target_net_debt, 0)
    equity_weight = target_mcap / total_capital if total_capital > 0 else 1.0
    debt_weight = 1 - equity_weight

    # ── Step 7: WACC ──
    wacc = cost_of_equity * equity_weight + cost_of_debt_after_tax * debt_weight

    return WACCResult(
        wacc=round(wacc, 5),
        cost_of_equity=round(cost_of_equity, 5),
        cost_of_debt_after_tax=round(cost_of_debt_after_tax, 5),
        equity_weight=round(equity_weight, 4),
        debt_weight=round(debt_weight, 4),
        risk_free_rate=risk_free_rate,
        equity_risk_premium=equity_risk_premium,
        beta_relevered=round(beta_relevered, 4),
        size_premium=size_premium,
        beta_unlevered_median=round(beta_unlevered_median, 4),
        peers_used=peers_used,
        peer_betas_unlevered=[round(b, 4) for b in peer_betas_unlevered],
        target_de_ratio=round(target_de_ratio, 4),
        target_market_cap=target_mcap,
        target_net_debt=target_net_debt,
    )


def compute_wacc_from_yfinance(
    ticker: str,
    peer_tickers: list[str] = None,
    hist: dict = None,
) -> WACCResult:
    """
    Convenience: compute WACC using yfinance data.
    If no peers provided, uses the target's own beta as fallback.
    Cost of debt is derived from actual interest expense / total debt if available.

    Args:
        hist: Pre-fetched result of get_historical_financials(ticker). If None, fetches it.
              Pass this when the caller already has historical data to avoid a double fetch.
    """
    from src.stage_00_data import market_data as md_client

    # Fetch target data
    mkt = md_client.get_market_data(ticker)
    if hist is None:
        hist = md_client.get_historical_financials(ticker)

    # Use derived cost of debt if available, else market default
    cost_of_debt = hist.get("cost_of_debt_derived") or DEFAULT_COST_OF_DEBT

    target = PeerData(
        ticker=ticker,
        beta=mkt.get("beta"),
        market_cap=mkt.get("market_cap"),
        total_debt=mkt.get("total_debt"),
        cash=mkt.get("cash"),
        cost_of_debt=cost_of_debt,
    )

    # Fetch peer data
    peers = []
    if peer_tickers:
        for pt in peer_tickers:
            try:
                pmkt = md_client.get_market_data(pt)
                peers.append(PeerData(
                    ticker=pt,
                    beta=pmkt.get("beta"),
                    market_cap=pmkt.get("market_cap"),
                    total_debt=pmkt.get("total_debt"),
                    cash=pmkt.get("cash"),
                ))
            except Exception:
                continue

    return compute_wacc(target, peers)
