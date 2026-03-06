"""
Stage 2 Deep Filter — processes Capital IQ data exports.

Reads the CSV exported by ciq_refresh.py and applies fundamental quality filters:
- ROIC > 10% for 3+ consecutive years (durable competitive advantage)
- FCF yield > 3% (real cash generation)
- Revenue growth (positive 3-year CAGR)
- Debt/EBITDA < 3x (manageable leverage)
- Margin trend stable or expanding

Outputs the final ~25-50 names for deep LLM agent analysis.
"""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import CIQ_EXPORTS_DIR, OUTPUT_DIR


def run_stage2_filter():
    print("=" * 60)
    print("STAGE 2 DEEP FILTER — Capital IQ Fundamentals")
    print("=" * 60)

    # 1. Load latest CIQ data
    latest_csv = CIQ_EXPORTS_DIR / "ciq_latest.csv"
    if not latest_csv.exists():
        print(f"Error: Could not find {latest_csv}")
        print("Run `python ciq/ciq_refresh.py` first to export data from CIQ.")
        return

    try:
        df = pd.read_csv(latest_csv)
    except Exception as e:
        print(f"Error reading CSV: {e}")
        return
        
    initial_count = len(df)
    print(f"Loaded {initial_count} tickers from CIQ export.")
    
    # 2. Normalize column names assuming a specific template structure
    # Expected columns roughly:
    # ticker, roic_y1, roic_y2, roic_y3, fcf_yield, rev_y1, rev_y4, debt_ebitda, op_margin_y1, op_margin_y3
    # (Where y1 = most recent year, y2 = prior year, etc.)
    #
    # Realistically, the user's Excel template might use different headers.
    # We will soft-match them or require the Excel to match these specific names.
    
    expected_cols = [
        "ticker", "roic_y1", "roic_y2", "roic_y3", 
        "fcf_yield", "rev_y1", "rev_y4", 
        "debt_ebitda", "op_margin_y1", "op_margin_y3"
    ]
    
    missing = [c for c in expected_cols if c not in df.columns]
    if missing:
        print(f"Warning: Missing expected columns from CIQ export: {missing}")
        print("Please ensure your ciq_screener.xlsx 'Export' tab matches these headers exactly.")
        print("Skipping Stage 2 deep filter due to missing columns.")
        return

    # 3. Apply Filters sequentially to see attrition
    survivors = df.copy()
    
    # Filter 1: ROIC Consistency (>10% for 3 years)
    f_roic = (survivors['roic_y1'] > 0.10) & (survivors['roic_y2'] > 0.10) & (survivors['roic_y3'] > 0.10)
    survivors = survivors[f_roic]
    print(f"  Passed ROIC > 10% consistency:  {len(survivors):>4} names")
    
    # Filter 2: FCF Yield (>3%)
    f_fcf = survivors['fcf_yield'] > 0.03
    survivors = survivors[f_fcf]
    print(f"  Passed FCF Yield > 3%:          {len(survivors):>4} names")
    
    # Filter 3: Revenue 3-year CAGR > 0 (just comparing y1 vs y4)
    f_rev = survivors['rev_y1'] > survivors['rev_y4']
    survivors = survivors[f_rev]
    print(f"  Passed Positive Rev Growth:     {len(survivors):>4} names")
    
    # Filter 4: Leverage (Debt/EBITDA < 3.0x)
    # Be careful with negative EBITDA or nan
    f_debt = (survivors['debt_ebitda'] >= 0) & (survivors['debt_ebitda'] < 3.0)
    survivors = survivors[f_debt]
    print(f"  Passed Debt/EBITDA < 3.0x:      {len(survivors):>4} names")
    
    # Filter 5: Margin Trend (Stable or expanding)
    # op_margin_y1 >= slightly below op_margin_y3 (-200bps tolerance)
    f_margin = survivors['op_margin_y1'] >= (survivors['op_margin_y3'] - 0.02)
    survivors = survivors[f_margin]
    print(f"  Passed Margin Trend stable:     {len(survivors):>4} names")

    # 4. Save final output
    print()
    print(f"Final Watchlist Count: {len(survivors)} names")
    
    if len(survivors) > 0:
        out_path = OUTPUT_DIR / "screens" / "stage2_watch_list.csv"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        survivors.to_csv(out_path, index=False)
        print(f"✓ Saved final watchlist to {out_path}")
        print()
        print("Next steps: Run these through the Agentic Valuation Pipeline for deep qualitative reviews.")


if __name__ == "__main__":
    run_stage2_filter()
