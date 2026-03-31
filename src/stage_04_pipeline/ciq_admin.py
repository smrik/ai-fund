from __future__ import annotations

from dataclasses import asdict, is_dataclass
from importlib.util import find_spec
import os
from pathlib import Path
import re
import sys
from typing import Any

from ciq.ciq_refresh import refresh_and_ingest_single_ticker, refresh_workbook
from ciq.ingest import _list_candidate_workbooks, ingest_ciq_folder
from ciq.workbook_parser import parse_ciq_workbook
from config import CIQ_DROP_FOLDER, CIQ_EXPORTS_DIR, CIQ_TEMPLATES_DIR
from db.schema import create_tables, get_connection


def _serialize(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return {k: _serialize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    return value


def _detect_active_env(python_executable: str) -> str:
    active_env = os.environ.get("CONDA_DEFAULT_ENV")

    raw_parts = [part for part in re.split(r"[\\/]+", python_executable) if part]
    parts = [part.lower() for part in raw_parts]
    if "envs" in parts:
        env_index = parts.index("envs")
        if env_index + 1 < len(raw_parts):
            inferred_env = raw_parts[env_index + 1]
            if active_env and active_env.lower() == inferred_env.lower():
                return active_env
            return inferred_env
    return active_env or ""


def _build_runtime_warnings(folder: Path, candidates: list[Path]) -> list[str]:
    warnings: list[str] = []

    try:
        resolved_folder = folder.resolve()
    except FileNotFoundError:
        resolved_folder = folder

    try:
        resolved_templates = CIQ_TEMPLATES_DIR.resolve()
    except FileNotFoundError:
        resolved_templates = CIQ_TEMPLATES_DIR

    if not folder.exists():
        warnings.append(f"Configured CIQ folder does not exist: {folder}")
    elif resolved_folder == resolved_templates:
        warnings.append(
            "CIQ folder points at the template directory. Live CIQ refresh/ingest should use the export/drop directory, not ciq/templates."
        )

    candidate_names = {path.name for path in candidates}
    if not candidates:
        warnings.append("No candidate workbooks found in the configured CIQ folder.")
    elif candidate_names == {"ciq_cleandata.xlsx"}:
        warnings.append(
            "Only ciq_cleandata.xlsx is present. That is a reference workbook, not evidence of live ticker CIQ coverage."
        )

    if resolved_folder != CIQ_EXPORTS_DIR and resolved_folder != resolved_templates:
        warnings.append(
            f"CIQ folder differs from the configured export landing directory ({CIQ_EXPORTS_DIR}). Verify your Excel/CIQ drop path is intentional."
        )

    return warnings


def get_ciq_runtime_status(folder_path: str | Path | None = None) -> dict[str, Any]:
    folder = Path(folder_path or CIQ_DROP_FOLDER)
    module_names = {
        "streamlit": "streamlit",
        "openpyxl": "openpyxl",
        "python_dotenv": "dotenv",
        "xlwings": "xlwings",
    }
    module_status = {name: bool(find_spec(spec_name)) for name, spec_name in module_names.items()}

    db_counts = {}
    db_error = None
    try:
        with get_connection() as conn:
            create_tables(conn)
            for table in ("ciq_ingest_runs", "ciq_valuation_snapshot", "ciq_comps_snapshot"):
                db_counts[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    except Exception as exc:
        db_error = str(exc)

    candidates = _list_candidate_workbooks(folder)

    return {
        "folder": str(folder),
        "candidate_workbooks": [path.name for path in candidates],
        "recommended_env": "ai-fund",
        "active_env": _detect_active_env(sys.executable),
        "python_executable": sys.executable,
        "module_status": module_status,
        "db_counts": db_counts,
        "db_error": db_error,
        "warnings": _build_runtime_warnings(folder, candidates),
        "ignored_templates": ["IBM_Standard.xlsx", "~$*.xlsx"],
    }


def run_ciq_operation(
    action: str,
    folder_path: str | Path | None = None,
    *,
    ticker: str | None = None,
    ciq_symbol: str | None = None,
    exchange: str | None = None,
) -> dict[str, Any]:
    folder = Path(folder_path or CIQ_DROP_FOLDER)
    if action not in {"ingest_saved", "refresh_and_ingest", "dry_run_parse", "refresh_single_ticker"}:
        raise ValueError(f"Unsupported CIQ action: {action}")

    if action == "refresh_single_ticker":
        if not ticker or not ticker.strip():
            raise ValueError("refresh_single_ticker requires ticker")
        result = refresh_and_ingest_single_ticker(
            ticker=ticker,
            ciq_symbol=ciq_symbol,
            exchange=exchange,
            output_folder=folder,
        )
        workbook_path = Path(result["workbook_path"])
        return {
            "action": action,
            "folder": str(folder),
            "ticker": result["ticker"],
            "ciq_symbol": result["ciq_symbol"],
            "workbook_path": str(workbook_path),
            "archive_path": result.get("archive_path"),
            "refreshed": bool(result["refreshed"]),
            "refresh_results": [{"file": workbook_path.name, "ok": bool(result["refreshed"])}],
            "report": _serialize(result["ingest_report"]),
        }

    refresh_results: list[dict[str, Any]] = []
    if action == "dry_run_parse":
        results: list[dict[str, Any]] = []
        processed = 0
        failed = 0
        for workbook in _list_candidate_workbooks(folder):
            try:
                payload = parse_ciq_workbook(workbook)
                results.append(
                    {
                        "file": workbook.name,
                        "status": "processed",
                        "ticker": getattr(payload, "ticker", None),
                        "as_of_date": getattr(payload, "as_of_date", None),
                    }
                )
                processed += 1
            except Exception as exc:
                results.append({"file": workbook.name, "status": "failed", "error": str(exc)})
                failed += 1
        return {
            "action": action,
            "folder": str(folder),
            "refresh_results": [],
            "report": {
                "folder": str(folder),
                "total_files": len(results),
                "processed": processed,
                "failed": failed,
                "results": results,
            },
        }

    if action == "refresh_and_ingest":
        for workbook in _list_candidate_workbooks(folder):
            ok = refresh_workbook(workbook)
            refresh_results.append({"file": workbook.name, "ok": bool(ok)})

    report = ingest_ciq_folder(folder)
    return {
        "action": action,
        "folder": str(folder),
        "refresh_results": refresh_results,
        "report": _serialize(report),
    }
