"""Inspect a DB-backed Business Context Evidence Packet for a target ticker."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Add project root to sys.path
project_root = Path(__file__).resolve().parents[2]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.stage_04_pipeline.evidence.context import (  # noqa: E402
    build_business_context_packet,
)



def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inspect a DB-backed Business Context Evidence Packet."
    )
    parser.add_argument(
        "--db-path",
        type=str,
        required=True,
        help="Path to SQLite database containing canonical statement facts and section cache.",
    )
    parser.add_argument(
        "--ticker",
        type=str,
        default="MSFT",
        help="Ticker symbol to inspect (default: MSFT).",
    )
    args = parser.parse_args()

    packet = build_business_context_packet(args.db_path, args.ticker)

    print("=" * 80)
    print(f"BUSINESS CONTEXT EVIDENCE PACKET: {packet.ticker}")
    print("=" * 80)
    print(f"Profile Name:         {packet.profile_name}")
    print(f"Packet Kind:          {packet.packet_kind}")
    print(f"Generated At:         {packet.generated_at}")
    print(f"Source Quality:       {packet.run_metadata.get('source_quality')}")
    print(f"Evidence Sufficiency: {packet.run_metadata.get('evidence_sufficiency')}")
    print(f"Evidence Gaps:        {packet.run_metadata.get('evidence_gaps')}")
    print(f"Selected Chunk Count: {packet.run_metadata.get('selected_chunk_count')}")
    print(f"Canonical DB Path:    {packet.run_metadata.get('canonical_db_path')}")
    print(f"Financial As-Of:      {packet.run_metadata.get('financial_as_of_date')}")
    print()

    print("-" * 80)
    print(f"SOURCE REFS ({len(packet.source_refs)})")
    print("-" * 80)
    for idx, ref in enumerate(packet.source_refs, start=1):
        print(f" [{idx}] {ref.source_ref_id} ({ref.source_kind})")
        print(f"     Label:    {ref.source_label}")
        print(f"     Locator:  {ref.source_locator}")
        if ref.metadata:
            print(f"     Metadata: {json.dumps(ref.metadata)}")
    print()

    print("-" * 80)
    print(f"REPORTED FACTS ({len(packet.facts)})")
    print("-" * 80)
    for idx, fact in enumerate(packet.facts, start=1):
        print(f" [{idx}] {fact.fact_name}: {fact.value}")
        if fact.metadata:
            print(f"     Metadata: {json.dumps(fact.metadata)}")
    print()

    print("-" * 80)
    print(f"TEXT SNIPPETS ({len(packet.snippets)})")
    print("-" * 80)
    for idx, snippet in enumerate(packet.snippets, start=1):
        print(f" [{idx}] {snippet.snippet_id} (source: {snippet.source_ref_id})")
        if snippet.metadata:
            print(f"     Metadata: {json.dumps(snippet.metadata)}")
        preview = snippet.text[:200].replace("\n", " ")
        if len(snippet.text) > 200:
            preview += "..."
        print(f"     Preview:  {preview}")
        print()
    print("=" * 80)


if __name__ == "__main__":
    main()
