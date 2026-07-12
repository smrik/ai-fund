from __future__ import annotations

import pytest

from src.contracts.accounting_evidence import (
    AccountingEvidenceAnchor,
    AccountingSourceFact,
    AccountingFinding,
    AccountingFocusKey,
    AccountingFocusResponse,
    AccountingFindingStatus,
    AccountingPacketStatus,
    AccountingTopic,
    FocusedAccountingEvidencePacket,
    ValuationTreatment,
)
from src.stage_04_pipeline.accounting_evidence_runner import (
    run_focus_repair_cycle,
    run_repair_cycle,
)
from src.stage_04_pipeline.accounting_validation import (
    build_repair_request,
    validate_accounting_finding,
)


def _packet() -> dict:
    return {
        "ticker": "MSFT",
        "current_model_fields": {"ebit_margin_target": 0.332},
        "topic": "qoe",
        "allowed_driver_fields": ["ebit_margin_start", "ebit_margin_target"],
        "facts": [
            {
                "fact_id": "fact:margin_target",
                "fact_name": "model_assumption_ebit_margin_target",
                "metadata": {
                    "fact_role": "current_model_driver",
                    "driver_field": "ebit_margin_target",
                    "period_type": "forecast",
                },
                "value": 0.332,
            }
        ],
        "snippets": [
            {
                "snippet_id": "snippet:margin_history",
                "source_ref_id": "filing:msft:10-k",
                "text": "EBIT margin rose to 45.6%; the three-year average was 44.0%.",
            }
        ],
    }


def _bad_target_finding() -> dict:
    return {
        "topic": "qoe",
        "finding_status": "candidate",
        "finding_type": "margin_target_review",
        "line_item": "EBIT margin target",
        "claim": "The 33.2% EBIT margin target is below the 44.0% historical average.",
        "claim_driver_field": "ebit_margin_target",
        "proposed_driver_field": "ebit_margin_start",
        "valuation_treatment": "normalized_ebit",
        "proposed_value": 0.332,
        "accounting_treatment": "normalize",
        "evidence_anchor_ids": ["fact:margin_target", "snippet:margin_history"],
        "citation_text": "EBIT margin rose to 45.6%; the three-year average was 44.0%.",
        "materiality_rationale": "The difference is material to the modeled EBIT margin.",
        "pm_question": "Should the supported forward margin input be reviewed?",
        "what_would_change_mind": "A source showing the current target is already normalized would change the view.",
    }


def test_accounting_contract_preserves_focused_packet_and_finding_fields():
    packet = FocusedAccountingEvidencePacket(
        packet_id="accounting:MSFT:qoe",
        ticker="msft",
        topic=AccountingTopic.qoe,
        allowed_driver_fields=["ebit_margin_target"],
        source_refs=[
            {
                "source_ref_id": "filing:msft:10-k",
                "source_kind": "10-K",
                "source_label": "MSFT 10-K",
                "source_locator": "edgar://MSFT/10-K",
            }
        ],
        facts=[
            AccountingSourceFact(
                fact_id="fact:margin_target",
                fact_name="model_assumption_ebit_margin_target",
                value=0.332,
                currency="USD",
                period="2026-03-31",
            )
        ],
        evidence_anchors=[
            AccountingEvidenceAnchor(
                anchor_id="snippet:margin_history",
                citation_text="The three-year average EBIT margin was 44.0%.",
            )
        ],
    )
    finding = AccountingFinding(
        topic=AccountingTopic.qoe,
        finding_status=AccountingFindingStatus.candidate,
        finding_type="margin_target_review",
        line_item="EBIT margin target",
        claim="The margin target needs review.",
        claim_driver_field="ebit_margin_target",
        proposed_driver_field="ebit_margin_target",
        valuation_treatment=ValuationTreatment.normalized_ebit,
        evidence_anchor_ids=["snippet:margin_history"],
        citation_text="The three-year average EBIT margin was 44.0%.",
    )

    assert packet.ticker == "MSFT"
    assert packet.topic == AccountingTopic.qoe
    assert finding.claim_driver_field == finding.proposed_driver_field
    assert finding.model_dump(mode="json")["evidence_anchor_ids"] == ["snippet:margin_history"]
    persisted = packet.as_evidence_packet()
    assert persisted.packet_kind.value == "accounting"
    assert persisted.profile_name == "accounting:qoe"
    assert persisted.facts[0].metadata["period"] == "2026-03-31"


