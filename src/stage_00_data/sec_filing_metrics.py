"""Deterministic SEC/XBRL filing metrics derived from EDGAR company facts."""
from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from config import DB_PATH
from db.loader import upsert_sec_filing_metrics_snapshot
from db.schema import create_tables
from src.stage_00_data.edgar_client import get_cik

# Bump when the extraction logic changes. Cached snapshots stamped with an older
# metric_source are ignored on read and recomputed on the next request, so rows
# produced by a buggy extractor cannot keep resurfacing from the DB cache.
_METRIC_SOURCE = "sec_xbrl_companyfacts_v2"


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


def _duration_days(start: Any, end: Any) -> int | None:
    try:
        start_date = datetime.fromisoformat(str(start)[:10])
        end_date = datetime.fromisoformat(str(end)[:10])
    except (TypeError, ValueError):
        return None
    return (end_date - start_date).days


def _extract_annual_series(ticker: str, metric_names: tuple[str, ...]) -> list[dict[str, float | str]]:
    if os.getenv("ALPHA_POD_EDGAR_CACHE_ONLY", "0").strip().lower() in {"1", "true", "yes"}:
        return []
    from edgar import Company
    try:
        facts = Company(ticker).get_facts()
    except Exception:
        return []

    candidates: list[list[dict[str, float | str]]] = []
    for metric_name in metric_names:
        try:
            q = facts.query().by_concept(metric_name).latest_periods(5, annual=True).to_dataframe()
            if q.empty:
                continue

            values_by_period: dict[str, list[tuple[float, int | None]]] = {}
            for _, row in q.iterrows():
                val = _to_float(row.get("numeric_value"))
                period = row.get("period_end")
                if not period or val is None:
                    continue
                # Annual filings also carry quarterly-duration facts under the
                # same period_end. Keep only ~1-year durations when the fact
                # has a period_start; keep rows without one (fail open into
                # the ambiguity check below).
                duration_days = _duration_days(row.get("period_start"), period)
                if duration_days is not None and not (300 <= duration_days <= 400):
                    continue
                normalized_period = str(period)[:10]
                try:
                    fiscal_year = int(row.get("fiscal_year")) if row.get("fiscal_year") is not None else None
                except (TypeError, ValueError):
                    fiscal_year = None
                values_by_period.setdefault(normalized_period, []).append((val, fiscal_year))

            # Resolve restatements by filing vintage when possible. A conflict
            # without a usable fiscal year, or a tie at the newest vintage, stays
            # omitted rather than guessing which value is correct.
            unambiguous: list[dict[str, float | str]] = []
            for period, observations in values_by_period.items():
                distinct_values = {value for value, _ in observations}
                if len(distinct_values) == 1:
                    value = next(iter(distinct_values))
                elif any(fiscal_year is None for _, fiscal_year in observations):
                    continue
                else:
                    max_fiscal_year = max(fiscal_year for _, fiscal_year in observations if fiscal_year is not None)
                    latest_values = {
                        value for value, fiscal_year in observations if fiscal_year == max_fiscal_year
                    }
                    if len(latest_values) != 1:
                        continue
                    value = next(iter(latest_values))
                unambiguous.append({"period": period, "value": value})

            annual: list[dict[str, float | str]] = []
            for item in sorted(unambiguous, key=lambda x: str(x["period"])):
                if not annual:
                    annual.append(item)
                    continue
                spacing_days = _duration_days(str(annual[-1]["period"]), str(item["period"]))
                if spacing_days is None or spacing_days > 300:
                    annual.append(item)
                else:
                    annual[-1] = item
            if annual:
                candidates.append(annual)
        except Exception:
            continue
    if not candidates:
        return []
    return max(candidates, key=lambda series: (str(series[-1]["period"]), len(series)))


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
    # Three consecutive fiscal years span ~2 years first-to-last (52/53-week
    # calendars wobble by a few days). A wider span means the series has year
    # gaps, and annualizing over the wrong period count would fabricate a CAGR.
    span_days = _duration_days(trimmed[0]["period"], trimmed[-1]["period"])
    if span_days is None or not (670 <= span_days <= 790):
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
    # Deliberately do not fall back to legacy metric_source rows: the version
    # stamp quarantines snapshots from poisoned extraction logic, and serving
    # those rows in cache-only mode would resurrect corrupted metrics.
    if as_of_date:
        row = conn.execute(
            """
            SELECT * FROM sec_filing_metrics_snapshot
            WHERE ticker = ? AND as_of_date = ? AND metric_source = ?
            LIMIT 1
            """,
            [ticker.upper(), as_of_date, _METRIC_SOURCE],
        ).fetchone()
    else:
        row = conn.execute(
            """
            SELECT * FROM sec_filing_metrics_snapshot
            WHERE ticker = ? AND metric_source = ?
            ORDER BY as_of_date DESC
            LIMIT 1
            """,
            [ticker.upper(), _METRIC_SOURCE],
        ).fetchone()
    return _row_to_metrics(row) if row is not None else None


