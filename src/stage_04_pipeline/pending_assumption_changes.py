from __future__ import annotations

from dataclasses import replace as dc_replace
from datetime import datetime, timezone
from typing import Any

from db.schema import create_tables, get_connection
from src.contracts.assumption_policy import (
    PendingAssumptionChange,
    PendingAssumptionSourceType,
    PendingAssumptionStackPreview,
    QoEProposal,
    qoe_proposal_to_pending_change_payload,
)
from src.stage_02_valuation.professional_dcf import default_scenario_specs, run_dcf_professional


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_pending_assumption_change(change: PendingAssumptionChange) -> PendingAssumptionChange:
    payload = change.model_copy(update={"created_at": change.created_at or _now(), "updated_at": _now()})
    with get_connection() as conn:
        create_tables(conn)
        from db.loader import insert_pending_assumption_change

        change_id = insert_pending_assumption_change(
            conn,
            {
                **payload.model_dump(),
                "source_type": payload.source_type.value,
                "status": payload.status.value,
            },
        )
    return payload.model_copy(update={"change_id": change_id})


def list_pending_assumption_changes(ticker: str, status: str | None = "pending") -> list[PendingAssumptionChange]:
    with get_connection() as conn:
        create_tables(conn)
        from db.loader import load_pending_assumption_changes

        rows = load_pending_assumption_changes(conn, ticker=ticker, status=status)
    return [PendingAssumptionChange.model_validate(row) for row in rows]


def write_pending_changes_from_recommendations(ticker: str, recommendations: list[Any]) -> list[PendingAssumptionChange]:
    created: list[PendingAssumptionChange] = []
    existing = {
        (change.assumption_name, change.source_ref, round(float(change.proposed_value), 12))
        for change in list_pending_assumption_changes(ticker)
    }
    for rec in recommendations:
        proposed = getattr(rec, "proposed_value", None)
        if not isinstance(proposed, (int, float)):
            continue
        key = (str(getattr(rec, "field", "")), str(getattr(rec, "agent", "agent")), round(float(proposed), 12))
        if key in existing:
            continue
        if str(getattr(rec, "agent", "")).lower() == "qoe" and str(getattr(rec, "field", "")) == "ebit_margin_start":
            qoe_proposal_raw = (getattr(rec, "qoe_proposal", None) or {}).copy() if isinstance(getattr(rec, "qoe_proposal", None), dict) else None
            if qoe_proposal_raw:
                proposal = QoEProposal.model_validate(qoe_proposal_raw)
                payload = qoe_proposal_to_pending_change_payload(proposal)
                change = PendingAssumptionChange(
                    ticker=payload["ticker"],
                    assumption_name=payload["assumption_name"],
                    current_value=getattr(rec, "current_value", None),
                    proposed_value=float(proposed),
                    source_type=PendingAssumptionSourceType.agent,
                    source_ref=payload["source_ref"],
                    confidence=payload["confidence"],
                    rationale=payload["rationale"],
                    citation=payload["citation"],
                    metadata={**payload.get("metadata", {}), "legacy_recommendation_status": getattr(rec, "status", "pending")},
                )
            else:
                change = PendingAssumptionChange(
                    ticker=ticker,
                    assumption_name=str(getattr(rec, "field", "")),
                    current_value=getattr(rec, "current_value", None),
                    proposed_value=float(proposed),
                    source_type=PendingAssumptionSourceType.agent,
                    source_ref=str(getattr(rec, "agent", "agent")),
                    confidence=getattr(rec, "confidence", None),
                    rationale=getattr(rec, "rationale", None),
                    citation=getattr(rec, "citation", None),
                    metadata={"legacy_recommendation_status": getattr(rec, "status", "pending")},
                )
        else:
            change = PendingAssumptionChange(
                ticker=ticker,
                assumption_name=str(getattr(rec, "field", "")),
                current_value=getattr(rec, "current_value", None),
                proposed_value=float(proposed),
                source_type=PendingAssumptionSourceType.agent,
                source_ref=str(getattr(rec, "agent", "agent")),
                confidence=getattr(rec, "confidence", None),
                rationale=getattr(rec, "rationale", None),
                citation=getattr(rec, "citation", None),
                metadata={"legacy_recommendation_status": getattr(rec, "status", "pending")},
            )
        created.append(create_pending_assumption_change(change))
        existing.add(key)
    return created


