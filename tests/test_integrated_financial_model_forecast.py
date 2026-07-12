from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from src.contracts.professional_financial_model import AvailabilityStatus, CheckStatus
from src.contracts.professional_financial_model import DriverGroup, ModelPeriod, PeriodAxis, PeriodType
from src.stage_02_valuation.integrated_financial_forecast import (
    CIRCULARITY_POLICY_ID,
    DRIVER_SPECS,
    FORECAST_YEARS,
    DriverPath,
    IncompleteHistoricalSeedError,
    ForecastCalculationError,
    InvalidScenarioPolicyError,
    ScenarioDriverSet,
    build_five_year_forecast,
)
from src.stage_02_valuation.model_line_items import professional_line_item_registry


def complete_historical_seed() -> dict[str, float]:
    """Latest normalized actual; expenses/outflows and contra accounts are negative."""
    return {
        "is.revenue": 100.0,
        "bs.cash": 20.0,
        "bs.short_term_investments": 10.0,
        "bs.accounts_receivable": 15.0,
        "bs.other_receivables": 0.0,
        "bs.inventory": 5.0,
        "bs.prepaids": 2.0,
        "bs.other_current_assets": 3.0,
        "bs.gross_ppe": 80.0,
        "bs.accumulated_depreciation": -30.0,
        "bs.long_term_investments": 5.0,
        "bs.goodwill": 10.0,
        "bs.other_intangibles": 5.0,
        "bs.gross_intangibles": 12.0,
        "bs.accumulated_amortization": -7.0,
        "bs.deferred_tax_assets": 2.0,
        "bs.other_long_term_assets": 8.0,
        "bs.accounts_payable": 8.0,
        "bs.accrued_expenses": 4.0,
        "bs.short_term_borrowings": 2.0,
        "bs.current_long_term_debt": 3.0,
        "bs.current_lease_liabilities": 1.0,
        "bs.income_taxes_payable": 2.0,
        "bs.deferred_revenue_current": 5.0,
        "bs.other_current_liabilities": 5.0,
        "bs.long_term_debt": 12.0,
        "bs.long_term_leases": 3.0,
        "bs.deferred_revenue_noncurrent": 4.0,
        "bs.pension_liability": 1.0,
        "bs.deferred_tax_liability": 2.0,
        "bs.other_noncurrent_liabilities": 3.0,
        "bs.common_stock_apic": 40.0,
        "bs.retained_earnings": 50.0,
        "bs.treasury_stock": -10.0,
        "bs.aoci": 0.0,
        "bs.minority_interest": 0.0,
        # Reported total debt includes 17.0 of borrowings and 4.0 of leases.
        "bs.total_debt": 21.0,
        "shares.basic_weighted_average": 10.0,
        "shares.diluted_weighted_average": 10.5,
        "shares.period_end": 10.0,
    }


BASE_DRIVER_VALUES: dict[str, float] = {
    "revenue_growth": 0.10,
    "gross_margin": 0.60,
    "sga_percent_revenue": 0.10,
    "rd_percent_revenue": 0.15,
    "other_opex_percent_revenue": 0.00,
    "da_percent_revenue": 0.05,
    "intangible_amortization_percent_revenue": 0.005,
    "stock_comp_percent_revenue": 0.02,
    "effective_tax_rate": 0.20,
    "cash_tax_rate": 0.20,
    "nopat_tax_rate": 0.21,
    "dso": 45.0,
    "dio": 30.0,
    "dpo": 60.0,
    "deferred_revenue_percent_revenue": 0.09,
    "capex_percent_revenue": 0.06,
    "minimum_cash": 15.0,
    "scheduled_debt_issuance": 0.0,
    "scheduled_debt_repayment": 1.0,
    "cost_of_debt": 0.05,
    "cash_yield": 0.02,
    "dividend_payout": 0.20,
    "buyback_amount": 1.0,
    "common_stock_issuance": 0.0,
    "average_share_price": 50.0,
    "incremental_diluted_shares": 0.02,
    "net_investment_purchases": 1.0,
    "acquisition_spend": 0.0,
    "asset_sale_proceeds": 0.0,
    "asset_cost_disposals": 0.0,
    "asset_disposal_accumulated_depreciation": 0.0,
    "other_nonoperating_percent_revenue": 0.0,
    "prepaids_percent_revenue": 0.02,
    "other_current_assets_percent_revenue": 0.03,
    "accrued_expenses_percent_revenue": 0.04,
    "other_current_liabilities_percent_revenue": 0.05,
    "deferred_tax_assets_percent_revenue": 0.02,
    "deferred_tax_liabilities_percent_revenue": 0.02,
    "preferred_dividends": 0.0,
    "minority_earnings_percent": 0.0,
    "other_operating_cash_flow": 0.0,
    "other_investing_cash_flow": 0.0,
    "other_financing_cash_flow": 0.0,
    "fx_cash_adjustment": 0.0,
    "misc_cash_adjustment": 0.0,
}