def test_accounting_contract_requires_reason_for_non_candidate_states():
    with pytest.raises(ValueError, match="no_adjustment_identified"):
        AccountingFinding(
            topic=AccountingTopic.ev_equity_bridge,
            finding_status=AccountingFindingStatus.no_adjustment_identified,
            finding_type="lease_review",
            line_item="Lease liabilities",
            claim="No adjustment identified.",
        )

    with pytest.raises(ValueError, match="missing_evidence"):
        AccountingFinding(
            topic=AccountingTopic.contingencies_and_taxes,
            finding_status=AccountingFindingStatus.missing_evidence,
            finding_type="tax_contingency",
            line_item="Tax contingency",
            claim="Evidence was not available.",
        )


def test_driver_mismatch_returns_machine_readable_rejection_reason():
    result = validate_accounting_finding(_bad_target_finding(), _packet())

    assert result.valid is False
    issue = next(issue for issue in result.issues if issue.code == "driver_mismatch")
    assert "ebit_margin_target" in issue.message
    assert "ebit_margin_start" in issue.message


def test_repair_request_returns_original_finding_reason_allowed_fields_and_evidence():
    validation = validate_accounting_finding(_bad_target_finding(), _packet())
    request = build_repair_request(
        _bad_target_finding(),
        validation.issues,
        _packet(),
    )

    assert request["original_finding"] == _bad_target_finding()
    assert "driver_mismatch" in {item["code"] for item in request["validation_errors"]}
    assert request["allowed_driver_fields"] == ["ebit_margin_start", "ebit_margin_target"]
    assert request["evidence_anchor_ids"] == ["fact:margin_target", "snippet:margin_history"]
    assert "preserve" in request["repair_instruction"].lower()


def test_repair_cycle_keeps_valid_correction_and_records_failed_repair():
    corrected = {
        **_bad_target_finding(),
        "proposed_driver_field": "ebit_margin_target",
        "proposed_value": 0.332,
    }

    repaired = run_repair_cycle(
        _bad_target_finding(),
        packet=_packet(),
        repair_callable=lambda request: corrected,
    )
    assert repaired.status == "repaired"
    assert repaired.finding["proposed_driver_field"] == "ebit_margin_target"
    assert len(repaired.attempts) == 2

    rejected = run_repair_cycle(
        _bad_target_finding(),
        packet=_packet(),
        repair_callable=lambda request: _bad_target_finding(),
    )
    invented = run_repair_cycle(
        _bad_target_finding(),
        packet=_packet(),
        repair_callable=lambda request: {
            **corrected,
            "proposed_value": 0.3500,
        },
    )
    assert invented.status == "rejected_after_repair"
    assert "numeric_value_not_anchored" in {issue.code for issue in invented.final_issues}
    assert rejected.status == "rejected_after_repair"
    assert rejected.finding is None
    assert len(rejected.attempts) == 2
    assert rejected.final_issues[0].code == "driver_mismatch"


def test_focus_contract_has_stable_ids_and_serializes_focus_and_parent_topic():
    kwargs = dict(
        topic=AccountingTopic.qoe,
        focus_key=AccountingFocusKey.qoe_nonrecurring,
        finding_status=AccountingFindingStatus.no_adjustment_identified,
        finding_type="restructuring_review",
        line_item="Restructuring costs",
        claim="No separately actionable restructuring item was identified.",
        no_adjustment_reason="The supplied disclosure does not support a separate adjustment.",
    )
    first = AccountingFinding(**kwargs)
    second = AccountingFinding(**kwargs)

    assert first.finding_id == second.finding_id
    payload = first.model_dump(mode="json")
    assert payload["finding_id"] == first.finding_id
    assert payload["focus_key"] == "qoe_nonrecurring"
    assert payload["topic"] == "qoe"


