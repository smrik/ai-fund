"""Public-market fallback comps for deterministic valuation review paths."""
from __future__ import annotations

from datetime import date
from typing import Any, Callable

from src.stage_00_data import market_data as md_client
from src.stage_02_valuation.comps_model import build_comps_detail_from_yfinance


PUBLIC_PEER_FALLBACKS = {
    "MSFT": ["AAPL", "GOOGL", "AMZN", "META", "ORCL", "CRM", "ADBE", "NOW"],
    "IBM": ["ACN", "ORCL", "SAP", "CTSH", "INFY", "NOW", "CRM", "ADBE"],
}
PUBLIC_SECTOR_FALLBACKS = {
    "TECHNOLOGY": ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "ORCL", "CRM", "ADBE", "NOW"],
    "COMMUNICATION SERVICES": ["GOOGL", "META", "NFLX", "DIS", "CMCSA", "TMUS"],
    "CONSUMER CYCLICAL": ["AMZN", "TSLA", "HD", "MCD", "NKE", "SBUX"],
    "CONSUMER DEFENSIVE": ["WMT", "COST", "PG", "KO", "PEP", "MDLZ"],
    "FINANCIAL SERVICES": ["JPM", "BAC", "WFC", "GS", "MS", "C"],
    "HEALTHCARE": ["UNH", "JNJ", "LLY", "MRK", "ABBV", "PFE"],
    "INDUSTRIALS": ["GE", "CAT", "HON", "UPS", "RTX", "DE"],
    "ENERGY": ["XOM", "CVX", "COP", "EOG", "SLB", "MPC"],
}


def median(values: list[Any]) -> float | None:
    cleaned = sorted(float(value) for value in values if value is not None)
    if not cleaned:
        return None
    midpoint = len(cleaned) // 2
    if len(cleaned) % 2:
        return cleaned[midpoint]
    return round((cleaned[midpoint - 1] + cleaned[midpoint]) / 2.0, 4)


def fallback_peer_tickers(
    ticker: str,
    sector: str | None = None,
    *,
    explicit_peers: list[str] | None = None,
) -> list[str]:
    ticker = ticker.upper()
    peers = explicit_peers
    if peers is None:
        peers = PUBLIC_PEER_FALLBACKS.get(ticker)
    if peers is None:
        peers = PUBLIC_SECTOR_FALLBACKS.get(str(sector or "").strip().upper(), [])
    return [str(peer).upper() for peer in peers if str(peer).upper() != ticker]


def with_public_target_derived_fields(market: dict[str, Any]) -> dict[str, Any]:
    target = dict(market or {})
    price = target.get("current_price")
    pe_trailing = target.get("pe_trailing")
    revenue_ttm = target.get("revenue_ttm")
    operating_margin = target.get("operating_margin")
    if target.get("eps_ltm") is None and price is not None and pe_trailing not in (None, 0):
        target["eps_ltm"] = float(price) / float(pe_trailing)
    if target.get("ebit_ltm_mm") is None and revenue_ttm is not None and operating_margin is not None:
        target["ebit_ltm_mm"] = (float(revenue_ttm) * float(operating_margin)) / 1_000_000.0
    return target


def build_public_market_fallback_comps_detail(
    ticker: str,
    *,
    market: dict[str, Any] | None = None,
    sector: str | None = None,
    explicit_peers: list[str] | None = None,
    market_data_client=md_client,
    target_market_loader: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    ticker = ticker.upper()
    if market is None:
        try:
            loader = target_market_loader or market_data_client.get_market_data
            market = loader(ticker)
        except Exception:
            return None
    sector = sector if sector is not None else str((market or {}).get("sector") or "")
    peer_tickers = fallback_peer_tickers(ticker, sector, explicit_peers=explicit_peers)
    if not peer_tickers:
        return None
    try:
        peer_multiples = market_data_client.get_peer_multiples(peer_tickers)
    except Exception:
        return None
    comps_detail = build_comps_detail_from_yfinance(
        ticker,
        peer_multiples,
        with_public_target_derived_fields(market or {}),
    )
    if not comps_detail:
        return None
    peers = comps_detail.get("peers") or []
    medians = {
        "tev_ebitda_ltm": median([row.get("tev_ebitda_ltm") for row in peers]),
        "pe_ltm": median([row.get("pe_ltm") for row in peers]),
    }
    comps_detail["medians"] = {key: value for key, value in medians.items() if value is not None}
    target = comps_detail.setdefault("target", {})
    target.update(
        {
            "as_of_date": date.today().isoformat(),
            "source_file": "public_market_yfinance_fallback",
            "revenue_growth": (market or {}).get("revenue_growth"),
            "ebit_margin": (market or {}).get("operating_margin"),
            "pe_ltm": (market or {}).get("pe_trailing"),
            "tev_ebitda_ltm": (market or {}).get("ev_ebitda"),
        }
    )
    comps_detail["source_lineage"] = {
        "source": "public_market_yfinance_fallback",
        "as_of_date": target["as_of_date"],
        "source_file": target["source_file"],
        "peer_universe": peer_tickers,
    }
    comps_detail["_fallback_audit_flags"] = [
        "No CIQ comps detail available; using public market yfinance fallback comps",
    ]
    return comps_detail
