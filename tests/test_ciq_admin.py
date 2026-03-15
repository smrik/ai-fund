from __future__ import annotations

from pathlib import Path

import src.stage_04_pipeline.ciq_admin as ciq_admin


def test_detect_active_env_falls_back_to_python_path(monkeypatch):
    monkeypatch.delenv("CONDA_DEFAULT_ENV", raising=False)

    active_env = ciq_admin._detect_active_env(r"C:\Users\patri\miniconda3\envs\ai-fund\python.exe")

    assert active_env == "ai-fund"


def test_detect_active_env_prefers_python_path_when_env_var_is_stale(monkeypatch):
    monkeypatch.setenv("CONDA_DEFAULT_ENV", "base")

    active_env = ciq_admin._detect_active_env(r"C:\Users\patri\miniconda3\envs\ai-fund\python.exe")

    assert active_env == "ai-fund"


def test_get_ciq_runtime_status_reports_environment_and_candidates(tmp_path, monkeypatch):
    (tmp_path / "LYFT_Standard.xlsx").write_text("stub", encoding="utf-8")
    (tmp_path / "IBM_Standard.xlsx").write_text("stub", encoding="utf-8")

    monkeypatch.setattr(ciq_admin, "CIQ_DROP_FOLDER", tmp_path)
    class _ExplodingConn:
        def __enter__(self):
            raise RuntimeError("db unavailable")

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(ciq_admin, "get_connection", lambda: _ExplodingConn())

    status = ciq_admin.get_ciq_runtime_status(tmp_path)

    assert status["folder"] == str(tmp_path)
    assert "LYFT_Standard.xlsx" in status["candidate_workbooks"]
    assert "IBM_Standard.xlsx" not in status["candidate_workbooks"]
    assert status["recommended_env"] == "ai-fund"
    assert "openpyxl" in status["module_status"]


def test_run_ciq_operation_ingest_saved_uses_ingest_only(tmp_path, monkeypatch):
    calls: list[tuple[str, str]] = []

    monkeypatch.setattr(ciq_admin, "ingest_ciq_folder", lambda folder_path: {"folder": str(folder_path), "processed": 1})
    monkeypatch.setattr(ciq_admin, "_list_candidate_workbooks", lambda folder: [Path(folder) / "LYFT_Standard.xlsx"])

    result = ciq_admin.run_ciq_operation("ingest_saved", folder_path=tmp_path)

    assert result["action"] == "ingest_saved"
    assert result["report"]["processed"] == 1
    assert result["refresh_results"] == []


def test_run_ciq_operation_refresh_and_ingest_refreshes_each_candidate(tmp_path, monkeypatch):
    candidates = [tmp_path / "LYFT_Standard.xlsx", tmp_path / "META_Standard.xlsx"]
    refreshed: list[Path] = []

    monkeypatch.setattr(ciq_admin, "_list_candidate_workbooks", lambda folder: candidates)
    monkeypatch.setattr(ciq_admin, "refresh_workbook", lambda path: refreshed.append(path) or True)
    monkeypatch.setattr(ciq_admin, "ingest_ciq_folder", lambda folder_path: {"folder": str(folder_path), "processed": 2})

    result = ciq_admin.run_ciq_operation("refresh_and_ingest", folder_path=tmp_path)

    assert refreshed == candidates
    assert len(result["refresh_results"]) == 2
    assert all(item["ok"] is True for item in result["refresh_results"])
    assert result["report"]["processed"] == 2


def test_run_ciq_operation_dry_run_parse_validates_without_ingest(tmp_path, monkeypatch):
    workbook = tmp_path / "IBM_Research.xlsx"
    workbook.write_text("stub", encoding="utf-8")

    monkeypatch.setattr(ciq_admin, "_list_candidate_workbooks", lambda folder: [workbook])
    monkeypatch.setattr(
        ciq_admin,
        "parse_ciq_workbook",
        lambda path: type("Payload", (), {"ticker": "IBM", "as_of_date": "2026-03-15"})(),
    )
    ingest_called = False

    def _ingest(_folder):
        nonlocal ingest_called
        ingest_called = True
        return {}

    monkeypatch.setattr(ciq_admin, "ingest_ciq_folder", _ingest)

    result = ciq_admin.run_ciq_operation("dry_run_parse", folder_path=tmp_path)

    assert result["action"] == "dry_run_parse"
    assert result["report"]["processed"] == 1
    assert result["report"]["failed"] == 0
    assert ingest_called is False