def _driver_path(
    *,
    key: str,
    value: float,
    scenario_key: str,
    approved: bool,
) -> DriverPath:
    values = (value,) * FORECAST_YEARS
    unit = DRIVER_SPECS[key].unit
    source_ref = f"fixture:{scenario_key}:{key}"
    method = "synthetic_test_driver"
    fingerprint = DriverPath.fingerprint_for(
        key=key,
        values=values,
        unit=unit,
        source_ref=source_ref,
        method=method,
    )
    return DriverPath(
        key=key,
        values=values,
        unit=unit,
        source_ref=source_ref,
        method=method,
        approval_ref=f"approval:{scenario_key}:{key}" if approved else None,
        queue_item_id=None if approved else f"queue:{scenario_key}:{key}",
        current_driver_fingerprint=fingerprint,
        approved_driver_fingerprint=fingerprint if approved else None,
    )

def driver_set(
    scenario_key: str = "Base",
    *,
    changes: dict[str, float] | None = None,
    approved: bool = True,
) -> ScenarioDriverSet:
    values = {**BASE_DRIVER_VALUES, **(changes or {})}
    assert set(values) == set(DRIVER_SPECS)
    paths = tuple(
        _driver_path(
            key=key,
            value=value,
            scenario_key=scenario_key,
            approved=approved,
        )
        for key, value in values.items()
    )
    return ScenarioDriverSet(
        scenario_key=scenario_key,
        parent_scenario_key=None if scenario_key == "Base" else "Base",
        paths=paths,
    )


def test_builds_five_year_integrated_forecast_for_every_registry_line() -> None:
    forecast = build_five_year_forecast(
        complete_historical_seed(),
        driver_set(),
        last_historical_period_end=date(2026, 6, 30),
    )

    assert tuple(period.key for period in forecast.model.period_axis.periods) == (
        "FY27E",
        "FY28E",
        "FY29E",
        "FY30E",
        "FY31E",
    )
    assert forecast.circularity_policy.policy_id == CIRCULARITY_POLICY_ID
    assert forecast.circularity_policy.uses_excel_iteration is False

    registry_keys = {spec.canonical_key for spec in professional_line_item_registry()}
    assert set(forecast.line_index) == registry_keys
    assert all(len(line.values) == FORECAST_YEARS for line in forecast.line_index.values())
    assert all(
        value.value is not None or value.state.status is not AvailabilityStatus.AVAILABLE
        for line in forecast.line_index.values()
        for value in line.values
    )

    # Source-dependent detail is explicit; the consolidated forecast is never
    # silently disaggregated into invented segments or KPIs.
    for key in ("segment.revenue", "segment.operating_income", "segment.assets", "segment.kpi"):
        value = forecast.value(key, 1)
        assert value.value is None
        assert value.state.status is AvailabilityStatus.PM_REQUIRED
        assert value.state.reason_code == "segment_source_or_approval_required"


