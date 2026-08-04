from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any

from db.schema import create_tables, get_connection
from src.contracts.assumption_policy import PendingAssumptionChange, PendingAssumptionSourceType
from src.contracts.accounting_evidence import AccountingTreatment, ValuationTreatment
from src.contracts.driver_families import DriverFamilyCritique
from src.contracts.judgment_runs import (
    AgentRunStatus,
    canonical_semantic_hash,
)
from src.contracts.pm_decision_queue import AssumptionChangePack
from src.stage_04_pipeline.accounting_ledger import _NON_MUTATING_TREATMENTS
from src.stage_04_pipeline.driver_family_queue import (
    approved_scenario_values_from_queue_pack,
    driver_family_proposal_from_queue_pack,
)
from src.stage_04_pipeline.valuation_run_store import (
    load_agent_run_envelope,
    load_analysis_snapshot,
)
from src.stage_04_pipeline.pending_assumption_changes import (
    approve_pending_assumption_changes,
    apply_pending_assumption_stack,
    create_pending_assumption_change,
    preview_pending_assumption_stack,
)


class PMDecisionQueuePreviewRequiredError(ValueError):
    """Raised when approval is attempted before a fresh deterministic preview."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_queue_item_or_raise(conn: Any, ticker: str, item_id: int) -> dict[str, Any]:
    from db.loader import list_pm_decision_queue_items

    rows = list_pm_decision_queue_items(conn, ticker=ticker.upper(), status=None)
    for row in rows:
        if int(row["item_id"]) == int(item_id):
            return row
    raise ValueError(f"queue item not found for ticker={ticker} item_id={item_id}")


def _active_pack(item: dict[str, Any]) -> dict[str, Any] | None:
    return item.get("pm_edited_proposal_pack") or item.get("proposal_pack")


def _append_decision_history(item: dict[str, Any], event: dict[str, Any]) -> list[dict[str, Any]]:
    history = list(item.get("decision_history") or [])
    history.append(event)
    return history


def _valuation_inputs_fingerprint(ticker: str) -> str:
    from src.stage_02_valuation.input_assembler import build_valuation_inputs

    inputs = build_valuation_inputs(ticker)
    drivers = inputs.drivers if inputs is not None else None
    if is_dataclass(drivers):
        payload = asdict(drivers)
    elif hasattr(drivers, "__dict__"):
        payload = vars(drivers)
    else:
        payload = drivers
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(serialized.encode("utf-8")).hexdigest()


def _preview_fingerprint(ticker: str, resolved_pack: dict[str, Any] | None, skipped_fields: list[str]) -> str:
    payload = {
        "valuation_inputs_fingerprint": _valuation_inputs_fingerprint(ticker),
        "resolved_pack": resolved_pack or {},
        "skipped_fields": sorted(skipped_fields),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _driver_family_pack(
    pack_payload: dict[str, Any] | None,
) -> AssumptionChangePack | None:
    if not pack_payload:
        return None
    pack = AssumptionChangePack.model_validate(pack_payload)
    return pack if pack.family is not None else None


def _supersede_prior_driver_family_approvals(
    conn: Any,
    *,
    ticker: str,
    current_item: dict[str, Any],
    family: Any,
    superseding_item_id: int,
    actor: str,
    event_ts: str,
) -> None:
    """Close older active approvals for the same ticker and driver family."""

    from db.loader import (
        insert_pm_decision_queue_event,
        list_pm_decision_queue_items,
        update_pm_decision_queue_item,
    )

    rows = list_pm_decision_queue_items(
        conn,
        ticker=ticker,
        status="approved",
        item_type="assumption_change_pack",
    )
    for prior in rows:
        prior_item_id = int(prior["item_id"])
        if prior_item_id == int(current_item["item_id"]):
            continue
        prior_pack = _driver_family_pack(prior.get("approved_proposal_pack"))
        if prior_pack is None or prior_pack.family != family:
            continue
        prior_links = dict(prior.get("adapter_links") or {})
        prior_links["superseded_by_item_id"] = superseding_item_id
        prior_links["superseded_at"] = event_ts
        prior_history = _append_decision_history(
            prior,
            {
                "event": "supersede",
                "actor": actor,
                "event_ts": event_ts,
                "superseded_by_item_id": superseding_item_id,
            },
        )
        update_pm_decision_queue_item(
            conn,
            item_id=prior_item_id,
            updates={
                "status": "superseded",
                "adapter_links": prior_links,
                "decision_history": prior_history,
                "updated_at": event_ts,
            },
            commit=False,
        )
        insert_pm_decision_queue_event(
            conn,
            {
                "created_at": event_ts,
                "item_id": prior_item_id,
                "ticker": ticker,
                "event_type": "supersede",
                "actor": actor,
                "payload": {"superseded_by_item_id": superseding_item_id},
            },
            commit=False,
        )


def _accounting_treatment_metadata(item: dict[str, Any]) -> dict[str, Any] | None:
    """Return ledger metadata only for queue items produced by accounting review."""
    metadata = item.get("metadata")
    if not isinstance(metadata, dict) or metadata.get("source") != "accounting_ledger":
        return None
    finding_metadata = metadata.get("finding_metadata")
    if not isinstance(finding_metadata, dict):
        return dict(metadata)
    merged = dict(finding_metadata)
    merged.update(metadata)
    return merged


def _evidence_corpus_hash(
    conn: Any,
    item: dict[str, Any],
    metadata: dict[str, Any],
) -> str | None:
    """Read an explicitly supplied corpus hash without substituting a fingerprint."""
    for key in ("evidence_corpus_hash", "corpus_hash"):
        value = metadata.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()

    # Some queue producers retain only the persisted evidence packet id. If that
    # packet contains an explicit hash, use it; otherwise the provenance is
    # genuinely unavailable at approval time.
    from db.loader import load_evidence_packet

    hashes: set[str] = set()
    for packet_id in item.get("evidence_packet_ids") or []:
        try:
            packet = load_evidence_packet(conn, int(packet_id))
        except (TypeError, ValueError):
            continue
        if not packet:
            continue
        containers: list[dict[str, Any]] = []
        run_metadata = packet.get("run_metadata")
        if isinstance(run_metadata, dict):
            containers.append(run_metadata)
        for source_ref in packet.get("source_refs") or []:
            if not isinstance(source_ref, dict):
                continue
            containers.append(source_ref)
            source_metadata = source_ref.get("metadata")
            if isinstance(source_metadata, dict):
                containers.append(source_metadata)
        for container in containers:
            for key in ("evidence_corpus_hash", "corpus_hash"):
                value = container.get(key)
                if value is not None and str(value).strip():
                    hashes.add(str(value).strip())
    return next(iter(hashes)) if len(hashes) == 1 else None


def _is_non_treatment_advisory(metadata: dict[str, Any]) -> bool:
    """Return whether accounting metadata records a conclusion not to act.

    The accounting contract owns the permitted treatment values. The ledger owns
    the valuation treatments that are explicitly non-mutating. Invalid or
    incomplete metadata is not treated as an advisory so approval remains
    fail-closed for malformed treatment-bearing items.
    """
    accounting_value = metadata.get("accounting_treatment")
    valuation_value = metadata.get("valuation_treatment")
    if accounting_value is None or valuation_value is None:
        return False
    try:
        accounting_treatment = AccountingTreatment(str(accounting_value).strip())
        valuation_treatment = ValuationTreatment(str(valuation_value).strip())
    except ValueError:
        return False

    non_treatment_accounting = {
        AccountingTreatment.no_adjustment,
        AccountingTreatment.scenario_only,
        AccountingTreatment.disclosure_only,
        AccountingTreatment.unclear,
    }
    return (
        accounting_treatment in non_treatment_accounting
        and valuation_treatment.value in _NON_MUTATING_TREATMENTS
    )


def _accounting_treatment_row(
    conn: Any,
    item: dict[str, Any],
    *,
    ticker: str,
    actor: str,
    decided_at: str,
) -> dict[str, Any] | None:
    """Translate an approved accounting queue item into a register row.

    Generic queue items and driver-family packs deliberately return ``None``.
    Required register fields are not inferred from proposal values or hashes.
    """
    metadata = _accounting_treatment_metadata(item)
    if metadata is None:
        return None
    if _is_non_treatment_advisory(metadata):
        return None

    def _text(value: Any) -> str | None:
        cleaned = str(value).strip() if value is not None else ""
        return cleaned or None

    topic = _text(metadata.get("topic"))
    treatment = _text(metadata.get("accounting_treatment"))
    valuation_treatment = _text(metadata.get("valuation_treatment"))
    rationale = (
        _text(item.get("summary"))
        or _text(metadata.get("rationale"))
        or _text(metadata.get("materiality_rationale"))
    )
    evidence_corpus_hash = _evidence_corpus_hash(conn, item, metadata)
    if not topic or not treatment or not valuation_treatment or not rationale:
        return None
    if not evidence_corpus_hash:
        # treatment_decisions.evidence_corpus_hash is NOT NULL. Do not write a
        # made-up value when the approved queue item carries no corpus hash.
        return None

    return {
        "ticker": ticker,
        "topic": topic,
        "focus_key": _text(metadata.get("focus_key")),
        "treatment": treatment,
        "valuation_treatment": valuation_treatment,
        "driver_field": _text(metadata.get("proposed_driver_field")),
        "model_change_request": _text(metadata.get("model_change_request")),
        "evidence_anchor_ids": list(item.get("evidence_anchor_ids") or []),
        "rationale": rationale,
        "decided_at": decided_at,
        "approved_by": actor,
        "evidence_corpus_hash": evidence_corpus_hash,
        "created_at": decided_at,
        "updated_at": decided_at,
    }


def _driver_family_review(
    conn: Any,
    *,
    ticker: str,
    pack: AssumptionChangePack,
) -> tuple[str, dict[str, Any]]:
    """Recheck frozen evidence and run identities before PM action."""

    snapshot_hash = str(pack.analysis_snapshot_hash or "")
    snapshot = load_analysis_snapshot(conn, snapshot_hash)
    if snapshot is None:
        raise ValueError("driver family snapshot is missing")
    if snapshot.ticker != ticker:
        raise ValueError("driver family snapshot ticker changed")
    proposal = driver_family_proposal_from_queue_pack(pack)
    proposal_anchors = {
        anchor
        for assumption in proposal.assumptions
        for anchor in assumption.evidence_anchor_ids
    }
    unknown = sorted(proposal_anchors - set(snapshot.evidence))
    if unknown:
        raise ValueError(
            "driver family evidence changed after judgment: "
            + ", ".join(unknown)
        )

    envelope_identity: list[dict[str, Any]] = []
    for run_role, run_id, allowed_roles in (
        ("primary", pack.primary_run_id, {"primary", "revision"}),
        ("critic", pack.critic_run_id, {"critic"}),
    ):
        envelope = load_agent_run_envelope(conn, str(run_id or ""))
        if envelope is None:
            raise ValueError(f"driver family {run_role} run is missing")
        if envelope.status != AgentRunStatus.succeeded:
            raise ValueError(f"driver family {run_role} run did not succeed")
        task = envelope.task
        if (
            task.ticker != ticker
            or task.family != pack.family.value
            or task.frozen_snapshot_hash != snapshot_hash
            or task.role not in allowed_roles
        ):
            raise ValueError(
                f"driver family {run_role} run identity changed"
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
                    "final critic run does not accept the family"
                )
        final_trace = envelope.attempts[-1].trace
        envelope_identity.append(
            {
                "run_role": run_role,
                "run_id": envelope.run_id,
                "semantic_task_hash": envelope.semantic_task_hash,
                "invocation_hash": envelope.invocation_hash,
                "prompt_hash": task.prompt_hash,
                "schema_hash": task.schema_hash,
                "compiler_hash": task.compiler_hash,
                "provider": envelope.route.provider,
                "adapter_id": envelope.route.adapter_id,
                "adapter_version": envelope.route.adapter_version,
                "requested_model": envelope.route.requested_model,
                "actual_model": final_trace.actual_model,
                "validated_payload_hash": canonical_semantic_hash(
                    envelope.validated_payload
                ),
            }
        )
    identity = {
        "ticker": ticker,
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
        "run_envelopes": envelope_identity,
    }
    fingerprint = canonical_semantic_hash(identity)
    preview = {
        "proposal_scope": "low_base_high",
        "family": pack.family.value,
        "analysis_snapshot_hash": snapshot.snapshot_hash,
        "scenario_values": approved_scenario_values_from_queue_pack(pack),
        "review_fingerprint": fingerprint,
        "trust_status": "provisional_until_complete_bundle_replay",
    }
    return fingerprint, preview


def _conflict_proposal_value(item: dict[str, Any], proposal: dict[str, Any]) -> float | None:
    if proposal.get("proposed_target_value") is not None:
        return float(proposal["proposed_target_value"])
    if proposal.get("proposal_mode") == "scenarios":
        if proposal.get("applicability") == "not_applicable":
            return 0.0
        scenario_values = proposal.get("scenario_values") or {}
        if scenario_values.get("base") is not None:
            return float(scenario_values["base"])
    assumption_name = str(proposal.get("assumption_name") or "")
    preview_values = (item.get("adapter_links") or {}).get("last_preview_manual_values") or {}
    if assumption_name in preview_values:
        return float(preview_values[assumption_name])
    return None


def _require_status(item: dict[str, Any], allowed: set[str], action: str) -> None:
    status = str(item.get("status") or "")
    if status not in allowed:
        raise ValueError(f"queue item with status={status or 'unknown'} cannot be {action}")


def _active_proposals(item: dict[str, Any]) -> list[dict[str, Any]]:
    pack = _active_pack(item)
    proposals = pack.get("proposals") if isinstance(pack, dict) else []
    return [proposal for proposal in proposals if isinstance(proposal, dict)]


def build_pm_decision_queue_conflict_groups(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group pending assumption-change items that touch the same model driver."""
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in items:
        if item.get("status") not in {"pending", "previewed"}:
            continue
        if item.get("item_type") != "assumption_change_pack":
            continue
        ticker = str(item.get("ticker") or "").upper()
        for proposal in _active_proposals(item):
            assumption_name = str(proposal.get("assumption_name") or "").strip()
            if not ticker or not assumption_name:
                continue
            grouped.setdefault((ticker, assumption_name), []).append(
                {
                    "item_id": item.get("item_id"),
                    "profile_name": item.get("profile_name"),
                    "status": item.get("status"),
                    "title": item.get("title"),
                    "summary": item.get("summary"),
                    "assumption_name": assumption_name,
                    "proposal_mode": proposal.get("proposal_mode"),
                    "proposed_value": _conflict_proposal_value(item, proposal),
                    "proposal": proposal,
                    "qualitative_importance": item.get("qualitative_importance"),
                    "agent_confidence": item.get("agent_confidence"),
                    "translator_confidence": item.get("translator_confidence"),
                    "valuation_impact_bucket": item.get("valuation_impact_bucket"),
                    "source_quality": (item.get("metadata") or {}).get("packet_provenance", {}).get("source_quality"),
                    "evidence_packet_ids": item.get("evidence_packet_ids") or [],
                    "evidence_anchor_ids": item.get("evidence_anchor_ids") or [],
                    "last_preview_at": (item.get("adapter_links") or {}).get("last_preview_at"),
                    "last_preview_fingerprint": (item.get("adapter_links") or {}).get("last_preview_fingerprint"),
                }
            )

    conflict_groups: list[dict[str, Any]] = []
    for (ticker, assumption_name), entries in grouped.items():
        latest_entry_by_profile: dict[str, dict[str, Any]] = {}
        for entry in entries:
            profile_name = str(entry.get("profile_name") or "").strip()
            if not profile_name:
                continue
            current = latest_entry_by_profile.get(profile_name)
            if current is None or int(entry.get("item_id") or 0) > int(current.get("item_id") or 0):
                latest_entry_by_profile[profile_name] = entry
        entries = list(latest_entry_by_profile.values())
        if len(entries) < 2:
            continue
        profile_names = sorted(latest_entry_by_profile)
        values = [entry.get("proposed_value") for entry in entries if entry.get("proposed_value") is not None]
        distinct_values = sorted({round(float(value), 8) for value in values})
        conflict_groups.append(
            {
                "group_id": f"{ticker}:{assumption_name}",
                "ticker": ticker,
                "assumption_name": assumption_name,
                "profile_names": profile_names,
                "item_ids": [entry.get("item_id") for entry in entries if entry.get("item_id") is not None],
                "proposal_count": len(entries),
                "distinct_value_count": len(distinct_values),
                "conflict_level": "conflict" if len(distinct_values) > 1 else "cluster",
                "review_note": (
                    "Multiple profiles propose different values for this driver."
                    if len(distinct_values) > 1
                    else "Multiple profiles touch this driver; review as one assumption cluster."
                ),
                "entries": entries,
            }
        )
    return sorted(
        conflict_groups,
        key=lambda group: (
            0 if group["conflict_level"] == "conflict" else 1,
            str(group["assumption_name"]),
        ),
    )


