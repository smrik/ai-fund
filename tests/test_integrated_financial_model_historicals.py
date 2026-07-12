from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from src.contracts.professional_financial_model import (
    AvailabilityState,
    AvailabilityStatus,
    CheckStatus,
    EstimateStatus,
    FactFormulaStatus,
    ModelInputSnapshot,
    PeriodType,
    SourceFact,
    SourceManifest,
    SupplementalInputFact,
    SupplementalInputSnapshot,
    UnitKind,
    WorkbookSourceIdentity,
)
from src.stage_02_valuation.integrated_financial_model import (
    AmbiguousHistoricalSourceError,
    IncompleteHistoricalAxisError,
    build_historical_financial_model,
    build_historical_financial_model_from_sqlite,
)


PERIODS = (
    ("FY23", "2023-06-30", 2),
    ("FY24", "2024-06-30", 3),
    ("FY25", "2025-06-30", 4),
    ("LTM", "2026-03-31", 5),
)
SOURCE_HASH = "a" * 64


def _available() -> AvailabilityState:
    return AvailabilityState(status=AvailabilityStatus.AVAILABLE)


def _fact(
    row: int,
    label: str,
    values: tuple[float | None, ...],
    *,
    run_id: int = 7,
) -> list[dict]:
    rows: list[dict] = []
    for (calc_type, period_date, column), value in zip(PERIODS, values, strict=True):
        a1 = f"{chr(64 + column)}{row}"
        rows.append(
            {
                "run_id": run_id,
                "ticker": "MSFT",
                "sheet_name": "Financial Statements",
                "section_name": "Uncategorized",
                "row_index": row,
                "source_row_id": f"Financial Statements!{row}",
                "row_label": label,
                "period_date": period_date,
                "calc_type": calc_type,
                "column_index": column,
                "a1_locator": a1,
                "cell_locator": f"Financial Statements!{a1}",
                "value_num": value,
                "cached_value": value,
                "has_formula": 1,
                "has_cached_value": int(value is not None),
                "formula_text": f"=CIQ({a1})",
                "formula_status": "formula_cached" if value is not None else "formula_cache_missing",
                "formula_error": None,
                "cached_error": None,
                "source_file": "MSFT_Standard.xlsx",
                "scale_factor": 1.0,
            }
        )
    return rows


