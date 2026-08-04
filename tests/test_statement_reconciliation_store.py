from __future__ import annotations

import hashlib
import json
import sqlite3

import pytest

from db.schema import create_tables
from src.stage_04_pipeline.statement_reconciliation_store import (
    load_statement_source_manifests,
    persist_statement_reconciliation_run,
    persist_statement_source_manifest,
)


def _hash(value) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _manifest() -> dict:
    payload = {
        "contract_version": "statement_coverage_v1",
        "ticker": "TEST",
        "source": "ciq_workbook_v1",
        "source_run_id": None,
        "status": "completed",
        "evidence_cutoff": "2025-12-31",
        "as_of_date": "2025-12-31",
        "coverage": {"entries": {}},
        "errors": [],
    }
    payload["manifest_id"] = f"sha256:{_hash(payload)}"
    return payload


def _connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_tables(conn)
    return conn


def test_statement_manifest_persistence_is_idempotent_and_integrity_checked():
    conn = _connection()
    manifest = _manifest()

    first = persist_statement_source_manifest(
        conn,
        manifest,
        source_run_id=7,
    )
    second = persist_statement_source_manifest(
        conn,
        manifest,
        source_run_id=7,
    )

    assert second == first
    assert conn.execute(
        "SELECT COUNT(*) FROM statement_source_manifests"
    ).fetchone()[0] == 1
    loaded = load_statement_source_manifests(conn, "TEST")
    assert loaded[0]["_store"]["source_run_id"] == 7

    conn.execute(
        """
        UPDATE statement_source_manifests
        SET payload_json = '{"tampered":true}'
        WHERE manifest_id = ?
        """,
        (first,),
    )
    with pytest.raises(ValueError, match="integrity"):
        load_statement_source_manifests(conn, "TEST")


def test_reconciliation_run_hash_binds_selected_facts_and_manifests():
    conn = _connection()

    first = persist_statement_reconciliation_run(
        conn,
        ticker="TEST",
        as_of_date="2025-12-31",
        facts_fingerprint="raw-ledger",
        selected_fact_ids=["fact:b", "fact:a"],
        readiness={"status": "decision_grade"},
        manifest_ids=["manifest:b", "manifest:a"],
        selected_view_hash="selected-view",
        raw_ledger_hash="raw-ledger",
        status="decision_grade",
    )
    second = persist_statement_reconciliation_run(
        conn,
        ticker="test",
        as_of_date="2025-12-31",
        facts_fingerprint="raw-ledger",
        selected_fact_ids=["fact:a", "fact:b"],
        readiness={"status": "decision_grade"},
        manifest_ids=["manifest:a", "manifest:b"],
        selected_view_hash="selected-view",
        raw_ledger_hash="raw-ledger",
        status="decision_grade",
    )

    assert second == first
    assert conn.execute(
        "SELECT COUNT(*) FROM valuation_statement_reconciliation_runs"
    ).fetchone()[0] == 1
