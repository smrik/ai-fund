"""Offline contract tests for accounting ledger merge and PM queue translation."""

from __future__ import annotations

import pytest

from src.contracts.pm_decision_queue import PMDecisionQueueItemType, ProposalMode
from src.stage_04_pipeline.accounting_ledger import (
    finding_fingerprint,
    merge_findings_into_ledger,
    translate_accounting_ledger_to_queue_items,
)
from src.stage_04_pipeline.accounting_validation import validate_accounting_finding
from src.stage_04_pipeline.accounting_evidence_runner import run_repair_cycle


def _candidate(
    *,
    finding_id: str,
    focus_key: str = "qoe_nonrecurring",
    topic: str = "qoe",
    line_item: str = "Restructuring charges",
    period: str = "2025-06-30",
    proposed_driver: str = "ebit_margin_target",
    claim_driver: str | None = None,
    proposed_value: float | None = 0.41,
    direction: str | None = "up",
    anchors: list[str] | None = None,
    valuation_treatment: str = "normalized_ebit",
    claim: str | None = None,
) -> dict:
    return {
        "finding_id": finding_id,
        "topic": topic,
        "focus_key": focus_key,
        "finding_status": "candidate",
        "finding_type": "restructuring_adjustment",
        "line_item": line_item,
        "claim": claim or f"{line_item} should adjust {proposed_driver}",
        "claim_driver_field": claim_driver or proposed_driver,
        "proposed_driver_field": proposed_driver,
        "direction": direction,
        "proposed_value": proposed_value,
        "period": period,
        "booked_or_disclosed_status": "booked",
        "accounting_treatment": "normalize_out_nonrecurring",
        "valuation_treatment": valuation_treatment,
        "evidence_anchor_ids": anchors or ["fact:restruct", "snippet:note"],
        "citation_text": "Restructuring charges of $1.2B were recognized.",
        "confidence": "medium",
        "pm_question": "Should the non-recurring charge be normalized out of EBIT?",
        "what_would_change_mind": "Evidence the charge is recurring operating cost.",
        "materiality_rationale": "Charge is large relative to annual EBIT.",
    }


def _packet() -> dict:
    return {
        "ticker": "MSFT",
        "topic": "qoe",
        "allowed_driver_fields": ["ebit_margin_start", "ebit_margin_target", "net_debt"],
        "facts": [{"fact_id": "fact:restruct", "fact_name": "restructuring_charge", "value": 1.2e9}],
        "snippets": [
            {
                "snippet_id": "snippet:note",
                "source_ref_id": "filing:msft:10-k",
                "text": "Restructuring charges of $1.2B were recognized.",
            }
        ],
    }


def test_fingerprint_is_stable_and_ignores_claim_prose():
    a = _candidate(finding_id="finding:a", claim="First wording of the claim.")
    b = _candidate(finding_id="finding:b", claim="Different wording of the same claim.")
    assert finding_fingerprint(a) == finding_fingerprint(b)


def test_fingerprint_changes_when_driver_or_anchors_change():
    base = _candidate(finding_id="finding:base")
    other_driver = _candidate(finding_id="finding:drv", proposed_driver="ebit_margin_start")
    other_anchors = _candidate(finding_id="finding:anc", anchors=["fact:restruct"])
    assert finding_fingerprint(base) != finding_fingerprint(other_driver)
    assert finding_fingerprint(base) != finding_fingerprint(other_anchors)


def test_merge_marks_duplicates_and_retains_provenance():
    primary = _candidate(finding_id="finding:primary")
    duplicate = _candidate(finding_id="finding:duplicate", claim="Same economics, different prose.")
    ledger = merge_findings_into_ledger(
        ticker="MSFT",
        findings=[primary, duplicate],
    )

    assert len(ledger.entries) == 2
    statuses = {entry.finding_id: entry.ledger_status for entry in ledger.entries}
    assert statuses["finding:primary"] == "candidate"
    assert statuses["finding:duplicate"] == "duplicate"
    dup_entry = next(entry for entry in ledger.entries if entry.finding_id == "finding:duplicate")
    assert dup_entry.duplicate_of == "finding:primary"
    assert dup_entry.fingerprint == finding_fingerprint(primary)