def _complete_source() -> list[dict]:
    # A compact but fully tied three-statement fixture. Optional registry rows
    # intentionally remain typed unavailable; the source-dependent segment and
    # consensus modules are never inferred from consolidated facts.
    lines = [
        (10, "Total Revenues", (100.0, 120.0, 140.0, 160.0)),
        (11, "Cost Of Goods Sold", (40.0, 48.0, 56.0, 64.0)),
        (15, "Gross Profit", (60.0, 72.0, 84.0, 96.0)),
        (16, "Selling General & Admin Exp.", (10.0, 12.0, 14.0, 16.0)),
        (21, "R & D Exp.", (15.0, 18.0, 21.0, 24.0)),
        (26, "Other Operating Exp., Total", (25.0, 30.0, 35.0, 40.0)),
        (27, "Operating Income", (35.0, 42.0, 49.0, 56.0)),
        (28, "Interest Expense", (-2.0, -2.0, -2.0, -2.0)),
        (29, "Interest and Invest. Income", (1.0, 1.0, 1.0, 1.0)),
        (33, "Other Non-Operating Inc. (Exp.)", (0.0, 0.0, 0.0, 0.0)),
        (45, "EBT Incl Unusual Items", (34.0, 41.0, 48.0, 55.0)),
        (46, "Income Tax Expense", (6.8, 8.2, 9.6, 11.0)),
        (50, "Net Income to Company", (27.2, 32.8, 38.4, 44.0)),
        (52, "Net Income to Parent", (27.2, 32.8, 38.4, 44.0)),
        (54, "NI to Common Incl Extra Items", (27.2, 32.8, 38.4, 44.0)),
        (58, "Weighted Avg. Basic Shares Out.", (10.0, 10.0, 10.0, 10.0)),
        (61, "Weighted Avg. Diluted Shares Out.", (11.0, 11.0, 11.0, 11.0)),
        (56, "Basic EPS", (2.72, 3.28, 3.84, 4.40)),
        (59, "Diluted EPS", (2.4727, 2.9818, 3.4909, 4.0)),
        (74, "EBITDA", (40.0, 48.0, 56.0, 64.0)),
        (81, "EBIT", (35.0, 42.0, 49.0, 56.0)),
        (127, "Effective Tax Rate (%)", (20.0, 20.0, 20.0, 20.0)),
        (183, "Net Income", (27.2, 32.8, 38.4, 44.0)),
        (185, "Amort. of Goodwill and Intangibles", (1.0, 1.0, 1.0, 1.0)),
        (187, "Depreciation & Amort., Total", (5.0, 6.0, 7.0, 8.0)),
        (198, "Change in Acc. Receivable", (-1.0, -1.0, -1.0, -1.0)),
        (199, "Change In Inventories", (0.0, 0.0, 0.0, 0.0)),
        (200, "Change in Acc. Payable", (1.0, 1.0, 1.0, 1.0)),
        (207, "Cash from Ops.", (32.2, 38.8, 45.4, 52.0)),
        (210, "Capital Expenditure", (-5.0, -6.0, -7.0, -8.0)),
        (219, "Cash from Investing", (-5.0, -6.0, -7.0, -8.0)),
        (236, "Cash from Financing", (-10.0, -11.0, -12.0, -13.0)),
        (220, "Total Debt Issued", (0.0, 0.0, 0.0, 0.0)),
        (221, "Total Debt Repaid", (0.0, 0.0, 0.0, 0.0)),
        (243, "Depreciation (From Notes)", (4.0, 5.0, 6.0, 7.0)),
        (237, "Foreign Exchange Rate Adj.", (0.0, 0.0, 0.0, 0.0)),
        (238, "Misc. Cash Flow Adj.", (0.0, 0.0, 0.0, 0.0)),
        (239, "Net Change in Cash", (17.2, 21.8, 26.4, 31.0)),
        (281, "Cash And Equivalents", (30.0, 40.0, 50.0, 60.0)),
        (282, "Short Term Investments", (20.0, 20.0, 20.0, 20.0)),
        (284, "Total Cash & ST Investments", (50.0, 60.0, 70.0, 80.0)),
        (285, "Accounts Receivable", (10.0, 12.0, 14.0, 16.0)),
        (288, "Total Receivables", (10.0, 12.0, 14.0, 16.0)),
        (289, "Inventory", (2.0, 2.0, 2.0, 2.0)),
        (293, "Total Current Assets", (70.0, 84.0, 98.0, 112.0)),
        (298, "Gross Property, Plant & Equipment", (40.0, 46.0, 53.0, 61.0)),
        (299, "Accumulated Depreciation", (-10.0, -16.0, -23.0, -31.0)),
        (300, "Net Property, Plant & Equipment", (30.0, 30.0, 30.0, 30.0)),
        (301, "Long-term Investments", (5.0, 5.0, 5.0, 5.0)),
        (302, "Goodwill", (5.0, 5.0, 5.0, 5.0)),
        (303, "Other Intangibles", (0.0, 0.0, 0.0, 0.0)),
        (310, "Other Long-Term Assets", (10.0, 10.0, 10.0, 10.0)),
        (455, "Gross Intangible Assets", (7.0, 8.0, 9.0, 10.0)),
        (456, "Accumulated Amortization of Intangible Assets", (-7.0, -8.0, -9.0, -10.0)),
        (311, "Total Assets", (120.0, 134.0, 148.0, 162.0)),
        (312, "Accounts Payable", (8.0, 9.0, 10.0, 11.0)),
        (314, "Short-term Borrowings", (2.0, 2.0, 2.0, 2.0)),
        (315, "Current Portion of Long Term Debt", (3.0, 3.0, 3.0, 3.0)),
        (316, "Current Portion of Leases", (1.0, 1.0, 1.0, 1.0)),
        (323, "Total Current Liabilities", (20.0, 21.0, 22.0, 23.0)),
        (324, "Long-Term Debt", (10.0, 10.0, 10.0, 10.0)),
        (325, "Long-Term Leases", (4.0, 4.0, 4.0, 4.0)),
        (331, "Other Non-Current Liabilities", (6.0, 6.0, 6.0, 6.0)),
        (332, "Total Liabilities", (40.0, 41.0, 42.0, 43.0)),
        (338, "Common Stock", (20.0, 20.0, 20.0, 20.0)),
        (340, "Retained Earnings", (60.0, 73.0, 86.0, 99.0)),
        (343, "Total Common Equity", (80.0, 93.0, 106.0, 119.0)),
        (345, "Total Equity", (80.0, 93.0, 106.0, 119.0)),
        (346, "Total Liabilities And Equity", (120.0, 134.0, 148.0, 162.0)),
        (371, "Total Shares Out. on Balance Sheet Date", (10.0, 10.0, 10.0, 10.0)),
        (379, "Total Debt", (20.0, 20.0, 20.0, 20.0)),
    ]
    return [fact for row, label, values in lines for fact in _fact(row, label, values)]


