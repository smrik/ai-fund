import sys
from pathlib import Path
import builtins
import importlib

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import sqlite3

import ciq.ingest as ingest_module
from ciq.ingest import ingest_ciq_folder
from db import schema as schema_module
from ciq_test_utils import create_ibm_style_workbook


def test_ingest_ciq_folder_is_idempotent(tmp_path, monkeypatch):
    db_path = tmp_path / "alpha_pod.db"

    monkeypatch.setattr(schema_module, "DB_PATH", db_path)
    monkeypatch.setattr(schema_module, "DATA_DIR", tmp_path)

    create_ibm_style_workbook(tmp_path / "TEST_Standard.xlsx")

    report1 = ingest_ciq_folder(tmp_path)
    assert report1.total_files == 1
    assert report1.processed == 1
    assert report1.skipped == 0
    assert report1.failed == 0

    report2 = ingest_ciq_folder(tmp_path)
    assert report2.total_files == 1
    assert report2.processed == 0
    assert report2.skipped == 1
    assert report2.failed == 0

    conn = sqlite3.connect(str(db_path))
    try:
        runs = conn.execute("SELECT COUNT(*) FROM ciq_ingest_runs").fetchone()[0]
        snapshots = conn.execute("SELECT COUNT(*) FROM ciq_valuation_snapshot").fetchone()[0]
        long_rows = conn.execute("SELECT COUNT(*) FROM ciq_long_form").fetchone()[0]
        manifests = conn.execute(
            """
            SELECT COUNT(*), MIN(source_run_id), MIN(status)
            FROM statement_source_manifests
            WHERE source = 'ciq_workbook_v1'
            """
        ).fetchone()
    finally:
        conn.close()

    assert runs == 1
    assert snapshots == 1
    assert long_rows > 0
    assert manifests == (1, 1, "partial")


def test_ingest_ciq_folder_skips_excel_lock_files(tmp_path, monkeypatch):
    db_path = tmp_path / "alpha_pod.db"

    monkeypatch.setattr(schema_module, "DB_PATH", db_path)
    monkeypatch.setattr(schema_module, "DATA_DIR", tmp_path)

    create_ibm_style_workbook(tmp_path / "TEST_Standard.xlsx")
    # Simulate Excel lock file in drop folder.
    (tmp_path / "~$TEST_Standard.xlsx").write_text("lock", encoding="utf-8")

    report = ingest_ciq_folder(tmp_path)

    assert report.total_files == 1
    assert report.processed == 1
    assert report.failed == 0
    assert all(not r.file.startswith("~$") for r in report.results)


def test_ingest_ciq_folder_skips_reference_template_workbooks(tmp_path, monkeypatch):
    db_path = tmp_path / "alpha_pod.db"

    monkeypatch.setattr(schema_module, "DB_PATH", db_path)
    monkeypatch.setattr(schema_module, "DATA_DIR", tmp_path)

    create_ibm_style_workbook(tmp_path / "LYFT_Standard.xlsx")
    create_ibm_style_workbook(tmp_path / "IBM_Standard.xlsx")

    report = ingest_ciq_folder(tmp_path)

    assert report.total_files == 1
    assert report.processed == 1
    assert report.failed == 0
    assert [r.file for r in report.results] == ["LYFT_Standard.xlsx"]


def test_explicit_ciq_workbook_ingest_does_not_scan_sibling_files(tmp_path):
    selected = create_ibm_style_workbook(
        tmp_path / "SELECTED_Standard.xlsx"
    )
    create_ibm_style_workbook(
        tmp_path / "UNREQUESTED_Standard.xlsx",
        break_anchor=True,
    )
    conn = sqlite3.connect(":memory:")

    report = ingest_ciq_folder(
        tmp_path,
        workbook_paths=[selected],
        connection=conn,
    )

    assert report.total_files == 1
    assert report.processed == 1
    assert report.failed == 0
    assert [result.file for result in report.results] == [
        "SELECTED_Standard.xlsx"
    ]
    assert conn.execute(
        "SELECT COUNT(*) FROM ciq_ingest_runs"
    ).fetchone()[0] == 1
    conn.execute("SELECT 1").fetchone()


def test_failed_ciq_ingest_is_recorded_and_same_payload_can_resume(
    tmp_path,
    monkeypatch,
):
    db_path = tmp_path / "alpha_pod.db"
    monkeypatch.setattr(schema_module, "DB_PATH", db_path)
    monkeypatch.setattr(schema_module, "DATA_DIR", tmp_path)
    create_ibm_style_workbook(tmp_path / "TEST_Standard.xlsx")

    real_insert = ingest_module.insert_ciq_long_form

    def fail_statement_insert(*args, **kwargs):
        raise RuntimeError("statement ledger unavailable")

    monkeypatch.setattr(
        ingest_module,
        "insert_ciq_long_form",
        fail_statement_insert,
    )
    failed = ingest_ciq_folder(tmp_path)

    assert failed.failed == 1
    with sqlite3.connect(db_path) as conn:
        first_run = conn.execute(
            """
            SELECT id, status, error_message
            FROM ciq_ingest_runs
            """
        ).fetchone()
    assert first_run[1:] == (
        "failed",
        "statement ledger unavailable",
    )
    # Older builds stranded this exact run key at "started". Reproduce that
    # upgrade state and prove the deterministic payload can still resume.
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            UPDATE ciq_ingest_runs
            SET status = 'started', error_message = NULL
            WHERE id = ?
            """,
            (first_run[0],),
        )
        conn.commit()

    monkeypatch.setattr(
        ingest_module,
        "insert_ciq_long_form",
        real_insert,
    )
    resumed = ingest_ciq_folder(tmp_path)

    assert resumed.processed == 1
    assert resumed.failed == 0
    with sqlite3.connect(db_path) as conn:
        runs = conn.execute(
            "SELECT COUNT(*), MIN(status) FROM ciq_ingest_runs"
        ).fetchone()
        fact_count = conn.execute(
            "SELECT COUNT(*) FROM ciq_long_form"
        ).fetchone()[0]
        distinct_fact_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM (
                SELECT DISTINCT
                    run_id, sheet_name, row_label, period_date,
                    calc_type, column_index
                FROM ciq_long_form
            )
            """
        ).fetchone()[0]
    assert runs == (1, "completed")
    assert fact_count > 0
    assert fact_count == distinct_fact_count


def test_ciq_refresh_module_does_not_import_xlwings_at_module_import_time(monkeypatch):
    sys.modules.pop("ciq.ciq_refresh", None)

    real_import = builtins.__import__

    def _guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "xlwings":
            raise AssertionError("xlwings imported at module import time")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _guarded_import)
    module = importlib.import_module("ciq.ciq_refresh")
    assert hasattr(module, "refresh_workbook")


def test_ciq_package_init_is_lazy():
    sys.modules.pop("ciq", None)
    sys.modules.pop("ciq.ingest", None)

    import ciq  # noqa: F401

    assert "ciq.ingest" not in sys.modules
