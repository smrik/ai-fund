from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any

from db.loader import insert_statement_facts
from src.contracts.analysis_snapshot import AnalysisSnapshot
from src.contracts.judgment_runs import canonical_semantic_hash
from src.stage_04_pipeline.statement_reconciliation_store import (
    persist_statement_reconciliation_run,
    persist_statement_source_manifest,
)


_SOURCE = "fixture_statement_v1"
_RECONCILIATION_CONTRACT_VERSION = "statement_reconciliation_v2"


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _fact(ticker: str, as_of_date: str) -> dict[str, Any]:
    fact_id = f"fixture:{ticker}:{as_of_date}:revenue"
    return {
        "fact_id": fact_id,
        "ingestion_fingerprint": f"fingerprint:{fact_id}",
        "ticker": ticker,
        "source": _SOURCE,
        "statement": "IncomeStatement",
        "concept": "Revenue",
        "label": "Revenue",
        "value": 100.0,
        "numeric_value": 100.0,
        "unit": "USD",
        "currency": "USD",
        "scale_factor": 1.0,
        "period_kind": "annual",
        "period_type": "duration",
        "period_start": f"{as_of_date[:4]}-01-01",
        "period_end": as_of_date,
        "filing_date": as_of_date,
        "dimensions": {},
        "hierarchy": {"presentation_complete": True},
        "source_locator": fact_id,
    }


def _manifest(ticker: str, as_of_date: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "contract_version": "statement_coverage_v1",
        "ticker": ticker,
        "source": _SOURCE,
        "status": "completed",
        "evidence_cutoff": as_of_date,
        "coverage": {"fixture": True},
        "errors": [],
    }
    payload["manifest_id"] = "sha256:" + hashlib.sha256(
        _canonical_json(payload).encode("utf-8")
    ).hexdigest()
    return payload


def _fact_identity(fact: dict[str, Any]) -> dict[str, Any]:
    return {
        "fact_id": str(fact.get("fact_id") or ""),
        "ingestion_fingerprint": str(
            fact.get("ingestion_fingerprint") or ""
        ),
        "source": str(fact.get("source") or ""),
        "source_run_id": fact.get("source_run_id"),
        "accession": fact.get("accession"),
        "statement": str(fact.get("statement") or ""),
        "concept": str(fact.get("concept") or ""),
        "period_start": fact.get("period_start"),
        "period_end": fact.get("period_end"),
        "period_kind": fact.get("period_kind"),
        "unit": fact.get("unit"),
        "currency": fact.get("currency"),
        "scale_factor": fact.get("scale_factor"),
        "statement_role": (
            (fact.get("hierarchy") or {}).get("statement_role")
        ),
        "presentation_path": (
            (fact.get("hierarchy") or {}).get("presentation_path")
        ),
        "context_ref": fact.get("context_ref")
        or (fact.get("context") or {}).get("context_ref"),
    }


def _fact_projection(fact: dict[str, Any]) -> dict[str, Any]:
    return {
        "fact_id": fact.get("fact_id"),
        "ingestion_fingerprint": fact.get("ingestion_fingerprint"),
        "source": fact.get("source"),
        "statement": fact.get("statement"),
        "concept": fact.get("concept"),
        "label": fact.get("label"),
        "numeric_value": fact.get("numeric_value"),
        "unit": fact.get("unit"),
        "currency": fact.get("currency"),
        "scale_factor": fact.get("scale_factor"),
        "period_kind": fact.get("period_kind"),
        "period_type": fact.get("period_type"),
        "period_start": fact.get("period_start"),
        "period_end": fact.get("period_end"),
        "fiscal_year": fact.get("fiscal_year"),
        "fiscal_period": fact.get("fiscal_period"),
        "filing_date": fact.get("filing_date"),
        "form_type": fact.get("form_type"),
        "accession": fact.get("accession"),
        "source_locator": fact.get("source_locator"),
        "is_derived": bool(fact.get("is_derived")),
        "derivation": fact.get("derivation"),
        "hierarchy": fact.get("hierarchy") or {},
    }