def _resolve_active_pack(
    pack: dict[str, Any] | None,
    ticker: str,
) -> tuple[dict[str, Any] | None, dict[str, float], list[str]]:
    """Resolve an active proposal pack to absolute target values.

    Returns (resolved_pack, manual_values, skipped_fields) where skipped_fields contains
    assumption names for delta proposals that could not be resolved (e.g. no valuation inputs).
    """
    if not pack:
        return None, {}, []
    values: dict[str, float] = {}
    skipped: list[str] = []
    resolved_proposals: list[dict[str, Any]] = []

    # Resolve current driver values for delta proposals (lazy import to avoid circular deps).
    _drivers: Any = None
    _drivers_loaded = False

    def _get_drivers() -> Any:
        nonlocal _drivers, _drivers_loaded
        if _drivers_loaded:
            return _drivers
        _drivers_loaded = True
        try:
            from src.stage_02_valuation.input_assembler import build_valuation_inputs

            inputs = build_valuation_inputs(ticker)
            _drivers = inputs.drivers if inputs is not None else None
        except Exception:
            _drivers = None
        return _drivers

    for proposal in pack.get("proposals") or []:
        name = proposal.get("assumption_name")
        mode = proposal.get("proposal_mode")
        if not name:
            continue
        resolved_value: float | None = None
        if mode == "target" and proposal.get("proposed_target_value") is not None:
            resolved_value = float(proposal["proposed_target_value"])
        elif mode == "scenarios":
            scenario_values = proposal.get("scenario_values") or {}
            if proposal.get("applicability") == "not_applicable":
                resolved_value = 0.0
            elif scenario_values.get("base") is not None:
                resolved_value = float(scenario_values["base"])
            else:
                skipped.append(str(name))
                continue
        elif mode == "delta" and proposal.get("proposed_delta") is not None:
            drivers = _get_drivers()
            if drivers is not None and hasattr(drivers, name):
                current = float(getattr(drivers, name))
                resolved_value = current + float(proposal["proposed_delta"])
            else:
                skipped.append(str(name))
                continue
        else:
            continue
        values[str(name)] = resolved_value
        if mode == "scenarios":
            resolved_proposals.append(dict(proposal))
        else:
            resolved_proposals.append(
                {
                    **proposal,
                    "proposal_mode": "target",
                    "proposed_target_value": resolved_value,
                    "proposed_delta": None,
                }
            )
    resolved_pack = {**pack, "proposals": resolved_proposals}
    return resolved_pack, values, skipped


