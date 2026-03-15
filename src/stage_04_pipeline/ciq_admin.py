from __future__ import annotations

from dataclasses import asdict, is_dataclass
from importlib.util import find_spec
import os
from pathlib import Path
import sys
from typing import Any

from ciq.ciq_refresh import refresh_workbook
from ciq.ingest import _list_candidate_workbooks, ingest_ciq_folder
from ciq.workbook_parser import parse_ciq_workbook
from config import CIQ_DROP_FOLDER
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

    python_path = Path(python_executable)
    parts = [part.lower() for part in python_path.parts]
    if "envs" in parts:
        env_index = parts.index("envs")
        if env_index + 1 < len(python_path.parts):
            inferred_env = python_path.parts[env_index + 1]
            if active_env and active_env.lower() == inferred_env.lower():
                return active_env
            return inferred_env
    return active_env or ""


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

    return {
        "folder": str(folder),
        "candidate_workbooks": [path.name for path in _list_candidate_workbooks(folder)],
        "recommended_env": "ai-fund",
        "active_env": _detect_active_env(sys.executable),
        "python_executable": sys.executable,
        "module_status": module_status,
        "db_counts": db_counts,
        "db_error": db_error,
        "ignored_templates": ["IBM_Standard.xlsx", "~$*.xlsx"],
    }


def run_ciq_operation(action: str, folder_path: str | Path | None = None) -> dict[str, Any]:
    folder = Path(folder_path or CIQ_DROP_FOLDER)
    if action not in {"ingest_saved", "refresh_and_ingest", "dry_run_parse"}:
        raise ValueError(f"Unsupported CIQ action: {action}")

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