def test_merge_groups_contradictory_findings_without_resolving():
    up = _candidate(finding_id="finding:up", proposed_value=0.42, direction="up")
    down = _candidate(finding_id="finding:down", proposed_value=0.30, direction="down")
    ledger = merge_findings_into_ledger(ticker="MSFT", findings=[up, down])

    assert len(ledger.conflict_groups) == 1
    group = ledger.conflict_groups[0]
    assert set(group["finding_ids"]) == {"finding:up", "finding:down"}
    statuses = {entry.finding_id: entry.ledger_status for entry in ledger.entries}
    assert statuses["finding:up"] == "conflict"
    assert statuses["finding:down"] == "conflict"


def test_no_adjustment_and_missing_evidence_stay_out_of_mutation_queue():
    no_adj = {
        "finding_id": "finding:noadj",
        "topic": "qoe",
        "focus_key": "qoe_cash_conversion",
        "finding_status": "no_adjustment_identified",
        "finding_type": "cash_conversion_review",
        "line_item": "Working capital",
        "claim": "No adjustment identified for WC conversion.",
        "no_adjustment_reason": "Accruals are within normal range.",
        "valuation_treatment": "none",
        "evidence_anchor_ids": ["fact:restruct"],
    }
    missing = {
        "finding_id": "finding:missing",
        "topic": "segments_and_disclosure",
        "focus_key": "segments_disclosure",
        "finding_status": "missing_evidence",
        "finding_type": "segment_margin_review",
        "line_item": "Segment profit",
        "claim": "Segment profit disclosure not located.",
        "missing_evidence_reason": "No note_segments section in packet.",
        "valuation_treatment": "none",
    }
    ledger = merge_findings_into_ledger(ticker="MSFT", findings=[no_adj, missing])
    items = translate_accounting_ledger_to_queue_items(
        ledger,
        ticker="MSFT",
        profile_name="accounting_qoe",
        evidence_packet_id=42,
    )
    assert items == []
    assert {entry.ledger_status for entry in ledger.entries} == {
        "no_adjustment_identified",
        "missing_evidence",
    }


def test_distinct_valid_candidates_each_become_queue_items():
    sbc = _candidate(
        finding_id="finding:sbc",
        focus_key="qoe_opex_and_compensation",
        line_item="Stock-based compensation",
        proposed_driver="tax_rate_target",
        proposed_value=0.19,
    )
    restruct = _candidate(finding_id="finding:restruct")
    ledger = merge_findings_into_ledger(ticker="MSFT", findings=[sbc, restruct])
    items = translate_accounting_ledger_to_queue_items(
        ledger,
        ticker="MSFT",
        profile_name="accounting_qoe",
        evidence_packet_id=42,
    )

    assert len(items) == 2
    assert all(item.item_type == PMDecisionQueueItemType.assumption_change_pack for item in items)
    fields = {
        item.proposal_pack.proposals[0].assumption_name
        for item in items
        if item.proposal_pack is not None
    }
    assert fields == {"tax_rate_target", "ebit_margin_target"}
    for item in items:
        assert item.metadata["ledger_status"] == "candidate"
        assert item.metadata["finding_id"]
        assert item.metadata["fingerprint"]
        assert item.metadata["valuation_treatment"] == "normalized_ebit"
        assert item.evidence_packet_ids == ["42"]


