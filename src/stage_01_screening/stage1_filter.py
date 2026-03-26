"""
Alpha Pod — Stage 1 Filter
Applies simple, fast filters to the seed universe using yfinance data.
Produces ~200-300 survivors for the CIQ deep screen (Stage 2).

All yfinance data is cached to avoid repeat API calls.

Usage:
    python -m src.stage_01_screening.stage1_filter
    python -m src.stage_01_screening.stage1_filter --force   # Force yfinance refresh
"""
import json
import sys
import time
import csv
from pathlib import Path
from datetime import datetime

import yfinance as yf
import pandas as pd

# Paths
ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
CACHE_DIR = DATA_DIR / "cache"
YFINANCE_CACHE_FILE = CACHE_DIR / "yfinance_info.json"
STAGE1_OUTPUT = DATA_DIR / "stage1_survivors.csv"
UNIVERSE_CSV = ROOT_DIR / "config" / "universe.csv"

# Cache config
YFINANCE_CACHE_MAX_AGE_HOURS = 24 * 3  # 3 days — fundamentals don't change hourly

# ── Stage 1 Filter Thresholds ──────────────────────────
# These target small/mid-cap quality companies.
# Adjust as needed — the idea is to cast a wide net, not be too strict.

FILTERS = {
    "min_market_cap_mm": 500,        # $500M floor
    "max_market_cap_mm": 10_000,     # $10B ceiling — avoid mega-caps
    "min_roe": 0.12,                 # 12% ROE floor (quality filter)
    "min_net_income": 0,             # Must be profitable
    "min_ipo_age_years": 2,          # Avoid recent IPOs
    "min_avg_volume": 100_000,       # Tradeable (shares/day)
    "excluded_sectors": [            # Harder to model, different frameworks
        "Financial Services",
        "Utilities",
        "Real Estate",
    ],
    "required_country": "United States",  # US-domiciled only
}


def _load_yfinance_cache() -> dict:
    """Load cached yfinance info data."""
    if not YFINANCE_CACHE_FILE.exists():
        return {"cached_at": None, "tickers": {}}
    try:
        with open(YFINANCE_CACHE_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, KeyError):
        return {"cached_at": None, "tickers": {}}