def _typed_snapshot(rows: list[dict]) -> ModelInputSnapshot:
    facts: list[SourceFact] = []
    for row in rows:
        fact_id = SourceFact.stable_fact_id(
            ticker="MSFT",
            ciq_run_id=7,
            source_hash=SOURCE_HASH,
            workbook_sheet="Financial Statements",
            row_index=row["row_index"],
            column_index=row["column_index"],
        )
        facts.append(
            SourceFact(
                fact_id=fact_id,
                ticker="MSFT",
                ciq_run_id=7,
                source_file="MSFT_Standard.xlsx",
                source_path=r"C:\licensed\MSFT_Standard.xlsx",
                source_hash=SOURCE_HASH,
                workbook_sheet="Financial Statements",
                section="Uncategorized",
                row_index=row["row_index"],
                column_index=row["column_index"],
                cell_locator=row["a1_locator"],
                row_label=row["row_label"],
                period_end=date.fromisoformat(row["period_date"]),
                period_type=(
                    PeriodType.LTM
                    if row["calc_type"] == "LTM"
                    else PeriodType.FISCAL_YEAR
                ),
                estimate_status=EstimateStatus.ACTUAL,
                formula_text=row["formula_text"],
                cached_value=row["cached_value"],
                formula_status=FactFormulaStatus.CALCULATED,
                calculation_type=row["calc_type"],
                unit="USD mm",
                unit_kind=UnitKind.CURRENCY,
                scale=1_000_000.0,
                currency="USD",
                quality_state=_available(),
            )
        )

    supplemental_facts: list[SupplementalInputFact] = []
    for key in (
        "current_price",
        "market_cap",
        "beta",
        "risk_free_rate",
        "equity_risk_premium",
        "total_debt",
        "cost_of_debt",
        "fx_rate",
    ):
        kwargs: dict = {}
        unit = "x"
        unit_kind = UnitKind.MULTIPLE
        if key in {"current_price", "market_cap", "total_debt"}:
            unit = "USD"
            unit_kind = UnitKind.CURRENCY
            kwargs["currency"] = "USD"
        if key == "beta":
            kwargs["method"] = "peer_median"
        if key == "risk_free_rate":
            kwargs["duration"] = "10Y"
        supplemental_facts.append(
            SupplementalInputFact(
                field_key=key,
                value=1.0,
                state=_available(),
                unit=unit,
                unit_kind=unit_kind,
                source_name="CIQ Standard",
                source_locator=f"cache:{key}",
                as_of_date=date(2026, 7, 11),
                **kwargs,
            )
        )
    supplemental = SupplementalInputSnapshot(
        ticker="MSFT",
        valuation_date=date(2026, 7, 11),
        currency="USD",
        peer_universe_version="fixture-v1",
        facts=tuple(supplemental_facts),
    )
    manifest = SourceManifest(
        ticker="MSFT",
        fiscal_convention="June year-end",
        workbook=WorkbookSourceIdentity(
            ticker="MSFT",
            source_file="MSFT_Standard.xlsx",
            source_path=r"C:\licensed\MSFT_Standard.xlsx",
            source_hash=SOURCE_HASH,
            file_modified_at=datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc),
            workbook_as_of_date=date(2026, 7, 11),
            fiscal_period_end=date(2026, 3, 31),
            currency="USD",
            unit_convention="USD mm",
            state=_available(),
        ),
        selected_ciq_run_id=7,
        parser_version="ibm_standard_v4",
        fact_count=len(facts),
        fact_status_counts={"available": len(facts)},
        supplemental_snapshot_hash=supplemental.snapshot_hash,
    )
    return ModelInputSnapshot(
        ticker="MSFT",
        fiscal_calendar="June year-end",
        currency="USD",
        source_manifest=manifest,
        selected_ciq_run_id=7,
        source_facts=tuple(facts),
        line_item_registry_version="professional_line_items_v3",
        normalized_actuals=(),
        approved_assumptions=(),
        supplemental_input_snapshot=supplemental,
        supplemental_input_hash=supplemental.snapshot_hash,
    )


