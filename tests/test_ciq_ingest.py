import sys
from pathlib import Path
import builtins
import importlib

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import sqlite3

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
    finally:
        conn.close()

    assert runs == 1
    assert snapshots == 1
    assert long_rows > 0


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
