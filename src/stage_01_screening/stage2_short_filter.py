"""
Stage 2 Short Filter — CIQ snapshot-backed short candidate identification.

Mirrors stage2_filter.py but inverts criteria to surface deteriorating names.
Reads the same CIQ snapshot + long-form history and applies:

Hard filters (all must pass to be a short candidate):
  - ROIC declining for 3 consecutive periods OR below 5% in latest period
  - Revenue decelerating or declining (rev_y1 <= rev_y4)
  - Debt/EBITDA > 2.0x

Soft scoring (0-100, higher = stronger short signal):
  25%  roic_deterioration   — magnitude of ROIC decline
  20%  revenue_deceleration — magnitude of revenue deceleration/contraction
  20%  margin_compression   — margin fell > 2pp over 3 years
  20%  leverage_stress      — Debt/EBITDA level (>3x = full score)
  15%  dso_trend            — DSO rising (accounts receivable concern)

Outputs: data/screens/stage2_short_list.csv ranked by short_score DESC
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


def _load_short_input(conn: sqlite3.Connection) -> pd.DataFrame:
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
    ),
    dso AS (
        SELECT
            ticker,
            period_date,
            value_num,
            ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY period_date DESC) AS rn
        FROM ciq_long_form
        WHERE metric_key IN ('dso', 'days_sales_outstanding')
            AND period_date IS NOT NULL AND value_num IS NOT NULL
    )
    SELECT
        snap.ticker,
        snap.fcf_yield,
        snap.debt_to_ebitda,
        MAX(CASE WHEN rev.rn  = 1 THEN rev.value_num END) AS rev_y1,
        MAX(CASE WHEN rev.rn  = 4 THEN rev.value_num END) AS rev_y4,
        MAX(CASE WHEN roic.rn = 1 THEN roic.value_num END) AS roic_y1,
        MAX(CASE WHEN roic.rn = 2 THEN roic.value_num END) AS roic_y2,
        MAX(CASE WHEN roic.rn = 3 THEN roic.value_num END) AS roic_y3,
        MAX(CASE WHEN op.rn   = 1 THEN op.value_num   END) AS op_y1,
        MAX(CASE WHEN op.rn   = 3 THEN op.value_num   END) AS op_y3,
        MAX(CASE WHEN rev.rn  = 1 THEN rev.period_date END) AS period_y1,
        MAX(CASE WHEN dso.rn  = 1 THEN dso.value_num   END) AS dso_y1,
        MAX(CASE WHEN dso.rn  = 3 THEN dso.value_num   END) AS dso_y3
    FROM snap
    LEFT JOIN rev  ON snap.ticker = rev.ticker
    LEFT JOIN roic ON snap.ticker = roic.ticker
    LEFT JOIN op   ON snap.ticker = op.ticker
    LEFT JOIN dso  ON snap.ticker = dso.ticker
    GROUP BY snap.ticker, snap.fcf_yield, snap.debt_to_ebitda
    """
    return pd.read_sql(query, conn)


def _score_roic_deterioration(row: pd.Series) -> float:
    """0-1 score. Higher = ROIC deteriorating more severely."""
    y1 = row.get("roic_y1")
    y2 = row.get("roic_y2")
    y3 = row.get("roic_y3")
    if pd.isna(y1):
        return 0.0
    # Trend direction: roic falling y3 → y2 → y1
    trend_score = 0.0
    if not pd.isna(y2) and not pd.isna(y3):
        if y1 < y2 < y3:
            trend_score = 1.0         # clear declining trend
        elif y1 < y3:
            trend_score = 0.5         # falling overall but not monotonically
    # Level: below 5% = weak returns
    level_score = max(0.0, min(1.0, (0.05 - y1) / 0.15)) if y1 < 0.05 else 0.0
    return max(trend_score, level_score)


def _score_revenue_deceleration(row: pd.Series) -> float:
    """0-1 score. Higher = revenue more severely decelerating/declining."""
    y1 = row.get("rev_y1")
    y4 = row.get("rev_y4")
    if pd.isna(y1) or pd.isna(y4) or y4 <= 0:
        return 0.0
    growth = (y1 / y4) - 1.0  # 3-year cumulative growth
    if growth >= 0:
        return 0.0
    # Score scales: -5% contraction → 0.33, -15% → 1.0
    return min(1.0, abs(growth) / 0.15)


def _score_margin_compression(row: pd.Series) -> float:
    """0-1 score based on operating margin compression."""
    op_y1 = row.get("op_y1")
    op_y3 = row.get("op_y3")
    rev_y1 = row.get("rev_y1")
    rev_y4 = row.get("rev_y4")
    if pd.isna(op_y1) or pd.isna(op_y3) or pd.isna(rev_y1) or pd.isna(rev_y4):
        return 0.0
    if rev_y1 <= 0 or rev_y4 <= 0:
        return 0.0
    margin_y1 = op_y1 / rev_y1
    margin_y3 = op_y3 / rev_y4
    compression = margin_y3 - margin_y1  # positive = compression
    if compression <= 0.02:
        return 0.0
    # 2pp compression → 0, 10pp compression → 1.0
    return min(1.0, (compression - 0.02) / 0.08)


def _score_leverage_stress(row: pd.Series) -> float:
    """0-1 score. Debt/EBITDA > 3x → rising concern; > 5x → maximum."""
    d2e = row.get("debt_to_ebitda")
    if pd.isna(d2e) or d2e < 2.0:
        return 0.0
    # 2x → 0, 3x → 0.33, 5x → 1.0
    return min(1.0, (d2e - 2.0) / 3.0)


