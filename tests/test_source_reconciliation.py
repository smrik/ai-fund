from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.contracts.pm_decision_queue import PMDecisionQueueItem
from src.stage_00_data.source_reconciliation import (
    ExpectedSourceQuantity,
    SourceAmount,
    assess_statement_readiness,
    canonical_statement_key,
    reconcile_persisted_statement_facts,
    reconcile_statement_sources,
    source_amount_from_statement_fact,
    validate_balance_sheet_identity,
    validate_calculation_rollup,
    validate_cash_bridge,
)


def _amount(
    *,
    source: str,
    value: float,
    scale_factor: float,
    canonical_key: str = "revenue",
    unit: str = "USD",
    currency: str | None = "USD",
    period_end: str = "2025-06-30",
    fact_id: str | None = None,
) -> SourceAmount:
    return SourceAmount(
        ticker="MSFT",
        source=source,
        statement="IncomeStatement",
        canonical_key=canonical_key,
        value=value,
        scale_factor=scale_factor,
        unit=unit,
        currency=currency,
        period_end=period_end,
        period_kind="annual",
        fact_id=fact_id or f"{source}:{canonical_key}",
        source_locator=f"{source}.example/{canonical_key}",
    )


def _expected(amount: SourceAmount) -> ExpectedSourceQuantity:
    return ExpectedSourceQuantity(
        ticker=amount.ticker,
        statement=amount.statement,
        canonical_key=amount.canonical_key,
        period_start=amount.period_start,
        period_end=amount.period_end,
        period_kind=amount.period_kind,
    )


def test_reconciliation_compares_currency_values_in_common_scale():
    xbrl = _amount(
        source="sec_xbrl_companyfacts_v3",
        value=281_724_000_000.0,
        scale_factor=1.0,
    )
    ciq = _amount(
        source="ciq_workbook_v1",
        value=281_724.0,
        scale_factor=1_000_000.0,
    )

    result = reconcile_statement_sources(
        [xbrl],
        [ciq],
        expected_quantities=[_expected(xbrl)],
    )

    assert result.status == "pass"
    assert result.decision_grade
    assert len(result.comparisons) == 1
    comparison = result.comparisons[0]
    assert comparison.status == "matched"
    assert comparison.xbrl_base_value == 281_724_000_000.0
    assert comparison.ciq_base_value == 281_724_000_000.0
    assert comparison.difference == 0.0
    assert result.findings == ()


def test_zero_ciq_da_against_nonzero_xbrl_is_a_queue_ready_blocker():
    common = {
        "ticker": "MSFT",
        "statement": "CashFlowStatement",
        "label": "Depreciation and amortization",
        "unit": "USD",
        "currency": "USD",
        "period_end": "2025-06-30",
        "period_start": "2024-07-01",
        "period_kind": "ltm",
        "dimensions": {},
    }
    xbrl = source_amount_from_statement_fact(
        {
            **common,
            "source": "sec_xbrl_companyfacts_v3",
            "concept": "us-gaap:DepreciationDepletionAndAmortization",
            "numeric_value": 22_000_000.0,
            "scale_factor": 1.0,
            "fact_id": "xbrl:da",
            "source_locator": "sec.example/da",
            "filing_date": "2025-07-30",
        }
    )
    ciq = source_amount_from_statement_fact(
        {
            **common,
            "source": "ciq_workbook_v1",
            "concept": "da",
            "numeric_value": 0.0,
            "scale_factor": 1_000_000.0,
            "fact_id": "ciq:da-zero",
            "source_locator": "MSFT.xlsx#da",
        }
    )

    result = reconcile_statement_sources([xbrl], [ciq])

    assert result.status == "review_required"
    assert not result.decision_grade
    assert result.comparisons[0].status == "material_disagreement"
    assert result.comparisons[0].tolerance == 1_000_000.0
    finding = result.findings[0]
    assert finding.blocking
    assert finding.observed_values["ciq_workbook_v1"] == 0.0
    queue_payload = finding.as_queue_payload()
    queue_item = PMDecisionQueueItem.model_validate(queue_payload)
    assert queue_item.item_type.value == "advisory_finding"
    assert queue_item.evidence_anchor_ids == ["xbrl:da", "ciq:da-zero"]
    assert queue_item.metadata["blocking"]


