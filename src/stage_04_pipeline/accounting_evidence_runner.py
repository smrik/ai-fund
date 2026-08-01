"""Focused accounting evidence orchestration.

The judgment and repair callables stay transport-agnostic. This module connects
the deterministic packet, validation, ledger, and PM queue seams without
mutating valuation inputs.
"""

from __future__ import annotations

from dataclasses import dataclass
import sqlite3
from typing import Any, Callable

from db.loader import insert_pm_decision_queue_item
from src.contracts.accounting_evidence import AccountingFocusKey
from src.contracts.pm_decision_queue import PMDecisionQueueItem
from src.stage_04_pipeline.accounting_focus import (
    select_accounting_focus,
    to_focused_accounting_packet,
)
from src.stage_04_pipeline.accounting_ledger import (
    AccountingAdjustmentLedger,
    translate_accounting_findings_to_queue_items,
)
from src.stage_04_pipeline.accounting_validation import (
    FocusFindingRepairResult,
    FocusRepairResult,
    RepairCycleResult,
    run_focus_repair_cycle,
    run_repair_cycle,
)


@dataclass(frozen=True)
class AccountingEvidenceTrialResult:
    focused_packet: Any
    repair_result: FocusRepairResult
    ledger: AccountingAdjustmentLedger
    queue_items: list[PMDecisionQueueItem]
    persisted_queue_item_ids: list[int]


def _persist_queue_item(
    conn: sqlite3.Connection,
    item: PMDecisionQueueItem,
) -> int:
    row = item.model_dump(mode="json")
    row.setdefault("valuation_impact_bucket", None)
    return insert_pm_decision_queue_item(conn, row)


def run_accounting_evidence_trial(
    *,
    source_packet: Any,
    focus_key: AccountingFocusKey | str,
    judgment_callable: Callable[[dict[str, Any]], Any],
    repair_callable: Callable[[dict[str, Any]], Any],
    conn: sqlite3.Connection | None = None,
) -> AccountingEvidenceTrialResult:
    """Run one focused accounting judgment through validation and the PM queue."""

    context = select_accounting_focus(source_packet, focus_key)
    focused_packet = to_focused_accounting_packet(context, source_packet)
    packet_payload = focused_packet.model_dump(mode="json")
    raw_response = judgment_callable(packet_payload)
    repair_result = run_focus_repair_cycle(
        raw_response,
        packet=packet_payload,
        repair_callable=repair_callable,
    )

    accepted_findings = list((repair_result.response or {}).get("findings") or [])
    rejected_findings = [
        result.finding
        for result in repair_result.finding_results
        if result.status == "rejected_after_repair"
    ]
    packet_id = focused_packet.base_packet_id or focused_packet.packet_id
    ledger, queue_items = translate_accounting_findings_to_queue_items(
        ticker=focused_packet.ticker,
        findings=accepted_findings,
        rejected_findings=rejected_findings,
        evidence_packet_id=packet_id,
    )
    persisted_ids = (
        [_persist_queue_item(conn, item) for item in queue_items]
        if conn is not None
        else []
    )
    return AccountingEvidenceTrialResult(
        focused_packet=focused_packet,
        repair_result=repair_result,
        ledger=ledger,
        queue_items=queue_items,
        persisted_queue_item_ids=persisted_ids,
    )


__all__ = [
    "AccountingEvidenceTrialResult",
    "FocusFindingRepairResult",
    "FocusRepairResult",
    "RepairCycleResult",
    "run_accounting_evidence_trial",
    "run_focus_repair_cycle",
    "run_repair_cycle",
]
