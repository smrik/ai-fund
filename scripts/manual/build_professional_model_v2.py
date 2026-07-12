"""Build the cache-only professional-model v2 workbook and audit manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.stage_04_pipeline.professional_model_adapter import (  # noqa: E402
    ProfessionalModelAdapterError,
    build_professional_model_v2,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build a run-bound, cache-only 26-sheet professional finance model. "
            "The source workbook is read-only and native Excel recalculation is not run."
        )
    )
    parser.add_argument("--ticker", required=True, help="Ticker symbol, e.g. MSFT")
    parser.add_argument("--db-path", required=True, type=Path, help="SQLite cache path")
    parser.add_argument("--run-id", required=True, type=int, help="Exact completed CIQ ingest run ID")
    parser.add_argument(
        "--workbook-path",
        required=True,
        type=Path,
        help="Exact Standard source workbook used by the selected run",
    )
    parser.add_argument(
        "--valuation-json",
        required=True,
        type=Path,
        help="Explicit timestamped frozen valuation JSON; latest aliases are rejected",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "output" / "professional_models",
        help="Output root; artifacts are written under <root>/<ticker>/<run-id>/",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.run_id <= 0:
        raise SystemExit("--run-id must be positive")
    try:
        artifacts = build_professional_model_v2(
            ticker=args.ticker.upper(),
            db_path=args.db_path,
            run_id=args.run_id,
            workbook_path=args.workbook_path,
            valuation_json=args.valuation_json,
            output_dir=args.output_dir,
        )
    except ProfessionalModelAdapterError as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}, indent=2), file=sys.stderr)
        return 2

    verification_path = artifacts.output_dir / "calculation_verification.json"
    recalc_argv = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "manual" / "recalculate_excel_isolated.py"),
        str(artifacts.workbook_path),
        "--model-input-hash",
        artifacts.manifest.model_input_hash,
        "--expected-formula-text-hash",
        str(artifacts.manifest.expected_formula_text_hash),
        "--verification-output",
        str(verification_path),
    ]
    print(
        json.dumps(
            {
                "status": "built_blocked" if artifacts.manifest.blockers else "built",
                "ticker": artifacts.payload.ticker,
                "run_id": artifacts.payload.source.run_id,
                "source_hash": artifacts.payload.source.source_hash,
                "model_input_hash": artifacts.manifest.model_input_hash,
                "expected_formula_text_hash": (
                    artifacts.manifest.expected_formula_text_hash
                ),
                "workflow_state": artifacts.payload.backend_checks.get(
                    "workflow.package.state",
                    "UNVERIFIED",
                ),
                "calculation_verification_state": "UNVERIFIED",
                "calculation_verification_path": str(verification_path),
                "recalculation_argv": recalc_argv,
                "workbook": str(artifacts.workbook_path),
                "manifest": str(artifacts.manifest_path),
                "blockers": list(artifacts.manifest.blockers),
                "warnings": list(artifacts.manifest.warnings),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

