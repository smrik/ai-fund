from __future__ import annotations

import hashlib
import json
import sqlite3

from db.loader import insert_statement_facts
from db.schema import create_tables
from src.stage_00_data.source_reconciliation import canonical_statement_key
from src.stage_04_pipeline.statement_reconciliation_service import (
    _apply_manifest_calculation_edges,
    _calculation_rollup_checks,
    reconcile_ticker_statements,
)
from src.stage_04_pipeline.statement_reconciliation_store import (
    persist_statement_source_manifest,
)


def _fact(
    *,
    source: str,
    concept: str,
    value: float,
    period_end: str,
    statement: str,
    period_kind: str = "annual",
    period_start: str | None = None,
    scale_factor: float = 1.0,
    suffix: str = "",
    is_derived: bool = False,
    presentation_complete: bool = True,
    source_run_id: int | None = None,
    accession: str | None = "000-test-filing",
    filing_date: str = "2026-02-01",
) -> dict[str, object]:
    identity = (
        f"{source}:{concept}:{period_start or 'instant'}:{period_end}:{suffix}"
    )
    return {
        "fact_id": identity,
        "ingestion_fingerprint": f"fingerprint:{identity}",
        "ticker": "TEST",
        "source": source,
        "source_run_id": source_run_id,
        "statement": statement,
        "concept": concept,
        "label": concept,
        "value": value,
        "numeric_value": value,
        "unit": "USD",
        "currency": "USD",
        "scale_factor": scale_factor,
        "period_kind": period_kind,
        "period_type": "duration" if period_start else "instant",
        "period_start": period_start,
        "period_end": period_end,
        "filing_date": filing_date,
        "accession": accession if source.startswith("sec_xbrl") else None,
        "context_ref": identity,
        "dimensions": {},
        "hierarchy": {
            "presentation_complete": presentation_complete,
            "statement_role": f"role:{statement}",
            "presentation_path": f"role:{statement}/{concept}",
            "coverage_entry_key": identity,
        },
        "source_locator": identity,
        "is_derived": is_derived,
    }


def _ready_facts() -> list[dict[str, object]]:
    facts: list[dict[str, object]] = [
        _fact(
            source="sec_xbrl_filing_presentation_v1",
            concept="CashAndCashEquivalentsAtCarryingValue",
            value=0.0,
            statement="BalanceSheet",
            period_end="2022-12-31",
            suffix="cash-opening-2023",
        )
    ]
    for year in (2023, 2024, 2025):
        end = f"{year}-12-31"
        start = f"{year}-01-01"
        facts.append(
            _fact(
                source="sec_xbrl_filing_presentation_v1",
                concept="Revenue",
                value=100_000_000.0,
                statement="IncomeStatement",
                period_start=start,
                period_end=end,
                suffix=str(year),
            )
        )
        facts.extend(
            [
                _fact(
                    source="sec_xbrl_filing_presentation_v1",
                    concept="Assets",
                    value=200_000_000.0,
                    statement="BalanceSheet",
                    period_end=end,
                    suffix=str(year),
                ),
                _fact(
                    source="sec_xbrl_filing_presentation_v1",
                    concept="Liabilities",
                    value=120_000_000.0,
                    statement="BalanceSheet",
                    period_end=end,
                    suffix=str(year),
                ),
                _fact(
                    source="sec_xbrl_filing_presentation_v1",
                    concept="StockholdersEquity",
                    value=80_000_000.0,
                    statement="BalanceSheet",
                    period_end=end,
                    suffix=str(year),
                ),
                _fact(
                    source="sec_xbrl_filing_presentation_v1",
                    concept="OperatingIncome",
                    value=25_000_000.0,
                    statement="IncomeStatement",
                    period_start=start,
                    period_end=end,
                    suffix=f"operating-income-{year}",
                ),
                _fact(
                    source="sec_xbrl_filing_presentation_v1",
                    concept="NetIncome",
                    value=20_000_000.0,
                    statement="IncomeStatement",
                    period_start=start,
                    period_end=end,
                    suffix=f"net-income-{year}",
                ),
                _fact(
                    source="sec_xbrl_filing_presentation_v1",
                    concept="NetCashProvidedByUsedInOperatingActivities",
                    value=30_000_000.0,
                    statement="CashFlowStatement",
                    period_start=start,
                    period_end=end,
                    suffix=f"cfo-{year}",
                ),
                _fact(
                    source="sec_xbrl_filing_presentation_v1",
                    concept="CapitalExpenditure",
                    value=8_000_000.0,
                    statement="CashFlowStatement",
                    period_start=start,
                    period_end=end,
                    suffix=f"capex-{year}",
                ),
                _fact(
                    source="sec_xbrl_filing_presentation_v1",
                    concept="DepreciationAndAmortization",
                    value=6_000_000.0,
                    statement="CashFlowStatement",
                    period_start=start,
                    period_end=end,
                    suffix=f"da-{year}",
                ),
                _fact(
                    source="sec_xbrl_filing_presentation_v1",
                    concept="CashAndCashEquivalentsPeriodIncreaseDecrease",
                    value=10_000_000.0,
                    statement="CashFlowStatement",
                    period_start=start,
                    period_end=end,
                    suffix=str(year),
                ),
                _fact(
                    source="sec_xbrl_filing_presentation_v1",
                    concept="CashAndCashEquivalentsAtCarryingValue",
                    value=float((year - 2022) * 10_000_000),
                    statement="BalanceSheet",
                    period_end=end,
                    suffix=f"cash-{year}",
                ),
            ]
        )
    facts.append(
        _fact(
            source="sec_xbrl_derived_ltm_v1",
            concept="Revenue",
            value=110_000_000.0,
            statement="IncomeStatement",
            period_kind="ltm",
            period_start="2025-04-01",
            period_end="2026-03-31",
            suffix="ltm",
            is_derived=True,
        )
    )
    for concept, statement, value in (
        ("OperatingIncome", "IncomeStatement", 27_000_000.0),
        ("NetIncome", "IncomeStatement", 22_000_000.0),
        (
            "NetCashProvidedByUsedInOperatingActivities",
            "CashFlowStatement",
            33_000_000.0,
        ),
        ("CapitalExpenditure", "CashFlowStatement", 9_000_000.0),
        (
            "DepreciationAndAmortization",
            "CashFlowStatement",
            7_000_000.0,
        ),
    ):
        facts.append(
            _fact(
                source="sec_xbrl_derived_ltm_v1",
                concept=concept,
                value=value,
                statement=statement,
                period_kind="ltm",
                period_start="2025-04-01",
                period_end="2026-03-31",
                suffix=f"ltm-{concept}",
                is_derived=True,
            )
        )
    xbrl_facts = tuple(
        fact
        for fact in facts
        if str(fact["source"]).startswith("sec_xbrl")
    )
    for fact in xbrl_facts:
        source_value = float(fact["numeric_value"])
        if canonical_statement_key(str(fact["concept"])) == "capex":
            source_value = -source_value
        facts.append(
            _fact(
                source="ciq_workbook_v1",
                concept=str(fact["concept"]),
                value=source_value / 1_000_000.0,
                scale_factor=1_000_000.0,
                statement=str(fact["statement"]),
                period_kind=str(fact["period_kind"]),
                period_start=(
                    str(fact["period_start"])
                    if fact.get("period_start")
                    else None
                ),
                period_end=str(fact["period_end"]),
                suffix=f"mirror-{fact['fact_id']}",
                source_run_id=17,
                accession=None,
                filing_date=str(fact["filing_date"]),
            )
        )
    return facts


