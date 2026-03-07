"""
Alpha Pod — Seed Universe
Downloads a broad list of US-listed equities from NASDAQ's free listing files.
No API keys needed. Results are cached locally.

Usage:
    python -m src.stage_01_screening.seed_universe
"""
import csv
import json
import io
import time
from pathlib import Path
from datetime import datetime

import requests

# NASDAQ provides free listing files (no auth required)
LISTING_URLS = {
    "nasdaq": "https://api.nasdaq.com/api/screener/stocks?tableonly=true&limit=5000&exchange=NASDAQ",
    "nyse":   "https://api.nasdaq.com/api/screener/stocks?tableonly=true&limit=5000&exchange=NYSE",
    "amex":   "https://api.nasdaq.com/api/screener/stocks?tableonly=true&limit=5000&exchange=AMEX",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}

# Cache config
CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "cache"
SEED_CACHE_FILE = CACHE_DIR / "seed_universe.json"
CACHE_MAX_AGE_HOURS = 24 * 7  # One week — listings don't change fast


def _cache_is_fresh() -> bool:
    """Check if the cached seed universe is still fresh."""
    if not SEED_CACHE_FILE.exists():
        return False
    try:
        with open(SEED_CACHE_FILE, "r") as f:
            data = json.load(f)
        cached_at = datetime.fromisoformat(data.get("cached_at", "2000-01-01"))
        age_hours = (datetime.now() - cached_at).total_seconds() / 3600
        return age_hours < CACHE_MAX_AGE_HOURS
    except (json.JSONDecodeError, KeyError, ValueError):
        return False


def _fetch_exchange(exchange: str, url: str) -> list[dict]:
    """Fetch stock listings from one exchange via NASDAQ API."""
    print(f"  Fetching {exchange} listings...")
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        rows = data.get("data", {}).get("table", {}).get("rows", [])
        print(f"    → {len(rows)} listings")
        return [{
            "ticker": row.get("symbol", "").strip(),
            "company_name": row.get("name", "").strip(),
            "market_cap_raw": row.get("marketCap", ""),
            "sector": row.get("sector", ""),
            "industry": row.get("industry", ""),
            "country": row.get("country", ""),
            "ipo_year": row.get("ipoyear", ""),
            "exchange": exchange.upper(),
        } for row in rows if row.get("symbol")]
    except Exception as e:
        print(f"    ✗ Failed to fetch {exchange}: {e}")
        return []


def _parse_market_cap(raw: str) -> float | None:
    """Parse NASDAQ market cap strings like '$1.23B' or '$456.78M' into millions."""
    if not raw or raw == "N/A" or raw == "":
        return None
    raw = raw.strip().replace(",", "").replace("$", "")
    try:
        if raw.endswith("T"):
            return float(raw[:-1]) * 1_000_000
        elif raw.endswith("B"):
            return float(raw[:-1]) * 1_000
        elif raw.endswith("M"):
            return float(raw[:-1])
        elif raw.endswith("K"):
            return float(raw[:-1]) / 1_000
        else:
            return float(raw) / 1_000_000  # Raw number → millions
    except (ValueError, TypeError):
        return None


def fetch_seed_universe(force_refresh: bool = False) -> list[dict]:
    """
    Get a broad list of all US-listed equities.
    Uses NASDAQ's free listing API with local caching.

    Returns:
        List of dicts with keys: ticker, company_name, market_cap_mm,
        sector, industry, country, ipo_year, exchange
    """
    # Check cache first
    if not force_refresh and _cache_is_fresh():
        print("[seed_universe] Loading from cache...")
        with open(SEED_CACHE_FILE, "r") as f:
            data = json.load(f)
        stocks = data["stocks"]
        print(f"  → {len(stocks)} stocks from cache (cached {data['cached_at']})")
        return stocks

    # Fetch from all exchanges
    print("[seed_universe] Downloading fresh listing data...")
    all_stocks = []
    for exchange, url in LISTING_URLS.items():
        stocks = _fetch_exchange(exchange, url)
        all_stocks.extend(stocks)
        time.sleep(1)  # Be polite

    # Parse market caps
    for stock in all_stocks:
        stock["market_cap_mm"] = _parse_market_cap(stock.pop("market_cap_raw"))

    # Deduplicate by ticker (some dual-listed)
    seen = set()
    unique = []
    for stock in all_stocks:
        if stock["ticker"] not in seen:
            seen.add(stock["ticker"])
            unique.append(stock)

    # Cache the results
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_data = {
        "cached_at": datetime.now().isoformat(),
        "count": len(unique),
        "stocks": unique,
    }
    with open(SEED_CACHE_FILE, "w") as f:
        json.dump(cache_data, f, indent=2)

    print(f"\n✓ Seed universe: {len(unique)} unique US-listed stocks")
    print(f"  Cached to {SEED_CACHE_FILE}")
    return unique


if __name__ == "__main__":
    stocks = fetch_seed_universe()
    # Quick stats
    with_mcap = [s for s in stocks if s["market_cap_mm"] is not None]
    sectors = {}
    for s in stocks:
        sec = s.get("sector") or "Unknown"
        sectors[sec] = sectors.get(sec, 0) + 1

    print(f"\nStats:")
    print(f"  Total:          {len(stocks)}")
    print(f"  With market cap: {len(with_mcap)}")
    print(f"  Sectors:")
    for sec, count in sorted(sectors.items(), key=lambda x: -x[1]):
        print(f"    {sec}: {count}")
