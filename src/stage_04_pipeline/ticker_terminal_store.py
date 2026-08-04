"""Immutable checkpoints for terminal ticker valuation outcomes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import sqlite3
from typing import Any

from src.contracts.ticker_runs import (
    TickerIdentity,
    TickerTerminalRecord,
    canonical_hash,
)


@dataclass(frozen=True, slots=True)
class PersistedTickerTerminalOutcome:
    outcome_id: str
    execution_run_id: str
    batch_run_id: str | None
    ticker: str
    identity_key: str
    context_fingerprint: str
    checkpoint_fingerprint: str
    analysis_snapshot_hash: str
    readiness_fingerprint: str
    status: str
    reason_code: str
    reason_codes: tuple[str, ...]
    retryable: bool
    result_fingerprint: str | None
    attempt_count: int
    record_hash: str
    created_at: str
    record: TickerTerminalRecord

    def as_dict(self) -> dict[str, Any]:
        return {
            "outcome_id": self.outcome_id,
            "execution_run_id": self.execution_run_id,
            "batch_run_id": self.batch_run_id,
            "ticker": self.ticker,
            "identity_key": self.identity_key,
            "context_fingerprint": self.context_fingerprint,
            "checkpoint_fingerprint": self.checkpoint_fingerprint,
            "analysis_snapshot_hash": self.analysis_snapshot_hash,
            "readiness_fingerprint": self.readiness_fingerprint,
            "status": self.status,
            "reason_code": self.reason_code,
            "reason_codes": list(self.reason_codes),
            "retryable": self.retryable,
            "result_fingerprint": self.result_fingerprint,
            "attempt_count": self.attempt_count,
            "record_hash": self.record_hash,
            "created_at": self.created_at,
            "record": self.record.model_dump(mode="json"),
        }


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _required_text(value: str, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be blank")
    return normalized


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    return str(value).strip() or None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _outcome_id(
    execution_run_id: str,
    identity_key: str,
    batch_run_id: str | None,
) -> str:
    return canonical_hash(
        {
            "contract_version": "ticker_terminal_outcome.v1",
            "execution_run_id": execution_run_id,
            "batch_run_id": batch_run_id,
            "identity_key": identity_key,
        }
    )


def _row_mapping(row: sqlite3.Row | tuple[Any, ...]) -> dict[str, Any]:
    if isinstance(row, sqlite3.Row):
        return dict(row)
    columns = (
        "outcome_id",
        "execution_run_id",
        "batch_run_id",
        "ticker",
        "identity_key",
        "context_fingerprint",
        "checkpoint_fingerprint",
        "analysis_snapshot_hash",
        "readiness_fingerprint",
        "status",
        "reason_code",
        "reason_codes_json",
        "retryable",
        "result_fingerprint",
        "attempt_count",
        "record_hash",
        "record_json",
        "created_at",
    )
    return dict(zip(columns, row, strict=True))


_SELECT_COLUMNS = """
    outcome_id, execution_run_id, batch_run_id, ticker, identity_key,
    context_fingerprint, checkpoint_fingerprint, analysis_snapshot_hash,
    readiness_fingerprint, status, reason_code, reason_codes_json, retryable,
    result_fingerprint, attempt_count, record_hash, record_json, created_at
