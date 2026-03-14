"""Deterministic SEC/XBRL filing metrics derived from EDGAR company facts."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from config import DB_PATH
from db.loader import upsert_sec_filing_metrics_snapshot
from db.schema import create_tables
from src.stage_00_data.edgar_client import get_cik, get_company_facts


@dataclass
class SecFilingMetrics:
    ticker: str
    cik: str
    as_of_date: str | None
    source_filing_date: str | None
    source_form: str
    revenue_cagr_3y: float | None
    ebit_margin_avg_3y: float | None
    gross_margin_avg_3y: float | None
    fcf_yield: float | None
    net_debt_to_ebitda: float | None
    revenue_series: list[dict[str, float | str]]
    ebit_series: list[dict[str, float | str]]
    metric_source: str


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    create_tables(conn)
    return conn


def _to_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_annual_series(company_facts: dict, metric_names: tuple[str, ...]) -> list[dict[str, float | str]]:
    us_gaap = company_facts.get("facts", {}).get("us-gaap", {})
    for metric_name in metric_names:
        metric = us_gaap.get(metric_name)
        if not metric:
            continue
        units = metric.get("units", {})
        vals = units.get("USD") or units.get("pure") or []
        annual: list[dict[str, float | str]] = []
        for item in vals:
            if item.get("form") != "10-K":
                continue
            period = item.get("end")
            value = _to_float(item.get("val"))
            if not period or value is None:
                continue
            annual.append({"period": str(period), "value": value})
        annual.sort(key=lambda row: str(row["period"]))
        if annual:
            return annual
    return []


def _trim_series(series: list[dict[str, float | str]], n: int = 3) -> list[dict[str, float | str]]:
    return series[-n:] if len(series) > n else series


def _series_map(series: list[dict[str, float | str]]) -> dict[str, float]:
    return {
        str(item["period"]): float(item["value"])
        for item in series
        if _to_float(item["value"]) is not None
    }


def _compute_cagr(series: list[dict[str, float | str]]) -> float | None:
    trimmed = _trim_series(series, n=3)
    if len(trimmed) < 3:
        return None
    start = _to_float(trimmed[0]["value"])
    end = _to_float(trimmed[-1]["value"])
    if start is None or end is None or start <= 0:
        return None
    periods = len(trimmed) - 1
    return (end / start) ** (1.0 / periods) - 1.0


def _compute_margin(
    numerator_series: list[dict[str, float | str]],
    denominator_series: list[dict[str, float | str]],
) -> float | None:
    numerators = _series_map(_trim_series(numerator_series, n=3))
    denominators = _series_map(_trim_series(denominator_series, n=3))
    margins: list[float] = []
    for period, numerator in numerators.items():
        denominator = denominators.get(period)
        if denominator is not None and denominator > 0:
            margins.append(numerator / denominator)
    if not margins:
        return None
    return sum(margins) / len(margins)


def _row_to_metrics(row: sqlite3.Row) -> SecFilingMetrics:
    return SecFilingMetrics(
        ticker=str(row["ticker"]),
        cik=str(row["cik"]),
        as_of_date=row["as_of_date"],
        source_filing_date=row["source_filing_date"],
        source_form=str(row["source_form"]),
        revenue_cagr_3y=_to_float(row["revenue_cagr_3y"]),
        ebit_margin_avg_3y=_to_float(row["ebit_margin_avg_3y"]),
        gross_margin_avg_3y=_to_float(row["gross_margin_avg_3y"]),
        fcf_yield=_to_float(row["fcf_yield"]),
        net_debt_to_ebitda=_to_float(row["net_debt_to_ebitda"]),
        revenue_series=json.loads(row["revenue_series_json"] or "[]"),
        ebit_series=json.loads(row["ebit_series_json"] or "[]"),
        metric_source=str(row["metric_source"] or "sec_xbrl_companyfacts"),
    )


def _load_cached_metrics(conn: sqlite3.Connection, ticker: str, as_of_date: str | None) -> SecFilingMetrics | None:
    if as_of_date:
        row = conn.execute(
            """
            SELECT * FROM sec_filing_metrics_snapshot
            WHERE ticker = ? AND as_of_date = ?
            LIMIT 1
            """,
            [ticker.upper(), as_of_date],
        ).fetchone()
    else:
        row = conn.execute(
            """
            SELECT * FROM sec_filing_metrics_snapshot
            WHERE ticker = ?
            ORDER BY as_of_date DESC
            LIMIT 1
            """,
            [ticker.upper()],
        ).fetchone()
    return _row_to_metrics(row) if row is not None else None


def get_sec_filing_metrics(ticker: str, as_of_date: str | None = None) -> SecFilingMetrics | None:
    """Deterministically compute and cache filing-derived numeric metrics from SEC XBRL facts."""
    ticker = ticker.upper().strip()
    conn = _connect()
    try:
        cached = _load_cached_metrics(conn, ticker, as_of_date)
        if cached is not None:
            return cached

        cik = get_cik(ticker)
        company_facts = get_company_facts(cik)
        revenue_series = _trim_series(
            _extract_annual_series(
                company_facts,
                ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax"),
            ),
            n=3,
        )
        if not revenue_series:
            return None

        operating_income_series = _trim_series(
            _extract_annual_series(company_facts, ("OperatingIncomeLoss",)),
            n=3,
        )
        gross_profit_series = _trim_series(
            _extract_annual_series(company_facts, ("GrossProfit",)),
            n=3,
        )

        source_filing_date = str(revenue_series[-1]["period"])
        effective_as_of_date = as_of_date or source_filing_date
        metrics = SecFilingMetrics(
            ticker=ticker,
            cik=cik,
            as_of_date=effective_as_of_date,
            source_filing_date=source_filing_date,
            source_form="10-K",
            revenue_cagr_3y=_compute_cagr(revenue_series),
            ebit_margin_avg_3y=_compute_margin(operating_income_series, revenue_series),
            gross_margin_avg_3y=_compute_margin(gross_profit_series, revenue_series),
            fcf_yield=None,
            net_debt_to_ebitda=None,
            revenue_series=revenue_series,
            ebit_series=operating_income_series,
            metric_source="sec_xbrl_companyfacts",
        )

        upsert_sec_filing_metrics_snapshot(
            conn,
            {
                "ticker": metrics.ticker,
                "cik": metrics.cik,
                "as_of_date": metrics.as_of_date,
                "source_filing_date": metrics.source_filing_date,
                "source_form": metrics.source_form,
                "revenue_cagr_3y": metrics.revenue_cagr_3y,
                "ebit_margin_avg_3y": metrics.ebit_margin_avg_3y,
                "gross_margin_avg_3y": metrics.gross_margin_avg_3y,
                "net_debt_to_ebitda": metrics.net_debt_to_ebitda,
                "fcf_yield": metrics.fcf_yield,
                "revenue_series_json": json.dumps(metrics.revenue_series, separators=(",", ":")),
                "ebit_series_json": json.dumps(metrics.ebit_series, separators=(",", ":")),
                "metric_source": metrics.metric_source,
                "pulled_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            },
        )
        return metrics
    finally:
        conn.close()