def preview_pm_decision_queue_item(
    ticker: str,
    item_id: int,
) -> dict[str, Any]:
    ticker = ticker.upper().strip()
    with get_connection() as conn:
        create_tables(conn)
        from db.loader import update_pm_decision_queue_item

        item = _load_queue_item_or_raise(conn, ticker, item_id)
        _require_status(item, {"pending", "previewed"}, "previewed")
        active_pack = _active_pack(item)
        family_pack = _driver_family_pack(active_pack)
        if family_pack is not None:
            (
                preview_fingerprint,
                family_preview,
            ) = _driver_family_review(
                conn,
                ticker=ticker,
                pack=family_pack,
            )
            previewed_at = _now()
            adapter_links = dict(item.get("adapter_links") or {})
            adapter_links.update(
                {
                    "last_preview_at": previewed_at,
                    "last_preview_fingerprint": preview_fingerprint,
                    "last_preview_kind": "driver_family_low_base_high",
                    "last_preview_skipped_fields": [],
                    "last_preview_manual_values": {},
                }
            )
            item = update_pm_decision_queue_item(
                conn,
                item_id=item_id,
                updates={
                    "status": "previewed",
                    "adapter_links": adapter_links,
                    "valuation_impact": family_preview,
                    "updated_at": previewed_at,
                },
            )
            return {
                "item": item,
                "preview": family_preview,
                "skipped_fields": [],
                "preview_fingerprint": preview_fingerprint,
                "previewed_at": previewed_at,
            }
        resolved_pack, manual_values, skipped_fields = _resolve_active_pack(active_pack, ticker)
        adapter_links = dict(item.get("adapter_links") or {})
        if item.get("item_type") == "assumption_change_pack":
            previewed_at = _now()
            preview_fingerprint = _preview_fingerprint(ticker, resolved_pack, skipped_fields)
            adapter_links["last_preview_at"] = previewed_at
            adapter_links["last_preview_fingerprint"] = preview_fingerprint
            adapter_links["last_preview_skipped_fields"] = skipped_fields
            adapter_links["last_preview_manual_values"] = manual_values
            adapter_links["last_preview_conflicts"] = []
            item = update_pm_decision_queue_item(
                conn,
                item_id=item_id,
                updates={"status": "previewed", "adapter_links": adapter_links, "updated_at": previewed_at},
            )
    preview = preview_pending_assumption_stack(ticker, change_ids=[], manual_values=manual_values)
    return {
        "item": item,
        "preview": preview,
        "skipped_fields": skipped_fields,
        "preview_fingerprint": adapter_links.get("last_preview_fingerprint") if item.get("item_type") == "assumption_change_pack" else None,
        "previewed_at": adapter_links.get("last_preview_at") if item.get("item_type") == "assumption_change_pack" else None,
    }


