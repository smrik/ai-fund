"""Adapter: open-ended discovery recasts -> accounting ledger -> PM Decision Queue.

The two-pass classification flow (``AccountingDiscoveryAgent`` chooses
company-specific questions, deterministic retrieval assembles focused evidence,
one ``AccountingRecastAgent`` call answers each question) produces one recast
payload per question. This module maps those payloads onto the existing
:mod:`src.stage_04_pipeline.accounting_ledger` machinery without flattening them.

Design rules, all of which have offline regressions in
``tests/test_accounting_discovery_ledger.py``:

* **One item, one finding.** Every income-statement adjustment, balance-sheet
  reclassification, driver proposal, non-null override candidate, and model-change
  proposal becomes its own finding carrying its own ``question_id``. Six analyses
  never collapse into one override map.
* **Driver proposals are how classification reaches the DCF.** A recast that only
  reclassifies balance-sheet claims leaves the forecast unchanged; a
  ``driver_proposals`` entry naming a field in
  ``AGENT_PROPOSABLE_ASSUMPTION_FIELDS`` becomes an assumption change pack for PM
  approval.
* **No-adjustment stays visible.** A question that concludes "nothing to change"
  produces an explicit ``no_adjustment_identified`` finding. It reaches the
  ledger and never reaches the mutation queue.
* **Unsupported treatments become model-change requests.** ``normalized_ebit``
  is in the recast agent's override vocabulary but is *not* in
  ``AGENT_PROPOSABLE_ASSUMPTION_FIELDS``. Such a finding is flagged
  ``model_change_required`` rather than remapped onto a margin driver — that
  remapping is exactly the mismapping the plan froze as a regression.
* **Bridge values come from claim identity.** Direct bridge amounts are rejected.
  An identity-only ``reclassify`` proposal is checked against the exact-once
  claim ledger and its value is derived deterministically.
* **Every mapped finding passes the shared validator** before it is merged, so
  claim/proposal driver alignment is enforced on this path too.

This module never calls an LLM and never mutates valuation inputs. Queue items
are only persisted when the caller supplies a connection.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

from src.contracts.accounting_evidence import AccountingFocusKey, AccountingTopic
from src.contracts.assumption_registry import get_assumption_definition
from src.contracts.pm_decision_queue import (
    AssumptionChangePack,
    AssumptionChangeProposal,
    PMDecisionQueueItem,
    PMDecisionQueueItemType,
    ProposalMode,
    QueueConfidence,
)
from src.stage_02_valuation.claim_ledger import (
    ClaimLedger,
    ClaimReclassificationError,
    EV_BRIDGE_COMPONENTS,
)
from src.stage_04_pipeline.accounting_evidence_runner import _persist_queue_item
from src.stage_04_pipeline.accounting_ledger import (
    AccountingAdjustmentLedger,
    merge_findings_into_ledger,
    translate_accounting_ledger_to_queue_items,
)
from src.stage_04_pipeline.accounting_validation import validate_accounting_finding
from src.stage_04_pipeline.agentic_handoff_profiles import (
    AGENT_PROPOSABLE_ASSUMPTION_FIELDS,
)

DISCOVERY_LEDGER_CONTRACT_VERSION = "1.0.0"

# Bridge claims that live beside debt/cash rather than in the cash-and-investments
# reconciliation. Used only to pick the narrower focus key for review grouping.
_CLAIM_LIKE_DRIVERS = frozenset(
    EV_BRIDGE_COMPONENTS - {"net_debt", "non_operating_assets"}
)

# The recast agent may return this override, but the deterministic model has no
# proposable normalized-EBIT field. It is a model-change request, not a driver.
_NON_PROPOSABLE_OVERRIDES = frozenset({"normalized_ebit"})

# Drivers that sit in the EV-to-equity bridge rather than the operating forecast.
_CLAIM_LEDGER_COMPONENTS = EV_BRIDGE_COMPONENTS
_BRIDGE_DRIVERS = EV_BRIDGE_COMPONENTS | {"shares_outstanding"}

# Discovery questions are open-ended, so no parent accounting topic genuinely
# describes a structural model-change proposal. This is a routing default only;
# the queue path for these findings is driven by ``model_change_required``.
_MODEL_CHANGE_TOPIC = AccountingTopic.qoe
_MODEL_CHANGE_FOCUS = AccountingFocusKey.qoe_revenue

_MAX_LINE_ITEM_CHARS = 160


@dataclass(frozen=True)
class DiscoveryJudgmentContext:
    """The four context blocks every focused judgment call must receive."""

    business_context: str
    industry_context: str
    quantitative_context: str
    current_model_context: str


@dataclass
class DiscoveryAccountingResult:
    ticker: str
    contract_version: str = DISCOVERY_LEDGER_CONTRACT_VERSION
    focused_analyses: list[dict[str, Any]] = field(default_factory=list)
    findings: list[dict[str, Any]] = field(default_factory=list)
    rejected_findings: list[dict[str, Any]] = field(default_factory=list)
    validated_pairs: list[tuple[dict[str, Any], dict[str, Any]]] = field(default_factory=list)
    ledger: AccountingAdjustmentLedger | None = None
    queue_items: list[PMDecisionQueueItem] = field(default_factory=list)
    persisted_queue_item_ids: list[int] = field(default_factory=list)
    coverage: dict[str, Any] | None = None
    reconciled_claim_ledger: dict[str, Any] | None = None


@dataclass
class _ReclassificationState:
    """Build-local cumulative state over an immutable claim ledger."""

    initial_ledger: ClaimLedger | None
    working_ledger: ClaimLedger | None
    applied_by_identity: dict[tuple[str, str, str], Any] = field(
        default_factory=dict
    )
    applied_reported_lines: list[str] = field(default_factory=list)
    failed: bool = False


def _text(value: Any) -> str:
    return str(value or "").strip()


def _truncate(value: str, limit: int = _MAX_LINE_ITEM_CHARS) -> str:
    cleaned = " ".join(value.split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"


def _matched_sections(retrieval_summary: Mapping[str, Any] | None) -> list[str]:
    """Anchor on sections that actually resolved, never on requested-but-missing ones."""

    summary = retrieval_summary or {}
    matched = [
        _text(section_id)
        for section_id in summary.get("matched_section_ids") or []
    ]
    return sorted({section_id for section_id in matched if section_id})


def build_question_packet(
    *,
    ticker: str,
    question_id: str,
    retrieval_summary: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Synthesize the minimal packet shape the shared validator reads.

    The validator resolves evidence anchors through ``source_refs``/``facts``/
    ``snippets``; a retrieved filing section is genuinely a source ref, so the
    matched section ids become the anchor vocabulary for this question.
    """

    sections = _matched_sections(retrieval_summary)
    summary = dict(retrieval_summary or {})
    return {
        "packet_id": f"discovery:{ticker.upper()}:{question_id}",
        "ticker": ticker.upper(),
        "facts": [],
        "snippets": [],
        "source_refs": [
            {
                "source_ref_id": section_id,
                "source_type": "sec_filing_section",
                "locator": section_id,
                "corpus_hash": summary.get("corpus_hash"),
            }
            for section_id in sections
        ],
        # Discovery is open-ended: the validator checks that a finding is
        # internally coherent, and the queue translator narrows to the profile's
        # own allowed fields afterwards.
        "allowed_driver_fields": sorted(
            set(AGENT_PROPOSABLE_ASSUMPTION_FIELDS)
            | set(_CLAIM_LEDGER_COMPONENTS)
        ),
    }