def test_historical_owned_driver_cannot_become_a_mutation():
    """`*_start` drivers are owned by reconciled history, not by the judgment layer.

    `assumption_registry` marks `ebit_margin_start` as ``owner=historical`` with
    ``apply_supported=False``, so it was removed from
    ``AGENT_PROPOSABLE_ASSUMPTION_FIELDS``. A finding that proposes one stays visible
    as an advisory instead of becoming an applicable assumption change.
    """

    historical = _candidate(
        finding_id="finding:margin-start",
        focus_key="qoe_opex_and_compensation",
        line_item="Stock-based compensation",
        proposed_driver="ebit_margin_start",
        proposed_value=0.38,
    )
    ledger = merge_findings_into_ledger(ticker="MSFT", findings=[historical])
    items = translate_accounting_ledger_to_queue_items(
        ledger,
        ticker="MSFT",
        profile_name="accounting_qoe",
        evidence_packet_id=42,
    )

    assert len(items) == 1
    assert items[0].item_type == PMDecisionQueueItemType.advisory_finding
    assert items[0].proposal_pack is None
    assert items[0].metadata["queue_reason"] == "driver_not_proposable_or_missing"
    # The reasoning stays reviewable; only the mutation is withheld.
    assert items[0].metadata["proposed_driver_field"] == "ebit_margin_start"


def test_scenario_only_candidate_becomes_advisory_not_mutation():
    contingency = _candidate(
        finding_id="finding:tax",
        focus_key="tax_contingencies",
        topic="contingencies_and_taxes",
        line_item="Uncertain tax position",
        proposed_driver="tax_rate_target",
        proposed_value=None,
        valuation_treatment="scenario_only",
        claim="UTP may matter in a downside scenario.",
    )
    ledger = merge_findings_into_ledger(ticker="MSFT", findings=[contingency])
    items = translate_accounting_ledger_to_queue_items(
        ledger,
        ticker="MSFT",
        profile_name="accounting_contingencies_and_taxes",
        evidence_packet_id=7,
    )
    assert len(items) == 1
    assert items[0].item_type == PMDecisionQueueItemType.advisory_finding
    assert items[0].proposal_pack is None
    assert items[0].metadata["valuation_treatment"] == "scenario_only"


def test_novel_model_change_is_preserved_as_an_explicit_advisory():
    finding = _candidate(
        finding_id="finding:model-change",
        focus_key="qoe_revenue",
        line_item="Capitalized contract acquisition costs",
        proposed_driver="contract_cost_asset",
        proposed_value=2.4e9,
        valuation_treatment="historical_recast",
        claim="Historical operating expense should be recast for multi-period contract costs.",
    )
    finding["model_change_required"] = True
    finding["model_change_request"] = (
        "Add a contract-cost asset and amortization schedule, recast historical EBIT, "
        "and use normalized EBIT as the forecast starting point."
    )

    ledger = merge_findings_into_ledger(ticker="MSFT", findings=[finding])
    items = translate_accounting_ledger_to_queue_items(
        ledger,
        ticker="MSFT",
        profile_name="accounting_qoe",
        evidence_packet_id=42,
    )

    assert len(items) == 1
    assert items[0].item_type == PMDecisionQueueItemType.advisory_finding
    assert items[0].metadata["queue_reason"] == "model_change_required"
    assert items[0].metadata["model_change_required"] is True
    assert "amortization schedule" in items[0].metadata["model_change_request"]


def test_conflict_candidates_are_queueable_but_not_auto_applicable():
    up = _candidate(finding_id="finding:up", proposed_value=0.42)
    down = _candidate(finding_id="finding:down", proposed_value=0.30)
    ledger = merge_findings_into_ledger(ticker="MSFT", findings=[up, down])
    items = translate_accounting_ledger_to_queue_items(
        ledger,
        ticker="MSFT",
        profile_name="accounting_qoe",
        evidence_packet_id=9,
    )
    assert len(items) == 2
    assert all(item.item_type == PMDecisionQueueItemType.advisory_finding for item in items)
    assert all(item.metadata["ledger_status"] == "conflict" for item in items)
    assert all(item.metadata.get("conflict_group_id") for item in items)
    assert all(item.proposal_pack is None for item in items)


def test_duplicate_does_not_create_second_queue_item():
    primary = _candidate(finding_id="finding:primary")
    duplicate = _candidate(finding_id="finding:duplicate")
    ledger = merge_findings_into_ledger(ticker="MSFT", findings=[primary, duplicate])
    items = translate_accounting_ledger_to_queue_items(
        ledger,
        ticker="MSFT",
        profile_name="accounting_qoe",
        evidence_packet_id=3,
    )
    assert len(items) == 1
    assert items[0].metadata["finding_id"] == "finding:primary"
    assert items[0].metadata["duplicate_finding_ids"] == ["finding:duplicate"]