def test_balance_sheet_identity_and_cash_bridge_return_typed_readiness():
    assets = _amount(
        source="sec_xbrl_companyfacts_v3",
        value=512_000_000_000.0,
        scale_factor=1.0,
        canonical_key="assets",
        fact_id="xbrl:assets",
    )
    liabilities = _amount(
        source="sec_xbrl_companyfacts_v3",
        value=243_000_000_000.0,
        scale_factor=1.0,
        canonical_key="liabilities",
        fact_id="xbrl:liabilities",
    )
    equity = _amount(
        source="sec_xbrl_companyfacts_v3",
        value=269_000_000_000.0,
        scale_factor=1.0,
        canonical_key="equity",
        fact_id="xbrl:equity",
    )
    balance_check = validate_balance_sheet_identity(
        assets=assets,
        liabilities=liabilities,
        equity=equity,
    )

    beginning_cash = _amount(
        source="sec_xbrl_companyfacts_v3",
        value=75_000_000_000.0,
        scale_factor=1.0,
        canonical_key="cash",
        fact_id="xbrl:cash-beginning",
        period_end="2024-06-30",
    )
    net_change = _amount(
        source="sec_xbrl_companyfacts_v3",
        value=10_000_000_000.0,
        scale_factor=1.0,
        canonical_key="net_change_in_cash",
        fact_id="xbrl:cash-change",
    )
    ending_cash = _amount(
        source="sec_xbrl_companyfacts_v3",
        value=85_000_000_000.0,
        scale_factor=1.0,
        canonical_key="cash",
        fact_id="xbrl:cash-ending",
    )
    cash_check = validate_cash_bridge(
        beginning_cash=beginning_cash,
        net_change=net_change,
        ending_cash=ending_cash,
    )

    assert balance_check.check_name == "balance_sheet_identity"
    assert balance_check.status == "pass"
    assert balance_check.ready
    assert balance_check.finding is None
    assert cash_check.check_name == "cash_flow_to_cash_bridge"
    assert cash_check.status == "pass"
    assert cash_check.ready
    assert cash_check.finding is None


def test_available_source_calculation_rollup_fails_closed():
    parent = _amount(
        source="sec_xbrl_companyfacts_v3",
        value=100_000_000.0,
        scale_factor=1.0,
        canonical_key="operating_cash_flow",
        fact_id="xbrl:cfo",
    )
    components = [
        _amount(
            source="sec_xbrl_companyfacts_v3",
            value=80_000_000.0,
            scale_factor=1.0,
            canonical_key="net_income",
            fact_id="xbrl:net-income",
        ),
        _amount(
            source="sec_xbrl_companyfacts_v3",
            value=10_000_000.0,
            scale_factor=1.0,
            canonical_key="da",
            fact_id="xbrl:da",
        ),
    ]

    check = validate_calculation_rollup(parent=parent, components=components)

    assert check.check_name == "source_calculation_rollup"
    assert check.status == "fail"
    assert not check.ready
    assert check.difference == 10_000_000.0
    assert check.finding is not None
    assert check.finding.blocking
    assert check.finding.source_fact_ids == (
        "xbrl:cfo",
        "xbrl:net-income",
        "xbrl:da",
    )


