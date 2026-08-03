"""Build every driver-family projection locally and report size + contents.

No provider calls. Run this before dispatching an LLM run so we know exactly
what would be sent, instead of discovering it afterwards from envelope forensics.

Usage:
    python -m scripts.manual.inspect_family_projections MSFT
    python -m scripts.manual.inspect_family_projections --ticker MSFT
    python -m scripts.manual.inspect_family_projections MSFT --max-chars 200000
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.contracts.analysis_snapshot import AnalysisSnapshot
from src.contracts.assumption_registry import DriverFamily, judgment_owned_fields
from src.stage_04_pipeline.driver_family_workflow import _family_analysis_projection

LINE = "=" * 78
CHARS_PER_TOKEN_ESTIMATE = 4


def _db_path() -> Path:
    env = os.environ.get("ALPHA_POD_DB_PATH")
    if env:
        return Path(env)
    return ROOT / "data" / "alpha_pod.db"


def _load_snapshot(ticker: str) -> AnalysisSnapshot:
    """Load the latest analysis snapshot for a ticker from the database."""

    db = _db_path()
    if not db.exists():
        raise SystemExit(f"database not found: {db}")

    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        """
        SELECT payload_json
        FROM analysis_snapshots
        WHERE ticker = ?
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (ticker.upper(),),
    ).fetchone()
    conn.close()
    if row is None:
        raise SystemExit(f"no analysis snapshot found for ticker {ticker!r}")
    return AnalysisSnapshot.model_validate_json(row["payload_json"])


def _count_patterns(text: str) -> dict[str, tuple[int, int]]:
    """Count SEC URLs and verbose fact-id strings in the serialized text."""

    sec_urls = re.findall(r"https://www\.sec\.gov/[^\"]*", text)
    # xbrl-style fact IDs: source_type:TICKER:accession:hash
    fact_ids = re.findall(r"[a-z_-]+:[A-Z]+:[0-9-]+:[0-9a-f]+", text)
    return {
        "sec_urls": (len(sec_urls), sum(map(len, sec_urls))),
        "fact_ids": (len(fact_ids), sum(map(len, fact_ids))),
    }


def _component_sizes(projection: dict[str, Any]) -> list[tuple[str, int]]:
    """Return top-level projection components sorted by size descending."""

    return sorted(
        ((str(k), len(json.dumps(v))) for k, v in projection.items()),
        key=lambda kv: -kv[1],
    )


def _projection_stats(projection: dict[str, Any]) -> dict[str, Any]:
    """Extract key statistics from a built projection."""

    text = json.dumps(projection)
    patterns = _count_patterns(text)
    chars = len(text)

    # Statement stats
    statements = projection.get("statements", {})
    statement_scope = None
    retained_fact_count = None
    source_fact_count = None
    if isinstance(statements, dict):
        scope = statements.get("projection_scope", {})
        if isinstance(scope, dict):
            statement_scope = scope
            retained_fact_count = scope.get("retained_fact_count")
            source_fact_count = scope.get("source_fact_count")

    # Evidence stats
    evidence = projection.get("evidence", {})
    evidence_selected = None
    evidence_source = None
    if isinstance(evidence, dict):
        evidence_selected = evidence.get("selected_anchor_count")
        evidence_source = evidence.get("source_anchor_count")

    # Source table
    source_table = projection.get("source_table", [])
    source_table_count = len(source_table) if isinstance(source_table, list) else None

    # Reconciliation
    reconciliation = projection.get("statement_reconciliation", {})
    reconciliation_chars = len(json.dumps(reconciliation)) if reconciliation else 0

    # Projection scope
    projection_scope = projection.get("projection_scope", {})

    return {
        "chars": chars,
        "estimated_tokens": chars // CHARS_PER_TOKEN_ESTIMATE,
        "sec_urls": patterns["sec_urls"],
        "fact_ids": patterns["fact_ids"],
        "statement_retained_facts": retained_fact_count,
        "statement_source_facts": source_fact_count,
        "statement_scope": statement_scope,
        "evidence_selected_anchors": evidence_selected,
        "evidence_source_anchors": evidence_source,
        "source_table_count": source_table_count,
        "reconciliation_chars": reconciliation_chars,
        "projection_scope": projection_scope,
    }


