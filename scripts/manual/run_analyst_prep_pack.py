from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.manual.run_ticker_valuation_flow import DEFAULT_PROFILES, render_markdown, run_flow
from src.stage_04_pipeline.analyst_prep_pack import build_analyst_prep_payload, render_analyst_prep_markdown

DEFAULT_ANALYST_PREP_PROFILES = (*DEFAULT_PROFILES, "analyst_prep_synthesis")


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def _export_xlsx(ticker: str) -> dict[str, Any]:
    from src.stage_04_pipeline.export_service import run_ticker_export

    return run_ticker_export(
        ticker=ticker,
        export_format="xlsx",
        source_mode="loaded_backend_state",
        template_strategy="power_query",
        created_by="analyst_prep_pack_script",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Analyst Prep Pack MVP for one ticker.")
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--profiles", nargs="*", default=list(DEFAULT_ANALYST_PREP_PROFILES))
    parser.add_argument("--agent-mode", choices=("live", "heuristic"), default="heuristic")
    parser.add_argument("--skip-agent-runs", action="store_true")
    parser.add_argument("--include-existing-queue", action="store_true")
    parser.add_argument("--preview-queue", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--isolated-db", action="store_true")
    parser.add_argument("--market-cache-only", action="store_true")
    parser.add_argument("--edgar-cache-only", action="store_true")
    parser.add_argument("--ingest-ciq-template", action="store_true")
    parser.add_argument("--refresh-ciq", action="store_true")
    parser.add_argument("--ciq-symbol")
    parser.add_argument("--ciq-exchange")
    parser.add_argument("--ciq-date")
    parser.add_argument("--ciq-currency", default="USD")
    parser.add_argument("--ciq-template", default=str(ROOT / "ciq" / "templates" / "ciq_refresh_template.xlsx"))
    parser.add_argument("--ciq-input-json", default=str(ROOT / "ciq" / "templates" / "financials_input.json"))
    parser.add_argument("--ciq-folder", default=str(ROOT / "ciq" / "output"))
    parser.add_argument("--ciq-timeout-sec", type=int, default=180)
    parser.add_argument("--ciq-no-refresh", action="store_true")
    parser.add_argument("--ciq-template-folder", default=str(ROOT / "ciq" / "templates"))
    parser.add_argument("--use-openrouter-free", action="store_true")
    parser.add_argument("--openrouter-model", default="openrouter/free")
    parser.add_argument("--openrouter-fallback-models", nargs="*", default=[])
    parser.add_argument("--export-xlsx", action="store_true")
    parser.add_argument("--output-dir", default=str(ROOT / "output" / "analyst_prep"))
    return parser


def main() -> int:
    parser = _parser()
    args = parser.parse_args()
    ticker = args.ticker.upper().strip()
    run_stamp = _stamp()
    output_dir = Path(args.output_dir) / ticker
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"[analyst-prep] Running source flow for {ticker}...", file=sys.stderr)
    flow_result = run_flow(args)

    print("[analyst-prep] Building deterministic prep pack...", file=sys.stderr)
    prep_pack = build_analyst_prep_payload(ticker)
    flow_result["analyst_prep"] = prep_pack

    export_result: dict[str, Any] | None = None
    if args.export_xlsx:
        print("[analyst-prep] Exporting Excel workbook...", file=sys.stderr)
        export_result = _export_xlsx(ticker)
        flow_result["excel_export"] = export_result

    json_path = output_dir / f"{ticker}-{run_stamp}.json"
    md_path = output_dir / f"{ticker}-{run_stamp}.md"
    prep_md_path = output_dir / f"{ticker}-{run_stamp}-analyst-prep.md"
    _write_json(json_path, flow_result)
    md_path.write_text(render_markdown(flow_result), encoding="utf-8")
    prep_md_path.write_text(render_analyst_prep_markdown(prep_pack), encoding="utf-8")

    print("[analyst-prep] Done.")
    print(f"- JSON: {json_path}")
    print(f"- Flow markdown: {md_path}")
    print(f"- Prep markdown: {prep_md_path}")
    print(f"- Thesis cards: {len(prep_pack.get('thesis_cards') or [])}")
    print(f"- Driver cards: {len(prep_pack.get('driver_cards') or [])}")
    print(f"- Missing flags: {len(prep_pack.get('missing_data') or [])}")
    if export_result:
        artifacts = export_result.get("artifacts") or []
        workbook = next((item for item in artifacts if item.get("artifact_key") == "excel_workbook"), None)
        print(f"- Excel: {(workbook or {}).get('path') or export_result.get('bundle_dir')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
