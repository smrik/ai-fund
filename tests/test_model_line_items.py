from __future__ import annotations

from collections import Counter

import pytest
from src.stage_02_valuation.integrated_financial_forecast import DRIVER_SPECS

from src.contracts.professional_financial_model import AvailabilityStatus, LineItemSpec
from src.stage_02_valuation.model_line_items import (
    AmbiguousLineItemMappingError,
    CoverageResolution,
    InvalidLineItemRegistryError,
    REGISTRY_VERSION,
    RowDisposition,
    build_line_item_coverage,
    classify_source_records,
    professional_line_item_registry,
    validate_line_item_registry,
)


def _fact(
    *,
    row: int,
    label: str,
    value: float | None,
    column: int = 4,
    sheet: str = "Financial Statements",
    period: str = "2025-12-31",
    calc_type: str = "FY25",
) -> dict:
    return {
        "sheet_name": sheet,
        "row_index": row,
        "row_label": label,
        "column_index": column,
        "a1_locator": f"D{row}",
        "period_date": period,
        "calc_type": calc_type,
        "value_num": value,
    }


def _spec(
    key: str,
    *,
    alias: str | None = None,
    dependencies: tuple[str, ...] = (),
    required: bool = True,
    missing: AvailabilityStatus = AvailabilityStatus.BLOCKING,
    order: int = 1,
) -> LineItemSpec:
    return LineItemSpec(
        canonical_key=key,
        display_label=key,
        statement_or_schedule="test",
        sign_convention="positive",
        source_mappings=(alias,) if alias else (),
        required=required,
        material=required,
        historical_aggregation_rule="direct" if alias else "derived_identity",
        forecast_method="direct_driver" if alias else "derived_identity",
        dependencies=dependencies,
        scenario_drivers=(),
        presentation_order=order,
        missing_data_policy=missing,
    )


def test_professional_registry_is_deterministic_complete_and_dependency_valid() -> None:
    first = professional_line_item_registry()
    second = professional_line_item_registry()

    assert first == second
    assert REGISTRY_VERSION == "professional_line_items_v3"
    assert len(first) >= 90
    assert len({spec.canonical_key for spec in first}) == len(first)
    assert len({spec.presentation_order for spec in first}) == len(first)
    assert validate_line_item_registry(first) == first

    sections = Counter(spec.statement_or_schedule for spec in first)
    assert sections["income_statement"] >= 15
    assert sections["balance_sheet"] >= 25
    assert sections["cash_flow"] >= 20
    assert sections["working_capital"] >= 5
    assert sections["ppe_intangibles"] >= 5
    assert sections["debt_cash_interest"] >= 5
    assert sections["capital_allocation"] >= 5
    assert sections["taxes"] >= 3
    assert sections["shares_eps"] >= 5

    keys = {spec.canonical_key for spec in first}
    for spec in first:
        assert set(spec.dependencies) <= keys
        assert spec.sign_convention
        assert spec.historical_aggregation_rule
        assert spec.forecast_method
        assert isinstance(spec.missing_data_policy, AvailabilityStatus)


def test_exact_alias_mapping_preserves_unmapped_and_reference_rows() -> None:
    records = [
        _fact(row=10, label="Total Revenues", value=100.0),
        _fact(row=11, label="Cost Of Goods Sold", value=40.0),
        _fact(row=12, label="Total Revenue", value=100.0),
        _fact(row=13, label="Unmapped Custom KPI", value=3.0),
        _fact(row=3, label="Total Revenues", value=1.0, sheet="Common Size"),
    ]

    classifications = classify_source_records(records)
    by_identity = {(row.sheet_name, row.row_index): row for row in classifications}

    assert by_identity[("Financial Statements", 10)].disposition is RowDisposition.MAPPED
    assert by_identity[("Financial Statements", 10)].canonical_key == "is.revenue"
    assert by_identity[("Financial Statements", 11)].canonical_key == "is.cost_of_revenue"
    # No fuzzy/singular guess is permitted.
    assert by_identity[("Financial Statements", 12)].disposition is RowDisposition.UNMAPPED
    assert by_identity[("Financial Statements", 13)].disposition is RowDisposition.UNMAPPED
    # Common Size remains reference evidence; raw statements are canonical.
    assert by_identity[("Common Size", 3)].disposition is RowDisposition.REFERENCE_ONLY


def test_stock_compensation_aliases_are_bound_to_statement_roles() -> None:
    records = [
        _fact(row=19, label="Stock-Based Compensation", value=0.0),
        _fact(row=173, label="Stock-Based Comp., Total", value=11_974.0),
        _fact(row=196, label="Stock-Based Compensation", value=11_974.0),
    ]

    classifications = classify_source_records(records)
    by_row = {row.row_index: row for row in classifications}
    registry = {spec.canonical_key: spec for spec in professional_line_item_registry()}

    assert registry["is.stock_based_compensation"].source_mappings == (
        "Stock-Based Comp., Total",
    )
    assert registry["cf.stock_based_compensation"].source_mappings == (
        "Stock-Based Compensation",
    )
    assert by_row[19].disposition is RowDisposition.UNMAPPED
    assert by_row[19].reason == "source_row_role_mismatch"
    assert by_row[173].canonical_key == "is.stock_based_compensation"
    assert by_row[196].canonical_key == "cf.stock_based_compensation"

def test_duplicate_logical_rows_remain_separate_by_exact_source_row() -> None:
    records = [
        _fact(row=10, label="Total Revenues", value=100.0),
        _fact(row=510, label="Total Revenues", value=101.0),
    ]

    classifications = classify_source_records(records)
    mapped = [row for row in classifications if row.disposition is RowDisposition.MAPPED]

    assert len(mapped) == 2
    assert {row.row_index for row in mapped} == {10, 510}
    assert {row.canonical_key for row in mapped} == {"is.revenue"}