def test_forecast_methods_use_operating_drivers_and_preserve_legitimate_zeroes() -> None:
    forecast = build_five_year_forecast(
        complete_historical_seed(),
        driver_set(),
        last_historical_period_end=date(2026, 6, 30),
    )

    revenue = forecast.numeric("is.revenue", 1)
    cogs = forecast.numeric("is.cost_of_revenue", 1)
    assert revenue == pytest.approx(110.0)
    assert cogs == pytest.approx(-44.0)
    assert forecast.numeric("is.gross_profit", 1) == pytest.approx(66.0)
    assert forecast.numeric("bs.accounts_receivable", 1) == pytest.approx(110.0 * 45.0 / 365.0)
    assert forecast.numeric("bs.inventory", 1) == pytest.approx(44.0 * 30.0 / 365.0)
    assert forecast.numeric("bs.accounts_payable", 1) == pytest.approx(44.0 * 60.0 / 365.0)
    assert forecast.numeric("cf.capex", 1) == pytest.approx(-6.6)
    assert forecast.numeric("bs.gross_ppe", 1) == pytest.approx(86.6)
    assert forecast.numeric("cf.common_stock_issued", 1) == 0.0
    assert forecast.numeric("is.other_operating_expense", 1) == 0.0
    if "is.operating_expenses_total" in forecast.line_index:
        assert forecast.numeric("is.operating_expenses_total", 1) == pytest.approx(-27.5)


def test_statements_cash_debt_shares_and_fcfe_bridge_tie_each_year() -> None:
    forecast = build_five_year_forecast(
        complete_historical_seed(),
        driver_set(),
        last_historical_period_end=date(2026, 6, 30),
    )
    checks = {check.check_id: check for check in forecast.model.check_results}

    for year in range(1, FORECAST_YEARS + 1):
        for prefix in ("balance_sheet", "cash_flow", "debt_tie", "reported_debt_tie", "cash_tie", "shares_tie", "fcfe_bridge"):
            check = checks[f"{prefix}:FY{26 + year}E"]
            assert check.status is CheckStatus.PASS
            assert abs(check.difference or 0.0) <= 0.1

        fcff = forecast.numeric("cf.unlevered_fcf", year)
        cfo = forecast.numeric("cf.cash_from_operations", year)
        capex = forecast.numeric("cf.capex", year)
        net_income = forecast.numeric("is.net_income_company", year)
        nopat = forecast.numeric("tax.nopat", year)
        net_borrowing = (
            forecast.numeric("cf.debt_issued", year)
            + forecast.numeric("cf.debt_repaid", year)
        )
        assert fcff == pytest.approx(cfo - net_income + nopat + capex)
        assert forecast.numeric("cf.levered_fcf", year) == pytest.approx(
            cfo + capex + net_borrowing
        )
        assert forecast.numeric("tax.effective_rate", year) == 0.20
        assert nopat == pytest.approx(
            forecast.numeric("is.ebit", year) * (1.0 - 0.21)
        )


def test_minimum_cash_liquidity_draw_has_no_hidden_interest_circularity_or_cash_sweep() -> None:
    stress = driver_set(
        changes={
            "revenue_growth": -0.20,
            "minimum_cash": 25.0,
            "buyback_amount": 30.0,
            "scheduled_debt_repayment": 0.0,
        }
    )
    forecast = build_five_year_forecast(
        complete_historical_seed(),
        stress,
        last_historical_period_end=date(2026, 6, 30),
    )

    assert forecast.numeric("bs.cash", 1) == pytest.approx(25.0)
    assert forecast.liquidity_draws[0] > 0.0
    assert forecast.numeric("cf.debt_issued", 1) == pytest.approx(forecast.liquidity_draws[0])
    # Current-year interest uses average beginning and scheduled ending debt;
    # a minimum-cash draw begins accruing in the following year.
    assert forecast.numeric("is.interest_expense", 1) == pytest.approx(-17.0 * 0.05)
    assert abs(forecast.numeric("is.interest_expense", 2)) > abs(
        forecast.numeric("is.interest_expense", 1)
    )

    cash_rich = build_five_year_forecast(
        complete_historical_seed(),
        driver_set(
            changes={
                "revenue_growth": 0.30,
                "minimum_cash": 1.0,
                "intangible_amortization_percent_revenue": 0.001,
            }
        ),
        last_historical_period_end=date(2026, 6, 30),
    )
    assert cash_rich.numeric("bs.cash", 1) > 1.0
    # Excess cash is retained.  No LBO-style automatic debt repayment exists.
    assert cash_rich.numeric("cf.debt_repaid", 1) == -1.0
    assert cash_rich.liquidity_draws[0] == 0.0


