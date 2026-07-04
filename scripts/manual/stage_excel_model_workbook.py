from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stage the PowerQuery Excel model workbook for one ticker.")
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--json-path", help="Valuation JSON path. Defaults to data/valuations/json/<TICKER>_latest.json.")
    parser.add_argument("--template", help="Workbook template. Defaults to templates/20260614_template-GPT.xlsx.")
    parser.add_argument("--output-dir", default=str(ROOT / "data" / "exports" / "generated" / "ticker"))
    args = parser.parse_args(argv)

    from src.stage_04_pipeline.export_service import stage_excel_model_workbook
    from src.stage_04_pipeline.export_service import _ticker_bundle_dir
    from src.utils import coerce_ticker

    ticker = coerce_ticker(args.ticker)
    base_output = Path(args.output_dir)
    if base_output == ROOT / "data" / "exports" / "generated" / "ticker":
        bundle_dir = _ticker_bundle_dir(ticker, "excelmodel")
    else:
        bundle_dir = base_output / ticker
    result = stage_excel_model_workbook(
        ticker,
        bundle_dir,
        json_path=Path(args.json_path) if args.json_path else None,
        template_path=Path(args.template) if args.template else None,
    )
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