def _run_scenarios(drivers: Any) -> dict[str, float | None]:
    result: dict[str, float | None] = {}
    for spec in default_scenario_specs():
        try:
            dcf = run_dcf_professional(drivers, spec)
            result[spec.name] = round(dcf.intrinsic_value_per_share, 2)
        except Exception:
            result[spec.name] = None
    return result


def preview_pending_assumption_stack(
    ticker: str,
    change_ids: list[int],
    *,
    manual_values: dict[str, float] | None = None,
) -> PendingAssumptionStackPreview:
    from src.stage_02_valuation.input_assembler import build_valuation_inputs

    ticker = ticker.upper().strip()
    inputs = build_valuation_inputs(ticker)
    if inputs is None:
        return PendingAssumptionStackPreview(ticker=ticker, selected_change_ids=change_ids)
    pending = list_pending_assumption_changes(ticker)
    selected = [change for change in pending if change.change_id in set(change_ids)]
    current_iv = _run_scenarios(inputs.drivers)
    resolved: dict[str, dict[str, Any]] = {}
    conflicts: list[dict[str, Any]] = []
    updates: dict[str, float] = {}
    for change in selected:
        field = change.assumption_name
        if field in updates:
            conflicts.append({"assumption_name": field, "change_id": change.change_id, "reason": "multiple proposed values"})
            continue
        if not hasattr(inputs.drivers, field):
            conflicts.append({"assumption_name": field, "change_id": change.change_id, "reason": "unknown ForecastDrivers field"})
            continue
        updates[field] = float(change.proposed_value)
        resolved[field] = {
            "mode": "pending_change",
            "change_id": change.change_id,
            "current_value": getattr(inputs.drivers, field),
            "proposed_value": change.proposed_value,
            "source_ref": change.source_ref,
        }
    for field, value in (manual_values or {}).items():
        if hasattr(inputs.drivers, field):
            updates[field] = float(value)
            resolved[field] = {
                "mode": "manual",
                "current_value": getattr(inputs.drivers, field),
                "proposed_value": value,
                "source_ref": "manual_preview",
            }
    proposed_drivers = dc_replace(inputs.drivers, **updates) if updates else inputs.drivers
    proposed_iv = _run_scenarios(proposed_drivers)
    delta_pct: dict[str, float | None] = {}
    for scenario, current in current_iv.items():
        proposed = proposed_iv.get(scenario)
        if current and current > 0 and proposed is not None:
            delta_pct[scenario] = round((proposed / current - 1.0) * 100.0, 1)
        else:
            delta_pct[scenario] = None
    return PendingAssumptionStackPreview(
        ticker=ticker,
        selected_change_ids=change_ids,
        current_iv=current_iv,
        proposed_iv=proposed_iv,
        delta_pct=delta_pct,
        resolved_values=resolved,
        conflicts=conflicts,
    )


def apply_pending_assumption_stack(
    ticker: str,
    change_ids: list[int],
    *,
    actor: str = "api",
) -> dict[str, Any]:
    applied_at = _now()
    approval_ref = f"assumption_register_apply:{ticker.upper()}:{applied_at}"
    with get_connection() as conn:
        create_tables(conn)
        from db.loader import apply_pending_assumption_changes, insert_assumption_register_audit

        approved = apply_pending_assumption_changes(
            conn,
            ticker=ticker,
            change_ids=change_ids,
            actor=actor,
            applied_at=applied_at,
            approval_ref=approval_ref,
        )
        audit_rows = []
        for row in approved:
            audit_rows.append(
                {
                    "event_ts": applied_at,
                    "actor": actor,
                    "actor_type": "pm" if actor != "system" else "system",
                    "entity_type": "ticker",
                    "entity_id": ticker.upper(),
                    "ticker": ticker.upper(),
                    "assumption_name": row["assumption_name"],
                    "scope": "dcf",
                    "event_type": "pm_override_applied",
                    "changed_fields": {"current_value": {"prior": None, "new": row["proposed_value"]}},
                    "valuation_impact": None,
                    "reason": row.get("source_ref"),
                }
            )
        insert_assumption_register_audit(conn, audit_rows)
    return {
        "ticker": ticker.upper(),
        "applied_count": len(approved),
        "change_ids": [row["change_id"] for row in approved],
        "approval_ref": approval_ref,
        "actor": actor,
    }


def approved_assumption_overrides_for_ticker(ticker: str) -> dict[str, float]:
    try:
        with get_connection() as conn:
            create_tables(conn)
            from db.loader import load_approved_assumption_entries

            rows = load_approved_assumption_entries(conn, ticker)
    except Exception:
        return {}
    return {row["assumption_name"]: float(row["value"]) for row in rows}