def test_statement_readiness_requires_reconciled_sources_checks_and_ltm():
    xbrl = _amount(
        source="sec_xbrl_companyfacts_v3",
        value=100_000_000.0,
        scale_factor=1.0,
    )
    ciq = _amount(
        source="ciq_workbook_v1",
        value=100.0,
        scale_factor=1_000_000.0,
    )
    source_result = reconcile_statement_sources(
        [xbrl],
        [ciq],
        expected_quantities=[_expected(xbrl)],
    )
    assets = _amount(
        source="sec_xbrl_companyfacts_v3",
        value=200_000_000.0,
        scale_factor=1.0,
        canonical_key="assets",
        fact_id="xbrl:assets",
    )
    liabilities_and_equity = _amount(
        source="sec_xbrl_companyfacts_v3",
        value=200_000_000.0,
        scale_factor=1.0,
        canonical_key="liabilities_and_equity",
        fact_id="xbrl:liabilities-and-equity",
    )
    balance_check = validate_balance_sheet_identity(
        assets=assets,
        liabilities_and_equity=liabilities_and_equity,
    )
    cash_check = validate_cash_bridge(
        beginning_cash=_amount(
            source="sec_xbrl_companyfacts_v3",
            value=50_000_000.0,
            scale_factor=1.0,
            canonical_key="cash",
            fact_id="xbrl:cash-start",
        ),
        net_change=_amount(
            source="sec_xbrl_companyfacts_v3",
            value=10_000_000.0,
            scale_factor=1.0,
            canonical_key="net_change_in_cash",
            fact_id="xbrl:cash-change",
        ),
        ending_cash=_amount(
            source="sec_xbrl_companyfacts_v3",
            value=60_000_000.0,
            scale_factor=1.0,
            canonical_key="cash",
            fact_id="xbrl:cash-end",
        ),
    )

    ready = assess_statement_readiness(
        source_reconciliation=source_result,
        checks=[balance_check, cash_check],
        annual_period_count=5,
        ltm_status="constructed",
    )
    no_ltm = assess_statement_readiness(
        source_reconciliation=source_result,
        checks=[balance_check, cash_check],
        annual_period_count=5,
        ltm_status="not_available",
    )

    assert ready.status == "decision_grade"
    assert ready.decision_grade
    assert ready.reason_codes == ()
    assert no_ltm.status == "provisional"
    assert not no_ltm.decision_grade
    assert "ltm_not_ready" in no_ltm.reason_codes


def test_source_tolerance_is_inclusive_at_pm_boundary():
    xbrl = _amount(
        source="sec_xbrl_companyfacts_v3",
        value=10_000_000_000.0,
        scale_factor=1.0,
    )
    at_boundary = _amount(
        source="ciq_workbook_v1",
        value=10_005_002_501.250626,
        scale_factor=1.0,
        fact_id="ciq:boundary",
    )
    outside = _amount(
        source="ciq_workbook_v1",
        value=10_005_002_502.0,
        scale_factor=1.0,
        fact_id="ciq:outside",
    )

    passing = reconcile_statement_sources([xbrl], [at_boundary])
    failing = reconcile_statement_sources([xbrl], [outside])

    assert passing.comparisons[0].status == "matched"
    assert failing.comparisons[0].status == "material_disagreement"


def test_persisted_fact_reconciliation_accounts_for_every_overlap():
    common = {
        "ticker": "IBM",
        "statement": "CashFlowStatement",
        "label": "Depreciation and amortization",
        "unit": "USD",
        "currency": "USD",
        "period_end": "2025-12-31",
        "period_kind": "ltm",
        "dimensions": {},
    }
    facts = [
        {
            **common,
            "source": "sec_xbrl_companyfacts_v3",
            "concept": "us-gaap:DepreciationDepletionAndAmortization",
            "numeric_value": 5_000_000.0,
            "scale_factor": 1.0,
            "fact_id": "xbrl:ibm:da",
            "source_locator": "sec.example/ibm-da",
        },
        {
            **common,
            "source": "ciq_workbook_v1",
            "concept": "da",
            "numeric_value": 5.0,
            "scale_factor": 1_000_000.0,
            "fact_id": "ciq:ibm:da",
            "source_locator": "IBM.xlsx#da",
        },
        {
            **common,
            "source": "ciq_workbook_v1",
            "concept": "da",
            "numeric_value": 0.0,
            "scale_factor": 1_000_000.0,
            "fact_id": "ciq:ibm:da-zero",
            "source_locator": "IBM.xlsx#da-zero",
        },
    ]

    result = reconcile_persisted_statement_facts(facts)

    assert result.overlap_count == 2
    assert [item.status for item in result.comparisons] == [
        "matched",
        "material_disagreement",
    ]
    assert result.findings[0].source_fact_ids == (
        "xbrl:ibm:da",
        "ciq:ibm:da-zero",
    )