def test_builds_complete_typed_history_with_ordered_actuals_and_ltm() -> None:
    historical = build_historical_financial_model(_complete_source())

    assert historical.period_keys == ("FY23", "FY24", "FY25", "LTM")
    assert tuple(period.end_date for period in historical.result.period_axis.periods) == (
        date(2023, 6, 30),
        date(2024, 6, 30),
        date(2025, 6, 30),
        date(2026, 3, 31),
    )
    assert {statement.statement_key for statement in historical.result.statements} == {
        "income_statement",
        "balance_sheet",
        "cash_flow",
    }
    assert "working_capital" in {
        schedule.schedule_key for schedule in historical.result.supporting_schedules
    }
    assert len(historical.lineage) == len(historical.registry) * 4
    assert historical.value("ppe.ending_gross_ppe", "FY23").value == 40.0
    assert (
        historical.value("ppe.beginning_gross_ppe", "FY23").state.status
        is AvailabilityStatus.UNAVAILABLE
    )
    assert all(
        tuple(value.period_key for value in line.values) == historical.period_keys
        for container in (*historical.result.statements, *historical.result.supporting_schedules)
        for line in container.lines
    )


def test_accepts_validated_typed_model_input_snapshot_and_binds_its_hash() -> None:
    snapshot = _typed_snapshot(_complete_source())

    historical = build_historical_financial_model(snapshot)

    assert historical.period_keys == ("FY23", "FY24", "FY25", "LTM")
    assert historical.result.input_hash == snapshot.content_hash
    assert historical.coverage.required_direct_coverage == 1.0
    reference = historical.period_lineage("is.revenue", "FY25").source_refs[0]
    assert reference.source_ref.startswith("fact:")
    assert reference.cell_locator == "Financial Statements!D10"
    lineage = historical.period_lineage("is.revenue", "FY25")
    assert reference.period_key == "FY25"
    assert reference.period_end == date(2025, 6, 30)
    assert reference.period_type is PeriodType.FISCAL_YEAR
    assert reference.estimate_status is EstimateStatus.ACTUAL
    assert reference.raw_source_value == 140.0
    assert reference.unit == "USD mm"
    assert reference.unit_kind == UnitKind.CURRENCY.value
    assert reference.scale == 1_000_000.0
    assert reference.currency == "USD"
    assert reference.formula_status == FactFormulaStatus.CALCULATED.value
    assert reference.formula_error is None
    assert lineage.normalized_value == 140.0
    assert lineage.derived_value is None
    assert lineage.transformation_rule == "source_sign_preserved"
    assert lineage.source_scale == 1_000_000.0
    assert "is.gross_profit" in lineage.downstream_dependencies