def edit_pm_decision_queue_item(
    ticker: str,
    item_id: int,
    edited_pack_payload: dict[str, Any],
    *,
    actor: str,
) -> dict[str, Any]:
    ticker = ticker.upper().strip()
    edited_pack = AssumptionChangePack.model_validate(edited_pack_payload).model_dump()
    ts = _now()
    with get_connection() as conn:
        create_tables(conn)
        from db.loader import insert_pm_decision_queue_event, update_pm_decision_queue_item

        item = _load_queue_item_or_raise(conn, ticker, item_id)
        _require_status(item, {"pending", "previewed"}, "edited")
        original_family_pack = _driver_family_pack(item.get("proposal_pack"))
        edited_family_pack = _driver_family_pack(edited_pack)
        if original_family_pack is not None:
            if edited_family_pack is None:
                raise ValueError(
                    "driver family edits must remain atomic family packs"
                )
            immutable_fields = (
                "pack_id",
                "family",
                "analysis_snapshot_hash",
                "primary_run_id",
                "critic_run_id",
                "critic_verdict",
            )
            changed = [
                field_name
                for field_name in immutable_fields
                if getattr(original_family_pack, field_name)
                != getattr(edited_family_pack, field_name)
            ]
            if changed:
                raise ValueError(
                    "driver family provenance fields are immutable: "
                    + ", ".join(changed)
                )
        adapter_links = dict(item.get("adapter_links") or {})
        for key in (
            "last_preview_at",
            "last_preview_fingerprint",
            "last_preview_skipped_fields",
            "last_preview_manual_values",
        ):
            adapter_links.pop(key, None)
        history = _append_decision_history(
            item,
            {
                "event": "edit",
                "actor": actor,
                "event_ts": ts,
                "pm_edited_proposal_pack": edited_pack,
            },
        )
        updated = update_pm_decision_queue_item(
            conn,
            item_id=item_id,
            updates={
                "status": "pending",
                "pm_edited_proposal_pack": edited_pack,
                "adapter_links": adapter_links,
                "decision_history": history,
                "updated_at": ts,
            },
        )
        insert_pm_decision_queue_event(
            conn,
            {
                "created_at": ts,
                "item_id": item_id,
                "ticker": ticker,
                "event_type": "edit",
                "actor": actor,
                "payload": {"pm_edited_proposal_pack": edited_pack},
            },
        )
    return updated