def test_reconciliation_does_not_match_incomplete_currency_or_period_metadata():
    xbrl = SourceAmount(
        ticker="MSFT",
        source="sec_xbrl_filing_presentation_v1",
        statement="IncomeStatement",
        canonical_key="revenue",
        value=100_000_000.0,
        scale_factor=1.0,
        unit="USD",
        currency="USD",
        period_start="2024-07-01",
        period_end="2025-06-30",
        period_kind="annual",
        fact_id="xbrl:revenue",
        source_locator="filing#revenue",
    )
    missing_currency = SourceAmount(
        ticker="MSFT",
        source="ciq_workbook_v1",
        statement="IncomeStatement",
        canonical_key="revenue",
        value=100.0,
        scale_factor=1_000_000.0,
        unit=None,
        currency=None,
        period_start="2024-07-01",
        period_end="2025-06-30",
        period_kind="annual",
        fact_id="ciq:missing-currency",
        source_locator="MSFT.xlsx#revenue",
    )
    missing_period_start = SourceAmount(
        ticker="MSFT",
        source="ciq_workbook_v1",
        statement="IncomeStatement",
        canonical_key="revenue",
        value=100.0,
        scale_factor=1_000_000.0,
        unit="USD",
        currency="USD",
        period_start=None,
        period_end="2025-06-30",
        period_kind="annual",
        fact_id="ciq:missing-period-start",
        source_locator="MSFT.xlsx#revenue",
    )

    currency_result = reconcile_statement_sources([xbrl], [missing_currency])
    period_result = reconcile_statement_sources([xbrl], [missing_period_start])

    assert currency_result.status == "review_required"
    assert currency_result.comparisons[0].status == "currency_mismatch"
    assert period_result.status == "not_comparable"
    assert period_result.overlap_count == 0


def test_persisted_reconciliation_uses_only_current_source_vintages():
    common = {
        "ticker": "MSFT",
        "statement": "IncomeStatement",
        "concept": "Revenue",
        "label": "Revenue",
        "numeric_value": 110_000_000.0,
        "unit": "USD",
        "currency": "USD",
        "scale_factor": 1.0,
        "period_start": "2024-07-01",
        "period_end": "2025-06-30",
        "period_kind": "annual",
        "dimensions": {},
    }
    facts = [
        {
            **common,
            "source": "sec_xbrl_filing_presentation_v1",
            "numeric_value": 100_000_000.0,
            "filing_date": "2025-07-30",
            "accession": "old",
            "fact_id": "xbrl:old",
        },
        {
            **common,
            "source": "sec_xbrl_filing_presentation_v1",
            "filing_date": "2026-07-30",
            "accession": "revised",
            "fact_id": "xbrl:revised",
        },
        {
            **common,
            "source": "ciq_workbook_v1",
            "numeric_value": 110.0,
            "scale_factor": 1_000_000.0,
            "source_run_id": 4,
            "fact_id": "ciq:current",
        },
    ]

    result = reconcile_persisted_statement_facts(facts)

    assert result.status == "pass"
    assert result.overlap_count == 1
    assert result.comparisons[0].xbrl_fact_id == "xbrl:revised"


def test_unit_algebra_rejects_currency_per_share_against_currency_scalar():
    per_share = _amount(
        source="sec_xbrl_filing_presentation_v1",
        value=12.0,
        scale_factor=1.0,
        canonical_key="diluted_eps",
        unit="iso4217:USD/shares",
        fact_id="xbrl:eps",
    )
    currency = _amount(
        source="ciq_workbook_v1",
        value=12.0,
        scale_factor=1.0,
        canonical_key="diluted_eps",
        unit="USD",
        fact_id="ciq:eps",
    )

    result = reconcile_statement_sources([per_share], [currency])

    assert result.status == "review_required"
    assert result.comparisons[0].status == "unit_mismatch"


def test_per_share_comparison_does_not_receive_currency_absolute_floor():
    xbrl = _amount(
        source="sec_xbrl_filing_presentation_v1",
        value=12.0,
        scale_factor=1.0,
        canonical_key="diluted_eps",
        unit="USD/shares",
        fact_id="xbrl:eps",
    )
    ciq = _amount(
        source="ciq_workbook_v1",
        value=12.1,
        scale_factor=1.0,
        canonical_key="diluted_eps",
        unit="USD/share",
        fact_id="ciq:eps",
    )

    result = reconcile_statement_sources([xbrl], [ciq])

    assert result.comparisons[0].status == "material_disagreement"
    assert result.comparisons[0].tolerance < 1.0


def test_unit_algebra_rejects_shares_against_currency():
    shares = _amount(
        source="sec_xbrl_filing_presentation_v1",
        value=100.0,
        scale_factor=1.0,
        canonical_key="shares_outstanding",
        unit="xbrli:shares",
        currency=None,
        fact_id="xbrl:shares",
    )
    currency = _amount(
        source="ciq_workbook_v1",
        value=100.0,
        scale_factor=1.0,
        canonical_key="shares_outstanding",
        unit="USD",
        fact_id="ciq:shares",
    )

    result = reconcile_statement_sources([shares], [currency])

    assert result.comparisons[0].status == "unit_mismatch"