def test_unapproved_diagnostic_drivers_are_used_but_remain_explicit_pm_gates() -> None:
    forecast = build_five_year_forecast(
        complete_historical_seed(),
        driver_set(approved=False),
        last_historical_period_end=date(2026, 6, 30),
    )

    assert forecast.model.state.status is AvailabilityStatus.PM_REQUIRED
    assert any(item.startswith("pm_approval_required:Base:revenue_growth:") for item in forecast.model.blockers)
    assert "queue:Base:revenue_growth" in "|".join(forecast.model.blockers)
    for key in ("capex_percent_revenue", "dividend_payout", "buyback_amount"):
        assert any(
            item.startswith(f"pm_approval_required:Base:{key}:")
            for item in forecast.model.blockers
        )
    assert forecast.numeric("is.revenue", 1) == pytest.approx(110.0)


def test_reported_debt_keeps_leases_separate_and_long_term_receivables_visible() -> None:
    seed = complete_historical_seed()
    # Actual-MSFT shape: reported debt can be dominated by lease liabilities,
    # while borrowing interest and issuance schedules remain borrowing-only.
    seed["bs.current_lease_liabilities"] = 41.0
    seed["bs.long_term_leases"] = 44.0
    seed["bs.total_debt"] = 102.0  # 17 borrowings + 85 leases
    seed["bs.cash"] += 81.0
    seed["bs.long_term_receivables"] = 5.1
    seed["bs.common_stock_apic"] += 5.1

    forecast = build_five_year_forecast(
        seed,
        driver_set(),
        last_historical_period_end=date(2026, 6, 30),
    )

    assert forecast.debt_convention.convention_id == "borrowings_excluding_lease_liabilities_v1"
    assert forecast.numeric("bs.long_term_receivables", 1) == 5.1
    assert forecast.numeric("bs.total_debt", 1) == pytest.approx(
        forecast.numeric("debt.total_debt", 1)
        + forecast.numeric("debt.lease_liabilities", 1)
    )
    assert forecast.numeric("is.interest_expense", 1) == pytest.approx(-16.5 * 0.05)


def test_missing_historical_seed_is_not_coerced_to_zero() -> None:
    seed = complete_historical_seed()
    del seed["bs.treasury_stock"]

    with pytest.raises(IncompleteHistoricalSeedError, match="bs.treasury_stock"):
        build_five_year_forecast(
            seed,
            driver_set(),
            last_historical_period_end=date(2026, 6, 30),
        )



def test_driver_fingerprints_bind_approval_to_exact_driver_inputs() -> None:
    key = "revenue_growth"
    values = (0.1,) * FORECAST_YEARS
    unit = DRIVER_SPECS[key].unit
    source_ref = "fixture:fingerprint"
    method = "source_backed_path"
    fingerprint = DriverPath.fingerprint_for(
        key=key,
        values=values,
        unit=unit,
        source_ref=source_ref,
        method=method,
    )

    approved = DriverPath(
        key=key,
        values=values,
        unit=unit,
        source_ref=source_ref,
        method=method,
        approval_ref="approval:fingerprint",
        current_driver_fingerprint=fingerprint,
        approved_driver_fingerprint=fingerprint,
    )
    assert approved.approved is True
    assert approved.driver_group is DriverGroup.FINANCE_SEMANTIC
    assert approved.current_driver_fingerprint == fingerprint
    assert fingerprint != DriverPath.fingerprint_for(
        key=key,
        values=(0.11,) * FORECAST_YEARS,
        unit=unit,
        source_ref=source_ref,
        method=method,
    )

    with pytest.raises(InvalidScenarioPolicyError, match="missing or stale"):
        DriverPath(
            key=key,
            values=values,
            unit=unit,
            source_ref=source_ref,
            method=method,
            approval_ref="approval:stale",
            approved_driver_fingerprint="0" * 64,
        )
    with pytest.raises(InvalidScenarioPolicyError, match="current fingerprint"):
        DriverPath(
            key=key,
            values=values,
            unit=unit,
            source_ref=source_ref,
            method=method,
            queue_item_id="queue:mismatch",
            current_driver_fingerprint="0" * 64,
        )

    stale_unapproved = DriverPath(
        key=key,
        values=values,
        unit=unit,
        source_ref=source_ref,
        method=method,
        queue_item_id="queue:stale",
        approved_driver_fingerprint="0" * 64,
    )
    assert stale_unapproved.approved is False
    assert stale_unapproved.current_driver_fingerprint == fingerprint


