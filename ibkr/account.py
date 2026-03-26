"""
Alpha Pod — IBKR Account Data
Pull portfolio positions, NAV, margin, and P&L from IBKR.
"""
from datetime import datetime
from ib_insync import IB


def get_account_summary(ib: IB) -> dict:
    """
    Pull key account metrics from IBKR.
    Returns dict with NAV, cash, margin, etc.
    """
    summary = ib.accountSummary()
    result = {}
    for item in summary:
        if item.tag in (
            "NetLiquidation", "TotalCashValue", "GrossPositionValue",
            "MaintMarginReq", "AvailableFunds", "BuyingPower",
            "UnrealizedPnL", "RealizedPnL"
        ):
            result[item.tag] = float(item.value) if item.value else 0.0
    return result


def get_portfolio_positions(ib: IB) -> list[dict]:
    """
    Pull all current positions from IBKR.
    Returns list of position dicts ready for DB insertion.
    """
    positions = ib.positions()
    account = get_account_summary(ib)
    nav = account.get("NetLiquidation", 1.0)

    result = []
    for pos in positions:
        if pos.contract.secType != "STK":
            continue  # Skip non-equity positions for now

        ticker = pos.contract.symbol
        shares = pos.position
        avg_cost = pos.avgCost
        market_value = shares * avg_cost  # Will be updated with current price

        # Get current price for accurate P&L
        [ticker_data] = ib.reqTickers(pos.contract)
        ib.sleep(0.5)
        current_price = ticker_data.marketPrice()
        if current_price != current_price:  # NaN
            current_price = ticker_data.close

        if current_price and current_price == current_price:
            market_value = shares * current_price
            unrealized_pnl = (current_price - avg_cost) * shares
            pnl_pct = ((current_price / avg_cost) - 1) * 100 if avg_cost else 0
        else:
            unrealized_pnl = 0
            pnl_pct = 0

        weight_pct = (abs(market_value) / nav * 100) if nav else 0
        direction = "long" if shares > 0 else "short"

        result.append({
            "ticker": ticker,
            "direction": direction,
            "shares": int(abs(shares)),
            "avg_cost": round(avg_cost, 2),
            "current_price": round(current_price, 2) if current_price else None,
            "market_value": round(market_value, 2),
            "unrealized_pnl": round(unrealized_pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "weight_pct": round(weight_pct, 2),
            "entry_date": None,       # IBKR doesn't provide this; track in DB
            "thesis_link": None,
            "updated_at": datetime.utcnow().isoformat() + "Z",
        })

    return result


def compute_risk_snapshot(positions: list[dict], account: dict) -> dict:
    """
    Compute daily risk metrics from positions and account data.
    Returns dict ready for DB insertion.
    """
    nav = account.get("NetLiquidation", 0)

    long_value = sum(p["market_value"] for p in positions if p["direction"] == "long")
    short_value = sum(abs(p["market_value"]) for p in positions if p["direction"] == "short")

    gross = long_value + short_value
    net = long_value - short_value

    # Sector concentration (requires universe table join — simplified here)
    weights = [p["weight_pct"] for p in positions]
    top_weight = max(weights) if weights else 0

    # Margin
    margin_req = account.get("MaintMarginReq", 0)
    margin_pct = (margin_req / nav * 100) if nav else 0

    # Drawdown from high water mark (needs NAV history — placeholder)
    daily_pnl = account.get("UnrealizedPnL", 0) + account.get("RealizedPnL", 0)
    daily_pnl_pct = (daily_pnl / nav * 100) if nav else 0

    return {
        "date": datetime.utcnow().strftime("%Y-%m-%d"),
        "nav": round(nav, 2),
        "gross_exposure": round((gross / nav * 100) if nav else 0, 1),
        "net_exposure": round((net / nav * 100) if nav else 0, 1),
        "long_exposure": round((long_value / nav * 100) if nav else 0, 1),
        "short_exposure": round((short_value / nav * 100) if nav else 0, 1),
        "top_position_pct": round(top_weight, 1),
        "sector_max_pct": None,   # Computed separately with universe data
        "sector_max_name": None,
        "daily_pnl": round(daily_pnl, 2),
        "daily_pnl_pct": round(daily_pnl_pct, 2),
        "drawdown_from_hw": None,  # Computed from risk_daily history
        "margin_used_pct": round(margin_pct, 1),
    }