def test_focus_response_supports_multiple_findings_and_empty_outcome():
    finding_kwargs = dict(
        topic=AccountingTopic.qoe,
        focus_key=AccountingFocusKey.qoe_opex_and_compensation,
        finding_status=AccountingFindingStatus.no_adjustment_identified,
        line_item="Operating expenses",
        claim="No separate operating-expense adjustment was identified.",
        no_adjustment_reason="Evidence supports reported treatment.",
    )
    response = AccountingFocusResponse(
        focus_key=AccountingFocusKey.qoe_opex_and_compensation,
        packet_status=AccountingPacketStatus.complete,
        findings=[
            AccountingFinding(finding_type="sbc", **finding_kwargs),
            AccountingFinding(finding_type="compensation", **finding_kwargs),
        ],
    )
    empty = AccountingFocusResponse(
        focus_key=AccountingFocusKey.qoe_cash_conversion,
        packet_status=AccountingPacketStatus.complete,
        coverage_notes=["All selected cash-conversion evidence was reviewed; no actionable finding was identified."],
    )

    assert len(response.findings) == 2
    assert response.model_dump(mode="json")["findings"][0]["finding_id"]
    assert empty.findings == []


def test_focus_response_supports_explicit_missing_evidence():
    response = AccountingFocusResponse(
        focus_key=AccountingFocusKey.tax_contingencies,
        packet_status=AccountingPacketStatus.missing_evidence,
        coverage_notes=["No tax-contingency disclosure was available in the retrieved filing sections."],
    )

    assert response.findings == []
    assert response.model_dump(mode="json")["packet_status"] == "missing_evidence"

    with pytest.raises(ValueError, match="coverage_notes"):
        AccountingFocusResponse(
            focus_key=AccountingFocusKey.tax_contingencies,
            packet_status=AccountingPacketStatus.missing_evidence,
        )


def _valid_focus_finding(finding_type: str, line_item: str) -> dict:
    return {
        "finding_id": f"finding:{finding_type}",
        "topic": "qoe",
        "focus_key": "qoe_nonrecurring",
        "finding_status": "no_adjustment_identified",
        "finding_type": finding_type,
        "line_item": line_item,
        "claim": f"No separately actionable {line_item.lower()} item was identified.",
        "no_adjustment_reason": "The supplied evidence supports reported treatment.",
        "accounting_treatment": "no_adjustment",
        "valuation_treatment": "none",
    }


def _focus_envelope(*findings: dict, packet_status: str = "complete") -> dict:
    return {
        "focus_key": "qoe_nonrecurring",
        "packet_status": packet_status,
        "findings": list(findings),
        "coverage_notes": [],
    }


def test_focus_repair_cycle_accepts_two_independent_valid_findings_without_merging():
    calls: list[dict] = []
    result = run_focus_repair_cycle(
        _focus_envelope(
            _valid_focus_finding("sbc", "Stock compensation"),
            _valid_focus_finding("restructuring", "Restructuring"),
        ),
        packet=_packet(),
        repair_callable=lambda request: calls.append(request),
    )

    assert result.status == "accepted"
    assert result.response is not None
    assert [item["finding_type"] for item in result.response["findings"]] == [
        "sbc",
        "restructuring",
    ]
    assert len(result.finding_results) == 2
    assert calls == []


def test_focus_repair_cycle_repairs_only_invalid_item_and_preserves_valid_sibling():
    invalid = _bad_target_finding() | {
        "finding_id": "finding:item-123",
        "focus_key": "qoe_nonrecurring",
    }
    valid = _valid_focus_finding("restructuring", "Restructuring")
    seen: list[dict] = []

    def repair(request: dict) -> dict:
        seen.append(request)
        return invalid | {"proposed_driver_field": "ebit_margin_target"}

    result = run_focus_repair_cycle(
        _focus_envelope(invalid, valid),
        packet=_packet(),
        repair_callable=repair,
    )

    assert result.status == "accepted_with_rejections" or result.status == "repaired"
    assert result.response is not None
    assert [item["finding_type"] for item in result.response["findings"]] == [
        "margin_target_review",
        "restructuring",
    ]
    assert len(seen) == 1
    assert seen[0]["original_finding"]["finding_id"] == "finding:item-123"
    assert "correct only" in seen[0]["repair_instruction"].lower()


