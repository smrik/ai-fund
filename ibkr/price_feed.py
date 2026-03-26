"""
Alpha Pod — IBKR Price Feed
Pull historical daily bars and compute derived metrics.
"""
from datetime import datetime, timedelta
from ib_insync import IB, Stock, util
import pandas as pd


def make_contract(ticker: str, exchange: str = "SMART", currency: str = "USD") -> Stock:
    """Create an IBKR Stock contract."""
    return Stock(ticker, exchange, currency)


def get_historical_bars(ib: IB, ticker: str, days: int = 365,
                        bar_size: str = "1 day") -> pd.DataFrame:
    """
    Pull historical daily OHLCV data from IBKR.

    Args:
        ib: Connected IB instance
        ticker: Stock ticker symbol
        days: Number of calendar days of history
        bar_size: Bar size string (IBKR format)

    Returns:
        DataFrame with columns: date, open, high, low, close, volume
    """
    contract = make_contract(ticker)
    ib.qualifyContracts(contract)

    duration = f"{days} D"
    bars = ib.reqHistoricalData(
        contract,
        endDateTime="",          # Now
        durationStr=duration,
        barSizeSetting=bar_size,
        whatToShow="TRADES",
        useRTH=True,             # Regular trading hours only
        formatDate=1,
    )

    if not bars:
        print(f"⚠ No historical data returned for {ticker}")
        return pd.DataFrame()

    df = util.df(bars)
    df = df.rename(columns={"date": "date"})
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df["ticker"] = ticker

    # Compute 20-day average volume
    df["avg_volume_20d"] = df["volume"].rolling(window=20, min_periods=1).mean()

    # Keep only the columns we need
    df = df[["ticker", "date", "open", "high", "low", "close", "volume", "avg_volume_20d"]]

    return df


def get_batch_prices(ib: IB, tickers: list[str], days: int = 30) -> pd.DataFrame:
    """
    Pull historical prices for multiple tickers.
    Handles IBKR rate limiting (max ~60 requests per 10 min).

    Args:
        ib: Connected IB instance
        tickers: List of ticker symbols
        days: Days of history per ticker

    Returns:
        Combined DataFrame for all tickers
    """
    all_data = []
    for i, ticker in enumerate(tickers):
        try:
            df = get_historical_bars(ib, ticker, days=days)
            if not df.empty:
                all_data.append(df)
                print(f"  [{i+1}/{len(tickers)}] {ticker}: {len(df)} bars")
            else:
                print(f"  [{i+1}/{len(tickers)}] {ticker}: NO DATA")
        except Exception as e:
            print(f"  [{i+1}/{len(tickers)}] {ticker}: ERROR — {e}")

        # IBKR rate limit: ~6 requests per 2 seconds
        if (i + 1) % 5 == 0:
            ib.sleep(2)

    if all_data:
        return pd.concat(all_data, ignore_index=True)
    return pd.DataFrame()


def get_current_price(ib: IB, ticker: str) -> float | None:
    """Get current/last price for a single ticker."""
    contract = make_contract(ticker)
    ib.qualifyContracts(contract)
    [ticker_data] = ib.reqTickers(contract)
    ib.sleep(1)  # Allow data to populate

    price = ticker_data.marketPrice()
    if price != price:  # NaN check
        price = ticker_data.close
    return price if price == price else None