def approve_pm_decision_queue_item(
    ticker: str,
    item_id: int,
    *,
    actor: str,
) -> dict[str, Any]:
    ticker = ticker.upper().strip()
    ts = _now()
    with get_connection() as conn:
        create_tables(conn)
        from db.loader import (
            insert_pm_decision_queue_event,
            insert_treatment_decision,
            update_pm_decision_queue_item,
        )

        item = _load_queue_item_or_raise(conn, ticker, item_id)
        _require_status(item, {"pending", "previewed"}, "approved")
        active_pack = _active_pack(item)
        family_pack = _driver_family_pack(active_pack)
        if family_pack is not None:
            expected_fingerprint, _ = _driver_family_review(
                conn,
                ticker=ticker,
                pack=family_pack,
            )
            adapter_links = dict(item.get("adapter_links") or {})
            if (
                adapter_links.get("last_preview_fingerprint")
                != expected_fingerprint
            ):
                raise PMDecisionQueuePreviewRequiredError(
                    "driver family must be previewed against the current "
                    "snapshot, evidence, runs, peers, treatments, and model "
                    "contracts before approval"
                )
            approved_pack = family_pack.model_dump(mode="json")
            history = _append_decision_history(
                item,
                {
                    "event": "approve",
                    "actor": actor,
                    "event_ts": ts,
                    "approved_proposal_pack": approved_pack,
                    "approval_fingerprint": expected_fingerprint,
                },
            )
            adapter_links.update(
                {
                    "approval_fingerprint": expected_fingerprint,
                    "approval_ref": (
                        f"driver-family:{ticker}:{item_id}:{ts}"
                    ),
                    "scalar_pending_rows_created": 0,
                }
            )
            _supersede_prior_driver_family_approvals(
                conn,
                ticker=ticker,
                current_item=item,
                family=family_pack.family,
                superseding_item_id=int(item_id),
                actor=actor,
                event_ts=ts,
            )
            updated = update_pm_decision_queue_item(
                conn,
                item_id=item_id,
                updates={
                    "status": "approved",
                    "approved_proposal_pack": approved_pack,
                    "adapter_links": adapter_links,
                    "decision_history": history,
                    "updated_at": ts,
                },
                commit=False,
            )
            insert_pm_decision_queue_event(
                conn,
                {
                    "created_at": ts,
                    "item_id": item_id,
                    "ticker": ticker,
                    "event_type": "approve",
                    "actor": actor,
                    "payload": {
                        "approval_fingerprint": expected_fingerprint,
                        "approved_proposal_pack": approved_pack,
                    },
                },
                commit=False,
            )
            return updated
        resolved_pack, _, skipped_fields = _resolve_active_pack(active_pack, ticker)
        if item.get("item_type") == "assumption_change_pack":
            adapter_links = dict(item.get("adapter_links") or {})
            expected_fingerprint = _preview_fingerprint(ticker, resolved_pack, skipped_fields)
            if adapter_links.get("last_preview_fingerprint") != expected_fingerprint:
                raise PMDecisionQueuePreviewRequiredError(
                    "queue item must be previewed after the latest edit before approval"
                )
        if item.get("item_type") == "assumption_change_pack" and skipped_fields:
            raise ValueError(
                "queue item has unresolvable proposal fields; preview and edit before approval: "
                + ", ".join(skipped_fields)
            )
        if item.get("item_type") == "assumption_change_pack" and not (
            resolved_pack and resolved_pack.get("proposals")
        ):
            raise ValueError("queue item has no resolvable proposals to approve")
        pending_ids: list[int] = []
        if resolved_pack:
            for idx, proposal in enumerate(resolved_pack.get("proposals") or [], start=1):
                name = proposal.get("assumption_name")
                if not name:
                    continue
                proposed_value = proposal.get("proposed_target_value")
                if (
                    proposed_value is None
                    and proposal.get("proposal_mode") == "scenarios"
                ):
                    if proposal.get("applicability") == "not_applicable":
                        proposed_value = 0.0
                    else:
                        proposed_value = (
                            proposal.get("scenario_values") or {}
                        ).get("base")
                if proposed_value is None:
                    continue
                created = create_pending_assumption_change(
                    PendingAssumptionChange(
                        ticker=ticker,
                        assumption_name=str(name),
                        current_value=None,
                        proposed_value=float(proposed_value),
                        source_type=PendingAssumptionSourceType.agent,
                        source_ref=f"pm_decision_queue_item:{item_id}",
                        confidence=item.get("translator_confidence"),
                        rationale=item.get("summary"),
                        citation=None,
                        metadata={
                            "queue_item_id": item_id,
                            "proposal_index": idx,
                            "proposal_mode": proposal.get("proposal_mode"),
                            "original_proposal_pack": item.get("proposal_pack"),
                            "pm_edited_proposal_pack": item.get("pm_edited_proposal_pack"),
                            "approved_proposal_pack": resolved_pack,
                        },
                    )
                )
                if created.change_id is not None:
                    pending_ids.append(int(created.change_id))

        approval_result = approve_pending_assumption_changes(ticker, pending_ids, actor=actor) if pending_ids else {
            "ticker": ticker,
            "approved_count": 0,
            "change_ids": [],
            "approval_ref": None,
        }
        accounting_metadata = _accounting_treatment_metadata(item)
        treatment_row = _accounting_treatment_row(
            conn,
            item,
            ticker=ticker,
            actor=actor,
            decided_at=ts,
        )
        if (
            accounting_metadata is not None
            and not _is_non_treatment_advisory(accounting_metadata)
            and treatment_row is None
        ):
            raise ValueError(
                "accounting queue item cannot be persisted: treatment register "
                "requires topic, treatment, valuation treatment, rationale, and "
                "a genuine evidence corpus hash"
            )
        if treatment_row is not None:
            insert_treatment_decision(conn, treatment_row, commit=False)
        approved_pack = resolved_pack if resolved_pack and resolved_pack.get("proposals") else None
        adapter_links = dict(item.get("adapter_links") or {})
        adapter_links["pending_assumption_change_ids"] = pending_ids
        adapter_links["approval_ref"] = approval_result.get("approval_ref")
        adapter_links["skipped_fields"] = skipped_fields

        history = _append_decision_history(
            item,
            {
                "event": "approve",
                "actor": actor,
                "event_ts": ts,
                "pending_assumption_change_ids": pending_ids,
                "approval_ref": approval_result.get("approval_ref"),
                "approved_proposal_pack": approved_pack,
                "skipped_fields": skipped_fields,
            },
        )

        updated = update_pm_decision_queue_item(
            conn,
            item_id=item_id,
            updates={
                "status": "approved",
                "approved_proposal_pack": approved_pack,
                "adapter_links": adapter_links,
                "decision_history": history,
                "updated_at": ts,
            },
            commit=False,
        )
        insert_pm_decision_queue_event(
            conn,
            {
                "created_at": ts,
                "item_id": item_id,
                "ticker": ticker,
                "event_type": "approve",
                "actor": actor,
                "payload": {
                    "pending_assumption_change_ids": pending_ids,
                    "approval_ref": approval_result.get("approval_ref"),
                },
            },
            commit=False,
        )
    return updated


