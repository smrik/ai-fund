from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.stage_00_data.edgar_prefetch import DEFAULT_FORMS, prefetch_filings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Populate the local EDGAR filing cache for one ticker.")
    parser.add_argument("--ticker", required=True, help="Ticker to prefetch, e.g. MSFT")
    parser.add_argument("--forms", nargs="+", default=list(DEFAULT_FORMS), help="SEC forms to fetch")
    parser.add_argument("--limit", type=int, default=4, help="Maximum filings per form")
    parser.add_argument("--summary-only", action="store_true", help="Report cached filings without fetching")
    args = parser.parse_args(argv)

    result = prefetch_filings(
        args.ticker,
        forms=args.forms,
        limit=args.limit,
        summary_only=args.summary_only,
    )
    _print_table(result.rows)
    if result.errors:
        print("\nIssues:")
        for error in result.errors:
            print(f"- {error}")
    if result.cached_count <= 0:
        print(f"\nNo cached filing text available for {result.ticker}.")
        return 1
    print(f"\nCached filings with text for {result.ticker}: {result.cached_count}")
    return 0


def _print_table(rows) -> None:
    headers = ("form", "accession", "filing_date", "cached_chars", "cache")
    print(f"{headers[0]:<8} {headers[1]:<24} {headers[2]:<12} {headers[3]:>12} {headers[4]:<5}")
    print("-" * 68)
    for row in rows:
        filing_date = row.filing_date or ""
        print(f"{row.form_type:<8} {row.accession_no:<24} {filing_date:<12} {row.cached_chars:>12} {row.cache_status:<5}")


if __name__ == "__main__":
    raise SystemExit(main())