def get_bridge_items_from_xbrl(ticker: str) -> dict:
    """
    Extract most recent annual EV bridge items from EDGAR XBRL.

    Returns a dict with keys (all in raw dollars, not millions):
        minority_interest, preferred_equity, lease_liabilities,
        pension_deficit, sbc
    Returns {} on any failure — never raises.
    """
    if os.getenv("ALPHA_POD_EDGAR_CACHE_ONLY", "0").strip().lower() in {"1", "true", "yes"}:
        return {}
    try:
        from edgar import Company
        facts = Company(ticker.upper()).get_facts()
    except Exception:
        return {}

    def _latest_annual_value(concept: str) -> float | None:
        try:
            q = facts.query().by_concept(concept).latest_periods(1, annual=True).to_dataframe()
            if q.empty:
                return None
            val = _to_float(q.iloc[0].get("numeric_value"))
            return val
        except Exception:
            return None

    operating_lease = _latest_annual_value("OperatingLeaseLiability")
    finance_lease = _latest_annual_value("FinanceLeaseLiability")
    minority_interest = _latest_annual_value("MinorityInterest")
    preferred_equity = _latest_annual_value("PreferredStockValue")
    pension_obligation = _latest_annual_value("DefinedBenefitPlanBenefitObligation")
    pension_assets = _latest_annual_value("DefinedBenefitPlanFairValueOfPlanAssets")
    sbc = _latest_annual_value("ShareBasedCompensation")

    lease_total = (operating_lease or 0.0) + (finance_lease or 0.0)
    pension_deficit = None
    if pension_obligation is not None and pension_assets is not None:
        pension_deficit = max(0.0, pension_obligation - pension_assets)

    result = {}
    if minority_interest is not None:
        result["minority_interest"] = minority_interest
    if preferred_equity is not None:
        result["preferred_equity"] = preferred_equity
    if lease_total > 0:
        result["lease_liabilities"] = lease_total
    if pension_deficit is not None:
        result["pension_deficit"] = pension_deficit
    if sbc is not None:
        result["sbc"] = sbc
    return result


def get_sec_filing_metrics(ticker: str, as_of_date: str | None = None) -> SecFilingMetrics | None:
    """Deterministically compute and cache filing-derived numeric metrics from SEC XBRL facts."""
    ticker = ticker.upper().strip()
    conn = _connect()
    try:
        cached = _load_cached_metrics(conn, ticker, as_of_date)
        if cached is not None:
            return cached

        cik = get_cik(ticker)
        revenue_series = _trim_series(
            _extract_annual_series(
                ticker,
                ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax"),
            ),
            n=3,
        )
        if not revenue_series:
            return None

        operating_income_series = _trim_series(
            _extract_annual_series(ticker, ("OperatingIncomeLoss",)),
            n=3,
        )
        gross_profit_series = _trim_series(
            _extract_annual_series(ticker, ("GrossProfit",)),
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
            metric_source=_METRIC_SOURCE,
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
