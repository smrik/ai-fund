"""
Market data client using yfinance (free, no API key).
Provides prices, valuation multiples, analyst ratings, and news.
"""

import yfinance as yf
from typing import Optional


def get_market_data(ticker: str) -> dict:
    """
    Return current market snapshot: price, market cap, multiples, 52w range.
    """
    t = yf.Ticker(ticker)
    info = t.info or {}

    return {
        "ticker": ticker.upper(),
        "name": info.get("longName", ""),
        "sector": info.get("sector", ""),
        "industry": info.get("industry", ""),
        "current_price": info.get("currentPrice") or info.get("regularMarketPrice"),
        "market_cap": info.get("marketCap"),
        "enterprise_value": info.get("enterpriseValue"),
        "pe_trailing": info.get("trailingPE"),
        "pe_forward": info.get("forwardPE"),
        "ev_ebitda": info.get("enterpriseToEbitda"),
        "ev_revenue": info.get("enterpriseToRevenue"),
        "price_to_book": info.get("priceToBook"),
        "price_to_sales": info.get("priceToSalesTrailing12Months"),
        "revenue_ttm": info.get("totalRevenue"),
        "ebitda_ttm": info.get("ebitda"),
        "gross_margin": info.get("grossMargins"),
        "operating_margin": info.get("operatingMargins"),
        "profit_margin": info.get("profitMargins"),
        "revenue_growth": info.get("revenueGrowth"),
        "earnings_growth": info.get("earningsGrowth"),
        "free_cashflow": info.get("freeCashflow"),
        "total_debt": info.get("totalDebt"),
        "cash": info.get("totalCash"),
        "beta": info.get("beta"),
        "52w_high": info.get("fiftyTwoWeekHigh"),
        "52w_low": info.get("fiftyTwoWeekLow"),
        "dividend_yield": info.get("dividendYield"),
        "shares_outstanding": info.get("sharesOutstanding"),
        "short_ratio": info.get("shortRatio"),
        "analyst_target_mean": info.get("targetMeanPrice"),
        "analyst_target_low": info.get("targetLowPrice"),
        "analyst_target_high": info.get("targetHighPrice"),
        "analyst_recommendation": info.get("recommendationKey"),
        "number_of_analysts": info.get("numberOfAnalystOpinions"),
    }


def get_price_history(ticker: str, period: str = "1y") -> list[dict]:
    """Return OHLCV price history. period: 1mo, 3mo, 6mo, 1y, 2y, 5y."""
    t = yf.Ticker(ticker)
    hist = t.history(period=period)
    if hist.empty:
        return []
    return [
        {
            "date": str(idx.date()),
            "open": round(row["Open"], 2),
            "close": round(row["Close"], 2),
            "volume": int(row["Volume"]),
        }
        for idx, row in hist.iterrows()
    ]


def get_volatility(ticker: str) -> Optional[float]:
    """Return annualized 1-year historical volatility."""
    import numpy as np
    t = yf.Ticker(ticker)
    hist = t.history(period="1y")
    if hist.empty or len(hist) < 20:
        return None
    returns = hist["Close"].pct_change().dropna()
    return float(round(returns.std() * (252 ** 0.5), 4))


def get_peer_multiples(ticker: str) -> list[dict]:
    """
    Return basic multiples for sector peers (uses yfinance peer list if available,
    otherwise returns empty list — enrich with Polygon later).
    """
    t = yf.Ticker(ticker)
    info = t.info or {}
    # yfinance doesn't expose a peer list directly; return sector context
    return [{
        "source": "self",
        "ticker": ticker.upper(),
        "pe_trailing": info.get("trailingPE"),
        "ev_ebitda": info.get("enterpriseToEbitda"),
        "price_to_sales": info.get("priceToSalesTrailing12Months"),
    }]


def get_news(ticker: str, limit: int = 15) -> list[dict]:
    """Return recent news headlines with titles and links."""
    t = yf.Ticker(ticker)
    news = t.news or []
    results = []
    for item in news[:limit]:
        content = item.get("content", {})
        results.append({
            "title": content.get("title", item.get("title", "")),
            "publisher": content.get("provider", {}).get("displayName", ""),
            "link": content.get("canonicalUrl", {}).get("url", ""),
            "published": content.get("pubDate", ""),
        })
    return results


def get_analyst_ratings(ticker: str) -> dict:
    """Return analyst recommendations summary."""
    t = yf.Ticker(ticker)
    info = t.info or {}
    return {
        "recommendation": info.get("recommendationKey", ""),
        "target_mean": info.get("targetMeanPrice"),
        "target_low": info.get("targetLowPrice"),
        "target_high": info.get("targetHighPrice"),
        "num_analysts": info.get("numberOfAnalystOpinions"),
        "current_price": info.get("currentPrice"),
    }
