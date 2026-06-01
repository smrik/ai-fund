from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from db.schema import create_tables, get_connection
from src.contracts.assumption_policy import PendingAssumptionChange, PendingAssumptionSourceType
from src.contracts.pm_decision_queue import AssumptionChangePack
from src.stage_04_pipeline.pending_assumption_changes import (
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


def _preview_fingerprint(resolved_pack: dict[str, Any] | None, skipped_fields: list[str]) -> str:
    payload = {
        "resolved_pack": resolved_pack or {},
        "skipped_fields": sorted(skipped_fields),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _proposal_value(proposal: dict[str, Any]) -> float | None:
    if proposal.get("proposed_target_value") is not None:
        return float(proposal["proposed_target_value"])
    if proposal.get("proposed_delta") is not None:
        return float(proposal["proposed_delta"])
    return None


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
                    "proposed_value": _proposal_value(proposal),
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
        if len(entries) < 2:
            continue
        profile_names = sorted({str(entry.get("profile_name")) for entry in entries if entry.get("profile_name")})
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
        resolved_pack, manual_values, skipped_fields = _resolve_active_pack(_active_pack(item), ticker)
        adapter_links = dict(item.get("adapter_links") or {})
        if item.get("item_type") == "assumption_change_pack":
            previewed_at = _now()
            preview_fingerprint = _preview_fingerprint(resolved_pack, skipped_fields)
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
        from db.loader import insert_pm_decision_queue_event, update_pm_decision_queue_item

        item = _load_queue_item_or_raise(conn, ticker, item_id)
        resolved_pack, _, skipped_fields = _resolve_active_pack(_active_pack(item), ticker)
        if item.get("item_type") == "assumption_change_pack":
            adapter_links = dict(item.get("adapter_links") or {})
            expected_fingerprint = _preview_fingerprint(resolved_pack, skipped_fields)
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

        apply_result = apply_pending_assumption_stack(ticker, pending_ids, actor=actor) if pending_ids else {
            "ticker": ticker,
            "applied_count": 0,
            "change_ids": [],
            "approval_ref": None,
            "actor": actor,
        }

        approved_pack = resolved_pack if resolved_pack and resolved_pack.get("proposals") else None
        adapter_links = dict(item.get("adapter_links") or {})
        adapter_links["pending_assumption_change_ids"] = pending_ids
        adapter_links["approval_ref"] = apply_result.get("approval_ref")
        adapter_links["skipped_fields"] = skipped_fields

        history = _append_decision_history(
            item,
            {
                "event": "approve",
                "actor": actor,
                "event_ts": ts,
                "pending_assumption_change_ids": pending_ids,
                "approval_ref": apply_result.get("approval_ref"),
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
                    "approval_ref": apply_result.get("approval_ref"),
                },
            },
        )
    return updated


def reject_pm_decision_queue_item(
    ticker: str,
    item_id: int,
    *,
    actor: str,
    reason: str | None = None,
) -> dict[str, Any]:
    ticker = ticker.upper().strip()
    ts = _now()
    with get_connection() as conn:
        create_tables(conn)
        from db.loader import insert_pm_decision_queue_event, update_pm_decision_queue_item

        item = _load_queue_item_or_raise(conn, ticker, item_id)
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
    reason: str | None = None,
) -> dict[str, Any]:
    ticker = ticker.upper().strip()
    ts = _now()
    with get_connection() as conn:
        create_tables(conn)
        from db.loader import insert_pm_decision_queue_event, update_pm_decision_queue_item

        item = _load_queue_item_or_raise(conn, ticker, item_id)
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