def _additional_annual_facts(
    year: int,
    *,
    ending_cash: float,
) -> list[dict[str, object]]:
    start = f"{year}-01-01"
    end = f"{year}-12-31"
    rows = (
        ("Revenue", "IncomeStatement", 100_000_000.0, start),
        ("OperatingIncome", "IncomeStatement", 25_000_000.0, start),
        ("NetIncome", "IncomeStatement", 20_000_000.0, start),
        ("Assets", "BalanceSheet", 200_000_000.0, None),
        ("Liabilities", "BalanceSheet", 120_000_000.0, None),
        ("StockholdersEquity", "BalanceSheet", 80_000_000.0, None),
        (
            "CashAndCashEquivalentsAtCarryingValue",
            "BalanceSheet",
            ending_cash,
            None,
        ),
        (
            "NetCashProvidedByUsedInOperatingActivities",
            "CashFlowStatement",
            30_000_000.0,
            start,
        ),
        ("CapitalExpenditure", "CashFlowStatement", 8_000_000.0, start),
        (
            "DepreciationAndAmortization",
            "CashFlowStatement",
            6_000_000.0,
            start,
        ),
        (
            "CashAndCashEquivalentsPeriodIncreaseDecrease",
            "CashFlowStatement",
            10_000_000.0,
            start,
        ),
    )
    facts: list[dict[str, object]] = []
    for concept, statement, value, period_start in rows:
        xbrl = _fact(
            source="sec_xbrl_filing_presentation_v1",
            concept=concept,
            value=value,
            statement=statement,
            period_start=period_start,
            period_end=end,
            suffix=f"history-{year}-{concept}",
        )
        facts.append(xbrl)
        facts.append(
            _fact(
                source="ciq_workbook_v1",
                concept=concept,
                value=(
                    -value
                    if canonical_statement_key(concept) == "capex"
                    else value
                )
                / 1_000_000.0,
                scale_factor=1_000_000.0,
                statement=statement,
                period_start=period_start,
                period_end=end,
                suffix=f"history-{year}-{concept}",
                source_run_id=17,
                accession=None,
            )
        )
    return facts


def _ciq_mirrors_for_run(
    facts: list[dict[str, object]],
    *,
    source_run_id: int,
    zero_ltm_da: bool = False,
) -> list[dict[str, object]]:
    mirrors: list[dict[str, object]] = []
    for fact in facts:
        if not str(fact["source"]).startswith("sec_xbrl"):
            continue
        normalized_value = float(fact["numeric_value"])
        if canonical_statement_key(str(fact["concept"])) == "capex":
            normalized_value = -normalized_value
        if (
            zero_ltm_da
            and fact["concept"] == "DepreciationAndAmortization"
            and fact["period_kind"] == "ltm"
        ):
            normalized_value = 0.0
        mirrors.append(
            _fact(
                source="ciq_workbook_v1",
                concept=str(fact["concept"]),
                value=normalized_value / 1_000_000.0,
                scale_factor=1_000_000.0,
                statement=str(fact["statement"]),
                period_kind=str(fact["period_kind"]),
                period_start=(
                    str(fact["period_start"])
                    if fact.get("period_start")
                    else None
                ),
                period_end=str(fact["period_end"]),
                suffix=f"run-{source_run_id}-{fact['fact_id']}",
                source_run_id=source_run_id,
                accession=None,
                filing_date=str(fact["filing_date"]),
            )
        )
    return mirrors


