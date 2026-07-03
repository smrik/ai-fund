from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta, timezone

from scripts.manual import weekly_preflight


def test_expected_schema_tables_uses_in_memory_schema():
    tables = weekly_preflight.expected_schema_tables()

    assert isinstance(tables, tuple)
    assert {"universe", "pm_decision_queue_items", "market_data_cache"}.issubset(tables)


def test_check_database_fails_when_db_missing(tmp_path):
    result = weekly_preflight.check_database(tmp_path / "missing.db", required_tables=("universe",))

    assert result.status == "FAIL"
    assert "missing database" in result.detail


def test_check_database_fails_when_schema_table_missing(tmp_path):
    db_path = tmp_path / "alpha_pod.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE universe (ticker TEXT PRIMARY KEY)")

    result = weekly_preflight.check_database(db_path, required_tables=("universe", "market_data_cache"))

    assert result.status == "FAIL"
    assert "market_data_cache" in result.detail


def test_check_database_passes_when_required_tables_present(tmp_path):
    db_path = tmp_path / "alpha_pod.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE universe (ticker TEXT PRIMARY KEY)")
        conn.execute("CREATE TABLE market_data_cache (ticker TEXT, fetched_at TEXT)")

    result = weekly_preflight.check_database(db_path, required_tables=("universe", "market_data_cache"))

    assert result.status == "PASS"


def test_check_ciq_workbook_fails_when_missing(tmp_path):
    result = weekly_preflight.check_ciq_workbook(tmp_path)

    assert result.status == "FAIL"
    assert "no CIQ workbook" in result.detail


def test_check_ciq_workbook_excludes_committed_template_names(tmp_path):
    (tmp_path / "ciq_cleandata.xlsx").write_bytes(b"stub")
    (tmp_path / "IBM_Standard.xlsx").write_bytes(b"stub")

    result = weekly_preflight.check_ciq_workbook(tmp_path)

    assert result.status == "FAIL"
    assert "no CIQ workbook" in result.detail


def test_check_ciq_workbook_warns_when_stale(tmp_path):
    workbook = tmp_path / "MSFT_Standard.xlsx"
    workbook.write_bytes(b"stub")
    now = datetime(2026, 7, 3, tzinfo=timezone.utc)
    stale_time = (now - timedelta(days=9)).timestamp()
    os.utime(workbook, (stale_time, stale_time))

    result = weekly_preflight.check_ciq_workbook(tmp_path, warn_days=7, now=now)

    assert result.status == "WARN"
    assert "age 9.0 days" in result.detail


def test_check_market_cache_warns_when_stale(tmp_path):
    db_path = tmp_path / "alpha_pod.db"
    now = datetime(2026, 7, 3, tzinfo=timezone.utc)
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE market_data_cache (ticker TEXT, data_type TEXT, data_json TEXT, fetched_at TEXT)")
        conn.execute(
            "INSERT INTO market_data_cache VALUES (?, ?, ?, ?)",
            ("MSFT", "market_data", "{}", (now - timedelta(days=2)).isoformat()),
        )

    result = weekly_preflight.check_market_cache(db_path, warn_days=1, now=now)

    assert result.status == "WARN"
    assert "age 2.0 days" in result.detail


def test_check_fred_api_key_is_warn_only_when_missing():
    result = weekly_preflight.check_fred_api_key({})

    assert result.status == "WARN"


def test_check_packages_pass_detail_comes_from_optional_names():
    result = weekly_preflight.check_packages(required={}, optional={"stdlib_os": "os"})

    assert result.status == "PASS"
    assert "optional present: stdlib_os" in result.detail


def test_exit_code_only_fails_on_fail_status():
    warn_only = [weekly_preflight.CheckResult("x", "WARN", "warn")]
    with_fail = [weekly_preflight.CheckResult("x", "FAIL", "fail")]

    assert weekly_preflight.exit_code(warn_only) == 0
    assert weekly_preflight.exit_code(with_fail) == 1
