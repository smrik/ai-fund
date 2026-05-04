from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from db.schema import create_tables, get_connection
from src.contracts.ticker_dossier import TickerDossier


ConnectionFactory = Callable[[], sqlite3.Connection]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _source_key(dossier: TickerDossier) -> str:
    snapshot_id = dossier.export_metadata.snapshot_id
    if snapshot_id is not None:
        return f"snapshot:{snapshot_id}"
    return f"asof:{dossier.as_of_date}"


def _normalise_payload(dossier_payload: TickerDossier | dict[str, Any]) -> tuple[TickerDossier, dict[str, Any]]:
    dossier = TickerDossier.model_validate(dossier_payload)
    payload = dossier.model_dump(mode="json")
    return dossier, payload


def _row_to_payload(row: sqlite3.Row) -> TickerDossier:
    return TickerDossier.model_validate_json(row["payload_json"])


def _upsert_with_connection(conn: sqlite3.Connection, dossier_payload: TickerDossier | dict[str, Any]) -> TickerDossier:
    create_tables(conn)
    dossier, payload = _normalise_payload(dossier_payload)
    source_mode = dossier.export_metadata.source_mode or dossier.loaded_backend_state.source_mode
    source_key = _source_key(dossier)
    now = _now()
    conn.execute(
        """
        INSERT INTO ticker_dossier_snapshots (
            ticker, as_of_date, contract_version, source_mode, source_key,
            snapshot_id, generated_at, display_name, payload_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(ticker, source_mode, source_key, contract_version) DO UPDATE SET
            as_of_date = excluded.as_of_date,
            snapshot_id = excluded.snapshot_id,
            generated_at = excluded.generated_at,
            display_name = excluded.display_name,
            payload_json = excluded.payload_json,
            updated_at = excluded.updated_at
        """,
        [
            dossier.ticker.upper(),
            dossier.as_of_date,
            dossier.contract_version,
            source_mode,
            source_key,
            dossier.export_metadata.snapshot_id,
            dossier.export_metadata.generated_at,
            dossier.display_name,
            json.dumps(payload, sort_keys=True),
            now,
            now,
        ],
    )
    conn.commit()
    return dossier


def upsert_ticker_dossier_snapshot(
    dossier_payload: TickerDossier | dict[str, Any],
    *,
    conn: sqlite3.Connection | None = None,
    connection_factory: ConnectionFactory | None = None,
) -> TickerDossier:
    """Persist a validated canonical TickerDossier payload as one JSON snapshot."""
    if conn is not None:
        return _upsert_with_connection(conn, dossier_payload)

    factory = connection_factory or get_connection
    with factory() as managed_conn:
        return _upsert_with_connection(managed_conn, dossier_payload)


def load_latest_ticker_dossier(
    ticker: str,
    source_mode: str | None = None,
    *,
    conn: sqlite3.Connection | None = None,
    connection_factory: ConnectionFactory | None = None,
) -> TickerDossier | None:
    """Load and validate the latest persisted TickerDossier payload for a ticker."""
    ticker = str(ticker or "").strip().upper()
    if not ticker:
        raise ValueError("ticker is required")

    def _load(active_conn: sqlite3.Connection) -> TickerDossier | None:
        create_tables(active_conn)
        query = [
            "SELECT payload_json FROM ticker_dossier_snapshots",
            "WHERE ticker = ?",
        ]
        params: list[Any] = [ticker]
        if source_mode:
            query.append("AND source_mode = ?")
            params.append(source_mode)
        query.append("ORDER BY as_of_date DESC, updated_at DESC LIMIT 1")
        row = active_conn.execute(" ".join(query), params).fetchone()
        if row is None:
            return None
        return _row_to_payload(row)

    if conn is not None:
        return _load(conn)

    factory = connection_factory or get_connection
    with factory() as managed_conn:
        return _load(managed_conn)
