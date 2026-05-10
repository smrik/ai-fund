"""Offline tests for operator diagnostics — healthy and degraded states."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from src.stage_04_pipeline.diagnostics import (
    DiagnosticsPayload,
    _check_database,
    _check_exports_writable,
    _check_universe,
    run_diagnostics,
)


# ---------------------------------------------------------------------------
# as_dict contract (no I/O)
# ---------------------------------------------------------------------------

def test_as_dict_shape():
    payload = DiagnosticsPayload(overall="ok", checks=[])
    d = payload.as_dict()
    assert d["overall"] == "ok"
    assert d["checks"] == []


def test_as_dict_includes_checks():
    from src.stage_04_pipeline.diagnostics import CheckResult
    payload = DiagnosticsPayload(
        overall="degraded",
        checks=[CheckResult("database", "degraded", "missing tables: pipeline_log")],
    )
    d = payload.as_dict()
    assert d["overall"] == "degraded"
    assert len(d["checks"]) == 1
    assert d["checks"][0] == {
        "name": "database",
        "status": "degraded",
        "message": "missing tables: pipeline_log",
    }


# ---------------------------------------------------------------------------
# Database check
# ---------------------------------------------------------------------------

def test_database_ok_when_tables_present():
    fake_conn = MagicMock()
    fake_conn.__enter__ = lambda s: fake_conn
    fake_conn.__exit__ = MagicMock(return_value=False)
    fake_conn.execute.return_value.fetchall.return_value = [
        ("pipeline_log",), ("market_data_cache",), ("universe",)
    ]
    with patch("src.stage_04_pipeline.diagnostics.get_connection", return_value=fake_conn):
        result = _check_database()
    assert result.status == "ok"


def test_database_degraded_when_tables_missing():
    fake_conn = MagicMock()
    fake_conn.__enter__ = lambda s: fake_conn
    fake_conn.__exit__ = MagicMock(return_value=False)
    fake_conn.execute.return_value.fetchall.return_value = []
    with patch("src.stage_04_pipeline.diagnostics.get_connection", return_value=fake_conn):
        result = _check_database()
    assert result.status == "degraded"
    assert "missing tables" in result.message


# ---------------------------------------------------------------------------
# Universe check
# ---------------------------------------------------------------------------

def test_universe_ok(monkeypatch):
    fake_path = MagicMock(spec=Path)
    fake_path.exists.return_value = True
    fake_path.read_text.return_value = "ticker,name\nAAPL,Apple\nMSFT,Microsoft\n"
    monkeypatch.setattr("src.stage_04_pipeline.diagnostics.UNIVERSE_PATH", fake_path)
    result = _check_universe()
    assert result.status == "ok"
    assert "2" in result.message


def test_universe_unavailable_when_missing(monkeypatch):
    fake_path = MagicMock(spec=Path)
    fake_path.exists.return_value = False
    monkeypatch.setattr("src.stage_04_pipeline.diagnostics.UNIVERSE_PATH", fake_path)
    result = _check_universe()
    assert result.status == "unavailable"


def test_universe_degraded_when_empty(monkeypatch):
    fake_path = MagicMock(spec=Path)
    fake_path.exists.return_value = True
    fake_path.read_text.return_value = "ticker,name\n"  # header only
    monkeypatch.setattr("src.stage_04_pipeline.diagnostics.UNIVERSE_PATH", fake_path)
    result = _check_universe()
    assert result.status == "degraded"


# ---------------------------------------------------------------------------
# Exports writable check
# ---------------------------------------------------------------------------

def test_exports_ok(monkeypatch):
    fake_dir = MagicMock(spec=Path)
    fake_dir.__truediv__ = lambda self, other: MagicMock(
        spec=Path,
        write_text=MagicMock(),
        unlink=MagicMock(),
        **{"glob.return_value": []},
    )
    monkeypatch.setattr("src.stage_04_pipeline.diagnostics.OUTPUT_DIR", fake_dir)
    result = _check_exports_writable()
    assert result.status == "ok"


def test_exports_unavailable_when_write_fails(monkeypatch):
    probe = MagicMock(spec=Path)
    probe.write_text.side_effect = PermissionError("read-only")
    exports_dir = MagicMock(spec=Path)
    exports_dir.__truediv__ = lambda self, other: probe if other == ".write_probe" else MagicMock()
    fake_output = MagicMock(spec=Path)
    fake_output.__truediv__ = lambda self, other: exports_dir
    monkeypatch.setattr("src.stage_04_pipeline.diagnostics.OUTPUT_DIR", fake_output)
    result = _check_exports_writable()
    assert result.status == "unavailable"


# ---------------------------------------------------------------------------
# Overall rollup
# ---------------------------------------------------------------------------

def test_overall_ok_when_all_checks_pass():
    from src.stage_04_pipeline.diagnostics import CheckResult
    with patch("src.stage_04_pipeline.diagnostics._check_database", return_value=CheckResult("database", "ok", "")), \
         patch("src.stage_04_pipeline.diagnostics._check_universe", return_value=CheckResult("universe", "ok", "")), \
         patch("src.stage_04_pipeline.diagnostics._check_exports_writable", return_value=CheckResult("exports_dir", "ok", "")), \
         patch("src.stage_04_pipeline.diagnostics._check_dossiers", return_value=CheckResult("dossiers", "ok", "")), \
         patch("src.stage_04_pipeline.diagnostics._check_latest_snapshot", return_value=CheckResult("latest_snapshot", "ok", "")), \
         patch("src.stage_04_pipeline.diagnostics._check_reports_dir", return_value=CheckResult("reports_dir", "ok", "")):
        payload = run_diagnostics()
    assert payload.overall == "ok"


def test_overall_degraded_when_one_check_degraded():
    from src.stage_04_pipeline.diagnostics import CheckResult
    with patch("src.stage_04_pipeline.diagnostics._check_database", return_value=CheckResult("database", "degraded", "missing tables")), \
         patch("src.stage_04_pipeline.diagnostics._check_universe", return_value=CheckResult("universe", "ok", "")), \
         patch("src.stage_04_pipeline.diagnostics._check_exports_writable", return_value=CheckResult("exports_dir", "ok", "")), \
         patch("src.stage_04_pipeline.diagnostics._check_dossiers", return_value=CheckResult("dossiers", "ok", "")), \
         patch("src.stage_04_pipeline.diagnostics._check_latest_snapshot", return_value=CheckResult("latest_snapshot", "ok", "")), \
         patch("src.stage_04_pipeline.diagnostics._check_reports_dir", return_value=CheckResult("reports_dir", "ok", "")):
        payload = run_diagnostics()
    assert payload.overall == "degraded"


def test_overall_unavailable_when_one_check_unavailable():
    from src.stage_04_pipeline.diagnostics import CheckResult
    with patch("src.stage_04_pipeline.diagnostics._check_database", return_value=CheckResult("database", "unavailable", "connection refused")), \
         patch("src.stage_04_pipeline.diagnostics._check_universe", return_value=CheckResult("universe", "ok", "")), \
         patch("src.stage_04_pipeline.diagnostics._check_exports_writable", return_value=CheckResult("exports_dir", "ok", "")), \
         patch("src.stage_04_pipeline.diagnostics._check_dossiers", return_value=CheckResult("dossiers", "ok", "")), \
         patch("src.stage_04_pipeline.diagnostics._check_latest_snapshot", return_value=CheckResult("latest_snapshot", "ok", "")), \
         patch("src.stage_04_pipeline.diagnostics._check_reports_dir", return_value=CheckResult("reports_dir", "ok", "")):
        payload = run_diagnostics()
    assert payload.overall == "unavailable"