def test_canonical_roles_do_not_collapse_incompatible_accounting_bases():
    assert canonical_statement_key(
        "CashAndCashEquivalentsAtCarryingValue"
    ) == "cash_and_equivalents"
    assert canonical_statement_key(
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"
    ) == "cash_including_restricted"
    assert canonical_statement_key("StockholdersEquity") == "equity_parent"
    assert canonical_statement_key(
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"
    ) == "equity_including_nci"
    assert canonical_statement_key(
        "WeightedAverageNumberOfDilutedSharesOutstanding"
    ) == "diluted_weighted_average_shares"
    assert canonical_statement_key("Shares") == "shares"
    assert canonical_statement_key(
        "AccountsReceivableNetCurrent"
    ) == "accounts_receivable"
    assert canonical_statement_key(
        "AccountsPayableCurrent"
    ) == "accounts_payable"
    assert canonical_statement_key("InventoryNet") == "inventory"
    assert canonical_statement_key("Cost Of Goods Sold") == "cost_of_revenue"


def test_canonical_roles_normalize_edgartools_qnames_and_presented_cash_flow_aliases():
    assert canonical_statement_key(
        "us-gaap_RevenueFromContractWithCustomerExcludingAssessedTax",
        "Net sales",
    ) == "revenue"
    assert canonical_statement_key(
        "us-gaap_NetCashProvidedByUsedInOperatingActivities",
        "Net cash from operations",
    ) == "operating_cash_flow"
    assert canonical_statement_key(
        "us-gaap_PaymentsToAcquirePropertyPlantAndEquipment",
        "Additions to property and equipment",
    ) == "capex"
    assert canonical_statement_key(
        "msft_DepreciationAmortizationAndOther",
        "Depreciation, amortization, and other",
    ) == "depreciation_amortization_and_other"
    assert canonical_statement_key(
        (
            "us-gaap_"
            "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"
            "PeriodIncreaseDecreaseExcludingExchangeRateEffect"
        ),
        "Increase (decrease) in cash, cash equivalents and restricted cash",
    ) == "net_change_in_cash_including_restricted"


def test_canonical_roles_use_generic_presented_labels_for_custom_concepts():
    assert canonical_statement_key(
        "msft_CustomRevenueConcept",
        "Net sales",
    ) == "revenue"
    assert canonical_statement_key(
        "msft_CustomOperatingCashFlowConcept",
        "Net cash from operations",
    ) == "operating_cash_flow"
    assert canonical_statement_key(
        "calm_CustomOperatingCashFlowConcept",
        "Net cash provided by operating activities",
    ) == "operating_cash_flow"
    assert canonical_statement_key(
        "msft_CustomCapitalSpendingConcept",
        "Additions to property and equipment",
    ) == "capex"
    assert canonical_statement_key(
        "calm_CustomCapitalSpendingConcept",
        "Purchases of property, plant and equipment",
    ) == "capex"


def test_capex_display_signs_compare_only_with_explicit_economic_sign_rules():
    xbrl = SourceAmount(
        **{
            **_amount(
                source="sec_xbrl_filing_presentation_v1",
                value=10_000_000.0,
                scale_factor=1.0,
                canonical_key="capex",
                fact_id="xbrl:capex",
            ).__dict__,
            "economic_sign": 1,
            "sign_rule": "cash_outflow_positive_v1",
        }
    )
    ciq = SourceAmount(
        **{
            **_amount(
                source="ciq_workbook_v1",
                value=-10.0,
                scale_factor=1_000_000.0,
                canonical_key="capex",
                fact_id="ciq:capex",
            ).__dict__,
            "economic_sign": -1,
            "sign_rule": "cash_outflow_positive_v1",
        }
    )
    opposite = SourceAmount(
        **{
            **ciq.__dict__,
            "fact_id": "ciq:opposite",
            "value": 10.0,
        }
    )

    matched = reconcile_statement_sources([xbrl], [ciq])
    failed = reconcile_statement_sources([xbrl], [opposite])

    assert matched.comparisons[0].status == "matched"
    assert failed.comparisons[0].status == "material_disagreement"


