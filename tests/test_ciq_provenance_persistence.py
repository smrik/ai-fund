from __future__ import annotations

import sqlite3
from pathlib import Path

from openpyxl import load_workbook
import pytest

from ciq.ingest import ingest_ciq_folder
from ciq.workbook_parser import parse_ciq_workbook
from db import schema as schema_module
from db.loader import (
    ensure_ciq_source_facts_v2,
    insert_ciq_long_form,
    insert_ciq_source_facts_v2,
    register_ciq_ingest_run,
)
from db.queries import get_ciq_metric_history, get_ciq_source_facts_v2
from db.schema import create_tables
from tests.ciq_test_utils import create_ibm_style_workbook


LEGACY_UNIQUE_GRAIN = (
    "run_id",
    "sheet_name",
    "row_label",
    "period_date",
    "calc_type",
    "column_index",
)
SOURCE_CELL_UNIQUE_GRAIN = ("run_id", "sheet_name", "row_index", "column_index")
PROVENANCE_COLUMNS = {
    "row_index",
    "source_row_id",
    "a1_locator",
    "cell_locator",
    "formula_text",
    "cached_value",
    "has_formula",
    "has_cached_value",
    "formula_status",
    "formula_error",
    "cached_error",
}


def _register_run(conn: sqlite3.Connection, run_key: str = "fixture:v4") -> int:
    run_id, is_new = register_ciq_ingest_run(
        conn,
        {
            "run_key": run_key,
            "source_file": "MSFT_Standard.xlsx",
            "file_hash": "fixture-hash",
            "ticker": "MSFT",
            "parser_version": "ibm_standard_v4",
            "ingest_ts": "2026-07-12T00:00:00Z",
            "status": "started",
            "error_message": None,
            "template_fingerprint": "{}",
            "rows_parsed": 0,
            "as_of_date": "2026-06-30",
        },
    )
    assert is_new is True
    return run_id


def _unique_index_grains(
    conn: sqlite3.Connection,
    table_name: str,
) -> set[tuple[str, ...]]:
    grains: set[tuple[str, ...]] = set()
    for index_row in conn.execute(f"PRAGMA index_list({table_name})").fetchall():
        if not bool(index_row["unique"]):
            continue
        index_name = str(index_row["name"]).replace("'", "''")
        columns = conn.execute(f"PRAGMA index_info('{index_name}')").fetchall()
        grains.add(tuple(str(column["name"]) for column in columns))
    return grains


def _legacy_ciq_long_form_table(conn: sqlite3.Connection) -> None:
    conn.execute("DROP TABLE ciq_long_form")
    conn.execute(
        """
        CREATE TABLE ciq_long_form (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id          INTEGER NOT NULL,
            ticker          TEXT NOT NULL,
            sheet_name      TEXT NOT NULL,
            section_name    TEXT,
            row_label       TEXT NOT NULL,
            metric_key      TEXT,
            period_date     TEXT,
            calc_type       TEXT,
            column_label    TEXT,
            column_index    INTEGER,
            value_raw       TEXT,
            value_num       REAL,
            unit            TEXT,
            scale_factor    REAL DEFAULT 1.0,
            source_file     TEXT NOT NULL,
            UNIQUE(run_id, sheet_name, row_label, period_date, calc_type, column_index),
            FOREIGN KEY (run_id) REFERENCES ciq_ingest_runs(id)
        )
        """
    )
    conn.commit()



def _create_duplicate_logical_row_workbook(path: Path) -> Path:
    workbook_path = create_ibm_style_workbook(path)
    workbook = load_workbook(workbook_path)
    financials = workbook["Financial Statements"]
    financials["A206"] = "Total Revenues"
    financials["D206"], financials["E206"], financials["F206"] = 900, 1000, 1100
    workbook.save(workbook_path)
    workbook.close()
    return workbook_path