def _selected_view_hash(
    *,
    ticker: str,
    as_of_date: str,
    manifest_ids: tuple[str, ...],
    fact: dict[str, Any],
) -> str:
    return canonical_semantic_hash(
        {
            "contract_version": _RECONCILIATION_CONTRACT_VERSION,
            "ticker": ticker,
            "as_of_date": as_of_date,
            "manifest_ids": manifest_ids,
            "facts": [_fact_identity(fact)],
        }
    )


def authoritative_snapshot(
    payload: dict[str, Any],
) -> AnalysisSnapshot:
    resolved = dict(payload)
    ticker = str(resolved["ticker"]).upper()
    as_of_date = str(resolved["as_of_date"])
    fact = _fact(ticker, as_of_date)
    manifest = _manifest(ticker, as_of_date)
    statements = dict(resolved["statements"])
    statements["fact_ids"] = [fact["fact_id"]]
    statements["consolidated_view"] = [_fact_projection(fact)]
    readiness = dict(resolved["statement_reconciliation"])
    facts_fingerprint = canonical_semantic_hash(
        [_fact_identity(fact)]
    )
    readiness_hash = canonical_semantic_hash(readiness)
    selected_view_hash = _selected_view_hash(
        ticker=ticker,
        as_of_date=as_of_date,
        manifest_ids=(manifest["manifest_id"],),
        fact=fact,
    )
    identity = {
        "ticker": ticker,
        "as_of_date": as_of_date,
        "facts_fingerprint": facts_fingerprint,
        "selected_fact_ids": (fact["fact_id"],),
        "readiness_hash": readiness_hash,
        "manifest_ids": (manifest["manifest_id"],),
        "selected_view_hash": selected_view_hash,
        "raw_ledger_hash": facts_fingerprint,
        "status": str(readiness["status"]),
    }
    run_hash = canonical_semantic_hash(identity)
    resolved["statements"] = statements
    resolved["statement_reconciliation"] = {
        **readiness,
        "reconciliation_run_hash": run_hash,
        "selected_fact_ids": [fact["fact_id"]],
    }
    resolved["source_fingerprints"] = {
        **dict(resolved["source_fingerprints"]),
        "statement_reconciliation_run": run_hash,
    }
    return AnalysisSnapshot.model_validate(resolved)


def persist_snapshot_provenance(
    conn: sqlite3.Connection,
    snapshot: AnalysisSnapshot,
) -> str:
    ticker = snapshot.ticker
    as_of_date = snapshot.as_of_date
    fact = _fact(ticker, as_of_date)
    manifest = _manifest(ticker, as_of_date)
    insert_statement_facts(conn, [fact])
    manifest_id = persist_statement_source_manifest(conn, manifest)
    readiness = dict(snapshot.statement_reconciliation)
    expected_run_hash = str(readiness.pop("reconciliation_run_hash"))
    selected_fact_ids = tuple(readiness.pop("selected_fact_ids"))
    facts_fingerprint = canonical_semantic_hash(
        [_fact_identity(fact)]
    )
    actual_run_hash = persist_statement_reconciliation_run(
        conn,
        ticker=ticker,
        as_of_date=as_of_date,
        facts_fingerprint=facts_fingerprint,
        selected_fact_ids=selected_fact_ids,
        readiness=readiness,
        manifest_ids=(manifest_id,),
        selected_view_hash=_selected_view_hash(
            ticker=ticker,
            as_of_date=as_of_date,
            manifest_ids=(manifest_id,),
            fact=fact,
        ),
        raw_ledger_hash=facts_fingerprint,
        status=str(readiness["status"]),
    )
    if actual_run_hash != expected_run_hash:
        raise AssertionError("fixture statement run hash changed")
    return actual_run_hash