def _manifest_id(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _persist_complete_manifests(
    conn: sqlite3.Connection,
    facts: list[dict[str, object]],
    *,
    evidence_cutoff: str = "2026-04-30",
    include_calculation_inventory: bool = True,
    ciq_source_run_id: int = 17,
) -> tuple[str, str]:
    manifest_ids: list[str] = []
    for source in (
        "sec_xbrl_filing_presentation_v1",
        "ciq_workbook_v1",
    ):
        source_facts = [
            fact
            for fact in facts
            if fact["source"] == source
            and (
                not source.startswith("ciq")
                or fact.get("source_run_id") == ciq_source_run_id
            )
        ]
        entries: dict[str, dict[str, object]] = {}
        for fact in source_facts:
            hierarchy = dict(fact["hierarchy"])
            entry_key = str(hierarchy["coverage_entry_key"])
            canonical_role = canonical_statement_key(str(fact["concept"]))
            entry: dict[str, object] = {
                "statement": fact["statement"],
                "statement_role": hierarchy["statement_role"],
                "canonical_role": canonical_role,
                "canonical_roles": [canonical_role],
                "period_start": fact.get("period_start"),
                "period_end": fact["period_end"],
                "period_kind": fact["period_kind"],
                "period_type": fact["period_type"],
                "unit": fact["unit"],
                "currency": fact["currency"],
                "completion_status": "completed",
                "consolidated_fact_ids": [fact["fact_id"]],
                "dimensioned_fact_ids": [],
            }
            if source.startswith("sec_xbrl"):
                entry["presented_fact_ids"] = [fact["fact_id"]]
            entries[entry_key] = entry

        payload: dict[str, object] = {
            "contract_version": (
                "filing_statement_coverage.v1"
                if source.startswith("sec_xbrl")
                else "ciq_statement_coverage_v1"
            ),
            "ticker": "TEST",
            "source": source,
            "source_run_id": (
                ciq_source_run_id
                if source.startswith("ciq")
                else None
            ),
            "accession": (
                "000-test-filing"
                if source.startswith("sec_xbrl")
                else None
            ),
            "status": "completed",
            "evidence_cutoff": evidence_cutoff,
            "as_of_date": evidence_cutoff,
            "coverage": {
                "entries": entries,
                "required_statement_roles": [
                    "role:BalanceSheet",
                    "role:CashFlowStatement",
                    "role:IncomeStatement",
                ],
                "covered_statement_roles": sorted(
                    {
                        str(entry["statement_role"])
                        for entry in entries.values()
                    }
                ),
            },
            "calculation_edges": (
                [
                    {
                        "statement_role": (
                            dict(fact["hierarchy"])[
                                "statement_role"
                            ]
                        ),
                        "parent_concept": (
                            dict(fact["hierarchy"])[
                                "calculation_parent"
                            ]
                        ),
                        "child_concept": fact["concept"],
                        "weight": (
                            dict(fact["hierarchy"])[
                                "calculation_weight"
                            ]
                        ),
                    }
                    for fact in source_facts
                    if dict(fact["hierarchy"]).get(
                        "calculation_parent"
                    )
                    and dict(fact["hierarchy"]).get(
                        "calculation_weight"
                    )
                    is not None
                ]
                if source.startswith("sec_xbrl")
                else []
            ),
            "errors": [],
        }
        if (
            source.startswith("sec_xbrl")
            and not include_calculation_inventory
        ):
            payload.pop("calculation_edges")
        payload["manifest_id"] = _manifest_id(payload)
        manifest_ids.append(
            persist_statement_source_manifest(
                conn,
                payload,
                source_run_id=(
                    ciq_source_run_id
                    if source.startswith("ciq")
                    else None
                ),
                accession=(
                    "000-test-filing"
                    if source.startswith("sec_xbrl")
                    else None
                ),
            )
        )
    return manifest_ids[0], manifest_ids[1]


def test_service_builds_decision_grade_statement_readiness() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_tables(conn)
    facts = _ready_facts()
    insert_statement_facts(conn, facts)
    manifest_ids = _persist_complete_manifests(conn, facts)

    result = reconcile_ticker_statements(
        conn,
        "TEST",
        evidence_cutoff="2026-04-30",
    )

    assert result.readiness.status == "decision_grade"
    assert result.readiness.annual_period_count == 3
    assert result.readiness.ltm_status == "constructed"
    assert {check.check_name for check in result.readiness.checks} == {
        "balance_sheet_identity",
        "cash_flow_to_cash_bridge",
    }
    assert result.persisted_queue_item_ids == ()
    assert set(result.manifest_ids) == set(manifest_ids)
    assert result.selected_fact_ids
    assert result.run_hash
    assert conn.execute(
        """
        SELECT COUNT(*)
        FROM valuation_statement_reconciliation_runs
        WHERE run_hash = ?
        """,
        (result.run_hash,),
    ).fetchone()[0] == 1


def test_service_persists_material_source_disagreement_once() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_tables(conn)
    facts = _ready_facts()
    for fact in facts:
        if (
            fact["source"] == "ciq_workbook_v1"
            and fact["concept"] == "DepreciationAndAmortization"
            and fact["period_kind"] == "ltm"
        ):
            fact["value"] = 0.0
            fact["numeric_value"] = 0.0
    insert_statement_facts(conn, facts)
    _persist_complete_manifests(conn, facts)

    first = reconcile_ticker_statements(
        conn,
        "TEST",
        evidence_cutoff="2026-04-30",
    )
    second = reconcile_ticker_statements(
        conn,
        "TEST",
        evidence_cutoff="2026-04-30",
    )

    assert first.readiness.status == "blocked"
    assert len(first.persisted_queue_item_ids) == 1
    assert second.persisted_queue_item_ids == first.persisted_queue_item_ids
    assert conn.execute(
        "SELECT COUNT(*) FROM pm_decision_queue_items"
    ).fetchone()[0] == 1
    assert conn.execute(
        """
        SELECT COUNT(*)
        FROM pm_decision_queue_items
        WHERE dedupe_key IS NOT NULL
        """
    ).fetchone()[0] == 1


def test_corrected_view_supersedes_old_finding_and_recurrence_is_new() -> None:
    initial = _ready_facts()
    for fact in initial:
        if (
            fact["source"] == "ciq_workbook_v1"
            and fact["concept"] == "DepreciationAndAmortization"
            and fact["period_kind"] == "ltm"
        ):
            fact["value"] = 0.0
            fact["numeric_value"] = 0.0
    conn = _connection_with_facts(initial)
    first = reconcile_ticker_statements(
        conn,
        "TEST",
        evidence_cutoff="2026-04-30",
    )
    first_id = first.persisted_queue_item_ids[0]

    xbrl = [
        fact
        for fact in _ready_facts()
        if str(fact["source"]).startswith("sec_xbrl")
    ]
    corrected = _ciq_mirrors_for_run(xbrl, source_run_id=18)
    insert_statement_facts(conn, corrected)
    _persist_complete_manifests(
        conn,
        [*xbrl, *corrected],
        evidence_cutoff="2026-05-31",
        ciq_source_run_id=18,
    )
    clean = reconcile_ticker_statements(
        conn,
        "TEST",
        evidence_cutoff="2026-05-31",
    )

    assert clean.readiness.status == "decision_grade"
    assert clean.persisted_queue_item_ids == ()
    assert conn.execute(
        "SELECT status FROM pm_decision_queue_items WHERE id = ?",
        (first_id,),
    ).fetchone()[0] == "superseded"

    recurring = _ciq_mirrors_for_run(
        xbrl,
        source_run_id=19,
        zero_ltm_da=True,
    )
    insert_statement_facts(conn, recurring)
    _persist_complete_manifests(
        conn,
        [*xbrl, *recurring],
        evidence_cutoff="2026-06-30",
        ciq_source_run_id=19,
    )
    third = reconcile_ticker_statements(
        conn,
        "TEST",
        evidence_cutoff="2026-06-30",
    )

    assert third.readiness.status == "blocked"
    assert len(third.persisted_queue_item_ids) == 1
    assert third.persisted_queue_item_ids[0] != first_id
    assert conn.execute(
        """
        SELECT COUNT(*)
        FROM pm_decision_queue_items
        WHERE profile_name = 'statement_reconciliation'
        """,
    ).fetchone()[0] == 2


def test_sparse_rows_and_company_facts_cannot_attest_complete_statements() -> None:
    sparse = [
        _fact(
            source="sec_xbrl_companyfacts_v3",
            concept="Revenue",
            value=100_000_000.0,
            statement="IncomeStatement",
            period_start="2025-01-01",
            period_end="2025-12-31",
        ),
        _fact(
            source="ciq_workbook_v1",
            concept="Revenue",
            value=100.0,
            scale_factor=1_000_000.0,
            statement="IncomeStatement",
            period_start="2025-01-01",
            period_end="2025-12-31",
        ),
    ]

    result = reconcile_ticker_statements(
        _connection_with_facts(sparse, with_manifests=False),
        "TEST",
        evidence_cutoff="2026-04-30",
    )

    assert result.readiness.status == "provisional"
    assert result.readiness.annual_period_count == 0
    assert "insufficient_annual_history" in result.readiness.reason_codes
    assert "complete_presentation_history_missing" in (
        result.readiness.reason_codes
    )


def test_service_executes_available_xbrl_calculation_rollups() -> None:
    facts = _ready_facts()
    for fact in facts:
        if (
            fact["period_end"] == "2025-12-31"
            and fact["concept"] == "DepreciationAndAmortization"
        ):
            fact["hierarchy"] = {
                **dict(fact["hierarchy"]),
                "calculation_parent": (
                    "NetCashProvidedByUsedInOperatingActivities"
                ),
                "calculation_weight": 1.0,
            }

    result = reconcile_ticker_statements(
        _connection_with_facts(facts),
        "TEST",
        evidence_cutoff="2026-04-30",
    )

    rollups = [
        check
        for check in result.readiness.checks
        if check.check_name == "source_calculation_rollup"
    ]
    assert len(rollups) == 3
    assert all(check.status == "fail" for check in rollups)
    assert "source_calculation_rollup_failed" in (
        result.readiness.reason_codes
    )
    assert result.readiness.status == "blocked"


def test_combined_da_and_other_line_sources_da_from_ciq() -> None:
    """PM decision 2026-07-31 (supersedes the earlier fail-closed-only behaviour).

    Where XBRL presents only a combined "depreciation, amortization, and other" line,
    `da` is sourced from CIQ and the difference is logged rather than blocking. Without
    a CIQ D&A the gate still fails closed — see
    `test_combined_da_still_blocks_when_ciq_has_no_da_either`.
    """

    facts = _ready_facts()
    for fact in facts:
        if (
            str(fact["source"]).startswith("sec_xbrl")
            and fact["concept"] == "DepreciationAndAmortization"
        ):
            fact["concept"] = "DepreciationAmortizationAndOther"
            fact["label"] = "Depreciation, amortization, and other"

    result = reconcile_ticker_statements(
        _connection_with_facts(facts),
        "TEST",
        evidence_cutoff="2026-04-30",
    )

    assert "pure_da_evidence_missing" not in result.readiness.reason_codes


def test_combined_da_and_other_line_blocks_when_no_ciq_da_exists() -> None:
    """The fail-closed path survives: no pure D&A anywhere means no valuation."""

    from src.stage_00_data.source_reconciliation import canonical_statement_key

    facts = [
        fact
        for fact in _ready_facts()
        if not (
            str(fact["source"]).startswith("ciq")
            and canonical_statement_key(
                str(fact.get("concept") or ""),
                str(fact.get("label") or ""),
            )
            == "da"
        )
    ]
    for fact in facts:
        if (
            str(fact["source"]).startswith("sec_xbrl")
            and fact["concept"] == "DepreciationAndAmortization"
        ):
            fact["concept"] = "DepreciationAmortizationAndOther"
            fact["label"] = "Depreciation, amortization, and other"

    result = reconcile_ticker_statements(
        _connection_with_facts(facts),
        "TEST",
        evidence_cutoff="2026-04-30",
    )

    assert result.readiness.status == "blocked"
    assert "pure_da_evidence_missing" in result.readiness.reason_codes


def test_calculation_edges_are_bound_to_the_fact_filing_vintage() -> None:
    facts = [
        {
            "source": "sec_xbrl_filing_presentation_v1",
            "concept": "Child",
            "accession": accession,
            "hierarchy": {"statement_role": "role:CashFlowStatement"},
        }
        for accession in ("filing-2024", "filing-2025")
    ]
    manifests = [
        {
            "_store": {
                "manifest_id": f"manifest-{year}",
                "accession": f"filing-{year}",
            },
            "calculation_edges": [
                {
                    "statement_role": "role:CashFlowStatement",
                    "parent_concept": f"Parent{year}",
                    "child_concept": "Child",
                    "weight": 1.0,
                }
            ],
        }
        for year in ("2024", "2025")
    ]

    selected = _apply_manifest_calculation_edges(facts, manifests)

    assert [
        fact["hierarchy"]["calculation_parent"] for fact in selected
    ] == ["Parent2024", "Parent2025"]
    assert [
        fact["hierarchy"]["calculation_manifest_id"] for fact in selected
    ] == ["manifest-2024", "manifest-2025"]


def test_calculation_rollups_do_not_mix_comparative_filing_vintages() -> None:
    facts: list[dict[str, object]] = []
    for year in ("2024", "2025"):
        accession = f"filing-{year}"
        role = f"role:{year}:IncomeStatement"
        facts.extend(
            [
                _fact(
                    source="sec_xbrl_filing_presentation_v1",
                    concept="Parent",
                    value=10.0,
                    period_start="2023-01-01",
                    period_end="2023-12-31",
                    statement="IncomeStatement",
                    accession=accession,
                    suffix=f"parent-{year}",
                ),
                _fact(
                    source="sec_xbrl_filing_presentation_v1",
                    concept="Child",
                    value=10.0,
                    period_start="2023-01-01",
                    period_end="2023-12-31",
                    statement="IncomeStatement",
                    accession=accession,
                    suffix=f"child-{year}",
                ),
            ]
        )
        facts[-2]["hierarchy"] = {
            **dict(facts[-2]["hierarchy"]),
            "statement_role": role,
        }
        facts[-1]["hierarchy"] = {
            **dict(facts[-1]["hierarchy"]),
            "statement_role": role,
            "calculation_parent": "Parent",
            "calculation_weight": 1.0,
            "calculation_manifest_id": f"manifest-{year}",
        }

    checks = _calculation_rollup_checks(
        facts=facts,
        eligible_periods={"2023-12-31"},
    )

    assert len(checks) == 2
    assert all(check.status == "pass" for check in checks)


def test_attested_calculation_edge_with_missing_parent_is_not_silent() -> None:
    facts = _ready_facts()
    for fact in facts:
        if (
            fact["period_end"] == "2025-12-31"
            and fact["concept"] == "NetIncome"
        ):
            fact["hierarchy"] = {
                **dict(fact["hierarchy"]),
                "calculation_parent": "MissingGrossProfitParent",
                "calculation_weight": 1.0,
            }

    result = reconcile_ticker_statements(
        _connection_with_facts(facts),
        "TEST",
        evidence_cutoff="2026-04-30",
    )

    rollups = [
        check
        for check in result.readiness.checks
        if check.check_name == "source_calculation_rollup"
    ]
    assert len(rollups) == 3
    assert all(check.status == "not_ready" for check in rollups)
    assert "source_calculation_rollup_not_ready" in (
        result.readiness.reason_codes
    )
    assert len(result.persisted_queue_item_ids) == 3
    assert result.readiness.status == "provisional"


def test_completed_source_manifests_are_required_for_decision_grade() -> None:
    result = reconcile_ticker_statements(
        _connection_with_facts(_ready_facts(), with_manifests=False),
        "TEST",
        evidence_cutoff="2026-04-30",
    )

    assert result.readiness.status == "provisional"
    assert result.readiness.decision_grade is False
    assert result.manifest_ids == ()
    assert "source_coverage_not_attested" in result.readiness.reason_codes


def test_manifest_inventory_prevents_single_revenue_false_pass() -> None:
    facts = [
        fact
        for fact in _ready_facts()
        if fact["source"] != "ciq_workbook_v1"
        or fact["concept"] == "Revenue"
    ]

    result = reconcile_ticker_statements(
        _connection_with_facts(facts),
        "TEST",
        evidence_cutoff="2026-04-30",
    )

    assert result.readiness.status == "blocked"
    assert result.readiness.source_reconciliation.missing_expected_count > 0
    assert "source_reconciliation_failed" in result.readiness.reason_codes


def test_completed_manifest_without_calculation_inventory_is_not_attested() -> None:
    conn = _connection_with_facts(
        _ready_facts(),
        with_manifests=False,
    )
    _persist_complete_manifests(
        conn,
        _ready_facts(),
        include_calculation_inventory=False,
    )

    result = reconcile_ticker_statements(
        conn,
        "TEST",
        evidence_cutoff="2026-04-30",
    )

    assert result.readiness.status == "provisional"
    assert "source_coverage_not_attested" in result.readiness.reason_codes


def test_selected_history_is_bounded_to_latest_five_annual_periods() -> None:
    facts = [
        *_ready_facts(),
        *_additional_annual_facts(2020, ending_cash=-20_000_000.0),
        *_additional_annual_facts(2021, ending_cash=-10_000_000.0),
        *_additional_annual_facts(2022, ending_cash=0.0),
    ]

    result = reconcile_ticker_statements(
        _connection_with_facts(facts),
        "TEST",
        evidence_cutoff="2026-04-30",
    )

    selected = set(result.selected_fact_ids)
    selected_revenue_periods = {
        str(fact["period_end"])
        for fact in facts
        if fact["fact_id"] in selected
        and fact["source"] == "sec_xbrl_filing_presentation_v1"
        and fact["concept"] == "Revenue"
    }
    assert result.readiness.annual_period_count == 5
    assert selected_revenue_periods == {
        "2021-12-31",
        "2022-12-31",
        "2023-12-31",
        "2024-12-31",
        "2025-12-31",
    }
    assert result.readiness.status == "decision_grade"


def test_evidence_cutoff_excludes_later_filing_and_manifest() -> None:
    conn = _connection_with_facts(_ready_facts())
    baseline = reconcile_ticker_statements(
        conn,
        "TEST",
        evidence_cutoff="2026-04-30",
    )
    post_cutoff = _fact(
        source="sec_xbrl_filing_presentation_v1",
        concept="Revenue",
        value=999_000_000.0,
        statement="IncomeStatement",
        period_start="2025-01-01",
        period_end="2025-12-31",
        suffix="post-cutoff-amendment",
        accession="000-test-amendment",
        filing_date="2026-05-15",
    )
    insert_statement_facts(conn, [post_cutoff])
    _persist_complete_manifests(
        conn,
        [*_ready_facts(), post_cutoff],
        evidence_cutoff="2026-06-30",
    )

    replay = reconcile_ticker_statements(
        conn,
        "TEST",
        evidence_cutoff="2026-04-30",
    )

    assert post_cutoff["fact_id"] not in replay.selected_fact_ids
    assert replay.raw_ledger_hash == baseline.raw_ledger_hash
    assert replay.run_hash == baseline.run_hash


def test_ltm_roles_from_different_windows_are_not_unioned() -> None:
    facts = _ready_facts()
    for fact in facts:
        if (
            fact["concept"] == "NetIncome"
            and fact["period_kind"] == "ltm"
        ):
            fact["period_start"] = "2025-01-01"
            fact["period_end"] = "2025-12-31"

    result = reconcile_ticker_statements(
        _connection_with_facts(facts),
        "TEST",
        evidence_cutoff="2026-04-30",
    )

    assert result.readiness.ltm_status == "unavailable"
    assert result.readiness.status == "blocked"
    assert "ltm_not_ready" in result.readiness.reason_codes


def _connection_with_facts(
    facts: list[dict[str, object]],
    *,
    with_manifests: bool = True,
) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_tables(conn)
    insert_statement_facts(conn, facts)
    if with_manifests:
        _persist_complete_manifests(conn, facts)
    return conn


def test_newest_manifest_wins_per_filing_vintage() -> None:
    """Re-ingestion must supersede a stale manifest for the same accession.

    `load_statement_source_manifests` orders by `evidence_cutoff DESC` first, but
    `evidence_cutoff` is a filter bound, not a recency signal: a manifest written by
    an older run can carry a later run-date cutoff than a freshly written manifest
    carrying its filing-date cutoff. Selection must therefore break ties on
    `created_at`, or re-ingesting can never replace a stale manifest.
    """

    from src.stage_04_pipeline.statement_reconciliation_service import (
        _select_source_manifests,
    )

    def _manifest(*, manifest_id: str, created_at: str, cutoff: str) -> dict:
        return {
            "manifest_id": manifest_id,
            "source": "sec_xbrl_filing_presentation_v1",
            "status": "completed",
            "coverage": {
                "entries": [
                    {
                        "statement": "BalanceSheet",
                        "statement_role": "http://example.test/role/BalanceSheet",
                        "period_end": "2025-06-30",
                        "period_kind": "annual",
                        "units": ["USD"],
                        "currencies": ["USD"],
                        "presented_fact_ids": ["fact-1"],
                    }
                ]
            },
            "calculation_edges": [
                {
                    "statement_role": "http://example.test/role/BalanceSheet",
                    "parent_concept": "us-gaap_Assets",
                    "child_concept": "us-gaap_AssetsCurrent",
                    "weight": 1.0,
                }
            ],
            "_store": {
                "manifest_id": manifest_id,
                "accession": "0000950170-25-100235",
                "created_at": created_at,
                "evidence_cutoff": cutoff,
            },
        }

    stale = _manifest(
        manifest_id="sha256:stale",
        created_at="2026-07-26T20:18:13",
        cutoff="2026-07-26",
    )
    fresh = _manifest(
        manifest_id="sha256:fresh",
        created_at="2026-07-30T22:21:07",
        cutoff="2025-07-30",
    )

    # Loader order: stale first, because its evidence_cutoff is later.
    selected = _select_source_manifests((stale, fresh))

    assert len(selected) == 1
    assert selected[0]["manifest_id"] == "sha256:fresh"


def test_orphaned_incomplete_manifest_cannot_poison_attestation() -> None:
    """A stale manifest for a vintage no current run refreshes must not be selected.

    MSFT kept a FY2021 manifest from an earlier, wider ingestion window. No current
    refresh reaches that vintage, so it can never be superseded, and selecting it made
    `source_coverage_not_attested` permanent. An incomplete manifest contributes no
    usable inventory, so it is excluded; coverage and period checks still fail closed
    on whatever genuinely remains.
    """

    from src.stage_04_pipeline.statement_reconciliation_service import (
        _select_source_manifests,
    )

    def _manifest(*, accession: str, entries: list[dict], edges: list[dict]) -> dict:
        return {
            "manifest_id": f"sha256:{accession}",
            "source": "sec_xbrl_filing_presentation_v1",
            "status": "completed",
            "coverage": {"entries": entries},
            "calculation_edges": edges,
            "_store": {
                "manifest_id": f"sha256:{accession}",
                "accession": accession,
                "created_at": "2026-07-30T22:21:07",
            },
        }

    complete_entry = {
        "statement": "BalanceSheet",
        "statement_role": "http://example.test/role/BalanceSheet",
        "period_end": "2025-06-30",
        "period_kind": "annual",
        "units": ["USD"],
        "currencies": ["USD"],
        "presented_fact_ids": ["fact-1"],
    }
    edge = {
        "statement_role": "http://example.test/role/BalanceSheet",
        "parent_concept": "us-gaap_Assets",
        "child_concept": "us-gaap_AssetsCurrent",
        "weight": 1.0,
    }
    fresh = _manifest(accession="0000950170-25-100235", entries=[complete_entry], edges=[edge])
    orphan = _manifest(
        accession="0001564590-21-039151",
        # Stale format: no `statement` key, so the contract cannot be satisfied.
        entries=[{k: v for k, v in complete_entry.items() if k != "statement"}],
        edges=[edge],
    )
    orphan["_store"]["created_at"] = "2026-07-26T20:18:13"

    selected = _select_source_manifests((orphan, fresh))

    assert [m["_store"]["accession"] for m in selected] == ["0000950170-25-100235"]


def _rollup_fact(
    *,
    concept: str,
    value: float,
    fact_id: str,
    parent: str | None = None,
    weight: float | None = None,
) -> dict:
    return {
        "fact_id": fact_id,
        "ticker": "CALM",
        "source": "sec_xbrl_filing_presentation_v1",
        "statement": "BalanceSheet",
        "concept": concept,
        "label": "",
        "numeric_value": value,
        "unit": "USD",
        "currency": "USD",
        "scale_factor": 1.0,
        "period_type": "instant",
        "period_start": "",
        "period_end": "2022-05-28",
        "period_kind": "annual",
        "accession": "0001562762-23-000287",
        "dimensions": {},
        "hierarchy": {
            "statement_role": "http://example.test/role/ConsolidatedBalanceSheets",
            "calculation_parent": parent,
            "calculation_weight": weight,
        },
    }


_ROLLUP_PARENT = "us-gaap_LiabilitiesAndStockholdersEquity"


def test_repeated_parent_presentation_does_not_block_rollup() -> None:
    """A concept presented twice on one statement is one quantity, not an ambiguity.

    CALM presents `LiabilitiesAndStockholdersEquity` twice on the balance sheet, which
    is preserved as two occurrence fact ids by design. Requiring exactly one parent
    fact turned every such rollup into `not_ready` — 47 findings on CALM alone — even
    though both rows carry the identical value.
    """

    from src.stage_04_pipeline.statement_reconciliation_service import (
        _calculation_rollup_checks,
    )

    facts = [
        _rollup_fact(concept=_ROLLUP_PARENT, value=1_427_489_000.0, fact_id="p1"),
        _rollup_fact(concept=_ROLLUP_PARENT, value=1_427_489_000.0, fact_id="p2"),
        _rollup_fact(
            concept="us-gaap_Liabilities",
            value=323_144_000.0,
            fact_id="c1",
            parent=_ROLLUP_PARENT,
            weight=1.0,
        ),
        _rollup_fact(
            concept="us-gaap_StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
            value=1_104_345_000.0,
            fact_id="c2",
            parent=_ROLLUP_PARENT,
            weight=1.0,
        ),
    ]

    checks = _calculation_rollup_checks(facts=facts, eligible_periods={"2022-05-28"})

    assert len(checks) == 1
    # 323,144,000 + 1,104,345,000 == 1,427,489,000 exactly.
    assert checks[0].status == "pass"


def test_conflicting_parent_values_remain_not_ready() -> None:
    """Deduping identical duplicates must not hide a genuine parent conflict."""

    from src.stage_04_pipeline.statement_reconciliation_service import (
        _calculation_rollup_checks,
    )

    facts = [
        _rollup_fact(concept=_ROLLUP_PARENT, value=1_427_489_000.0, fact_id="p1"),
        _rollup_fact(concept=_ROLLUP_PARENT, value=1_400_000_000.0, fact_id="p2"),
        _rollup_fact(
            concept="us-gaap_Liabilities",
            value=323_144_000.0,
            fact_id="c1",
            parent=_ROLLUP_PARENT,
            weight=1.0,
        ),
    ]

    checks = _calculation_rollup_checks(facts=facts, eligible_periods={"2022-05-28"})

    assert len(checks) == 1
    assert checks[0].status == "not_ready"


def test_rollup_never_mixes_filing_vintages() -> None:
    """A calculation linkbase belongs to one filing and must roll up within it.

    The selected consolidated view keeps the newest vintage per concept, which is right
    for restatements but wrong here: CALM's 2022-05-28 balance sheet took `Liabilities`
    from the FY2023 filing and `StockholdersEquity...` from the FY2025 filing's
    comparative, so the equity child grouped under a different accession than its
    parent — the parent matched zero children (`not_ready`) and the remaining group
    summed short (`failure`).

    Each period is rolled up using the filing that presents it most completely, which in
    practice is the filing that reported it as its current year. A later filing's
    abbreviated comparative is not held to a full rollup.
    """

    from src.stage_04_pipeline.statement_reconciliation_service import (
        _calculation_rollup_checks,
    )

    equity = (
        "us-gaap_StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"
    )

    def _vintage(accession: str, *, complete: bool) -> list[dict]:
        facts = [
            _rollup_fact(
                concept=_ROLLUP_PARENT, value=1_427_489_000.0, fact_id=f"{accession}-p"
            ),
            _rollup_fact(
                concept="us-gaap_Liabilities", value=323_144_000.0,
                fact_id=f"{accession}-c1", parent=_ROLLUP_PARENT, weight=1.0,
            ),
        ]
        if complete:
            facts.append(
                _rollup_fact(
                    concept=equity, value=1_104_345_000.0,
                    fact_id=f"{accession}-c2", parent=_ROLLUP_PARENT, weight=1.0,
                )
            )
        for fact in facts:
            fact["accession"] = accession
        return facts

    facts = [
        # The filing that reported this period as its current year: full presentation.
        *_vintage("0001562762-23-000287", complete=True),
        # A later filing repeating it as an abbreviated comparative.
        *_vintage("0001562762-25-000170", complete=False),
    ]

    checks = _calculation_rollup_checks(facts=facts, eligible_periods={"2022-05-28"})

    assert len(checks) == 1
    assert checks[0].status == "pass"
    # Every fact used came from the complete presentation, never the comparative.
    assert all(
        fact_id.startswith("0001562762-23-000287")
        for fact_id in checks[0].source_fact_ids
    )


def test_repeated_child_presentation_is_one_component() -> None:
    """A child presented twice under one parent is one component, not two.

    Summing each occurrence double-counted children: CALM's balance sheet showed a
    parent of 1,427,489,000 against components summing 2,531,834,000, the difference
    being exactly one child counted twice.
    """

    from src.stage_04_pipeline.statement_reconciliation_service import (
        _calculation_rollup_checks,
    )

    equity = "us-gaap_StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"
    facts = [
        _rollup_fact(concept=_ROLLUP_PARENT, value=1_427_489_000.0, fact_id="p1"),
        _rollup_fact(
            concept="us-gaap_Liabilities",
            value=323_144_000.0,
            fact_id="c1",
            parent=_ROLLUP_PARENT,
            weight=1.0,
        ),
        _rollup_fact(
            concept=equity, value=1_104_345_000.0, fact_id="c2",
            parent=_ROLLUP_PARENT, weight=1.0,
        ),
        # Same concept, same amount, second presentation occurrence.
        _rollup_fact(
            concept=equity, value=1_104_345_000.0, fact_id="c3",
            parent=_ROLLUP_PARENT, weight=1.0,
        ),
    ]

    checks = _calculation_rollup_checks(facts=facts, eligible_periods={"2022-05-28"})

    assert len(checks) == 1
    assert checks[0].status == "pass"


def test_distinct_children_sharing_a_value_are_both_counted() -> None:
    """Deduping occurrences must not collapse two genuinely different components."""

    from src.stage_04_pipeline.statement_reconciliation_service import (
        _calculation_rollup_checks,
    )

    facts = [
        _rollup_fact(concept=_ROLLUP_PARENT, value=200_000_000.0, fact_id="p1"),
        _rollup_fact(
            concept="us-gaap_Liabilities", value=100_000_000.0, fact_id="c1",
            parent=_ROLLUP_PARENT, weight=1.0,
        ),
        _rollup_fact(
            concept="us-gaap_StockholdersEquity", value=100_000_000.0, fact_id="c2",
            parent=_ROLLUP_PARENT, weight=1.0,
        ),
    ]

    checks = _calculation_rollup_checks(facts=facts, eligible_periods={"2022-05-28"})

    assert len(checks) == 1
    assert checks[0].status == "pass"


# --------------------------------------------------- PM-approved source treatments


def _cf_fact(
    concept: str,
    *,
    period_end: str = "2025-06-30",
    label: str = "Depreciation, amortization, and other",
) -> dict:
    return {
        "fact_id": f"f-{concept}-{period_end}",
        "ticker": "MSFT",
        "source": "sec_xbrl_filing_presentation_v1",
        "statement": "CashFlowStatement",
        "concept": concept,
        "label": label,
        "numeric_value": 1.0,
        "unit": "USD",
        "currency": "USD",
        "period_kind": "annual",
        "period_end": period_end,
    }


def test_combined_da_line_blocks_without_an_approved_treatment() -> None:
    """MSFT presents only `DepreciationAmortizationAndOther`; that is not pure D&A."""

    from src.stage_04_pipeline.statement_reconciliation_service import (
        _semantic_source_reason_codes,
    )

    facts = [_cf_fact("msft_DepreciationAmortizationAndOther")]

    assert _semantic_source_reason_codes(facts) == ("pure_da_evidence_missing",)


def test_approved_treatment_supplies_the_missing_da_source() -> None:
    """A PM-approved treatment is the sanctioned way past a combined-line gate.

    The system must not choose a D&A convention itself, but it must offer a seam so the
    PM's decision can unblock the ticker. Without this, `pure_da_evidence_missing` is
    unresolvable in code and MSFT can never reach a valuation regardless of approval.
    """

    from src.stage_04_pipeline.statement_reconciliation_service import (
        _semantic_source_reason_codes,
    )

    facts = [_cf_fact("msft_DepreciationAmortizationAndOther")]
    treatments = (
        {
            "ticker": "MSFT",
            "canonical_key": "da",
            "status": "approved",
            "active": 1,
            "rationale": "PM accepted the combined line; bias recorded.",
        },
    )

    assert _semantic_source_reason_codes(facts, approved_treatments=treatments) == ()


def test_treatment_for_another_key_or_ticker_does_not_unblock() -> None:
    from src.stage_04_pipeline.statement_reconciliation_service import (
        _semantic_source_reason_codes,
    )

    facts = [_cf_fact("msft_DepreciationAmortizationAndOther")]

    wrong_key = ({"ticker": "MSFT", "canonical_key": "capex", "active": 1},)
    wrong_ticker = ({"ticker": "CALM", "canonical_key": "da", "active": 1},)
    superseded = ({"ticker": "MSFT", "canonical_key": "da", "active": 0},)

    for treatments in (wrong_key, wrong_ticker, superseded):
        assert _semantic_source_reason_codes(
            facts, approved_treatments=treatments
        ) == ("pure_da_evidence_missing",)


# ------------------------------------------- PM decision: combined D&A sources from CIQ


def _ciq_fact(canonical_concept: str, *, period_end: str = "2025-06-30") -> dict:
    return {
        "fact_id": f"ciq-{canonical_concept}-{period_end}",
        "ticker": "MSFT",
        "source": "ciq_workbook_v1",
        "statement": "CashFlowStatement",
        "concept": canonical_concept,
        "label": "",
        "numeric_value": 28_000_000_000.0,
        "unit": "USD",
        "currency": "USD",
        "period_kind": "annual",
        "period_end": period_end,
    }


def test_combined_da_line_sources_da_from_ciq_when_available() -> None:
    """PM decision 2026-07-31: where XBRL presents only a combined D&A line, source
    `da` from CIQ and record the disagreement rather than blocking the ticker.

    This is deliberately a generic rule keyed on the *shape* of the disclosure, not on
    a ticker: the plan's scale contract forbids symbol-specific finance rules.
    """

    from src.stage_04_pipeline.statement_reconciliation_service import (
        _semantic_source_reason_codes,
    )

    combined_only = [_cf_fact("msft_DepreciationAmortizationAndOther")]
    assert _semantic_source_reason_codes(combined_only) == (
        "pure_da_evidence_missing",
    )

    with_ciq = [*combined_only, _ciq_fact("da")]
    assert _semantic_source_reason_codes(with_ciq) == ()


def test_combined_da_still_blocks_when_ciq_has_no_da_either() -> None:
    from src.stage_04_pipeline.statement_reconciliation_service import (
        _semantic_source_reason_codes,
    )

    facts = [
        _cf_fact("msft_DepreciationAmortizationAndOther"),
        _ciq_fact("capex"),
    ]
    assert _semantic_source_reason_codes(facts) == ("pure_da_evidence_missing",)


def test_conflicting_occurrences_of_one_child_are_ambiguous_not_a_sum() -> None:
    """One concept contributes to a rollup once — a balance-sheet line appears once.

    MSFT presents `us-gaap_CommercialPaper` twice at 2024-06-30 with different values
    (6,700,000,000 and 6,693,000,000). Summing both double-counted the line and failed
    the rollup by exactly the extra occurrence. Which figure is correct is not something
    deterministic code can decide, so the check reports ambiguity rather than guessing
    or manufacturing a failure.
    """

    from src.stage_04_pipeline.statement_reconciliation_service import (
        _calculation_rollup_checks,
    )

    facts = [
        _rollup_fact(concept=_ROLLUP_PARENT, value=100_000_000.0, fact_id="p1"),
        _rollup_fact(
            concept="us-gaap_Liabilities", value=93_300_000.0, fact_id="c1",
            parent=_ROLLUP_PARENT, weight=1.0,
        ),
        _rollup_fact(
            concept="us-gaap_CommercialPaper", value=6_700_000.0, fact_id="c2",
            parent=_ROLLUP_PARENT, weight=1.0,
        ),
        _rollup_fact(
            concept="us-gaap_CommercialPaper", value=6_693_000.0, fact_id="c3",
            parent=_ROLLUP_PARENT, weight=1.0,
        ),
    ]

    checks = _calculation_rollup_checks(facts=facts, eligible_periods={"2022-05-28"})

    assert len(checks) == 1
    assert checks[0].status == "not_ready"
    assert checks[0].finding is not None
    assert "CommercialPaper" in checks[0].finding.description


def test_ltm_expectation_skipped_when_a_later_annual_period_exists() -> None:
    """A trailing window ending before the latest complete fiscal year is stale.

    CALM's FY2026 ends 2026-05-30 while the derived LTM ends 2026-02-28, so the LTM adds
    nothing the annual period does not already cover more recently — and CIQ publishes
    its own LTM on different dates (2025-11-29, 2026-05-30), so demanding cross-source
    overlap on our derived window raised blocking findings for data neither source
    disagrees about.
    """

    from src.stage_04_pipeline.statement_reconciliation_service import (
        _ltm_window_is_superseded,
    )

    assert _ltm_window_is_superseded(
        ltm_period_end="2026-02-28",
        annual_period_ends=("2026-05-30", "2025-05-31"),
    )
    # MSFT's LTM runs past its latest annual close, so it still carries information.
    assert not _ltm_window_is_superseded(
        ltm_period_end="2026-03-31",
        annual_period_ends=("2025-06-30", "2024-06-30"),
    )
    assert not _ltm_window_is_superseded(
        ltm_period_end="2026-02-28",
        annual_period_ends=(),
    )


def test_earliest_window_period_is_not_required_to_bridge_cash() -> None:
    """The oldest period in a window has no in-window opening balance.

    A cash bridge needs the prior period's closing cash. For the earliest period that
    balance lies outside the selected window — MSFT's 2021-06-30 consolidated close is
    not ingested, only a dimensioned variant — so requiring the bridge there blocks
    permanently on data that structurally cannot be present. Later periods still bridge.
    """

    from src.stage_04_pipeline.statement_reconciliation_service import (
        _bridge_required_for_period,
    )

    periods = ("2025-06-30", "2024-06-30", "2023-06-30", "2022-06-30")
    assert _bridge_required_for_period("2025-06-30", periods)
    assert _bridge_required_for_period("2023-06-30", periods)
    assert not _bridge_required_for_period("2022-06-30", periods)
    # A single-period window has nothing to bridge against at all.
    assert not _bridge_required_for_period("2025-06-30", ("2025-06-30",))
