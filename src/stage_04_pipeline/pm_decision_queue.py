from __future__ import annotations

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


def _pack_to_manual_values(
    pack: dict[str, Any] | None,
    ticker: str,
) -> tuple[dict[str, float], list[str]]:
    """Convert an active proposal pack to absolute manual_values for preview_pending_assumption_stack.

    Returns (manual_values, skipped_fields) where skipped_fields contains assumption names
    for delta proposals that could not be resolved (e.g. no valuation inputs).
    """
    if not pack:
        return {}, []
    values: dict[str, float] = {}
    skipped: list[str] = []

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
        if mode == "target" and proposal.get("proposed_target_value") is not None:
            values[name] = float(proposal["proposed_target_value"])
        elif mode == "delta" and proposal.get("proposed_delta") is not None:
            drivers = _get_drivers()
            if drivers is not None and hasattr(drivers, name):
                current = float(getattr(drivers, name))
                values[name] = current + float(proposal["proposed_delta"])
            else:
                # Cannot resolve absolute value — skip from preview.
                skipped.append(str(name))
    return values, skipped


def preview_pm_decision_queue_item(
    ticker: str,
    item_id: int,
) -> dict[str, Any]:
    ticker = ticker.upper().strip()
    with get_connection() as conn:
        create_tables(conn)
        item = _load_queue_item_or_raise(conn, ticker, item_id)
    manual_values, skipped_fields = _pack_to_manual_values(_active_pack(item), ticker)
    preview = preview_pending_assumption_stack(ticker, change_ids=[], manual_values=manual_values)
    return {"item": item, "preview": preview, "skipped_fields": skipped_fields}


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
        pack = _active_pack(item)
        pending_ids: list[int] = []
        if pack:
            for idx, proposal in enumerate(pack.get("proposals") or [], start=1):
                name = proposal.get("assumption_name")
                if not name:
                    continue
                mode = proposal.get("proposal_mode")
                if mode == "target":
                    proposed_value = proposal.get("proposed_target_value")
                elif mode == "delta":
                    proposed_value = proposal.get("proposed_delta")
                else:
                    proposed_value = None
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
                            "proposal_mode": mode,
                            "original_proposal_pack": item.get("proposal_pack"),
                            "pm_edited_proposal_pack": item.get("pm_edited_proposal_pack"),
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

        approved_pack = pack
        adapter_links = dict(item.get("adapter_links") or {})
        adapter_links["pending_assumption_change_ids"] = pending_ids
        adapter_links["approval_ref"] = apply_result.get("approval_ref")

        history = _append_decision_history(
            item,
            {
                "event": "approve",
                "actor": actor,
                "event_ts": ts,
                "pending_assumption_change_ids": pending_ids,
                "approval_ref": apply_result.get("approval_ref"),
                "approved_proposal_pack": approved_pack,
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