def test_focus_repair_cycle_keeps_failed_item_rejected_after_repair():
    invalid = _bad_target_finding() | {
        "finding_id": "finding:item-123",
        "focus_key": "qoe_nonrecurring",
    }
    valid = _valid_focus_finding("restructuring", "Restructuring")
    result = run_focus_repair_cycle(
        _focus_envelope(invalid, valid),
        packet=_packet(),
        repair_callable=lambda request: request["original_finding"],
    )

    rejected = next(item for item in result.finding_results if item.finding_id == "finding:item-123")
    assert rejected.status == "rejected_after_repair"
    assert rejected.finding["finding_id"] == "finding:item-123"
    assert len(rejected.attempts) == 2
    assert "driver_mismatch" in {issue.code for issue in rejected.final_issues}
    assert result.response is not None
    assert [item["finding_type"] for item in result.response["findings"]] == ["restructuring"]


def test_focus_repair_cycle_retries_invalid_envelope_once():
    calls: list[dict] = []
    corrected = _focus_envelope(_valid_focus_finding("restructuring", "Restructuring"))

    def repair(request: dict) -> dict:
        calls.append(request)
        return corrected

    result = run_focus_repair_cycle(
        {"focus_key": "qoe_nonrecurring", "packet_status": "complete", "findings": "not-a-list"},
        packet=_packet(),
        repair_callable=repair,
    )

    assert result.status == "repaired"
    assert len(result.envelope_attempts) == 2
    assert len(calls) == 1
    assert calls[0]["schema_errors"]
    assert calls[0]["focused_packet"]["ticker"] == "MSFT"


def test_focus_repair_cycle_does_not_repair_empty_or_missing_evidence_response():
    calls: list[dict] = []
    for envelope in (
        _focus_envelope() | {"coverage_notes": ["All selected evidence was reviewed; no finding was warranted."]},
        _focus_envelope(packet_status="missing_evidence") | {
            "coverage_notes": ["The focused filing section was unavailable."],
        },
    ):
        result = run_focus_repair_cycle(
            envelope,
            packet=_packet(),
            repair_callable=lambda request: calls.append(request),
        )
        assert result.response is not None
        assert result.finding_results == []

    assert calls == []


def test_validator_rejects_fabricated_finance_metadata_and_pm_overreach():
    packet = {
        "ticker": "MSFT",
        "topic": "qoe",
        "focus_key": "qoe_nonrecurring",
        "packet_status": "complete",
        "allowed_driver_fields": ["ebit_margin_target"],
        "current_model_fields": {"ebit_margin_target": 0.33},
        "facts": [
            {
                "fact_id": "fact:revenue",
                "fact_name": "revenue",
                "value": 100.0,
                "unit": "USD mm",
                "metadata": {"period": "2025-06-30"},
            }
        ],
        "snippets": [
            {
                "snippet_id": "snippet:revenue",
                "source_ref_id": "filing:msft",
                "text": "Revenue increased during fiscal 2025.",
            }
        ],
    }
    finding = {
        "topic": "qoe",
        "focus_key": "qoe_nonrecurring",
        "finding_status": "candidate",
        "finding_type": "restructuring_review",
        "line_item": "Restructuring",
        "claim": "This adjustment was approved, decision-ready, and automatically applied.",
        "direction": "increase normalized EBIT",
        "reported_value": 99999.0,
        "cash_impact": 888.0,
        "tax_impact": 777.0,
        "currency": "EUR bn",
        "period": "LTM",
        "booked_or_disclosed_status": "booked",
        "accounting_treatment": "scenario_only",
        "valuation_treatment": "scenario_only",
        "materiality_rationale": "Material to the model.",
        "evidence_anchor_ids": ["fact:revenue", "snippet:revenue"],
        "citation_text": "A fabricated quotation.",
        "confidence": "certain",
        "pm_question": "Apply this now",
        "what_would_change_mind": "Nothing.",
    }

    result = validate_accounting_finding(finding, packet)
    codes = {issue.code for issue in result.issues}

    assert result.valid is False
    assert "numeric_value_not_anchored" in codes
    assert "numeric_metadata_mismatch" in codes
    assert "citation_not_in_anchor" in codes
    assert "evidence_anchor_not_relevant" in codes
    assert "pm_authority_overreach" in codes
    assert "invalid_pm_question" in codes
    assert "invalid_confidence" in codes