def _focus_for_driver(driver: str | None) -> AccountingFocusKey:
    if driver and driver in _CLAIM_LIKE_DRIVERS:
        return AccountingFocusKey.bridge_leases_pensions_claims
    return AccountingFocusKey.bridge_cash_debt_investments


def _base_finding(
    *,
    ticker: str,
    question_id: str,
    question_text: str,
    recast: Mapping[str, Any],
    anchors: Sequence[str],
    topic: AccountingTopic,
    focus_key: AccountingFocusKey,
    finding_type: str,
    line_item: str,
    claim: str,
    citation_text: str | None,
    extra_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = {
        "question_id": question_id,
        "question": _truncate(question_text, 400),
        "recast_source": _text(recast.get("source")) or None,
        "adapter_contract_version": DISCOVERY_LEDGER_CONTRACT_VERSION,
    }
    metadata.update({k: v for k, v in (extra_metadata or {}).items() if v is not None})
    return {
        "topic": topic.value,
        "focus_key": focus_key.value,
        "finding_type": finding_type,
        "line_item": _truncate(line_item) or finding_type,
        "claim": _truncate(claim, 600) or line_item,
        "evidence_anchor_ids": list(anchors),
        "citation_text": citation_text,
        "confidence": _text(recast.get("confidence")) or None,
        "pm_question": _text(recast.get("pm_review_notes")) or None,
        "metadata": metadata,
    }


def _income_statement_finding(
    item: Mapping[str, Any],
    **base_kwargs: Any,
) -> dict[str, Any]:
    direction = _text(item.get("proposed_ebit_direction")) or "none"
    classification = _text(item.get("classification")) or "unclear"
    rationale = _text(item.get("rationale"))
    finding = _base_finding(
        finding_type="income_statement_adjustment",
        line_item=_text(item.get("item")),
        claim=rationale,
        citation_text=_text(item.get("citation_text")) or None,
        topic=AccountingTopic.qoe,
        focus_key=AccountingFocusKey.qoe_nonrecurring,
        extra_metadata={
            "adjustment_classification": classification,
            "proposed_ebit_direction": direction,
        },
        **base_kwargs,
    )
    finding["reported_value"] = item.get("amount")
    finding["accounting_treatment"] = "normalize" if classification != "unclear" else "unclear"
    finding["booked_or_disclosed_status"] = "booked" if item.get("amount") is not None else "unclear"

    if direction == "none":
        finding["finding_status"] = "no_adjustment_identified"
        finding["valuation_treatment"] = "none"
        finding["accounting_treatment"] = "no_adjustment"
        finding["no_adjustment_reason"] = rationale or (
            "The focused evidence did not support an EBIT normalization."
        )
        return finding

    # A real EBIT normalization has no proposable driver field: it changes the
    # normalized historical starting point, not a margin assumption.
    finding["finding_status"] = "candidate"
    finding["valuation_treatment"] = "normalized_ebit"
    finding["direction"] = direction
    finding["model_change_required"] = True
    finding["model_change_request"] = (
        "Normalized EBIT is not a proposable driver field. The PM must decide whether to "
        f"recast reported EBIT by {direction}{item.get('amount')} before the forecast runs."
    )
    finding["materiality_rationale"] = rationale or None
    return finding


def _reclassification_finding(
    item: Mapping[str, Any],
    **base_kwargs: Any,
) -> dict[str, Any]:
    driver = _text(item.get("proposed_driver_field")) or None
    classification = _text(item.get("classification")) or "unclear"
    rationale = _text(item.get("rationale"))
    finding = _base_finding(
        finding_type="balance_sheet_reclassification",
        line_item=_text(item.get("line_item")),
        claim=rationale,
        citation_text=_text(item.get("citation_text")) or None,
        topic=AccountingTopic.ev_equity_bridge,
        focus_key=_focus_for_driver(driver),
        extra_metadata={"balance_sheet_classification": classification},
        **base_kwargs,
    )
    finding["reported_value"] = item.get("reported_value")
    finding["accounting_treatment"] = "reclassify"
    finding["booked_or_disclosed_status"] = (
        "booked" if item.get("reported_value") is not None else "unclear"
    )

    if driver is None:
        # The agent recorded a classification but named no field the model can
        # change. That is a conclusion, not a mutation; structural asks travel
        # through model_change_proposals instead.
        finding["finding_status"] = "no_adjustment_identified"
        finding["valuation_treatment"] = "disclosure_only"
        finding["no_adjustment_reason"] = rationale or (
            f"Classified as {classification} with no change to an existing driver field."
        )
        return finding

    finding["finding_status"] = "candidate"
    if driver in _CLAIM_LEDGER_COMPONENTS:
        return _reject_unreconciled_bridge_amount(finding, driver)

    finding["claim_driver_field"] = driver
    finding["proposed_driver_field"] = driver
    finding["proposed_value"] = item.get("reported_value")
    finding["valuation_treatment"] = "ev_equity_bridge"
    finding["materiality_rationale"] = rationale or None
    return finding


def _reject_unreconciled_bridge_amount(
    finding: dict[str, Any],
    driver: str,
) -> dict[str, Any]:
    finding["metadata"]["claim_reconciliation_rejected"] = True
    finding["metadata"]["claim_reconciliation_error"] = (
        f"Bridge component {driver!r} cannot accept an agent-authored amount. "
        "Use reclassify with a stable reported_line so the value is derived "
        "from the claim ledger."
    )
    return finding


def _coerce_claim_ledger(
    value: ClaimLedger | Mapping[str, Any] | None,
) -> ClaimLedger | None:
    if value is None or isinstance(value, ClaimLedger):
        return value
    return ClaimLedger.from_dict(value)


def _claim_reclassification_finding(
    item: Mapping[str, Any],
    *,
    claim_ledger: ClaimLedger | None,
    reclassification_state: _ReclassificationState | None = None,
    **base_kwargs: Any,
) -> dict[str, Any]:
    reported_line = _text(item.get("reported_line"))
    from_component = _text(item.get("from_component"))
    to_component = _text(item.get("to_component"))
    rationale = _text(item.get("rationale"))
    finding = _base_finding(
        finding_type="claim_reclassification",
        line_item=reported_line,
        claim=rationale or (
            f"Reclassify {reported_line} from {from_component} to {to_component}."
        ),
        citation_text=_text(item.get("citation_text")) or None,
        topic=AccountingTopic.ev_equity_bridge,
        focus_key=_focus_for_driver(to_component),
        extra_metadata={
            "reported_line": reported_line,
            "from_component": from_component,
            "to_component": to_component,
            "derived_from_claim_ledger": True,
        },
        **base_kwargs,
    )
    finding["finding_status"] = "candidate"
    finding["accounting_treatment"] = "reclassify"
    finding["booked_or_disclosed_status"] = "booked"
    finding["claim_driver_field"] = to_component
    finding["proposed_driver_field"] = to_component
    finding["valuation_treatment"] = "ev_equity_bridge"
    finding["materiality_rationale"] = rationale or None

    if claim_ledger is None:
        finding["metadata"]["claim_reconciliation_rejected"] = True
        finding["metadata"]["claim_reconciliation_error"] = (
            "No claim ledger was supplied; bridge reclassifications fail closed."
        )
        finding["proposed_value"] = None
        finding["reported_value"] = None
        return finding

    state = reclassification_state or _ReclassificationState(
        initial_ledger=claim_ledger,
        working_ledger=claim_ledger,
    )
    identity = (reported_line, from_component, to_component)
    try:
        if identity in state.applied_by_identity:
            reclassified = state.applied_by_identity[identity]
            finding["metadata"]["duplicate_reclassification_identity"] = True
        else:
            if state.working_ledger is None:
                raise ClaimReclassificationError(
                    "No working claim ledger was supplied.",
                    reported_line=reported_line,
                )
            reclassified = state.working_ledger.reclassify(
                reported_line=reported_line,
                from_component=from_component,
                to_component=to_component,
            )
            state.working_ledger = reclassified.ledger
            state.applied_by_identity[identity] = reclassified
            state.applied_reported_lines.append(reported_line)
    except ClaimReclassificationError as exc:
        state.failed = True
        finding["metadata"]["claim_reconciliation_rejected"] = True
        finding["metadata"]["claim_reconciliation_error"] = str(exc)
        finding["metadata"]["incumbent_claimants"] = list(
            exc.incumbent_components
        )
        finding["proposed_value"] = None
        finding["reported_value"] = None
        return finding

    target_value = (
        float(reclassified.derived_component_values[to_component])
        * reclassified.ledger.unit_scale
    )
    finding["reported_value"] = (
        float(reclassified.reported_value) * reclassified.ledger.unit_scale
    )
    finding["proposed_value"] = target_value
    finding["metadata"]["reconciled_ledger"] = reclassified.ledger.to_dict()
    finding["metadata"]["derived_component_values"] = {
        component: float(value) * reclassified.ledger.unit_scale
        for component, value in reclassified.derived_component_values.items()
    }
    return finding


def _override_finding(
    driver: str,
    value: Any,
    **base_kwargs: Any,
) -> dict[str, Any]:
    finding = _base_finding(
        finding_type="bridge_override_candidate",
        line_item=driver,
        claim=f"Focused evidence supports setting {driver} to {value}.",
        # The recast contract carries no citation on an override candidate; the
        # matched section anchors are its provenance.
        citation_text=None,
        topic=(
            AccountingTopic.qoe
            if driver in _NON_PROPOSABLE_OVERRIDES
            else AccountingTopic.ev_equity_bridge
        ),
        focus_key=(
            AccountingFocusKey.qoe_nonrecurring
            if driver in _NON_PROPOSABLE_OVERRIDES
            else _focus_for_driver(driver)
        ),
        extra_metadata={"override_field": driver},
        **base_kwargs,
    )
    finding["finding_status"] = "candidate"
    finding["reported_value"] = value
    finding["accounting_treatment"] = "bridge_adjustment"
    finding["booked_or_disclosed_status"] = "disclosed_not_booked"

    if driver in _CLAIM_LEDGER_COMPONENTS:
        return _reject_unreconciled_bridge_amount(finding, driver)

    if driver in _NON_PROPOSABLE_OVERRIDES:
        finding["valuation_treatment"] = "normalized_ebit"
        finding["model_change_required"] = True
        finding["model_change_request"] = (
            f"{driver} has no proposable driver field; the PM must approve a normalized "
            "historical recast rather than a driver override."
        )
        return finding

    finding["claim_driver_field"] = driver
    finding["proposed_driver_field"] = driver
    finding["proposed_value"] = value
    finding["valuation_treatment"] = "ev_equity_bridge"
    return finding


def _driver_proposal_finding(
    item: Mapping[str, Any],
    **base_kwargs: Any,
) -> dict[str, Any]:
    """A forward-looking driver value the accounting evidence supports.

    This is the path by which classification actually reaches the DCF. Bridge
    reclassifications alone leave the forecast untouched.
    """

    driver = _text(item.get("driver_field"))
    rationale = _text(item.get("rationale"))
    finding = _base_finding(
        finding_type="driver_proposal",
        line_item=driver,
        claim=rationale or f"Evidence supports setting {driver} to {item.get('proposed_value')}.",
        citation_text=_text(item.get("citation_text")) or None,
        topic=(
            AccountingTopic.ev_equity_bridge
            if driver in _BRIDGE_DRIVERS
            else AccountingTopic.qoe
        ),
        focus_key=(
            _focus_for_driver(driver)
            if driver in _BRIDGE_DRIVERS
            else AccountingFocusKey.qoe_nonrecurring
        ),
        extra_metadata={"driver_field": driver},
        **base_kwargs,
    )
    finding["finding_status"] = "candidate"
    finding["accounting_treatment"] = "reclassify" if driver in _BRIDGE_DRIVERS else "normalize"
    finding["booked_or_disclosed_status"] = "not_applicable"
    finding["direction"] = _text(item.get("direction")) or None
    finding["materiality_rationale"] = rationale or None

    if driver in _CLAIM_LEDGER_COMPONENTS:
        return _reject_unreconciled_bridge_amount(finding, driver)

    finding["claim_driver_field"] = driver
    finding["proposed_driver_field"] = driver
    finding["proposed_value"] = item.get("proposed_value")
    finding["reported_value"] = None
    finding["valuation_treatment"] = (
        "ev_equity_bridge" if driver in _BRIDGE_DRIVERS else "historical_recast"
    )
    return finding


def _model_change_finding(
    item: Mapping[str, Any],
    **base_kwargs: Any,
) -> dict[str, Any]:
    proposal = _text(item.get("proposal"))
    finding = _base_finding(
        finding_type="model_change_proposal",
        line_item=proposal,
        claim=_text(item.get("reasoning")) or proposal,
        citation_text=_text(item.get("citation_text")) or None,
        topic=_MODEL_CHANGE_TOPIC,
        focus_key=_MODEL_CHANGE_FOCUS,
        extra_metadata={
            "implementation_status": _text(item.get("implementation_status")) or None,
            "valuation_effect": _text(item.get("valuation_effect")) or None,
            "topic_is_routing_default": True,
        },
        **base_kwargs,
    )
    finding["finding_status"] = "candidate"
    finding["accounting_treatment"] = "unclear"
    finding["valuation_treatment"] = "none"
    finding["booked_or_disclosed_status"] = "not_applicable"
    finding["model_change_required"] = True
    finding["model_change_request"] = proposal
    finding["materiality_rationale"] = _text(item.get("valuation_effect")) or None
    return finding


def recast_to_findings(
    *,
    ticker: str,
    question_id: str,
    question_text: str,
    recast: Mapping[str, Any],
    retrieval_summary: Mapping[str, Any] | None,
    claim_ledger: ClaimLedger | Mapping[str, Any] | None = None,
    _reclassification_state: _ReclassificationState | None = None,
) -> list[dict[str, Any]]:
    """Map one focused recast payload onto independent accounting findings."""

    bridge_ledger = _coerce_claim_ledger(claim_ledger)
    reclassification_state = _reclassification_state or _ReclassificationState(
        initial_ledger=bridge_ledger,
        working_ledger=bridge_ledger,
    )
    anchors = _matched_sections(retrieval_summary)
    base_kwargs = {
        "ticker": ticker,
        "question_id": question_id,
        "question_text": question_text,
        "recast": recast,
        "anchors": anchors,
    }

    findings: list[dict[str, Any]] = []
    for item in recast.get("income_statement_adjustments") or []:
        if isinstance(item, Mapping) and _text(item.get("item")):
            findings.append(_income_statement_finding(item, **base_kwargs))
    # The recast contract can express one claim through three channels: a balance-sheet
    # reclassification naming a driver, a driver proposal, and an override candidate.
    # One (driver, value) pair inside one question is one claim. Emitting it per channel
    # produced duplicate assumption packs and a phantom self-contradiction in the
    # 2026-07-25 live MSFT run. Reclassifications are kept in preference because they
    # carry the reported accounting line item; the dropped channels are recorded.
    claimed: dict[tuple[str, Any], dict[str, Any]] = {}

    def _claim_key(driver: str, value: Any) -> tuple[str, Any] | None:
        return (driver, value) if driver else None

    for item in recast.get("reclassify") or []:
        if not isinstance(item, Mapping) or not _text(item.get("reported_line")):
            continue
        finding = _claim_reclassification_finding(
            item,
            claim_ledger=bridge_ledger,
            reclassification_state=reclassification_state,
            **base_kwargs,
        )
        findings.append(finding)
        key = _claim_key(
            _text(finding.get("proposed_driver_field")),
            finding.get("proposed_value"),
        )
        if key is not None:
            claimed.setdefault(key, finding)

    for item in recast.get("balance_sheet_reclassifications") or []:
        if not isinstance(item, Mapping) or not _text(item.get("line_item")):
            continue
        finding = _reclassification_finding(item, **base_kwargs)
        findings.append(finding)
        key = _claim_key(
            _text(item.get("proposed_driver_field")), item.get("reported_value")
        )
        if key is not None:
            claimed.setdefault(key, finding)
    for item in recast.get("driver_proposals") or []:
        if not isinstance(item, Mapping):
            continue
        driver = _text(item.get("driver_field"))
        if not driver:
            continue
        key = _claim_key(driver, item.get("proposed_value"))
        existing = claimed.get(key) if key else None
        if existing is not None:
            existing["metadata"]["also_proposed_via"] = "driver_proposal"
            # The reclassification kept the claim; preserve the proposal's reasoning.
            if not existing.get("materiality_rationale"):
                existing["materiality_rationale"] = _text(item.get("rationale")) or None
            continue
        finding = _driver_proposal_finding(item, **base_kwargs)
        findings.append(finding)
        if key is not None:
            claimed[key] = finding

    for driver, value in (recast.get("override_candidates") or {}).items():
        if value is None:
            continue
        driver = _text(driver)
        key = _claim_key(driver, value)
        existing = claimed.get(key) if key else None
        if existing is not None:
            existing["metadata"]["also_proposed_via"] = "override_candidate"
            continue
        finding = _override_finding(driver, value, **base_kwargs)
        findings.append(finding)
        if key is not None:
            claimed[key] = finding
    for item in recast.get("model_change_proposals") or []:
        if isinstance(item, Mapping) and _text(item.get("proposal")):
            findings.append(_model_change_finding(item, **base_kwargs))

    if not findings:
        findings.append(
            {
                **_base_finding(
                    finding_type="focused_question_review",
                    line_item=_truncate(question_text) or question_id,
                    claim=_text(recast.get("pm_review_notes"))
                    or "No adjustment identified from the focused evidence.",
                    citation_text=None,
                    topic=AccountingTopic.qoe,
                    focus_key=_MODEL_CHANGE_FOCUS,
                    extra_metadata={"topic_is_routing_default": True},
                    **base_kwargs,
                ),
                "finding_status": "no_adjustment_identified",
                "accounting_treatment": "no_adjustment",
                "valuation_treatment": "none",
                "booked_or_disclosed_status": "not_applicable",
                "no_adjustment_reason": _text(recast.get("pm_review_notes"))
                or "The focused evidence supported no change to the current model.",
            }
        )
    return findings


def _coalesce_reclassification_queue_items(
    *,
    ticker: str,
    evidence_packet_id: int | str,
    queue_items: list[PMDecisionQueueItem],
    accepted_findings: Sequence[Mapping[str, Any]],
    state: _ReclassificationState,
) -> list[PMDecisionQueueItem]:
    """Replace per-line bridge mutations with one final-ledger atomic pack."""

    claim_items = [
        item
        for item in queue_items
        if (
            isinstance(item.metadata.get("finding_metadata"), Mapping)
            and item.metadata["finding_metadata"].get(
                "derived_from_claim_ledger"
            )
            is True
        )
    ]
    other_items = [item for item in queue_items if item not in claim_items]
    if (
        state.failed
        or state.initial_ledger is None
        or state.working_ledger is None
        or not state.applied_by_identity
    ):
        return other_items

    initial = state.initial_ledger
    final = state.working_ledger
    changed_components = [
        component
        for component in sorted(
            set(initial.component_values) | set(final.component_values)
        )
        if component != "unclaimed"
        and float(initial.component_values.get(component, 0.0))
        != float(final.component_values.get(component, 0.0))
    ]
    if not changed_components:
        return other_items

    reclassification_findings = [
        finding
        for finding in accepted_findings
        if (finding.get("metadata") or {}).get("derived_from_claim_ledger")
        is True
    ]
    anchors = sorted(
        {
            _text(anchor)
            for finding in reclassification_findings
            for anchor in finding.get("evidence_anchor_ids") or []
            if _text(anchor)
        }
    )
    if not anchors:
        return other_items

    proposals = [
        AssumptionChangeProposal(
            assumption_name=component,
            proposal_mode=ProposalMode.target,
            proposed_target_value=(
                float(final.component_values.get(component, 0.0))
                * final.unit_scale
            ),
            unit=get_assumption_definition(component).unit,
            evidence_anchor_ids=anchors,
            rationale=(
                "Derived from the cumulative exact-once claim-ledger "
                "reclassification family."
            ),
            metadata={
                "derived_from_claim_ledger": True,
                "initial_claim_ledger_fingerprint": initial.fingerprint,
                "final_claim_ledger_fingerprint": final.fingerprint,
            },
        )
        for component in changed_components
    ]
    reported_lines = sorted(set(state.applied_reported_lines))
    pack = AssumptionChangePack(
        pack_id=f"pack:accounting-claim-ledger:{ticker}:{final.fingerprint[:16]}",
        proposals=proposals,
        notes={
            "atomic_reclassification": True,
            "reported_lines": reported_lines,
            "initial_claim_ledger_fingerprint": initial.fingerprint,
            "final_claim_ledger_fingerprint": final.fingerprint,
        },
    )
    exemplar = claim_items[0] if claim_items else None
    atomic_item = PMDecisionQueueItem(
        ticker=ticker,
        profile_name=(
            exemplar.profile_name
            if exemplar is not None
            else "accounting_ev_equity_bridge"
        ),
        item_type=PMDecisionQueueItemType.assumption_change_pack,
        status="pending",
        title="Review atomic EV-bridge reclassification",
        summary=(
            "Reclassify "
            + ", ".join(reported_lines)
            + " using the reconciled final bridge."
        ),
        evidence_anchor_ids=anchors,
        evidence_packet_ids=[str(evidence_packet_id)],
        proposal_pack=pack,
        agent_confidence=(
            exemplar.agent_confidence
            if exemplar is not None
            else QueueConfidence.medium
        ),
        translator_confidence=QueueConfidence.high,
        metadata={
            "finding_metadata": {
                "derived_from_claim_ledger": True,
                "atomic_reclassification": True,
                "reported_lines": reported_lines,
                "changed_components": changed_components,
            },
            "initial_claim_ledger": initial.to_dict(),
            "reconciled_claim_ledger": final.to_dict(),
        },
    )
    return [*other_items, atomic_item]


def build_discovery_accounting_ledger(
    *,
    ticker: str,
    focused_analyses: Sequence[Mapping[str, Any]],
    evidence_packet_id: int | str,
    claim_ledger: ClaimLedger | Mapping[str, Any] | None = None,
    conn: sqlite3.Connection | None = None,
) -> DiscoveryAccountingResult:
    """Merge per-question recast payloads into the ledger and PM queue.

    ``focused_analyses`` is the artifact shape written by the discovery runner:
    ``{question_id, question, retrieval_summary, recast}``. Passing a saved
    artifact replays the mapping without any agent call.
    """

    ticker = ticker.upper().strip()
    bridge_ledger = _coerce_claim_ledger(claim_ledger)
    reclassification_state = _ReclassificationState(
        initial_ledger=bridge_ledger,
        working_ledger=bridge_ledger,
    )
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    validated_pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    pending_validation: list[tuple[dict[str, Any], dict[str, Any]]] = []

    for analysis in focused_analyses:
        question_id = _text(analysis.get("question_id")) or "unnamed_question"
        retrieval_summary = analysis.get("retrieval_summary") or {}
        packet = build_question_packet(
            ticker=ticker,
            question_id=question_id,
            retrieval_summary=retrieval_summary,
        )
        findings = recast_to_findings(
            ticker=ticker,
            question_id=question_id,
            question_text=_text(analysis.get("question")),
            recast=analysis.get("recast") or {},
            retrieval_summary=retrieval_summary,
            claim_ledger=bridge_ledger,
            _reclassification_state=reclassification_state,
        )
        pending_validation.extend((finding, packet) for finding in findings)

    final_claim_ledger = (
        reclassification_state.initial_ledger
        if reclassification_state.failed
        else reclassification_state.working_ledger
    )
    if (
        final_claim_ledger is not None
        and reclassification_state.applied_by_identity
    ):
        final_components = final_claim_ledger.component_values
        for finding, _packet in pending_validation:
            metadata = finding.get("metadata") or {}
            if metadata.get("derived_from_claim_ledger") is not True:
                continue
            target = _text(metadata.get("to_component"))
            finding["proposed_value"] = (
                float(final_components.get(target, 0.0))
                * final_claim_ledger.unit_scale
            )
            finding["metadata"]["reconciled_ledger"] = (
                final_claim_ledger.to_dict()
            )
            finding["metadata"]["derived_component_values"] = {
                component: float(value) * final_claim_ledger.unit_scale
                for component, value in final_components.items()
            }

    for finding, packet in pending_validation:
        metadata = finding.get("metadata") or {}
        is_claim_reclassification = (
            metadata.get("derived_from_claim_ledger") is True
        )
        if (
            reclassification_state.failed
            and is_claim_reclassification
            and not metadata.get("claim_reconciliation_rejected")
        ):
            finding = {
                **finding,
                "metadata": {
                    **metadata,
                    "atomic_reclassification_batch_rejected": True,
                    "claim_reconciliation_rejected": True,
                    "claim_reconciliation_error": (
                        "The identity-only reclassification family was rejected "
                        "atomically because another proposal in the same family "
                        "could not reconcile."
                    ),
                },
            }
        if finding.get("metadata", {}).get("claim_reconciliation_rejected"):
            finding = {
                **finding,
                "metadata": {
                    **finding.get("metadata", {}),
                    "validation_issues": [
                        {
                            "code": "claim_reconciliation_rejected",
                            "message": finding["metadata"][
                                "claim_reconciliation_error"
                            ],
                            "field": "reclassify",
                        }
                    ],
                },
            }
            rejected.append(finding)
            continue
        result = validate_accounting_finding(finding, packet)
        if result.valid:
            accepted.append(finding)
            validated_pairs.append((finding, packet))
            continue
        # A mapping defect must stay auditable rather than disappear; the
        # ledger keeps it as rejected_after_repair and never queues it.
        finding = {
            **finding,
            "metadata": {
                **finding.get("metadata", {}),
                "validation_issues": [
                    {
                        "code": issue.code,
                        "message": issue.message,
                        "field": issue.field,
                    }
                    for issue in result.issues
                ],
            },
        }
        rejected.append(finding)

    ledger = merge_findings_into_ledger(
        ticker=ticker,
        findings=accepted,
        rejected_findings=rejected,
        metadata={
            "source": "accounting_discovery_two_pass",
            "adapter_contract_version": DISCOVERY_LEDGER_CONTRACT_VERSION,
            "question_count": len(focused_analyses),
            "claim_ledger_supplied": claim_ledger is not None,
        },
    )
    queue_items = translate_accounting_ledger_to_queue_items(
        ledger,
        ticker=ticker,
        evidence_packet_id=evidence_packet_id,
    )
    queue_items = _coalesce_reclassification_queue_items(
        ticker=ticker,
        evidence_packet_id=evidence_packet_id,
        queue_items=queue_items,
        accepted_findings=accepted,
        state=reclassification_state,
    )
    persisted = (
        [_persist_queue_item(conn, item) for item in queue_items]
        if conn is not None
        else []
    )
    return DiscoveryAccountingResult(
        ticker=ticker,
        focused_analyses=[dict(analysis) for analysis in focused_analyses],
        findings=accepted,
        rejected_findings=rejected,
        validated_pairs=validated_pairs,
        ledger=ledger,
        queue_items=queue_items,
        persisted_queue_item_ids=persisted,
        reconciled_claim_ledger=(
            final_claim_ledger.to_dict()
            if final_claim_ledger is not None
            else None
        ),
    )


def _bundle_field(bundle: Any, name: str) -> Any:
    if isinstance(bundle, Mapping):
        return bundle.get(name)
    return getattr(bundle, name, None)


def run_discovery_accounting_pass(
    *,
    ticker: str,
    discovery: Mapping[str, Any],
    contexts: DiscoveryJudgmentContext,
    evidence_packet_id: int | str,
    retrieval_callable: Callable[..., Any] | None = None,
    recast_callable: Callable[..., Mapping[str, Any]] | None = None,
    reported_ebit: float | None = None,
    claim_ledger: ClaimLedger | Mapping[str, Any] | None = None,
    conn: sqlite3.Connection | None = None,
    require_corpus_coverage: bool = True,
    max_selected_chunks: int = 12,
) -> DiscoveryAccountingResult:
    """Run one focused recast per discovery question, then build the ledger.

    Every focused call receives the business, industry, quantitative, and
    current-model/source-lineage context — that contract is why this loop lives
    in a module rather than a script. Nothing is persisted unless ``conn`` is
    supplied, so validation runs cannot mutate the live queue.
    """

    from src.stage_00_data import filing_retrieval

    ticker = ticker.upper().strip()
    coverage: dict[str, Any] | None = None
    if require_corpus_coverage:
        coverage = filing_retrieval.require_accounting_corpus_coverage(ticker)

    if retrieval_callable is None:
        def retrieval_callable(ticker: str, question: Mapping[str, Any]) -> Any:  # noqa: F811
            return filing_retrieval.get_discovery_filing_context(
                ticker,
                {"questions": [dict(question)]},
                max_selected_chunks=max_selected_chunks,
            )

    if recast_callable is None:
        from src.stage_03_judgment.accounting_recast_agent import AccountingRecastAgent

        recast_callable = AccountingRecastAgent().analyze

    focused_analyses: list[dict[str, Any]] = []
    for question in discovery.get("questions") or []:
        if not isinstance(question, Mapping):
            continue
        question_id = _text(question.get("question_id")) or "unnamed_question"
        bundle = retrieval_callable(ticker, question)
        analysis_task = (
            f"Question: {_text(question.get('question'))}\n"
            f"Why it matters: {_text(question.get('why_it_matters'))}\n"
            "Test the question against the focused evidence. Do not assume an "
            "adjustment is needed. If a sound treatment does not fit an existing "
            "driver, use model_change_proposals."
        )
        recast = recast_callable(
            ticker=ticker,
            reported_ebit=reported_ebit,
            filing_text=_bundle_field(bundle, "rendered_text"),
            business_context=contexts.business_context,
            industry_context=contexts.industry_context,
            quantitative_context=contexts.quantitative_context,
            current_model_context=contexts.current_model_context,
            analysis_task=analysis_task,
        )
        focused_analyses.append(
            {
                "question_id": question_id,
                "question": _text(question.get("question")),
                "retrieval_summary": _bundle_field(bundle, "retrieval_summary") or {},
                "recast": dict(recast or {}),
            }
        )

    result = build_discovery_accounting_ledger(
        ticker=ticker,
        focused_analyses=focused_analyses,
        evidence_packet_id=evidence_packet_id,
        claim_ledger=claim_ledger,
        conn=conn,
    )
    result.coverage = coverage
    return result


__all__ = [
    "DISCOVERY_LEDGER_CONTRACT_VERSION",
    "DiscoveryAccountingResult",
    "DiscoveryJudgmentContext",
    "build_discovery_accounting_ledger",
    "build_question_packet",
    "recast_to_findings",
    "run_discovery_accounting_pass",
]