def test_alias_collision_is_rejected_instead_of_silently_choosing() -> None:
    specs = (
        _spec("is.revenue", alias="Total Revenues", order=1),
        _spec("is.other_revenue", alias="Total Revenues", order=2),
    )

    with pytest.raises(AmbiguousLineItemMappingError, match="Total Revenues"):
        validate_line_item_registry(specs)

    with pytest.raises(AmbiguousLineItemMappingError, match="Total Revenues"):
        classify_source_records([_fact(row=10, label="Total Revenues", value=100.0)], registry=specs)


def test_dependency_cycle_and_unknown_dependency_are_rejected() -> None:
    unknown = (_spec("a", dependencies=("missing",), order=1),)
    with pytest.raises(InvalidLineItemRegistryError, match="unknown dependencies"):
        validate_line_item_registry(unknown)

    cyclic = (
        _spec("a", dependencies=("b",), order=1),
        _spec("b", dependencies=("a",), order=2),
    )
    with pytest.raises(InvalidLineItemRegistryError, match="dependency cycle"):
        validate_line_item_registry(cyclic)


def test_required_lines_resolve_to_direct_derived_or_typed_missing_states() -> None:
    specs = (
        _spec("is.revenue", alias="Total Revenues", order=1),
        _spec("is.cost", alias="Cost Of Goods Sold", order=2),
        _spec("is.gross_profit", dependencies=("is.revenue", "is.cost"), order=3),
        _spec("bs.total_assets", alias="Total Assets", order=4),
        _spec(
            "segment.revenue",
            required=True,
            missing=AvailabilityStatus.PM_REQUIRED,
            order=5,
        ),
    )
    records = [
        # A legitimate zero is historical coverage, not missing.
        _fact(row=10, label="Total Revenues", value=0.0),
        _fact(row=11, label="Cost Of Goods Sold", value=0.0),
        _fact(row=311, label="Total Assets", value=None),
    ]

    report = build_line_item_coverage(records, registry=specs)
    coverage = {row.canonical_key: row for row in report.line_coverage}

    assert coverage["is.revenue"].state.status is AvailabilityStatus.AVAILABLE
    assert coverage["is.revenue"].resolution is CoverageResolution.DIRECT
    assert coverage["is.gross_profit"].state.status is AvailabilityStatus.AVAILABLE
    assert coverage["is.gross_profit"].resolution is CoverageResolution.DERIVED
    assert coverage["bs.total_assets"].state.status is AvailabilityStatus.BLOCKING
    assert coverage["bs.total_assets"].state.reason_code == "historical_source_values_missing"
    assert coverage["segment.revenue"].state.status is AvailabilityStatus.PM_REQUIRED
    assert coverage["segment.revenue"].state.reason_code == "historical_source_mapping_missing"

    assert report.required_line_count == 5
    assert report.required_available_count == 3
    assert report.required_gap_count == 2
    assert all(
        row.state.status in AvailabilityStatus
        for row in report.line_coverage
        if row.required
    )


def test_default_registry_returns_typed_state_for_every_required_line_with_sparse_history() -> None:
    report = build_line_item_coverage([
        _fact(row=10, label="Total Revenues", value=100.0),
        _fact(row=11, label="Cost Of Goods Sold", value=40.0),
    ])

    required = [row for row in report.line_coverage if row.required]
    assert required
    assert len(required) == report.required_line_count
    assert report.required_available_count + report.required_gap_count == report.required_line_count
    assert all(row.state.status is not AvailabilityStatus.UNAVAILABLE or row.state.reason_code for row in required)
    assert report.classification_counts[RowDisposition.MAPPED] == 2


def test_registry_driver_keys_and_schedule_signs_match_forecast_semantics() -> None:
    registry = {
        spec.canonical_key: spec for spec in professional_line_item_registry()
    }
    driver_keys = {
        driver
        for spec in registry.values()
        for driver in spec.scenario_drivers
    }

    assert driver_keys <= set(DRIVER_SPECS)
    assert registry["is.net_interest_expense"].sign_convention == "signed"
    assert registry["wc.receivables"].dependencies == ("bs.accounts_receivable",)
    assert registry["cf.intangible_amortization"].source_mappings == (
        "Amort. of Goodwill and Intangibles",
    )
    assert registry["cf.levered_fcf"].source_mappings == ()
    assert registry["cf.unlevered_fcf"].source_mappings == ()
    assert registry["bs.other_intangibles"].dependencies == (
        "bs.accumulated_amortization",
        "bs.gross_intangibles",
    )
    assert registry["ppe.depreciation"].dependencies == (
        "cf.da",
        "cf.intangible_amortization",
    )
    assert registry["ppe.disposals"].scenario_drivers == (
        "asset_cost_disposals",
    )
    assert registry["tax.nopat"].scenario_drivers == ("nopat_tax_rate",)
    assert registry["debt.total_debt"].dependencies == (
        "bs.current_long_term_debt",
        "bs.long_term_debt",
        "bs.short_term_borrowings",
    )
    for key in (
        "debt.interest_expense",
        "capital.capex",
        "capital.acquisitions",
        "capital.dividends",
        "capital.buybacks",
        "capital.debt_repayment",
        "tax.income_tax_expense",
        "tax.cash_taxes",
        "shares.stock_compensation",
    ):
        assert registry[key].sign_convention == "negative"
    assert registry["ppe.capex"].sign_convention == "positive"