def test_historical_adapter_seeds_latest_fiscal_year_not_ltm() -> None:
    seed = complete_historical_seed()

    class HistoricalAdapter:
        period_keys = ("FY25", "LTM")
        result = SimpleNamespace(
            period_axis=PeriodAxis(
                periods=(
                    ModelPeriod(
                        index=1,
                        key="FY25",
                        end_date=date(2025, 6, 30),
                        period_type=PeriodType.FISCAL_YEAR,
                    ),
                    ModelPeriod(
                        index=2,
                        key="LTM",
                        end_date=date(2026, 3, 31),
                        period_type=PeriodType.LTM,
                    ),
                )
            )
        )

        def value(self, key: str, period_key: str) -> SimpleNamespace:
            if key not in seed:
                raise KeyError(key)
            value = 999.0 if key == "is.revenue" and period_key == "LTM" else seed[key]
            return SimpleNamespace(
                value=value,
                state=SimpleNamespace(status=AvailabilityStatus.AVAILABLE),
            )

    historical = HistoricalAdapter()
    with pytest.raises(
        IncompleteHistoricalSeedError,
        match="explicit YTD plus Q4 stub",
    ):
        build_five_year_forecast(
            historical,
            driver_set(),
            last_historical_period_end=date(2025, 6, 30),
        )

    class FYOnlyAdapter(HistoricalAdapter):
        period_keys = ("FY25",)
        result = SimpleNamespace(
            period_axis=PeriodAxis(
                periods=(HistoricalAdapter.result.period_axis.periods[0],)
            )
        )

    fy_only = FYOnlyAdapter()
    forecast = build_five_year_forecast(
        fy_only,
        driver_set(),
        last_historical_period_end=date(2025, 6, 30),
    )

    assert forecast.model.period_axis.periods[0].key == "FY26E"
    assert forecast.numeric("is.revenue", 1) == pytest.approx(110.0)
    with pytest.raises(IncompleteHistoricalSeedError, match="latest fiscal-year"):
        build_five_year_forecast(
            fy_only,
            driver_set(),
            last_historical_period_end=date(2026, 3, 31),
        )


