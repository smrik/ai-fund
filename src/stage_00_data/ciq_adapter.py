"""Adapter for reading latest CIQ valuation snapshot into compute-friendly fields."""
from __future__ import annotations

import sqlite3
from typing import Any

from config import DB_PATH


_MM_FIELDS = {
    "revenue_mm": "revenue_ttm",
    "operating_income_mm": "operating_income_ttm",
    "capex_mm": "capex_ttm",
    "da_mm": "da_ttm",
    "total_debt_mm": "total_debt",
    "cash_mm": "cash",
    "shares_out_mm": "shares_outstanding",
}


def _row_to_snapshot(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    out: dict[str, Any] = {
        "ticker": data.get("ticker"),
        "as_of_date": data.get("as_of_date"),
        "run_id": data.get("run_id"),
        "source_file": data.get("source_file"),
        "ebit_margin": data.get("ebit_margin"),
        "op_margin_avg_3yr": data.get("op_margin_avg_3yr"),
        "capex_pct_avg_3yr": data.get("capex_pct_avg_3yr"),
        "da_pct_avg_3yr": data.get("da_pct_avg_3yr"),
        "effective_tax_rate": data.get("effective_tax_rate"),
        "effective_tax_rate_avg": data.get("effective_tax_rate_avg"),
        "revenue_cagr_3yr": data.get("revenue_cagr_3yr"),
        "debt_to_ebitda": data.get("debt_to_ebitda"),
        "roic": data.get("roic"),
        "fcf_yield": data.get("fcf_yield"),
    }

    for mm_key, out_key in _MM_FIELDS.items():
        value = data.get(mm_key)
        out[out_key] = float(value) * 1_000_000.0 if value is not None else None

    return out


def get_ciq_snapshot(ticker: str, as_of_date: str | None = None) -> dict[str, Any] | None:
    """
    Read CIQ snapshot for ticker.

    Values stored in CIQ tables are in USD millions (raw CIQ scale). This adapter
    normalizes amount fields into absolute USD for compute-layer compatibility.
    """
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
    except sqlite3.Error:
        return None

    try:
        if as_of_date:
            row = conn.execute(
                """
                SELECT * FROM ciq_valuation_snapshot
                WHERE ticker = ? AND as_of_date = ?
                LIMIT 1
                """,
                [ticker.upper(), as_of_date],
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT * FROM ciq_valuation_snapshot
                WHERE ticker = ?
                ORDER BY as_of_date DESC, run_id DESC
                LIMIT 1
                """,
                [ticker.upper()],
            ).fetchone()
        return _row_to_snapshot(row) if row else None
    except sqlite3.OperationalError:
        return None
    finally:
        conn.close()
