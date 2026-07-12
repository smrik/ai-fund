from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from math import isfinite
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.manual.run_ticker_valuation_flow import DEFAULT_PROFILES, render_markdown, run_flow  # noqa: E402
from src.stage_04_pipeline.analyst_prep_pack import build_analyst_prep_payload, render_analyst_prep_markdown  # noqa: E402

DEFAULT_ANALYST_PREP_PROFILES = (*DEFAULT_PROFILES, "analyst_prep_synthesis")


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _build_advanced_model(
    ticker: str,
    *,
    json_path: Path,
    guided_workup_path: Path | None = None,
) -> Path:
    from src.stage_04_pipeline.advanced_dcf_model import build_advanced_dcf_model

    return Path(
        build_advanced_dcf_model(
            ticker,
            json_path=json_path,
            guided_workup_path=guided_workup_path,
        )
    )


def _remove_unavailable_fcfe(payload: dict[str, Any]) -> None:
    """Omit the legacy flat FCFE branch until an integrated debt/interest schedule exists."""
    valuation = _as_dict(payload.get("valuation"))
    legacy_value_omitted = valuation.get("fcfe_iv_base") is not None
    valuation.pop("fcfe_iv_base", None)
    payload["valuation"] = valuation
    payload["method_availability"] = {
        **_as_dict(payload.get("method_availability")),
        "fcfe": {
            "status": "unavailable",
            "reason_code": "integrated_debt_interest_schedule_required",
            "detail": (
                "Legacy flat FCFE omits a supportable integrated debt and after-tax "
                "interest schedule, so it is excluded from model inputs."
            ),
            "legacy_value_omitted": legacy_value_omitted,
        },
    }
    excel_flat = _as_dict(payload.get("excel_flat"))
    excel_flat["valuation"] = [
        row
        for row in (excel_flat.get("valuation") or [])
        if isinstance(row, dict) and str(row.get("key") or "") != "fcfe_iv_base"
    ]
    for row in excel_flat.get("forecast") or []:
        if not isinstance(row, dict):
            continue
        for key in ("fcfe", "pv_fcfe", "fcfe_mm", "pv_fcfe_mm"):
            row.pop(key, None)
    payload["excel_flat"] = excel_flat
    for row in payload.get("forecast_bridge") or []:
        if not isinstance(row, dict):
            continue
        row.pop("fcfe", None)
        row.pop("pv_fcfe", None)


def _forecast_contract_issues(forecast: Any) -> list[str]:
    if not isinstance(forecast, list) or not forecast:
        return ["excel_flat.forecast is empty"]
    required_numeric = (
        "year",
        "revenue_mm",
        "ebit_mm",
        "nopat_mm",
        "da_mm",
        "capex_mm",
        "delta_nwc_mm",
        "fcff_mm",
    )
    issues: list[str] = []
    for index, row in enumerate(forecast, start=1):
        if not isinstance(row, dict):
            issues.append(f"row {index} is not an object")
            continue
        missing: list[str] = []
        for field in required_numeric:
            value = row.get(field)
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                missing.append(field)
                continue
            if not isfinite(numeric) or (field == "year" and numeric <= 0):
                missing.append(field)
        if missing:
            issues.append(f"row {index} missing numeric fields: {', '.join(missing)}")
    return issues