def test_persisted_capex_uses_provider_sign_conventions_without_abs_values():
    common = {
        "ticker": "TEST",
        "statement": "CashFlowStatement",
        "period_start": "2024-01-01",
        "period_end": "2024-12-31",
        "period_kind": "annual",
        "unit": "USD",
        "currency": "USD",
        "scale_factor": 1.0,
        "dimensions": {},
    }
    xbrl = source_amount_from_statement_fact(
        {
            **common,
            "source": "sec_xbrl_filing_presentation_v1",
            "concept": "us-gaap_PaymentsToAcquirePropertyPlantAndEquipment",
            "numeric_value": 10_000_000.0,
            "fact_id": "xbrl:capex",
        }
    )
    ciq = source_amount_from_statement_fact(
        {
            **common,
            "source": "ciq_workbook_v1",
            "concept": "capex",
            "numeric_value": -10_000_000.0,
            "fact_id": "ciq:capex",
        }
    )
    opposite_ciq = source_amount_from_statement_fact(
        {
            **common,
            "source": "ciq_workbook_v1",
            "concept": "capex",
            "numeric_value": 10_000_000.0,
            "fact_id": "ciq:opposite",
        }
    )

    assert (xbrl.economic_sign, ciq.economic_sign) == (1, -1)
    assert xbrl.sign_rule == ciq.sign_rule == "cash_outflow_positive_v1"
    assert reconcile_statement_sources([xbrl], [ciq]).status == "pass"
    assert (
        reconcile_statement_sources([xbrl], [opposite_ciq]).status
        == "review_required"
    )


def test_non_usd_currency_floor_requires_fingerprinted_fx_context():
    base = _amount(
        source="sec_xbrl_filing_presentation_v1",
        value=10_000_000_000.0,
        scale_factor=1.0,
        unit="JPY",
        currency="JPY",
        fact_id="xbrl:jpy",
    )
    missing_fx = _amount(
        source="ciq_workbook_v1",
        value=10_100.0,
        scale_factor=1_000_000.0,
        unit="JPY",
        currency="JPY",
        fact_id="ciq:jpy-no-fx",
    )
    fx_fields = {
        "usd_per_currency_unit": 0.0067,
        "fx_date": "2025-06-30",
        "fx_source": "deterministic_fx_cache",
        "fx_fingerprint": "fx:jpy:2025-06-30",
    }
    with_fx = SourceAmount(
        **{
            **missing_fx.__dict__,
            **fx_fields,
            "fact_id": "ciq:jpy-with-fx",
        }
    )
    xbrl_with_fx = SourceAmount(**{**base.__dict__, **fx_fields})

    blocked = reconcile_statement_sources([base], [missing_fx])
    passing = reconcile_statement_sources([xbrl_with_fx], [with_fx])

    assert blocked.comparisons[0].status == "fx_missing"
    assert passing.comparisons[0].status == "matched"
    assert passing.comparisons[0].tolerance == pytest.approx(
        1_000_000.0 / 0.0067
    )


def test_matching_overlap_without_coverage_inventory_is_not_decision_grade():
    xbrl = _amount(
        source="sec_xbrl_filing_presentation_v1",
        value=100_000_000.0,
        scale_factor=1.0,
    )
    ciq = _amount(
        source="ciq_workbook_v1",
        value=100.0,
        scale_factor=1_000_000.0,
    )

    result = reconcile_statement_sources([xbrl], [ciq])

    assert result.status == "pass"
    assert not result.decision_grade
    assert not result.coverage_attested


def test_coverage_inventory_blocks_when_an_expected_source_fact_is_missing():
    revenue_xbrl = _amount(
        source="sec_xbrl_filing_presentation_v1",
        value=100_000_000.0,
        scale_factor=1.0,
    )
    revenue_ciq = _amount(
        source="ciq_workbook_v1",
        value=100.0,
        scale_factor=1_000_000.0,
    )
    expected_da = ExpectedSourceQuantity(
        ticker="MSFT",
        statement="CashFlowStatement",
        canonical_key="da",
        period_start=None,
        period_end="2025-06-30",
        period_kind="annual",
    )

    result = reconcile_statement_sources(
        [revenue_xbrl],
        [revenue_ciq],
        expected_quantities=[_expected(revenue_xbrl), expected_da],
    )

    assert result.status == "review_required"
    assert not result.decision_grade
    assert result.missing_expected_count == 1
    assert result.findings[-1].finding_type == "missing_source_overlap"