def test_preserves_zero_and_documents_source_and_normalized_signs() -> None:
    historical = build_historical_financial_model(_complete_source())

    other_opex = historical.period_lineage("is.other_operating_expense", "FY23")
    cogs = historical.period_lineage("is.cost_of_revenue", "FY23")
    capex = historical.period_lineage("cf.capex", "FY23")

    assert other_opex.normalized_value == 0.0
    assert other_opex.source_sign == "mixed"
    assert other_opex.normalization_rule == "deterministic_formula"
    assert {ref.row_label for ref in other_opex.source_refs} == {
        "Other Operating Exp., Total",
        "Selling General & Admin Exp.",
        "R & D Exp.",
    }
    assert cogs.source_value == 40.0
    assert cogs.normalized_value == -40.0
    assert cogs.normalization_rule == "negative=-abs(source)"
    assert cogs.source_refs[0].cell_locator == "Financial Statements!B11"
    assert capex.source_value == -5.0
    assert capex.normalized_value == -5.0


def test_duplicate_stock_compensation_rows_use_total_and_cash_flow_roles() -> None:
    rows = _complete_source()
    rows.extend(_fact(19, "Stock-Based Compensation", (0.0, 0.0, 0.0, 0.0)))
    rows.extend(
        _fact(
            173,
            "Stock-Based Comp., Total",
            (9_000.0, 10_000.0, 11_974.0, 12_356.0),
        )
    )
    rows.extend(
        _fact(
            196,
            "Stock-Based Compensation",
            (9_000.0, 10_000.0, 11_974.0, 12_356.0),
        )
    )

    historical = build_historical_financial_model(rows)

    income = historical.period_lineage("is.stock_based_compensation", "FY25")
    cash_flow = historical.period_lineage("cf.stock_based_compensation", "FY25")
    shares = historical.period_lineage("shares.stock_compensation", "FY25")
    assert income.normalized_value == -11_974.0
    assert income.method_id == "historical:direct"
    assert income.source_refs[0].cell_locator == "Financial Statements!D173"
    assert cash_flow.normalized_value == 11_974.0
    assert cash_flow.method_id == "historical:direct"
    assert cash_flow.source_refs[0].cell_locator == "Financial Statements!D196"
    assert shares.normalized_value == -11_974.0
    assert shares.method_id == "historical:derived"
    assert shares.source_refs[0].cell_locator == "Financial Statements!D173"
    assert all(ref.row_index != 19 for item in (income, cash_flow, shares) for ref in item.source_refs)


@pytest.mark.skipif(
    not Path("data/alpha_pod.db").exists(),
    reason="actual MSFT cache is unavailable",
)
def test_actual_msft_stock_compensation_uses_rows_173_and_196() -> None:
    historical = build_historical_financial_model_from_sqlite(
        "data/alpha_pod.db",
        ticker="MSFT",
        run_id=3,
    )

    for period, expected, income_cell, cash_flow_cell in (
        ("FY25", 11_974.0, "Financial Statements!L173", "Financial Statements!L196"),
        ("LTM", 12_356.0, "Financial Statements!M173", "Financial Statements!M196"),
    ):
        income = historical.period_lineage("is.stock_based_compensation", period)
        cash_flow = historical.period_lineage("cf.stock_based_compensation", period)
        assert income.normalized_value == -expected
        assert cash_flow.normalized_value == expected
        assert income.source_refs[0].cell_locator == income_cell
        assert cash_flow.source_refs[0].cell_locator == cash_flow_cell
        assert income.source_refs[0].row_index == 173
        assert cash_flow.source_refs[0].row_index == 196

    assert all(
        check.status not in {CheckStatus.FAIL}
        for check in historical.result.check_results
    )