def test_scenario_only_candidate_is_valid_without_driver_mapping():
    finding = {
        "topic": "qoe",
        "finding_status": "candidate",
        "finding_type": "margin_scenario_review",
        "line_item": "EBIT margin",
        "claim": "The supplied margin evidence supports scenario review only.",
        "reported_value": 0.332,
        "accounting_treatment": "scenario_only",
        "valuation_treatment": "scenario_only",
        "materiality_rationale": "Margin outcomes are material to operating profit.",
        "evidence_anchor_ids": ["fact:margin_target", "snippet:margin_history"],
        "citation_text": "EBIT margin rose to 45.6%; the three-year average was 44.0%.",
        "confidence": "medium",
        "pm_question": "Should this evidence be reflected only in scenario risk?",
        "what_would_change_mind": "A supported forward estimate could justify a driver review.",
    }

    result = validate_accounting_finding(finding, _packet())

    assert result.valid is True


def test_focus_response_rejects_more_than_five_or_duplicate_findings():
    findings = [
        AccountingFinding(
            topic=AccountingTopic.qoe,
            focus_key=AccountingFocusKey.qoe_nonrecurring,
            finding_status=AccountingFindingStatus.no_adjustment_identified,
            finding_type=f"item-{index}",
            line_item=f"Item {index}",
            claim=f"No adjustment was identified for item {index}.",
            accounting_treatment="no_adjustment",
            valuation_treatment="none",
            no_adjustment_reason="The supplied evidence supports reported treatment.",
        )
        for index in range(6)
    ]
    with pytest.raises(ValueError, match="at most 5 items"):
        AccountingFocusResponse(
            focus_key=AccountingFocusKey.qoe_nonrecurring,
            packet_status=AccountingPacketStatus.complete,
            findings=findings,
        )
    with pytest.raises(ValueError, match="duplicate finding IDs"):
        AccountingFocusResponse(
            focus_key=AccountingFocusKey.qoe_nonrecurring,
            packet_status=AccountingPacketStatus.complete,
            findings=[findings[0], findings[0]],
        )


def test_focus_repair_cycle_rejects_packet_status_spoof_after_one_repair():
    packet = {
        **_packet(),
        "focus_key": "qoe_nonrecurring",
        "packet_status": "partial",
    }
    response = _focus_envelope(
        _valid_focus_finding("restructuring", "Restructuring"),
        packet_status="complete",
    )

    result = run_focus_repair_cycle(
        response,
        packet=packet,
        repair_callable=lambda request: response,
    )

    assert result.status == "rejected_after_repair"
    assert "packet_status_mismatch" in {issue.code for issue in result.final_issues}


def test_item_repair_cannot_replace_identity_or_unflagged_claim():
    packet = {
        **_packet(),
        "focus_key": "qoe_nonrecurring",
        "packet_status": "complete",
    }
    invalid = {
        **_bad_target_finding(),
        "finding_id": "finding:original",
        "focus_key": "qoe_nonrecurring",
    }

    def replace_finding(request: dict) -> dict:
        return {
            **invalid,
            "finding_id": "finding:replacement",
            "focus_key": "qoe_revenue",
            "claim": "A different revenue claim replaced the original finding.",
            "proposed_driver_field": "ebit_margin_target",
        }

    result = run_focus_repair_cycle(
        _focus_envelope(invalid),
        packet=packet,
        repair_callable=replace_finding,
    )

    rejected = result.finding_results[0]
    assert rejected.status == "rejected_after_repair"
    codes = {issue.code for issue in rejected.final_issues}
    assert "repair_identity_changed" in codes


def test_no_adjustment_cannot_claim_approval_or_application():
    finding = _valid_focus_finding("reported-treatment", "Reported treatment")
    finding["claim"] = "The adjustment was approved and automatically applied."

    result = validate_accounting_finding(finding, _packet())

    assert "pm_authority_overreach" in {issue.code for issue in result.issues}
