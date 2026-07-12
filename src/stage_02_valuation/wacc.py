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

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import numpy as np
import yaml


def _load_wacc_params() -> dict:
    """Load Rf/ERP from config/config.yaml with hardcoded fallbacks."""
    config_path = Path(__file__).resolve().parent.parent.parent / "config" / "config.yaml"
    try:
        with config_path.open("r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        return cfg.get("wacc_params", {})
    except Exception:
        return {}


_wacc_cfg = _load_wacc_params()

# ── Market Parameters ───────────────────────────────────
# Loaded from config/config.yaml wacc_params; hardcoded values are fallbacks
RISK_FREE_RATE = float(_wacc_cfg.get("risk_free_rate", 0.045))       # 10Y US Treasury
EQUITY_RISK_PREMIUM = float(_wacc_cfg.get("equity_risk_premium", 0.05))  # Damodaran long-run ERP
DEFAULT_TAX_RATE = 0.21      # US corporate
DEFAULT_COST_OF_DEBT = 0.06  # BBB-ish spread


class MissingWACCInputError(ValueError):
    """Raised when a load-bearing WACC input is absent."""

# Size premia (CRSP Deciles Size Study - Data as of 12/31/2023)
# https://www.crsp.com/investing-research/
SIZE_PREMIA = {
    # CRSP Deciles 1-10 (market cap in $mm, premium in %)
    # Decile 1 (mega): $36,942.98M - $2,662,326.05M
    "mega": -0.0006,    # -0.06%
    # Decile 2 (large): $14,910.72M - $36,391.11M
    "large": 0.0046,    # 0.46%
    # Decile 3 (upper mid): $7,493.61M - $14,820.05M
    "upper_mid": 0.0061,  # 0.61%
    # Decile 4 (mid): $4,622.26M - $7,461.28M
    "mid": 0.0064,     # 0.64%
    # Decile 5 (lower mid): $3,011.22M - $4,621.79M
    "lower_mid": 0.0095,  # 0.95%
    # Decile 6: $1,864.29M - $3,010.81M
    "decile_6": 0.0121,   # 1.21%
    # Decile 7: $1,050.08M - $1,862.49M
    "decile_7": 0.0139,   # 1.39%
    # Decile 8: $555.88M - $1,046.04M
    "decile_8": 0.0114,   # 1.14%
    # Decile 9: $213.04M - $554.52M
    "micro": 0.0199,     # 1.99%
    # Decile 10: $1.58M - $212.64M
    "nano": 0.0470,      # 4.70%
}

# CRSP Decile breakpoints (high end of each decile in $mm)
CRSP_DECILE_BREAKPOINTS = [
    36.94,       # Decile 1 lower bound (~$37M)
    555.88,       # Decile 8 lower bound
    213.04,       # Decile 9 lower bound
    1.58,         # Decile 10 lower bound
]

SECTOR_BETA_PROXIES = {
    "Technology": 1.05,
    "Communication Services": 1.00,
    "Healthcare": 0.95,
    "Consumer Cyclical": 1.10,
    "Consumer Defensive": 0.85,
    "Industrials": 1.00,
    "Energy": 1.15,
    "Basic Materials": 1.10,
    "Utilities": 0.70,
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

    # Data-quality state. Numeric fallback results remain diagnostic only.
    quality_status: str = "source_backed"
    missing_inputs: list[str] = field(default_factory=list)
    beta_source: str = "peer_median"
    market_cap_source: str = "provided"

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


def _net_debt(data: PeerData) -> float:
    return (data.total_debt or 0.0) - (data.cash or 0.0)


def _de_ratio(data: PeerData) -> float:
    market_cap = data.market_cap or 0.0
    if market_cap <= 0:
        return 0.0
    return max(_net_debt(data), 0.0) / market_cap


WACC_METHODS = ("peer_bottom_up", "industry_proxy", "self_hamada")


def _get_size_premium(market_cap: float) -> float:
    """Determine size premium using CRSP Deciles Size Study (as of 12/31/2023).

    Uses linear interpolation between CRSP decile breakpoints to eliminate
    step-function discontinuities at bucket boundaries.
    """
    if market_cap is None or market_cap <= 0:
        return SIZE_PREMIA["mid"]

    mcap_mm = market_cap / 1e6

    # CRSP Deciles: (high end of decile in $mm, premium)
    # Ordered by market cap (largest to smallest)
    breakpoints = [
        (2662326.05, -0.0006),   # Decile 1: > $36,942.98M -> -0.06%
        (36391.11, 0.0046),     # Decile 2: $14,910.72M - $36,391.11M -> 0.46%
        (14820.05, 0.0061),     # Decile 3: $7,493.61M - $14,820.05M -> 0.61%
        (7461.28, 0.0064),      # Decile 4: $4,622.26M - $7,461.28M -> 0.64%
        (4621.79, 0.0095),     # Decile 5: $3,011.22M - $4,621.79M -> 0.95%
        (3010.81, 0.0121),     # Decile 6: $1,864.29M - $3,010.81M -> 1.21%
        (1862.49, 0.0139),     # Decile 7: $1,050.08M - $1,862.49M -> 1.39%
        (1046.04, 0.0114),     # Decile 8: $555.88M - $1,046.04M -> 1.14%
        (554.52, 0.0199),      # Decile 9: $213.04M - $554.52M -> 1.99%
        (212.64, 0.0470),      # Decile 10: $1.58M - $212.64M -> 4.70%
    ]

    # Below smallest decile (nano cap)
    if mcap_mm <= breakpoints[-1][0]:
        return breakpoints[-1][1]

    # Above largest decile (mega cap)
    if mcap_mm >= breakpoints[0][0]:
        return breakpoints[0][1]

    # Linear interpolation between adjacent deciles
    for i in range(len(breakpoints) - 1):
        x0, y0 = breakpoints[i]
        x1, y1 = breakpoints[i + 1]
        if x1 <= mcap_mm <= x0:
            alpha = (x0 - mcap_mm) / (x0 - x1)
            return y0 + alpha * (y1 - y0)

    return SIZE_PREMIA["mid"]


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
    if target.market_cap is None or target.market_cap <= 0:
        raise MissingWACCInputError(f"{target.ticker}: market cap is required for WACC")

    quality_status = "source_backed"
    missing_inputs: list[str] = []
    beta_source = "peer_median"

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
        beta_source = "peer_median"
    elif target.beta and target.beta > 0:
        # Fallback: use target's own beta (unlevered)
        target_net_debt = (target.total_debt or 0) - (target.cash or 0)
        target_de = max(target_net_debt, 0) / max(target.market_cap or 1, 1)
        beta_unlevered_median = unlever_beta(target.beta, target_de, target.tax_rate)
        peers_used = [f"{target.ticker} (self)"]
        peer_betas_unlevered = [beta_unlevered_median]
        beta_source = "target_beta"
    else:
        # Last resort: market beta
        beta_unlevered_median = 1.0
        peers_used = ["market (fallback)"]
        peer_betas_unlevered = [1.0]
        quality_status = "degraded_fallback"
        missing_inputs.append("beta")
        beta_source = "market_beta_assumption"

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
        quality_status=quality_status,
        missing_inputs=missing_inputs,
        beta_source=beta_source,
        market_cap_source="provided",
    )




def compute_wacc_from_yfinance(
    ticker: str,
    peer_tickers: list[str] = None,
    hist: dict = None,
    risk_free_rate: float | None = None,
    equity_risk_premium: float | None = None,
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

    rf = risk_free_rate if risk_free_rate is not None else RISK_FREE_RATE
    erp = equity_risk_premium if equity_risk_premium is not None else EQUITY_RISK_PREMIUM
    return compute_wacc(target, peers, risk_free_rate=rf, equity_risk_premium=erp)


def _target_from_market_data(
    ticker: str,
    *,
    market_data: dict | None = None,
    hist: dict | None = None,
) -> PeerData:
    from src.stage_00_data import market_data as md_client

    mkt = market_data or md_client.get_market_data(ticker)
    if hist is None:
        hist = md_client.get_historical_financials(ticker)

    # #4: Compute market_cap from price × shares when the API field is absent.
    # This ensures _get_size_premium() uses the correct decile rather than the
    # "mid" default, which matters for $500M-$2B names (small premium = 1.5% vs 1.0%).
    mkt_cap = mkt.get("market_cap")
    if not mkt_cap:
        price = mkt.get("current_price") or mkt.get("regularMarketPrice")
        shares = mkt.get("shares_outstanding")
        if price and shares:
            mkt_cap = float(price) * float(shares)

    cost_of_debt = (hist or {}).get("cost_of_debt_derived") or DEFAULT_COST_OF_DEBT
    return PeerData(
        ticker=ticker.upper(),
        beta=mkt.get("beta"),
        market_cap=mkt_cap,
        total_debt=mkt.get("total_debt"),
        cash=mkt.get("cash"),
        cost_of_debt=cost_of_debt,
    )


def _load_peer_data(peer_tickers: list[str]) -> list[PeerData]:
    from src.stage_00_data import market_data as md_client

    peers: list[PeerData] = []
    for peer_ticker in peer_tickers:
        try:
            pmkt = md_client.get_market_data(peer_ticker)
        except Exception:
            continue
        peers.append(
            PeerData(
                ticker=peer_ticker,
                beta=pmkt.get("beta"),
                market_cap=pmkt.get("market_cap"),
                total_debt=pmkt.get("total_debt"),
                cash=pmkt.get("cash"),
            )
        )
    return peers


def _net_debt(peer: PeerData) -> float:
    return float((peer.total_debt or 0.0) - (peer.cash or 0.0))


def _de_ratio(peer: PeerData) -> float | None:
    if peer.market_cap is None or peer.market_cap <= 0:
        return None
    return max(_net_debt(peer), 0.0) / float(peer.market_cap)


def _median_or_default(values: list[float], default: float) -> float:
    cleaned = [float(value) for value in values if value is not None]
    if not cleaned:
        return default
    return float(np.median(cleaned))


def _compute_industry_proxy_wacc(
    target: PeerData,
    peers: list[PeerData],
    risk_free_rate: float = RISK_FREE_RATE,
    equity_risk_premium: float = EQUITY_RISK_PREMIUM,
) -> WACCResult:
    peer_betas = [float(peer.beta) for peer in peers if peer.beta is not None and peer.beta > 0]
    peer_de_ratios = [ratio for peer in peers if (ratio := _de_ratio(peer)) is not None]

    proxy_beta = _median_or_default(peer_betas, target.beta or 1.0)
    proxy_de_ratio = _median_or_default(peer_de_ratios, _de_ratio(target) or 0.20)
    target_market_cap = float(target.market_cap or 1.0)
    target_cash = float(target.cash or 0.0)
    proxy_net_debt = max(proxy_de_ratio, 0.0) * target_market_cap

    proxy_target = PeerData(
        ticker=target.ticker,
        beta=proxy_beta,
        market_cap=target_market_cap,
        total_debt=proxy_net_debt + target_cash,
        cash=target_cash,
        tax_rate=target.tax_rate,
        cost_of_debt=target.cost_of_debt,
    )
    result = compute_wacc(proxy_target, [], risk_free_rate=risk_free_rate, equity_risk_premium=equity_risk_premium)
    result.peers_used = [peer.ticker for peer in peers] or ["industry_proxy"]
    return result


def _compute_self_hamada_wacc(
    target: PeerData,
    risk_free_rate: float = RISK_FREE_RATE,
    equity_risk_premium: float = EQUITY_RISK_PREMIUM,
) -> WACCResult:
    return compute_wacc(target, [], risk_free_rate=risk_free_rate, equity_risk_premium=equity_risk_premium)


def compute_wacc_methodology_set_for_ticker(
    ticker: str,
    *,
    peer_tickers: list[str] | None = None,
    hist: dict | None = None,
    market_data: dict | None = None,
    risk_free_rate: float | None = None,
    equity_risk_premium: float | None = None,
) -> dict[str, WACCResult]:
    target = _target_from_market_data(ticker, market_data=market_data, hist=hist)
    peers = _load_peer_data(peer_tickers or [])
    rf = risk_free_rate if risk_free_rate is not None else RISK_FREE_RATE
    erp = equity_risk_premium if equity_risk_premium is not None else EQUITY_RISK_PREMIUM

    results: dict[str, Any] = {
        "peer_bottom_up": compute_wacc(target, peers, risk_free_rate=rf, equity_risk_premium=erp),
        "industry_proxy": _compute_industry_proxy_wacc(target, peers, risk_free_rate=rf, equity_risk_premium=erp),
        "self_hamada": _compute_self_hamada_wacc(target, risk_free_rate=rf, equity_risk_premium=erp),
    }

    _WACC_DISAGREEMENT_THRESHOLD = 0.015  # 150bps
    method_waccs = {
        k: getattr(v, "wacc", None)
        for k, v in results.items()
        if getattr(v, "wacc", None) is not None
    }
    if len(method_waccs) >= 2:
        spread = max(method_waccs.values()) - min(method_waccs.values())
        results["_meta"] = {
            "wacc_method_spread": round(spread, 4),
            "wacc_method_spread_high": spread >= _WACC_DISAGREEMENT_THRESHOLD,
            "method_waccs": method_waccs,
        }

    return results


def blend_wacc_results(results: dict[str, WACCResult], weights: dict[str, float]) -> WACCResult:
    clean_weights = {
        method: float(weight)
        for method, weight in (weights or {}).items()
        if method in results and weight is not None and float(weight) > 0
    }
    total_weight = sum(clean_weights.values())
    if total_weight <= 0:
        raise ValueError("weights must contain at least one positive method weight")

    normalized = {method: weight / total_weight for method, weight in clean_weights.items()}

    def _weighted(attr: str) -> float:
        return float(sum(getattr(results[method], attr) * weight for method, weight in normalized.items()))

    peers_used: list[str] = []
    peer_betas_unlevered: list[float] = []
    for method in normalized:
        peers_used.extend(results[method].peers_used)
        peer_betas_unlevered.extend(results[method].peer_betas_unlevered)

    return WACCResult(
        wacc=round(_weighted("wacc"), 5),
        cost_of_equity=round(_weighted("cost_of_equity"), 5),
        cost_of_debt_after_tax=round(_weighted("cost_of_debt_after_tax"), 5),
        equity_weight=round(_weighted("equity_weight"), 4),
        debt_weight=round(_weighted("debt_weight"), 4),
        risk_free_rate=round(_weighted("risk_free_rate"), 5),
        equity_risk_premium=round(_weighted("equity_risk_premium"), 5),
        beta_relevered=round(_weighted("beta_relevered"), 4),
        size_premium=round(_weighted("size_premium"), 5),
        beta_unlevered_median=round(_weighted("beta_unlevered_median"), 4),
        peers_used=sorted(set(peers_used)),
        peer_betas_unlevered=[round(value, 4) for value in peer_betas_unlevered],
        target_de_ratio=round(_weighted("target_de_ratio"), 4),
        target_market_cap=float(_weighted("target_market_cap")),
        target_net_debt=float(_weighted("target_net_debt")),
    )
