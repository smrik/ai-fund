from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from db.schema import get_connection  # noqa: E402
from src.stage_04_pipeline.statement_source_refresh import (  # noqa: E402
    refresh_statement_sources,
)


def _workbook_mapping(
    parser: argparse.ArgumentParser,
    values: list[str],
) -> dict[str, Path]:
    mapping: dict[str, Path] = {}
    for value in values:
        ticker, separator, path_text = value.partition("=")
        ticker = ticker.strip().upper()
        path_text = path_text.strip()
        if not separator or not ticker or not path_text:
            parser.error(
                "--ciq-workbook must use TICKER=PATH, "
                "for example MSFT=data/exports/MSFT_Standard.xlsx"
            )
        if ticker in mapping:
            parser.error(f"duplicate CIQ workbook mapping for {ticker}")
        mapping[ticker] = Path(path_text)
    return mapping


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Refresh accession XBRL and explicit CIQ statement sources, "
            "then run the fail-closed statement reconciliation gate."
        )
    )
    parser.add_argument(
        "--ticker",
        action="append",
        required=True,
        help="Ticker to refresh; repeat for a batch.",
    )
    parser.add_argument(
        "--evidence-cutoff",
        help="Optional as-of cutoff in YYYY-MM-DD form.",
    )
    ciq_group = parser.add_mutually_exclusive_group()
    ciq_group.add_argument(
        "--ciq-workbook",
        action="append",
        default=[],
        metavar="TICKER=PATH",
        help="Exact workbook for one requested ticker; repeat as needed.",
    )
    ciq_group.add_argument(
        "--ciq-folder",
        help="Explicit folder whose CIQ workbooks should be ingested.",
    )
    parser.add_argument(
        "--db-path",
        help="Optional SQLite database path; defaults to Alpha Pod config.",
    )
    args = parser.parse_args(argv)

    workbooks = _workbook_mapping(parser, args.ciq_workbook)
    connection = get_connection(args.db_path) if args.db_path else None
    try:
        batch = refresh_statement_sources(
            args.ticker,
            connection=connection,
            evidence_cutoff=args.evidence_cutoff,
            ciq_workbooks=workbooks or None,
            ciq_folder=args.ciq_folder,
        )
    finally:
        if connection is not None:
            connection.close()
    print(json.dumps(batch.as_dict(), indent=2, sort_keys=True))
    return 0 if batch.status_counts["decision_grade"] == batch.requested_count else 1


if __name__ == "__main__":
    raise SystemExit(main())