def test_accounting_checks_pass_and_segment_data_remains_typed_pm_required() -> None:
    historical = build_historical_financial_model(_complete_source())
    checks = {check.check_id: check for check in historical.result.check_results}

    for period in historical.period_keys:
        assert checks[f"balance_sheet:{period}"].status is CheckStatus.PASS
        assert checks[f"cash_flow:{period}"].status is CheckStatus.PASS
        assert checks[f"debt_tie:{period}"].status is CheckStatus.PASS
        assert checks[f"cash_tie:{period}"].status is CheckStatus.PASS
        assert checks[f"diluted_eps:{period}"].status is CheckStatus.PASS

    segment = historical.value("segment.revenue", "FY25")
    assert segment.state.status is AvailabilityStatus.PM_REQUIRED
    assert segment.value is None
    assert historical.result.state.status is AvailabilityStatus.PM_REQUIRED
    assert checks["coverage:consolidated_direct"].status is CheckStatus.PASS
    assert checks["coverage:source_dependent"].status is CheckStatus.BLOCKED


def test_duplicate_restatement_rows_fail_closed_but_cross_statement_duplicate_is_resolved() -> None:
    rows = _complete_source()
    # The same label appearing in the cash-flow section must not displace the
    # income-statement row selected for is.net_income_parent.
    rows.extend(_fact(189, "Net Income to Parent", (999.0, 999.0, 999.0, 999.0)))
    historical = build_historical_financial_model(rows)
    assert historical.value("is.net_income_parent", "FY25").value == 38.4

    # A conflicting duplicate within the same statement section is an
    # ambiguous restatement, and must never be selected by accident.
    rows.extend(_fact(90, "Total Revenues", (101.0, 121.0, 141.0, 161.0)))
    with pytest.raises(AmbiguousHistoricalSourceError, match="is.revenue"):
        build_historical_financial_model(rows)


def test_axis_gaps_and_mixed_runs_fail_closed() -> None:
    rows = _complete_source()
    rows = [row for row in rows if row["calc_type"] != "FY24"]
    with pytest.raises(IncompleteHistoricalAxisError, match="non-contiguous"):
        build_historical_financial_model(rows)

    mixed = _complete_source()
    mixed[0] = {**mixed[0], "run_id": 8}
    with pytest.raises(AmbiguousHistoricalSourceError, match="CIQ run"):
        build_historical_financial_model(mixed)


def test_legitimate_missing_source_value_is_unavailable_not_coerced_to_zero() -> None:
    rows = _complete_source()
    for row in rows:
        if row["row_label"] == "Total Assets" and row["calc_type"] == "FY25":
            row["value_num"] = None
            row["cached_value"] = None
            row["has_cached_value"] = 0
            row["formula_status"] = "formula_cache_missing"

    historical = build_historical_financial_model(rows)
    value = historical.value("bs.total_assets", "FY25")
    check = {item.check_id: item for item in historical.result.check_results}[
        "balance_sheet:FY25"
    ]

    assert value.value is None
    assert value.state.status is AvailabilityStatus.BLOCKING
    assert value.state.reason_code == "historical_source_value_unavailable"
    assert check.status is CheckStatus.BLOCKED
    assert historical.result.state.status is AvailabilityStatus.BLOCKING