def _score_dso_trend(row: pd.Series) -> float:
    """0-1 score. Rising DSO = accounts receivable quality concern."""
    dso_y1 = row.get("dso_y1")
    dso_y3 = row.get("dso_y3")
    if pd.isna(dso_y1) or pd.isna(dso_y3) or dso_y3 <= 0:
        return 0.0
    rise_pct = (dso_y1 - dso_y3) / dso_y3
    if rise_pct <= 0.05:
        return 0.0
    # 5% rise → 0, 30% rise → 1.0
    return min(1.0, (rise_pct - 0.05) / 0.25)


def run_stage2_short_filter(export_csv: bool = True) -> pd.DataFrame | None:
    print("=" * 60)
    print("STAGE 2 SHORT FILTER — CIQ Snapshot Deterioration Screen")
    print("=" * 60)

    conn = sqlite3.connect(str(DB_PATH))
    try:
        df = _load_short_input(conn)
    except Exception as e:
        print(f"Error loading CIQ snapshot data: {e}")
        conn.close()
        return None
    finally:
        conn.close()

    if df.empty:
        print("No CIQ snapshot data found. Run `python -m ciq.ingest` first.")
        return None

    # Normalize percent fields
    for col in ["fcf_yield", "roic_y1", "roic_y2", "roic_y3"]:
        if col in df.columns:
            df[col] = df[col].apply(_percent_to_decimal)

    initial_count = len(df)
    print(f"Loaded {initial_count} tickers from CIQ snapshot.")
    print()
    print("Applying short-candidate hard filters:")

    candidates = df.copy()

    # Hard filter 1: ROIC declining or below 5%
    def _roic_bearish(row: pd.Series) -> bool:
        y1, y2, y3 = row.get("roic_y1"), row.get("roic_y2"), row.get("roic_y3")
        if pd.isna(y1):
            return False
        if y1 < 0.05:
            return True
        if not pd.isna(y2) and not pd.isna(y3) and y1 < y2 < y3:
            return True
        if not pd.isna(y3) and y1 < y3:
            return True
        return False

    mask_roic = candidates.apply(_roic_bearish, axis=1)
    candidates = candidates[mask_roic]
    print(f"  ROIC declining or < 5%:         {len(candidates):>4} names")

    # Hard filter 2: Revenue decelerating or declining
    mask_rev = candidates["rev_y1"].fillna(999999) <= candidates["rev_y4"].fillna(-999999)
    candidates = candidates[mask_rev]
    print(f"  Revenue decelerating/declining:  {len(candidates):>4} names")

    # Hard filter 3: Leverage > 2.0x
    mask_lev = candidates["debt_to_ebitda"].fillna(-1) > 2.0
    candidates = candidates[mask_lev]
    print(f"  Debt/EBITDA > 2.0x:              {len(candidates):>4} names")

    print()
    print(f"  Short candidate pool: {len(candidates)} names")
    print()
    print("Scoring...")

    if candidates.empty:
        print("No short candidates found after hard filters.")
        return candidates

    # Scoring weights (sum = 1.0)
    W_ROIC = 0.25
    W_REV = 0.20
    W_MARGIN = 0.20
    W_LEV = 0.20
    W_DSO = 0.15

    candidates = candidates.copy()
    candidates["score_roic"] = candidates.apply(_score_roic_deterioration, axis=1)
    candidates["score_rev"] = candidates.apply(_score_revenue_deceleration, axis=1)
    candidates["score_margin"] = candidates.apply(_score_margin_compression, axis=1)
    candidates["score_lev"] = candidates.apply(_score_leverage_stress, axis=1)
    candidates["score_dso"] = candidates.apply(_score_dso_trend, axis=1)

    candidates["short_score"] = (
        W_ROIC  * candidates["score_roic"]
        + W_REV   * candidates["score_rev"]
        + W_MARGIN * candidates["score_margin"]
        + W_LEV   * candidates["score_lev"]
        + W_DSO   * candidates["score_dso"]
    ).round(4)

    candidates.sort_values("short_score", ascending=False, inplace=True)

    print(f"{'Rank':<5} {'Ticker':<8} {'Score':>7}  {'ROIC':>7}  {'Rev chg':>8}  {'D/E':>6}  {'DSO rise':>9}")
    print("-" * 65)
    for rank, (_, row) in enumerate(candidates.head(25).iterrows(), 1):
        roic_y1 = row.get("roic_y1")
        rev_y1 = row.get("rev_y1")
        rev_y4 = row.get("rev_y4")
        rev_chg = ((rev_y1 / rev_y4) - 1) * 100 if (rev_y1 and rev_y4 and rev_y4 > 0) else float("nan")
        d2e = row.get("debt_to_ebitda")
        dso_y1 = row.get("dso_y1")
        dso_y3 = row.get("dso_y3")
        dso_rise = ((dso_y1 / dso_y3) - 1) * 100 if (dso_y1 and dso_y3 and dso_y3 > 0) else float("nan")
        print(
            f"{rank:<5} {row['ticker']:<8} {row['short_score']:>7.3f}  "
            f"{roic_y1*100:>6.1f}%  "
            f"{rev_chg:>+7.1f}%  "
            f"{d2e:>6.1f}x  "
            f"{dso_rise:>+8.1f}%"
        )

    if export_csv and len(candidates) > 0:
        out_path = OUTPUT_DIR / "screens" / "stage2_short_list.csv"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        candidates.to_csv(out_path, index=False)
        print()
        print(f"✓ Saved short candidate list to {out_path}")

    return candidates


if __name__ == "__main__":
    run_stage2_short_filter()
