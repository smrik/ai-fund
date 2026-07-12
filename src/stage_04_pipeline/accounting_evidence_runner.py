"""Transport-agnostic orchestration for focused accounting evidence."""

from dataclasses import asdict
from typing import Any, Callable

from src.contracts.accounting_evidence import AccountingFocusKey
from src.stage_03_judgment.focused_accounting_agent import FocusedAccountingAgent
from src.stage_04_pipeline.accounting_focus import select_accounting_focus
from src.stage_04_pipeline.accounting_validation import (
    FocusFindingRepairResult,
    FocusRepairResult,
    RepairCycleResult,
    run_focus_repair_cycle,
    run_repair_cycle,
)


def run_focused_accounting_analysis(
    packet: Any,
    focus_key: AccountingFocusKey | str,
    *,
    agent_factory: Callable[[], FocusedAccountingAgent] = FocusedAccountingAgent,
) -> dict[str, Any]:
    """Run one bounded focus without persistence or valuation mutation."""

    context = select_accounting_focus(packet, focus_key)
    agent = agent_factory()
    result = agent.analyze_focus(context)
    return {
        "ticker": context.ticker,
        "focus_key": context.focus_key.value,
        "parent_topic": context.parent_topic.value,
        "context": context.model_dump(mode="json"),
        "result": asdict(result),
        "artifact": dict(agent.last_focused_accounting_artifact),
        "approval_required": True,
        "valuation_inputs_mutated": False,
    }


__all__ = [
    "FocusFindingRepairResult",
    "FocusRepairResult",
    "RepairCycleResult",
    "run_focus_repair_cycle",
    "run_focused_accounting_analysis",
    "run_repair_cycle",
]

