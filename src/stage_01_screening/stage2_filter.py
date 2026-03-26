"""
Stage 2 Deep Filter — CIQ snapshot-backed fundamental filter.

Reads normalized CIQ snapshot + long-form history from SQLite and applies
fundamental quality filters:
- ROIC > 10% for 3+ consecutive years
- FCF yield > 3%
- Revenue growth (positive 3-year trend)
- Debt/EBITDA < 3x
- Margin trend stable or expanding

Outputs the final ~25-50 names for deep LLM agent analysis.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from config.settings import DB_PATH, OUTPUT_DIR


def _percent_to_decimal(value: float | None) -> float | None:
    if value is None:
        return None
    if abs(value) > 1.5:
        return value / 100.0
    return value


def _load_stage2_input(conn: sqlite3.Connection) -> pd.DataFrame:
    query = """
    WITH latest AS (
        SELECT MAX(as_of_date) AS as_of_date
        FROM ciq_valuation_snapshot
    ),
    snap AS (
        SELECT s.*
        FROM ciq_valuation_snapshot s
        JOIN latest l ON s.as_of_date = l.as_of_date
    ),
    rev AS (
        SELECT
            ticker,
            period_date,
            value_num,
            ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY period_date DESC) AS rn
        FROM ciq_long_form
        WHERE metric_key = 'revenue' AND period_date IS NOT NULL AND value_num IS NOT NULL
    ),
    op AS (
        SELECT
            ticker,
            period_date,
            value_num,
            ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY period_date DESC) AS rn
        FROM ciq_long_form
        WHERE metric_key = 'operating_income' AND period_date IS NOT NULL AND value_num IS NOT NULL
    ),
    roic AS (
        SELECT
            ticker,
            period_date,
            value_num,
            ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY period_date DESC) AS rn
        FROM ciq_long_form
        WHERE metric_key = 'roic' AND period_date IS NOT NULL AND value_num IS NOT NULL
    )
    SELECT
        snap.ticker,
        snap.fcf_yield,
        snap.debt_to_ebitda,
        MAX(CASE WHEN rev.rn = 1 THEN rev.value_num END) AS rev_y1,
        MAX(CASE WHEN rev.rn = 4 THEN rev.value_num END) AS rev_y4,
        MAX(CASE WHEN roic.rn = 1 THEN roic.value_num END) AS roic_y1,
        MAX(CASE WHEN roic.rn = 2 THEN roic.value_num END) AS roic_y2,
        MAX(CASE WHEN roic.rn = 3 THEN roic.value_num END) AS roic_y3,
        MAX(CASE WHEN op.rn = 1 THEN op.value_num END) AS op_y1,
        MAX(CASE WHEN op.rn = 3 THEN op.value_num END) AS op_y3,
        MAX(CASE WHEN rev.rn = 1 THEN rev.period_date END) AS period_y1,
        MAX(CASE WHEN rev.rn = 3 THEN rev.period_date END) AS period_y3
    FROM snap
    LEFT JOIN rev ON snap.ticker = rev.ticker
    LEFT JOIN roic ON snap.ticker = roic.ticker
    LEFT JOIN op ON snap.ticker = op.ticker
    GROUP BY snap.ticker, snap.fcf_yield, snap.debt_to_ebitda
    """
    return pd.read_sql(query, conn)


def run_stage2_filter(export_csv: bool = True):
    print("=" * 60)
    print("STAGE 2 DEEP FILTER — CIQ Snapshot Fundamentals")
    print("=" * 60)

    conn = sqlite3.connect(str(DB_PATH))
    try:
        df = _load_stage2_input(conn)
    except Exception as e:
        print(f"Error loading CIQ snapshot data: {e}")
        conn.close()
        return
    finally:
        conn.close()

    if df.empty:
        print("No CIQ snapshot data found. Run `python -m ciq.ingest` first.")
        return

    # Normalize percent-like fields
    for col in ["fcf_yield", "roic_y1", "roic_y2", "roic_y3"]:
        if col in df.columns:
            df[col] = df[col].apply(_percent_to_decimal)

    # Compute operating margins for trend filter
    df["op_margin_y1"] = df.apply(
        lambda r: (r["op_y1"] / r["rev_y1"]) if pd.notna(r["op_y1"]) and pd.notna(r["rev_y1"]) and r["rev_y1"] else None,
        axis=1,
    )
    df["op_margin_y3"] = df.apply(
        lambda r: (r["op_y3"] / r["rev_y4"]) if pd.notna(r["op_y3"]) and pd.notna(r["rev_y4"]) and r["rev_y4"] else None,
        axis=1,
    )

    initial_count = len(df)
    print(f"Loaded {initial_count} tickers from CIQ snapshot.")

    survivors = df.copy()

    # Filter 1: ROIC Consistency (>10% for 3 periods)
    f_roic = (
        survivors["roic_y1"].fillna(-999) > 0.10
    ) & (
        survivors["roic_y2"].fillna(-999) > 0.10
    ) & (
        survivors["roic_y3"].fillna(-999) > 0.10
    )
    survivors = survivors[f_roic]
    print(f"  Passed ROIC > 10% consistency:  {len(survivors):>4} names")

    # Filter 2: FCF Yield (>3%)
    f_fcf = survivors["fcf_yield"].fillna(-999) > 0.03
    survivors = survivors[f_fcf]
    print(f"  Passed FCF Yield > 3%:          {len(survivors):>4} names")

    # Filter 3: Revenue trend positive (y1 > y4)
    f_rev = survivors["rev_y1"].fillna(-999) > survivors["rev_y4"].fillna(999999999999)
    survivors = survivors[f_rev]
    print(f"  Passed Positive Rev Growth:     {len(survivors):>4} names")

    # Filter 4: Leverage (Debt/EBITDA < 3.0x)
    f_debt = (survivors["debt_to_ebitda"].fillna(999) >= 0) & (survivors["debt_to_ebitda"].fillna(999) < 3.0)
    survivors = survivors[f_debt]
    print(f"  Passed Debt/EBITDA < 3.0x:      {len(survivors):>4} names")

    # Filter 5: Margin trend stable or expanding
    f_margin = survivors["op_margin_y1"].fillna(-999) >= (survivors["op_margin_y3"].fillna(999) - 0.02)
    survivors = survivors[f_margin]
    print(f"  Passed Margin Trend stable:     {len(survivors):>4} names")

    print()
    print(f"Final Watchlist Count: {len(survivors)} names")

    if export_csv and len(survivors) > 0:
        out_path = OUTPUT_DIR / "screens" / "stage2_watch_list.csv"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        survivors.to_csv(out_path, index=False)
        print(f"✓ Saved final watchlist to {out_path}")
        print()
        print("Next steps: Run these through the Agentic Valuation Pipeline for deep qualitative reviews.")


if __name__ == "__main__":
    run_stage2_filter()
