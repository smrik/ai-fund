"""Assert that driver-family projections contain the facts each family needs.

This is a **presence** test, not a size test. The scoping code in
``driver_family_workflow._family_analysis_projection`` selects facts by
term-matching, so it can silently drop a needed fact if the term list is
incomplete. A family that reasons without its data produces a fast, cheap,
confidently-wrong answer — a worse failure than an oversized payload.

This test builds projections from a fixture snapshot and asserts that the
named accounting concepts actually appear in the output.

NOTE: This file must not overlap with ``tests/test_driver_family_workflow.py``
which is owned by task20.
"""

from __future__ import annotations

import json

from src.contracts.analysis_snapshot import AnalysisSnapshot
from src.contracts.assumption_registry import DriverFamily
from src.stage_04_pipeline.driver_family_workflow import (
    _family_analysis_projection,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

_SOURCE_URL = (
    "https://www.sec.gov/Archives/edgar/data/1/0000000000-index.html"
)


def _make_record(
    fact_id: str,
    statement: str,
    concept: str,
    label: str,
    value: float,
) -> dict[str, object]:
    return {
        "fact_id": fact_id,
        "statement": statement,
        "concept": concept,
        "label": label,
        "numeric_value": value,
        "accession": "0000000000",
        "source_locator": _SOURCE_URL,
    }


_RECORDS = [
    # ---- IncomeStatement ----
    _make_record("f:revenue", "IncomeStatement", "revenue", "Revenue", 200_000),
    _make_record("f:cost_of_revenue", "IncomeStatement", "cost_of_revenue", "Cost of revenue", 80_000),
    _make_record("f:gross_profit", "IncomeStatement", "gross_profit", "Gross profit", 120_000),
    _make_record("f:operating_income", "IncomeStatement", "operating_income", "Operating income", 70_000),
    _make_record("f:income_tax", "IncomeStatement", "income_tax_expense", "Income tax expense", 15_000),
    # ---- CashFlowStatement ----
    _make_record("f:capex", "CashFlowStatement", "capital_expenditure", "Capital expenditures", -25_000),
    _make_record("f:da", "CashFlowStatement", "depreciation_amortization", "Depreciation and amortization", 18_000),
    # ---- BalanceSheet ----
    _make_record("f:receivables", "BalanceSheet", "accounts_receivable", "Accounts receivable", 30_000),
    _make_record("f:inventory", "BalanceSheet", "inventory", "Inventory", 5_000),
    _make_record("f:payables", "BalanceSheet", "accounts_payable", "Accounts payable", 20_000),
    # ---- Facts that should NOT appear in reinvestment/revenue ----
    _make_record("f:goodwill", "BalanceSheet", "goodwill", "Goodwill", 50_000),
    _make_record("f:long_term_debt", "BalanceSheet", "long_term_debt", "Long-term debt", 40_000),
    _make_record("f:lease_liability", "BalanceSheet", "lease_liability", "Lease liability", 12_000),
]


def _evidence_for(fact_ids: list[str]) -> dict[str, object]:
    return {
        fid: {
            "fact_id": fid,
            "fact_name": fid.removeprefix("f:"),
            "concept": fid.removeprefix("f:"),
            "source_locator": _SOURCE_URL,
            "value": 1.0,
        }
        for fid in fact_ids
    }


def _snapshot_with_all_facts() -> AnalysisSnapshot:
    all_fact_ids = [r["fact_id"] for r in _RECORDS]
    return AnalysisSnapshot.model_validate(
        {
            "ticker": "PRESENCE",
            "as_of_date": "2026-08-03",
            "identity": {"cik": "0000000001", "currency": "USD"},
            "statements": {
                "annual_period_count": 5,
                "ltm_status": "compatible",
                "fact_ids": all_fact_ids,
                "consolidated_view": list(_RECORDS),
            },
            "statement_reconciliation": {
                "status": "reconciled",
                "selected_fact_ids": all_fact_ids,
            },
            "claim_ledger": {"status": "reconciled"},
            "market_inputs": {"price": 100.0},
            "wacc_inputs": {"wacc": 0.09},
            "comps_inputs": {"peer_count": 4},
            "approved_treatments": [],
            "evidence": _evidence_for(all_fact_ids),
            "upstream_context": {
                "business": {"summary": "Diversified tech company."},
                "industry": {"summary": "Enterprise software."},
            },
            "source_fingerprints": {"xbrl": "test-xbrl"},
            "component_versions": {"evidence_compiler": "v1"},
            "captured_at": "2026-08-03T10:00:00Z",
        }
    )


# ---------------------------------------------------------------------------
# Helpers to extract fact IDs from a projection
# ---------------------------------------------------------------------------


def _extract_statement_fact_ids(
    projection: dict[str, object],
) -> set[str]:
    """Resolve short handles back to full fact IDs from a projection."""

    statements = projection.get("statements", {})
    if not isinstance(statements, dict):
        return set()
    handle_map = statements.get("fact_handle_map", {})
    compact = statements.get("consolidated_view", {})
    if not isinstance(compact, dict):
        return set()
    columns = compact.get("columns", [])
    rows = compact.get("rows", [])
    if "fact_id" not in columns:
        return set()
    fact_id_idx = columns.index("fact_id")
    handles = {row[fact_id_idx] for row in rows if row[fact_id_idx]}
    # Resolve through handle map if present
    if handle_map:
        return {
            handle_map.get(h, h)
            for h in handles
        }
    return handles


def _extract_evidence_fact_ids(
    projection: dict[str, object],
) -> set[str]:
    """Resolve evidence anchor handles back to full IDs."""

    evidence = projection.get("evidence", {})
    if not isinstance(evidence, dict):
        return set()
    anchor_handle_map = evidence.get("anchor_handle_map", {})
    return set(anchor_handle_map.values())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_reinvestment_projection_contains_capex_da_receivables_inventory_payables() -> None:
    """The reinvestment_working_capital family must contain the facts it needs.

    If any of these are missing, the family will reason about DSO/DIO/DPO and
    capex-to-revenue without the underlying numbers. That produces a confident
    wrong answer, which is worse than a large payload.
    """

    snapshot = _snapshot_with_all_facts()
    projection = _family_analysis_projection(
        snapshot,
        DriverFamily.reinvestment_working_capital,
        max_chars=10_000_000,
    )

    statement_facts = _extract_statement_fact_ids(projection)

    required_facts = {
        "f:capex",
        "f:da",
        "f:receivables",
        "f:inventory",
        "f:payables",
    }
    missing = required_facts - statement_facts
    assert not missing, (
        f"reinvestment_working_capital projection is missing required facts: "
        f"{sorted(missing)}. Present facts: {sorted(statement_facts)}"
    )

    # Revenue and cost_of_revenue are also needed (denominators for ratios)
    assert "f:revenue" in statement_facts or "f:cost_of_revenue" in statement_facts, (
        "reinvestment_working_capital needs at least revenue or cost_of_revenue "
        "as ratio denominators"
    )


def test_reinvestment_projection_excludes_irrelevant_balance_sheet_items() -> None:
    """Lease, goodwill, and debt facts should not appear in reinvestment."""

    snapshot = _snapshot_with_all_facts()
    projection = _family_analysis_projection(
        snapshot,
        DriverFamily.reinvestment_working_capital,
        max_chars=10_000_000,
    )

    statement_facts = _extract_statement_fact_ids(projection)
    evidence_facts = _extract_evidence_fact_ids(projection)

    # These facts are owned by other families or explicitly irrelevant
    excluded = {"f:goodwill", "f:long_term_debt", "f:lease_liability"}
    leaked_statements = excluded & statement_facts
    leaked_evidence = excluded & evidence_facts
    assert not leaked_statements, (
        f"reinvestment_working_capital statements contain irrelevant facts: "
        f"{sorted(leaked_statements)}"
    )
    assert not leaked_evidence, (
        f"reinvestment_working_capital evidence contains irrelevant facts: "
        f"{sorted(leaked_evidence)}"
    )


def test_revenue_projection_contains_revenue_facts() -> None:
    """The revenue family must contain revenue line items."""

    snapshot = _snapshot_with_all_facts()
    projection = _family_analysis_projection(
        snapshot,
        DriverFamily.revenue,
        max_chars=10_000_000,
    )

    statement_facts = _extract_statement_fact_ids(projection)
    assert "f:revenue" in statement_facts, (
        f"revenue projection missing f:revenue. Present: {sorted(statement_facts)}"
    )


def test_revenue_projection_excludes_balance_sheet_and_cash_flow_facts() -> None:
    """Revenue family only needs IncomeStatement — no BS or CF facts."""

    snapshot = _snapshot_with_all_facts()
    projection = _family_analysis_projection(
        snapshot,
        DriverFamily.revenue,
        max_chars=10_000_000,
    )

    statement_facts = _extract_statement_fact_ids(projection)
    # These are CashFlowStatement or BalanceSheet facts
    non_income_facts = {
        "f:capex", "f:da",
        "f:receivables", "f:inventory", "f:payables",
        "f:goodwill", "f:long_term_debt", "f:lease_liability",
    }
    leaked = non_income_facts & statement_facts
    assert not leaked, (
        f"revenue projection contains non-IncomeStatement facts: {sorted(leaked)}"
    )


def test_profitability_projection_contains_margin_and_tax_facts() -> None:
    """Profitability family needs revenue, COGS, operating income, and tax."""

    snapshot = _snapshot_with_all_facts()
    projection = _family_analysis_projection(
        snapshot,
        DriverFamily.profitability_tax,
        max_chars=10_000_000,
    )

    statement_facts = _extract_statement_fact_ids(projection)
    required = {
        "f:revenue",
        "f:cost_of_revenue",
        "f:operating_income",
        "f:income_tax",
    }
    missing = required - statement_facts
    assert not missing, (
        f"profitability_tax projection missing required facts: "
        f"{sorted(missing)}. Present: {sorted(statement_facts)}"
    )


def test_terminal_capital_comps_gets_no_statement_facts() -> None:
    """terminal_capital_comps has no statement types — should get zero rows."""

    snapshot = _snapshot_with_all_facts()
    projection = _family_analysis_projection(
        snapshot,
        DriverFamily.terminal_capital_comps,
        max_chars=10_000_000,
    )

    statements = projection.get("statements")
    # terminal_capital_comps should not include a statements component at all
    # (it's not in its family_components list)
    if statements is not None:
        # If it somehow got statements, they should be empty
        if isinstance(statements, dict):
            compact = statements.get("consolidated_view", {})
            if isinstance(compact, dict):
                rows = compact.get("rows", [])
                assert len(rows) == 0, (
                    f"terminal_capital_comps should have zero statement rows, "
                    f"got {len(rows)}"
                )


def test_all_families_produce_valid_projections() -> None:
    """Smoke test: every family should build without error."""

    snapshot = _snapshot_with_all_facts()
    for family in DriverFamily:
        projection = _family_analysis_projection(
            snapshot, family, max_chars=10_000_000
        )
        text = json.dumps(projection)
        assert len(text) > 0, f"{family.value} produced empty projection"
        assert projection.get("ticker") == "PRESENCE"
        assert projection.get("family") == family.value