def test_inclusive_and_exclusive_period_starts_describe_the_same_window():
    """CIQ dates a duration from the prior year-end; XBRL from the day after.

    CALM (52/53-week fiscal calendar) reports FY2025 as 2024-06-01 -> 2025-05-31 in
    CIQ and 2024-06-02 -> 2025-05-31 in XBRL. Treating those as different windows made
    every duration fact — revenue, operating income, net income, D&A, capex, operating
    cash flow — fail to pair, so the whole cross-source check reported
    `missing_source_overlap`. A 53-week year differs by seven days, so a one-day
    tolerance cannot merge genuinely different windows.
    """

    from src.stage_00_data.source_reconciliation import _period_compatible

    def _amount(period_start: str):
        return SimpleNamespace(
            ticker="CALM",
            statement="IncomeStatement",
            canonical_key="revenue",
            period_end="2025-05-31",
            period_start=period_start,
            period_kind="annual",
        )

    assert _period_compatible(_amount("2024-06-01"), _amount("2024-06-02"))
    assert _period_compatible(_amount("2024-06-02"), _amount("2024-06-01"))
    # Same start is obviously still compatible (MSFT's fixed 6/30 year end).
    assert _period_compatible(_amount("2024-07-01"), _amount("2024-07-01"))


def test_a_different_fiscal_window_is_still_incompatible():
    from src.stage_00_data.source_reconciliation import _period_compatible

    def _amount(period_start: str):
        return SimpleNamespace(
            ticker="CALM",
            statement="IncomeStatement",
            canonical_key="revenue",
            period_end="2025-05-31",
            period_start=period_start,
            period_kind="annual",
        )

    # A 53-week year is seven days longer — never the same window as a 52-week year.
    assert not _period_compatible(_amount("2024-05-26"), _amount("2024-06-02"))
    # A quarter is not an anual window.
    assert not _period_compatible(_amount("2025-03-01"), _amount("2024-06-02"))


def test_ciq_cash_flow_row_names_map_to_canonical_keys():
    """CIQ's own row names must reach the same canonical keys as the XBRL concepts.

    `cash_from_ops` and `net_change_in_cash` were absent from the alias table, so every
    MSFT period reported CIQ as missing `operating_cash_flow` and
    `net_change_in_cash_*` even though the workbook carries both.
    """

    from src.stage_00_data.source_reconciliation import canonical_statement_key

    assert canonical_statement_key("cash_from_ops", "") == "operating_cash_flow"
    assert (
        canonical_statement_key("net_change_in_cash", "")
        == "net_change_in_cash_and_equivalents"
    )
    # Existing XBRL mappings must be untouched.
    assert (
        canonical_statement_key("us-gaap_NetCashProvidedByUsedInOperatingActivities", "")
        == "operating_cash_flow"
    )


def test_net_income_pairs_across_income_and_cash_flow_statements():
    """CIQ prints net income at the top of the indirect cash flow statement.

    XBRL reports it on the income statement. Requiring an identical `statement` on both
    sides made net income unpairable for every period, even though it is the same
    quantity by definition.
    """

    from src.stage_00_data.source_reconciliation import _expected_matches_amount

    expected = SimpleNamespace(
        ticker="MSFT",
        statement="IncomeStatement",
        canonical_key="net_income",
        period_end="2025-06-30",
        period_start="2024-07-01",
        period_kind="annual",
    )
    ciq_amount = SimpleNamespace(
        ticker="MSFT",
        statement="CashFlowStatement",
        canonical_key="net_income",
        period_end="2025-06-30",
        period_start="2024-07-01",
        period_kind="annual",
    )

    assert _expected_matches_amount(expected, ciq_amount)

    # A different quantity must still not pair across statements.
    other = SimpleNamespace(
        ticker="MSFT",
        statement="CashFlowStatement",
        canonical_key="capex",
        period_end="2025-06-30",
        period_start="2024-07-01",
        period_kind="annual",
    )
    assert not _expected_matches_amount(expected, other)


