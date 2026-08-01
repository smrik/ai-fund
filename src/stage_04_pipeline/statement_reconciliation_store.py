"""Durable integrity-checked statement manifests and reconciliation runs."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import sqlite3
from typing import Any, Mapping, Sequence


_MANIFEST_STATUSES = frozenset({"completed", "partial", "failed"})


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _payload_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _manifest_content_id(manifest: Mapping[str, Any]) -> str:
    content = dict(manifest)
    content.pop("manifest_id", None)
    content.pop("manifest_hash", None)
    return f"sha256:{_payload_hash(content)}"


def persist_statement_source_manifest(
    conn: sqlite3.Connection,
    manifest: Mapping[str, Any],
    *,
    source_run_id: int | str | None = None,
    accession: str | None = None,
    evidence_cutoff: str | None = None,
    created_at: str | None = None,
) -> str:
    """Persist one immutable coverage manifest and verify idempotent retries."""

    payload = dict(manifest)
    manifest_id = str(
        payload.get("manifest_id") or _manifest_content_id(payload)
    )
    if manifest_id != _manifest_content_id(payload):
        raise ValueError("statement manifest_id does not match canonical payload")
    ticker = str(payload.get("ticker") or "").strip().upper()
    source = str(payload.get("source") or "").strip()
    status = str(payload.get("status") or "").strip().lower()
    contract_version = str(
        payload.get("contract_version") or ""
    ).strip()
    resolved_evidence_cutoff = str(
        evidence_cutoff
        or payload.get("evidence_cutoff")
        or payload.get("as_of_date")
        or payload.get("filing_date")
        or ""
    ).strip()
    if (
        not ticker
        or not source
        or not contract_version
        or not resolved_evidence_cutoff
    ):
        raise ValueError(
            "statement manifest requires ticker, source, contract_version, "
            "and evidence_cutoff"
        )
    if status not in _MANIFEST_STATUSES:
        raise ValueError(f"invalid statement manifest status: {status}")

    raw_run_id = (
        source_run_id
        if source_run_id is not None
        else payload.get("source_run_id")
    )
    if isinstance(raw_run_id, bool):
        raise ValueError("statement manifest source_run_id must not be boolean")
    if isinstance(raw_run_id, str):
        resolved_run_id: int | str | None = raw_run_id.strip() or None
    elif isinstance(raw_run_id, int) or raw_run_id is None:
        resolved_run_id = raw_run_id
    else:
        raise ValueError(
            "statement manifest source_run_id must be an integer or string"
        )
    resolved_accession = str(
        accession or payload.get("accession") or ""
    ).strip() or None
    payload_json = _canonical_json(payload)
    payload_hash = _payload_hash(payload)
    conn.execute(
        """
        INSERT INTO statement_source_manifests (
            manifest_id, ticker, source, source_run_id, accession, status,
            contract_version, evidence_cutoff, payload_hash, payload_json,
            created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(manifest_id) DO NOTHING
        """,
        (
            manifest_id,
            ticker,
            source,
            resolved_run_id,
            resolved_accession,
            status,
            contract_version,
            resolved_evidence_cutoff,
            payload_hash,
            payload_json,
            created_at or _utc_now(),
        ),
    )
    row = conn.execute(
        """
        SELECT ticker, source, source_run_id, accession, status,
               contract_version, evidence_cutoff, payload_hash, payload_json
        FROM statement_source_manifests
        WHERE manifest_id = ?
        """,
        (manifest_id,),
    ).fetchone()
    if row is None:
        raise RuntimeError("statement manifest persistence failed")
    existing = dict(row) if isinstance(row, sqlite3.Row) else {
        "ticker": row[0],
        "source": row[1],
        "source_run_id": row[2],
        "accession": row[3],
        "status": row[4],
        "contract_version": row[5],
        "evidence_cutoff": row[6],
        "payload_hash": row[7],
        "payload_json": row[8],
    }
    if (
        existing["ticker"] != ticker
        or existing["source"] != source
        or existing["source_run_id"] != resolved_run_id
        or existing["accession"] != resolved_accession
        or existing["status"] != status
        or existing["contract_version"] != contract_version
        or existing["evidence_cutoff"] != resolved_evidence_cutoff
        or existing["payload_hash"] != payload_hash
        or existing["payload_json"] != payload_json
    ):
        raise ValueError("statement manifest idempotency conflict")
    conn.commit()
    return manifest_id


def load_statement_source_manifests(
    conn: sqlite3.Connection,
    ticker: str,
    *,
    evidence_cutoff: str | None = None,
) -> tuple[dict[str, Any], ...]:
    normalized_ticker = str(ticker).strip().upper()
    if not normalized_ticker:
        raise ValueError("ticker is required")
    clauses = ["ticker = ?"]
    params: list[Any] = [normalized_ticker]
    if evidence_cutoff:
        clauses.append("evidence_cutoff <= ?")
        params.append(str(evidence_cutoff))
    rows = conn.execute(
        f"""
        SELECT manifest_id, ticker, source, source_run_id, accession, status,
               contract_version, evidence_cutoff, payload_hash, payload_json,
               created_at
        FROM statement_source_manifests
        WHERE {' AND '.join(clauses)}
        ORDER BY evidence_cutoff DESC, created_at DESC, manifest_id DESC
        """,
        params,
    ).fetchall()
    manifests: list[dict[str, Any]] = []
    for raw_row in rows:
        row = dict(raw_row) if isinstance(raw_row, sqlite3.Row) else {
            "manifest_id": raw_row[0],
            "ticker": raw_row[1],
            "source": raw_row[2],
            "source_run_id": raw_row[3],
            "accession": raw_row[4],
            "status": raw_row[5],
            "contract_version": raw_row[6],
            "evidence_cutoff": raw_row[7],
            "payload_hash": raw_row[8],
            "payload_json": raw_row[9],
            "created_at": raw_row[10],
        }
        payload = json.loads(str(row["payload_json"]))
        if (
            _payload_hash(payload) != row["payload_hash"]
            or str(payload.get("manifest_id") or "") != row["manifest_id"]
            or str(payload.get("ticker") or "").upper() != row["ticker"]
            or str(payload.get("source") or "") != row["source"]
            or str(payload.get("status") or "").lower() != row["status"]
            or str(payload.get("contract_version") or "")
            != row["contract_version"]
        ):
            raise ValueError(
                f"statement manifest integrity failure: {row['manifest_id']}"
            )
        payload["_store"] = {
            "manifest_id": row["manifest_id"],
            "source_run_id": row["source_run_id"],
            "accession": row["accession"],
            "evidence_cutoff": row["evidence_cutoff"],
            "created_at": row["created_at"],
        }
        manifests.append(payload)
    return tuple(manifests)


def persist_statement_reconciliation_run(
    conn: sqlite3.Connection,
    *,
    ticker: str,
    as_of_date: str,
    facts_fingerprint: str,
    selected_fact_ids: Sequence[str],
    readiness: Mapping[str, Any],
    manifest_ids: Sequence[str],
    selected_view_hash: str,
    raw_ledger_hash: str,
    status: str,
    created_at: str | None = None,
) -> str:
    """Persist the immutable selected view that downstream snapshots may bind."""

    selected_ids = tuple(sorted({str(value) for value in selected_fact_ids}))
    manifest_keys = tuple(sorted({str(value) for value in manifest_ids}))
    readiness_payload = dict(readiness)
    readiness_hash = _payload_hash(readiness_payload)
    identity = {
        "ticker": str(ticker).strip().upper(),
        "as_of_date": str(as_of_date),
        "facts_fingerprint": str(facts_fingerprint),
        "selected_fact_ids": selected_ids,
        "readiness_hash": readiness_hash,
        "manifest_ids": manifest_keys,
        "selected_view_hash": str(selected_view_hash),
        "raw_ledger_hash": str(raw_ledger_hash),
        "status": str(status),
    }
    run_hash = _payload_hash(identity)
    conn.execute(
        """
        INSERT INTO valuation_statement_reconciliation_runs (
            run_hash, ticker, as_of_date, facts_fingerprint,
            selected_fact_ids_json, readiness_json, readiness_hash,
            manifest_ids_json, selected_view_hash, raw_ledger_hash, status,
            created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(run_hash) DO NOTHING
        """,
        (
            run_hash,
            identity["ticker"],
            identity["as_of_date"],
            identity["facts_fingerprint"],
            _canonical_json(selected_ids),
            _canonical_json(readiness_payload),
            readiness_hash,
            _canonical_json(manifest_keys),
            identity["selected_view_hash"],
            identity["raw_ledger_hash"],
            identity["status"],
            created_at or _utc_now(),
        ),
    )
    conn.commit()
    return run_hash


__all__ = [
    "load_statement_source_manifests",
    "persist_statement_reconciliation_run",
    "persist_statement_source_manifest",
]
