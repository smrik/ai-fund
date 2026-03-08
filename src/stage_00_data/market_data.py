"""
Market data client using yfinance (free, no API key).
Provides prices, valuation multiples, analyst ratings, and news.
"""

import yfinance as yf
from typing import Optional
import logging

logger = logging.getLogger(__name__)


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


def _row(df, *keys):
    """Extract up to 3 years of data for a given row from a yfinance DataFrame."""
    if df is None or df.empty:
        return []
    for key in keys:
        if key in df.index:
            vals = df.loc[key].dropna().tolist()
            result = []
            for v in vals[:3]:
                try:
                    result.append(float(v))
                except (TypeError, ValueError):
                    pass
            return result
    return []


def get_historical_financials(ticker: str) -> dict:
    """
    Return 3-year historical financial series and derived DCF inputs.

    Uses yfinance annual statements (P&L, cash flow, balance sheet).
    Columns are ordered newest-first. Returns up to 3 years of data.

    Returns a dict with raw series (lists, newest first) and derived
    metrics (CAGR, average margins, etc.) used by the valuation layer.
    Never raises — returns dict of Nones on any failure.
    NWC sign: positive nwc_change means working capital consumed cash (use in FCF as negative).
    """
    _none_result = {
        "revenue": [],
        "operating_income": [],
        "capex": [],
        "da": [],
        "nwc_change": [],
        "interest_expense": [],
        "revenue_cagr_3yr": None,
        "op_margin_avg_3yr": None,
        "capex_pct_avg_3yr": None,
        "da_pct_avg_3yr": None,
        "nwc_pct_avg_3yr": None,
        "effective_tax_rate_avg": None,
        "cost_of_debt_derived": None,
        "dso_derived": None,
        "dio_derived": None,
        "dpo_derived": None,
    }

    try:
        t = yf.Ticker(ticker)

        # Fetch all three statements
        financials = t.financials      # annual P&L, rows=items, cols=dates newest first
        cashflow = t.cashflow          # annual cash flow
        balance = t.balance_sheet      # annual balance sheet

        # --- Raw series extraction ---
        revenue = _row(financials, "Total Revenue")
        cost_of_revenue = _row(financials, "Cost Of Revenue", "Cost of Revenue", "Cost of Goods Sold", "Cost Of Goods Sold")
        operating_income = _row(financials, "Operating Income", "EBIT")
        capex_raw = _row(cashflow, "Capital Expenditure")
        capex = [abs(v) for v in capex_raw]
        da = _row(cashflow, "Depreciation And Amortization", "Depreciation")
        interest_expense_raw = _row(financials, "Interest Expense")
        if not interest_expense_raw:
            interest_expense_raw = _row(cashflow, "Interest Expense Paid")
        interest_expense = [abs(v) for v in interest_expense_raw]

        tax_expense = _row(financials, "Tax Provision", "Income Tax Expense")
        pretax_income = _row(financials, "Pretax Income", "Income Before Tax")

        current_assets = _row(balance, "Current Assets")
        current_liabilities = _row(balance, "Current Liabilities")
        cash_bs = _row(balance, "Cash And Cash Equivalents", "Cash")
        total_debt = _row(balance, "Total Debt", "Long Term Debt")

        accounts_receivable = _row(balance, "Accounts Receivable", "Net Receivables", "Receivables")
        inventory = _row(balance, "Inventory", "Inventories")
        accounts_payable = _row(balance, "Accounts Payable", "Payables And Accrued Expenses", "Trade Payables")

        # --- NWC change series ---
        # NWC[i] = (CurrentAssets[i] - Cash[i]) - CurrentLiabilities[i]
        # nwc_change[i] = NWC[i] - NWC[i+1]  (i=0 is most recent)
        n_nwc = min(len(current_assets), len(current_liabilities), len(cash_bs))
        nwc_series = []
        for i in range(n_nwc):
            ca = current_assets[i]
            cl = current_liabilities[i]
            c = cash_bs[i]
            nwc_series.append(ca - c - cl)

        nwc_change = []
        for i in range(len(nwc_series) - 1):
            nwc_change.append(nwc_series[i] - nwc_series[i + 1])

        # --- Derived metrics ---

        # Revenue CAGR: (newest / oldest) ^ (1/(n-1)) - 1
        revenue_cagr_3yr = None
        if len(revenue) >= 2 and revenue[-1] != 0:
            n = len(revenue) - 1
            try:
                revenue_cagr_3yr = round((revenue[0] / revenue[-1]) ** (1.0 / n) - 1, 4)
            except (ZeroDivisionError, ValueError):
                revenue_cagr_3yr = None

        # Operating margin average
        op_margin_avg_3yr = None
        if revenue:
            margins = []
            for i in range(min(len(operating_income), len(revenue))):
                if revenue[i] != 0:
                    margins.append(operating_income[i] / revenue[i])
            if margins:
                op_margin_avg_3yr = round(sum(margins) / len(margins), 4)

        # Capex % of revenue average
        capex_pct_avg_3yr = None
        if revenue:
            pcts = []
            for i in range(min(len(capex), len(revenue))):
                if revenue[i] != 0:
                    pcts.append(capex[i] / revenue[i])
            if pcts:
                capex_pct_avg_3yr = round(sum(pcts) / len(pcts), 4)

        # D&A % of revenue average
        da_pct_avg_3yr = None
        if revenue:
            pcts = []
            for i in range(min(len(da), len(revenue))):
                if revenue[i] != 0:
                    pcts.append(da[i] / revenue[i])
            if pcts:
                da_pct_avg_3yr = round(sum(pcts) / len(pcts), 4)

        # NWC change % of revenue average
        nwc_pct_avg_3yr = None
        if revenue and nwc_change:
            pcts = []
            for i in range(min(len(nwc_change), len(revenue))):
                if revenue[i] != 0:
                    pcts.append(nwc_change[i] / revenue[i])
            if pcts:
                nwc_pct_avg_3yr = round(sum(pcts) / len(pcts), 4)


        # NWC day-driver approximations (using revenue denominator)
        # NWC day-driver approximations
        # DSO uses revenue denominator.
        # DIO/DPO prefer COGS denominator when available, falling back to revenue.
        dso_derived = None
        dso_values = []
        for i in range(min(len(accounts_receivable), len(revenue))):
            if revenue[i] and revenue[i] > 0:
                dso = 365.0 * accounts_receivable[i] / revenue[i]
                if 0 < dso <= 365:
                    dso_values.append(dso)
        if dso_values:
            dso_derived = round(sum(dso_values) / len(dso_values), 1)

        dio_derived = None
        dio_values = []
        for i in range(min(len(inventory), len(revenue))):
            denom = None
            if i < len(cost_of_revenue) and cost_of_revenue[i] and cost_of_revenue[i] > 0:
                denom = cost_of_revenue[i]
            elif revenue[i] and revenue[i] > 0:
                denom = revenue[i]
            if denom:
                dio = 365.0 * inventory[i] / denom
                if 0 < dio <= 500:
                    dio_values.append(dio)
        if dio_values:
            dio_derived = round(sum(dio_values) / len(dio_values), 1)

        dpo_derived = None
        dpo_values = []
        for i in range(min(len(accounts_payable), len(revenue))):
            denom = None
            if i < len(cost_of_revenue) and cost_of_revenue[i] and cost_of_revenue[i] > 0:
                denom = cost_of_revenue[i]
            elif revenue[i] and revenue[i] > 0:
                denom = revenue[i]
            if denom:
                dpo = 365.0 * accounts_payable[i] / denom
                if 0 < dpo <= 365:
                    dpo_values.append(dpo)
        if dpo_values:
            dpo_derived = round(sum(dpo_values) / len(dpo_values), 1)

        # Effective tax rate average (use absolute ratio to handle sign convention variability)
        effective_tax_rate_avg = None
        rates = []
        for i in range(min(len(tax_expense), len(pretax_income))):
            denom = abs(pretax_income[i]) if pretax_income[i] is not None else 0
            if denom > 0:
                rate = abs(tax_expense[i]) / denom
                if 0.05 <= rate <= 0.40:
                    rates.append(rate)
        if rates:
            effective_tax_rate_avg = round(sum(rates) / len(rates), 4)
        # Cost of debt derived: interest_expense[0] / total_debt[0]
        cost_of_debt_derived = None
        if interest_expense and total_debt and total_debt[0] > 0:
            kd = interest_expense[0] / total_debt[0]
            if 0.02 <= kd <= 0.15:
                cost_of_debt_derived = round(kd, 4)

        return {
            "revenue": revenue,
            "operating_income": operating_income,
            "capex": capex,
            "da": da,
            "nwc_change": nwc_change,
            "interest_expense": interest_expense,
            "revenue_cagr_3yr": revenue_cagr_3yr,
            "op_margin_avg_3yr": op_margin_avg_3yr,
            "capex_pct_avg_3yr": capex_pct_avg_3yr,
            "da_pct_avg_3yr": da_pct_avg_3yr,
            "nwc_pct_avg_3yr": nwc_pct_avg_3yr,
            "effective_tax_rate_avg": effective_tax_rate_avg,
            "cost_of_debt_derived": cost_of_debt_derived,
            "dso_derived": dso_derived,
            "dio_derived": dio_derived,
            "dpo_derived": dpo_derived,
        }

    except Exception as e:
        logger.warning("get_historical_financials(%s) failed: %s", ticker, e)
        return _none_result




