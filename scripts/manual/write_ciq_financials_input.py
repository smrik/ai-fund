"""Write the CIQ Power Query input JSON for a single ticker."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ciq.ciq_refresh import DEFAULT_INPUT_JSON_NAME, CIQ_TEMPLATES_DIR, write_financials_input


def _ciq_symbol(args: argparse.Namespace) -> str:
    if args.ciq_symbol:
        return str(args.ciq_symbol).upper()
    if args.exchange:
        return f"{str(args.exchange).upper()}:{str(args.ticker).upper()}"
    return str(args.ticker).upper()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Write ciq/templates/financials_input.json for Excel Power Query refresh."
    )
    parser.add_argument("--ticker", required=True, help="Ticker used for operator clarity, e.g. MSFT")
    parser.add_argument("--ciq-symbol", help="Exact CIQ symbol, e.g. NASDAQ:MSFT")
    parser.add_argument("--exchange", help="Exchange prefix used when --ciq-symbol is omitted")
    parser.add_argument("--date", help="Optional as-of date in YYYY-MM-DD format")
    parser.add_argument("--currency", default="USD")
    parser.add_argument(
        "--output",
        default=str(CIQ_TEMPLATES_DIR / DEFAULT_INPUT_JSON_NAME),
        help="Output JSON path consumed by the CIQ template Power Query.",
    )
    args = parser.parse_args()

    output_path = Path(args.output)
    payload = write_financials_input(
        output_path,
        ciq_symbol=_ciq_symbol(args),
        as_of_date=args.date,
        currency=args.currency,
    )

    print(f"Wrote {output_path}")
    print(json.dumps({"ticker": args.ticker.upper(), "payload": payload}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