def test_driver_schedules_and_equity_roll_forwards_reconcile_each_year() -> None:
    forecast = build_five_year_forecast(
        complete_historical_seed(),
        driver_set(),
        last_historical_period_end=date(2026, 6, 30),
    )
    checks = {check.check_id: check for check in forecast.model.check_results}
    roll_forward_checks = (
        "interest_expense_tie",
        "interest_income_tie",
        "basic_share_average_tie",
        "incremental_diluted_shares_tie",
        "basic_eps_tie",
        "diluted_eps_tie",
        "issuance_cash_share_price_tie",
        "buyback_cash_share_price_tie",
        "cash_dividend_per_share_tie",
        "dividend_retained_earnings_tie",
        "stock_compensation_currency_tie",
        "receivables_driver_tie",
        "inventory_driver_tie",
        "payables_driver_tie",
        "deferred_revenue_driver_tie",
        "ppe_gross_roll_forward",
        "accumulated_depreciation_roll_forward",
        "net_ppe_tie",
        "da_split_tie",
        "asset_sale_gain_tie",
        "accumulated_amortization_roll_forward",
        "net_intangibles_tie",
        "book_current_deferred_tax_identity",
        "deferred_tax_asset_roll_forward",
        "deferred_tax_liability_roll_forward",
        "tax_cash_conversion",
        "fcff_definition",
        "investment_roll_forward",
        "debt_roll_forward",
        "tax_payable_roll_forward",
        "retained_earnings_roll_forward",
        "apic_roll_forward",
        "treasury_stock_roll_forward",
        "aoci_roll_forward",
        "minority_interest_roll_forward",
        "lease_liabilities_hold",
    )

    previous_shares = complete_historical_seed()["shares.period_end"]
    for year in range(1, FORECAST_YEARS + 1):
        period = forecast.model.period_axis.periods[year - 1].key
        for prefix in roll_forward_checks:
            assert checks[f"{prefix}:{period}"].status is CheckStatus.PASS
            assert abs(checks[f"{prefix}:{period}"].difference or 0.0) <= 0.1

        revenue = forecast.numeric("is.revenue", year)
        receivables = forecast.numeric("wc.receivables", year)
        assert receivables == pytest.approx(
            forecast.numeric("bs.accounts_receivable", year)
        )
        assert forecast.numeric("wc.dso", year) == pytest.approx(
            receivables / revenue * 365.0
        )
        assert forecast.numeric("ppe.capex", year) == pytest.approx(
            -forecast.numeric("cf.capex", year)
        )
        assert forecast.numeric("cf.da", year) == pytest.approx(
            forecast.numeric("ppe.depreciation", year)
            + forecast.numeric("cf.intangible_amortization", year)
        )
        assert forecast.numeric("bs.other_intangibles", year) == pytest.approx(
            forecast.numeric("bs.gross_intangibles", year)
            + forecast.numeric("bs.accumulated_amortization", year)
        )

        period_end = forecast.numeric("shares.period_end", year)
        expected_period_end = (
            previous_shares
            + forecast.numeric("cf.common_stock_issued", year)
            / BASE_DRIVER_VALUES["average_share_price"]
            + forecast.numeric("cf.share_repurchase", year)
            / BASE_DRIVER_VALUES["average_share_price"]
        )
        assert period_end == pytest.approx(expected_period_end)
        assert forecast.numeric("shares.basic_weighted_average", year) == pytest.approx(
            (previous_shares + period_end) / 2.0
        )
        assert forecast.numeric("shares.dilution", year) == pytest.approx(
            BASE_DRIVER_VALUES["incremental_diluted_shares"]
        )
        common_cash_dividend = (
            forecast.numeric("cf.dividends_paid", year)
            - forecast.numeric("is.preferred_dividends", year)
        )
        assert forecast.numeric("shares.cash_dividend_per_share", year) == pytest.approx(
            abs(common_cash_dividend)
            / forecast.numeric("shares.basic_weighted_average", year)
        )
        assert forecast.numeric("shares.stock_compensation", year) == pytest.approx(
            forecast.numeric("is.stock_based_compensation", year)
        )
        previous_shares = period_end

    for key in (
        "shares.dividend_per_share",
        "shares.options_incremental",
        "shares.rsu_incremental",
        "shares.psu_incremental",
        "shares.convertible_incremental",
        "shares.fully_diluted",
    ):
        value = forecast.value(key, 1)
        assert value.value is None
        assert value.state.status is AvailabilityStatus.PM_REQUIRED
    evidence_check = {
        item.check_id: item for item in forecast.model.check_results
    }["share_declaration_and_fds_evidence"]
    assert evidence_check.status is CheckStatus.BLOCKED
    assert "source_or_pm_required:shares.fully_diluted" in forecast.model.blockers


def test_interest_income_uses_cash_and_investments_on_a_prefunding_basis() -> None:
    zero_yield = build_five_year_forecast(
        complete_historical_seed(),
        driver_set(changes={"cash_yield": 0.0}),
        last_historical_period_end=date(2026, 6, 30),
    )
    forecast = build_five_year_forecast(
        complete_historical_seed(),
        driver_set(),
        last_historical_period_end=date(2026, 6, 30),
    )

    seed = complete_historical_seed()
    beginning_assets = (
        seed["bs.cash"]
        + seed["bs.short_term_investments"]
        + seed["bs.long_term_investments"]
    )
    ending_prefunding_assets = (
        zero_yield.numeric("bs.cash", 1)
        + zero_yield.numeric("bs.short_term_investments", 1)
        + zero_yield.numeric("bs.long_term_investments", 1)
    )
    expected_interest_income = (
        (beginning_assets + ending_prefunding_assets)
        / 2.0
        * BASE_DRIVER_VALUES["cash_yield"]
    )

    assert forecast.numeric("is.interest_income", 1) == pytest.approx(
        expected_interest_income
    )
    assert forecast.numeric("is.interest_expense", 1) == pytest.approx(
        -((17.0 + 16.0) / 2.0) * BASE_DRIVER_VALUES["cost_of_debt"]
    )


