"""Strict single-workbook CIQ ingestion for evidence-grade source runs."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

from ciq.workbook_parser import CIQTemplateContractError, parse_ciq_workbook
from db.loader import (
    ensure_ciq_source_facts_v2,
    finalize_ciq_ingest_run,
    insert_ciq_long_form,
    register_ciq_ingest_run,
    upsert_ciq_comps_snapshot,
    upsert_ciq_valuation_snapshot,
)
from db.schema import create_tables, get_connection


_SOURCE_FACT_COLUMNS = (
    "ticker", "sheet_name", "section_name", "row_index", "source_row_id",
    "row_label", "metric_key", "period_date", "calc_type", "column_label",
    "column_index", "a1_locator", "cell_locator", "value_raw", "value_num",
    "unit", "scale_factor", "source_file", "formula_text", "cached_value",
    "has_formula", "has_cached_value", "formula_status", "formula_error",
    "cached_error",
)
_SOURCE_FACT_DEFAULTS = {
    "section_name": None,
    "metric_key": None,
    "period_date": None,
    "calc_type": None,
    "column_label": None,
    "value_raw": None,
    "value_num": None,
    "unit": None,
    "scale_factor": 1.0,
    "formula_text": None,
    "cached_value": None,
    "formula_error": None,
    "cached_error": None,
}
_INTEGER_FACT_COLUMNS = {"row_index", "column_index", "has_formula", "has_cached_value"}
_REAL_FACT_COLUMNS = {"value_num", "scale_factor"}


def _normalized_fact(row: dict) -> dict:
    normalized = {}
    for column in _SOURCE_FACT_COLUMNS:
        value = row.get(column, _SOURCE_FACT_DEFAULTS.get(column))
        if value is not None and column in _INTEGER_FACT_COLUMNS:
            value = int(value)
        elif value is not None and column in _REAL_FACT_COLUMNS:
            value = float(value)
        elif isinstance(value, memoryview):
            value = bytes(value)
        if isinstance(value, bytes):
            value = {"bytes_hex": value.hex()}
        elif isinstance(value, float) and not math.isfinite(value):
            value = {"non_finite_float": repr(value)}
        normalized[column] = value
    return normalized


def _source_fact_digest(rows: list[dict]) -> str:
    normalized = [_normalized_fact(row) for row in rows]
    normalized.sort(key=lambda row: (row["sheet_name"], row["row_index"], row["column_index"]))
    encoded = json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ExactIngestResult:
    source_file: str
    source_hash: str
    ticker: str
    parser_version: str
    run_id: int
    status: str
    rows_parsed: int
    formula_error_count: int


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _formula_error_cells(records: list[dict]) -> list[str]:
    return sorted(
        {
            str(row.get("cell_locator"))
            for row in records
            if row.get("formula_error") and row.get("cell_locator")
        }
    )


def _run_key(*, source_file: str, file_hash: str, ticker: str, parser_version: str) -> str:
    normalized_source_file = Path(source_file).name.strip().casefold()
    return f"exact-v2:{normalized_source_file}:{file_hash}:{ticker.strip().upper()}:{parser_version.strip()}"


def _matching_run_id(
    conn,
    *,
    source_file: str,
    file_hash: str,
    ticker: str,
    parser_version: str,
) -> int | None:
    existing = conn.execute(
        """SELECT id FROM ciq_ingest_runs
            WHERE source_file = ? AND file_hash = ? AND ticker = ? AND parser_version = ?
            ORDER BY id DESC LIMIT 1""",
        [source_file, file_hash, ticker, parser_version],
    ).fetchone()
    return int(existing[0]) if existing else None


def _persisted_source_fact_digest(conn, run_id: int) -> str:
    column_sql = ", ".join(_SOURCE_FACT_COLUMNS)
    stored = conn.execute(
        f"""SELECT {column_sql}
              FROM ciq_source_facts_v2
             WHERE run_id = ?
             ORDER BY sheet_name, row_index, column_index""",
        [run_id],
    ).fetchall()
    rows = [dict(zip(_SOURCE_FACT_COLUMNS, row, strict=True)) for row in stored]
    return _source_fact_digest(rows)


def ingest_exact_workbook(
    workbook_path: str | Path,
    *,
    as_of_date: str | None = None,
    require_formula_integrity: bool = True,
) -> ExactIngestResult:
    """Ingest exactly one workbook and fail before registration on formula errors."""

    path = Path(workbook_path).expanduser().resolve()
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(path)
    payload = parse_ciq_workbook(path)
    formula_error_cells = _formula_error_cells(payload.long_form_records)
    if require_formula_integrity and formula_error_cells:
        schema_conn = get_connection()
        try:
            create_tables(schema_conn)
        finally:
            schema_conn.close()
        preview = ", ".join(formula_error_cells[:10])
        suffix = "" if len(formula_error_cells) <= 10 else f" (+{len(formula_error_cells) - 10} more)"
        raise CIQTemplateContractError(
            f"source formula integrity failed in {len(formula_error_cells)} cells: {preview}{suffix}"
        )

    run_as_of_date = as_of_date or datetime.now(timezone.utc).date().isoformat()
    conn = get_connection()
    create_tables(conn)
    try:
        run_id = _matching_run_id(
            conn,
            source_file=payload.source_file,
            file_hash=payload.file_hash,
            ticker=payload.ticker,
            parser_version=payload.parser_version,
        )
        is_new = run_id is None
        if is_new:
            run_id, is_new = register_ciq_ingest_run(
                conn,
                {
                    "run_key": _run_key(
                        source_file=payload.source_file,
                        file_hash=payload.file_hash,
                        ticker=payload.ticker,
                        parser_version=payload.parser_version,
                    ),
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
        assert run_id is not None
        if not is_new:
            existing = conn.execute(
                "SELECT status FROM ciq_ingest_runs WHERE id = ? LIMIT 1",
                [run_id],
            ).fetchone()
            existing_status = str(existing[0] or "").strip().lower() if existing else "missing"
            if existing_status != "completed":
                raise RuntimeError(
                    f"CIQ ingest run {run_id} is {existing_status}; "
                    "refusing to treat an incomplete run as an idempotent success"
                )
            ensure_ciq_source_facts_v2(conn, run_id, payload.long_form_records)
            expected_digest = _source_fact_digest(payload.long_form_records)
            persisted_digest = _persisted_source_fact_digest(conn, run_id)
            if persisted_digest != expected_digest:
                raise RuntimeError(
                    f"CIQ ingest run {run_id} source-fact content digest mismatch: "
                    f"expected {expected_digest}, persisted {persisted_digest}"
                )
            return ExactIngestResult(
                source_file=payload.source_file,
                source_hash=payload.file_hash,
                ticker=payload.ticker,
                parser_version=payload.parser_version,
                run_id=run_id,
                status="skipped_existing",
                rows_parsed=payload.rows_parsed,
                formula_error_count=len(formula_error_cells),
            )

        try:
            ensure_ciq_source_facts_v2(conn, run_id, payload.long_form_records)
            insert_ciq_long_form(conn, run_id, payload.long_form_records)
            snapshot = dict(payload.valuation_snapshot)
            snapshot["as_of_date"] = snapshot.get("as_of_date") or run_as_of_date
            snapshot["run_id"] = run_id
            snapshot["source_file"] = payload.source_file
            snapshot["pulled_at"] = _now_iso()
            upsert_ciq_valuation_snapshot(conn, [snapshot])

            comps = []
            for row in payload.comps_snapshot:
                item = dict(row)
                item["run_id"] = run_id
                item["as_of_date"] = snapshot["as_of_date"]
                comps.append(item)
            upsert_ciq_comps_snapshot(conn, comps)
            finalize_ciq_ingest_run(conn, run_id, "completed", None, payload.rows_parsed)
        except Exception as exc:
            finalize_ciq_ingest_run(
                conn,
                run_id,
                "failed",
                f"{type(exc).__name__}: {exc}",
                payload.rows_parsed,
            )
            raise
        return ExactIngestResult(
            source_file=payload.source_file,
            source_hash=payload.file_hash,
            ticker=payload.ticker,
            parser_version=payload.parser_version,
            run_id=run_id,
            status="processed",
            rows_parsed=payload.rows_parsed,
            formula_error_count=len(formula_error_cells),
        )
    finally:
        conn.close()


__all__ = ["ExactIngestResult", "ingest_exact_workbook"]