def test_create_tables_adds_v2_facts_without_mutating_legacy_long_form(tmp_path: Path) -> None:
    conn = sqlite3.connect(tmp_path / "legacy.sqlite")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        create_tables(conn)
        run_id = _register_run(conn, "fixture:legacy")
        _legacy_ciq_long_form_table(conn)
        conn.execute("DROP TABLE ciq_source_facts_v2")
        conn.execute(
            """
            INSERT INTO ciq_long_form (
                run_id, ticker, sheet_name, section_name, row_label,
                metric_key, period_date, calc_type, column_label,
                column_index, value_raw, value_num, unit, scale_factor,
                source_file
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                "MSFT",
                "Financial Statements",
                "Income Statement",
                "Total Revenues",
                "revenue",
                "2026-06-30",
                "Annual",
                "2026-06-30",
                6,
                "1200",
                1200.0,
                "currency_mm",
                1.0,
                "MSFT_Standard.xlsx",
            ),
        )
        conn.commit()

        create_tables(conn)

        columns = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(ciq_source_facts_v2)").fetchall()
        }
        assert PROVENANCE_COLUMNS <= columns
        assert SOURCE_CELL_UNIQUE_GRAIN in _unique_index_grains(
            conn,
            "ciq_source_facts_v2",
        )
        assert LEGACY_UNIQUE_GRAIN in _unique_index_grains(conn, "ciq_long_form")

        migrated = conn.execute("SELECT * FROM ciq_long_form").fetchone()
        assert migrated is not None
        assert migrated["value_num"] == 1200.0
        assert conn.execute("SELECT COUNT(*) FROM ciq_source_facts_v2").fetchone()[0] == 0

        # The additive columns must leave the v1 query surface unchanged.
        assert get_ciq_metric_history(conn, "MSFT", "revenue") == [
            {
                "period_date": "2026-06-30",
                "value_num": 1200.0,
                "unit": "currency_mm",
            }
        ]
    finally:
        conn.close()


def test_loader_dual_write_preserves_v4_facts_and_legacy_projection(tmp_path: Path) -> None:
    conn = sqlite3.connect(tmp_path / "loader.sqlite")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        create_tables(conn)
        run_id = _register_run(conn)
        logical_fact = {
            "ticker": "MSFT",
            "sheet_name": "Financial Statements",
            "section_name": "Income Statement",
            "row_label": "Total Revenues",
            "metric_key": "revenue",
            "period_date": "2026-06-30",
            "calc_type": "Annual",
            "column_label": "2026-06-30",
            "column_index": 6,
            "unit": "currency_mm",
            "scale_factor": 1.0,
            "source_file": "MSFT_Standard.xlsx",
            "formula_error": None,
            "cached_error": None,
        }
        rows = [
            {
                **logical_fact,
                "row_index": 12,
                "source_row_id": "Financial Statements!12",
                "a1_locator": "F12",
                "cell_locator": "Financial Statements!F12",
                "value_raw": "1200",
                "value_num": 1200.0,
                "formula_text": "=SUM(F8:F11)",
                "cached_value": 1200.0,
                "has_formula": True,
                "has_cached_value": True,
                "formula_status": "formula_cached",
            },
            {
                **logical_fact,
                "row_index": 206,
                "source_row_id": "Financial Statements!206",
                "a1_locator": "F206",
                "cell_locator": "Financial Statements!F206",
                "value_raw": "1100",
                "value_num": 1100.0,
                "formula_text": None,
                "cached_value": 1100,
                "has_formula": False,
                "has_cached_value": True,
                "formula_status": "literal",
            },
        ]

        insert_ciq_source_facts_v2(conn, run_id, rows)
        insert_ciq_source_facts_v2(conn, run_id, rows)
        insert_ciq_long_form(conn, run_id, rows)

        stored = get_ciq_source_facts_v2(conn, run_id)
        assert len(stored) == 2
        assert [row["cell_locator"] for row in stored] == [
            "Financial Statements!F12",
            "Financial Statements!F206",
        ]
        assert stored[0]["formula_text"] == "=SUM(F8:F11)"
        assert stored[0]["cached_value"] == 1200.0
        assert stored[0]["has_formula"] == 1
        assert stored[0]["formula_status"] == "formula_cached"
        assert stored[1]["source_row_id"] == "Financial Statements!206"
        assert stored[1]["a1_locator"] == "F206"
        assert stored[1]["cached_value"] == 1100
        assert conn.execute(
            "SELECT COUNT(*) FROM ciq_long_form WHERE run_id = ?",
            [run_id],
        ).fetchone()[0] == 1

        assert ensure_ciq_source_facts_v2(conn, run_id, rows) is False
        conn.execute(
            """
            UPDATE ciq_source_facts_v2
            SET cell_locator = 'Financial Statements!Z999'
            WHERE run_id = ? AND row_index = 206 AND column_index = 6
            """,
            [run_id],
        )
        conn.commit()
        with pytest.raises(RuntimeError, match="identity"):
            ensure_ciq_source_facts_v2(conn, run_id, rows)
    finally:
        conn.close()


def test_ingest_stores_every_parsed_source_cell(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "ingest.sqlite"
    monkeypatch.setattr(schema_module, "DB_PATH", db_path)
    monkeypatch.setattr(schema_module, "DATA_DIR", tmp_path)

    workbook_path = _create_duplicate_logical_row_workbook(tmp_path / "MSFT_Standard.xlsx")

    parsed = parse_ciq_workbook(workbook_path)
    report = ingest_ciq_folder(tmp_path)

    assert report.processed == 1
    assert report.failed == 0
    assert report.results[0].rows_parsed == parsed.rows_parsed

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        stored_count = conn.execute(
            "SELECT COUNT(*) FROM ciq_source_facts_v2 WHERE run_id = ?",
            [report.results[0].run_id],
        ).fetchone()[0]
        assert stored_count == parsed.rows_parsed
        legacy_count = conn.execute(
            "SELECT COUNT(*) FROM ciq_long_form WHERE run_id = ?",
            [report.results[0].run_id],
        ).fetchone()[0]
        assert legacy_count < parsed.rows_parsed

        duplicate_logical_rows = conn.execute(
            """
            SELECT row_index, a1_locator, cell_locator
            FROM ciq_source_facts_v2
            WHERE run_id = ?
              AND sheet_name = 'Financial Statements'
              AND row_label = 'Total Revenues'
              AND period_date = '2025-12-31'
            ORDER BY row_index
            """,
            [report.results[0].run_id],
        ).fetchall()
        assert [row["row_index"] for row in duplicate_logical_rows] == [12, 206]
        assert [row["a1_locator"] for row in duplicate_logical_rows] == ["F12", "F206"]
        assert len({row["cell_locator"] for row in duplicate_logical_rows}) == 2
    finally:
        conn.close()



def test_existing_run_backfills_empty_v2_without_touching_v1(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "empty-backfill.sqlite"
    monkeypatch.setattr(schema_module, "DB_PATH", db_path)
    monkeypatch.setattr(schema_module, "DATA_DIR", tmp_path)
    _create_duplicate_logical_row_workbook(tmp_path / "MSFT_Standard.xlsx")

    first = ingest_ciq_folder(tmp_path)
    run_id = first.results[0].run_id
    expected_count = first.results[0].rows_parsed
    assert run_id is not None

    conn = sqlite3.connect(db_path)
    try:
        legacy_count = conn.execute(
            "SELECT COUNT(*) FROM ciq_long_form WHERE run_id = ?",
            [run_id],
        ).fetchone()[0]
        conn.execute("DELETE FROM ciq_source_facts_v2 WHERE run_id = ?", [run_id])
        conn.commit()
    finally:
        conn.close()

    second = ingest_ciq_folder(tmp_path)

    assert second.processed == 0
    assert second.skipped == 1
    assert second.failed == 0
    assert second.results[0].run_id == run_id

    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM ciq_source_facts_v2 WHERE run_id = ?",
            [run_id],
        ).fetchone()[0] == expected_count
        assert conn.execute(
            "SELECT COUNT(*) FROM ciq_long_form WHERE run_id = ?",
            [run_id],
        ).fetchone()[0] == legacy_count
        assert conn.execute("SELECT COUNT(*) FROM ciq_ingest_runs").fetchone()[0] == 1
    finally:
        conn.close()


def test_existing_run_rejects_partial_v2_without_silent_repair(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "partial-backfill.sqlite"
    monkeypatch.setattr(schema_module, "DB_PATH", db_path)
    monkeypatch.setattr(schema_module, "DATA_DIR", tmp_path)
    _create_duplicate_logical_row_workbook(tmp_path / "MSFT_Standard.xlsx")

    first = ingest_ciq_folder(tmp_path)
    run_id = first.results[0].run_id
    expected_count = first.results[0].rows_parsed
    assert run_id is not None

    conn = sqlite3.connect(db_path)
    try:
        legacy_count = conn.execute(
            "SELECT COUNT(*) FROM ciq_long_form WHERE run_id = ?",
            [run_id],
        ).fetchone()[0]
        conn.execute(
            """
            DELETE FROM ciq_source_facts_v2
            WHERE rowid = (
                SELECT rowid
                FROM ciq_source_facts_v2
                WHERE run_id = ?
                LIMIT 1
            )
            """,
            [run_id],
        )
        conn.commit()
    finally:
        conn.close()

    second = ingest_ciq_folder(tmp_path)

    assert second.processed == 0
    assert second.skipped == 0
    assert second.failed == 1
    assert "partial" in str(second.results[0].error).lower()

    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM ciq_source_facts_v2 WHERE run_id = ?",
            [run_id],
        ).fetchone()[0] == expected_count - 1
        assert conn.execute(
            "SELECT COUNT(*) FROM ciq_long_form WHERE run_id = ?",
            [run_id],
        ).fetchone()[0] == legacy_count
        assert conn.execute("SELECT COUNT(*) FROM ciq_ingest_runs").fetchone()[0] == 1
    finally:
        conn.close()