def _save_yfinance_cache(cache: dict):
    """Save yfinance info cache to disk."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache["cached_at"] = datetime.now().isoformat()
    with open(YFINANCE_CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2)


def _cache_is_fresh(cache: dict) -> bool:
    """Check if the yfinance cache is still fresh."""
    cached_at = cache.get("cached_at")
    if not cached_at:
        return False
    try:
        age_hours = (datetime.now() - datetime.fromisoformat(cached_at)).total_seconds() / 3600
        return age_hours < YFINANCE_CACHE_MAX_AGE_HOURS
    except (ValueError, TypeError):
        return False


def pre_filter_seed(seed: list[dict]) -> list[dict]:
    """
    Apply fast pre-filters using seed data (from NASDAQ listing API).
    This avoids expensive yfinance calls for obviously disqualified names.
    """
    current_year = datetime.now().year
    survivors = []

    for stock in seed:
        # Market cap filter (from seed data)
        mcap = stock.get("market_cap_mm")
        if mcap is None:
            continue
        if mcap < FILTERS["min_market_cap_mm"] or mcap > FILTERS["max_market_cap_mm"]:
            continue

        # Sector exclusion (from seed data)
        sector = stock.get("sector", "")
        if sector in FILTERS["excluded_sectors"]:
            continue

        # IPO age (from seed data)
        ipo_year = stock.get("ipo_year", "")
        if ipo_year and ipo_year != "N/A":
            try:
                if current_year - int(ipo_year) < FILTERS["min_ipo_age_years"]:
                    continue
            except (ValueError, TypeError):
                pass  # Can't parse — keep it

        # Country filter
        country = stock.get("country", "")
        if country and country != FILTERS["required_country"] and country != "":
            # NASDAQ API doesn't always have country; keep if missing
            pass

        survivors.append(stock)

    return survivors


def enrich_with_yfinance(tickers: list[str], force_refresh: bool = False) -> dict:
    """
    Fetch financial data (ROE, net income, volume) from yfinance.
    Uses aggressive caching — only fetches tickers not already in cache.

    Returns:
        Dict mapping ticker → info dict
    """
    cache = _load_yfinance_cache()

    # Determine which tickers need fetching
    if force_refresh or not _cache_is_fresh(cache):
        to_fetch = tickers
        print(f"[yfinance] Cache expired or force refresh — fetching all {len(tickers)} tickers")
    else:
        cached_tickers = set(cache.get("tickers", {}).keys())
        to_fetch = [t for t in tickers if t not in cached_tickers]
        print(f"[yfinance] {len(cached_tickers)} cached, {len(to_fetch)} need fetching")

    if to_fetch:
        print(f"[yfinance] Fetching data for {len(to_fetch)} tickers (this may take a few minutes)...")
        batch_size = 50  # Process in batches to show progress
        for i in range(0, len(to_fetch), batch_size):
            batch = to_fetch[i:i + batch_size]
            batch_num = i // batch_size + 1
            total_batches = (len(to_fetch) + batch_size - 1) // batch_size
            print(f"  Batch {batch_num}/{total_batches} ({len(batch)} tickers)...")

            for ticker in batch:
                try:
                    t = yf.Ticker(ticker)
                    info = t.get_info()
                    # Extract only what we need (keeps cache small)
                    cache.setdefault("tickers", {})[ticker] = {
                        "sector": info.get("sector", ""),
                        "industry": info.get("industry", ""),
                        "market_cap": info.get("marketCap"),
                        "roe": info.get("returnOnEquity"),
                        "net_income": info.get("netIncomeToCommon"),
                        "avg_volume": info.get("averageVolume"),
                        "avg_volume_10d": info.get("averageDailyVolume10Day"),
                        "country": info.get("country", ""),
                        "current_price": info.get("currentPrice"),
                        "trailing_pe": info.get("trailingPE"),
                        "forward_pe": info.get("forwardPE"),
                        "revenue_growth": info.get("revenueGrowth"),
                        "profit_margins": info.get("profitMargins"),
                        "company_name": info.get("longName") or info.get("shortName", ticker),
                        "fetched_at": datetime.now().isoformat(),
                    }
                except Exception as e:
                    cache.setdefault("tickers", {})[ticker] = {
                        "error": str(e),
                        "fetched_at": datetime.now().isoformat(),
                    }

                # Rate limiting: ~1 req/sec to be safe
                time.sleep(0.5)

            # Save cache after each batch (resume-friendly)
            _save_yfinance_cache(cache)
            print(f"    ✓ Cached ({i + len(batch)}/{len(to_fetch)} done)")

    return cache.get("tickers", {})


def apply_stage1_filters(pre_filtered: list[dict], yf_data: dict) -> pd.DataFrame:
    """
    Apply Stage 1 quality filters using yfinance data.
    Returns a DataFrame of survivors ranked by ROE.
    """
    survivors = []

    for stock in pre_filtered:
        ticker = stock["ticker"]
        info = yf_data.get(ticker, {})

        # Skip tickers that errored
        if "error" in info:
            continue

        # ROE filter
        roe = info.get("roe")
        if roe is None or roe < FILTERS["min_roe"]:
            continue

        # Profitability filter
        net_income = info.get("net_income")
        if net_income is None or net_income <= FILTERS["min_net_income"]:
            continue

        # Volume filter (use yfinance data — more accurate than seed)
        avg_vol = info.get("avg_volume") or info.get("avg_volume_10d")
        if avg_vol is not None and avg_vol < FILTERS["min_avg_volume"]:
            continue

        # Sector re-check with yfinance data (more accurate)
        yf_sector = info.get("sector", "")
        if yf_sector in FILTERS["excluded_sectors"]:
            continue

        # Country filter (yfinance is more reliable here)
        country = info.get("country", "")
        if country and country != FILTERS["required_country"]:
            continue

        # Market cap re-check from yfinance (more current)
        yf_mcap = info.get("market_cap")
        if yf_mcap is not None:
            yf_mcap_mm = yf_mcap / 1_000_000
            if yf_mcap_mm < FILTERS["min_market_cap_mm"] or yf_mcap_mm > FILTERS["max_market_cap_mm"]:
                continue
        else:
            yf_mcap_mm = stock.get("market_cap_mm")

        survivors.append({
            "ticker": ticker,
            "company_name": info.get("company_name") or stock.get("company_name", ""),
            "sector": yf_sector or stock.get("sector", ""),
            "industry": info.get("industry") or stock.get("industry", ""),
            "market_cap_mm": round(yf_mcap_mm, 0) if yf_mcap_mm else None,
            "roe": round(roe * 100, 1),  # As percentage
            "net_income_mm": round(net_income / 1_000_000, 1) if net_income else None,
            "avg_volume": avg_vol,
            "current_price": info.get("current_price"),
            "trailing_pe": info.get("trailing_pe"),
            "revenue_growth": info.get("revenue_growth"),
            "profit_margin": info.get("profit_margins"),
            "exchange": stock.get("exchange", ""),
        })

    df = pd.DataFrame(survivors)
    if not df.empty:
        df = df.sort_values("roe", ascending=False).reset_index(drop=True)
    return df


def write_universe_csv(df: pd.DataFrame):
    """Write Stage 1 survivors to universe.csv for the rest of the pipeline."""
    universe_rows = []
    today = datetime.now().strftime("%Y-%m-%d")
    for _, row in df.iterrows():
        universe_rows.append({
            "ticker": row["ticker"],
            "company_name": row["company_name"],
            "ciq_id": "",
            "sector": row["sector"],
            "industry": row["industry"],
            "market_cap_mm": row["market_cap_mm"],
            "country": "US",
            "status": "watchlist",
            "added_date": today,
            "notes": f"Stage1 screen (ROE={row['roe']}%)",
        })

    UNIVERSE_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(UNIVERSE_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "ticker", "company_name", "ciq_id", "sector", "industry",
            "market_cap_mm", "country", "status", "added_date", "notes",
        ])
        writer.writeheader()
        writer.writerows(universe_rows)


def run(force_refresh: bool = False):
    """Run the full Stage 1 screening pipeline."""
    print("=" * 60)
    print("ALPHA POD — Stage 1 Screener")
    print("=" * 60)
    print()

    # Step 1: Load seed universe
    print("[1/4] Loading seed universe...")
    from src.stage_01_screening.seed_universe import fetch_seed_universe
    seed = fetch_seed_universe()
    print(f"  → {len(seed)} total listings")
    print()

    # Step 2: Pre-filter using seed data (fast, no API calls)
    print("[2/4] Pre-filtering (market cap, sector, IPO age)...")
    pre_filtered = pre_filter_seed(seed)
    print(f"  → {len(pre_filtered)} pass pre-filters")
    print(f"  ({len(seed) - len(pre_filtered)} eliminated by market cap/sector/IPO filters)")
    print()

    # Step 3: Enrich survivors with yfinance (cached)
    print("[3/4] Enriching with yfinance data...")
    tickers = [s["ticker"] for s in pre_filtered]
    yf_data = enrich_with_yfinance(tickers, force_refresh=force_refresh)
    print()

    # Step 4: Apply quality filters
    print("[4/4] Applying quality filters (ROE, profitability, volume)...")
    survivors = apply_stage1_filters(pre_filtered, yf_data)
    print(f"  → {len(survivors)} Stage 1 survivors")
    print()

    if survivors.empty:
        print("⚠ No survivors! Consider loosening filter thresholds.")
        return

    # Save outputs
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    survivors.to_csv(STAGE1_OUTPUT, index=False)
    print(f"✓ Saved to {STAGE1_OUTPUT}")

    write_universe_csv(survivors)
    print(f"✓ Updated {UNIVERSE_CSV}")

    # Print summary
    print()
    print("=" * 60)
    print("STAGE 1 RESULTS")
    print("=" * 60)
    print(f"  Total survivors: {len(survivors)}")
    print(f"  Market cap range: ${survivors['market_cap_mm'].min():,.0f}M – ${survivors['market_cap_mm'].max():,.0f}M")
    print(f"  ROE range: {survivors['roe'].min():.1f}% – {survivors['roe'].max():.1f}%")
    print()
    print("  Sector breakdown:")
    for sector, count in survivors["sector"].value_counts().items():
        print(f"    {sector}: {count}")
    print()
    print("  Top 20 by ROE:")
    for _, row in survivors.head(20).iterrows():
        print(f"    {row['ticker']:<8} {row['company_name'][:35]:<36} "
              f"MCap ${row['market_cap_mm']:>8,.0f}M  ROE {row['roe']:>5.1f}%")
    print()
    print(f"Next: Load these {len(survivors)} tickers into CIQ for Stage 2 deep filter.")


if __name__ == "__main__":
    force = "--force" in sys.argv
    run(force_refresh=force)