def test_net_change_in_cash_variants_pair_and_let_the_value_arbitrate():
    """The two net-change-in-cash variants are alternates, not different quantities.

    XBRL reports `...IncludingExchangeRateEffect` on restricted-cash-inclusive terms
    while CIQ carries a plain net change in cash. Declaring one "missing" hides the
    comparison entirely; pairing them lets the tolerance decide, so a filer with
    material restricted-cash movement surfaces as a disagreement rather than a silent
    gap.
    """

    from src.stage_00_data.source_reconciliation import _expected_matches_amount

    expected = SimpleNamespace(
        ticker="MSFT",
        statement="CashFlowStatement",
        canonical_key="net_change_in_cash_including_restricted",
        period_end="2025-06-30",
        period_start="2024-07-01",
        period_kind="annual",
    )
    ciq_amount = SimpleNamespace(
        ticker="MSFT",
        statement="CashFlowStatement",
        canonical_key="net_change_in_cash_and_equivalents",
        period_end="2025-06-30",
        period_start="2024-07-01",
        period_kind="annual",
    )

    assert _expected_matches_amount(expected, ciq_amount)

    unrelated = SimpleNamespace(
        ticker="MSFT",
        statement="CashFlowStatement",
        canonical_key="operating_cash_flow",
        period_end="2025-06-30",
        period_start="2024-07-01",
        period_kind="annual",
    )
    assert not _expected_matches_amount(expected, unrelated)


def test_non_comparable_fiscal_window_warns_instead_of_blocking():
    """PM decision 2026-07-31: differing fiscal windows are non-comparable, not failures.

    CALM FY2023 is 371 days in XBRL (a 53-week year) and 365 in CIQ. Refusing to pair
    them is correct; treating that refusal as a blocking data failure is not — the
    limitation is known and expected, and blocking on it stops periods that *do* pair
    from ever counting.
    """

    from src.stage_00_data.source_reconciliation import (
        _non_comparable_window_finding,
    )

    expected = SimpleNamespace(
        ticker="CALM",
        statement="IncomeStatement",
        canonical_key="revenue",
        period_end="2023-06-03",
        period_start="2022-05-29",
        period_kind="annual",
    )
    ciq_other_window = SimpleNamespace(
        ticker="CALM",
        statement="IncomeStatement",
        canonical_key="revenue",
        period_end="2023-06-03",
        period_start="2022-06-04",
        period_kind="annual",
        fact_id="ciq-1",
        source="ciq_workbook_v1",
        source_locator=None,
        base_value=1.0,
    )

    finding = _non_comparable_window_finding(expected, (ciq_other_window,))
    assert finding is not None
    assert finding.severity == "warning"
    assert finding.finding_type == "non_comparable_fiscal_window"

    # No counterpart at all is still a genuine gap, not a window mismatch.
    assert _non_comparable_window_finding(expected, ()) is None


def test_only_blocking_findings_force_review_required():
    """Finding severity must mean something.

    Every finding set `review_required`, which the readiness gate turns into
    `blocked`. A warning-severity finding — a known, expected limitation such as a
    non-comparable fiscal window — then blocked a ticker exactly as hard as a real
    disagreement, and no amount of correct classification could change the outcome.
    """

    from src.stage_00_data.source_reconciliation import _reconciliation_status

    warning = SimpleNamespace(severity="warning")
    blocking = SimpleNamespace(severity="blocking")

    assert _reconciliation_status(()) == "pass"
    assert _reconciliation_status((warning,)) == "pass"
    assert _reconciliation_status((warning, blocking)) == "review_required"
    assert _reconciliation_status((blocking,)) == "review_required"


def test_material_disagreement_is_advisory_not_blocking():
    """PM decision 2026-07-31: the filing is authoritative for the DCF path.

    Where the SEC filing and Capital IQ disagree on a reported figure, the filing value
    is used and the gap is recorded for PM review rather than halting the ticker. This
    scopes to statement reconciliation only — comparables read `ciq_comps_snapshot`
    through a separate path and keep Capital IQ's cross-company consistency.
    """

    from src.stage_00_data.source_reconciliation import (
        MATERIAL_DISAGREEMENT_SEVERITY,
        _reconciliation_status,
    )

    assert MATERIAL_DISAGREEMENT_SEVERITY == "warning"

    disagreement = SimpleNamespace(severity=MATERIAL_DISAGREEMENT_SEVERITY)
    assert _reconciliation_status((disagreement,)) == "pass"

    # A structural failure — one source simply has no such fact — still blocks.
    assert _reconciliation_status((SimpleNamespace(severity="blocking"),)) == (
        "review_required"
    )
