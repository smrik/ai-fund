from __future__ import annotations

import shutil
import sqlite3

import pytest
from openpyxl import load_workbook

from ciq import exact_ingest as exact_ingest_module
from ciq.exact_ingest import ingest_exact_workbook
from ciq.workbook_parser import CIQTemplateContractError
from db import schema as schema_module
from tests.ciq_test_utils import create_ibm_style_workbook


def test_exact_ingest_rejects_formula_errors_before_run_registration(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "alpha_pod.db"
    monkeypatch.setattr(schema_module, "DB_PATH", db_path)
    monkeypatch.setattr(schema_module, "DATA_DIR", tmp_path)
    path = create_ibm_style_workbook(tmp_path / "derived-repair.xlsx")
    workbook = load_workbook(path)
    workbook["Financial Statements"]["D12"] = "=SUM(1,#REF!)"
    workbook.save(path)
    workbook.close()

    with pytest.raises(CIQTemplateContractError, match="source formula integrity failed"):
        ingest_exact_workbook(path)

    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM ciq_ingest_runs").fetchone()[0] == 0


def test_exact_ingest_accepts_a_nonstandard_derived_filename(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "alpha_pod.db"
    monkeypatch.setattr(schema_module, "DB_PATH", db_path)
    monkeypatch.setattr(schema_module, "DATA_DIR", tmp_path)
    path = create_ibm_style_workbook(tmp_path / "derived-repair.xlsx")

    result = ingest_exact_workbook(path)
    repeated = ingest_exact_workbook(path)

    assert result.status == "processed"
    assert result.ticker == "TEST"
    assert result.formula_error_count == 0
    assert repeated.status == "skipped_existing"
    assert repeated.run_id == result.run_id


def test_exact_ingest_marks_post_registration_failure_and_rejects_retry(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "alpha_pod.db"
    monkeypatch.setattr(schema_module, "DB_PATH", db_path)
    monkeypatch.setattr(schema_module, "DATA_DIR", tmp_path)
    path = create_ibm_style_workbook(tmp_path / "derived-repair.xlsx")

    def fail_after_registration(*args, **kwargs) -> None:
        raise RuntimeError("simulated downstream write failure")

    monkeypatch.setattr(exact_ingest_module, "insert_ciq_long_form", fail_after_registration)

    with pytest.raises(RuntimeError, match="simulated downstream write failure"):
        ingest_exact_workbook(path)

    with sqlite3.connect(db_path) as conn:
        run_id, status, error_message = conn.execute(
            "SELECT id, status, error_message FROM ciq_ingest_runs"
        ).fetchone()
    assert status == "failed"
    assert error_message == "RuntimeError: simulated downstream write failure"

    with pytest.raises(RuntimeError, match=rf"CIQ ingest run {run_id} is failed"):
        ingest_exact_workbook(path)


def test_exact_ingest_distinguishes_identical_workbooks_with_different_names(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "alpha_pod.db"
    monkeypatch.setattr(schema_module, "DB_PATH", db_path)
    monkeypatch.setattr(schema_module, "DATA_DIR", tmp_path)
    original = create_ibm_style_workbook(tmp_path / "first-name.xlsx")
    renamed = tmp_path / "second-name.xlsx"
    shutil.copyfile(original, renamed)

    first = ingest_exact_workbook(original)
    second = ingest_exact_workbook(renamed)

    assert first.source_hash == second.source_hash
    assert first.run_id != second.run_id
    assert first.status == second.status == "processed"
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT source_file, status FROM ciq_ingest_runs ORDER BY id"
        ).fetchall()
    assert rows == [("first-name.xlsx", "completed"), ("second-name.xlsx", "completed")]


def test_exact_ingest_rejects_completed_run_with_mutated_source_fact_content(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "alpha_pod.db"
    monkeypatch.setattr(schema_module, "DB_PATH", db_path)
    monkeypatch.setattr(schema_module, "DATA_DIR", tmp_path)
    path = create_ibm_style_workbook(tmp_path / "derived-repair.xlsx")
    result = ingest_exact_workbook(path)

    with sqlite3.connect(db_path) as conn:
        identity = conn.execute(
            """SELECT sheet_name, row_index, column_index
                 FROM ciq_source_facts_v2
                WHERE run_id = ?
                ORDER BY sheet_name, row_index, column_index
                LIMIT 1""",
            [result.run_id],
        ).fetchone()
        conn.execute(
            """UPDATE ciq_source_facts_v2 SET value_raw = 'tampered'
                WHERE run_id = ? AND sheet_name = ? AND row_index = ? AND column_index = ?""",
            [result.run_id, *identity],
        )
        conn.commit()

    with pytest.raises(RuntimeError, match="source-fact content digest mismatch"):
        ingest_exact_workbook(path)


def test_exact_ingest_reuses_completed_legacy_key_when_full_identity_matches(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "alpha_pod.db"
    monkeypatch.setattr(schema_module, "DB_PATH", db_path)
    monkeypatch.setattr(schema_module, "DATA_DIR", tmp_path)
    path = create_ibm_style_workbook(tmp_path / "derived-repair.xlsx")
    result = ingest_exact_workbook(path)

    with sqlite3.connect(db_path) as conn:
        parser_version = conn.execute(
            "SELECT parser_version FROM ciq_ingest_runs WHERE id = ?", [result.run_id]
        ).fetchone()[0]
        conn.execute(
            "UPDATE ciq_ingest_runs SET run_key = ? WHERE id = ?",
            [f"{result.source_hash}:{parser_version}", result.run_id],
        )
        conn.commit()

    repeated = ingest_exact_workbook(path)
    assert repeated.status == "skipped_existing"
    assert repeated.run_id == result.run_id