def test_preferred_dividends_and_diagnostic_counterparts_are_explicit() -> None:
    preferred = build_five_year_forecast(
        complete_historical_seed(),
        driver_set(changes={"preferred_dividends": 2.0}),
        last_historical_period_end=date(2026, 6, 30),
    )
    common_dividend = preferred.numeric("cf.dividends_paid", 1) + 2.0
    assert common_dividend == pytest.approx(
        -max(preferred.numeric("is.net_income_common", 1), 0.0)
        * BASE_DRIVER_VALUES["dividend_payout"]
    )

    unsupported = build_five_year_forecast(
        complete_historical_seed(),
        driver_set(changes={"acquisition_spend": 1.0}),
        last_historical_period_end=date(2026, 6, 30),
    )
    checks = {check.check_id: check for check in unsupported.model.check_results}
    assert unsupported.model.state.status is AvailabilityStatus.BLOCKING
    assert checks["counterpart_policy:acquisition_spend"].status is CheckStatus.BLOCKED
    assert "unsupported_counterpart_policy:Base:acquisition_spend" in unsupported.model.blockers
    assert checks["balance_sheet:FY27E"].status is CheckStatus.PASS


def test_tax_roll_forwards_convert_book_tax_to_cash_tax_once() -> None:
    seed = complete_historical_seed()
    forecast = build_five_year_forecast(
        seed,
        driver_set(
            changes={
                "effective_tax_rate": 0.20,
                "cash_tax_rate": 0.20,
                "nopat_tax_rate": 0.24,
                "deferred_tax_assets_percent_revenue": 0.018,
                "deferred_tax_liabilities_percent_revenue": 0.022,
            }
        ),
        last_historical_period_end=date(2026, 6, 30),
    )
    checks = {check.check_id: check for check in forecast.model.check_results}

    prior_payable = seed["bs.income_taxes_payable"]
    prior_dta = seed["bs.deferred_tax_assets"]
    prior_dtl = seed["bs.deferred_tax_liability"]
    for year in range(1, FORECAST_YEARS + 1):
        period = forecast.model.period_axis.periods[year - 1].key
        book_tax = -forecast.numeric("is.income_tax", year)
        cash_taxes = forecast.numeric("tax.cash_taxes", year)
        deferred_tax = forecast.numeric("cf.change_deferred_taxes", year)
        current_tax = book_tax - deferred_tax
        payable = forecast.numeric("bs.income_taxes_payable", year)
        payable_change = payable - prior_payable
        dta = forecast.numeric("bs.deferred_tax_assets", year)
        dtl = forecast.numeric("bs.deferred_tax_liability", year)

        assert abs(cash_taxes) == pytest.approx(book_tax)
        assert book_tax == pytest.approx(current_tax + deferred_tax)
        assert payable_change == pytest.approx(current_tax + cash_taxes)
        assert forecast.numeric("cf.change_income_taxes", year) == pytest.approx(
            payable_change
        )
        assert payable_change + deferred_tax == pytest.approx(book_tax + cash_taxes)
        assert payable_change + deferred_tax == pytest.approx(0.0)
        assert deferred_tax == pytest.approx((dtl - prior_dtl) - (dta - prior_dta))
        for prefix in (
            "book_current_deferred_tax_identity",
            "tax_payable_roll_forward",
            "tax_cash_conversion",
            "deferred_tax_asset_roll_forward",
            "deferred_tax_liability_roll_forward",
        ):
            assert checks[f"{prefix}:{period}"].status is CheckStatus.PASS

        assert forecast.numeric("tax.nopat", year) == pytest.approx(
            forecast.numeric("is.ebit", year) * (1.0 - 0.24)
        )
        prior_payable = payable
        prior_dta = dta
        prior_dtl = dtl


