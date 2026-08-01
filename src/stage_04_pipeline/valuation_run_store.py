"""SQLite persistence for frozen judgment inputs, runs, and approved replay."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import sqlite3
import time
from typing import Any, Mapping

from db.loader import load_statement_facts
from src.contracts.analysis_snapshot import AnalysisSnapshot
from src.contracts.assumption_registry import DriverFamily
from src.contracts.driver_families import (
    DriverFamilyCritique,
    DriverFamilyProposal,
)
from src.contracts.judgment_runs import (
    AgentRunEnvelope,
    AgentRunStatus,
    canonical_semantic_hash,
)
from src.contracts.model_change_requests import (
    ModelChangeStatus,
    ValuationModelChangeRequest,
    decide_model_change_request,
)
from src.contracts.pm_decision_queue import AssumptionChangePack
from src.stage_02_valuation.approved_case_replay import (
    SCENARIO_NAMES,
    ApprovedValuationCase,
    ApprovedValuationReplayResult,
    FrozenScenarioDrivers,
    compile_approved_valuation_case,
    replay_approved_valuation_case,
)
from src.stage_02_valuation.valuation_types import ForecastDrivers
from src.stage_04_pipeline.driver_family_queue import (
    driver_family_proposal_from_queue_pack,
)
from src.stage_04_pipeline.statement_reconciliation_service import (
    _RECONCILIATION_CONTRACT_VERSION,
    _fact_identity_payload,
    _facts_as_of,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _required_text(value: str, field_name: str) -> str:
    cleaned = str(value).strip()
    if not cleaned:
        raise ValueError(f"{field_name} is required")
    return cleaned


def _payload_hash(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _row_value(
    row: sqlite3.Row | tuple[Any, ...],
    index: int,
    name: str,
) -> Any:
    if isinstance(row, sqlite3.Row):
        return row[name]
    return row[index]


def _persist_artifact_integrity(
    conn: sqlite3.Connection,
    *,
    artifact_type: str,
    artifact_key: str,
    payload_hash: str,
) -> None:
    existing = conn.execute(
        """
        SELECT payload_hash
        FROM valuation_artifact_integrity
        WHERE artifact_type = ? AND artifact_key = ?
        """,
        (artifact_type, artifact_key),
    ).fetchone()
    if existing is not None:
        stored_hash = _row_value(existing, 0, "payload_hash")
        if stored_hash != payload_hash:
            raise ValueError(
                f"{artifact_type} integrity identity has divergent payloads"
            )
        return
    conn.execute(
        """
        INSERT INTO valuation_artifact_integrity (
            artifact_type, artifact_key, payload_hash, created_at
        ) VALUES (?, ?, ?, ?)
        """,
        (artifact_type, artifact_key, payload_hash, _now()),
    )


def _verify_artifact_integrity(
    conn: sqlite3.Connection,
    *,
    artifact_type: str,
    artifact_key: str,
    payload: str,
) -> None:
    row = conn.execute(
        """
        SELECT payload_hash
        FROM valuation_artifact_integrity
        WHERE artifact_type = ? AND artifact_key = ?
        """,
        (artifact_type, artifact_key),
    ).fetchone()
    if row is None:
        raise ValueError(
            f"{artifact_type} is missing its persisted integrity record"
        )
    stored_hash = _row_value(row, 0, "payload_hash")
    if stored_hash != _payload_hash(payload):
        raise ValueError(f"{artifact_type} failed persisted integrity check")


def reserve_judgment_invocation(
    conn: sqlite3.Connection,
    *,
    invocation_hash: str,
    owner_run_id: str,
    lease_seconds: float = 900.0,
    now_epoch: float | None = None,
) -> bool:
    """Atomically acquire or replace an expired cross-process execution lease."""

    key = _required_text(invocation_hash, "invocation_hash")
    owner = _required_text(owner_run_id, "owner_run_id")
    lease = float(lease_seconds)
    if lease <= 0:
        raise ValueError("lease_seconds must be positive")
    reserved_at = float(time.time() if now_epoch is None else now_epoch)
    expires_at = reserved_at + lease
    with conn:
        cursor = conn.execute(
            """
            INSERT INTO judgment_invocation_reservations (
                invocation_hash, owner_run_id, reserved_at_epoch,
                lease_expires_at_epoch
            ) VALUES (?, ?, ?, ?)
            ON CONFLICT(invocation_hash) DO UPDATE SET
                owner_run_id = excluded.owner_run_id,
                reserved_at_epoch = excluded.reserved_at_epoch,
                lease_expires_at_epoch = excluded.lease_expires_at_epoch
            WHERE judgment_invocation_reservations.lease_expires_at_epoch
                  <= excluded.reserved_at_epoch
            """,
            (key, owner, reserved_at, expires_at),
        )
    return cursor.rowcount == 1


def release_judgment_invocation(
    conn: sqlite3.Connection,
    *,
    invocation_hash: str,
    owner_run_id: str,
) -> bool:
    """Release only the caller's lease; a stale owner cannot release a successor."""

    key = _required_text(invocation_hash, "invocation_hash")
    owner = _required_text(owner_run_id, "owner_run_id")
    with conn:
        cursor = conn.execute(
            """
            DELETE FROM judgment_invocation_reservations
            WHERE invocation_hash = ? AND owner_run_id = ?
            """,
            (key, owner),
        )
    return cursor.rowcount == 1