def apply_pm_decision_queue_item(ticker: str, item_id: int, *, actor: str) -> dict[str, Any]:
    ticker = ticker.upper().strip()
    ts = _now()
    with get_connection() as conn:
        create_tables(conn)
        from db.loader import insert_pm_decision_queue_event, update_pm_decision_queue_item

        item = _load_queue_item_or_raise(conn, ticker, item_id)
        if item.get("status") != "approved":
            raise ValueError("queue item must be approved before apply")
        if _driver_family_pack(item.get("approved_proposal_pack")) is not None:
            raise ValueError(
                "approved driver families are consumed atomically by the "
                "low/base/high replay; scalar apply is not supported"
            )
        adapter_links = dict(item.get("adapter_links") or {})
        if adapter_links.get("applied_at"):
            return item
        pending_ids = [int(value) for value in adapter_links.get("pending_assumption_change_ids") or []]
        apply_result = apply_pending_assumption_stack(ticker, pending_ids, actor=actor)
        adapter_links["applied_assumption_change_ids"] = apply_result.get("change_ids") or []
        adapter_links["applied_at"] = ts
        history = _append_decision_history(
            item,
            {
                "event": "apply",
                "actor": actor,
                "event_ts": ts,
                "applied_assumption_change_ids": adapter_links["applied_assumption_change_ids"],
            },
        )
        updated = update_pm_decision_queue_item(
            conn,
            item_id=item_id,
            updates={"adapter_links": adapter_links, "decision_history": history, "updated_at": ts},
        )
        insert_pm_decision_queue_event(
            conn,
            {
                "created_at": ts,
                "item_id": item_id,
                "ticker": ticker,
                "event_type": "apply",
                "actor": actor,
                "payload": {"applied_assumption_change_ids": adapter_links["applied_assumption_change_ids"]},
            },
        )
    return updated