"""


def _outcome_from_row(
    row: sqlite3.Row | tuple[Any, ...],
) -> PersistedTickerTerminalOutcome:
    values = _row_mapping(row)
    record_json = str(values["record_json"])
    record = TickerTerminalRecord.model_validate_json(record_json)
    reason_codes = tuple(json.loads(str(values["reason_codes_json"])))
    expected = {
        "outcome_id": _outcome_id(
            str(values["execution_run_id"]),
            record.context.identity.canonical_key,
            _optional_text(values["batch_run_id"]),
        ),
        "ticker": record.context.identity.ticker,
        "identity_key": record.context.identity.canonical_key,
        "context_fingerprint": record.context.context_fingerprint,
        "checkpoint_fingerprint": record.checkpoint_fingerprint,
        "analysis_snapshot_hash": (
            record.context.replay_inputs.analysis_snapshot_hash
        ),
        "readiness_fingerprint": (
            record.context.readiness.readiness_fingerprint
        ),
        "status": record.status.value,
        "reason_code": record.reason_code.value,
        "reason_codes": record.reason_codes,
        "retryable": record.retryable,
        "result_fingerprint": record.result_fingerprint,
        "attempt_count": record.attempt_count,
        "record_hash": canonical_hash(record),
        "record_json": _canonical_json(
            record.model_dump(mode="json", exclude_computed_fields=True)
        ),
    }
    actual = {
        "outcome_id": str(values["outcome_id"]),
        "ticker": str(values["ticker"]),
        "identity_key": str(values["identity_key"]),
        "context_fingerprint": str(values["context_fingerprint"]),
        "checkpoint_fingerprint": str(values["checkpoint_fingerprint"]),
        "analysis_snapshot_hash": str(values["analysis_snapshot_hash"]),
        "readiness_fingerprint": str(values["readiness_fingerprint"]),
        "status": str(values["status"]),
        "reason_code": str(values["reason_code"]),
        "reason_codes": reason_codes,
        "retryable": bool(values["retryable"]),
        "result_fingerprint": values["result_fingerprint"],
        "attempt_count": int(values["attempt_count"]),
        "record_hash": str(values["record_hash"]),
        "record_json": record_json,
    }
    if actual != expected:
        raise ValueError("ticker terminal outcome integrity check failed")
    return PersistedTickerTerminalOutcome(
        outcome_id=actual["outcome_id"],
        execution_run_id=str(values["execution_run_id"]),
        batch_run_id=_optional_text(values["batch_run_id"]),
        ticker=actual["ticker"],
        identity_key=actual["identity_key"],
        context_fingerprint=actual["context_fingerprint"],
        checkpoint_fingerprint=actual["checkpoint_fingerprint"],
        analysis_snapshot_hash=actual["analysis_snapshot_hash"],
        readiness_fingerprint=actual["readiness_fingerprint"],
        status=actual["status"],
        reason_code=actual["reason_code"],
        reason_codes=reason_codes,
        retryable=actual["retryable"],
        result_fingerprint=actual["result_fingerprint"],
        attempt_count=actual["attempt_count"],
        record_hash=actual["record_hash"],
        created_at=str(values["created_at"]),
        record=record,
    )


def persist_ticker_terminal_outcome(
    conn: sqlite3.Connection,
    *,
    execution_run_id: str,
    record: TickerTerminalRecord,
    batch_run_id: str | None = None,
    created_at: str | None = None,
) -> PersistedTickerTerminalOutcome:
    """Persist one immutable terminal row for one execution and identity."""

    resolved_run_id = _required_text(execution_run_id, "execution_run_id")
    resolved_batch_run_id = _optional_text(batch_run_id)
    identity_key = record.context.identity.canonical_key
    outcome_id = _outcome_id(
        resolved_run_id,
        identity_key,
        resolved_batch_run_id,
    )
    record_json = _canonical_json(
        record.model_dump(mode="json", exclude_computed_fields=True)
    )
    values = (
        outcome_id,
        resolved_run_id,
        resolved_batch_run_id,
        record.context.identity.ticker,
        identity_key,
        record.context.context_fingerprint,
        record.checkpoint_fingerprint,
        record.context.replay_inputs.analysis_snapshot_hash,
        record.context.readiness.readiness_fingerprint,
        record.status.value,
        record.reason_code.value,
        _canonical_json(record.reason_codes),
        int(record.retryable),
        record.result_fingerprint,
        record.attempt_count,
        canonical_hash(record),
        record_json,
        created_at or _utc_now(),
    )
    with conn:
        existing = conn.execute(
            f"""
            SELECT {_SELECT_COLUMNS}
            FROM ticker_terminal_outcomes
            WHERE execution_run_id = ? AND identity_key = ?
            """,
            (resolved_run_id, identity_key),
        ).fetchone()
        if existing is None:
            conn.execute(
                """
                INSERT INTO ticker_terminal_outcomes (
                    outcome_id, execution_run_id, batch_run_id, ticker,
                    identity_key, context_fingerprint, checkpoint_fingerprint,
                    analysis_snapshot_hash, readiness_fingerprint, status,
                    reason_code, reason_codes_json, retryable,
                    result_fingerprint, attempt_count, record_hash, record_json,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
        else:
            persisted = _outcome_from_row(existing)
            if (
                persisted.outcome_id != outcome_id
                or persisted.batch_run_id != resolved_batch_run_id
                or persisted.checkpoint_fingerprint
                != record.checkpoint_fingerprint
            ):
                raise ValueError(
                    "ticker terminal outcome idempotency conflict"
                )
        row = conn.execute(
            f"""
            SELECT {_SELECT_COLUMNS}
            FROM ticker_terminal_outcomes
            WHERE outcome_id = ?
            """,
            (outcome_id,),
        ).fetchone()
    if row is None:
        raise RuntimeError("ticker terminal outcome persistence failed")
    return _outcome_from_row(row)


def load_ticker_terminal_outcome(
    conn: sqlite3.Connection,
    outcome_id: str,
) -> PersistedTickerTerminalOutcome | None:
    row = conn.execute(
        f"""
        SELECT {_SELECT_COLUMNS}
        FROM ticker_terminal_outcomes
        WHERE outcome_id = ?
        """,
        (_required_text(outcome_id, "outcome_id"),),
    ).fetchone()
    return _outcome_from_row(row) if row is not None else None


def list_ticker_terminal_outcomes(
    conn: sqlite3.Connection,
    *,
    ticker: str | None = None,
    execution_run_id: str | None = None,
    batch_run_id: str | None = None,
    limit: int = 100,
) -> tuple[PersistedTickerTerminalOutcome, ...]:
    if (
        isinstance(limit, bool)
        or not isinstance(limit, int)
        or not 1 <= limit <= 250
    ):
        raise ValueError("limit must be between 1 and 250")
    clauses: list[str] = []
    params: list[Any] = []
    if ticker is not None:
        clauses.append("ticker = ?")
        params.append(_required_text(ticker, "ticker").upper())
    if execution_run_id is not None:
        clauses.append("execution_run_id = ?")
        params.append(
            _required_text(execution_run_id, "execution_run_id")
        )
    if batch_run_id is not None:
        clauses.append("batch_run_id = ?")
        params.append(_required_text(batch_run_id, "batch_run_id"))
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f"""
        SELECT {_SELECT_COLUMNS}
        FROM ticker_terminal_outcomes
        {where}
        ORDER BY created_at DESC, outcome_id DESC
        LIMIT ?
        """,
        (*params, limit),
    ).fetchall()
    return tuple(_outcome_from_row(row) for row in rows)


def build_ticker_terminal_outcomes_payload(
    ticker: str,
    *,
    limit: int = 25,
) -> dict[str, Any]:
    """Load bounded terminal history for the read-only API surface."""

    from db.schema import get_connection

    normalized_ticker = TickerIdentity(ticker=ticker).ticker
    with get_connection() as conn:
        outcomes = list_ticker_terminal_outcomes(
            conn,
            ticker=normalized_ticker,
            limit=limit,
        )
    return {
        "ticker": normalized_ticker,
        "count": len(outcomes),
        "limit": limit,
        "outcomes": [outcome.as_dict() for outcome in outcomes],
    }


__all__ = [
    "PersistedTickerTerminalOutcome",
    "build_ticker_terminal_outcomes_payload",
    "list_ticker_terminal_outcomes",
    "load_ticker_terminal_outcome",
    "persist_ticker_terminal_outcome",
]