def test_asset_sale_cash_proceeds_are_distinct_from_cost_disposals() -> None:
    forecast = build_five_year_forecast(
        complete_historical_seed(),
        driver_set(
            changes={
                "asset_sale_proceeds": 4.0,
                "asset_cost_disposals": 5.0,
                "asset_disposal_accumulated_depreciation": 2.0,
            }
        ),
        last_historical_period_end=date(2026, 6, 30),
    )

    assert forecast.numeric("cf.sale_ppe", 1) == 4.0
    assert forecast.numeric("ppe.disposals", 1) == 5.0
    assert forecast.numeric("cf.gain_sale_assets", 1) == -1.0
    assert forecast.numeric("bs.gross_ppe", 1) == pytest.approx(
        80.0 + 110.0 * BASE_DRIVER_VALUES["capex_percent_revenue"] - 5.0
    )
    assert forecast.numeric("bs.accumulated_depreciation", 1) == pytest.approx(
        -30.0
        - forecast.numeric("ppe.depreciation", 1)
        + 2.0
    )
    checks = {check.check_id: check for check in forecast.model.check_results}
    for prefix in (
        "asset_sale_gain_tie",
        "ppe_gross_roll_forward",
        "accumulated_depreciation_roll_forward",
        "balance_sheet",
    ):
        assert checks[f"{prefix}:FY27E"].status is CheckStatus.PASS

    with pytest.raises(
        ForecastCalculationError,
        match="distinct asset-cost disposal path",
    ):
        build_five_year_forecast(
            complete_historical_seed(),
            driver_set(changes={"asset_sale_proceeds": 4.0}),
            last_historical_period_end=date(2026, 6, 30),
        )


def test_finance_semantic_policy_paths_cannot_be_mislabeled_mechanical() -> None:
    key = "capex_percent_revenue"
    values = (0.06,) * FORECAST_YEARS
    unit = DRIVER_SPECS[key].unit
    source_ref = "fixture:flat-capex-policy"
    method = "flat_policy_requires_pm"
    fingerprint = DriverPath.fingerprint_for(
        key=key,
        values=values,
        unit=unit,
        source_ref=source_ref,
        method=method,
    )

    with pytest.raises(InvalidScenarioPolicyError, match="finance-semantic policy"):
        DriverPath(
            key=key,
            values=values,
            unit=unit,
            source_ref=source_ref,
            method=method,
            approval_ref="approval:invalid-mechanical-capex",
            driver_group=DriverGroup.MECHANICAL,
            current_driver_fingerprint=fingerprint,
            approved_driver_fingerprint=fingerprint,
        )


def test_incremental_dilution_and_stock_compensation_never_issue_basic_shares() -> None:
    base = build_five_year_forecast(
        complete_historical_seed(),
        driver_set(),
        last_historical_period_end=date(2026, 6, 30),
    )
    high_dilution = build_five_year_forecast(
        complete_historical_seed(),
        driver_set(changes={"incremental_diluted_shares": 5.0}),
        last_historical_period_end=date(2026, 6, 30),
    )
    high_stock_comp = build_five_year_forecast(
        complete_historical_seed(),
        driver_set(changes={"stock_comp_percent_revenue": 0.10}),
        last_historical_period_end=date(2026, 6, 30),
    )

    assert high_dilution.numeric("shares.period_end", 1) == pytest.approx(
        base.numeric("shares.period_end", 1)
    )
    assert high_dilution.numeric("shares.basic_weighted_average", 1) == pytest.approx(
        base.numeric("shares.basic_weighted_average", 1)
    )
    assert high_dilution.numeric("shares.diluted_weighted_average", 1) == pytest.approx(
        high_dilution.numeric("shares.basic_weighted_average", 1) + 5.0
    )
    assert high_stock_comp.numeric("shares.period_end", 1) == pytest.approx(
        base.numeric("shares.period_end", 1)
    )
    assert high_stock_comp.numeric("shares.stock_compensation", 1) == pytest.approx(
        -high_stock_comp.numeric("is.revenue", 1) * 0.10
    )
    assert high_stock_comp.numeric("shares.dilution", 1) == pytest.approx(
        BASE_DRIVER_VALUES["incremental_diluted_shares"]
    )
