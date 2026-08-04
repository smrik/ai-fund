"""Compile deterministic valuation evidence into one frozen judgment snapshot."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from enum import Enum
import json
import sqlite3
from typing import Any, Mapping, Sequence

from pydantic import BaseModel

from db.loader import load_statement_facts
from src.contracts.analysis_snapshot import (
    ANALYSIS_SNAPSHOT_CONTRACT_VERSION,
    AnalysisSnapshot,
)
from src.contracts.judgment_runs import canonical_semantic_hash
from src.stage_00_data.source_reconciliation import StatementReadinessResult
from src.stage_02_valuation.input_assembler import ValuationInputsWithLineage
from src.stage_04_pipeline.statement_reconciliation_service import (
    TickerStatementReconciliationRun,
    _RECONCILIATION_CONTRACT_VERSION,
    _fact_identity_payload,
    _facts_as_of,
)
from src.stage_04_pipeline.statement_reconciliation_store import (
    load_statement_source_manifests,
)


ANALYSIS_SNAPSHOT_BUILDER_VERSION = "1.0.0"


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", exclude_computed_fields=True)
    if is_dataclass(value) and not isinstance(value, type):
        return _jsonable(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {
            str(key): _jsonable(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _statement_source_fingerprints(
    *,
    ticker: str,
    statement_facts: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, str], list[str]]:
    by_source: dict[str, set[str]] = {}
    fact_ids: set[str] = set()
    for fact in statement_facts:
        fact_ticker = str(fact.get("ticker") or "").strip().upper()
        if fact_ticker != ticker:
            raise ValueError(
                "analysis snapshot cannot contain cross-ticker statement evidence"
            )
        source = str(fact.get("source") or "").strip()
        fact_id = str(fact.get("fact_id") or "").strip()
        fingerprint = str(
            fact.get("ingestion_fingerprint") or ""
        ).strip()
        if not source or not fact_id or not fingerprint:
            raise ValueError(
                "statement facts require source, fact_id, and "
                "ingestion_fingerprint"
            )
        by_source.setdefault(source, set()).add(fingerprint)
        fact_ids.add(fact_id)
    fingerprints = {
        source: canonical_semantic_hash(sorted(values))
        for source, values in sorted(by_source.items())
    }
    return fingerprints, sorted(fact_ids)


def _authoritative_statement_evidence(
    *,
    conn: sqlite3.Connection,
    ticker: str,
    as_of_date: str,
    reconciliation_run: TickerStatementReconciliationRun,
) -> tuple[
    list[Mapping[str, Any]],
    StatementReadinessResult,
    str,
    list[str],
    list[dict[str, Any]],
]:
    if reconciliation_run.ticker != ticker:
        raise ValueError(
            "statement reconciliation run ticker does not match valuation"
        )
    all_facts = load_statement_facts(conn, ticker)
    if not all_facts:
        raise ValueError(
            "authoritative valuation snapshot requires persisted statement facts"
        )
    if reconciliation_run.as_of_date != as_of_date:
        relation = (
            "post-as-of "
            if reconciliation_run.as_of_date > as_of_date
            else ""
        )
        raise ValueError(
            f"{relation}statement reconciliation run as-of date does not "
            "match valuation"
        )

    persisted_row = conn.execute(
        """
        SELECT ticker, as_of_date, facts_fingerprint,
               selected_fact_ids_json, readiness_json, readiness_hash,
               manifest_ids_json, selected_view_hash, raw_ledger_hash,
               status
        FROM valuation_statement_reconciliation_runs
        WHERE run_hash = ?
        """,
        (reconciliation_run.run_hash,),
    ).fetchone()
    if persisted_row is None:
        raise ValueError(
            "statement reconciliation run is not persisted"
        )
    (
        stored_ticker,
        stored_as_of_date,
        stored_facts_fingerprint,
        stored_selected_fact_ids_json,
        stored_readiness_json,
        stored_readiness_hash,
        stored_manifest_ids_json,
        stored_selected_view_hash,
        stored_raw_ledger_hash,
        stored_status,
    ) = tuple(persisted_row)
    readiness_payload = _jsonable(reconciliation_run.readiness)
    selected_fact_ids = tuple(
        sorted(str(value) for value in reconciliation_run.selected_fact_ids)
    )
    manifest_ids = tuple(
        sorted(str(value) for value in reconciliation_run.manifest_ids)
    )
    persisted_selected_fact_ids = tuple(
        sorted(json.loads(str(stored_selected_fact_ids_json)))
    )
    persisted_manifest_ids = tuple(
        sorted(json.loads(str(stored_manifest_ids_json)))
    )
    if (
        str(stored_ticker) != ticker
        or str(stored_as_of_date) != as_of_date
        or str(stored_facts_fingerprint)
        != reconciliation_run.facts_fingerprint
        or persisted_selected_fact_ids != selected_fact_ids
        or json.loads(str(stored_readiness_json)) != readiness_payload
        or str(stored_readiness_hash)
        != canonical_semantic_hash(readiness_payload)
        or persisted_manifest_ids != manifest_ids
        or str(stored_selected_view_hash)
        != reconciliation_run.selected_view_hash
        or str(stored_raw_ledger_hash)
        != reconciliation_run.raw_ledger_hash
        or str(stored_status)
        != str(reconciliation_run.readiness.status)
    ):
        raise ValueError(
            "statement reconciliation run does not match persisted evidence"
        )
    run_identity = {
        "ticker": ticker,
        "as_of_date": as_of_date,
        "facts_fingerprint": str(stored_facts_fingerprint),
        "selected_fact_ids": persisted_selected_fact_ids,
        "readiness_hash": str(stored_readiness_hash),
        "manifest_ids": persisted_manifest_ids,
        "selected_view_hash": str(stored_selected_view_hash),
        "raw_ledger_hash": str(stored_raw_ledger_hash),
        "status": str(stored_status),
    }
    if canonical_semantic_hash(run_identity) != reconciliation_run.run_hash:
        raise ValueError(
            "statement reconciliation run hash is invalid"
        )

    raw_facts = tuple(_facts_as_of(all_facts, as_of_date))
    raw_ledger_hash = canonical_semantic_hash(
        sorted(
            (
                _fact_identity_payload(fact)
                for fact in raw_facts
            ),
            key=lambda item: (
                item["source"],
                item["fact_id"],
                item["ingestion_fingerprint"],
            ),
        )
    )
    if (
        raw_ledger_hash != reconciliation_run.raw_ledger_hash
        or raw_ledger_hash != reconciliation_run.facts_fingerprint
    ):
        raise ValueError(
            "persisted statement facts changed after reconciliation"
        )

    facts_by_id = {
        str(fact.get("fact_id") or ""): fact
        for fact in raw_facts
    }
    if set(facts_by_id).issuperset(selected_fact_ids) is False:
        raise ValueError(
            "statement reconciliation references missing selected facts"
        )
    selected = sorted(
        (facts_by_id[fact_id] for fact_id in selected_fact_ids),
        key=lambda fact: (
            str(fact.get("source") or ""),
            str(fact.get("statement") or ""),
            str(fact.get("period_end") or ""),
            str(fact.get("period_start") or ""),
            str(fact.get("fact_id") or ""),
        ),
    )
    if not selected:
        raise ValueError(
            "statement reconciliation selected no authoritative facts"
        )
    for fact in selected:
        for field_name in ("period_end", "filing_date"):
            value = str(fact.get(field_name) or "").strip()
            if value and value > as_of_date:
                raise ValueError(
                    "post-as-of statement evidence cannot enter a valuation "
                    f"snapshot: fact_id={fact.get('fact_id')}, "
                    f"{field_name}={value}, as_of_date={as_of_date}"
                )

    selected_view_hash = canonical_semantic_hash(
        {
            "contract_version": _RECONCILIATION_CONTRACT_VERSION,
            "ticker": ticker,
            "as_of_date": as_of_date,
            "manifest_ids": manifest_ids,
            "facts": [
                _fact_identity_payload(fact)
                for fact in selected
            ],
        }
    )
    if selected_view_hash != reconciliation_run.selected_view_hash:
        raise ValueError(
            "statement reconciliation selected view changed"
        )
    consolidated_view = [
        {
            key: _jsonable(fact.get(key))
            for key in (
                "fact_id",
                "ingestion_fingerprint",
                "source",
                "statement",
                "concept",
                "label",
                "numeric_value",
                "unit",
                "currency",
                "scale_factor",
                "period_kind",
                "period_type",
                "period_start",
                "period_end",
                "fiscal_year",
                "fiscal_period",
                "filing_date",
                "form_type",
                "accession",
                "source_locator",
                "is_derived",
                "derivation",
                "hierarchy",
            )
        }
        for fact in selected
    ]
    manifests = load_statement_source_manifests(
        conn,
        ticker,
        evidence_cutoff=as_of_date,
    )
    manifests_by_id = {
        str(manifest["_store"]["manifest_id"]): manifest
        for manifest in manifests
        if str(manifest.get("status") or "").lower() == "completed"
    }
    if not set(manifest_ids).issubset(manifests_by_id):
        raise ValueError(
            "statement reconciliation references missing source manifests"
        )
    manifest_sources = {
        str(manifests_by_id[manifest_id].get("source") or "")
        for manifest_id in manifest_ids
    }
    selected_sources = {
        str(fact.get("source") or "")
        for fact in selected
    }
    has_xbrl_manifest = any(
        source.lower().startswith("sec_xbrl_filing_presentation")
        or source.lower() == "sec_filing_xbrl"
        for source in manifest_sources
    )
    missing_manifest_sources = sorted(
        source
        for source in selected_sources
        if source not in manifest_sources
        and not (
            source.lower().startswith("sec_xbrl_derived_ltm")
            and has_xbrl_manifest
        )
    )
    if missing_manifest_sources:
        raise ValueError(
            "authoritative statement facts require completed source manifests: "
            + ", ".join(missing_manifest_sources)
        )
    return (
        list(selected),
        reconciliation_run.readiness,
        reconciliation_run.run_hash,
        list(selected_fact_ids),
        consolidated_view,
    )


def build_valuation_analysis_snapshot(
    *,
    conn: sqlite3.Connection,
    valuation_inputs: ValuationInputsWithLineage,
    statement_reconciliation_run: TickerStatementReconciliationRun,
    operating_reconciliation: Mapping[str, Any],
    comps_inputs: Mapping[str, Any],
    valuation_policy: Mapping[str, Any],
    evidence: Mapping[str, Any],
    upstream_context: Mapping[str, Any],
    captured_at: str,
    approved_treatments: Sequence[Mapping[str, Any]] = (),
    component_versions: Mapping[str, str] | None = None,
) -> AnalysisSnapshot:
    """Freeze one ticker's reconciled deterministic inputs for all providers."""

    ticker = str(valuation_inputs.ticker).strip().upper()
    if not ticker:
        raise ValueError("valuation inputs require ticker")
    as_of_date = (
        valuation_inputs.as_of_date
        or str(captured_at).split("T", 1)[0]
    )
    claim_ledger = _jsonable(valuation_inputs.claim_ledger)
    reconciliation = (
        claim_ledger.get("reconciliation")
        if isinstance(claim_ledger, dict)
        else None
    )
    if not isinstance(reconciliation, dict) or not reconciliation.get(
        "is_reconciled"
    ):
        raise ValueError("a reconciled claim ledger is required")

    (
        statement_facts,
        statement_readiness,
        statement_run_hash,
        fact_ids,
        consolidated_statement_view,
    ) = _authoritative_statement_evidence(
        conn=conn,
        ticker=ticker,
        as_of_date=as_of_date,
        reconciliation_run=statement_reconciliation_run,
    )
    statement_source_fingerprints, _ = (
        _statement_source_fingerprints(
            ticker=ticker,
            statement_facts=statement_facts,
        )
    )
    operating_payload = _jsonable(operating_reconciliation)
    operating_fingerprint = str(
        operating_payload.get("fingerprint") or ""
    ).strip()
    if not operating_fingerprint:
        raise ValueError(
            "operating reconciliation requires a stable fingerprint"
        )

    comps_payload = _jsonable(comps_inputs)
    policy_payload = _jsonable(valuation_policy)
    evidence_payload = _jsonable(evidence)
    wacc_payload = _jsonable(valuation_inputs.wacc_inputs)
    treatments_payload = tuple(
        _jsonable(treatment) for treatment in approved_treatments
    )
    source_fingerprints = {
        **statement_source_fingerprints,
        "claim_ledger": str(claim_ledger.get("fingerprint") or "").strip()
        or canonical_semantic_hash(claim_ledger),
        "operating_reconciliation": operating_fingerprint,
        "comps": canonical_semantic_hash(comps_payload),
        "valuation_policy": canonical_semantic_hash(policy_payload),
        "evidence": canonical_semantic_hash(evidence_payload),
        "wacc": canonical_semantic_hash(wacc_payload),
        "market_inputs": canonical_semantic_hash(
            {
                "current_price": valuation_inputs.current_price,
                "as_of_date": valuation_inputs.as_of_date,
                "source_lineage": valuation_inputs.source_lineage,
            }
        ),
        "approved_treatments": canonical_semantic_hash(treatments_payload),
        "statement_reconciliation_run": statement_run_hash,
    }
    versions = {
        "analysis_snapshot_builder": ANALYSIS_SNAPSHOT_BUILDER_VERSION,
        "analysis_snapshot_contract": ANALYSIS_SNAPSHOT_CONTRACT_VERSION,
        "statement_reconciliation": "1.0.0",
        "claim_ledger": "1.0.0",
        "operating_reconciliation": "1.0.0",
        **{
            str(key): str(value)
            for key, value in dict(component_versions or {}).items()
        },
    }
    readiness_payload = {
        **_jsonable(statement_readiness),
        "reconciliation_run_hash": statement_run_hash,
        "selected_fact_ids": fact_ids,
    }
    statements = {
        "annual_period_count": statement_readiness.annual_period_count,
        "ltm_status": statement_readiness.ltm_status,
        "fact_ids": fact_ids,
        "consolidated_view": consolidated_statement_view,
    }
    market_inputs = {
        "current_price": float(valuation_inputs.current_price),
        "as_of_date": valuation_inputs.as_of_date,
        "model_applicability_status": (
            valuation_inputs.model_applicability_status
        ),
        "base_drivers": _jsonable(valuation_inputs.drivers),
        "source_lineage": _jsonable(valuation_inputs.source_lineage),
        "ciq_lineage": _jsonable(valuation_inputs.ciq_lineage),
        "operating_cash_policy": _jsonable(
            valuation_inputs.operating_cash_policy
        ),
        "operating_reconciliation": operating_payload,
        "valuation_policy": policy_payload,
    }
    return AnalysisSnapshot.model_validate(
        {
            "ticker": ticker,
            "as_of_date": as_of_date,
            "identity": {
                "company_name": valuation_inputs.company_name,
                "sector": valuation_inputs.sector,
                "industry": valuation_inputs.industry,
            },
            "statements": statements,
            "statement_reconciliation": readiness_payload,
            "claim_ledger": claim_ledger,
            "market_inputs": market_inputs,
            "wacc_inputs": wacc_payload,
            "comps_inputs": comps_payload,
            "approved_treatments": treatments_payload,
            "evidence": evidence_payload,
            "upstream_context": _jsonable(upstream_context),
            "source_fingerprints": source_fingerprints,
            "component_versions": versions,
            "captured_at": captured_at,
        }
    )


__all__ = [
    "ANALYSIS_SNAPSHOT_BUILDER_VERSION",
    "build_valuation_analysis_snapshot",
]