def _run_inspection(
    ticker: str,
    max_chars: int,
    *,
    verbose: bool = False,
) -> None:
    print(f"Ticker: {ticker}")
    print(f"Max projection chars: {max_chars:,}")
    print(f"Database: {_db_path()}")
    print()

    snapshot = _load_snapshot(ticker)
    print(f"Snapshot hash: {snapshot.snapshot_hash}")
    print(f"As-of date:    {snapshot.as_of_date}")
    print(f"Captured at:   {snapshot.captured_at}")
    print(f"Total evidence anchors: {len(snapshot.evidence)}")
    statements = snapshot.statements
    consolidated = statements.get("consolidated_view", [])
    if isinstance(consolidated, (list, tuple)):
        print(f"Total statement facts:  {len(consolidated)}")
    print()

    grand_chars = 0
    family_results: list[tuple[DriverFamily, dict[str, Any] | None, str | None]] = []

    for family in DriverFamily:
        try:
            projection = _family_analysis_projection(
                snapshot, family, max_chars=max_chars
            )
        except OverflowError as exc:
            family_results.append((family, None, str(exc)))
            continue
        except Exception as exc:  # noqa: BLE001 — want the reason, not a crash
            family_results.append((family, None, f"{type(exc).__name__}: {exc}"))
            continue
        stats = _projection_stats(projection)
        grand_chars += stats["chars"]
        family_results.append((family, stats, None))

        print(LINE)
        print(f"FAMILY: {family.value}")
        print(LINE)
        drivers = sorted(judgment_owned_fields(family))
        print(f"  Drivers:        {', '.join(drivers)}")
        print(f"  Size:           {stats['chars']:>12,} chars  (~{stats['estimated_tokens']:,} tokens)")

        # Statement scoping
        if stats["statement_retained_facts"] is not None:
            print(
                f"  Statements:     {stats['statement_retained_facts']:>12,} retained facts "
                f"(of {stats['statement_source_facts'] or '?'} source)"
            )
            if stats["statement_scope"]:
                types = stats["statement_scope"].get("retained_statement_types", [])
                terms = stats["statement_scope"].get("selection_terms", [])
                if types:
                    print(f"    types:        {', '.join(types)}")
                if terms and verbose:
                    print(f"    terms:        {', '.join(terms)}")
        else:
            print("  Statements:     (no consolidated view)")

        # Evidence scoping
        if stats["evidence_selected_anchors"] is not None:
            print(
                f"  Evidence:       {stats['evidence_selected_anchors']:>12,} selected anchors "
                f"(of {stats['evidence_source_anchors'] or '?'} source)"
            )

        # Source table
        if stats["source_table_count"] is not None:
            print(f"  Source table:   {stats['source_table_count']:>12,} entries")

        # Reconciliation
        print(f"  Reconciliation: {stats['reconciliation_chars']:>12,} chars")

        # Boilerplate
        url_count, url_chars = stats["sec_urls"]
        fid_count, fid_chars = stats["fact_ids"]
        print(f"  SEC URLs:       {url_count:>12,} occurrences, {url_chars:,} chars")
        print(f"  Fact IDs:       {fid_count:>12,} occurrences, {fid_chars:,} chars")

        # Biggest components
        components = _component_sizes(projection)
        print("  Biggest components:")
        for key, size in components[:8]:
            pct = (size / stats["chars"] * 100) if stats["chars"] else 0
            print(f"    {key:36} {size:>10,}  ({pct:5.1f}%)")

        print()

    # Summary
    print(LINE)
    print("SUMMARY")
    print(LINE)
    print()
    blocked = []
    for family, stats, error in family_results:
        if error:
            print(f"  {family.value:35} BLOCKED: {error}")
            blocked.append(family)
        elif stats:
            print(
                f"  {family.value:35} "
                f"{stats['chars']:>10,} chars  "
                f"~{stats['estimated_tokens']:>8,} tokens  "
                f"stmts={stats['statement_retained_facts'] or 0}  "
                f"evidence={stats['evidence_selected_anchors'] or 0}  "
                f"sources={stats['source_table_count'] or 0}"
            )
    print()
    if blocked:
        print(f"  BLOCKED families: {', '.join(f.value for f in blocked)}")
    print(
        f"  TOTAL across {len(family_results) - len(blocked)} families: "
        f"{grand_chars:,} chars "
        f"(~{grand_chars // CHARS_PER_TOKEN_ESTIMATE:,} tokens per full run pass)"
    )
    print()

    # Threshold warning
    per_family_warn = 200_000
    for family, stats, error in family_results:
        if stats and stats["chars"] > per_family_warn:
            print(
                f"  WARNING: {family.value} exceeds {per_family_warn:,}-char "
                f"sanity threshold ({stats['chars']:,} chars)"
            )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Build driver-family projections locally and report size + contents. "
            "No provider calls."
        ),
    )
    parser.add_argument(
        "ticker",
        nargs="?",
        help="Ticker symbol (e.g. MSFT)",
    )
    parser.add_argument(
        "--ticker", "-t",
        dest="ticker_flag",
        help="Ticker symbol (alternative to positional)",
    )
    parser.add_argument(
        "--max-chars",
        type=int,
        default=50_000_000,
        help=(
            "Maximum chars per family projection. "
            "Defaults to 50M (effectively unbounded) so you see true sizes."
        ),
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show additional detail (selection terms, etc.)",
    )
    args = parser.parse_args()
    ticker = args.ticker or args.ticker_flag
    if not ticker:
        parser.error("ticker is required (positional or --ticker)")
    _run_inspection(
        ticker=ticker,
        max_chars=args.max_chars,
        verbose=args.verbose,
    )


if __name__ == "__main__":
    main()
