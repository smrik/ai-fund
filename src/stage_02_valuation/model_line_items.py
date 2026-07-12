"""Deterministic professional-model line registry and source coverage controls.

The registry deliberately uses exact source aliases.  It never guesses that a
similar label is equivalent, and it retains every source row in the coverage
classification so unmapped evidence remains visible to reviewers.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, Mapping, Sequence

from src.contracts.professional_financial_model import (
    AvailabilityState,
    AvailabilityStatus,
    LineItemSpec,
)


REGISTRY_VERSION = "professional_line_items_v3"
PRIMARY_STATEMENT_SHEET = "Financial Statements"
REFERENCE_ONLY_SHEETS = frozenset({"Common Size", "Detailed Comps"})
SOURCE_ALIAS_ROW_ROLES: Mapping[tuple[str, str], tuple[int, int]] = {
    ("is.stock_based_compensation", "Stock-Based Comp., Total"): (1, 182),
    ("cf.stock_based_compensation", "Stock-Based Compensation"): (183, 280),
    (
        "cf.intangible_amortization",
        "Amort. of Goodwill and Intangibles",
    ): (183, 280),
}


class InvalidLineItemRegistryError(ValueError):
    """Raised when registry identities or dependencies are invalid."""


class AmbiguousLineItemMappingError(InvalidLineItemRegistryError):
    """Raised when one exact source alias maps to multiple canonical lines."""


class RowDisposition(str, Enum):
    MAPPED = "mapped"
    REFERENCE_ONLY = "reference_only"
    UNMAPPED = "unmapped"


class CoverageResolution(str, Enum):
    DIRECT = "direct"
    DERIVED = "derived"
    MISSING = "missing"


@dataclass(frozen=True, slots=True)
class SourceRowClassification:
    sheet_name: str
    row_index: int
    row_label: str
    column_index: int | None
    disposition: RowDisposition
    canonical_key: str | None
    reason: str


@dataclass(frozen=True, slots=True)
class LineCoverage:
    canonical_key: str
    display_label: str
    statement_or_schedule: str
    required: bool
    material: bool
    resolution: CoverageResolution
    state: AvailabilityState
    source_rows: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class CoverageReport:
    registry_version: str
    classifications: tuple[SourceRowClassification, ...]
    line_coverage: tuple[LineCoverage, ...]
    classification_counts: Mapping[RowDisposition, int]
    required_line_count: int
    required_available_count: int
    required_gap_count: int


def _clean_alias(value: Any) -> str:
    return str(value or "").strip()


def _available() -> AvailabilityState:
    return AvailabilityState(status=AvailabilityStatus.AVAILABLE)


def _missing_state(spec: LineItemSpec, reason_code: str, message: str) -> AvailabilityState:
    return AvailabilityState(
        status=spec.missing_data_policy,
        reason_code=reason_code,
        message=message,
    )


def validate_line_item_registry(
    registry: Sequence[LineItemSpec],
) -> tuple[LineItemSpec, ...]:
    """Validate deterministic identities, aliases, dependencies, and cycles."""
    ordered = tuple(sorted(registry, key=lambda item: item.presentation_order))
    keys = [item.canonical_key for item in ordered]
    if len(set(keys)) != len(keys):
        duplicates = sorted(key for key, count in Counter(keys).items() if count > 1)
        raise InvalidLineItemRegistryError(f"duplicate canonical keys: {duplicates}")

    orders = [item.presentation_order for item in ordered]
    if len(set(orders)) != len(orders):
        duplicates = sorted(order for order, count in Counter(orders).items() if count > 1)
        raise InvalidLineItemRegistryError(f"duplicate presentation orders: {duplicates}")

    alias_owner: dict[str, str] = {}
    for item in ordered:
        for raw_alias in item.source_mappings:
            alias = _clean_alias(raw_alias)
            if not alias:
                raise InvalidLineItemRegistryError(
                    f"blank source mapping on {item.canonical_key}"
                )
            owner = alias_owner.get(alias)
            if owner is not None and owner != item.canonical_key:
                raise AmbiguousLineItemMappingError(
                    f"exact source alias {alias!r} maps to both {owner} and "
                    f"{item.canonical_key}"
                )
            alias_owner[alias] = item.canonical_key

    known = set(keys)
    for item in ordered:
        unknown = sorted(set(item.dependencies) - known)
        if unknown:
            raise InvalidLineItemRegistryError(
                f"{item.canonical_key} has unknown dependencies: {unknown}"
            )

    graph = {item.canonical_key: tuple(item.dependencies) for item in ordered}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(key: str, path: tuple[str, ...]) -> None:
        if key in visiting:
            cycle = " -> ".join((*path, key))
            raise InvalidLineItemRegistryError(f"dependency cycle: {cycle}")
        if key in visited:
            return
        visiting.add(key)
        for dependency in graph[key]:
            visit(dependency, (*path, key))
        visiting.remove(key)
        visited.add(key)

    for key in keys:
        visit(key, ())
    return ordered


def _line(
    rows: list[LineItemSpec],
    canonical_key: str,
    display_label: str,
    section: str,
    *,
    aliases: Sequence[str] = (),
    sign: str = "positive",
    required: bool = True,
    material: bool | None = None,
    aggregation: str = "direct",
    forecast: str = "direct_driver",
    dependencies: Sequence[str] = (),
    drivers: Sequence[str] = (),
    missing: AvailabilityStatus | None = None,
) -> None:
    if material is None:
        material = required
    if missing is None:
        missing = AvailabilityStatus.BLOCKING if required else AvailabilityStatus.UNAVAILABLE
    rows.append(
        LineItemSpec(
            canonical_key=canonical_key,
            display_label=display_label,
            statement_or_schedule=section,
            sign_convention=sign,
            source_mappings=tuple(aliases),
            required=required,
            material=material,
            historical_aggregation_rule=aggregation,
            forecast_method=forecast,
            dependencies=tuple(dependencies),
            scenario_drivers=tuple(drivers),
            presentation_order=len(rows) + 1,
            missing_data_policy=missing,
        )
    )


def professional_line_item_registry() -> tuple[LineItemSpec, ...]:
    """Return the deterministic cross-sector three-statement registry.

    Supporting schedules depend on canonical statement lines rather than
    claiming the same source alias twice.  This keeps the source map collision
    free while still making each schedule complete and traceable.
    """
    rows: list[LineItemSpec] = []

    # Income statement and profitability.
    _line(rows, "is.revenue", "Revenue", "income_statement", aliases=("Total Revenues",), drivers=("revenue_growth",))
    _line(rows, "is.cost_of_revenue", "Cost of revenue", "income_statement", aliases=("Cost Of Goods Sold",), sign="negative", drivers=("gross_margin",))
    _line(rows, "is.gross_profit", "Gross profit", "income_statement", aliases=("Gross Profit",), forecast="derived_identity", dependencies=("is.revenue", "is.cost_of_revenue"))
    _line(rows, "is.sga", "Selling, general and administrative", "income_statement", aliases=("Selling General & Admin Exp.",), sign="negative", drivers=("sga_percent_revenue",))
    _line(rows, "is.research_development", "Research and development", "income_statement", aliases=("R & D Exp.",), sign="negative", drivers=("rd_percent_revenue",))
    _line(rows, "is.operating_expenses_total", "Operating expenses, total", "income_statement", aliases=("Other Operating Exp., Total",), sign="negative", required=False)
    _line(rows, "is.other_operating_expense", "Incremental other operating expense", "income_statement", sign="negative", required=False, aggregation="derived_identity", forecast="direct_driver", dependencies=("is.operating_expenses_total", "is.sga", "is.research_development"), drivers=("other_opex_percent_revenue",))
    _line(rows, "is.operating_income", "Operating income", "income_statement", aliases=("Operating Income",), forecast="derived_identity", dependencies=("is.gross_profit", "is.sga", "is.research_development", "is.other_operating_expense"))
    _line(rows, "is.interest_expense", "Interest expense", "income_statement", aliases=("Interest Expense",), sign="negative", drivers=("scheduled_debt_issuance", "scheduled_debt_repayment", "cost_of_debt"))
    _line(rows, "is.interest_income", "Interest income", "income_statement", aliases=("Interest and Invest. Income",), drivers=("minimum_cash", "cash_yield"))
    _line(rows, "is.net_interest_expense", "Net interest expense (income)", "income_statement", aliases=("Net Interest Exp.",), sign="signed", required=False, forecast="derived_identity", dependencies=("is.interest_expense", "is.interest_income"))
    _line(rows, "is.affiliates_income", "Income from affiliates", "income_statement", aliases=("Income / (Loss) from Affiliates",), required=False)
    _line(rows, "is.fx_gain_loss", "Currency gains (losses)", "income_statement", aliases=("Currency Exchange Gains (Loss)",), required=False)
    _line(rows, "is.other_nonoperating", "Other non-operating income", "income_statement", aliases=("Other Non-Operating Inc. (Exp.)",), required=False, drivers=("other_nonoperating_percent_revenue",))
    _line(rows, "is.ebt_ex_unusual", "EBT excluding unusual items", "income_statement", aliases=("EBT Excl Unusual Items",), required=False)
    _line(rows, "is.unusual_items", "Unusual items", "income_statement", aliases=("Unusual Items, Total (Supple)",), required=False)
    _line(rows, "is.ebt", "Earnings before tax", "income_statement", aliases=("EBT Incl Unusual Items",), dependencies=("is.operating_income", "is.interest_expense", "is.interest_income", "is.other_nonoperating"))
    _line(rows, "is.income_tax", "Income tax expense", "income_statement", aliases=("Income Tax Expense",), sign="negative", drivers=("effective_tax_rate",))
    _line(rows, "is.net_income_company", "Net income to company", "income_statement", aliases=("Net Income to Company",), forecast="derived_identity", dependencies=("is.ebt", "is.income_tax"))
    _line(rows, "is.minority_earnings", "Minority interest in earnings", "income_statement", aliases=("Minority Int. in Earnings",), sign="negative", required=False, drivers=("minority_earnings_percent",))
    _line(rows, "is.net_income_parent", "Net income to parent", "income_statement", aliases=("Net Income to Parent",), forecast="derived_identity", dependencies=("is.net_income_company", "is.minority_earnings"))
    _line(rows, "is.preferred_dividends", "Preferred dividends", "income_statement", aliases=("Pref. Dividends and Other Adj.",), sign="negative", required=False, drivers=("preferred_dividends",))
    _line(rows, "is.net_income_common", "Net income to common", "income_statement", aliases=("NI to Common Incl Extra Items",), forecast="derived_identity", dependencies=("is.net_income_parent", "is.preferred_dividends"))
    _line(rows, "is.ebitda", "EBITDA", "income_statement", aliases=("EBITDA",), forecast="derived_identity", drivers=("da_percent_revenue",))
    _line(rows, "is.ebit", "EBIT", "income_statement", aliases=("EBIT",), forecast="dependency_link", dependencies=("is.operating_income",))
    _line(rows, "is.stock_based_compensation", "Stock-based compensation", "income_statement", aliases=("Stock-Based Comp., Total",), sign="negative", required=False, drivers=("stock_comp_percent_revenue",))
    _line(rows, "is.da_for_ebitda", "D&A for EBITDA", "income_statement", aliases=("D&A For EBITDA",), required=False)

    # Cash flow statement.
    _line(rows, "cf.net_income", "Net income", "cash_flow", aliases=("Net Income",), forecast="dependency_link", dependencies=("is.net_income_company",))
    _line(rows, "cf.da", "Depreciation and amortization", "cash_flow", aliases=("Depreciation & Amort., Total",), drivers=("da_percent_revenue",))
    _line(rows, "cf.intangible_amortization", "Intangible amortization", "cash_flow", aliases=("Amort. of Goodwill and Intangibles",), required=False, drivers=("intangible_amortization_percent_revenue",))
    _line(rows, "cf.gain_sale_assets", "Gain/(loss) adjustment on sale of assets", "cash_flow", aliases=("(Gain) Loss From Sale Of Asset",), sign="signed", required=False, forecast="derived_cash_flow", drivers=("asset_sale_proceeds", "asset_cost_disposals", "asset_disposal_accumulated_depreciation"))
    _line(rows, "cf.gain_sale_investments", "Gain on sale of investments", "cash_flow", aliases=("(Gain) Loss On Sale Of Invest.",), required=False)
    _line(rows, "cf.asset_writedown_restructuring", "Asset writedown and restructuring", "cash_flow", aliases=("Asset Writedown & Restructuring Costs",), required=False)
    _line(rows, "cf.credit_loss_provision", "Provision for credit losses", "cash_flow", aliases=("Provision for Credit Losses",), required=False)
    _line(rows, "cf.stock_based_compensation", "Stock-based compensation", "cash_flow", aliases=("Stock-Based Compensation",), aggregation="direct", forecast="dependency_link", dependencies=("is.stock_based_compensation",), required=False)
    _line(rows, "cf.change_accounts_receivable", "Change in accounts receivable", "cash_flow", aliases=("Change in Acc. Receivable",), drivers=("dso",))
    _line(rows, "cf.change_inventory", "Change in inventory", "cash_flow", aliases=("Change In Inventories",), drivers=("dio",))
    _line(rows, "cf.change_accounts_payable", "Change in accounts payable", "cash_flow", aliases=("Change in Acc. Payable",), drivers=("dpo",))
    _line(rows, "cf.change_deferred_revenue", "Change in deferred revenue", "cash_flow", aliases=("Change in Unearned Rev.",), required=False, drivers=("deferred_revenue_percent_revenue",))
    _line(rows, "cf.change_income_taxes", "Change in income taxes payable", "cash_flow", aliases=("Change in Inc. Taxes",), required=False, drivers=("effective_tax_rate", "cash_tax_rate", "deferred_tax_assets_percent_revenue", "deferred_tax_liabilities_percent_revenue"))
    _line(rows, "cf.change_deferred_taxes", "Change in deferred taxes", "cash_flow", aliases=("Change in Def. Taxes",), required=False, drivers=("deferred_tax_assets_percent_revenue", "deferred_tax_liabilities_percent_revenue"))
    _line(rows, "cf.change_other_operating_assets", "Change in other operating assets", "cash_flow", aliases=("Change In Other Net Operating Assets",), required=False, drivers=("prepaids_percent_revenue", "other_current_assets_percent_revenue", "accrued_expenses_percent_revenue", "other_current_liabilities_percent_revenue"))
    _line(rows, "cf.other_operating_activities", "Other operating activities", "cash_flow", aliases=("Other Operating Activities",), required=False, drivers=("other_operating_cash_flow",))
    _line(rows, "cf.cash_from_operations", "Cash from operations", "cash_flow", aliases=("Cash from Ops.",), forecast="derived_cash_flow", dependencies=("cf.net_income", "cf.da", "cf.gain_sale_assets", "cf.stock_based_compensation", "cf.change_accounts_receivable", "cf.change_inventory", "cf.change_accounts_payable", "cf.change_deferred_revenue", "cf.change_income_taxes", "cf.change_deferred_taxes", "cf.change_other_operating_assets", "cf.other_operating_activities"))
    _line(rows, "cf.capex", "Capital expenditures", "cash_flow", aliases=("Capital Expenditure",), sign="negative", drivers=("capex_percent_revenue",))
    _line(rows, "cf.sale_ppe", "Sale of PP&E", "cash_flow", aliases=("Sale of Property, Plant, and Equipment",), required=False, drivers=("asset_sale_proceeds",))
    _line(rows, "cf.acquisitions", "Cash acquisitions", "cash_flow", aliases=("Cash Acquisitions",), sign="negative", required=False, drivers=("acquisition_spend",))
    _line(rows, "cf.divestitures", "Divestitures", "cash_flow", aliases=("Divestitures",), required=False, forecast="constant_zero")
    _line(rows, "cf.investments", "Net investment purchases", "cash_flow", aliases=("Invest. in Marketable & Equity Sec.",), required=False, drivers=("net_investment_purchases",))
    _line(rows, "cf.other_investing", "Other investing activities", "cash_flow", aliases=("Other Investing Activities",), required=False, drivers=("other_investing_cash_flow",))
    _line(rows, "cf.cash_from_investing", "Cash from investing", "cash_flow", aliases=("Cash from Investing",), forecast="derived_cash_flow", dependencies=("cf.capex", "cf.sale_ppe", "cf.acquisitions", "cf.divestitures", "cf.investments", "cf.other_investing"))
    _line(rows, "cf.debt_issued", "Debt issued", "cash_flow", aliases=("Total Debt Issued",), required=False, drivers=("scheduled_debt_issuance",))
    _line(rows, "cf.debt_repaid", "Debt repaid", "cash_flow", aliases=("Total Debt Repaid",), sign="negative", required=False, drivers=("scheduled_debt_repayment",))
    _line(rows, "cf.common_stock_issued", "Common stock issued", "cash_flow", aliases=("Issuance of Common Stock",), required=False, drivers=("common_stock_issuance",))
    _line(rows, "cf.share_repurchase", "Share repurchases", "cash_flow", aliases=("Repurchase of Common",), sign="negative", required=False, drivers=("buyback_amount",))
    _line(rows, "cf.dividends_paid", "Dividends paid", "cash_flow", aliases=("Total Dividends Paid",), sign="negative", required=False, drivers=("dividend_payout", "preferred_dividends"))
    _line(rows, "cf.other_financing", "Other financing activities", "cash_flow", aliases=("Other Financing Activities",), required=False, drivers=("other_financing_cash_flow",))
    _line(rows, "cf.cash_from_financing", "Cash from financing", "cash_flow", aliases=("Cash from Financing",), forecast="derived_cash_flow", dependencies=("cf.debt_issued", "cf.debt_repaid", "cf.common_stock_issued", "cf.share_repurchase", "cf.dividends_paid", "cf.other_financing"))
    _line(rows, "cf.fx_adjustment", "FX adjustment", "cash_flow", aliases=("Foreign Exchange Rate Adj.",), required=False, drivers=("fx_cash_adjustment",))
    _line(rows, "cf.misc_adjustment", "Miscellaneous cash adjustment", "cash_flow", aliases=("Misc. Cash Flow Adj.",), required=False, drivers=("misc_cash_adjustment",))
    _line(rows, "cf.net_change_cash", "Net change in cash", "cash_flow", aliases=("Net Change in Cash",), forecast="derived_cash_flow", dependencies=("cf.cash_from_operations", "cf.cash_from_investing", "cf.cash_from_financing", "cf.fx_adjustment", "cf.misc_adjustment"))
    _line(rows, "cf.levered_fcf", "Levered free cash flow (FCFE)", "cash_flow", aggregation="derived_identity", required=False, forecast="derived_cash_flow", dependencies=("cf.cash_from_operations", "cf.capex", "cf.debt_issued", "cf.debt_repaid"))
    _line(rows, "cf.unlevered_fcf", "Unlevered free cash flow (FCFF)", "cash_flow", aggregation="derived_identity", required=False, forecast="derived_cash_flow", dependencies=("cf.cash_from_operations", "cf.capex", "cf.net_income", "is.ebit", "is.ebt", "is.income_tax"))

    # Balance sheet.
    _line(rows, "bs.cash", "Cash and equivalents", "balance_sheet", aliases=("Cash And Equivalents",), drivers=("minimum_cash",))
    _line(rows, "bs.short_term_investments", "Short-term investments", "balance_sheet", aliases=("Short Term Investments",), required=False, forecast="roll_forward", drivers=("net_investment_purchases",))
    _line(rows, "bs.cash_and_investments", "Cash and short-term investments", "balance_sheet", aliases=("Total Cash & ST Investments",), forecast="derived_identity", dependencies=("bs.cash", "bs.short_term_investments"))
    _line(rows, "bs.accounts_receivable", "Accounts receivable", "balance_sheet", aliases=("Accounts Receivable",), drivers=("dso",))
    _line(rows, "bs.other_receivables", "Other receivables", "balance_sheet", aliases=("Other Receivables",), required=False)
    _line(rows, "bs.total_receivables", "Total receivables", "balance_sheet", aliases=("Total Receivables",), dependencies=("bs.accounts_receivable", "bs.other_receivables"))
    _line(rows, "bs.inventory", "Inventory", "balance_sheet", aliases=("Inventory",), drivers=("dio",))
    _line(rows, "bs.prepaids", "Prepaid expenses", "balance_sheet", aliases=("Prepaid Exp.",), required=False, drivers=("prepaids_percent_revenue",))
    _line(rows, "bs.other_current_assets", "Other current assets", "balance_sheet", aliases=("Other Current Assets",), required=False, drivers=("other_current_assets_percent_revenue",))
    _line(rows, "bs.total_current_assets", "Total current assets", "balance_sheet", aliases=("Total Current Assets",), dependencies=("bs.cash", "bs.short_term_investments", "bs.total_receivables", "bs.inventory", "bs.prepaids", "bs.other_current_assets"))
    _line(rows, "bs.gross_ppe", "Gross PP&E", "balance_sheet", aliases=("Gross Property, Plant & Equipment",), forecast="roll_forward", drivers=("capex_percent_revenue", "asset_cost_disposals"))
    _line(rows, "bs.accumulated_depreciation", "Accumulated depreciation", "balance_sheet", aliases=("Accumulated Depreciation",), sign="negative", forecast="roll_forward", drivers=("da_percent_revenue",))
    _line(rows, "bs.net_ppe", "Net PP&E", "balance_sheet", aliases=("Net Property, Plant & Equipment",), forecast="derived_identity", dependencies=("bs.gross_ppe", "bs.accumulated_depreciation"))
    _line(rows, "bs.long_term_investments", "Long-term investments", "balance_sheet", aliases=("Long-term Investments",), required=False)
    _line(rows, "bs.long_term_receivables", "Long-term receivables", "balance_sheet", aliases=("Accounts Receivable Long-Term",), required=False)
    _line(rows, "bs.goodwill", "Goodwill", "balance_sheet", aliases=("Goodwill",), required=False, drivers=("acquisition_spend",))
    _line(rows, "bs.gross_intangibles", "Gross intangible assets", "balance_sheet", aliases=("Gross Intangible Assets",), required=False, forecast="roll_forward")
    _line(rows, "bs.accumulated_amortization", "Accumulated amortization of intangible assets", "balance_sheet", aliases=("Accumulated Amortization of Intangible Assets",), sign="negative", required=False, forecast="roll_forward", drivers=("intangible_amortization_percent_revenue",))
    _line(rows, "bs.other_intangibles", "Net other intangibles", "balance_sheet", aliases=("Other Intangibles",), required=False, forecast="derived_identity", dependencies=("bs.gross_intangibles", "bs.accumulated_amortization"))
    _line(rows, "bs.deferred_tax_assets", "Deferred tax assets", "balance_sheet", aliases=("Deferred Tax Assets, LT",), required=False, drivers=("deferred_tax_assets_percent_revenue",))
    _line(rows, "bs.other_long_term_assets", "Other long-term assets", "balance_sheet", aliases=("Other Long-Term Assets",), required=False, drivers=("other_investing_cash_flow",))
    _line(rows, "bs.total_assets", "Total assets", "balance_sheet", aliases=("Total Assets",), forecast="derived_balance_sheet", dependencies=("bs.total_current_assets", "bs.net_ppe", "bs.long_term_investments", "bs.long_term_receivables", "bs.goodwill", "bs.other_intangibles", "bs.deferred_tax_assets", "bs.other_long_term_assets"))
    _line(rows, "bs.accounts_payable", "Accounts payable", "balance_sheet", aliases=("Accounts Payable",), drivers=("dpo",))
    _line(rows, "bs.accrued_expenses", "Accrued expenses", "balance_sheet", aliases=("Accrued Exp.",), required=False, drivers=("accrued_expenses_percent_revenue",))
    _line(rows, "bs.short_term_borrowings", "Short-term borrowings", "balance_sheet", aliases=("Short-term Borrowings",), required=False, forecast="roll_forward", drivers=("scheduled_debt_issuance", "scheduled_debt_repayment"))
    _line(rows, "bs.current_long_term_debt", "Current portion of long-term debt", "balance_sheet", aliases=("Current Portion of Long Term Debt",), required=False, forecast="roll_forward", drivers=("scheduled_debt_issuance", "scheduled_debt_repayment"))
    _line(rows, "bs.current_lease_liabilities", "Current lease liabilities", "balance_sheet", aliases=("Current Portion of Leases",), required=False)
    _line(rows, "bs.income_taxes_payable", "Income taxes payable", "balance_sheet", aliases=("Curr. Income Taxes Payable",), required=False, forecast="roll_forward", drivers=("effective_tax_rate", "cash_tax_rate", "deferred_tax_assets_percent_revenue", "deferred_tax_liabilities_percent_revenue"))
    _line(rows, "bs.deferred_revenue_current", "Deferred revenue, current", "balance_sheet", aliases=("Unearned Revenue, Current",), required=False, drivers=("deferred_revenue_percent_revenue",))
    _line(rows, "bs.other_current_liabilities", "Other current liabilities", "balance_sheet", aliases=("Other Current Liabilities",), required=False, drivers=("other_current_liabilities_percent_revenue",))
    _line(rows, "bs.total_current_liabilities", "Total current liabilities", "balance_sheet", aliases=("Total Current Liabilities",), dependencies=("bs.accounts_payable", "bs.accrued_expenses", "bs.short_term_borrowings", "bs.current_long_term_debt", "bs.current_lease_liabilities", "bs.income_taxes_payable", "bs.deferred_revenue_current", "bs.other_current_liabilities"))
    _line(rows, "bs.long_term_debt", "Long-term debt", "balance_sheet", aliases=("Long-Term Debt",), forecast="roll_forward", drivers=("scheduled_debt_issuance", "scheduled_debt_repayment"))
    _line(rows, "bs.long_term_leases", "Long-term leases", "balance_sheet", aliases=("Long-Term Leases",), required=False)
    _line(rows, "bs.deferred_revenue_noncurrent", "Deferred revenue, non-current", "balance_sheet", aliases=("Unearned Revenue, Non-Current",), required=False, drivers=("deferred_revenue_percent_revenue",))
    _line(rows, "bs.pension_liability", "Pension and post-retirement liabilities", "balance_sheet", aliases=("Pension & Other Post-Retire. Benefits",), required=False)
    _line(rows, "bs.deferred_tax_liability", "Deferred tax liability", "balance_sheet", aliases=("Def. Tax Liability, Non-Curr.",), required=False, drivers=("deferred_tax_liabilities_percent_revenue",))
    _line(rows, "bs.other_noncurrent_liabilities", "Other non-current liabilities", "balance_sheet", aliases=("Other Non-Current Liabilities",), required=False, drivers=("other_operating_cash_flow",))
    _line(rows, "bs.total_liabilities", "Total liabilities", "balance_sheet", aliases=("Total Liabilities",), forecast="derived_balance_sheet", dependencies=("bs.total_current_liabilities", "bs.long_term_debt", "bs.long_term_leases", "bs.deferred_revenue_noncurrent", "bs.pension_liability", "bs.deferred_tax_liability", "bs.other_noncurrent_liabilities"))
    _line(rows, "bs.common_stock_apic", "Common stock and APIC", "balance_sheet", aliases=("Common Stock",), forecast="roll_forward", drivers=("stock_comp_percent_revenue", "common_stock_issuance", "other_financing_cash_flow"))
    _line(rows, "bs.retained_earnings", "Retained earnings", "balance_sheet", aliases=("Retained Earnings",), forecast="roll_forward", drivers=("dividend_payout", "preferred_dividends"))
    _line(rows, "bs.treasury_stock", "Treasury stock", "balance_sheet", aliases=("Treasury Stock",), sign="negative", required=False, forecast="roll_forward", drivers=("buyback_amount",))
    _line(rows, "bs.aoci", "AOCI and other", "balance_sheet", aliases=("Comprehensive Inc. and Other",), required=False, forecast="roll_forward", drivers=("fx_cash_adjustment", "misc_cash_adjustment"))
    _line(rows, "bs.total_common_equity", "Total common equity", "balance_sheet", aliases=("Total Common Equity",), dependencies=("bs.common_stock_apic", "bs.retained_earnings", "bs.treasury_stock", "bs.aoci"))
    _line(rows, "bs.minority_interest", "Minority interest", "balance_sheet", aliases=("Minority Interest",), required=False, forecast="roll_forward", drivers=("minority_earnings_percent",))
    _line(rows, "bs.total_equity", "Total equity", "balance_sheet", aliases=("Total Equity",), dependencies=("bs.total_common_equity", "bs.minority_interest"))
    _line(rows, "bs.total_liabilities_equity", "Total liabilities and equity", "balance_sheet", aliases=("Total Liabilities And Equity",), dependencies=("bs.total_liabilities", "bs.total_equity"))
    _line(rows, "bs.total_debt", "Total debt including leases", "balance_sheet", aliases=("Total Debt",), forecast="derived_identity", drivers=("scheduled_debt_issuance", "scheduled_debt_repayment"))
    _line(rows, "bs.net_debt", "Net debt including leases", "balance_sheet", aliases=("Net Debt",), required=False, forecast="derived_identity", dependencies=("bs.total_debt", "bs.cash_and_investments"))
    _line(rows, "bs.working_capital", "Working capital", "balance_sheet", aliases=("Working Capital",), required=False, forecast="derived_identity")
    _line(rows, "bs.net_working_capital", "Net working capital", "balance_sheet", aliases=("Net Working Capital",), required=False, forecast="derived_identity")

    # Working-capital schedule (derived views avoid duplicate source aliases).
    _line(rows, "wc.receivables", "Trade accounts receivable", "working_capital", aggregation="derived_identity", forecast="dependency_link", dependencies=("bs.accounts_receivable",))
    _line(rows, "wc.inventory", "Inventory", "working_capital", aggregation="derived_identity", forecast="dependency_link", dependencies=("bs.inventory",))
    _line(rows, "wc.payables", "Accounts payable", "working_capital", aggregation="derived_identity", forecast="dependency_link", dependencies=("bs.accounts_payable",))
    _line(rows, "wc.deferred_revenue", "Deferred revenue", "working_capital", aggregation="derived_identity", forecast="derived_identity", dependencies=("bs.deferred_revenue_current", "bs.deferred_revenue_noncurrent"), required=False)
    _line(rows, "wc.operating_nwc", "Operating net working capital", "working_capital", aggregation="derived_identity", forecast="working_capital_driver", dependencies=("wc.receivables", "wc.inventory", "wc.payables", "wc.deferred_revenue"), drivers=("dso", "dio", "dpo"))
    _line(rows, "wc.change_nwc", "Change in operating NWC", "working_capital", aggregation="derived_identity", forecast="period_change", dependencies=("wc.operating_nwc",))
    _line(rows, "wc.dso", "Days sales outstanding", "working_capital", aggregation="derived_ratio", forecast="scenario_driver", dependencies=("wc.receivables", "is.revenue"), drivers=("dso",), required=False)
    _line(rows, "wc.dio", "Days inventory outstanding", "working_capital", aggregation="derived_ratio", forecast="scenario_driver", dependencies=("wc.inventory", "is.cost_of_revenue"), drivers=("dio",), required=False)
    _line(rows, "wc.dpo", "Days payable outstanding", "working_capital", aggregation="derived_ratio", forecast="scenario_driver", dependencies=("wc.payables", "is.cost_of_revenue"), drivers=("dpo",), required=False)

    # PP&E and intangibles schedule.
    _line(rows, "ppe.beginning_gross_ppe", "Beginning gross PP&E", "ppe_intangibles", aggregation="derived_identity", forecast="prior_period", dependencies=("bs.gross_ppe",))
    _line(rows, "ppe.capex", "Capital expenditures (additions)", "ppe_intangibles", aggregation="derived_identity", forecast="dependency_link", dependencies=("cf.capex",))
    _line(rows, "ppe.disposals", "PP&E disposals at asset cost", "ppe_intangibles", aggregation="source_if_available", forecast="scenario_driver", drivers=("asset_cost_disposals",), required=False)
    _line(rows, "ppe.ending_gross_ppe", "Ending gross PP&E", "ppe_intangibles", aggregation="derived_identity", forecast="roll_forward", dependencies=("ppe.beginning_gross_ppe", "ppe.capex", "ppe.disposals"))
    _line(rows, "ppe.depreciation", "PP&E depreciation", "ppe_intangibles", aliases=("Depreciation (From Notes)",), aggregation="direct", forecast="dependency_link", dependencies=("cf.da", "cf.intangible_amortization"))
    _line(rows, "ppe.ending_net_ppe", "Ending net PP&E", "ppe_intangibles", aggregation="derived_identity", forecast="roll_forward", dependencies=("bs.net_ppe", "ppe.capex", "ppe.depreciation"))
    _line(rows, "ppe.goodwill", "Goodwill", "ppe_intangibles", aggregation="derived_identity", forecast="dependency_link", dependencies=("bs.goodwill",), required=False)
    _line(rows, "ppe.gross_intangibles", "Gross intangible assets", "ppe_intangibles", aggregation="derived_identity", forecast="dependency_link", dependencies=("bs.gross_intangibles",), required=False)
    _line(rows, "ppe.accumulated_amortization", "Accumulated intangible amortization", "ppe_intangibles", aggregation="derived_identity", forecast="dependency_link", dependencies=("bs.accumulated_amortization",), required=False)
    _line(rows, "ppe.amortization", "Intangible amortization", "ppe_intangibles", aggregation="derived_identity", forecast="dependency_link", dependencies=("cf.intangible_amortization",), required=False)
    _line(rows, "ppe.intangibles", "Net other intangibles", "ppe_intangibles", aggregation="derived_identity", forecast="roll_forward", dependencies=("bs.other_intangibles",), required=False)

    # Debt, cash, and interest schedule.
    _line(rows, "debt.cash", "Cash", "debt_cash_interest", aggregation="derived_identity", forecast="dependency_link", dependencies=("bs.cash",))
    _line(rows, "debt.investments", "Short and long-term investments", "debt_cash_interest", aggregation="derived_identity", forecast="derived_identity", dependencies=("bs.short_term_investments", "bs.long_term_investments"), required=False)
    _line(rows, "debt.short_term_debt", "Short-term debt", "debt_cash_interest", aggregation="derived_identity", forecast="dependency_link", dependencies=("bs.short_term_borrowings", "bs.current_long_term_debt"), required=False)
    _line(rows, "debt.long_term_debt", "Long-term debt", "debt_cash_interest", aggregation="derived_identity", forecast="dependency_link", dependencies=("bs.long_term_debt",))
    _line(rows, "debt.total_debt", "Total borrowings excluding leases", "debt_cash_interest", aggregation="derived_identity", forecast="roll_forward", dependencies=("bs.short_term_borrowings", "bs.current_long_term_debt", "bs.long_term_debt"))
    _line(rows, "debt.lease_liabilities", "Lease liabilities", "debt_cash_interest", aggregation="derived_identity", forecast="roll_forward", dependencies=("bs.current_lease_liabilities", "bs.long_term_leases"), required=False)
    _line(rows, "debt.net_debt", "Net debt", "debt_cash_interest", aggregation="derived_identity", forecast="derived_identity", dependencies=("debt.total_debt", "debt.cash", "debt.investments"), required=False)
    _line(rows, "debt.interest_expense", "Interest expense", "debt_cash_interest", sign="negative", aggregation="derived_identity", forecast="average_balance", dependencies=("is.interest_expense", "debt.total_debt"))
    _line(rows, "debt.interest_income", "Interest income", "debt_cash_interest", aggregation="derived_identity", forecast="average_balance", dependencies=("is.interest_income", "debt.cash"), required=False)

    # Capital allocation schedule.
    _line(rows, "capital.cfo", "Cash from operations", "capital_allocation", aggregation="derived_identity", forecast="dependency_link", dependencies=("cf.cash_from_operations",))
    _line(rows, "capital.capex", "Capital expenditures", "capital_allocation", sign="negative", aggregation="derived_identity", forecast="dependency_link", dependencies=("cf.capex",))
    _line(rows, "capital.acquisitions", "Acquisitions", "capital_allocation", sign="negative", aggregation="derived_identity", forecast="dependency_link", dependencies=("cf.acquisitions",), required=False)
    _line(rows, "capital.dividends", "Dividends", "capital_allocation", sign="negative", aggregation="derived_identity", forecast="dependency_link", dependencies=("cf.dividends_paid",), required=False)
    _line(rows, "capital.buybacks", "Share repurchases", "capital_allocation", sign="negative", aggregation="derived_identity", forecast="dependency_link", dependencies=("cf.share_repurchase",), required=False)
    _line(rows, "capital.debt_issuance", "Debt issuance", "capital_allocation", aggregation="derived_identity", forecast="dependency_link", dependencies=("cf.debt_issued",), required=False)
    _line(rows, "capital.debt_repayment", "Debt repayment", "capital_allocation", sign="negative", aggregation="derived_identity", forecast="dependency_link", dependencies=("cf.debt_repaid",), required=False)
    _line(rows, "capital.post_allocation_cash", "Post-allocation cash flow", "capital_allocation", aggregation="derived_identity", forecast="derived_identity", dependencies=("capital.cfo", "capital.capex", "capital.acquisitions", "capital.dividends", "capital.buybacks", "capital.debt_issuance", "capital.debt_repayment"))

    # Tax schedule.
    _line(rows, "tax.pretax_income", "Pretax income", "taxes", aggregation="derived_identity", forecast="dependency_link", dependencies=("is.ebt",))
    _line(rows, "tax.income_tax_expense", "Income tax expense", "taxes", sign="negative", aggregation="derived_identity", forecast="dependency_link", dependencies=("is.income_tax",))
    _line(rows, "tax.effective_rate", "Effective tax rate", "taxes", aliases=("Effective Tax Rate (%)",), aggregation="direct", forecast="scenario_driver", dependencies=("tax.pretax_income", "tax.income_tax_expense"), drivers=("effective_tax_rate",))
    _line(rows, "tax.cash_taxes", "Cash taxes paid", "taxes", aliases=("Cash Taxes Paid",), sign="negative", required=False, drivers=("cash_tax_rate",))
    _line(rows, "tax.deferred_taxes", "Deferred income taxes", "taxes", aliases=("Deferred Income Taxes, Total",), required=False)
    _line(rows, "tax.nopat", "NOPAT", "taxes", aggregation="derived_identity", forecast="derived_identity", dependencies=("is.ebit", "tax.effective_rate"), drivers=("nopat_tax_rate",))

    # Shares and EPS schedule.
    _line(rows, "shares.basic_weighted_average", "Weighted average basic shares", "shares_eps", aliases=("Weighted Avg. Basic Shares Out.",), drivers=("buyback_amount", "common_stock_issuance", "average_share_price"))
    _line(rows, "shares.diluted_weighted_average", "Weighted average diluted shares", "shares_eps", aliases=("Weighted Avg. Diluted Shares Out.",), drivers=("incremental_diluted_shares",))
    _line(rows, "shares.period_end", "Period-end shares", "shares_eps", aliases=("Total Shares Out. on Balance Sheet Date",), drivers=("buyback_amount", "common_stock_issuance", "average_share_price"))
    _line(rows, "shares.basic_eps", "Basic EPS", "shares_eps", aliases=("Basic EPS",), dependencies=("is.net_income_common", "shares.basic_weighted_average"))
    _line(rows, "shares.diluted_eps", "Diluted EPS", "shares_eps", aliases=("Diluted EPS",), dependencies=("is.net_income_common", "shares.diluted_weighted_average"))
    _line(rows, "shares.dividend_per_share", "Declared dividend per share", "shares_eps", aliases=("Dividends per Share",), required=False, forecast="source_or_approved_declaration", missing=AvailabilityStatus.PM_REQUIRED)
    _line(rows, "shares.cash_dividend_per_share", "Cash common dividends per weighted-average basic share", "shares_eps", aggregation="derived_identity", forecast="derived_identity", dependencies=("cf.dividends_paid", "is.preferred_dividends", "shares.basic_weighted_average"), required=False)
    _line(rows, "shares.options_incremental", "Incremental option shares", "shares_eps", aggregation="source_if_available", forecast="source_or_pm", required=False, missing=AvailabilityStatus.PM_REQUIRED)
    _line(rows, "shares.rsu_incremental", "Incremental RSU shares", "shares_eps", aggregation="source_if_available", forecast="source_or_pm", required=False, missing=AvailabilityStatus.PM_REQUIRED)
    _line(rows, "shares.psu_incremental", "Incremental PSU shares", "shares_eps", aggregation="source_if_available", forecast="source_or_pm", required=False, missing=AvailabilityStatus.PM_REQUIRED)
    _line(rows, "shares.convertible_incremental", "Incremental convertible shares", "shares_eps", aggregation="source_if_available", forecast="source_or_pm", required=False, missing=AvailabilityStatus.PM_REQUIRED)
    _line(rows, "shares.fully_diluted", "Current fully diluted shares", "shares_eps", aggregation="derived_identity", forecast="source_or_pm", dependencies=("shares.period_end", "shares.options_incremental", "shares.rsu_incremental", "shares.psu_incremental", "shares.convertible_incremental"), required=False, missing=AvailabilityStatus.PM_REQUIRED)
    _line(rows, "shares.stock_compensation", "Stock-based compensation", "shares_eps", sign="negative", aggregation="derived_identity", forecast="dependency_link", dependencies=("is.stock_based_compensation",), required=False)
    _line(rows, "shares.dilution", "Incremental diluted weighted-average shares", "shares_eps", aggregation="derived_identity", forecast="derived_identity", dependencies=("shares.diluted_weighted_average", "shares.basic_weighted_average"), drivers=("incremental_diluted_shares",), required=False)

    # Source-dependent modules remain explicit rather than guessed.
    for key, label in (
        ("segment.revenue", "Segment revenue"),
        ("segment.operating_income", "Segment operating income"),
        ("segment.assets", "Segment assets"),
        ("segment.kpi", "Segment operating KPI"),
    ):
        _line(
            rows,
            key,
            label,
            "segment_build",
            aggregation="source_dimension",
            forecast="segment_driver",
            missing=AvailabilityStatus.PM_REQUIRED,
        )

    for key, label in (
        ("consensus.revenue", "Consensus revenue"),
        ("consensus.ebit", "Consensus EBIT"),
        ("consensus.eps", "Consensus EPS"),
    ):
        _line(
            rows,
            key,
            label,
            "consensus_bridge",
            required=False,
            aggregation="source_estimate",
            forecast="reference_only",
        )

    return validate_line_item_registry(tuple(rows))


def _alias_map(registry: Sequence[LineItemSpec]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for spec in validate_line_item_registry(registry):
        for alias in spec.source_mappings:
            cleaned = _clean_alias(alias)
            owner = mapping.get(cleaned)
            if owner is not None and owner != spec.canonical_key:
                raise AmbiguousLineItemMappingError(
                    f"exact source alias {cleaned!r} maps to both {owner} and "
                    f"{spec.canonical_key}"
                )
            mapping[cleaned] = spec.canonical_key
    return mapping


def classify_source_records(
    records: Iterable[Mapping[str, Any]],
    *,
    registry: Sequence[LineItemSpec] | None = None,
) -> tuple[SourceRowClassification, ...]:
    """Classify every source fact without dropping duplicate logical rows."""
    specs = professional_line_item_registry() if registry is None else validate_line_item_registry(registry)
    aliases = _alias_map(specs)
    output: list[SourceRowClassification] = []
    for record in records:
        sheet = _clean_alias(record.get("sheet_name"))
        row_index = int(record.get("row_index") or 0)
        row_label = _clean_alias(record.get("row_label"))
        raw_column = record.get("column_index")
        column_index = int(raw_column) if raw_column not in (None, "") else None
        canonical_key: str | None = None
        if sheet in REFERENCE_ONLY_SHEETS:
            disposition = RowDisposition.REFERENCE_ONLY
            reason = "reference_sheet_not_primary_statement_source"
        elif sheet != PRIMARY_STATEMENT_SHEET:
            disposition = RowDisposition.UNMAPPED
            reason = "unsupported_primary_mapping_sheet"
        elif row_label in aliases:
            candidate_key = aliases[row_label]
            row_role = SOURCE_ALIAS_ROW_ROLES.get((candidate_key, row_label))
            if row_role is not None and not (row_role[0] <= row_index <= row_role[1]):
                disposition = RowDisposition.UNMAPPED
                reason = "source_row_role_mismatch"
            else:
                disposition = RowDisposition.MAPPED
                canonical_key = candidate_key
                reason = "exact_alias_match"
        else:
            disposition = RowDisposition.UNMAPPED
            reason = "no_exact_alias_match"
        output.append(
            SourceRowClassification(
                sheet_name=sheet,
                row_index=row_index,
                row_label=row_label,
                column_index=column_index,
                disposition=disposition,
                canonical_key=canonical_key,
                reason=reason,
            )
        )
    return tuple(output)


def build_line_item_coverage(
    records: Iterable[Mapping[str, Any]],
    *,
    registry: Sequence[LineItemSpec] | None = None,
) -> CoverageReport:
    """Resolve each registry line to direct, derived, or typed missing state."""
    record_list = list(records)
    specs = professional_line_item_registry() if registry is None else validate_line_item_registry(registry)
    classifications = classify_source_records(record_list, registry=specs)

    mapped_records: dict[str, list[tuple[SourceRowClassification, Mapping[str, Any]]]] = {}
    for classification, record in zip(classifications, record_list, strict=True):
        if classification.disposition is RowDisposition.MAPPED and classification.canonical_key:
            mapped_records.setdefault(classification.canonical_key, []).append((classification, record))

    spec_by_key = {spec.canonical_key: spec for spec in specs}
    resolution_cache: dict[str, LineCoverage] = {}
    resolving: set[str] = set()

    def resolve(key: str) -> LineCoverage:
        cached = resolution_cache.get(key)
        if cached is not None:
            return cached
        if key in resolving:  # validate_line_item_registry should make this unreachable.
            raise InvalidLineItemRegistryError(f"dependency cycle while resolving {key}")
        resolving.add(key)
        spec = spec_by_key[key]
        source_entries = mapped_records.get(key, [])
        source_rows = tuple(
            sorted({(entry.sheet_name, entry.row_index) for entry, _ in source_entries})
        )
        has_value = any(record.get("value_num") is not None for _, record in source_entries)
        if has_value:
            coverage = LineCoverage(
                canonical_key=key,
                display_label=spec.display_label,
                statement_or_schedule=spec.statement_or_schedule,
                required=spec.required,
                material=spec.material,
                resolution=CoverageResolution.DIRECT,
                state=_available(),
                source_rows=source_rows,
            )
        else:
            dependencies = tuple(resolve(dependency) for dependency in spec.dependencies)
            if dependencies and all(
                item.state.status is AvailabilityStatus.AVAILABLE for item in dependencies
            ):
                coverage = LineCoverage(
                    canonical_key=key,
                    display_label=spec.display_label,
                    statement_or_schedule=spec.statement_or_schedule,
                    required=spec.required,
                    material=spec.material,
                    resolution=CoverageResolution.DERIVED,
                    state=_available(),
                    source_rows=source_rows,
                )
            else:
                reason_code = (
                    "historical_source_values_missing"
                    if source_entries
                    else "historical_source_mapping_missing"
                )
                coverage = LineCoverage(
                    canonical_key=key,
                    display_label=spec.display_label,
                    statement_or_schedule=spec.statement_or_schedule,
                    required=spec.required,
                    material=spec.material,
                    resolution=CoverageResolution.MISSING,
                    state=_missing_state(
                        spec,
                        reason_code,
                        f"No usable historical source value is available for {key}.",
                    ),
                    source_rows=source_rows,
                )
        resolving.remove(key)
        resolution_cache[key] = coverage
        return coverage

    line_coverage = tuple(resolve(spec.canonical_key) for spec in specs)
    required = tuple(item for item in line_coverage if item.required)
    available_count = sum(
        item.state.status is AvailabilityStatus.AVAILABLE for item in required
    )
    counts = Counter(item.disposition for item in classifications)
    normalized_counts = {disposition: counts.get(disposition, 0) for disposition in RowDisposition}
    return CoverageReport(
        registry_version=REGISTRY_VERSION,
        classifications=classifications,
        line_coverage=line_coverage,
        classification_counts=normalized_counts,
        required_line_count=len(required),
        required_available_count=available_count,
        required_gap_count=len(required) - available_count,
    )


__all__ = [
    "AmbiguousLineItemMappingError",
    "CoverageReport",
    "CoverageResolution",
    "InvalidLineItemRegistryError",
    "LineCoverage",
    "REGISTRY_VERSION",
    "RowDisposition",
    "SOURCE_ALIAS_ROW_ROLES",
    "SourceRowClassification",
    "build_line_item_coverage",
    "classify_source_records",
    "professional_line_item_registry",
    "validate_line_item_registry",
]