def test_target_proposal_uses_finding_proposed_value():
    finding = _candidate(finding_id="finding:target", proposed_value=0.405)
    ledger = merge_findings_into_ledger(ticker="MSFT", findings=[finding])
    items = translate_accounting_ledger_to_queue_items(
        ledger,
        ticker="MSFT",
        profile_name="accounting_qoe",
        evidence_packet_id=1,
    )
    proposal = items[0].proposal_pack.proposals[0]
    assert proposal.proposal_mode == ProposalMode.target
    assert proposal.proposed_target_value == pytest.approx(0.405)
    assert proposal.assumption_name == "ebit_margin_target"


def test_item_123_driver_mismatch_is_repaired_before_queue_creation():
    """Semantic regression: wrong driver must not enter the mutation queue."""
    packet = _packet()
    bad = {
        "finding_id": "finding:item-123",
        "topic": "qoe",
        "focus_key": "qoe_nonrecurring",
        "finding_status": "candidate",
        "finding_type": "margin_target_review",
        "line_item": "EBIT margin target",
        "claim": "The 33.2% EBIT margin target is below the historical average.",
        "claim_driver_field": "ebit_margin_target",
        "proposed_driver_field": "ebit_margin_start",
        "valuation_treatment": "normalized_ebit",
        "proposed_value": 0.4503,
        "period": "2026-03-31",
        "evidence_anchor_ids": ["fact:restruct", "snippet:note"],
        "citation_text": "Restructuring charges of $1.2B were recognized.",
    }
    assert validate_accounting_finding(bad, packet).valid is False

    def repair_callable(request):
        repaired = dict(request["original_finding"])
        repaired["proposed_driver_field"] = repaired["claim_driver_field"]
        return repaired

    repaired_result = run_repair_cycle(bad, packet=packet, repair_callable=repair_callable)
    assert repaired_result.status == "repaired"
    assert repaired_result.finding is not None
    assert repaired_result.finding["proposed_driver_field"] == "ebit_margin_target"

    unrepaired_ledger = merge_findings_into_ledger(
        ticker="MSFT",
        findings=[],
        rejected_findings=[bad],
    )
    unrepaired_items = translate_accounting_ledger_to_queue_items(
        unrepaired_ledger,
        ticker="MSFT",
        profile_name="accounting_qoe",
        evidence_packet_id=123,
    )
    assert unrepaired_items == []
    assert unrepaired_ledger.entries[0].ledger_status == "rejected_after_repair"

    ledger = merge_findings_into_ledger(ticker="MSFT", findings=[repaired_result.finding])
    items = translate_accounting_ledger_to_queue_items(
        ledger,
        ticker="MSFT",
        profile_name="accounting_qoe",
        evidence_packet_id=123,
    )
    assert len(items) == 1
    assert items[0].item_type == PMDecisionQueueItemType.assumption_change_pack
    assert items[0].proposal_pack.proposals[0].assumption_name == "ebit_margin_target"


def test_multiple_queue_candidates_preserve_ledger_links_in_metadata():
    a = _candidate(finding_id="finding:a", line_item="SBC")
    b = _candidate(
        finding_id="finding:b",
        line_item="Impairment",
        proposed_driver="ebit_margin_start",
        proposed_value=0.36,
    )
    ledger = merge_findings_into_ledger(ticker="MSFT", findings=[a, b])
    items = translate_accounting_ledger_to_queue_items(
        ledger,
        ticker="MSFT",
        profile_name="accounting_qoe",
        evidence_packet_id=5,
    )
    assert len(items) == 2
    for item in items:
        assert "ledger_entry_id" in item.metadata
        assert "accounting_treatment" in item.metadata
        assert item.metadata.get("observation_id")  # required for packet-backed items