_STATEMENT_SNAPSHOT_FIELDS = (
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


def _statement_snapshot_projection(
    fact: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        field_name: fact.get(field_name)
        for field_name in _STATEMENT_SNAPSHOT_FIELDS
    }


def _validate_snapshot_statement_provenance(
    conn: sqlite3.Connection,
    snapshot: AnalysisSnapshot,
) -> None:
    reconciliation = dict(snapshot.statement_reconciliation)
    run_hash = str(
        reconciliation.pop("reconciliation_run_hash", "")
    ).strip()
    selected_from_reconciliation = tuple(
        sorted(
            str(value)
            for value in reconciliation.pop("selected_fact_ids", ())
        )
    )
    selected_from_statements = tuple(
        sorted(
            str(value)
            for value in snapshot.statements.get("fact_ids", ())
        )
    )
    if not run_hash or not selected_from_reconciliation:
        raise ValueError(
            "analysis snapshot requires persisted statement reconciliation "
            "run provenance"
        )
    if selected_from_reconciliation != selected_from_statements:
        raise ValueError(
            "analysis snapshot selected statement fact IDs are inconsistent"
        )
    if (
        snapshot.source_fingerprints.get(
            "statement_reconciliation_run"
        )
        != run_hash
    ):
        raise ValueError(
            "analysis snapshot reconciliation run fingerprint changed"
        )

    row = conn.execute(
        """
        SELECT ticker, as_of_date, facts_fingerprint,
               selected_fact_ids_json, readiness_json, readiness_hash,
               manifest_ids_json, selected_view_hash, raw_ledger_hash,
               status
        FROM valuation_statement_reconciliation_runs
        WHERE run_hash = ?
        """,
        (run_hash,),
    ).fetchone()
    if row is None:
        raise ValueError(
            "analysis snapshot statement reconciliation run is not persisted"
        )
    names = (
        "ticker",
        "as_of_date",
        "facts_fingerprint",
        "selected_fact_ids_json",
        "readiness_json",
        "readiness_hash",
        "manifest_ids_json",
        "selected_view_hash",
        "raw_ledger_hash",
        "status",
    )
    stored = {
        name: _row_value(row, index, name)
        for index, name in enumerate(names)
    }
    readiness_json = _canonical_json(reconciliation)
    readiness_hash = canonical_semantic_hash(reconciliation)
    selected_ids = tuple(
        sorted(json.loads(str(stored["selected_fact_ids_json"])))
    )
    manifest_ids = tuple(
        sorted(json.loads(str(stored["manifest_ids_json"])))
    )
    identity = {
        "ticker": snapshot.ticker,
        "as_of_date": snapshot.as_of_date,
        "facts_fingerprint": str(stored["facts_fingerprint"]),
        "selected_fact_ids": selected_ids,
        "readiness_hash": readiness_hash,
        "manifest_ids": manifest_ids,
        "selected_view_hash": str(stored["selected_view_hash"]),
        "raw_ledger_hash": str(stored["raw_ledger_hash"]),
        "status": str(stored["status"]),
    }
    if canonical_semantic_hash(identity) != run_hash:
        raise ValueError(
            "analysis snapshot statement reconciliation run hash is invalid"
        )
    consolidated_view = snapshot.statements.get("consolidated_view")
    persisted_facts = load_statement_facts(conn, snapshot.ticker)
    raw_facts = tuple(
        _facts_as_of(persisted_facts, snapshot.as_of_date)
    )
    computed_raw_ledger_hash = canonical_semantic_hash(
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
    facts_by_id = {
        str(fact.get("fact_id") or ""): fact
        for fact in persisted_facts
    }
    if not set(facts_by_id).issuperset(selected_ids):
        raise ValueError(
            "analysis snapshot references missing authoritative statement facts"
        )
    selected_facts = sorted(
        (facts_by_id[fact_id] for fact_id in selected_ids),
        key=lambda fact: (
            str(fact.get("source") or ""),
            str(fact.get("statement") or ""),
            str(fact.get("period_end") or ""),
            str(fact.get("period_start") or ""),
            str(fact.get("fact_id") or ""),
        ),
    )
    expected_selected_view_hash = canonical_semantic_hash(
        {
            "contract_version": _RECONCILIATION_CONTRACT_VERSION,
            "ticker": snapshot.ticker,
            "as_of_date": snapshot.as_of_date,
            "manifest_ids": manifest_ids,
            "facts": [
                _fact_identity_payload(fact)
                for fact in selected_facts
            ],
        }
    )
    expected_consolidated_view = [
        _statement_snapshot_projection(fact)
        for fact in selected_facts
    ]
    if (
        str(stored["ticker"]) != snapshot.ticker
        or str(stored["as_of_date"]) != snapshot.as_of_date
        or selected_ids != selected_from_statements
        or str(stored["readiness_json"]) != readiness_json
        or str(stored["readiness_hash"]) != readiness_hash
        or str(stored["raw_ledger_hash"])
        != computed_raw_ledger_hash
        or str(stored["facts_fingerprint"])
        != computed_raw_ledger_hash
        or str(stored["selected_view_hash"])
        != expected_selected_view_hash
        or consolidated_view != expected_consolidated_view
        or str(stored["status"])
        != str(reconciliation.get("status") or "")
        or not manifest_ids
    ):
        raise ValueError(
            "analysis snapshot statement reconciliation run does not match "
            "its indexed evidence"
        )

    fact_sources: set[str] = set()
    for fact in selected_facts:
        fact_sources.add(str(fact.get("source") or ""))
        for name in ("period_end", "filing_date"):
            value = str(fact.get(name) or "")
            if value and value > snapshot.as_of_date:
                raise ValueError(
                    "analysis snapshot contains post-as-of statement evidence"
                )

    manifest_sources: set[str] = set()
    for manifest_id in manifest_ids:
        manifest = conn.execute(
            """
            SELECT ticker, source, status, evidence_cutoff,
                   payload_hash, payload_json
            FROM statement_source_manifests
            WHERE manifest_id = ?
            """,
            (manifest_id,),
        ).fetchone()
        if manifest is None:
            raise ValueError(
                "analysis snapshot references a missing source manifest"
            )
        payload = str(_row_value(manifest, 5, "payload_json"))
        if (
            str(_row_value(manifest, 0, "ticker")) != snapshot.ticker
            or str(_row_value(manifest, 2, "status")) != "completed"
            or str(_row_value(manifest, 3, "evidence_cutoff"))
            > snapshot.as_of_date
            or str(_row_value(manifest, 4, "payload_hash"))
            != _payload_hash(payload)
        ):
            raise ValueError(
                "analysis snapshot source manifest integrity is invalid"
            )
        manifest_sources.add(str(_row_value(manifest, 1, "source")))
    has_xbrl_manifest = any(
        source.lower().startswith("sec_xbrl_filing_presentation")
        or source.lower() == "sec_filing_xbrl"
        for source in manifest_sources
    )
    uncovered_sources = {
        source
        for source in fact_sources
        if source not in manifest_sources
        and not (
            source.lower().startswith("sec_xbrl_derived_ltm")
            and has_xbrl_manifest
        )
    }
    if uncovered_sources:
        raise ValueError(
            "analysis snapshot facts are not covered by source manifests"
        )


def _insert_immutable(
    conn: sqlite3.Connection,
    *,
    table: str,
    key_column: str,
    key_value: str,
    payload_column: str,
    payload_json: str,
    insert_sql: str,
    insert_values: tuple[Any, ...],
) -> None:
    existing = conn.execute(
        f"SELECT {payload_column} FROM {table} WHERE {key_column} = ?",
        (key_value,),
    ).fetchone()
    if existing is not None:
        existing_payload = existing[0]
        if existing_payload != payload_json:
            raise ValueError(
                f"immutable {table} identity {key_value!r} has divergent payloads"
            )
        return
    conn.execute(insert_sql, insert_values)


def persist_analysis_snapshot(
    conn: sqlite3.Connection,
    snapshot: AnalysisSnapshot,
) -> str:
    _validate_snapshot_statement_provenance(conn, snapshot)
    payload = _canonical_json(
        snapshot.model_dump(mode="json", exclude_computed_fields=True)
    )
    persisted_payload = payload
    with conn:
        existing = conn.execute(
            """
            SELECT payload_json
            FROM analysis_snapshots
            WHERE snapshot_hash = ?
            """,
            (snapshot.snapshot_hash,),
        ).fetchone()
        if existing is None:
            conn.execute(
                """
                INSERT INTO analysis_snapshots (
                    snapshot_hash, ticker, as_of_date, payload_json,
                    captured_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.snapshot_hash,
                    snapshot.ticker,
                    snapshot.as_of_date,
                    payload,
                    snapshot.captured_at,
                    _now(),
                ),
            )
        else:
            persisted_payload = str(existing[0])
            _verify_artifact_integrity(
                conn,
                artifact_type="analysis_snapshot",
                artifact_key=snapshot.snapshot_hash,
                payload=persisted_payload,
            )
            stored = AnalysisSnapshot.model_validate_json(persisted_payload)
            if stored.semantic_payload() != snapshot.semantic_payload():
                raise ValueError(
                    "analysis snapshot hash has divergent semantic payloads"
                )
        _persist_artifact_integrity(
            conn,
            artifact_type="analysis_snapshot",
            artifact_key=snapshot.snapshot_hash,
            payload_hash=_payload_hash(persisted_payload),
        )
    return snapshot.snapshot_hash


def load_analysis_snapshot(
    conn: sqlite3.Connection,
    snapshot_hash: str,
) -> AnalysisSnapshot | None:
    row = conn.execute(
        """
        SELECT snapshot_hash, ticker, as_of_date, payload_json, captured_at
        FROM analysis_snapshots
        WHERE snapshot_hash = ?
        """,
        (snapshot_hash,),
    ).fetchone()
    if row is None:
        return None
    stored_hash = str(_row_value(row, 0, "snapshot_hash"))
    ticker = str(_row_value(row, 1, "ticker"))
    as_of_date = str(_row_value(row, 2, "as_of_date"))
    payload = str(_row_value(row, 3, "payload_json"))
    captured_at = str(_row_value(row, 4, "captured_at"))
    _verify_artifact_integrity(
        conn,
        artifact_type="analysis_snapshot",
        artifact_key=stored_hash,
        payload=payload,
    )
    snapshot = AnalysisSnapshot.model_validate_json(payload)
    if (
        stored_hash != snapshot_hash
        or snapshot.snapshot_hash != stored_hash
        or snapshot.ticker != ticker
        or snapshot.as_of_date != as_of_date
        or snapshot.captured_at != captured_at
    ):
        raise ValueError(
            "analysis snapshot indexed columns do not match its payload"
        )
    _validate_snapshot_statement_provenance(conn, snapshot)
    return snapshot


def persist_agent_run_envelope(
    conn: sqlite3.Connection,
    envelope: AgentRunEnvelope,
) -> str:
    snapshot = load_analysis_snapshot(
        conn,
        envelope.task.frozen_snapshot_hash,
    )
    if snapshot is None:
        raise ValueError(
            "judgment run analysis snapshot is not persisted"
        )
    if snapshot.ticker != envelope.task.ticker:
        raise ValueError(
            "judgment run ticker does not match its analysis snapshot"
        )
    if (
        envelope.status.value == "succeeded"
        and not str(
            envelope.attempts[-1].trace.actual_model or ""
        ).strip()
    ):
        raise ValueError(
            "successful judgment runs require a nonblank actual_model"
        )
    payload = _canonical_json(
        envelope.model_dump(mode="json", exclude_computed_fields=True)
    )
    created_at = envelope.attempts[0].trace.started_at.isoformat()
    with conn:
        _insert_immutable(
            conn,
            table="judgment_run_envelopes",
            key_column="run_id",
            key_value=envelope.run_id,
            payload_column="payload_json",
            payload_json=payload,
            insert_sql="""
                INSERT INTO judgment_run_envelopes (
                    run_id, idempotency_key, semantic_task_hash,
                    invocation_hash, snapshot_hash, ticker, family, role,
                    provider, requested_model, status, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            insert_values=(
                envelope.run_id,
                envelope.idempotency_key,
                envelope.semantic_task_hash,
                envelope.invocation_hash,
                envelope.task.frozen_snapshot_hash,
                envelope.task.ticker,
                envelope.task.family,
                envelope.task.role,
                envelope.route.provider,
                envelope.route.requested_model,
                envelope.status.value,
                payload,
                created_at,
            ),
        )
        _persist_artifact_integrity(
            conn,
            artifact_type="judgment_run_envelope",
            artifact_key=envelope.run_id,
            payload_hash=_payload_hash(payload),
        )
    return envelope.run_id


def _envelope_from_row(
    conn: sqlite3.Connection,
    row: sqlite3.Row | tuple[Any, ...],
) -> AgentRunEnvelope:
    column_names = (
        "run_id",
        "idempotency_key",
        "semantic_task_hash",
        "invocation_hash",
        "snapshot_hash",
        "ticker",
        "family",
        "role",
        "provider",
        "requested_model",
        "status",
        "payload_json",
    )
    values = {
        name: _row_value(row, index, name)
        for index, name in enumerate(column_names)
    }
    payload = str(values["payload_json"])
    run_id = str(values["run_id"])
    _verify_artifact_integrity(
        conn,
        artifact_type="judgment_run_envelope",
        artifact_key=run_id,
        payload=payload,
    )
    envelope = AgentRunEnvelope.model_validate_json(payload)
    expected = {
        "run_id": envelope.run_id,
        "idempotency_key": envelope.idempotency_key,
        "semantic_task_hash": envelope.semantic_task_hash,
        "invocation_hash": envelope.invocation_hash,
        "snapshot_hash": envelope.task.frozen_snapshot_hash,
        "ticker": envelope.task.ticker,
        "family": envelope.task.family,
        "role": envelope.task.role,
        "provider": envelope.route.provider,
        "requested_model": envelope.route.requested_model,
        "status": envelope.status.value,
    }
    if any(str(values[name]) != str(value) for name, value in expected.items()):
        raise ValueError(
            "judgment run indexed columns do not match its payload"
        )
    if (
        envelope.status.value == "succeeded"
        and not str(
            envelope.attempts[-1].trace.actual_model or ""
        ).strip()
    ):
        raise ValueError(
            "successful judgment run has blank actual_model"
        )
    snapshot = load_analysis_snapshot(
        conn,
        envelope.task.frozen_snapshot_hash,
    )
    if snapshot is None or snapshot.ticker != envelope.task.ticker:
        raise ValueError(
            "judgment run analysis snapshot provenance is invalid"
        )
    return envelope


def load_agent_run_envelope(
    conn: sqlite3.Connection,
    run_id: str,
) -> AgentRunEnvelope | None:
    row = conn.execute(
        """
        SELECT run_id, idempotency_key, semantic_task_hash, invocation_hash,
               snapshot_hash, ticker, family, role, provider, requested_model,
               status, payload_json
        FROM judgment_run_envelopes
        WHERE run_id = ?
        """,
        (run_id,),
    ).fetchone()
    if row is None:
        return None
    envelope = _envelope_from_row(conn, row)
    if envelope.run_id != run_id:
        raise ValueError("judgment run identity does not match lookup key")
    return envelope


def load_cached_successful_envelope(
    conn: sqlite3.Connection,
    idempotency_key: str,
) -> AgentRunEnvelope | None:
    row = conn.execute(
        """
        SELECT run_id, idempotency_key, semantic_task_hash, invocation_hash,
               snapshot_hash, ticker, family, role, provider, requested_model,
               status, payload_json
        FROM judgment_run_envelopes
        WHERE idempotency_key = ? AND status = 'succeeded'
        ORDER BY created_at DESC, run_id DESC
        LIMIT 1
        """,
        (idempotency_key,),
    ).fetchone()
    if row is None:
        return None
    envelope = _envelope_from_row(conn, row)
    if envelope.idempotency_key != idempotency_key:
        raise ValueError(
            "cached judgment run identity does not match lookup key"
        )
    return envelope


def _case_payload(case: ApprovedValuationCase) -> dict[str, Any]:
    return asdict(case)


def _case_from_payload(payload: dict[str, Any]) -> ApprovedValuationCase:
    return ApprovedValuationCase(
        **{
            **payload,
            "approved_pack_hashes": tuple(payload["approved_pack_hashes"]),
            "approval_fingerprints": tuple(
                payload["approval_fingerprints"]
            ),
            "approved_treatment_hashes": tuple(
                payload["approved_treatment_hashes"]
            ),
            "scenario_drivers": tuple(
                FrozenScenarioDrivers(**item)
                for item in payload["scenario_drivers"]
            ),
        }
    )


def _approved_case_replay_key(case: ApprovedValuationCase) -> str:
    identity_payload = {
        "ticker": case.ticker,
        "analysis_snapshot_hash": case.analysis_snapshot_hash,
        "approved_pack_hashes": case.approved_pack_hashes,
        "approval_fingerprints": case.approval_fingerprints,
        "approved_treatment_hashes": case.approved_treatment_hashes,
        "scenario_drivers": [
            {
                "scenario": frozen.scenario,
                "payload": json.loads(frozen.payload_json),
            }
            for frozen in case.scenario_drivers
        ],
        "frozen_comps": json.loads(case.frozen_comps_json),
        "similarity_scores": json.loads(case.similarity_scores_json),
        "valuation_policy": json.loads(case.valuation_policy_json),
        "engine_fingerprint": case.engine_fingerprint,
        "readiness": json.loads(case.readiness_json),
        "readiness_fingerprint": case.readiness_fingerprint,
    }
    return canonical_semantic_hash(identity_payload)


def _validate_approved_case_structure(case: ApprovedValuationCase) -> None:
    scenario_names = tuple(
        frozen.scenario for frozen in case.scenario_drivers
    )
    if scenario_names != SCENARIO_NAMES:
        raise ValueError(
            "approved replay requires exactly low, base, and high scenarios"
        )
    if (
        len(case.approved_pack_hashes) != len(DriverFamily)
        or any(
            not str(pack_hash).strip()
            for pack_hash in case.approved_pack_hashes
        )
        or
        len(case.approval_fingerprints) != len(DriverFamily)
        or any(
            not str(fingerprint).strip()
            for fingerprint in case.approval_fingerprints
        )
    ):
        raise ValueError(
            "approved replay requires one approval fingerprint per "
            "driver family"
        )
    for frozen in case.scenario_drivers:
        frozen.thaw()
    readiness = case.readiness()
    readiness.require_decision_grade()
    if case.readiness_fingerprint != readiness.readiness_fingerprint:
        raise ValueError(
            "approved case readiness fingerprint does not match readiness payload"
        )


def _approval_run_identity(
    envelope: AgentRunEnvelope,
    *,
    run_role: str,
) -> dict[str, Any]:
    trace = envelope.attempts[-1].trace
    return {
        "run_role": run_role,
        "run_id": envelope.run_id,
        "semantic_task_hash": envelope.semantic_task_hash,
        "invocation_hash": envelope.invocation_hash,
        "prompt_hash": envelope.task.prompt_hash,
        "schema_hash": envelope.task.schema_hash,
        "compiler_hash": envelope.task.compiler_hash,
        "provider": envelope.route.provider,
        "adapter_id": envelope.route.adapter_id,
        "adapter_version": envelope.route.adapter_version,
        "requested_model": envelope.route.requested_model,
        "actual_model": trace.actual_model,
        "validated_payload_hash": canonical_semantic_hash(
            envelope.validated_payload
        ),
    }


def _prompt_contract_identity(
    envelope: AgentRunEnvelope,
    *,
    run_role: str,
) -> dict[str, Any]:
    task = envelope.task
    return {
        "family": task.family,
        "run_role": run_role,
        "semantic_task_hash": envelope.semantic_task_hash,
        "task_version": task.task_version,
        "prompt_id": task.prompt_id,
        "prompt_hash": task.prompt_hash,
        "schema_id": task.schema_id,
        "schema_hash": task.schema_hash,
        "compiler_id": task.compiler_id,
        "compiler_hash": task.compiler_hash,
        "reviewed_output_hash": task.reviewed_output_hash,
    }


def _validated_approval_event(
    conn: sqlite3.Connection,
    *,
    item_id: int,
    ticker: str,
    approved_pack: dict[str, Any],
    approval_fingerprint: str,
) -> None:
    rows = conn.execute(
        """
        SELECT ticker, payload_json
        FROM pm_decision_queue_events
        WHERE item_id = ? AND event_type = 'approve'
        ORDER BY id
        """,
        (item_id,),
    ).fetchall()
    for row in rows:
        event_ticker = str(_row_value(row, 0, "ticker"))
        payload = json.loads(str(_row_value(row, 1, "payload_json")))
        if (
            event_ticker == ticker
            and payload.get("approval_fingerprint")
            == approval_fingerprint
            and payload.get("approved_proposal_pack")
            == approved_pack
        ):
            return
    raise ValueError(
        "approved driver-family pack is missing its matching approval event"
    )


def _validated_family_approval(
    conn: sqlite3.Connection,
    *,
    snapshot: AnalysisSnapshot,
    item_id: int,
    row_ticker: str,
    pack: AssumptionChangePack,
    adapter_links_json: str,
    decision_history_json: str,
) -> tuple[
    DriverFamilyProposal,
    str,
    tuple[dict[str, Any], ...],
]:
    if pack.family is None:
        raise ValueError("approved driver-family pack has no family")
    if (
        row_ticker != snapshot.ticker
        or pack.analysis_snapshot_hash != snapshot.snapshot_hash
        or pack.critic_verdict != "accept"
    ):
        raise ValueError("approved driver-family pack identity changed")
    proposal = driver_family_proposal_from_queue_pack(pack)
    proposal_anchors = {
        anchor
        for assumption in proposal.assumptions
        for anchor in assumption.evidence_anchor_ids
    }
    unknown_anchors = sorted(proposal_anchors - set(snapshot.evidence))
    if unknown_anchors:
        raise ValueError(
            "approved driver-family evidence anchors are not in the "
            "persisted snapshot: "
            + ", ".join(unknown_anchors)
        )

    envelope_identities: list[dict[str, Any]] = []
    prompt_identities: list[dict[str, Any]] = []
    for run_role, run_id, allowed_roles in (
        ("primary", pack.primary_run_id, {"primary", "revision"}),
        ("critic", pack.critic_run_id, {"critic"}),
    ):
        envelope = load_agent_run_envelope(conn, str(run_id or ""))
        if envelope is None:
            raise ValueError(
                f"approved driver-family {run_role} run is missing"
            )
        task = envelope.task
        if (
            envelope.status != AgentRunStatus.succeeded
            or task.ticker != snapshot.ticker
            or task.family != pack.family.value
            or task.frozen_snapshot_hash != snapshot.snapshot_hash
            or task.role not in allowed_roles
        ):
            raise ValueError(
                f"approved driver-family {run_role} run identity changed"
            )
        if run_role == "critic":
            critique = DriverFamilyCritique.model_validate(
                envelope.validated_payload
            )
            if (
                critique.family != pack.family
                or critique.verdict != "accept"
            ):
                raise ValueError(
                    "approved driver-family critic no longer accepts the pack"
                )
        envelope_identities.append(
            _approval_run_identity(envelope, run_role=run_role)
        )
        prompt_identities.append(
            _prompt_contract_identity(envelope, run_role=run_role)
        )

    approval_identity = {
        "ticker": snapshot.ticker,
        "analysis_snapshot_hash": snapshot.snapshot_hash,
        "source_fingerprints": snapshot.source_fingerprints,
        "component_versions": snapshot.component_versions,
        "statement_reconciliation": snapshot.statement_reconciliation,
        "claim_ledger": snapshot.claim_ledger,
        "operating_reconciliation": snapshot.market_inputs.get(
            "operating_reconciliation"
        ),
        "peer_set": snapshot.comps_inputs,
        "approved_treatments": snapshot.approved_treatments,
        "proposal_pack": pack.model_dump(mode="json"),
        "run_envelopes": envelope_identities,
    }
    expected_approval_fingerprint = canonical_semantic_hash(
        approval_identity
    )
    adapter_links = json.loads(adapter_links_json)
    approval_fingerprint = str(
        adapter_links.get("approval_fingerprint") or ""
    ).strip()
    if approval_fingerprint != expected_approval_fingerprint:
        raise ValueError(
            "approved driver-family approval fingerprint changed"
        )

    approved_pack = pack.model_dump(mode="json")
    history = json.loads(decision_history_json)
    if not any(
        isinstance(event, Mapping)
        and event.get("event") == "approve"
        and event.get("approval_fingerprint") == approval_fingerprint
        and event.get("approved_proposal_pack") == approved_pack
        for event in history
    ):
        raise ValueError(
            "approved driver-family decision history changed"
        )
    _validated_approval_event(
        conn,
        item_id=item_id,
        ticker=snapshot.ticker,
        approved_pack=approved_pack,
        approval_fingerprint=approval_fingerprint,
    )
    return (
        proposal,
        approval_fingerprint,
        tuple(prompt_identities),
    )


def load_approved_family_bundle(
    conn: sqlite3.Connection,
    *,
    snapshot: AnalysisSnapshot,
) -> (
    tuple[
        tuple[DriverFamilyProposal, ...],
        tuple[str, ...],
        str,
    ]
    | None
):
    """Load the complete, validated approval bundle for an exact snapshot."""
    rows = conn.execute(
        """
        SELECT id, ticker, approved_proposal_pack_json,
               adapter_links_json, decision_history_json
        FROM pm_decision_queue_items
        WHERE ticker = ?
          AND status = 'approved'
          AND item_type = 'assumption_change_pack'
          AND approved_proposal_pack_json IS NOT NULL
        ORDER BY id
        """,
        (snapshot.ticker,),
    ).fetchall()
    by_family: dict[
        DriverFamily,
        tuple[DriverFamilyProposal, str, tuple[dict[str, Any], ...]],
    ] = {}
    for row in rows:
        pack = AssumptionChangePack.model_validate_json(
            str(_row_value(row, 2, "approved_proposal_pack_json"))
        )
        if (
            pack.analysis_snapshot_hash != snapshot.snapshot_hash
            or pack.family is None
        ):
            continue
        validated = _validated_family_approval(
            conn,
            snapshot=snapshot,
            item_id=int(_row_value(row, 0, "id")),
            row_ticker=str(_row_value(row, 1, "ticker")),
            pack=pack,
            adapter_links_json=str(
                _row_value(row, 3, "adapter_links_json")
            ),
            decision_history_json=str(
                _row_value(row, 4, "decision_history_json")
            ),
        )
        if pack.family in by_family:
            raise ValueError(
                "approved driver-family provenance requires exactly one "
                "matching approval per family"
            )
        by_family[pack.family] = validated
    if set(by_family) != set(DriverFamily):
        return None

    ordered = tuple(by_family[family] for family in DriverFamily)
    proposals = tuple(item[0] for item in ordered)
    approval_fingerprints = tuple(item[1] for item in ordered)
    prompt_identities = tuple(
        identity
        for item in ordered
        for identity in item[2]
    )
    prompt_contract_fingerprint = canonical_semantic_hash(
        {
            "contract_version": "approved_replay_prompt_contract_v1",
            "analysis_snapshot_hash": snapshot.snapshot_hash,
            "runs": prompt_identities,
        }
    )
    return (
        proposals,
        approval_fingerprints,
        prompt_contract_fingerprint,
    )


def _load_approved_family_bundle(
    conn: sqlite3.Connection,
    *,
    snapshot: AnalysisSnapshot,
    case: ApprovedValuationCase,
) -> tuple[
    tuple[DriverFamilyProposal, ...],
    tuple[str, ...],
    str,
]:
    bundle = load_approved_family_bundle(
        conn,
        snapshot=snapshot,
    )
    if bundle is None:
        raise ValueError(
            "approved driver-family provenance requires exactly one "
            "approved pack for all four families"
        )
    proposals, approval_fingerprints, _ = bundle
    expected_pack_hashes = dict(
        zip(
            DriverFamily,
            case.approved_pack_hashes,
            strict=True,
        )
    )
    expected_approval_fingerprints = dict(
        zip(
            DriverFamily,
            case.approval_fingerprints,
            strict=True,
        )
    )
    for family, proposal, approval_fingerprint in zip(
        DriverFamily,
        proposals,
        approval_fingerprints,
        strict=True,
    ):
        if (
            canonical_semantic_hash(proposal)
            != expected_pack_hashes[family]
        ):
            raise ValueError(
                "approved driver-family pack hash does not match replay case"
            )
        if (
            approval_fingerprint
            != expected_approval_fingerprints[family]
        ):
            raise ValueError(
                "approved driver-family approval fingerprint does not "
                "match replay case"
            )
    return bundle


def _is_reconciled(payload: Mapping[str, Any]) -> bool:
    status = str(payload.get("status") or "").strip().lower()
    if (
        payload.get("decision_grade") is True
        or payload.get("is_reconciled") is True
        or status
        in {
            "reconciled",
            "ready",
            "decision_grade",
            "pass",
            "passed",
        }
    ):
        return True
    nested = payload.get("reconciliation")
    return isinstance(nested, Mapping) and _is_reconciled(nested)


def _unresolved_clamp_count(operating: Mapping[str, Any]) -> int:
    explicit = operating.get("unresolved_clamp_count")
    if isinstance(explicit, int) and not isinstance(explicit, bool):
        return explicit
    events = operating.get("clamp_events") or ()
    if not isinstance(events, (list, tuple)):
        return 0
    resolved_statuses = {"accepted", "approved", "resolved"}
    return sum(
        1
        for event in events
        if isinstance(event, Mapping)
        and not event.get("resolved")
        and str(event.get("status") or "").lower()
        not in resolved_statuses
    )


def _validate_replay_readiness(
    conn: sqlite3.Connection,
    *,
    snapshot: AnalysisSnapshot,
    case: ApprovedValuationCase,
    proposals: tuple[DriverFamilyProposal, ...],
    prompt_contract_fingerprint: str,
) -> None:
    readiness = case.readiness()
    statement = snapshot.statement_reconciliation
    source_reconciliation = statement.get("source_reconciliation")
    if not isinstance(source_reconciliation, Mapping):
        source_reconciliation = statement
    claim_ledger = snapshot.claim_ledger
    operating = snapshot.market_inputs.get("operating_reconciliation")
    if not isinstance(operating, Mapping):
        raise ValueError(
            "approved replay snapshot lacks operating reconciliation"
        )
    if not all(
        (
            _is_reconciled(statement),
            _is_reconciled(source_reconciliation),
            _is_reconciled(claim_ledger),
            _is_reconciled(operating),
        )
    ):
        raise ValueError(
            "approved replay snapshot is not fully reconciled"
        )

    annual_period_count = snapshot.statements.get(
        "annual_period_count",
        snapshot.statements.get("annual_periods", 0),
    )
    if int(annual_period_count) != readiness.annual_period_count:
        raise ValueError(
            "approved replay annual history readiness changed"
        )
    snapshot_ltm_status = str(
        snapshot.statements.get("ltm_status") or ""
    ).lower()
    if (
        readiness.ltm_status.value == "compatible"
        and snapshot_ltm_status
        not in {
            "compatible",
            "constructed",
            "reported",
            "source_provided",
        }
    ):
        raise ValueError("approved replay LTM readiness changed")

    source_fingerprints = snapshot.source_fingerprints
    expected_fingerprints = {
        "statement_reconciliation_hash": canonical_semantic_hash(
            statement
        ),
        "source_reconciliation_hash": canonical_semantic_hash(
            source_fingerprints
        ),
        "claim_ledger_hash": source_fingerprints.get("claim_ledger"),
        "operating_reconciliation_hash": source_fingerprints.get(
            "operating_reconciliation"
        ),
        "peer_set_fingerprint": canonical_semantic_hash(
            snapshot.comps_inputs
        ),
        "prompt_contract_fingerprint": prompt_contract_fingerprint,
    }
    for field_name, expected in expected_fingerprints.items():
        if not expected or getattr(readiness, field_name) != expected:
            raise ValueError(
                f"approved replay {field_name} changed"
            )

    if (
        source_fingerprints.get("claim_ledger")
        != str(
            claim_ledger.get("fingerprint")
            or canonical_semantic_hash(claim_ledger)
        )
        or source_fingerprints.get("operating_reconciliation")
        != str(
            operating.get("fingerprint")
            or canonical_semantic_hash(operating)
        )
        or source_fingerprints.get("comps")
        != canonical_semantic_hash(snapshot.comps_inputs)
        or source_fingerprints.get("approved_treatments")
        != canonical_semantic_hash(snapshot.approved_treatments)
        or source_fingerprints.get("evidence")
        != canonical_semantic_hash(snapshot.evidence)
    ):
        raise ValueError(
            "approved replay snapshot component fingerprint changed"
        )

    treatment_hashes = tuple(
        sorted(
            canonical_semantic_hash(treatment)
            for treatment in snapshot.approved_treatments
        )
    )
    if (
        case.approved_treatment_hashes != treatment_hashes
        or readiness.treatment_set_fingerprint
        != canonical_semantic_hash(list(treatment_hashes))
    ):
        raise ValueError(
            "approved replay treatment fingerprint changed"
        )

    pack_hashes = tuple(
        canonical_semantic_hash(proposal)
        for proposal in proposals
    )
    pack_hashes_by_family = {
        proposal.family: pack_hash
        for proposal, pack_hash in zip(
            proposals,
            pack_hashes,
            strict=True,
        )
    }
    if (
        case.approved_pack_hashes != pack_hashes
        or readiness.approved_family_hashes
        != pack_hashes_by_family
    ):
        raise ValueError(
            "approved replay family-pack fingerprint changed"
        )

    engine_fields = (
        "dcf_engine_fingerprint",
        "comps_engine_fingerprint",
        "bridge_engine_fingerprint",
    )
    for field_name in engine_fields:
        expected = snapshot.component_versions.get(field_name)
        if not expected or getattr(readiness, field_name) != expected:
            raise ValueError(
                f"approved replay {field_name} changed"
            )
    expected_engine_fingerprint = canonical_semantic_hash(
        {
            "dcf": readiness.dcf_engine_fingerprint,
            "comps": readiness.comps_engine_fingerprint,
            "bridge": readiness.bridge_engine_fingerprint,
        }
    )
    if case.engine_fingerprint != expected_engine_fingerprint:
        raise ValueError(
            "approved replay valuation engine fingerprint changed"
        )

    pending_model_changes = conn.execute(
        """
        SELECT COUNT(*)
        FROM valuation_model_change_requests
        WHERE ticker = ?
          AND analysis_snapshot_hash = ?
          AND status = 'pending'
        """,
        (snapshot.ticker, snapshot.snapshot_hash),
    ).fetchone()
    pending_count = int(
        _row_value(pending_model_changes, 0, "COUNT(*)")
    )
    material_disagreement_count = int(
        statement.get("pending_material_disagreement_count") or 0
    )
    if (
        readiness.unresolved_clamp_count
        != _unresolved_clamp_count(operating)
        or readiness.pending_material_disagreement_count
        != material_disagreement_count
        or readiness.pending_model_change_count != pending_count
    ):
        raise ValueError(
            "approved replay unresolved readiness counts changed"
        )


def _validate_approved_case_provenance(
    conn: sqlite3.Connection,
    case: ApprovedValuationCase,
) -> None:
    snapshot = load_analysis_snapshot(
        conn,
        case.analysis_snapshot_hash,
    )
    if snapshot is None:
        raise ValueError(
            "approved replay analysis snapshot is not persisted"
        )
    if snapshot.ticker != case.ticker:
        raise ValueError(
            "approved replay analysis snapshot ticker changed"
        )
    (
        proposals,
        approval_fingerprints,
        prompt_contract_fingerprint,
    ) = _load_approved_family_bundle(
        conn,
        snapshot=snapshot,
        case=case,
    )
    _validate_replay_readiness(
        conn,
        snapshot=snapshot,
        case=case,
        proposals=proposals,
        prompt_contract_fingerprint=prompt_contract_fingerprint,
    )

    base_drivers_payload = snapshot.market_inputs.get("base_drivers")
    valuation_policy = snapshot.market_inputs.get("valuation_policy")
    if not isinstance(base_drivers_payload, Mapping):
        raise ValueError(
            "approved replay snapshot lacks frozen base drivers"
        )
    if not isinstance(valuation_policy, Mapping):
        raise ValueError(
            "approved replay snapshot lacks valuation policy"
        )
    similarity_scores = snapshot.comps_inputs.get(
        "similarity_scores",
        {},
    )
    if not isinstance(similarity_scores, Mapping):
        raise ValueError(
            "approved replay snapshot similarity scores are invalid"
        )
    expected_case = compile_approved_valuation_case(
        ticker=snapshot.ticker,
        analysis_snapshot_hash=snapshot.snapshot_hash,
        base_drivers=ForecastDrivers(**dict(base_drivers_payload)),
        approved_packs=proposals,
        approval_fingerprints=approval_fingerprints,
        approved_treatment_hashes=case.approved_treatment_hashes,
        frozen_comps_detail=snapshot.comps_inputs,
        valuation_policy=valuation_policy,
        engine_fingerprint=case.engine_fingerprint,
        readiness=case.readiness(),
        comps_similarity_scores={
            str(key): float(value)
            for key, value in similarity_scores.items()
        },
    )
    if expected_case != case:
        raise ValueError(
            "approved replay case does not match its persisted snapshot, "
            "approvals, and readiness evidence"
        )


def persist_approved_valuation_replay(
    conn: sqlite3.Connection,
    *,
    case: ApprovedValuationCase,
    result: ApprovedValuationReplayResult,
) -> str:
    _validate_approved_case_structure(case)
    if case.replay_key != _approved_case_replay_key(case):
        raise ValueError("approved case replay identity does not match its payload")
    if case.replay_key != result.replay_key:
        raise ValueError("approved case and replay result keys do not match")
    recomputed_result = replay_approved_valuation_case(case)
    if result != recomputed_result:
        raise ValueError(
            "supplied replay result does not match deterministic replay"
        )
    computed_output_hash = hashlib.sha256(
        result.canonical_output.encode("utf-8")
    ).hexdigest()
    if computed_output_hash != result.output_hash:
        raise ValueError("replay output hash does not match canonical output")
    _validate_approved_case_provenance(conn, case)
    case_json = _canonical_json(_case_payload(case))
    result_json = _canonical_json(asdict(result))
    with conn:
        existing = conn.execute(
            """
            SELECT case_json, result_json
            FROM approved_valuation_replays
            WHERE replay_key = ?
            """,
            (case.replay_key,),
        ).fetchone()
        if existing is not None:
            existing_case_json = str(
                _row_value(existing, 0, "case_json")
            )
            existing_result_json = str(
                _row_value(existing, 1, "result_json")
            )
            _verify_artifact_integrity(
                conn,
                artifact_type="approved_valuation_case",
                artifact_key=case.replay_key,
                payload=existing_case_json,
            )
            _verify_artifact_integrity(
                conn,
                artifact_type="approved_valuation_result",
                artifact_key=case.replay_key,
                payload=existing_result_json,
            )
            if (
                existing_case_json != case_json
                or existing_result_json != result_json
            ):
                raise ValueError(
                    "immutable approved_valuation_replays identity "
                    f"{case.replay_key!r} has divergent payloads"
                )
        else:
            conn.execute(
                """
                INSERT INTO approved_valuation_replays (
                    replay_key, ticker, analysis_snapshot_hash,
                    readiness_fingerprint, output_hash, case_json,
                    result_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    case.replay_key,
                    case.ticker,
                    case.analysis_snapshot_hash,
                    case.readiness_fingerprint,
                    result.output_hash,
                    case_json,
                    result_json,
                    _now(),
                ),
            )
        _persist_artifact_integrity(
            conn,
            artifact_type="approved_valuation_case",
            artifact_key=case.replay_key,
            payload_hash=_payload_hash(case_json),
        )
        _persist_artifact_integrity(
            conn,
            artifact_type="approved_valuation_result",
            artifact_key=case.replay_key,
            payload_hash=_payload_hash(result_json),
        )
    return case.replay_key


def load_approved_valuation_replay(
    conn: sqlite3.Connection,
    replay_key: str,
) -> tuple[ApprovedValuationCase, ApprovedValuationReplayResult] | None:
    row = conn.execute(
        """
        SELECT replay_key, ticker, analysis_snapshot_hash,
               readiness_fingerprint, output_hash, case_json, result_json
        FROM approved_valuation_replays
        WHERE replay_key = ?
        """,
        (replay_key,),
    ).fetchone()
    if row is None:
        return None
    stored_replay_key = str(_row_value(row, 0, "replay_key"))
    ticker = str(_row_value(row, 1, "ticker"))
    snapshot_hash = str(
        _row_value(row, 2, "analysis_snapshot_hash")
    )
    readiness_fingerprint = str(
        _row_value(row, 3, "readiness_fingerprint")
    )
    output_hash = str(_row_value(row, 4, "output_hash"))
    case_json = str(_row_value(row, 5, "case_json"))
    result_json = str(_row_value(row, 6, "result_json"))
    _verify_artifact_integrity(
        conn,
        artifact_type="approved_valuation_case",
        artifact_key=stored_replay_key,
        payload=case_json,
    )
    _verify_artifact_integrity(
        conn,
        artifact_type="approved_valuation_result",
        artifact_key=stored_replay_key,
        payload=result_json,
    )
    case = _case_from_payload(json.loads(case_json))
    result = ApprovedValuationReplayResult(**json.loads(result_json))
    if (
        stored_replay_key != replay_key
        or case.replay_key != stored_replay_key
        or result.replay_key != stored_replay_key
        or case.ticker != ticker
        or case.analysis_snapshot_hash != snapshot_hash
        or case.readiness_fingerprint != readiness_fingerprint
        or result.output_hash != output_hash
    ):
        raise ValueError(
            "approved replay indexed columns do not match its payload"
        )
    _validate_approved_case_structure(case)
    if case.replay_key != _approved_case_replay_key(case):
        raise ValueError(
            "approved case replay identity does not match its payload"
        )
    recomputed_result = replay_approved_valuation_case(case)
    if result != recomputed_result:
        raise ValueError(
            "persisted replay result does not match deterministic replay"
        )
    _validate_approved_case_provenance(conn, case)
    return case, result


def persist_model_change_request(
    conn: sqlite3.Connection,
    request: ValuationModelChangeRequest,
    *,
    actor: str,
) -> str:
    payload_json = _canonical_json(request.model_dump(mode="json"))
    with conn:
        existing = conn.execute(
            """
            SELECT payload_json
            FROM valuation_model_change_requests
            WHERE request_id = ?
            """,
            (request.request_id,),
        ).fetchone()
        if existing is not None:
            if existing[0] != payload_json:
                raise ValueError(
                    "model-change request identity has divergent payloads"
                )
            return request.request_id
        conn.execute(
            """
            INSERT INTO valuation_model_change_requests (
                request_id, ticker, analysis_snapshot_hash, category,
                status, payload_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                request.request_id,
                request.ticker,
                request.analysis_snapshot_hash,
                request.category.value,
                request.status.value,
                payload_json,
                request.created_at,
                request.created_at,
            ),
        )
        conn.execute(
            """
            INSERT INTO valuation_model_change_events (
                request_id, event_type, actor, payload_json, created_at
            ) VALUES (?, 'created', ?, ?, ?)
            """,
            (
                request.request_id,
                actor,
                payload_json,
                request.created_at,
            ),
        )
    return request.request_id


def load_model_change_request(
    conn: sqlite3.Connection,
    request_id: str,
) -> ValuationModelChangeRequest | None:
    row = conn.execute(
        """
        SELECT payload_json
        FROM valuation_model_change_requests
        WHERE request_id = ?
        """,
        (request_id,),
    ).fetchone()
    if row is None:
        return None
    return ValuationModelChangeRequest.model_validate_json(row[0])


def decide_persisted_model_change_request(
    conn: sqlite3.Connection,
    *,
    request_id: str,
    status: ModelChangeStatus | str,
    actor: str,
    decided_at: str,
    implementation_intent: str | None = None,
) -> ValuationModelChangeRequest:
    current = load_model_change_request(conn, request_id)
    if current is None:
        raise KeyError(f"model-change request not found: {request_id}")
    if current.status != ModelChangeStatus.pending:
        raise ValueError("model-change request has already been decided")
    decided = decide_model_change_request(
        current,
        status=status,
        actor=actor,
        decided_at=decided_at,
        implementation_intent=implementation_intent,
    )
    payload_json = _canonical_json(decided.model_dump(mode="json"))
    with conn:
        cursor = conn.execute(
            """
            UPDATE valuation_model_change_requests
            SET status = ?, payload_json = ?, updated_at = ?
            WHERE request_id = ? AND status = 'pending'
            """,
            (
                decided.status.value,
                payload_json,
                decided_at,
                request_id,
            ),
        )
        if cursor.rowcount != 1:
            raise ValueError("model-change request decision conflict")
        conn.execute(
            """
            INSERT INTO valuation_model_change_events (
                request_id, event_type, actor, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                request_id,
                decided.status.value,
                actor,
                payload_json,
                decided_at,
            ),
        )
    return decided
