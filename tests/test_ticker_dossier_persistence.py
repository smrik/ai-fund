from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import uuid4

from db.schema import create_tables


def _workspace_tempdir(name: str) -> Path:
    root = Path.cwd() / ".tmp-tests" / "ticker-dossier-persistence"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{name}-{uuid4().hex}"
    path.mkdir(parents=True)
    return path


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    create_tables(conn)
    return conn


def _legacy_payload(company_name: str = "International Business Machines") -> dict:
    return {
        "ticker": "IBM",
        "company_name": company_name,
        "currency": "USD",
        "generated_at": "2026-04-30T12:00:00+00:00",
        "market": {"price": 260.0, "beta": 1.1},
        "valuation": {"iv_base": 202.0, "iv_bear": 180.0, "iv_bull": 230.0, "expected_iv": 205.0},
        "ciq_lineage": {"snapshot_as_of_date": "2026-04-30"},
        "comps_analysis": {"primary_metric": "tev_ebitda_ltm", "peer_counts": {"raw": 4, "clean": 3}},
        "forecast_bridge": [{"year": 2027, "fcff": 100.0}],
    }


def _dossier_payload(company_name: str = "International Business Machines", snapshot_id: int | None = 42) -> dict:
    from src.stage_04_pipeline.ticker_dossier import build_ticker_dossier_from_export_payload, ticker_dossier_to_payload

    dossier = build_ticker_dossier_from_export_payload(
        _legacy_payload(company_name),
        source_mode="latest_snapshot",
        snapshot_id=snapshot_id,
    )
    return ticker_dossier_to_payload(dossier)


def test_ticker_dossier_schema_creates_table_indexes_and_unique_key():
    conn = _connect(_workspace_tempdir("schema") / "schema.db")

    columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(ticker_dossier_snapshots)").fetchall()
    }
    indexes = {
        row["name"]: row["unique"]
        for row in conn.execute("PRAGMA index_list(ticker_dossier_snapshots)").fetchall()
    }

    assert {
        "id",
        "ticker",
        "as_of_date",
        "contract_version",
        "source_mode",
        "source_key",
        "snapshot_id",
        "generated_at",
        "display_name",
        "payload_json",
        "created_at",
        "updated_at",
    } <= columns
    assert "idx_ticker_dossier_snapshots_ticker_mode_asof" in indexes
    assert "idx_ticker_dossier_snapshots_ticker_updated" in indexes
    assert any(unique for unique in indexes.values())


def test_ticker_dossier_persistence_round_trips_validated_payload():
    from db.ticker_dossier import load_latest_ticker_dossier, upsert_ticker_dossier_snapshot

    conn = _connect(_workspace_tempdir("roundtrip") / "roundtrip.db")
    payload = _dossier_payload()

    upsert_ticker_dossier_snapshot(payload, conn=conn)
    loaded = load_latest_ticker_dossier("ibm", source_mode="latest_snapshot", conn=conn)

    assert loaded is not None
    assert loaded.model_dump(mode="json") == payload


def test_ticker_dossier_upsert_updates_same_source_key_without_duplicates():
    from db.ticker_dossier import load_latest_ticker_dossier, upsert_ticker_dossier_snapshot

    conn = _connect(_workspace_tempdir("upsert") / "upsert.db")
    upsert_ticker_dossier_snapshot(_dossier_payload(), conn=conn)
    upsert_ticker_dossier_snapshot(_dossier_payload("IBM Updated Name"), conn=conn)

    row_count = conn.execute("SELECT COUNT(*) AS n FROM ticker_dossier_snapshots").fetchone()["n"]
    loaded = load_latest_ticker_dossier("IBM", source_mode="latest_snapshot", conn=conn)

    assert row_count == 1
    assert loaded is not None
    assert loaded.display_name == "IBM Updated Name"
    assert loaded.latest_snapshot.company_identity.display_name == "IBM Updated Name"


def test_ticker_dossier_source_key_uses_as_of_date_when_snapshot_is_missing():
    from db.ticker_dossier import upsert_ticker_dossier_snapshot

    conn = _connect(_workspace_tempdir("asof") / "asof.db")
    upsert_ticker_dossier_snapshot(_dossier_payload(snapshot_id=None), conn=conn)

    row = conn.execute("SELECT source_key FROM ticker_dossier_snapshots").fetchone()

    assert row["source_key"] == "asof:2026-04-30"


def test_create_tables_does_not_backfill_existing_archive_rows():
    conn = _connect(_workspace_tempdir("no-backfill") / "no-backfill.db")
    conn.execute(
        """
        INSERT INTO pipeline_report_archive (
            ticker, created_at, company_name, memo_json
        ) VALUES (?, ?, ?, ?)
        """,
        ["IBM", "2026-04-30T12:00:00+00:00", "International Business Machines", "{}"],
    )
    conn.commit()

    create_tables(conn)
    row = conn.execute("SELECT COUNT(*) AS n FROM ticker_dossier_snapshots").fetchone()

    assert row["n"] == 0
