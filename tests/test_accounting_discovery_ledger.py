"""Offline regressions for the discovery -> focused-recast -> ledger/PM-Queue adapter.

These tests fix the boundary described in
``docs/plans/active/2026-07-11-accounting-evidence-packs-focused-repair.md``:
several independent discovery questions must survive into the accounting ledger
as separate findings, contradictions must stay visible as conflicts, explicit
no-adjustment conclusions must remain inspectable without entering the mutation
queue, unsupported-but-sound treatments must become model-change requests, and a
deterministically guarded override must never reach an assumption change pack.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from db.loader import list_pm_decision_queue_items
from db.schema import create_tables
from src.contracts.pm_decision_queue import PMDecisionQueueItemType
from src.stage_02_valuation.claim_ledger import (
    ClaimAllocation,
    ClaimLedger,
    ReportedLine,
)
from src.stage_04_pipeline.accounting_discovery_ledger import (
    DiscoveryJudgmentContext,
    build_discovery_accounting_ledger,
    recast_to_findings,
    run_discovery_accounting_pass,
)
from src.stage_04_pipeline.accounting_ledger import AccountingLedgerStatus
from src.stage_04_pipeline.accounting_validation import validate_accounting_finding

REPO_ROOT = Path(__file__).resolve().parents[1]
UNGUARDED_ARTIFACT = (
    REPO_ROOT / "output" / "accounting_discovery" / "MSFT-20260725T155924Z.json"
)

SECTION_A = "0000950170-25-100235::note_013"
SECTION_B = "0001193125-26-191507::note_012"


def _retrieval_summary(section_ids: list[str]) -> dict:
    return {
        "profile_name": "accounting_discovery_focus",
        "corpus_hash": "corpus-hash",
        "requested_section_ids": list(section_ids),
        "matched_section_ids": list(section_ids),
        "unmatched_section_ids": [],
        "selected_chunk_count": len(section_ids),
        "corpus_chunk_count": 3831,
    }


def _recast(**overrides) -> dict:
    payload = {
        "ticker": "MSFT",
        "source": "provided_filing_text",
        "confidence": "medium",
        "income_statement_adjustments": [],
        "balance_sheet_reclassifications": [],
        "model_change_proposals": [],
        "override_candidates": {
            "normalized_ebit": None,
            "non_operating_assets": None,
            "lease_liabilities": None,
            "minority_interest": None,
            "preferred_equity": None,
            "pension_deficit": None,
        },
        "approval_required": True,
        "pm_review_notes": "Reviewed against the focused evidence.",
    }
    overrides_candidates = overrides.pop("override_candidates", None)
    payload.update(overrides)
    if overrides_candidates:
        payload["override_candidates"].update(overrides_candidates)
    return payload


def _analysis(question_id: str, recast: dict, sections: list[str]) -> dict:
    return {
        "question_id": question_id,
        "question": f"Question body for {question_id}",
        "retrieval_summary": _retrieval_summary(sections),
        "recast": recast,
    }


def _bridge_reclass(
    *,
    line_item: str = "Finance lease liabilities",
    value: float = 62_932_000_000.0,
    driver: str | None = "lease_liabilities",
) -> dict:
    return {
        "line_item": line_item,
        "reported_value": value,
        "classification": "financing_liability",
        "proposed_driver_field": driver,
        "rationale": "Finance lease obligations are debt-like financing claims.",
        "citation_text": 'NOTE 12 - LEASES: "Total finance lease liabilities $ 62,932".',
    }


def _claim_ledger_with_unclaimed_line(
    line_id: str,
    value_mm: float,
    *,
    semantic_type: str = "asset",
) -> ClaimLedger:
    return ClaimLedger(
        reported_lines=[
            ReportedLine(
                line_id,
                value_mm,
                line_id,
                semantic_type=semantic_type,
            )
        ],
        allocations=[
            ClaimAllocation(
                parent_line_id=line_id,
                allocation_id=line_id,
                component="unclaimed",
                sign=1,
                value=value_mm,
            )
        ],
        component_values={
            "unclaimed": value_mm,
            "non_operating_assets": 0.0,
            "pension_deficit": 0.0,
            "lease_liabilities": 0.0,
        },
    )


def _claim_ledger_with_unclaimed_investment() -> ClaimLedger:
    return _claim_ledger_with_unclaimed_line(
        "xbrl:MarketableSecuritiesNoncurrent",
        12_000.0,
        semantic_type="asset",
    )


def _msft_bridge_claim_ledger() -> ClaimLedger:
    return ClaimLedger(
        reported_lines=[
            ReportedLine(
                "cash",
                32_105.0,
                "ciq:cash",
                semantic_type="asset",
            ),
            ReportedLine(
                "total_debt",
                125_432.0,
                "ciq:total_debt",
                semantic_type="liability",
            ),
        ],
        allocations=[
            ClaimAllocation(
                parent_line_id="cash",
                allocation_id="cash:operating",
                component="net_debt",
                sign=-1,
                value=6_365.46,
            ),
            ClaimAllocation(
                parent_line_id="cash",
                allocation_id="cash:excess",
                component="non_operating_assets",
                sign=1,
                value=25_739.54,
            ),
            ClaimAllocation(
                parent_line_id="total_debt",
                allocation_id="total_debt:funded",
                component="net_debt",
                sign=1,
                value=40_262.0,
            ),
            ClaimAllocation(
                parent_line_id="total_debt",
                allocation_id="total_debt:leases",
                component="lease_liabilities",
                sign=1,
                value=85_170.0,
            ),
        ],
        component_values={
            "net_debt": 33_896.54,
            "non_operating_assets": 25_739.54,
            "lease_liabilities": 85_170.0,
        },
    )


# --------------------------------------------------------------- fan-out


def test_multiple_questions_produce_multiple_independent_ledger_findings():
    analyses = [
        _analysis(
            "debt_structure",
            _recast(
                balance_sheet_reclassifications=[
                    _bridge_reclass(
                        line_item="Long-term debt",
                        value=31_423_000_000.0,
                        driver=None,
                    )
                ]
            ),
            [SECTION_A],
        ),
        _analysis(
            "sbc_and_share_count",
            _recast(
                income_statement_adjustments=[
                    {
                        "item": "Stock-based compensation",
                        "amount": 11_974_000_000.0,
                        "classification": "non_core",
                        "proposed_ebit_direction": "-",
                        "rationale": "SBC is a real economic cost of the workforce.",
                        "citation_text": "NOTE 17: Stock-based compensation expense was $11,974 million.",
                    }
                ]
            ),
            [SECTION_B],
        ),
    ]

    result = build_discovery_accounting_ledger(
        ticker="MSFT",
        focused_analyses=analyses,
        evidence_packet_id=214,
    )

    question_ids = {
        entry.finding.get("metadata", {}).get("question_id")
        for entry in result.ledger.entries
    }
    assert question_ids == {"debt_structure", "sbc_and_share_count"}
    # Two questions, two distinct accounting objects: nothing is flattened.
    line_items = {entry.finding["line_item"] for entry in result.ledger.entries}
    assert line_items == {"Long-term debt", "Stock-based compensation"}
    assert len(result.ledger.entries) == 2


def test_every_mapped_finding_passes_the_shared_accounting_validator():
    analyses = [
        _analysis(
            "bridge",
            _recast(
                reclassify=[
                    {
                        "reported_line": "xbrl:MarketableSecuritiesNoncurrent",
                        "from_component": "unclaimed",
                        "to_component": "non_operating_assets",
                        "rationale": "The securities are separable from operations.",
                        "citation_text": "NOTE 7 - INVESTMENTS.",
                    }
                ],
                model_change_proposals=[
                    {
                        "proposal": "Model datacenter capex intensity separately.",
                        "valuation_effect": "Lower near-term FCF.",
                        "reasoning": "Buildout is capitalized rather than expensed.",
                        "citation_text": "NOTE 6 - PROPERTY AND EQUIPMENT.",
                        "implementation_status": "proposed",
                    }
                ],
            ),
            [SECTION_A],
        )
    ]

    result = build_discovery_accounting_ledger(
        ticker="MSFT",
        focused_analyses=analyses,
        evidence_packet_id=214,
        claim_ledger=_claim_ledger_with_unclaimed_investment(),
    )

    assert result.rejected_findings == []
    for finding, packet in result.validated_pairs:
        assert validate_accounting_finding(finding, packet).valid, finding


# --------------------------------------------------------------- dedupe / conflict


def test_duplicate_proposals_across_questions_dedupe_with_provenance():
    reclass = {
        "reported_line": "xbrl:PensionLiability",
        "from_component": "unclaimed",
        "to_component": "pension_deficit",
        "rationale": "The underfunded obligation is a non-equity claim.",
        "citation_text": "NOTE 13 - PENSIONS.",
    }
    analyses = [
        _analysis("question_one", _recast(reclassify=[reclass]), [SECTION_A]),
        _analysis("question_two", _recast(reclassify=[dict(reclass)]), [SECTION_A]),
    ]

    result = build_discovery_accounting_ledger(
        ticker="MSFT",
        focused_analyses=analyses,
        evidence_packet_id=214,
        claim_ledger=_claim_ledger_with_unclaimed_line(
            "xbrl:PensionLiability",
            1_500.0,
            semantic_type="liability",
        ),
    )

    statuses = [entry.ledger_status for entry in result.ledger.entries]
    assert statuses.count(AccountingLedgerStatus.candidate) == 1
    assert statuses.count(AccountingLedgerStatus.duplicate) == 1
    duplicate = next(
        entry for entry in result.ledger.entries
        if entry.ledger_status == AccountingLedgerStatus.duplicate
    )
    assert duplicate.duplicate_of
    # The duplicate keeps its own question provenance rather than being erased.
    assert duplicate.finding["metadata"]["question_id"] == "question_two"
    packs = [
        item for item in result.queue_items
        if item.item_type == PMDecisionQueueItemType.assumption_change_pack
    ]
    assert len(packs) == 1


def test_conflicting_proposals_across_questions_stay_visible_as_a_conflict():
    analyses = [
        _analysis(
            "question_one",
            _recast(
                driver_proposals=[
                    _driver_proposal(
                        driver_field="ebit_margin_target",
                        proposed_value=0.30,
                    )
                ]
            ),
            [SECTION_A],
        ),
        _analysis(
            "question_two",
            _recast(
                driver_proposals=[
                    _driver_proposal(
                        driver_field="ebit_margin_target",
                        proposed_value=0.44,
                    )
                ]
            ),
            [SECTION_B],
        ),
    ]

    result = build_discovery_accounting_ledger(
        ticker="MSFT",
        focused_analyses=analyses,
        evidence_packet_id=214,
    )

    assert len(result.ledger.conflict_groups) == 1
    conflicted = [
        entry for entry in result.ledger.entries
        if entry.ledger_status == AccountingLedgerStatus.conflict
    ]
    assert len(conflicted) == 2
    # A contradiction is never silently resolved into an applicable proposal.
    assert all(
        item.item_type == PMDecisionQueueItemType.advisory_finding
        for item in result.queue_items
    )


# --------------------------------------------------------------- no-adjustment


def test_no_adjustment_conclusions_stay_in_the_ledger_and_out_of_the_queue():
    analyses = [
        _analysis(
            "sbc_no_adjustment",
            _recast(
                income_statement_adjustments=[
                    {
                        "item": "No separate EBIT normalization for stock-based compensation",
                        "amount": None,
                        "classification": "unclear",
                        "proposed_ebit_direction": "none",
                        "rationale": "SBC is a recurring operating cost of the workforce.",
                        "citation_text": "NOTE 17 - EMPLOYEE STOCK AND SAVINGS PLANS.",
                    }
                ]
            ),
            [SECTION_A],
        ),
        _analysis("nothing_found", _recast(), [SECTION_B]),
    ]

    result = build_discovery_accounting_ledger(
        ticker="MSFT",
        focused_analyses=analyses,
        evidence_packet_id=214,
    )

    assert len(result.ledger.entries) == 2
    assert all(
        entry.ledger_status == AccountingLedgerStatus.no_adjustment_identified
        for entry in result.ledger.entries
    )
    assert all(entry.finding["no_adjustment_reason"] for entry in result.ledger.entries)
    assert result.queue_items == []


# --------------------------------------------------------------- model change


def test_unsupported_treatment_becomes_a_model_change_request():
    analyses = [
        _analysis(
            "capex_intensity",
            _recast(
                income_statement_adjustments=[
                    {
                        "item": "Datacenter buildout depreciation",
                        "amount": 9_000_000_000.0,
                        "classification": "non_core",
                        "proposed_ebit_direction": "+",
                        "rationale": "Buildout depreciation distorts run-rate EBIT.",
                        "citation_text": "NOTE 6: depreciation expense $9.0 billion.",
                    }
                ],
                model_change_proposals=[
                    {
                        "proposal": "Add a datacenter capex intensity driver to the forecast.",
                        "valuation_effect": "Lower near-term FCF.",
                        "reasoning": "Capital intensity is structurally elevated.",
                        "citation_text": "NOTE 6 - PROPERTY AND EQUIPMENT.",
                        "implementation_status": "proposed",
                    }
                ],
            ),
            [SECTION_A],
        )
    ]

    result = build_discovery_accounting_ledger(
        ticker="MSFT",
        focused_analyses=analyses,
        evidence_packet_id=214,
    )

    assert len(result.queue_items) == 2
    assert all(
        item.item_type == PMDecisionQueueItemType.advisory_finding
        for item in result.queue_items
    )
    assert all(item.metadata.get("model_change_required") for item in result.queue_items)
    assert all(item.metadata.get("model_change_request") for item in result.queue_items)
    # Normalized EBIT is not a proposable driver, so nothing may be remapped onto a
    # margin field just to make the proposal fit the current model.
    assert not any(
        item.metadata.get("proposed_driver_field") for item in result.queue_items
    )


# --------------------------------------------------------------- guard


def test_legacy_bridge_amounts_never_become_queue_candidates():
    """Saved legacy payloads fail closed even without a named field blocklist."""

    analyses = [
        _analysis(
            "ai_capacity",
            _recast(
                balance_sheet_reclassifications=[
                    _bridge_reclass(
                        line_item="Operating lease liabilities",
                        value=22_238_000_000.0,
                        driver="lease_liabilities",
                    ),
                    _bridge_reclass(driver="lease_liabilities"),
                ],
                override_candidates={"lease_liabilities": 85_126_000_000.0},
            ),
            [SECTION_A],
        )
    ]

    result = build_discovery_accounting_ledger(
        ticker="MSFT",
        focused_analyses=analyses,
        evidence_packet_id=214,
        claim_ledger=_msft_bridge_claim_ledger(),
    )

    assert not any(
        item.item_type == PMDecisionQueueItemType.assumption_change_pack
        for item in result.queue_items
    )
    assert not any(
        item.metadata.get("proposed_driver_field") == "lease_liabilities"
        for item in result.queue_items
    )
    rejected = [
        entry for entry in result.ledger.entries
        if entry.ledger_status == AccountingLedgerStatus.rejected_after_repair
    ]
    assert len(rejected) == 3
    assert all(entry.finding["claim"] for entry in rejected)
    assert all(entry.finding["evidence_anchor_ids"] for entry in rejected)
    assert all(
        entry.finding["metadata"]["claim_reconciliation_error"]
        for entry in rejected
    )
    cited = [entry for entry in rejected if entry.finding["citation_text"]]
    assert len(cited) == 2
    assert result.queue_items == []


@pytest.mark.skipif(
    not UNGUARDED_ARTIFACT.exists(),
    reason="live MSFT discovery artifact is not present in this checkout",
)
def test_live_unguarded_msft_artifact_produces_no_lease_assumption_pack():
    artifact = json.loads(UNGUARDED_ARTIFACT.read_text(encoding="utf-8"))
    result = build_discovery_accounting_ledger(
        ticker=artifact["ticker"],
        focused_analyses=artifact["focused_analyses"],
        evidence_packet_id=214,
        claim_ledger=_msft_bridge_claim_ledger(),
    )

    assert result.ledger.entries
    assert not any(
        item.item_type == PMDecisionQueueItemType.assumption_change_pack
        and item.metadata.get("proposed_driver_field") == "lease_liabilities"
        for item in result.queue_items
    )
    # Every question in the live run survives as its own ledger provenance.
    question_ids = {
        entry.finding["metadata"]["question_id"] for entry in result.ledger.entries
    }
    assert question_ids == {
        analysis["question_id"] for analysis in artifact["focused_analyses"]
    }


# --------------------------------------------------------------- context contract


def test_every_focused_call_receives_business_industry_quant_and_model_context():
    calls: list[dict] = []

    def fake_retrieval(ticker, question):
        return {
            "rendered_text": f"evidence for {question['question_id']}",
            "retrieval_summary": _retrieval_summary(question["requested_section_ids"]),
        }

    def fake_recast(**kwargs):
        calls.append(kwargs)
        return _recast()

    discovery = {
        "ticker": "MSFT",
        "questions": [
            {
                "question_id": "q1",
                "question": "Lease treatment?",
                "why_it_matters": "EV bridge",
                "requested_section_ids": [SECTION_A],
                "search_terms": ["lease"],
            },
            {
                "question_id": "q2",
                "question": "Segment mix?",
                "why_it_matters": "margin path",
                "requested_section_ids": [SECTION_B],
                "search_terms": ["segment"],
            },
        ],
    }
    contexts = DiscoveryJudgmentContext(
        business_context="MSFT business read",
        industry_context="software industry read",
        quantitative_context="revenue, margin, and bridge facts",
        current_model_context="CIQ total_debt is lease inclusive",
    )

    result = run_discovery_accounting_pass(
        ticker="MSFT",
        discovery=discovery,
        contexts=contexts,
        retrieval_callable=fake_retrieval,
        recast_callable=fake_recast,
        evidence_packet_id=214,
        require_corpus_coverage=False,
    )

    assert len(calls) == 2
    for call in calls:
        assert call["business_context"] == "MSFT business read"
        assert call["industry_context"] == "software industry read"
        assert call["quantitative_context"] == "revenue, margin, and bridge facts"
        assert call["current_model_context"] == "CIQ total_debt is lease inclusive"
        assert call["filing_text"]
        assert call["analysis_task"]
    assert [analysis["question_id"] for analysis in result.focused_analyses] == ["q1", "q2"]


def test_pass_fails_closed_when_required_filing_coverage_is_incomplete(monkeypatch):
    from src.stage_00_data import filing_retrieval

    def boom(ticker):
        raise RuntimeError(
            "Accounting corpus incomplete: parsed 6/8 required accounting filings"
        )

    monkeypatch.setattr(
        filing_retrieval, "require_accounting_corpus_coverage", boom, raising=True
    )

    with pytest.raises(RuntimeError, match="Accounting corpus incomplete"):
        run_discovery_accounting_pass(
            ticker="MSFT",
            discovery={"questions": []},
            contexts=DiscoveryJudgmentContext("b", "i", "q", "m"),
            retrieval_callable=lambda ticker, question: {"rendered_text": "", "retrieval_summary": {}},
            recast_callable=lambda **kwargs: _recast(),
            evidence_packet_id=214,
        )


def test_invalid_mapping_stays_visible_as_rejected_and_never_queues():
    """A finding the validator refuses is preserved with its reason, not dropped."""

    analyses = [
        _analysis(
            "bad_mapping",
            _recast(
                balance_sheet_reclassifications=[
                    # A driver outside AGENT_PROPOSABLE_ASSUMPTION_FIELDS: the queue
                    # translator alone would not catch this, the validator does.
                    _bridge_reclass(driver="gross_margin_target")
                ]
            ),
            [SECTION_A],
        )
    ]

    result = build_discovery_accounting_ledger(
        ticker="MSFT",
        focused_analyses=analyses,
        evidence_packet_id=214,
    )

    assert result.findings == []
    assert len(result.rejected_findings) == 1
    codes = {
        issue["code"]
        for issue in result.rejected_findings[0]["metadata"]["validation_issues"]
    }
    assert "proposed_driver_not_allowed" in codes
    entry = result.ledger.entries[0]
    assert entry.ledger_status == AccountingLedgerStatus.rejected_after_repair
    assert entry.finding["citation_text"]
    assert result.queue_items == []


def test_pass_persists_queue_items_only_when_given_a_connection():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_tables(conn)

    result = run_discovery_accounting_pass(
        ticker="MSFT",
        discovery={
            "questions": [
                {
                    "question_id": "q1",
                    "question": "Pension treatment?",
                    "requested_section_ids": [SECTION_A],
                    "search_terms": ["pension"],
                }
            ]
        },
        contexts=DiscoveryJudgmentContext("b", "i", "q", "m"),
        retrieval_callable=lambda ticker, question: {
            "rendered_text": "evidence",
            "retrieval_summary": _retrieval_summary([SECTION_A]),
        },
        recast_callable=lambda **kwargs: _recast(
            driver_proposals=[
                _driver_proposal(
                    driver_field="ebit_margin_target",
                    proposed_value=0.44,
                )
            ]
        ),
        evidence_packet_id=214,
        conn=conn,
        require_corpus_coverage=False,
    )

    assert len(result.persisted_queue_item_ids) == len(result.queue_items) == 1
    stored = list_pm_decision_queue_items(conn, ticker="MSFT", status="pending")
    assert len(stored) == 1
    assert stored[0]["metadata"]["finding_metadata"]["question_id"] == "q1"
    conn.close()


def test_pass_persists_nothing_without_a_connection():
    result = run_discovery_accounting_pass(
        ticker="MSFT",
        discovery={
            "questions": [
                {
                    "question_id": "q1",
                    "question": "Lease treatment?",
                    "requested_section_ids": [SECTION_A],
                    "search_terms": ["lease"],
                }
            ]
        },
        contexts=DiscoveryJudgmentContext("b", "i", "q", "m"),
        retrieval_callable=lambda ticker, question: {
            "rendered_text": "evidence",
            "retrieval_summary": _retrieval_summary([SECTION_A]),
        },
        recast_callable=lambda **kwargs: _recast(
            driver_proposals=[
                _driver_proposal(
                    driver_field="ebit_margin_target",
                    proposed_value=0.44,
                )
            ]
        ),
        evidence_packet_id=214,
        require_corpus_coverage=False,
    )

    assert result.queue_items
    assert result.persisted_queue_item_ids == []


# --------------------------------------------------------------- anchors


def test_findings_anchor_to_matched_sections_only():
    summary = _retrieval_summary([SECTION_A])
    summary["requested_section_ids"] = [SECTION_A, "0000000000-00-000000::note_999"]
    analysis = {
        "question_id": "q1",
        "question": "Lease treatment?",
        "retrieval_summary": summary,
        "recast": _recast(balance_sheet_reclassifications=[_bridge_reclass()]),
    }

    findings = recast_to_findings(
        ticker="MSFT",
        question_id="q1",
        question_text="Lease treatment?",
        recast=analysis["recast"],
        retrieval_summary=summary,
    )

    assert findings
    for finding in findings:
        assert finding["evidence_anchor_ids"] == [SECTION_A]


# --------------------------------------------------------------- driver proposals


def _driver_proposal(
    *,
    driver_field: str = "ebit_margin_target",
    proposed_value: float = 0.44,
) -> dict:
    return {
        "driver_field": driver_field,
        "proposed_value": proposed_value,
        "direction": "up",
        "rationale": (
            "Segment mix is shifting toward higher-margin cloud revenue and management "
            "guided to continued operating leverage."
        ),
        "citation_text": 'NOTE 19 - SEGMENT INFORMATION: "Microsoft Cloud operating margin".',
    }


def test_recast_agent_accepts_the_full_proposable_driver_vocabulary():
    """The judgment layer must be able to reach the drivers that move the DCF."""

    from src.stage_03_judgment.accounting_recast_agent import AccountingRecastAgent
    from src.stage_04_pipeline.agentic_handoff_profiles import (
        AGENT_PROPOSABLE_ASSUMPTION_FIELDS,
    )

    parsed = AccountingRecastAgent._parse_driver_proposals(
        [
            _driver_proposal(driver_field="ebit_margin_target", proposed_value=0.44),
            _driver_proposal(driver_field="capex_pct_target", proposed_value=0.19),
            # Not a proposable field: dropped rather than silently mapped elsewhere.
            _driver_proposal(driver_field="gross_margin_target", proposed_value=0.7),
            # No value: a driver proposal without a number is not a proposal.
            {"driver_field": "wacc", "rationale": "should be higher"},
        ]
    )

    assert [item["driver_field"] for item in parsed] == [
        "ebit_margin_target",
        "capex_pct_target",
    ]
    assert all(
        item["driver_field"] in AGENT_PROPOSABLE_ASSUMPTION_FIELDS for item in parsed
    )


def test_recast_agent_parses_identity_only_reclassification_contract():
    from src.stage_03_judgment.accounting_recast_agent import AccountingRecastAgent

    parsed = AccountingRecastAgent._parse_reclassifications(
        [
            {
                "reported_line": "xbrl:MarketableSecuritiesNoncurrent",
                "from_component": "unclaimed",
                "to_component": "non_operating_assets",
                "rationale": "These securities are separable from operations.",
                "citation_text": "NOTE 7 - INVESTMENTS.",
                # An agent-authored amount is deliberately outside the contract.
                "proposed_value": 111_955_000_000.0,
            },
            {
                "reported_line": "",
                "from_component": "unclaimed",
                "to_component": "non_operating_assets",
            },
        ]
    )

    assert parsed == [
        {
            "reported_line": "xbrl:MarketableSecuritiesNoncurrent",
            "from_component": "unclaimed",
            "to_component": "non_operating_assets",
            "rationale": "These securities are separable from operations.",
            "citation_text": "NOTE 7 - INVESTMENTS.",
        }
    ]


def test_reclassification_value_is_derived_from_claim_ledger_not_agent_arithmetic():
    analysis = _analysis(
        "investment_classification",
        _recast(
            reclassify=[
                {
                    "reported_line": "xbrl:MarketableSecuritiesNoncurrent",
                    "from_component": "unclaimed",
                    "to_component": "non_operating_assets",
                    "rationale": "The securities are separable from operations.",
                    "citation_text": "NOTE 7 - INVESTMENTS.",
                    "proposed_value": 111_955_000_000.0,
                }
            ]
        ),
        [SECTION_A],
    )

    result = build_discovery_accounting_ledger(
        ticker="MSFT",
        focused_analyses=[analysis],
        evidence_packet_id=214,
        claim_ledger=_claim_ledger_with_unclaimed_investment().to_dict(),
    )

    assert result.rejected_findings == []
    assert len(result.queue_items) == 1
    proposal = result.queue_items[0].proposal_pack.proposals[0]
    assert proposal.assumption_name == "non_operating_assets"
    assert proposal.proposed_target_value == 12_000_000_000.0
    finding = result.ledger.entries[0].finding
    assert finding["reported_value"] == 12_000_000_000.0
    assert finding["metadata"]["derived_from_claim_ledger"] is True


def test_multiple_reclassifications_use_one_cumulative_atomic_queue_pack():
    ledger = ClaimLedger(
        reported_lines=[
            ReportedLine(
                "investment:a",
                12_000.0,
                "xbrl:InvestmentA",
                semantic_type="asset",
            ),
            ReportedLine(
                "investment:b",
                8_000.0,
                "xbrl:InvestmentB",
                semantic_type="asset",
            ),
        ],
        allocations=[
            ClaimAllocation(
                "investment:a",
                "investment:a",
                "unclaimed",
                1,
                12_000.0,
            ),
            ClaimAllocation(
                "investment:b",
                "investment:b",
                "unclaimed",
                1,
                8_000.0,
            ),
        ],
        component_values={
            "unclaimed": 20_000.0,
            "non_operating_assets": 0.0,
        },
    )
    reclassifications = [
        {
            "reported_line": line_id,
            "from_component": "unclaimed",
            "to_component": "non_operating_assets",
            "rationale": "The investment is separable from operations.",
            "citation_text": "NOTE 7 - INVESTMENTS.",
        }
        for line_id in ("investment:a", "investment:b")
    ]

    result = build_discovery_accounting_ledger(
        ticker="MSFT",
        focused_analyses=[
            _analysis(
                "investment_classification",
                _recast(reclassify=reclassifications),
                [SECTION_A],
            )
        ],
        evidence_packet_id=214,
        claim_ledger=ledger,
    )

    assert result.rejected_findings == []
    mutation_items = [
        item
        for item in result.queue_items
        if item.item_type == PMDecisionQueueItemType.assumption_change_pack
    ]
    assert len(mutation_items) == 1
    pack = mutation_items[0].proposal_pack
    assert pack is not None
    assert [proposal.assumption_name for proposal in pack.proposals] == [
        "non_operating_assets"
    ]
    assert pack.proposals[0].proposed_target_value == 20_000_000_000.0
    assert pack.notes["atomic_reclassification"] is True
    assert pack.notes["reported_lines"] == ["investment:a", "investment:b"]


def test_same_reported_line_cannot_feed_two_reclassification_queue_items():
    ledger = _claim_ledger_with_unclaimed_investment()
    first = {
        "reported_line": "xbrl:MarketableSecuritiesNoncurrent",
        "from_component": "unclaimed",
        "to_component": "non_operating_assets",
        "rationale": "Treat as separable investment.",
        "citation_text": "NOTE 7 - INVESTMENTS.",
    }
    second = {
        **first,
        "to_component": "net_debt",
        "rationale": "Alternative treatment that must not also queue.",
    }

    result = build_discovery_accounting_ledger(
        ticker="MSFT",
        focused_analyses=[
            _analysis(
                "conflicting_treatments",
                _recast(reclassify=[first, second]),
                [SECTION_A],
            )
        ],
        evidence_packet_id=214,
        claim_ledger=ledger,
    )

    assert not any(
        item.item_type == PMDecisionQueueItemType.assumption_change_pack
        for item in result.queue_items
    )
    assert {
        finding["metadata"].get("reported_line")
        for finding in result.rejected_findings
    } == {"xbrl:MarketableSecuritiesNoncurrent"}
    assert any(
        "already claimed by non_operating_assets"
        in finding["metadata"].get("claim_reconciliation_error", "")
        for finding in result.rejected_findings
    )
    assert any(
        finding["metadata"].get("atomic_reclassification_batch_rejected")
        for finding in result.rejected_findings
    )
    assert result.reconciled_claim_ledger["fingerprint"] == (
        ledger.fingerprint
    )


@pytest.mark.parametrize(
    ("driver", "value"),
    [
        ("lease_liabilities", 85_170_000_000.0),
        ("non_operating_assets", 111_955_000_000.0),
    ],
)
def test_direct_bridge_amount_without_reported_line_fails_closed(driver, value):
    """A plausible bridge number is not a claim until it names ledger identity."""

    result = build_discovery_accounting_ledger(
        ticker="MSFT",
        focused_analyses=[
            _analysis(
                "legacy_bridge_amount",
                _recast(
                    driver_proposals=[
                        _driver_proposal(
                            driver_field=driver,
                            proposed_value=value,
                        )
                    ]
                ),
                [SECTION_A],
            )
        ],
        evidence_packet_id=214,
        claim_ledger=_claim_ledger_with_unclaimed_investment().to_dict(),
    )

    assert result.queue_items == []
    assert len(result.rejected_findings) == 1
    rejection = result.rejected_findings[0]
    assert rejection["metadata"]["claim_reconciliation_rejected"] is True
    assert "reported_line" in rejection["metadata"]["claim_reconciliation_error"]


@pytest.mark.parametrize(
    ("reported_line", "to_component", "incumbents"),
    [
        (
            "total_debt",
            "lease_liabilities",
            {"net_debt", "lease_liabilities"},
        ),
        (
            "cash",
            "non_operating_assets",
            {"net_debt", "non_operating_assets"},
        ),
    ],
)
def test_known_bridge_double_claims_are_rejected_by_incumbent_claimants(
    reported_line,
    to_component,
    incumbents,
):
    result = build_discovery_accounting_ledger(
        ticker="MSFT",
        focused_analyses=[
            _analysis(
                "bridge_double_claim",
                _recast(
                    reclassify=[
                        {
                            "reported_line": reported_line,
                            "from_component": "unclaimed",
                            "to_component": to_component,
                            "rationale": "Proposed bridge treatment.",
                            "citation_text": "NOTE 12 - BALANCE SHEET DETAIL.",
                        }
                    ]
                ),
                [SECTION_A],
            )
        ],
        evidence_packet_id=214,
        claim_ledger=_msft_bridge_claim_ledger().to_dict(),
    )

    assert result.queue_items == []
    assert len(result.rejected_findings) == 1
    rejection = result.rejected_findings[0]
    assert set(rejection["metadata"]["incumbent_claimants"]) == incumbents
    error = rejection["metadata"]["claim_reconciliation_error"]
    assert reported_line in error
    assert all(component in error for component in incumbents)


def test_driver_proposal_reaches_the_queue_as_an_assumption_change_pack():
    analyses = [
        _analysis(
            "segment_margin_mix",
            _recast(driver_proposals=[_driver_proposal()]),
            [SECTION_A],
        )
    ]

    result = build_discovery_accounting_ledger(
        ticker="MSFT",
        focused_analyses=analyses,
        evidence_packet_id=214,
    )

    assert len(result.queue_items) == 1
    item = result.queue_items[0]
    assert item.item_type == PMDecisionQueueItemType.assumption_change_pack
    proposal = item.proposal_pack.proposals[0]
    assert proposal.assumption_name == "ebit_margin_target"
    assert proposal.proposed_target_value == 0.44
    assert item.evidence_anchor_ids == [SECTION_A]
    assert item.metadata["finding_metadata"]["question_id"] == "segment_margin_mix"


def test_same_legacy_bridge_amount_via_two_channels_is_one_rejection():
    """A duplicated legacy amount is deduped, then fails claim reconciliation once.

    Regression for the live 2026-07-25 MSFT run, where `non_operating_assets`
    = $111.955bn arrived as both an override candidate and a driver proposal and was
    flagged as `contradictory_proposals_for_same_accounting_object` against itself.
    """

    analyses = [
        _analysis(
            "debt_structure",
            _recast(
                driver_proposals=[
                    _driver_proposal(
                        driver_field="non_operating_assets",
                        proposed_value=111_955_000_000.0,
                    )
                ],
                override_candidates={"non_operating_assets": 111_955_000_000.0},
            ),
            [SECTION_A],
        )
    ]

    result = build_discovery_accounting_ledger(
        ticker="MSFT",
        focused_analyses=analyses,
        evidence_packet_id=214,
    )

    assert result.ledger.conflict_groups == []
    assert len(result.ledger.entries) == 1
    # The surviving finding is the richer one: it carries the rationale and citation.
    finding = result.ledger.entries[0].finding
    assert finding["finding_type"] == "driver_proposal"
    assert finding["citation_text"]
    assert result.queue_items == []
    assert len(result.rejected_findings) == 1
    assert finding["metadata"]["claim_reconciliation_rejected"] is True


@pytest.mark.parametrize(
    "driver",
    ("options_value", "convertibles_value"),
)
def test_every_canonical_bridge_component_rejects_agent_authored_amount(
    driver,
):
    result = build_discovery_accounting_ledger(
        ticker="MSFT",
        focused_analyses=[
            _analysis(
                "bridge_claim",
                _recast(
                    driver_proposals=[
                        _driver_proposal(
                            driver_field=driver,
                            proposed_value=500_000_000.0,
                        )
                    ]
                ),
                [SECTION_A],
            )
        ],
        evidence_packet_id=214,
    )

    assert result.queue_items == []
    assert len(result.rejected_findings) == 1
    finding = result.rejected_findings[0]
    assert finding["metadata"]["driver_field"] == driver
    assert finding["metadata"]["claim_reconciliation_rejected"] is True


def test_two_questions_disagreeing_on_one_driver_still_conflict():
    """Deduping same-value channels must not suppress a real disagreement."""

    analyses = [
        _analysis(
            "capex_question",
            _recast(driver_proposals=[_driver_proposal(proposed_value=0.30)]),
            [SECTION_A],
        ),
        _analysis(
            "segment_question",
            _recast(driver_proposals=[_driver_proposal(proposed_value=0.44)]),
            [SECTION_B],
        ),
    ]

    result = build_discovery_accounting_ledger(
        ticker="MSFT",
        focused_analyses=analyses,
        evidence_packet_id=214,
    )

    assert len(result.ledger.conflict_groups) == 1
    assert not any(
        item.item_type == PMDecisionQueueItemType.assumption_change_pack
        for item in result.queue_items
    )


def test_legacy_bridge_driver_proposal_is_rejected_without_a_blocklist():
    analyses = [
        _analysis(
            "ai_capacity",
            _recast(
                driver_proposals=[
                    _driver_proposal(
                        driver_field="lease_liabilities",
                        proposed_value=85_126_000_000.0,
                    )
                ]
            ),
            [SECTION_A],
        )
    ]

    result = build_discovery_accounting_ledger(
        ticker="MSFT",
        focused_analyses=analyses,
        evidence_packet_id=214,
        claim_ledger=_msft_bridge_claim_ledger(),
    )

    assert not any(
        item.item_type == PMDecisionQueueItemType.assumption_change_pack
        for item in result.queue_items
    )
    assert result.ledger.entries[0].finding["metadata"][
        "claim_reconciliation_rejected"
    ]


# --------------------------------------------------------------- corpus gate


def test_require_accounting_corpus_coverage_reports_the_missing_filings(monkeypatch):
    from src.stage_00_data import filing_retrieval

    monkeypatch.setattr(
        filing_retrieval,
        "get_accounting_corpus_coverage",
        lambda ticker: {
            "ticker": "MSFT",
            "parser_version": "v6",
            "required_filing_count": 8,
            "parsed_filing_count": 6,
            "missing_filings": [{"form_type": "10-Q"}],
            "filings_without_notes": [],
            "complete": False,
        },
    )

    with pytest.raises(RuntimeError, match="parsed 6/8 required accounting filings"):
        filing_retrieval.require_accounting_corpus_coverage("MSFT")


def test_require_accounting_corpus_coverage_rejects_filings_parsed_without_notes():
    """"Parsed" is not "complete": a filing yielding zero numbered notes fails closed.

    Regression for the IBM case — four required filings were present and parsed, but
    produced no numbered notes at all, so discovery would have received an empty
    inventory from a corpus the gate called complete.
    """

    from src.stage_00_data import filing_retrieval

    coverage = filing_retrieval.summarize_accounting_corpus_coverage(
        ticker="IBM",
        filings=[
            {"form_type": "10-K", "filing_date": "2026-02-24",
             "accession_no": "0000051143-26-000010", "doc_name": "ibm-20251231.htm"},
            {"form_type": "10-Q", "filing_date": "2025-10-23",
             "accession_no": "0000051143-25-000064", "doc_name": "ibm-20250930.htm"},
        ],
        parsed_counts={
            ("0000051143-26-000010", "ibm-20251231.htm"): {"sections": 5, "raw_notes": 0},
            ("0000051143-25-000064", "ibm-20250930.htm"): {"sections": 1, "raw_notes": 0},
        },
    )

    assert coverage["parsed_filing_count"] == 2
    assert coverage["missing_filings"] == []
    assert len(coverage["filings_without_notes"]) == 2
    assert coverage["complete"] is False

    with pytest.raises(RuntimeError, match="no numbered notes"):
        filing_retrieval._raise_for_incomplete_coverage(coverage)


def test_corpus_coverage_is_complete_when_every_filing_has_notes():
    from src.stage_00_data import filing_retrieval

    coverage = filing_retrieval.summarize_accounting_corpus_coverage(
        ticker="MSFT",
        filings=[
            {"form_type": "10-K", "filing_date": "2025-07-30",
             "accession_no": "0000950170-25-100235", "doc_name": "msft-10k.htm"},
            {"form_type": "8-K", "filing_date": "2026-06-05",
             "accession_no": "0001193125-26-258667", "doc_name": "msft-8k.htm"},
        ],
        parsed_counts={
            ("0000950170-25-100235", "msft-10k.htm"): {"sections": 33, "raw_notes": 18},
        },
    )

    # The 8-K is supplemental and is neither required nor note-checked.
    assert coverage["required_filing_count"] == 1
    assert coverage["cached_filing_count"] == 2
    assert coverage["filings_without_notes"] == []
    assert coverage["complete"] is True


def test_require_accounting_corpus_coverage_passes_when_complete(monkeypatch):
    from src.stage_00_data import filing_retrieval

    complete = {
        "ticker": "MSFT",
        "required_filing_count": 8,
        "parsed_filing_count": 8,
        "missing_filings": [],
        "complete": True,
    }
    monkeypatch.setattr(
        filing_retrieval, "get_accounting_corpus_coverage", lambda ticker: complete
    )

    assert filing_retrieval.require_accounting_corpus_coverage("MSFT") is complete


# --------------------------------------------------------------- guard bookkeeping


def test_forward_driver_proposal_remains_queueable():
    result = build_discovery_accounting_ledger(
        ticker="MSFT",
        focused_analyses=[
            _analysis(
                "margin",
                _recast(
                    driver_proposals=[
                        _driver_proposal(
                            driver_field="ebit_margin_target",
                            proposed_value=0.44,
                        )
                    ]
                ),
                [SECTION_A],
            )
        ],
        evidence_packet_id=214,
    )

    assert len(result.queue_items) == 1
    assert (
        result.queue_items[0].proposal_pack.proposals[0].assumption_name
        == "ebit_margin_target"
    )