def build_run_bound_valuation_payload(
    ticker: str,
    flow_result: dict[str, Any],
    *,
    output_dir: Path,
    run_stamp: str,
) -> dict[str, Any]:
    """Write only the current deterministic run; never discover a *_latest.json."""
    batch_row = _as_dict(_as_dict(flow_result.get("deterministic")).get("batch_row"))
    if not batch_row or batch_row.get("error"):
        return {
            "status": "unavailable",
            "reason_code": "current_run_batch_row_unavailable",
            "path": None,
            "advanced_model_input": {
                "status": "unavailable",
                "reason_code": "current_run_batch_row_unavailable",
                "required_contract": "deterministic.batch_row",
            },
        }

    from src.stage_02_valuation.json_exporter import (
        build_historical_financials_from_ciq_workbook,
        build_nested_structure,
    )

    source_preflight = _as_dict(flow_result.get("source_preflight"))
    source = _as_dict(source_preflight.get("source"))
    historical_financials: list[dict[str, Any]] = []
    historical_status: dict[str, Any] = {
        "status": "unavailable",
        "reason_code": "source_workbook_path_unavailable",
    }
    raw_source_path = source.get("path")
    if raw_source_path:
        source_path = Path(str(raw_source_path)).expanduser()
        if source_path.exists() and source_path.is_file():
            try:
                historical_financials = build_historical_financials_from_ciq_workbook(
                    source_path,
                    expected_ticker=ticker,
                )
                historical_status = {
                    "status": "available",
                    "row_count": len(historical_financials),
                    "source_path": str(source_path.resolve()),
                }
            except Exception as exc:
                historical_status = {
                    "status": "unavailable",
                    "reason_code": "historical_financials_extraction_failed",
                    "detail": f"{type(exc).__name__}: {exc}",
                }

    payload = build_nested_structure(
        batch_row,
        historical_financials=historical_financials,
        source_preflight=source_preflight,
    )
    _remove_unavailable_fcfe(payload)
    payload["run_binding"] = {
        "run_started_at": flow_result.get("run_started_at"),
        "ciq_run_id": batch_row.get("ciq_run_id"),
        "ciq_comps_run_id": batch_row.get("ciq_comps_run_id"),
        "source_sha256": source.get("sha256"),
        "source_file": source.get("source_file"),
    }
    payload["historical_financials_availability"] = historical_status

    output_dir.mkdir(parents=True, exist_ok=True)
    valuation_path = output_dir / f"{ticker.upper()}-{run_stamp}-valuation.json"
    _write_json(valuation_path, payload)

    forecast = _as_dict(payload.get("excel_flat")).get("forecast")
    forecast_issues = _forecast_contract_issues(forecast)
    forecast_available = not forecast_issues
    advanced_input = (
        {
            "status": "available",
            "required_contract": "excel_flat.forecast",
            "row_count": len(forecast),
        }
        if forecast_available
        else {
            "status": "unavailable",
            "reason_code": (
                "excel_flat_forecast_unavailable"
                if not isinstance(forecast, list) or not forecast
                else "excel_flat_forecast_incompatible"
            ),
            "required_contract": "excel_flat.forecast",
            "row_count": len(forecast) if isinstance(forecast, list) else 0,
            "contract_issues": forecast_issues,
        }
    )
    return {
        "status": "available" if forecast_available else "incompatible",
        "path": str(valuation_path),
        "advanced_model_input": advanced_input,
        "source_binding": {
            "preflight_status": source_preflight.get("status") or "missing",
            "source_file": source.get("source_file"),
            "sha256": source.get("sha256"),
            "run_id": source.get("run_id"),
        },
        "historical_financials": historical_status,
    }


def export_current_run_xlsx(
    ticker: str,
    valuation_payload: dict[str, Any],
    *,
    decision_ready: bool,
    guided_workup_path: Path | None = None,
) -> dict[str, Any]:
    """Build from one explicit current-run JSON or return typed unavailability."""
    advanced_input = _as_dict(valuation_payload.get("advanced_model_input"))
    if advanced_input.get("status") != "available":
        return {
            "strategy": "none",
            "status": "unavailable",
            "reason_code": (
                advanced_input.get("reason_code")
                or valuation_payload.get("reason_code")
                or "advanced_model_input_unavailable"
            ),
            "required_contract": advanced_input.get("required_contract"),
            "valuation_json": valuation_payload.get("path"),
            "stale_latest_fallback_used": False,
        }

    raw_path = valuation_payload.get("path")
    valuation_path = Path(str(raw_path)).expanduser() if raw_path else None
    if valuation_path is None or not valuation_path.exists():
        return {
            "strategy": "none",
            "status": "unavailable",
            "reason_code": "current_run_valuation_json_missing",
            "valuation_json": str(valuation_path) if valuation_path else None,
            "stale_latest_fallback_used": False,
        }

    try:
        workbook_path = _build_advanced_model(
            ticker,
            json_path=valuation_path,
            guided_workup_path=guided_workup_path,
        )
    except Exception as exc:
        return {
            "strategy": "advanced_dcf_model",
            "status": "unavailable",
            "reason_code": "advanced_model_build_failed",
            "detail": f"{type(exc).__name__}: {exc}",
            "valuation_json": str(valuation_path),
            "stale_latest_fallback_used": False,
        }
    return {
        "strategy": "advanced_dcf_model",
        "status": "completed" if decision_ready else "diagnostic_blocked",
        "path": str(workbook_path),
        "valuation_json": str(valuation_path),
        "stale_latest_fallback_used": False,
    }


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

    json_path = output_dir / f"{ticker}-{run_stamp}.json"
    md_path = output_dir / f"{ticker}-{run_stamp}.md"
    prep_md_path = output_dir / f"{ticker}-{run_stamp}-analyst-prep.md"
    valuation_payload = build_run_bound_valuation_payload(
        ticker,
        flow_result,
        output_dir=output_dir,
        run_stamp=run_stamp,
    )
    flow_result["valuation_payload"] = valuation_payload
    _write_json(json_path, flow_result)

    export_result: dict[str, Any] | None = None
    if args.export_xlsx:
        print("[analyst-prep] Exporting Excel workbook...", file=sys.stderr)
        export_result = export_current_run_xlsx(
            ticker,
            valuation_payload,
            decision_ready=flow_result.get("decision_ready") is True,
            guided_workup_path=json_path,
        )
        flow_result["excel_export"] = export_result

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
    print(f"- Valuation JSON: {valuation_payload.get('path') or 'unavailable'}")
    print(f"- Advanced input: {_as_dict(valuation_payload.get('advanced_model_input')).get('status')}")
    if export_result:
        if export_result.get("path"):
            print(f"- Excel: {export_result.get('path')} ({export_result.get('status')})")
        else:
            print(
                f"- Excel unavailable: {export_result.get('reason_code') or 'unknown'}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