def reject_pm_decision_queue_item(
    ticker: str,
    item_id: int,
    *,
    actor: str,
    reason: str,
) -> dict[str, Any]:
    reason = reason.strip()
    if not reason:
        raise ValueError("reason is required")
    ticker = ticker.upper().strip()
    ts = _now()
    with get_connection() as conn:
        create_tables(conn)
        from db.loader import insert_pm_decision_queue_event, update_pm_decision_queue_item

        item = _load_queue_item_or_raise(conn, ticker, item_id)
        _require_status(item, {"pending", "previewed"}, "rejected")
        history = _append_decision_history(
            item,
            {"event": "reject", "actor": actor, "event_ts": ts, "reason": reason},
        )
        updated = update_pm_decision_queue_item(
            conn,
            item_id=item_id,
            updates={"status": "rejected", "decision_history": history, "updated_at": ts},
        )
        insert_pm_decision_queue_event(
            conn,
            {
                "created_at": ts,
                "item_id": item_id,
                "ticker": ticker,
                "event_type": "reject",
                "actor": actor,
                "payload": {"reason": reason},
            },
        )
    return updated


def defer_pm_decision_queue_item(
    ticker: str,
    item_id: int,
    *,
    actor: str,
    reason: str,
) -> dict[str, Any]:
    reason = reason.strip()
    if not reason:
        raise ValueError("reason is required")
    ticker = ticker.upper().strip()
    ts = _now()
    with get_connection() as conn:
        create_tables(conn)
        from db.loader import insert_pm_decision_queue_event, update_pm_decision_queue_item

        item = _load_queue_item_or_raise(conn, ticker, item_id)
        _require_status(item, {"pending", "previewed"}, "deferred")
        history = _append_decision_history(
            item,
            {"event": "defer", "actor": actor, "event_ts": ts, "reason": reason},
        )
        updated = update_pm_decision_queue_item(
            conn,
            item_id=item_id,
            updates={"status": "deferred", "decision_history": history, "updated_at": ts},
        )
        insert_pm_decision_queue_event(
            conn,
            {
                "created_at": ts,
                "item_id": item_id,
                "ticker": ticker,
                "event_type": "defer",
                "actor": actor,
                "payload": {"reason": reason},
            },
        )
    return updated
