"""Folder-based CIQ workbook ingestion into normalized SQLite tables."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Iterable

from config import CIQ_DROP_FOLDER, CIQ_WORKBOOK_GLOB
from db.loader import (
    finalize_ciq_ingest_run,
    insert_ciq_long_form,
    register_ciq_ingest_run,
    upsert_ciq_comps_snapshot,
    upsert_ciq_valuation_snapshot,
)
from db.schema import create_tables, get_connection
from ciq.workbook_parser import CIQTemplateContractError, parse_ciq_workbook
from src.stage_04_pipeline.statement_reconciliation_store import (
    persist_statement_source_manifest,
)


IGNORED_WORKBOOK_NAMES = {
    "IBM_Standard.xlsx",
}


@dataclass(slots=True)
class IngestFileResult:
    file: str
    status: str
    ticker: str | None = None
    run_id: int | None = None
    rows_parsed: int = 0
    error: str | None = None


@dataclass(slots=True)
class IngestReport:
    as_of_date: str
    folder: str
    total_files: int
    processed: int
    skipped: int
    failed: int
    results: list[IngestFileResult]



def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _list_candidate_workbooks(folder: Path) -> list[Path]:
    files = sorted(folder.glob(CIQ_WORKBOOK_GLOB)) if folder.exists() else []
    candidates: list[Path] = []
    for path in files:
        if path.name.startswith("~$"):
            continue
        if path.name in IGNORED_WORKBOOK_NAMES:
            continue
        candidates.append(path)
    return candidates


def ingest_ciq_folder(
    folder_path: str | Path | None = None,
    as_of_date: str | None = None,
    *,
    workbook_paths: Iterable[str | Path] | None = None,
    connection: sqlite3.Connection | None = None,
) -> IngestReport:
    """Ingest an explicit workbook set or every candidate in a drop folder."""
    folder = Path(folder_path or CIQ_DROP_FOLDER)
    run_as_of_date = as_of_date or datetime.now(timezone.utc).date().isoformat()

    if workbook_paths is None:
        files = _list_candidate_workbooks(folder)
    else:
        files = []
        seen: set[Path] = set()
        for raw_path in workbook_paths:
            path = Path(raw_path)
            if not path.exists():
                raise FileNotFoundError(f"CIQ workbook not found: {path}")
            resolved = path.resolve()
            if resolved in seen:
                continue
            if path.name.startswith("~$"):
                raise ValueError(f"CIQ workbook is an Excel lock file: {path}")
            if path.suffix.lower() != ".xlsx":
                raise ValueError(f"CIQ workbook must be .xlsx: {path}")
            files.append(path)
            seen.add(resolved)
    results: list[IngestFileResult] = []

    close_connection = connection is None
    conn = connection or get_connection()
    create_tables(conn)

    processed = 0
    skipped = 0
    failed = 0

    try:
        for workbook_path in files:
            run_id: int | None = None
            payload = None
            try:
                payload = parse_ciq_workbook(workbook_path)

                run_id, is_new = register_ciq_ingest_run(
                    conn,
                    {
                        "run_key": f"{payload.file_hash}:{payload.parser_version}",
                        "source_file": payload.source_file,
                        "file_hash": payload.file_hash,
                        "ticker": payload.ticker,
                        "parser_version": payload.parser_version,
                        "ingest_ts": _now_iso(),
                        "status": "started",
                        "error_message": None,
                        "template_fingerprint": payload.template_fingerprint,
                        "rows_parsed": payload.rows_parsed,
                        "as_of_date": payload.valuation_snapshot.get("as_of_date") or run_as_of_date,
                    },
                )

                if not is_new:
                    existing_status = conn.execute(
                        """
                        SELECT status
                        FROM ciq_ingest_runs
                        WHERE id = ?
                        """,
                        (run_id,),
                    ).fetchone()[0]
                    if existing_status != "completed":
                        conn.execute(
                            """
                            UPDATE ciq_ingest_runs
                            SET status = 'started',
                                error_message = NULL,
                                ingest_ts = ?,
                                rows_parsed = ?
                            WHERE id = ?
                              AND status IN ('started', 'failed')
                            """,
                            (_now_iso(), payload.rows_parsed, run_id),
                        )
                        conn.commit()
                        resumed = conn.execute(
                            """
                            SELECT status
                            FROM ciq_ingest_runs
                            WHERE id = ?
                            """,
                            (run_id,),
                        ).fetchone()
                        if resumed is None or resumed[0] != "started":
                            raise RuntimeError(
                                "existing CIQ ingest run cannot be resumed"
                            )
                    else:
                        persist_statement_source_manifest(
                            conn,
                            payload.coverage_manifest,
                            source_run_id=run_id,
                            evidence_cutoff=(
                                payload.valuation_snapshot.get("as_of_date")
                                or run_as_of_date
                            ),
                        )
                        skipped += 1
                        results.append(
                            IngestFileResult(
                                file=workbook_path.name,
                                status="skipped",
                                ticker=payload.ticker,
                                run_id=run_id,
                            )
                        )
                        continue

                insert_ciq_long_form(conn, run_id, payload.long_form_records)

                snapshot_row = dict(payload.valuation_snapshot)
                snapshot_row["as_of_date"] = snapshot_row.get("as_of_date") or run_as_of_date
                snapshot_row["run_id"] = run_id
                snapshot_row["source_file"] = payload.source_file
                snapshot_row["pulled_at"] = _now_iso()
                upsert_ciq_valuation_snapshot(conn, [snapshot_row])

                comps_rows = []
                for row in payload.comps_snapshot:
                    item = dict(row)
                    item["run_id"] = run_id
                    item["as_of_date"] = snapshot_row["as_of_date"]
                    comps_rows.append(item)
                upsert_ciq_comps_snapshot(conn, comps_rows)

                finalize_ciq_ingest_run(conn, run_id, "completed", None, payload.rows_parsed)
                persist_statement_source_manifest(
                    conn,
                    payload.coverage_manifest,
                    source_run_id=run_id,
                    evidence_cutoff=snapshot_row["as_of_date"],
                )

                processed += 1
                results.append(
                    IngestFileResult(
                        file=workbook_path.name,
                        status="processed",
                        ticker=payload.ticker,
                        run_id=run_id,
                        rows_parsed=payload.rows_parsed,
                    )
                )
            except CIQTemplateContractError as exc:
                if run_id is not None:
                    conn.rollback()
                    finalize_ciq_ingest_run(
                        conn,
                        run_id,
                        "failed",
                        str(exc),
                        int(getattr(payload, "rows_parsed", 0)),
                    )
                failed += 1
                results.append(
                    IngestFileResult(
                        file=workbook_path.name,
                        status="failed",
                        ticker=getattr(payload, "ticker", None),
                        run_id=run_id,
                        error=str(exc),
                    )
                )
            except Exception as exc:  # pragma: no cover - defensive path
                if run_id is not None:
                    conn.rollback()
                    finalize_ciq_ingest_run(
                        conn,
                        run_id,
                        "failed",
                        str(exc),
                        int(getattr(payload, "rows_parsed", 0)),
                    )
                failed += 1
                results.append(
                    IngestFileResult(
                        file=workbook_path.name,
                        status="failed",
                        ticker=getattr(payload, "ticker", None),
                        run_id=run_id,
                        error=str(exc),
                    )
                )
    finally:
        if close_connection:
            conn.close()

    return IngestReport(
        as_of_date=run_as_of_date,
        folder=str(folder),
        total_files=len(files),
        processed=processed,
        skipped=skipped,
        failed=failed,
        results=results,
    )


if __name__ == "__main__":
    report = ingest_ciq_folder()
    print(
        {
            "as_of_date": report.as_of_date,
            "folder": report.folder,
            "total_files": report.total_files,
            "processed": report.processed,
            "skipped": report.skipped,
            "failed": report.failed,
            "results": [asdict(r) for r in report.results],
        }
    )
