"""Production façade for resumable, persisted valuation workups."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timezone
import json
import math
from typing import Any

from config import PEER_SIMILARITY_MODEL
from db.loader import (
    list_evidence_packets,
    load_treatment_decision_history,
)
from db.schema import get_connection
from src.contracts.assumption_policy import ValuationPolicy
from src.contracts.assumption_registry import DriverFamily
from src.contracts.judgment_runs import canonical_semantic_hash
from src.contracts.ticker_runs import (
    EligibilityStatus,
    ReplayInputFingerprints,
    RetryPolicy,
    SourceFingerprint,
    TickerIdentity,
    TickerRunContext,
    TickerTerminalRecord,
)
from src.contracts.valuation_readiness import (
    LTMStatus,
    ReconciliationGateStatus,
    ValuationReadinessEvidence,
)
from src.stage_04_pipeline.ticker_terminal_store import (
    list_ticker_terminal_outcomes,
    persist_ticker_terminal_outcome,
)
from src.stage_04_pipeline.ticker_batch import TickerBatchManifest
from src.stage_04_pipeline.ticker_valuation_execution import (
    BRIDGE_ENGINE_FINGERPRINT,
    COMPS_ENGINE_FINGERPRINT,
    DCF_ENGINE_FINGERPRINT,
    JUDGMENT_CONTRACT_FINGERPRINT,
    VALUATION_ENGINE_FINGERPRINT,
    PreparedTickerRun,
    prepare_ticker_run,
    run_valuation_workup_batch,
)
from src.stage_04_pipeline.valuation_judgment_pipeline import (
    DriverFamilyExecutionBinding,
)


_REQUIRED_CONTEXT_PROFILES = {
    "business": "company_analysis",
    "industry": "industry_analysis",
}
_SUCCESSFUL_OBSERVATION_STATUS = "completed_with_items"


@dataclass(frozen=True, slots=True)
class PersistedValuationMaterials:
    """Persisted inputs used to freeze one valuation analysis snapshot."""

    evidence: Mapping[str, Any] = field(default_factory=dict)
    upstream_context: Mapping[str, Any] = field(default_factory=dict)
    comps_inputs: Mapping[str, Any] = field(default_factory=dict)
    valuation_policy: Mapping[str, Any] = field(default_factory=dict)
    approved_treatments: tuple[Mapping[str, Any], ...] = ()
    blocker_reason_codes: tuple[str, ...] = ()


def _timestamp(value: Any) -> datetime | None:
    text_value = str(value or "").strip()
    if not text_value:
        return None
    try:
        parsed = datetime.fromisoformat(text_value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _as_of(value: Any, analysis_as_of: date) -> bool:
    parsed = _timestamp(value)
    if parsed is None:
        return False
    cutoff = datetime.combine(
        analysis_as_of,
        time.max,
        tzinfo=timezone.utc,
    )
    return parsed <= cutoff


def _looks_heuristic(model_name: str) -> bool:
    normalized = model_name.strip().lower().replace("-", "_")
    return any(
        marker in normalized
        for marker in (
            "heuristic",
            "rule_based",
            "rulebased",
            "deterministic_stub",
            "local_stub",
        )
    )


def _packet_validation_blockers(
    packet: Mapping[str, Any],
    *,
    profile_name: str,
) -> tuple[str, ...]:
    prefix = f"materials.{profile_name}"
    blockers: list[str] = []
    metadata = packet.get("run_metadata")
    if not isinstance(metadata, Mapping):
        return (f"{prefix}.run_metadata_missing",)
    if str(metadata.get("source_quality") or "").strip().lower() != "real":
        blockers.append(f"{prefix}.source_not_real")
    if (
        str(metadata.get("handoff_run_status") or "").strip()
        != _SUCCESSFUL_OBSERVATION_STATUS
    ):
        blockers.append(f"{prefix}.run_incomplete")
    observations = packet.get("observations")
    if (
        not isinstance(observations, Sequence)
        or isinstance(observations, (str, bytes))
        or not observations
    ):
        blockers.append(f"{prefix}.observations_missing")
    artifact = metadata.get("agent_observation_artifact")
    if not isinstance(artifact, Mapping):
        blockers.append(f"{prefix}.agent_artifact_missing")
        return tuple(blockers)
    models = tuple(
        str(artifact.get(field_name) or "").strip()
        for field_name in ("model_used", "structured_model_used")
        if str(artifact.get(field_name) or "").strip()
    )
    if not models:
        blockers.append(f"{prefix}.agent_model_unverified")
    elif any(_looks_heuristic(model_name) for model_name in models):
        blockers.append(f"{prefix}.heuristic_observations")
    raw_accepted_ids = artifact.get("accepted_observation_ids")
    accepted_ids = (
        {
            str(value).strip()
            for value in raw_accepted_ids
            if str(value).strip()
        }
        if isinstance(raw_accepted_ids, Sequence)
        and not isinstance(raw_accepted_ids, (str, bytes))
        else set()
    )
    observation_ids = {
        str(observation.get("observation_id") or "").strip()
        for observation in observations or ()
        if isinstance(observation, Mapping)
    }
    valid_anchor_ids = {
        str(row.get(id_field) or "").strip()
        for collection_name, id_field in (
            ("source_refs", "source_ref_id"),
            ("facts", "fact_id"),
            ("snippets", "snippet_id"),
        )
        for row in packet.get(collection_name) or ()
        if isinstance(row, Mapping)
        and str(row.get(id_field) or "").strip()
    }
    snippet_ids = {
        str(row.get("snippet_id") or "").strip()
        for row in packet.get("snippets") or ()
        if isinstance(row, Mapping)
        and str(row.get("snippet_id") or "").strip()
    }
    invalid_grounding = False
    for observation in observations or ():
        if not isinstance(observation, Mapping):
            invalid_grounding = True
            continue
        raw_anchor_ids = observation.get("evidence_anchor_ids")
        anchor_ids = (
            {
                str(value).strip()
                for value in raw_anchor_ids
                if str(value).strip()
            }
            if isinstance(raw_anchor_ids, Sequence)
            and not isinstance(raw_anchor_ids, (str, bytes))
            else set()
        )
        raw_snippet_ids = observation.get("text_snippet_ids") or ()
        referenced_snippets = (
            {
                str(value).strip()
                for value in raw_snippet_ids
                if str(value).strip()
            }
            if isinstance(raw_snippet_ids, Sequence)
            and not isinstance(raw_snippet_ids, (str, bytes))
            else set()
        )
        if (
            not anchor_ids
            or not anchor_ids.issubset(valid_anchor_ids)
            or not referenced_snippets.issubset(snippet_ids)
        ):
            invalid_grounding = True
    if invalid_grounding:
        blockers.append(f"{prefix}.evidence_anchors_invalid")
    try:
        accepted_count = int(
            artifact.get("accepted_observation_count") or 0
        )
    except (TypeError, ValueError):
        accepted_count = -1
    if (
        not observation_ids
        or accepted_ids != observation_ids
        or accepted_count != len(observation_ids)
    ):
        blockers.append(f"{prefix}.agent_artifact_mismatch")
    return tuple(blockers)


def _latest_profile_packet(
    packets: Sequence[Mapping[str, Any]],
    *,
    profile_name: str,
    analysis_as_of: date,
    freshness_policy: (
        Callable[[Mapping[str, Any], date], bool] | None
    ) = None,
) -> tuple[Mapping[str, Any] | None, tuple[str, ...]]:
    profile_packets = tuple(
        packet
        for packet in packets
        if str(packet.get("profile_name") or "").strip() == profile_name
    )
    if not profile_packets:
        return None, (f"materials.{profile_name}.missing",)
    candidates = tuple(
        packet
        for packet in profile_packets
        if _as_of(packet.get("generated_at"), analysis_as_of)
        and _as_of(packet.get("updated_at"), analysis_as_of)
    )
    if not candidates:
        return None, (f"materials.{profile_name}.after_as_of",)
    latest = max(
        candidates,
        key=lambda packet: (
            _timestamp(packet.get("generated_at"))
            or datetime.min.replace(tzinfo=timezone.utc),
            int(packet.get("packet_id") or 0),
        ),
    )
    blockers = list(
        _packet_validation_blockers(
            latest,
            profile_name=profile_name,
        )
    )
    if freshness_policy is not None:
        try:
            is_fresh = bool(freshness_policy(latest, analysis_as_of))
        except Exception:
            blockers.append(f"materials.{profile_name}.freshness_check_failed")
        else:
            if not is_fresh:
                blockers.append(f"materials.{profile_name}.stale")
    return latest, tuple(blockers)


def _packet_context(packet: Mapping[str, Any]) -> dict[str, Any]:
    metadata = packet.get("run_metadata") or {}
    artifact = metadata.get("agent_observation_artifact") or {}
    model_name = str(
        artifact.get("structured_model_used")
        or artifact.get("model_used")
        or ""
    ).strip()
    return {
        "packet_id": int(packet["packet_id"]),
        "profile_name": str(packet["profile_name"]),
        "packet_kind": str(packet["packet_kind"]),
        "bundle_id": packet.get("bundle_id"),
        "generated_at": str(packet["generated_at"]),
        "source_quality": str(metadata.get("source_quality") or ""),
        "agent_model": model_name,
        "observations": list(packet.get("observations") or ()),
        "source_ref_ids": [
            str(row.get("source_ref_id") or "")
            for row in packet.get("source_refs") or ()
            if isinstance(row, Mapping) and str(row.get("source_ref_id") or "")
        ],
        "fact_ids": [
            str(row.get("fact_id") or "")
            for row in packet.get("facts") or ()
            if isinstance(row, Mapping) and str(row.get("fact_id") or "")
        ],
        "snippet_ids": [
            str(row.get("snippet_id") or "")
            for row in packet.get("snippets") or ()
            if isinstance(row, Mapping) and str(row.get("snippet_id") or "")
        ],
        "observation_ids": [
            str(row.get("observation_id") or "")
            for row in packet.get("observations") or ()
            if isinstance(row, Mapping)
            and str(row.get("observation_id") or "")
        ],
    }


def _merge_packet_evidence(
    evidence: dict[str, Any],
    packet: Mapping[str, Any],
) -> tuple[str, ...]:
    blockers: list[str] = []
    provenance = {
        "packet_id": int(packet["packet_id"]),
        "profile_name": str(packet["profile_name"]),
        "generated_at": str(packet["generated_at"]),
    }
    for collection_name, id_field in (
        ("source_refs", "source_ref_id"),
        ("facts", "fact_id"),
        ("snippets", "snippet_id"),
        ("observations", "observation_id"),
    ):
        for raw_row in packet.get(collection_name) or ():
            if not isinstance(raw_row, Mapping):
                blockers.append(
                    f"materials.{packet['profile_name']}.evidence_malformed"
                )
                continue
            anchor_id = str(raw_row.get(id_field) or "").strip()
            if not anchor_id:
                blockers.append(
                    f"materials.{packet['profile_name']}.evidence_malformed"
                )
                continue
            row = dict(raw_row)
            row["packet_provenance"] = provenance
            existing = evidence.get(anchor_id)
            if (
                existing is not None
                and canonical_semantic_hash(existing)
                != canonical_semantic_hash(row)
            ):
                blockers.append("materials.evidence_anchor_conflict")
                continue
            evidence[anchor_id] = row
    return tuple(blockers)


def _load_policy_as_of(
    conn: Any,
    *,
    analysis_as_of: date,
) -> tuple[dict[str, Any], tuple[str, ...]]:
    rows = conn.execute(
        """
        SELECT id, created_at, actor, global_defaults_json,
               sector_defaults_json, source_ref, notes
        FROM valuation_policy_versions
        ORDER BY created_at DESC, id DESC
        """
    ).fetchall()
    candidates = tuple(
        dict(candidate)
        for candidate in rows
        if _as_of(dict(candidate).get("created_at"), analysis_as_of)
    )
    if not candidates:
        blocker = (
            "materials.valuation_policy.after_as_of"
            if rows
            else "materials.valuation_policy.missing"
        )
        return {}, (blocker,)
    payload = max(
        candidates,
        key=lambda candidate: (
            _timestamp(candidate.get("created_at"))
            or datetime.min.replace(tzinfo=timezone.utc),
            int(candidate.get("id") or 0),
        ),
    )
    try:
        global_defaults = json.loads(
            payload["global_defaults_json"] or "{}"
        )
        sector_defaults = json.loads(
            payload["sector_defaults_json"] or "{}"
        )
        if (
            not isinstance(global_defaults, Mapping)
            or not {
                "risk_free_rate",
                "equity_risk_premium",
            }.issubset(global_defaults)
            or not isinstance(sector_defaults, Mapping)
            or not str(payload.get("actor") or "").strip()
        ):
            raise ValueError("persisted valuation policy is incomplete")
        policy = ValuationPolicy(
            policy_id=int(payload["id"]),
            created_at=str(payload["created_at"]),
            actor=str(payload["actor"]),
            global_defaults=global_defaults,
            sector_defaults=sector_defaults,
            source_ref=payload.get("source_ref"),
            notes=payload.get("notes"),
        )
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}, ("materials.valuation_policy.invalid",)
    return (
        policy.model_dump(mode="json", exclude_computed_fields=True),
        (),
    )


def _load_treatments_as_of(
    conn: Any,
    *,
    ticker: str,
    analysis_as_of: date,
) -> tuple[Mapping[str, Any], ...]:
    selected: dict[tuple[str, str], Mapping[str, Any]] = {}
    eligible = sorted(
        (
            treatment
            for treatment in load_treatment_decision_history(conn, ticker)
            if _as_of(treatment.get("decided_at"), analysis_as_of)
        ),
        key=lambda treatment: (
            _timestamp(treatment.get("decided_at"))
            or datetime.min.replace(tzinfo=timezone.utc),
            int(treatment.get("id") or 0),
        ),
        reverse=True,
    )
    for treatment in eligible:
        key = (
            str(treatment.get("topic") or "").strip(),
            str(treatment.get("focus_key") or "").strip(),
        )
        if key in selected:
            continue
        as_of_treatment = dict(treatment)
        as_of_treatment["active"] = True
        as_of_treatment["superseded_by"] = None
        as_of_treatment["updated_at"] = str(
            treatment.get("created_at")
            or treatment.get("decided_at")
            or ""
        )
        selected[key] = as_of_treatment
    return tuple(
        selected[key]
        for key in sorted(selected)
    )


def _load_similarity_scores(
    conn: Any,
    *,
    ticker: str,
    peer_tickers: set[str],
    analysis_as_of: date,
) -> dict[str, float]:
    rows = conn.execute(
        """
        SELECT peer_ticker, similarity_score, computed_at
        FROM peer_similarity_cache
        WHERE target_ticker = ? AND embedding_model = ?
        ORDER BY computed_at DESC, peer_ticker ASC
        """,
        (ticker, PEER_SIMILARITY_MODEL),
    ).fetchall()
    scores: dict[str, float] = {}
    eligible = sorted(
        (
            dict(raw_row)
            for raw_row in rows
            if _as_of(dict(raw_row).get("computed_at"), analysis_as_of)
        ),
        key=lambda row: (
            _timestamp(row.get("computed_at"))
            or datetime.min.replace(tzinfo=timezone.utc),
            str(row.get("peer_ticker") or ""),
        ),
        reverse=True,
    )
    for row in eligible:
        peer_ticker = str(row.get("peer_ticker") or "").strip().upper()
        if (
            peer_ticker not in peer_tickers
            or peer_ticker in scores
        ):
            continue
        try:
            score = float(row["similarity_score"])
        except (TypeError, ValueError):
            continue
        if math.isfinite(score) and 0.0 <= score <= 1.0:
            scores[peer_ticker] = score
    return scores


def _load_ciq_comps(
    conn: Any,
    *,
    identity: TickerIdentity,
    analysis_as_of: date,
    comps_loader: Callable[[str, str | None], Mapping[str, Any] | None],
) -> tuple[dict[str, Any], tuple[str, ...]]:
    try:
        raw_comps = comps_loader(
            identity.ticker,
            analysis_as_of.isoformat(),
        )
    except Exception as exc:
        return {}, (
            "materials.comps.loading_failed",
            f"materials.exception.{type(exc).__name__}",
        )
    if not isinstance(raw_comps, Mapping) or not raw_comps:
        return {}, ("materials.comps.missing",)
    target = raw_comps.get("target")
    if (
        not isinstance(target, Mapping)
        or str(target.get("ticker") or "").strip().upper()
        != identity.ticker
    ):
        return {}, ("materials.comps.target_mismatch",)
    peers = raw_comps.get("peers")
    if (
        not isinstance(peers, Sequence)
        or isinstance(peers, (str, bytes))
        or not peers
    ):
        return {}, ("materials.comps.peers_missing",)
    peer_tickers = {
        str(peer.get("ticker") or "").strip().upper()
        for peer in peers
        if isinstance(peer, Mapping)
        and str(peer.get("ticker") or "").strip()
    }
    if not peer_tickers:
        return {}, ("materials.comps.peers_missing",)
    lineage = raw_comps.get("source_lineage")
    if (
        not isinstance(lineage, Mapping)
        or not str(lineage.get("run_id") or "").strip()
        or not str(lineage.get("source_file") or "").strip()
        or not _as_of(lineage.get("as_of_date"), analysis_as_of)
    ):
        return {}, ("materials.comps.lineage_invalid",)
    similarity_scores = _load_similarity_scores(
        conn,
        ticker=identity.ticker,
        peer_tickers=peer_tickers,
        analysis_as_of=analysis_as_of,
    )
    if not similarity_scores:
        return {}, ("materials.comps.similarity_scores_missing",)
    comps = dict(raw_comps)
    comps["similarity_scores"] = similarity_scores
    return comps, ()


def load_persisted_valuation_materials(
    conn: Any,
    identity: TickerIdentity,
    *,
    analysis_as_of: date,
    comps_loader: Callable[[str, str | None], Mapping[str, Any] | None] | None = (
        None
    ),
    freshness_policy: (
        Callable[[Mapping[str, Any], date], bool] | None
    ) = None,
) -> PersistedValuationMaterials:
    """Load production snapshot materials without synthesizing missing data."""

    if comps_loader is None:
        from src.stage_00_data.ciq_adapter import get_ciq_comps_detail

        comps_loader = get_ciq_comps_detail

    packets = list_evidence_packets(
        conn,
        ticker=identity.ticker,
    )
    evidence: dict[str, Any] = {}
    upstream_context: dict[str, Any] = {}
    blockers: list[str] = []
    for context_name, profile_name in _REQUIRED_CONTEXT_PROFILES.items():
        packet, packet_blockers = _latest_profile_packet(
            packets,
            profile_name=profile_name,
            analysis_as_of=analysis_as_of,
            freshness_policy=freshness_policy,
        )
        blockers.extend(packet_blockers)
        if packet is None or packet_blockers:
            continue
        merge_blockers = _merge_packet_evidence(evidence, packet)
        blockers.extend(merge_blockers)
        if not merge_blockers:
            upstream_context[context_name] = _packet_context(packet)

    comps_inputs, comps_blockers = _load_ciq_comps(
        conn,
        identity=identity,
        analysis_as_of=analysis_as_of,
        comps_loader=comps_loader,
    )
    blockers.extend(comps_blockers)
    valuation_policy, policy_blockers = _load_policy_as_of(
        conn,
        analysis_as_of=analysis_as_of,
    )
    blockers.extend(policy_blockers)
    treatments = _load_treatments_as_of(
        conn,
        ticker=identity.ticker,
        analysis_as_of=analysis_as_of,
    )
    return PersistedValuationMaterials(
        evidence=evidence,
        upstream_context=upstream_context,
        comps_inputs=comps_inputs,
        valuation_policy=valuation_policy,
        approved_treatments=treatments,
        blocker_reason_codes=tuple(dict.fromkeys(blockers)),
    )


def _blocked_prepared_run(
    identity: TickerIdentity,
    *,
    analysis_as_of: date,
    reason_codes: Sequence[str],
) -> PreparedTickerRun:
    normalized_reasons = tuple(
        dict.fromkeys(
            str(reason).strip() for reason in reason_codes if str(reason).strip()
        )
    )
    blocker_hash = canonical_semantic_hash(
        {
            "identity": identity.model_dump(
                mode="json",
                exclude_computed_fields=True,
            ),
            "analysis_as_of": analysis_as_of.isoformat(),
            "reason_codes": normalized_reasons,
        }
    )
    readiness = ValuationReadinessEvidence(
        statement_reconciliation=ReconciliationGateStatus.failed,
        source_reconciliation=ReconciliationGateStatus.failed,
        claim_ledger_reconciliation=ReconciliationGateStatus.failed,
        operating_reconciliation=ReconciliationGateStatus.failed,
        annual_period_count=0,
        ltm_status=LTMStatus.unavailable,
        approved_family_hashes={},
        statement_reconciliation_hash=blocker_hash,
        source_reconciliation_hash=blocker_hash,
        claim_ledger_hash=blocker_hash,
        operating_reconciliation_hash=blocker_hash,
        peer_set_fingerprint=blocker_hash,
        treatment_set_fingerprint=blocker_hash,
        prompt_contract_fingerprint=JUDGMENT_CONTRACT_FINGERPRINT,
        dcf_engine_fingerprint=DCF_ENGINE_FINGERPRINT,
        comps_engine_fingerprint=COMPS_ENGINE_FINGERPRINT,
        bridge_engine_fingerprint=BRIDGE_ENGINE_FINGERPRINT,
    )
    context = TickerRunContext(
        identity=identity,
        analysis_as_of=analysis_as_of,
        eligibility=EligibilityStatus.supported_v1,
        valuation_model="industrial_fcff_dcf_comps_v1",
        replay_inputs=ReplayInputFingerprints(
            analysis_snapshot_hash=blocker_hash,
            approved_case_replay_fingerprint=blocker_hash,
            peer_universe_fingerprint=blocker_hash,
            treatment_register_fingerprint=blocker_hash,
            judgment_contract_fingerprint=JUDGMENT_CONTRACT_FINGERPRINT,
            valuation_engine_fingerprint=VALUATION_ENGINE_FINGERPRINT,
        ),
        readiness=readiness,
        source_fingerprints=(
            SourceFingerprint(
                source_id=f"preparation:{identity.ticker}",
                fingerprint=blocker_hash,
            ),
        ),
    )
    return PreparedTickerRun(
        context=context,
        snapshot=None,
        blocker_reason_codes=normalized_reasons,
    )


def _normalize_requests(
    requests: Iterable[str | TickerIdentity],
) -> tuple[TickerIdentity, ...]:
    return tuple(
        request
        if isinstance(request, TickerIdentity)
        else TickerIdentity(ticker=str(request))
        for request in requests
    )


def _replace_prepared_identity(
    prepared: PreparedTickerRun,
    identity: TickerIdentity,
) -> PreparedTickerRun:
    if prepared.context.identity == identity:
        return prepared
    context_payload = prepared.context.model_dump(
        mode="python",
        exclude_computed_fields=True,
    )
    context_payload["identity"] = identity.model_dump(
        mode="python",
        exclude_computed_fields=True,
    )
    return replace(
        prepared,
        context=TickerRunContext.model_validate(context_payload),
    )


def _prepared_matches_identity(
    prepared: PreparedTickerRun,
    identity: TickerIdentity,
    *,
    analysis_as_of: date,
) -> bool:
    if (
        prepared.context.identity.ticker != identity.ticker
        or prepared.context.analysis_as_of != analysis_as_of
    ):
        return False
    snapshot_ticker = str(
        getattr(prepared.snapshot, "ticker", "") or ""
    ).strip().upper()
    snapshot_as_of = str(
        getattr(prepared.snapshot, "as_of_date", "") or ""
    ).strip()
    return (
        (not snapshot_ticker or snapshot_ticker == identity.ticker)
        and (
            not snapshot_as_of
            or snapshot_as_of == analysis_as_of.isoformat()
        )
    )


def _load_prior_records(
    *,
    connection_factory: Callable[[], Any],
    identities: Sequence[TickerIdentity],
    execution_run_id: str,
) -> tuple[TickerTerminalRecord, ...]:
    requested_keys = {identity.canonical_key for identity in identities}
    records: dict[str, TickerTerminalRecord] = {}
    conn = connection_factory()
    try:
        for ticker in sorted({identity.ticker for identity in identities}):
            outcomes = list_ticker_terminal_outcomes(
                conn,
                ticker=ticker,
                execution_run_id=execution_run_id,
                limit=250,
            )
            for outcome in outcomes:
                identity_key = outcome.record.context.identity.canonical_key
                if identity_key in requested_keys:
                    records[identity_key] = outcome.record
    finally:
        close = getattr(conn, "close", None)
        if callable(close):
            close()
    return tuple(records[key] for key in sorted(records))


def run_persisted_valuation_workups(
    requests: Iterable[str | TickerIdentity],
    *,
    execution_run_id: str,
    analysis_as_of: date,
    captured_at: str,
    bindings: Mapping[DriverFamily, DriverFamilyExecutionBinding],
    connection_factory: Callable[[], Any] = get_connection,
    material_loader: Callable[..., PersistedValuationMaterials] = (
        load_persisted_valuation_materials
    ),
    prepare_run: Callable[..., PreparedTickerRun] = prepare_ticker_run,
    max_workers: int = 8,
    batch_run_id: str | None = None,
    judgment_runner: Callable[..., Any] | None = None,
    retry_policy: RetryPolicy = RetryPolicy(),
    transport_timeout_seconds: float = 120.0,
    batch_timeout_seconds: float = 900.0,
    max_in_flight: int | None = None,
    provider_lane: Callable[[TickerRunContext], str] | None = None,
    provider_lane_limits: Mapping[str, int] | None = None,
    rate_limiter: Callable[[str, TickerRunContext], None] | None = None,
    force_refresh: bool = False,
) -> TickerBatchManifest:
    """Prepare, resume, execute, and checkpoint every requested identity."""

    resolved_execution_run_id = str(execution_run_id).strip()
    if not resolved_execution_run_id:
        raise ValueError("execution_run_id is required")
    identities = _normalize_requests(requests)
    prior_records = _load_prior_records(
        connection_factory=connection_factory,
        identities=identities,
        execution_run_id=resolved_execution_run_id,
    )

    prepared_runs: list[PreparedTickerRun] = []
    for identity in identities:
        conn = connection_factory()
        try:
            try:
                materials = material_loader(
                    conn,
                    identity,
                    analysis_as_of=analysis_as_of,
                )
            except Exception as exc:
                materials = PersistedValuationMaterials(
                    blocker_reason_codes=(
                        "preparation.material_loading_failed",
                        f"preparation.exception.{type(exc).__name__}",
                    )
                )
            if not isinstance(materials, PersistedValuationMaterials):
                materials = PersistedValuationMaterials(
                    blocker_reason_codes=(
                        "preparation.material_loader_invalid",
                    )
                )
            try:
                prepared = prepare_run(
                    conn,
                    identity.ticker,
                    analysis_as_of=analysis_as_of,
                    captured_at=captured_at,
                    evidence=materials.evidence,
                    upstream_context=materials.upstream_context,
                    comps_inputs=materials.comps_inputs,
                    valuation_policy=materials.valuation_policy,
                    approved_treatments=materials.approved_treatments,
                )
                if not isinstance(prepared, PreparedTickerRun):
                    prepared = _blocked_prepared_run(
                        identity,
                        analysis_as_of=analysis_as_of,
                        reason_codes=(
                            *materials.blocker_reason_codes,
                            "preparation.prepare_result_invalid",
                        ),
                    )
                elif not _prepared_matches_identity(
                    prepared,
                    identity,
                    analysis_as_of=analysis_as_of,
                ):
                    prepared = _blocked_prepared_run(
                        identity,
                        analysis_as_of=analysis_as_of,
                        reason_codes=(
                            *materials.blocker_reason_codes,
                            "preparation.prepare_identity_mismatch",
                        ),
                    )
                else:
                    prepared = _replace_prepared_identity(
                        prepared,
                        identity,
                    )
                    if materials.blocker_reason_codes:
                        prepared = replace(
                            prepared,
                            blocker_reason_codes=tuple(
                                dict.fromkeys(
                                    (
                                        *prepared.blocker_reason_codes,
                                        *materials.blocker_reason_codes,
                                    )
                                )
                            ),
                        )
            except Exception as exc:
                prepared = _blocked_prepared_run(
                    identity,
                    analysis_as_of=analysis_as_of,
                    reason_codes=(
                        *materials.blocker_reason_codes,
                        "preparation.unhandled_exception",
                        f"preparation.exception.{type(exc).__name__}",
                    ),
                )
            prepared_runs.append(prepared)
        finally:
            close = getattr(conn, "close", None)
            if callable(close):
                close()

    provider_free_contexts = {
        item.context.context_fingerprint
        for item in prepared_runs
        if (
            item.blocker_reason_codes
            or item.snapshot is None
            or item.approved_replay is not None
            or item.context.readiness.trust_status.value == "blocked"
        )
    }

    def resolve_provider_lane(context: TickerRunContext) -> str:
        if context.context_fingerprint in provider_free_contexts:
            return "provider-free"
        if provider_lane is None:
            return "default"
        return provider_lane(context)

    def apply_rate_limit(lane: str, context: TickerRunContext) -> None:
        if context.context_fingerprint in provider_free_contexts:
            return
        if rate_limiter is not None:
            rate_limiter(lane, context)

    def checkpoint(record: TickerTerminalRecord) -> None:
        conn = connection_factory()
        try:
            persist_ticker_terminal_outcome(
                conn,
                execution_run_id=resolved_execution_run_id,
                batch_run_id=batch_run_id,
                created_at=captured_at,
                record=record,
            )
        finally:
            close = getattr(conn, "close", None)
            if callable(close):
                close()

    batch_options: dict[str, Any] = {}
    if judgment_runner is not None:
        batch_options["judgment_runner"] = judgment_runner
    return run_valuation_workup_batch(
        prepared_runs,
        bindings=bindings,
        connection_factory=connection_factory,
        max_workers=max_workers,
        prior_records=prior_records,
        retry_policy=retry_policy,
        transport_timeout_seconds=transport_timeout_seconds,
        batch_timeout_seconds=batch_timeout_seconds,
        max_in_flight=max_in_flight,
        provider_lane=resolve_provider_lane,
        provider_lane_limits=provider_lane_limits,
        rate_limiter=(apply_rate_limit if rate_limiter is not None else None),
        checkpoint_callback=checkpoint,
        force_refresh=force_refresh,
        **batch_options,
    )


__all__ = [
    "PersistedValuationMaterials",
    "load_persisted_valuation_materials",
    "run_persisted_valuation_workups",
]
