from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.contracts.transcript import TranscriptDocument  # noqa: E402
from src.stage_00_data.quartr_client import persist_transcript  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate and import a normalized Quartr transcript JSON file.")
    parser.add_argument("--file", required=True, help="Path to TranscriptDocument JSON")
    parser.add_argument("--ticker", help="Optional ticker override")
    parser.add_argument("--dry-run", action="store_true", help="Validate without writing to transcript_cache")
    args = parser.parse_args(argv)

    try:
        payload = json.loads(Path(args.file).read_text(encoding="utf-8"))
        if args.ticker:
            payload["ticker"] = args.ticker
        doc = TranscriptDocument.model_validate(payload)
    except (OSError, json.JSONDecodeError, TypeError, ValidationError) as exc:
        print(f"Transcript validation failed: {exc}", file=sys.stderr)
        return 1

    if args.dry_run:
        print(f"Validated transcript {doc.document_id} for {doc.ticker}; dry run, no rows written.")
        return 0

    persist_transcript(doc)
    print(f"Imported transcript {doc.document_id} for {doc.ticker} ({doc.event_date}) into transcript_cache.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
