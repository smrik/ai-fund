"""Production service for persisted statement reconciliation and PM findings."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timedelta, timezone
import math
import sqlite3
from typing import Any, Mapping, Sequence

from db.loader import (
    insert_pm_decision_queue_item,
    load_statement_facts,
    load_active_treatment_decisions,
)
from src.contracts.judgment_runs import canonical_semantic_hash
from src.contracts.pm_decision_queue import PMDecisionQueueItem
from src.stage_00_data.source_reconciliation import (
    ExpectedSourceQuantity,
    ReconciliationFinding,
    SourceAmount,
    StatementCheckResult,
    StatementReadinessResult,
    assess_statement_readiness,
    canonical_statement_key,
    reconcile_persisted_statement_facts,
    source_amount_from_statement_fact,
    validate_balance_sheet_identity,
    validate_calculation_rollup,
    validate_cash_bridge,
)
from src.stage_04_pipeline.statement_reconciliation_store import (
    load_statement_source_manifests,
    persist_statement_reconciliation_run,
)


@dataclass(frozen=True, slots=True)
class TickerStatementReconciliationRun:
    ticker: str
    facts_fingerprint: str
    readiness: StatementReadinessResult
    persisted_queue_item_ids: tuple[int, ...]
    run_hash: str
    as_of_date: str
    raw_ledger_hash: str
    selected_view_hash: str
    manifest_ids: tuple[str, ...]
    selected_fact_ids: tuple[str, ...]


_PRESENTATION_SOURCE_PREFIX = "sec_xbrl_filing_presentation"
_ANNUAL_REQUIRED_KEYS = {
    "IncomeStatement": frozenset(
        {"revenue", "operating_income", "net_income"}
    ),
    "CashFlowStatement": frozenset(
        {
            "operating_cash_flow",
            "capex",
            "da",
        }
    ),
}
_LTM_REQUIRED_KEYS = frozenset(
    {
        "revenue",
        "operating_income",
        "net_income",
        "operating_cash_flow",
        "capex",
        "da",
    }
)
_MAX_ANNUAL_PERIODS = 5
_RECONCILIATION_CONTRACT_VERSION = "statement_reconciliation_v2"


def _manifest_entries(
    manifest: Mapping[str, Any],
) -> tuple[Mapping[str, Any], ...]:
    coverage = manifest.get("coverage")
    raw_entries: Any
    if isinstance(coverage, Mapping):
        raw_entries = coverage.get("entries") or ()
    else:
        raw_entries = coverage or ()
    if isinstance(raw_entries, Mapping):
        values = raw_entries.values()
    elif isinstance(raw_entries, Sequence) and not isinstance(
        raw_entries,
        (str, bytes),
    ):
        values = raw_entries
    else:
        return ()
    return tuple(
        entry for entry in values if isinstance(entry, Mapping)
    )


def _stored_manifest_id(manifest: Mapping[str, Any]) -> str:
    store = manifest.get("_store") or {}
    return str(
        store.get("manifest_id") or manifest.get("manifest_id") or ""
    )


def _select_source_manifests(
    manifests: Sequence[Mapping[str, Any]],
) -> tuple[Mapping[str, Any], ...]:
    completed = tuple(
        manifest
        for manifest in manifests
        if str(manifest.get("status") or "").lower() == "completed"
    )
    ciq = next(
        (
            manifest
            for manifest in completed
            if str(manifest.get("source") or "")
            .lower()
            .startswith("ciq")
            and (manifest.get("_store") or {}).get("source_run_id")
            is not None
        ),
        None,
    )

    # Prefer the most recently written manifest for each filing vintage. The store
    # orders by `evidence_cutoff DESC` first, but that field is a filter bound rather
    # than a recency signal: a stale manifest can carry a run-date cutoff later than a
    # freshly written manifest's filing-date cutoff, in which case re-ingestion could
    # never supersede it.
    def _created_at(manifest: Mapping[str, Any]) -> str:
        return str((manifest.get("_store") or {}).get("created_at") or "")

    by_recency = sorted(completed, key=_created_at, reverse=True)

    xbrl: list[Mapping[str, Any]] = []
    seen_vintages: set[str] = set()
    for manifest in by_recency:
        source = str(manifest.get("source") or "").lower()
        if not (
            source.startswith(_PRESENTATION_SOURCE_PREFIX)
            or source == "sec_filing_xbrl"
        ):
            continue
        store = manifest.get("_store") or {}
        vintage = str(
            store.get("accession")
            or manifest.get("accession")
            or _stored_manifest_id(manifest)
        )
        if vintage in seen_vintages:
            continue
        seen_vintages.add(vintage)
        if not _manifest_contract_complete(manifest):
            # An incomplete manifest carries no usable inventory, and one left behind
            # by a wider earlier ingestion window can never be superseded — no current
            # refresh reaches its vintage. Selecting it made attestation permanently
            # impossible. Coverage and period checks still fail closed on what remains.
            continue
        xbrl.append(manifest)
        if len(xbrl) >= _MAX_ANNUAL_PERIODS + 1:
            break
    return tuple([*xbrl, *([ciq] if ciq is not None else [])])


def _manifest_contract_complete(
    manifest: Mapping[str, Any],
) -> bool:
    entries = _manifest_entries(manifest)
    if not entries:
        return False
    source = str(manifest.get("source") or "").lower()
    for entry in entries:
        if not (
            (entry.get("statement") or entry.get("statement_kind"))
            and entry.get("statement_role")
            and entry.get("period_end")
            and entry.get("period_kind")
        ):
            return False
        units = entry.get("units") or (
            [entry.get("unit")] if entry.get("unit") else []
        )
        currencies = entry.get("currencies") or (
            [entry.get("currency")] if entry.get("currency") else []
        )
        if not units or not currencies:
            return False
        if source.startswith(_PRESENTATION_SOURCE_PREFIX):
            inventory_ids = tuple(
                value
                for field in (
                    "presented_fact_ids",
                    "consolidated_fact_ids",
                    "dimensioned_fact_ids",
                    "fact_ids",
                )
                for value in (entry.get(field) or ())
            )
            if not inventory_ids:
                return False
    if source.startswith(_PRESENTATION_SOURCE_PREFIX):
        edges = manifest.get("calculation_edges")
        if not isinstance(edges, Sequence) or isinstance(
            edges,
            (str, bytes),
        ):
            return False
        for edge in edges:
            if not isinstance(edge, Mapping) or not (
                edge.get("statement_role")
                and edge.get("parent_concept")
                and edge.get("child_concept")
                and edge.get("weight") is not None
            ):
                return False
            try:
                weight = float(edge["weight"])
            except (TypeError, ValueError):
                return False
            if not math.isfinite(weight):
                return False
        return True
    if source.startswith("ciq"):
        return (manifest.get("_store") or {}).get("source_run_id") is not None
    return False


def _manifest_fact_ids(
    manifests: Sequence[Mapping[str, Any]],
) -> set[str]:
    fact_ids: set[str] = set()
    for manifest in manifests:
        for entry in _manifest_entries(manifest):
            for field in (
                "presented_fact_ids",
                "consolidated_fact_ids",
                "dimensioned_fact_ids",
                "fact_ids",
            ):
                values = entry.get(field) or ()
                if isinstance(values, Sequence) and not isinstance(
                    values,
                    (str, bytes),
                ):
                    fact_ids.update(
                        str(value) for value in values if str(value)
                    )
    return fact_ids


def _manifest_entry_keys(
    manifests: Sequence[Mapping[str, Any]],
) -> set[str]:
    keys: set[str] = set()
    for manifest in manifests:
        coverage = manifest.get("coverage")
        if isinstance(coverage, Mapping):
            raw_entries = coverage.get("entries") or {}
            if isinstance(raw_entries, Mapping):
                keys.update(str(key) for key in raw_entries)
    return keys


def _facts_as_of(
    facts: Sequence[Mapping[str, Any]],
    evidence_cutoff: str,
) -> tuple[Mapping[str, Any], ...]:
    selected: list[Mapping[str, Any]] = []
    for fact in facts:
        filing_date = str(fact.get("filing_date") or "")
        if filing_date and filing_date > evidence_cutoff:
            continue
        if not filing_date:
            period_end = str(fact.get("period_end") or "")
            if period_end and period_end > evidence_cutoff:
                continue
        selected.append(fact)
    return tuple(selected)


def _apply_manifest_calculation_edges(
    facts: Sequence[Mapping[str, Any]],
    xbrl_manifests: Sequence[Mapping[str, Any]],
) -> tuple[Mapping[str, Any], ...]:
    by_child: dict[
        tuple[str, str, str],
        list[tuple[Mapping[str, Any], str]],
    ] = {}
    for manifest in xbrl_manifests:
        store = manifest.get("_store") or {}
        accession = str(
            store.get("accession") or manifest.get("accession") or ""
        )
        edges = manifest.get("calculation_edges") or ()
        if not isinstance(edges, Sequence) or isinstance(
            edges,
            (str, bytes),
        ):
            continue
        for edge in edges:
            if not isinstance(edge, Mapping):
                continue
            statement_role = str(edge.get("statement_role") or "")
            child = _concept_token(edge.get("child_concept"))
            parent = _concept_token(edge.get("parent_concept"))
            if (
                not statement_role
                or not child
                or not parent
                or edge.get("weight") is None
            ):
                continue
            by_child.setdefault(
                (accession, statement_role, child),
                [],
            ).append((edge, _stored_manifest_id(manifest)))

    out: list[Mapping[str, Any]] = []
    for fact in facts:
        source = str(fact.get("source") or "").lower()
        if not source.startswith(_PRESENTATION_SOURCE_PREFIX):
            out.append(fact)
            continue
        hierarchy = dict(fact.get("hierarchy") or {})
        role = str(hierarchy.get("statement_role") or "")
        candidates = by_child.get(
            (
                str(fact.get("accession") or ""),
                role,
                _concept_token(fact.get("concept")),
            ),
            [],
        )
        hierarchy.pop("calculation_parent", None)
        hierarchy.pop("calculation_weight", None)
        hierarchy.pop("calculation_manifest_id", None)
        if len(candidates) == 1:
            edge, manifest_id = candidates[0]
            hierarchy["calculation_parent"] = edge["parent_concept"]
            hierarchy["calculation_weight"] = float(edge["weight"])
            hierarchy["calculation_manifest_id"] = manifest_id
        out.append({**dict(fact), "hierarchy": hierarchy})
    return tuple(out)


def _manifest_bound_facts(
    facts: Sequence[Mapping[str, Any]],
    manifests: Sequence[Mapping[str, Any]],
) -> tuple[Mapping[str, Any], ...]:
    xbrl_manifests = tuple(
        manifest
        for manifest in manifests
        if str(manifest.get("source") or "")
        .lower()
        .startswith(_PRESENTATION_SOURCE_PREFIX)
        or str(manifest.get("source") or "").lower()
        == "sec_filing_xbrl"
    )
    ciq_manifest = next(
        (
            manifest
            for manifest in manifests
            if str(manifest.get("source") or "")
            .lower()
            .startswith("ciq")
        ),
        None,
    )
    xbrl_fact_ids = _manifest_fact_ids(xbrl_manifests)
    xbrl_accessions = {
        str(
            (manifest.get("_store") or {}).get("accession")
            or manifest.get("accession")
            or ""
        )
        for manifest in xbrl_manifests
    } - {""}
    ciq_fact_ids = (
        _manifest_fact_ids((ciq_manifest,))
        if ciq_manifest is not None
        else set()
    )
    ciq_entry_keys = (
        _manifest_entry_keys((ciq_manifest,))
        if ciq_manifest is not None
        else set()
    )
    ciq_run_id = (
        (ciq_manifest.get("_store") or {}).get("source_run_id")
        if ciq_manifest is not None
        else None
    )

    selected: list[Mapping[str, Any]] = []
    for fact in facts:
        source = str(fact.get("source") or "").lower()
        fact_id = str(fact.get("fact_id") or "")
        if source.startswith(_PRESENTATION_SOURCE_PREFIX):
            if not xbrl_manifests:
                continue
            if xbrl_fact_ids and fact_id not in xbrl_fact_ids:
                continue
            if (
                not xbrl_fact_ids
                and str(fact.get("accession") or "")
                not in xbrl_accessions
            ):
                continue
            selected.append(fact)
            continue
        if source.startswith("sec_xbrl_derived_ltm"):
            if xbrl_manifests:
                selected.append(fact)
            continue
        if source.startswith("ciq"):
            if ciq_manifest is None or fact.get("source_run_id") != ciq_run_id:
                continue
            coverage_key = str(
                (fact.get("hierarchy") or {}).get(
                    "coverage_entry_key"
                )
                or ""
            )
            if ciq_fact_ids:
                if fact_id not in ciq_fact_ids:
                    continue
            elif ciq_entry_keys and coverage_key not in ciq_entry_keys:
                continue
            selected.append(fact)
    return _apply_manifest_calculation_edges(selected, xbrl_manifests)


def _xbrl_source_priority(source: str) -> int:
    if source.startswith(_PRESENTATION_SOURCE_PREFIX):
        return 3
    if source.startswith("sec_xbrl_derived_ltm"):
        return 2
    return 1


def _selected_consolidated_xbrl_facts(
    facts: Sequence[Mapping[str, Any]],
) -> tuple[Mapping[str, Any], ...]:
    selected: dict[
        tuple[Any, ...],
        tuple[tuple[int, str, str, str], Mapping[str, Any]],
    ] = {}
    for fact in facts:
        source = str(fact.get("source") or "").lower()
        if not (
            source.startswith(_PRESENTATION_SOURCE_PREFIX)
            or source.startswith("sec_xbrl_derived_ltm")
        ):
            continue
        if fact.get("numeric_value") is None or fact.get("dimensions"):
            continue
        amount = source_amount_from_statement_fact(fact)
        identity = (
            amount.statement,
            amount.canonical_key,
            amount.period_start,
            amount.period_end,
            amount.period_kind,
            amount.statement_role,
            amount.presentation_path,
            amount.context_ref,
            amount.unit_kind,
            amount.unit_currency,
        )
        vintage = (
            _xbrl_source_priority(source),
            str(fact.get("filing_date") or ""),
            str(fact.get("accession") or ""),
            str(fact.get("ingestion_fingerprint") or ""),
        )
        previous = selected.get(identity)
        if previous is None or vintage > previous[0]:
            selected[identity] = (vintage, fact)
    return tuple(
        value[1]
        for _, value in sorted(
            selected.items(),
            key=lambda item: (
                item[0][3],
                item[0][0],
                item[0][1],
                item[0][2] or "",
                item[0][4] or "",
                *(str(value or "") for value in item[0][5:]),
            ),
        )
    )


def _consolidated_xbrl_amounts(
    facts: Sequence[Mapping[str, Any]],
) -> tuple[SourceAmount, ...]:
    return tuple(
        source_amount_from_statement_fact(fact)
        for fact in _selected_consolidated_xbrl_facts(facts)
    )


def _canonical_keys(
    facts: Sequence[Mapping[str, Any]],
) -> set[str]:
    return {
        canonical_statement_key(
            str(fact.get("concept") or ""),
            str(fact.get("label") or ""),
        )
        for fact in facts
    }


def _balance_sheet_coverage(keys: set[str]) -> bool:
    return (
        "assets" in keys
        and bool(
            {"cash_and_equivalents", "cash_including_restricted"} & keys
        )
        and (
            "liabilities_and_equity" in keys
            or {"liabilities", "equity_including_nci"}.issubset(keys)
            or {"liabilities", "equity_parent"}.issubset(keys)
        )
    )


def _cash_flow_coverage(keys: set[str]) -> bool:
    return (
        _ANNUAL_REQUIRED_KEYS["CashFlowStatement"].issubset(keys)
        and bool(
            {
                "net_change_in_cash_and_equivalents",
                "net_change_in_cash_including_restricted",
            }
            & keys
        )
    )


def _presentation_attested(
    facts: Sequence[Mapping[str, Any]],
) -> bool:
    return bool(facts) and all(
        bool((fact.get("hierarchy") or {}).get("statement_role"))
        for fact in facts
    )


def _annual_period_count(
    facts: Sequence[Mapping[str, Any]],
    *,
    approved_treatments: Sequence[Mapping[str, Any]] | None = None,
    corroborating_facts: Sequence[Mapping[str, Any]] | None = None,
) -> tuple[int, tuple[str, ...]]:
    by_period: dict[str, dict[str, list[Mapping[str, Any]]]] = {}
    for fact in facts:
        source = str(fact.get("source") or "").lower()
        if not source.startswith(_PRESENTATION_SOURCE_PREFIX):
            continue
        if str(fact.get("period_kind") or "").lower() != "annual":
            continue
        statement = str(fact.get("statement") or "")
        period_end = str(fact.get("period_end") or "")
        if statement and period_end:
            by_period.setdefault(period_end, {}).setdefault(
                statement,
                [],
            ).append(fact)

    complete: list[str] = []
    for period_end, statements in by_period.items():
        if set(statements) < {
            "IncomeStatement",
            "BalanceSheet",
            "CashFlowStatement",
        }:
            continue
        if not all(
            _presentation_attested(statement_facts)
            for statement_facts in statements.values()
        ):
            continue
        income_keys = _canonical_keys(statements["IncomeStatement"])
        cash_flow_keys = _canonical_keys(
            statements["CashFlowStatement"]
        )
        balance_keys = _canonical_keys(statements["BalanceSheet"])
        # A PM-approved treatment is the sanctioned way to supply a canonical key the
        # filing does not present purely (e.g. MSFT reporting only a combined
        # "depreciation, amortization, and other" line). The deterministic layer never
        # chooses the convention; it only honours an approved one.
        ticker = next(
            (
                str(fact.get("ticker") or "")
                for statement_facts in statements.values()
                for fact in statement_facts
                if fact.get("ticker")
            ),
            "",
        )
        for supplied in ("da", "capex", "operating_cash_flow"):
            if supplied not in cash_flow_keys and _treatment_supplies(
                approved_treatments,
                ticker=ticker,
                canonical_key=supplied,
            ):
                cash_flow_keys = cash_flow_keys | {supplied}
        # PM decision 2026-07-31: a combined "depreciation, amortization, and other"
        # line sources `da` from CIQ, with the difference reported as an ordinary source
        # disagreement. `_annual_period_count` only sees presentation facts, so the CIQ
        # side is checked against the full fact set for this period.
        if "da" not in cash_flow_keys and _combined_da_resolved_by_ciq(
            corroborating_facts if corroborating_facts is not None else facts,
            period_end=period_end,
        ):
            cash_flow_keys = cash_flow_keys | {"da"}
        if (
            _ANNUAL_REQUIRED_KEYS["IncomeStatement"].issubset(income_keys)
            and _cash_flow_coverage(cash_flow_keys)
            and _balance_sheet_coverage(balance_keys)
        ):
            complete.append(period_end)
    periods = tuple(sorted(complete, reverse=True)[:_MAX_ANNUAL_PERIODS])
    return len(periods), periods


def _keys_by_source_family(
    facts: Sequence[Mapping[str, Any]],
    *,
    statement: str,
    prefix: str,
    period_end: str | None = None,
) -> set[str]:
    return {
        canonical_statement_key(
            str(fact.get("concept") or ""),
            str(fact.get("label") or ""),
        )
        for fact in facts
        if str(fact.get("source") or "").lower().startswith(prefix)
        and str(fact.get("statement") or "") == statement
        and (period_end is None or str(fact.get("period_end") or "") == period_end)
    }


def _combined_da_resolved_by_ciq(
    facts: Sequence[Mapping[str, Any]],
    *,
    period_end: str | None = None,
) -> bool:
    """PM decision 2026-07-31: a combined D&A line sources `da` from CIQ.

    Where a filer presents only "depreciation, amortization, and other" (an entity
    extension), the pure D&A figure is taken from CIQ and the difference surfaces as an
    ordinary source disagreement rather than blocking the ticker. Keyed on the shape of
    the disclosure, never on a ticker — the plan's scale contract forbids
    symbol-specific finance rules.
    """

    xbrl_keys = _keys_by_source_family(
        facts, statement="CashFlowStatement", prefix="sec_xbrl", period_end=period_end
    )
    if "da" in xbrl_keys or "depreciation_amortization_and_other" not in xbrl_keys:
        return False
    ciq_keys = _keys_by_source_family(
        facts, statement="CashFlowStatement", prefix="ciq", period_end=period_end
    )
    return "da" in ciq_keys


def _treatment_supplies(
    approved_treatments: Sequence[Mapping[str, Any]] | None,
    *,
    ticker: str,
    canonical_key: str,
) -> bool:
    """Is there an active, PM-approved treatment supplying this canonical key?

    The deterministic layer must never pick an accounting convention (Vision Decision
    11), but it must offer a seam for the PM's decision to take effect. Without this,
    a combined-line gate such as `pure_da_evidence_missing` is unresolvable in code and
    the ticker can never reach a valuation no matter what the PM approves.
    """

    for treatment in approved_treatments or ():
        if not isinstance(treatment, Mapping):
            continue
        if str(treatment.get("ticker") or "").upper() != ticker.upper():
            continue
        # `treatment_decisions` records the field a treatment concerns in
        # `driver_field`; an explicit `canonical_key` is accepted for callers that
        # carry one directly.
        supplied = str(
            treatment.get("canonical_key")
            or treatment.get("driver_field")
            or ""
        )
        if supplied != canonical_key:
            continue
        if not treatment.get("active"):
            continue
        status = str(treatment.get("status") or "approved").lower()
        if status not in {"approved", "active"}:
            continue
        return True
    return False


def _semantic_source_reason_codes(
    facts: Sequence[Mapping[str, Any]],
    *,
    approved_treatments: Sequence[Mapping[str, Any]] | None = None,
) -> tuple[str, ...]:
    cash_flow_keys = {
        canonical_statement_key(
            str(fact.get("concept") or ""),
            str(fact.get("label") or ""),
        )
        for fact in facts
        if str(fact.get("source") or "")
        .lower()
        .startswith("sec_xbrl")
        and str(fact.get("statement") or "") == "CashFlowStatement"
    }
    if (
        "da" not in cash_flow_keys
        and "depreciation_amortization_and_other"
        in cash_flow_keys
    ):
        ticker = next(
            (str(fact.get("ticker") or "") for fact in facts if fact.get("ticker")),
            "",
        )
        if not _combined_da_resolved_by_ciq(facts) and not _treatment_supplies(
            approved_treatments,
            ticker=ticker,
            canonical_key="da",
        ):
            return ("pure_da_evidence_missing",)
    return ()


def _ltm_group_key(
    fact: Mapping[str, Any],
) -> tuple[str, str, str, str]:
    source = str(fact.get("source") or "").lower()
    source_family = (
        "derived"
        if source.startswith("sec_xbrl_derived_ltm")
        else "presentation"
    )
    return (
        source_family,
        str(fact.get("accession") or ""),
        str(fact.get("period_start") or ""),
        str(fact.get("period_end") or ""),
    )


def _ltm_groups(
    facts: Sequence[Mapping[str, Any]],
) -> dict[tuple[str, str, str, str], tuple[Mapping[str, Any], ...]]:
    grouped: dict[
        tuple[str, str, str, str],
        list[Mapping[str, Any]],
    ] = {}
    for fact in _selected_consolidated_xbrl_facts(facts):
        if not (
            str(fact.get("source") or "")
            .lower()
            .startswith("sec_xbrl")
            and str(fact.get("period_kind") or "").lower() == "ltm"
            and not fact.get("dimensions")
        ):
            continue
        grouped.setdefault(_ltm_group_key(fact), []).append(fact)
    return {
        key: tuple(value)
        for key, value in grouped.items()
    }


def _preferred_ltm_group(
    facts: Sequence[Mapping[str, Any]],
) -> tuple[
    tuple[str, str, str, str] | None,
    tuple[Mapping[str, Any], ...],
]:
    groups = _ltm_groups(facts)
    if not groups:
        return None, ()
    ordered = sorted(
        groups.items(),
        key=lambda item: (
            len(_LTM_REQUIRED_KEYS & _canonical_keys(item[1])),
            item[0][3],
            item[0][2],
            item[0][0] == "presentation",
            item[0][1],
        ),
        reverse=True,
    )
    return ordered[0]


def _ltm_status(
    facts: Sequence[Mapping[str, Any]],
) -> str:
    groups = [
        (key, group)
        for key, group in _ltm_groups(facts).items()
        if _LTM_REQUIRED_KEYS.issubset(_canonical_keys(group))
    ]
    if not groups:
        return "unavailable"
    _, ltm = max(
        groups,
        key=lambda item: (
            item[0][3],
            item[0][2],
            item[0][0] == "presentation",
            item[0][1],
        ),
    )
    if all(bool(fact.get("is_derived")) for fact in ltm):
        return "constructed"
    if all(
        str(fact.get("source") or "")
        .lower()
        .startswith(_PRESENTATION_SOURCE_PREFIX)
        for fact in ltm
    ):
        return "source_provided"
    return "unavailable"


def _bounded_selected_view(
    facts: Sequence[Mapping[str, Any]],
    *,
    approved_treatments: Sequence[Mapping[str, Any]] | None = None,
) -> tuple[Mapping[str, Any], ...]:
    xbrl = _selected_consolidated_xbrl_facts(facts)
    # The bound is derived from the complete annual periods, so it must honour the same
    # PM-approved treatments the readiness gate does. Without this the view collapses to
    # a single period for any issuer whose filing needs a treatment, and every
    # downstream check reports "missing" rather than the real reason.
    _, annual_periods = _annual_period_count(
        xbrl,
        approved_treatments=approved_treatments,
        # The CIQ side of the combined-D&A rule lives outside the XBRL view.
        corroborating_facts=facts,
    )
    annual_ends = set(annual_periods)
    ltm_key, ltm_group = _preferred_ltm_group(xbrl)
    ltm_window = (
        (ltm_key[2], ltm_key[3])
        if ltm_key is not None
        else None
    )

    opening_dates: set[str] = set()
    for fact in xbrl:
        if str(fact.get("period_end") or "") not in annual_ends:
            continue
        key = canonical_statement_key(
            str(fact.get("concept") or ""),
            str(fact.get("label") or ""),
        )
        if key not in {
            "net_change_in_cash_and_equivalents",
            "net_change_in_cash_including_restricted",
        }:
            continue
        period_start = str(fact.get("period_start") or "")
        if not period_start:
            continue
        try:
            opening_dates.add(
                (
                    date.fromisoformat(period_start)
                    - timedelta(days=1)
                ).isoformat()
            )
        except ValueError:
            continue

    component_ids: set[str] = set()
    for fact in ltm_group:
        derivation = fact.get("derivation") or {}
        values = derivation.get("component_fact_ids") or ()
        if isinstance(values, Sequence) and not isinstance(
            values,
            (str, bytes),
        ):
            component_ids.update(str(value) for value in values)

    selected: list[Mapping[str, Any]] = []
    for fact in facts:
        period_kind = str(fact.get("period_kind") or "").lower()
        period_start = str(fact.get("period_start") or "")
        period_end = str(fact.get("period_end") or "")
        fact_id = str(fact.get("fact_id") or "")
        include = (
            (period_kind == "annual" and period_end in annual_ends)
            or (
                period_kind == "ltm"
                and ltm_window == (period_start, period_end)
            )
            or fact_id in component_ids
            or (
                str(fact.get("period_type") or "").lower()
                == "instant"
                and period_end in opening_dates
            )
        )
        if include:
            selected.append(fact)
    return tuple(
        sorted(
            selected,
            key=lambda fact: (
                str(fact.get("source") or ""),
                str(fact.get("statement") or ""),
                str(fact.get("period_end") or ""),
                str(fact.get("period_start") or ""),
                str(fact.get("fact_id") or ""),
            ),
        )
    )


_EXPECTED_ROLE_STATEMENTS = {
    "revenue": "IncomeStatement",
    "operating_income": "IncomeStatement",
    "net_income": "IncomeStatement",
    "operating_cash_flow": "CashFlowStatement",
    "capex": "CashFlowStatement",
    "da": "CashFlowStatement",
    "net_change_in_cash_and_equivalents": "CashFlowStatement",
    "net_change_in_cash_including_restricted": "CashFlowStatement",
    "assets": "BalanceSheet",
    "cash_and_equivalents": "BalanceSheet",
    "cash_including_restricted": "BalanceSheet",
}


def _ltm_window_is_superseded(
    *,
    ltm_period_end: str,
    annual_period_ends: Sequence[str],
) -> bool:
    """Is the trailing window older than the latest complete fiscal year?

    A trailing-twelve-month window that closes before the most recent complete annual
    period carries nothing the annual data does not already cover more recently. CALM
    derives an LTM ending 2026-02-28 while FY2026 closes 2026-05-30, and CIQ publishes
    its own LTM on different dates entirely, so requiring cross-source overlap on the
    derived window produced blocking findings for figures neither source disputes.
    """

    if not annual_period_ends:
        return False
    latest_annual = max(str(end) for end in annual_period_ends if end)
    return bool(latest_annual) and latest_annual >= str(ltm_period_end)


def _expected_source_quantities(
    facts: Sequence[Mapping[str, Any]],
    *,
    approved_treatments: Sequence[Mapping[str, Any]] | None = None,
) -> tuple[ExpectedSourceQuantity, ...]:
    xbrl = _selected_consolidated_xbrl_facts(facts)
    _, annual_periods = _annual_period_count(
        xbrl,
        approved_treatments=approved_treatments,
        corroborating_facts=facts,
    )
    expected: dict[
        tuple[str, str, str | None, str, str],
        ExpectedSourceQuantity,
    ] = {}

    for period_end in annual_periods:
        period_facts = tuple(
            fact
            for fact in xbrl
            if str(fact.get("period_kind") or "").lower() == "annual"
            and str(fact.get("period_end") or "") == period_end
        )
        keys = _canonical_keys(period_facts)
        # The cash expectation is looked up on the balance sheet, so it must be chosen
        # from balance-sheet keys. Both MSFT and CALM report
        # `CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents` on the *cash
        # flow* statement while the balance sheet carries plain cash and equivalents;
        # choosing from the combined key set demanded a balance-sheet line that never
        # exists and raised `missing_source_overlap` on every period.
        balance_sheet_keys = _canonical_keys(
            [
                fact
                for fact in period_facts
                if str(fact.get("statement") or "") == "BalanceSheet"
            ]
        )
        cash_key = (
            "cash_including_restricted"
            if "cash_including_restricted" in balance_sheet_keys
            else "cash_and_equivalents"
        )
        net_change_key = (
            "net_change_in_cash_including_restricted"
            if "net_change_in_cash_including_restricted" in keys
            else "net_change_in_cash_and_equivalents"
        )
        required = {
            *_ANNUAL_REQUIRED_KEYS["IncomeStatement"],
            *_ANNUAL_REQUIRED_KEYS["CashFlowStatement"],
            "assets",
            cash_key,
            net_change_key,
        }
        # PM decision 2026-07-31: where a filer presents only a combined
        # "depreciation, amortization, and other" line, `da` is sourced from CIQ. Asking
        # XBRL for a pure D&A it never reports would raise a blocking
        # `missing_source_overlap` on every period for a gap the decision already
        # resolved. The CIQ sourcing stays visible on the fact's own `source`.
        if _combined_da_resolved_by_ciq(facts, period_end=period_end):
            required.discard("da")
        for canonical_key in required:
            statement = _EXPECTED_ROLE_STATEMENTS[canonical_key]
            candidates = [
                fact
                for fact in period_facts
                if str(fact.get("statement") or "") == statement
                and canonical_statement_key(
                    str(fact.get("concept") or ""),
                    str(fact.get("label") or ""),
                )
                == canonical_key
            ]
            period_start = (
                str(candidates[0].get("period_start"))
                if candidates and candidates[0].get("period_start")
                else None
            )
            identity = (
                statement,
                canonical_key,
                period_start,
                period_end,
                "annual",
            )
            expected[identity] = ExpectedSourceQuantity(
                ticker=str(period_facts[0].get("ticker") or ""),
                statement=statement,
                canonical_key=canonical_key,
                period_start=period_start,
                period_end=period_end,
                period_kind="annual",
            )

    ltm_key, ltm_group = _preferred_ltm_group(xbrl)
    if (
        ltm_key is not None
        and ltm_group
        and not _ltm_window_is_superseded(
            ltm_period_end=str(ltm_key[3]),
            annual_period_ends=annual_periods,
        )
    ):
        period_start, period_end = ltm_key[2], ltm_key[3]
        ticker = str(ltm_group[0].get("ticker") or "")
        ltm_required = set(_LTM_REQUIRED_KEYS)
        # Same PM decision as the annual periods: a filer presenting only a combined
        # "depreciation, amortization, and other" line sources `da` from CIQ, so XBRL is
        # not asked for a pure D&A it never reports.
        if _combined_da_resolved_by_ciq(facts):
            ltm_required.discard("da")
        for canonical_key in sorted(ltm_required):
            statement = _EXPECTED_ROLE_STATEMENTS[canonical_key]
            identity = (
                statement,
                canonical_key,
                period_start,
                period_end,
                "ltm",
            )
            expected[identity] = ExpectedSourceQuantity(
                ticker=ticker,
                statement=statement,
                canonical_key=canonical_key,
                period_start=period_start,
                period_end=period_end,
                period_kind="ltm",
            )
    # Keys carry an optional period_start, so a None sorts against a str as soon as a
    # ticker has both duration and instant expectations. Coerce for ordering only.
    return tuple(
        expected[key]
        for key in sorted(
            expected,
            key=lambda item: tuple("" if part is None else str(part) for part in item),
        )
    )


def _amount(
    amounts: Sequence[SourceAmount],
    *,
    key: str,
    period_end: str,
) -> SourceAmount | None:
    candidates = [
        amount
        for amount in amounts
        if amount.canonical_key == key and amount.period_end == period_end
    ]
    return candidates[-1] if candidates else None


def _bridge_required_for_period(
    period_end: str,
    window_period_ends: Sequence[str],
) -> bool:
    """Is a cash bridge structurally testable for this period?

    The bridge needs the prior period's closing cash. For the earliest period in the
    selected window that balance sits outside the window, so requiring it blocks
    permanently on data that cannot be present.
    """

    ends = sorted({str(end) for end in window_period_ends if end})
    if len(ends) < 2:
        return False
    return str(period_end) != ends[0]


def _statement_checks(
    amounts: Sequence[SourceAmount],
    complete_periods: Sequence[str],
    facts: Sequence[Mapping[str, Any]],
    rollup_facts: Sequence[Mapping[str, Any]] | None = None,
) -> tuple[StatementCheckResult, ...]:
    if not complete_periods:
        return ()
    checks: list[StatementCheckResult] = []
    periods = tuple(sorted(set(complete_periods), reverse=True))
    for period_end in periods:
        assets = _amount(amounts, key="assets", period_end=period_end)
        if assets is not None:
            equity = _amount(
                amounts,
                key="equity_including_nci",
                period_end=period_end,
            ) or _amount(
                amounts,
                key="equity_parent",
                period_end=period_end,
            )
            checks.append(
                validate_balance_sheet_identity(
                    assets=assets,
                    liabilities_and_equity=_amount(
                        amounts,
                        key="liabilities_and_equity",
                        period_end=period_end,
                    ),
                    liabilities=_amount(
                        amounts,
                        key="liabilities",
                        period_end=period_end,
                    ),
                    equity=equity,
                )
            )

        net_change = _amount(
            amounts,
            key="net_change_in_cash_including_restricted",
            period_end=period_end,
        )
        cash_key = "cash_including_restricted"
        if net_change is None:
            net_change = _amount(
                amounts,
                key="net_change_in_cash_and_equivalents",
                period_end=period_end,
            )
            cash_key = "cash_and_equivalents"
        ending_cash = _amount(
            amounts,
            key=cash_key,
            period_end=period_end,
        )
        prior_period_end: str | None = None
        if net_change is not None and net_change.period_start:
            try:
                prior_period_end = (
                    date.fromisoformat(net_change.period_start)
                    - timedelta(days=1)
                ).isoformat()
            except ValueError:
                prior_period_end = None
        beginning_cash = (
            _amount(
                amounts,
                key=cash_key,
                period_end=prior_period_end,
            )
            if prior_period_end
            else None
        )
        if beginning_cash is None and prior_period_end:
            # The opening balance may be presented under the other cash variant. MSFT's
            # bridge keys on `cash_including_restricted` while its 2021-06-30 opening
            # balance is tagged `cash_and_equivalents`, so the earliest period could
            # never bridge even though the figure was present.
            for alternate in (
                "cash_and_equivalents",
                "cash_including_restricted",
            ):
                if alternate == cash_key:
                    continue
                beginning_cash = _amount(
                    amounts,
                    key=alternate,
                    period_end=prior_period_end,
                )
                if beginning_cash is not None:
                    break
        if _bridge_required_for_period(period_end, periods) and any(
            amount is not None
            for amount in (beginning_cash, net_change, ending_cash)
        ):
            checks.append(
                validate_cash_bridge(
                    beginning_cash=beginning_cash,
                    net_change=net_change,
                    ending_cash=ending_cash,
                )
            )
    checks.extend(
        _calculation_rollup_checks(
            # The full fact set, not the vintage-collapsed selected view: a
            # calculation linkbase belongs to one filing and must roll up against that
            # filing's own facts.
            facts=rollup_facts if rollup_facts is not None else facts,
            eligible_periods=set(complete_periods),
        )
    )
    return tuple(checks)


def _concept_token(value: Any) -> str:
    return "".join(
        character
        for character in str(value or "").lower()
        if character.isalnum()
    )


def _calculation_rollup_checks(
    *,
    facts: Sequence[Mapping[str, Any]],
    eligible_periods: set[str],
) -> tuple[StatementCheckResult, ...]:
    # Deliberately NOT the selected consolidated view. That view keeps the newest
    # vintage per concept, which is correct for restatements but wrong here: a
    # calculation linkbase belongs to one filing and must roll up against that
    # filing's own facts. Mixing vintages orphaned children under an accession their
    # parent did not share, producing `not_ready` parents and short-summing groups.
    # The identity tuple below already partitions by accession, so every filing is
    # checked independently.
    selected = [
        fact
        for fact in facts
        if str(fact.get("period_end") or "") in eligible_periods
        and fact.get("numeric_value") is not None
        and not fact.get("dimensions")
        and str(fact.get("source") or "")
        .lower()
        .startswith(_PRESENTATION_SOURCE_PREFIX)
    ]
    # A later filing repeats prior periods as comparatives, usually abbreviated. Holding
    # an abbreviated comparative to a full calculation rollup manufactures failures, so
    # each (statement, role, period) is rolled up using the filing that presents it most
    # completely — in practice the filing that reported it as its current year.
    presentation_size: dict[tuple[str, str, str], dict[str, int]] = {}
    for fact in selected:
        hierarchy = fact.get("hierarchy") or {}
        scope = (
            str(fact.get("statement") or ""),
            str(hierarchy.get("statement_role") or ""),
            str(fact.get("period_end") or ""),
        )
        accession = str(fact.get("accession") or "")
        presentation_size.setdefault(scope, {})
        presentation_size[scope][accession] = (
            presentation_size[scope].get(accession, 0) + 1
        )
    primary_accession = {
        scope: max(counts.items(), key=lambda item: (item[1], item[0]))[0]
        for scope, counts in presentation_size.items()
    }
    selected = [
        fact
        for fact in selected
        if str(fact.get("accession") or "")
        == primary_accession.get(
            (
                str(fact.get("statement") or ""),
                str((fact.get("hierarchy") or {}).get("statement_role") or ""),
                str(fact.get("period_end") or ""),
            )
        )
    ]

    parents: dict[
        tuple[str, str, str, str, str, str],
        list[Mapping[str, Any]],
    ] = {}
    for fact in selected:
        hierarchy = fact.get("hierarchy") or {}
        identity = (
            str(fact.get("statement") or ""),
            str(fact.get("period_start") or ""),
            str(fact.get("period_end") or ""),
            _concept_token(fact.get("concept")),
            str(fact.get("accession") or ""),
            str(hierarchy.get("statement_role") or ""),
        )
        parents.setdefault(identity, []).append(fact)
    grouped: dict[
        tuple[str, str, str, str, str, str],
        list[tuple[Mapping[str, Any], float]],
    ] = {}
    for fact in selected:
        hierarchy = fact.get("hierarchy") or {}
        parent = hierarchy.get("calculation_parent")
        weight = hierarchy.get("calculation_weight")
        if not parent or weight is None:
            continue
        identity = (
            str(fact.get("statement") or ""),
            str(fact.get("period_start") or ""),
            str(fact.get("period_end") or ""),
            _concept_token(parent),
            str(fact.get("accession") or ""),
            str(hierarchy.get("statement_role") or ""),
        )
        grouped.setdefault(identity, []).append((fact, float(weight)))

    # A concept presented more than once under the same parent is one component, not
    # several. Summing each occurrence double-counted children and inflated the rollup
    # (CALM: parent 1,427,489,000 vs components summing 2,531,834,000, the difference
    # being one child counted twice). Two *different* concepts sharing a value are kept.
    ambiguous_children: dict[
        tuple[str, str, str, str, str, str],
        tuple[str, ...],
    ] = {}
    for identity, children in list(grouped.items()):
        seen: set[tuple[str, Any, float]] = set()
        by_concept: dict[str, set[Any]] = {}
        deduped: list[tuple[Mapping[str, Any], float]] = []
        for fact, weight in children:
            token = _concept_token(fact.get("concept"))
            value = source_amount_from_statement_fact(fact).base_value
            by_concept.setdefault(token, set()).add(value)
            occurrence = (token, value, weight)
            if occurrence in seen:
                continue
            seen.add(occurrence)
            deduped.append((fact, weight))
        # One concept contributes to a rollup once. If its occurrences disagree, which
        # figure is correct is not something deterministic code can decide, so the
        # rollup is reported ambiguous rather than summing both or guessing one.
        conflicting = tuple(
            sorted(
                str(next(
                    fact.get("concept")
                    for fact, _ in children
                    if _concept_token(fact.get("concept")) == token
                ))
                for token, values in by_concept.items()
                if len(values) > 1
            )
        )
        if conflicting:
            ambiguous_children[identity] = conflicting
        grouped[identity] = deduped

    checks: list[StatementCheckResult] = []
    for identity, children in sorted(grouped.items()):
        parent_facts = parents.get(identity, [])
        if identity in ambiguous_children:
            child_amounts = tuple(
                source_amount_from_statement_fact(child) for child, _ in children
            )
            anchor = child_amounts[0]
            conflicting = ambiguous_children[identity]
            finding_identity = {
                "type": "source_calculation_rollup_ambiguous_child",
                "ticker": anchor.ticker,
                "statement": identity[0],
                "period_end": identity[2],
                "parent_concept": identity[3],
                "conflicting_concepts": list(conflicting),
            }
            checks.append(
                StatementCheckResult(
                    check_name="source_calculation_rollup",
                    status="not_ready",
                    expected_value=None,
                    actual_value=None,
                    difference=None,
                    tolerance=None,
                    source_fact_ids=tuple(a.fact_id for a in child_amounts),
                    finding=ReconciliationFinding(
                        finding_id=(
                            "reconciliation:" + canonical_semantic_hash(finding_identity)
                        ),
                        ticker=anchor.ticker,
                        finding_type="source_calculation_rollup_not_ready",
                        severity="warning",
                        title="Source calculation child is presented more than once",
                        description=(
                            "These concepts appear multiple times under parent "
                            f"{identity[3]!r} with different values, so the rollup "
                            "cannot be evaluated without choosing between them: "
                            + ", ".join(conflicting)
                        ),
                        canonical_key=identity[3],
                        statement=identity[0],
                        period_end=identity[2],
                        source_fact_ids=tuple(a.fact_id for a in child_amounts),
                        source_locators=tuple(
                            a.source_locator for a in child_amounts if a.source_locator
                        ),
                        observed_values={
                            f"child:{a.fact_id}": a.base_value for a in child_amounts
                        },
                        tolerance=None,
                        metadata={
                            "period_start": identity[1],
                            "parent_concept": identity[3],
                            "accession": identity[4],
                            "statement_role": identity[5],
                        },
                    ),
                )
            )
            continue
        if len(parent_facts) > 1:
            # A concept presented more than once on one statement is preserved as
            # distinct occurrence fact ids by design. When every occurrence reports the
            # same amount it is one quantity, not an ambiguity, so the rollup proceeds.
            # Genuinely conflicting parents still fall through to `not_ready`.
            parent_values = {
                source_amount_from_statement_fact(fact).base_value
                for fact in parent_facts
            }
            if len(parent_values) == 1:
                parent_facts = parent_facts[:1]
        if len(parent_facts) != 1:
            child_amounts = tuple(
                source_amount_from_statement_fact(child)
                for child, _ in children
            )
            anchor = child_amounts[0]
            finding_identity = {
                "type": "source_calculation_rollup_not_ready",
                "ticker": anchor.ticker,
                "statement": identity[0],
                "period_start": identity[1],
                "period_end": identity[2],
                "parent_concept": identity[3],
                "child_fact_ids": sorted(
                    amount.fact_id for amount in child_amounts
                ),
                "parent_fact_count": len(parent_facts),
            }
            checks.append(
                StatementCheckResult(
                    check_name="source_calculation_rollup",
                    status="not_ready",
                    expected_value=None,
                    actual_value=None,
                    difference=None,
                    tolerance=None,
                    source_fact_ids=tuple(
                        amount.fact_id for amount in child_amounts
                    ),
                    finding=ReconciliationFinding(
                        finding_id=(
                            "reconciliation:"
                            + canonical_semantic_hash(finding_identity)
                        ),
                        ticker=anchor.ticker,
                        finding_type=(
                            "source_calculation_rollup_not_ready"
                        ),
                        severity="warning",
                        title=(
                            "Source calculation parent is not uniquely "
                            "available"
                        ),
                        description=(
                            "The attested calculation inventory names "
                            f"parent {identity[3]!r}, but the selected "
                            f"period has {len(parent_facts)} matching "
                            "parent facts."
                        ),
                        canonical_key=identity[3],
                        statement=identity[0],
                        period_end=identity[2],
                        source_fact_ids=tuple(
                            amount.fact_id for amount in child_amounts
                        ),
                        source_locators=tuple(
                            amount.source_locator
                            for amount in child_amounts
                            if amount.source_locator
                        ),
                        observed_values={
                            "parent_fact_count": len(parent_facts),
                            **{
                                f"child:{amount.fact_id}": (
                                    amount.base_value
                                )
                                for amount in child_amounts
                            },
                        },
                        tolerance=None,
                        metadata={
                            "period_start": identity[1],
                            "parent_concept": identity[3],
                            "accession": identity[4],
                            "statement_role": identity[5],
                        },
                    ),
                )
            )
            continue
        parent_fact = parent_facts[0]
        checks.append(
            validate_calculation_rollup(
                parent=source_amount_from_statement_fact(parent_fact),
                components=tuple(
                    source_amount_from_statement_fact(child)
                    for child, _ in children
                ),
                weights=tuple(weight for _, weight in children),
            )
        )
    return tuple(checks)


def assess_persisted_statement_facts(
    facts: Sequence[Mapping[str, Any]],
    *,
    expected_quantities: Sequence[ExpectedSourceQuantity] | None = None,
    approved_treatments: Sequence[Mapping[str, Any]] | None = None,
) -> StatementReadinessResult:
    """Reconcile a complete immutable fact set without database side effects."""

    source_reconciliation = reconcile_persisted_statement_facts(
        facts,
        expected_quantities=expected_quantities,
    )
    selected_facts = _selected_consolidated_xbrl_facts(facts)
    amounts = tuple(
        source_amount_from_statement_fact(fact)
        for fact in selected_facts
    )
    annual_count, complete_periods = _annual_period_count(
        selected_facts,
        approved_treatments=approved_treatments,
        corroborating_facts=facts,
    )
    checks = _statement_checks(
        amounts,
        complete_periods,
        selected_facts,
        rollup_facts=facts,
    )
    readiness = assess_statement_readiness(
        source_reconciliation=source_reconciliation,
        checks=checks,
        annual_period_count=annual_count,
        ltm_status=_ltm_status(facts),
        complete_presentation_history=annual_count >= 3,
    )
    # Pass the full fact set: the CIQ side of the combined-D&A rule is not present in
    # the XBRL-only consolidated view.
    semantic_reasons = _semantic_source_reason_codes(
        facts,
        approved_treatments=approved_treatments,
    )
    if not semantic_reasons:
        return readiness
    return replace(
        readiness,
        status="blocked",
        decision_grade=False,
        reason_codes=tuple(
            dict.fromkeys([*readiness.reason_codes, *semantic_reasons])
        ),
    )


def _persist_findings(
    conn: sqlite3.Connection,
    *,
    ticker: str,
    findings: Sequence[ReconciliationFinding],
    selected_view_hash: str,
) -> tuple[int, ...]:
    ids: list[int] = []
    current_keys: list[str] = []
    savepoint = "statement_reconciliation_findings"
    conn.execute(f"SAVEPOINT {savepoint}")
    try:
        for finding in findings:
            dedupe_key = canonical_semantic_hash(
                {
                    "contract_version": (
                        _RECONCILIATION_CONTRACT_VERSION
                    ),
                    "ticker": ticker,
                    "selected_view_hash": selected_view_hash,
                    "finding_id": finding.finding_id,
                }
            )
            current_keys.append(dedupe_key)
            payload = finding.as_queue_payload()
            payload["metadata"] = {
                **dict(payload.get("metadata") or {}),
                "reconciliation_contract_version": (
                    _RECONCILIATION_CONTRACT_VERSION
                ),
                "selected_view_hash": selected_view_hash,
            }
            if not payload.get("evidence_anchor_ids"):
                payload["evidence_anchor_ids"] = [
                    "statement-manifest:"
                    f"{selected_view_hash}:{finding.finding_id}"
                ]
            queue_item = PMDecisionQueueItem.model_validate(
                payload
            )
            row = queue_item.model_dump(mode="json")
            row["valuation_impact_bucket"] = (
                "high" if finding.blocking else "medium"
            )
            row["dedupe_key"] = dedupe_key
            ids.append(
                insert_pm_decision_queue_item(
                    conn,
                    row,
                    commit=False,
                )
            )

        params: list[Any] = [
            datetime.now(timezone.utc).isoformat(),
            ticker,
        ]
        current_clause = ""
        if current_keys:
            current_clause = (
                " AND (dedupe_key IS NULL OR dedupe_key NOT IN "
                f"({','.join('?' for _ in current_keys)}))"
            )
            params.extend(current_keys)
        conn.execute(
            f"""
            UPDATE pm_decision_queue_items
            SET status = 'superseded', updated_at = ?
            WHERE ticker = ?
              AND profile_name = 'statement_reconciliation'
              AND status = 'pending'
              {current_clause}
            """,
            params,
        )
        conn.execute(f"RELEASE SAVEPOINT {savepoint}")
    except Exception:
        conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
        conn.execute(f"RELEASE SAVEPOINT {savepoint}")
        raise
    return tuple(ids)


def _resolve_evidence_cutoff(
    facts: Sequence[Mapping[str, Any]],
    manifests: Sequence[Mapping[str, Any]],
    evidence_cutoff: str | None,
) -> str:
    if evidence_cutoff is not None:
        resolved = str(evidence_cutoff)
        date.fromisoformat(resolved)
        return resolved
    candidates = [
        str(value)
        for value in (
            *[
                (manifest.get("_store") or {}).get("evidence_cutoff")
                or manifest.get("evidence_cutoff")
                for manifest in manifests
            ],
            *[
                fact.get("filing_date") or fact.get("period_end")
                for fact in facts
            ],
        )
        if value
    ]
    resolved = max(candidates, default=date.today().isoformat())
    date.fromisoformat(resolved)
    return resolved


def _fact_identity_payload(
    fact: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "fact_id": str(fact.get("fact_id") or ""),
        "ingestion_fingerprint": str(
            fact.get("ingestion_fingerprint") or ""
        ),
        "source": str(fact.get("source") or ""),
        "source_run_id": fact.get("source_run_id"),
        "accession": fact.get("accession"),
        "statement": str(fact.get("statement") or ""),
        "concept": str(fact.get("concept") or ""),
        "period_start": fact.get("period_start"),
        "period_end": fact.get("period_end"),
        "period_kind": fact.get("period_kind"),
        "unit": fact.get("unit"),
        "currency": fact.get("currency"),
        "scale_factor": fact.get("scale_factor"),
        "statement_role": (
            (fact.get("hierarchy") or {}).get("statement_role")
        ),
        "presentation_path": (
            (fact.get("hierarchy") or {}).get("presentation_path")
        ),
        "context_ref": fact.get("context_ref")
        or (fact.get("context") or {}).get("context_ref"),
    }


def reconcile_ticker_statements(
    conn: sqlite3.Connection,
    ticker: str,
    *,
    evidence_cutoff: str | None = None,
) -> TickerStatementReconciliationRun:
    """Reconcile one as-of, manifest-bound, bounded statement view."""

    normalized_ticker = str(ticker).strip().upper()
    if not normalized_ticker:
        raise ValueError("ticker is required")
    all_facts = tuple(load_statement_facts(conn, normalized_ticker))
    all_manifests = load_statement_source_manifests(
        conn,
        normalized_ticker,
        evidence_cutoff=evidence_cutoff,
    )
    as_of_date = _resolve_evidence_cutoff(
        all_facts,
        all_manifests,
        evidence_cutoff,
    )
    if evidence_cutoff is None:
        all_manifests = tuple(
            manifest
            for manifest in all_manifests
            if str(
                (manifest.get("_store") or {}).get(
                    "evidence_cutoff"
                )
                or manifest.get("evidence_cutoff")
                or ""
            )
            <= as_of_date
        )
    manifests = _select_source_manifests(all_manifests)
    manifest_ids = tuple(
        sorted(
            _stored_manifest_id(manifest)
            for manifest in manifests
            if _stored_manifest_id(manifest)
        )
    )
    raw_facts = _facts_as_of(all_facts, as_of_date)
    raw_ledger_hash = canonical_semantic_hash(
        sorted(
            (
                _fact_identity_payload(fact)
                for fact in raw_facts
            ),
            key=lambda item: (
                item["source"],
                item["fact_id"],
                item["ingestion_fingerprint"],
            ),
        )
    )
    manifest_bound = _manifest_bound_facts(raw_facts, manifests)
    # Active PM-approved treatments are the only sanctioned way past a semantic source
    # gate (e.g. a filer presenting only a combined "depreciation, amortization, and
    # other" line). Deterministic code never picks the convention — it honours one the
    # PM already approved through the queue.
    approved_treatments = load_active_treatment_decisions(conn, normalized_ticker)
    selected_facts = _bounded_selected_view(
        manifest_bound,
        approved_treatments=approved_treatments,
    )
    selected_fact_ids = tuple(
        sorted(
            {
                str(fact.get("fact_id") or "")
                for fact in selected_facts
                if str(fact.get("fact_id") or "")
            }
        )
    )
    selected_view_hash = canonical_semantic_hash(
        {
            "contract_version": _RECONCILIATION_CONTRACT_VERSION,
            "ticker": normalized_ticker,
            "as_of_date": as_of_date,
            "manifest_ids": manifest_ids,
            "facts": [
                _fact_identity_payload(fact)
                for fact in selected_facts
            ],
        }
    )
    source_families = {
        (
            "ciq"
            if str(manifest.get("source") or "")
            .lower()
            .startswith("ciq")
            else "xbrl"
        )
        for manifest in manifests
    }
    expected_quantities = (
        _expected_source_quantities(
            selected_facts,
            approved_treatments=approved_treatments,
        )
        if source_families == {"xbrl", "ciq"}
        and all(_manifest_contract_complete(item) for item in manifests)
        else None
    )
    readiness = assess_persisted_statement_facts(
        selected_facts,
        expected_quantities=expected_quantities,
        approved_treatments=approved_treatments,
    )
    run_hash = persist_statement_reconciliation_run(
        conn,
        ticker=normalized_ticker,
        as_of_date=as_of_date,
        facts_fingerprint=raw_ledger_hash,
        selected_fact_ids=selected_fact_ids,
        readiness=asdict(readiness),
        manifest_ids=manifest_ids,
        selected_view_hash=selected_view_hash,
        raw_ledger_hash=raw_ledger_hash,
        status=readiness.status,
    )
    queue_ids = _persist_findings(
        conn,
        ticker=normalized_ticker,
        findings=readiness.findings,
        selected_view_hash=selected_view_hash,
    )
    return TickerStatementReconciliationRun(
        ticker=normalized_ticker,
        facts_fingerprint=raw_ledger_hash,
        readiness=readiness,
        persisted_queue_item_ids=queue_ids,
        run_hash=run_hash,
        as_of_date=as_of_date,
        raw_ledger_hash=raw_ledger_hash,
        selected_view_hash=selected_view_hash,
        manifest_ids=manifest_ids,
        selected_fact_ids=selected_fact_ids,
    )


__all__ = [
    "TickerStatementReconciliationRun",
    "assess_persisted_statement_facts",
    "reconcile_ticker_statements",
]
