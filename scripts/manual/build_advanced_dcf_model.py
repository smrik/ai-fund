"""Build or refresh a formula-driven advanced DCF workbook for one ticker.

Two modes:

  Build (default) — generate a fresh, reconciling model workbook. This is *your*
  template: edit the formula sheets (DCF_Base, WACC, Sensitivity), add tabs, grow
  the model over time.

      python scripts/manual/build_advanced_dcf_model.py --ticker BAH

  Refresh — swap a different ticker's data into a model you already built and
  edited. Rebuilds only the data sheets; preserves your formula sheets, the PM
  Override column, and any sheets you added.

      python scripts/manual/build_advanced_dcf_model.py --ticker IBM \\
          --refresh data/exports/.../BAH_model.xlsx --output-path IBM_model.xlsx
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.stage_04_pipeline.advanced_dcf_model import (  # noqa: E402
    build_advanced_dcf_model,
    refresh_model_data,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--ticker", required=True, help="Ticker symbol, e.g. BAH")
    parser.add_argument(
        "--json-path",
        help="Optional valuation JSON path. Defaults to data/valuations/json/<TICKER>_latest.json.",
    )
    parser.add_argument("--output-path", help="Optional workbook output path.")
    parser.add_argument(
        "--guided-workup",
        help="Optional path to a guided-workup / analyst-prep JSON whose agent judgment "
        "(thesis + driver proposals) is surfaced read-only. Auto-discovered from "
        "output/guided_workups/<TICKER>/ if omitted.",
    )
    parser.add_argument(
        "--refresh",
        metavar="MODEL_XLSX",
        help="Refresh data into this existing model workbook instead of building fresh. "
        "Preserves formula sheets, PM overrides, and added sheets.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.refresh:
        out = refresh_model_data(
            args.refresh,
            ticker=args.ticker,
            json_path=args.json_path,
            output_path=args.output_path,
            guided_workup_path=args.guided_workup,
        )
        print(f"refreshed -> {out}")
    else:
        out = build_advanced_dcf_model(
            args.ticker,
            json_path=args.json_path,
            output_path=args.output_path,
            guided_workup_path=args.guided_workup,
        )
        print(f"built -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