def test_schedule_identities_keep_borrowings_leases_and_interest_distinct() -> None:
    historical = build_historical_financial_model(_complete_source())

    assert historical.value("debt.total_debt", "FY25").value == 15.0
    assert historical.value("debt.lease_liabilities", "FY25").value == 5.0
    assert historical.value("bs.total_debt", "FY25").value == 20.0
    assert historical.value("debt.interest_expense", "FY25").value == -2.0
    assert historical.value("debt.interest_income", "FY25").value == 1.0
    assert historical.value("ppe.capex", "FY25").value == 7.0
    assert historical.value("cf.intangible_amortization", "FY25").value == 1.0
    assert historical.value("ppe.depreciation", "FY25").value == 6.0
    assert historical.value("bs.gross_intangibles", "FY25").value == 9.0
    assert historical.value("bs.accumulated_amortization", "FY25").value == -9.0
    assert historical.value("bs.other_intangibles", "FY25").value == 0.0
    assert historical.value("ppe.gross_intangibles", "FY25").value == 9.0
    assert historical.value("ppe.accumulated_amortization", "FY25").value == -9.0
    assert historical.value("ppe.intangibles", "FY25").value == 0.0
    assert historical.period_lineage(
        "cf.intangible_amortization", "FY25"
    ).source_refs[0].row_index == 185
    assert historical.period_lineage(
        "ppe.depreciation", "FY25"
    ).source_refs[0].row_index == 243

    assert historical.value("tax.effective_rate", "FY25").value == pytest.approx(0.20)
    assert historical.value("tax.nopat", "FY25").value == pytest.approx(39.2)
    assert historical.period_lineage(
        "tax.effective_rate", "FY25"
    ).normalization_rule == "percentage_points_to_decimal_rate"
    assert historical.value("cf.unlevered_fcf", "FY25").value == pytest.approx(39.2)
    assert historical.value("cf.levered_fcf", "FY25").value == pytest.approx(38.4)


    for key in ("wc.change_nwc", "ppe.beginning_gross_ppe"):
        ltm = historical.value(key, "LTM")
        assert ltm.value is None
        assert ltm.state.status is AvailabilityStatus.UNAVAILABLE
        assert ltm.state.reason_code == "ltm_year_ago_balance_unavailable"

@pytest.mark.skipif(
    not Path("data/alpha_pod.db").exists(),
    reason="actual MSFT cache is unavailable",
)
def test_actual_msft_da_intangibles_and_fcff_use_distinct_source_roles() -> None:
    historical = build_historical_financial_model_from_sqlite(
        "data/alpha_pod.db",
        ticker="MSFT",
        run_id=3,
    )

    assert historical.value("cf.da", "FY25").value == 28_000.0
    assert historical.value("cf.intangible_amortization", "FY25").value == 6_000.0
    assert historical.value("ppe.depreciation", "FY25").value == 22_000.0
    assert historical.value("bs.gross_intangibles", "FY25").value == 43_557.0
    assert historical.value("bs.accumulated_amortization", "FY25").value == -20_953.0
    assert historical.value("bs.other_intangibles", "FY25").value == 22_604.0
    expected_fcff = 136_162.0 - 101_832.0 + historical.value(
        "tax.nopat", "FY25"
    ).value - 64_551.0
    assert historical.value("cf.unlevered_fcf", "FY25").value == pytest.approx(
        expected_fcff
    )


def test_historical_unusual_items_and_net_interest_preserve_signed_source_values() -> None:
    rows = _complete_source()
    rows.extend(_fact(30, "Net Interest Exp.", (1.0, 2.0, 3.0, 4.0)))
    rows.extend(
        _fact(
            44,
            "Unusual Items, Total (Supple)",
            (2.0, -3.0, 0.0, 4.0),
        )
    )

    historical = build_historical_financial_model(rows)

    assert historical.value("is.net_interest_expense", "FY25").value == 3.0
    assert historical.period_lineage(
        "is.net_interest_expense",
        "FY25",
    ).normalization_rule == "source_sign_preserved"
    assert historical.value("is.unusual_items", "FY24").value == -3.0
    assert historical.value("is.unusual_items", "FY25").value == 0.0


def test_formula_error_details_make_a_cached_number_unavailable() -> None:
    rows = _complete_source()
    target = next(
        row
        for row in rows
        if row["row_label"] == "Total Revenues" and row["calc_type"] == "FY25"
    )
    target["formula_error"] = "#VALUE!"

    historical = build_historical_financial_model(rows)
    lineage = historical.period_lineage("is.revenue", "FY25")

    assert lineage.normalized_value is None
    assert lineage.raw_source_value == 140.0
    assert lineage.formula_status == "formula_cached"
    assert lineage.formula_error == "#VALUE!"
    assert lineage.source_refs[0].formula_error == "#VALUE!"
    assert historical.result.state.status is AvailabilityStatus.BLOCKING
