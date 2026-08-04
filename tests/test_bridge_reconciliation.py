from __future__ import annotations

import pytest

from src.stage_02_valuation.claim_ledger import (
    ClaimAllocation,
    ClaimLedger,
    ClaimReclassificationError,
    ReconciledEVBridge,
    ReportedLine,
)


def test_cash_and_lease_split_consumes_each_parent_once_without_changing_total_claim() -> None:
    revenue = 318_273.0
    total_cash = 32_105.0
    total_debt = 125_432.0
    leases = 85_170.0
    operating_cash = min(total_cash, revenue * 0.02)
    excess_cash = total_cash - operating_cash
    debt_ex_leases = total_debt - leases

    ledger = ClaimLedger(
        reported_lines=[
            ReportedLine("cash", total_cash, "ciq:cash"),
            ReportedLine("debt", total_debt, "ciq:total_debt"),
        ],
        allocations=[
            ClaimAllocation(
                parent_line_id="cash",
                allocation_id="cash:operating",
                component="net_debt",
                sign=-1,
                value=operating_cash,
            ),
            ClaimAllocation(
                parent_line_id="cash",
                allocation_id="cash:excess",
                component="non_operating_assets",
                sign=1,
                value=excess_cash,
            ),
            ClaimAllocation(
                parent_line_id="debt",
                allocation_id="debt:funded",
                component="net_debt",
                sign=1,
                value=debt_ex_leases,
            ),
            ClaimAllocation(
                parent_line_id="debt",
                allocation_id="debt:leases",
                component="lease_liabilities",
                sign=1,
                value=leases,
            ),
        ],
        component_values={
            "net_debt": debt_ex_leases - operating_cash,
            "non_operating_assets": excess_cash,
            "lease_liabilities": leases,
        },
    )

    reconciliation = ledger.reconcile()
    bridge = ReconciledEVBridge.from_ledger(ledger)

    assert reconciliation.is_reconciled
    assert bridge.ev_to_equity_adjustment == pytest.approx(93_327.0)
    assert bridge.equity_value(enterprise_value=1_000_000.0) == pytest.approx(
        906_673.0
    )


def test_duplicate_allocation_reports_both_claimants_and_blocks_bridge() -> None:
    ledger = ClaimLedger(
        reported_lines=[ReportedLine("cash", 100.0, "xbrl:cash")],
        allocations=[
            ClaimAllocation(
                parent_line_id="cash",
                allocation_id="cash:same-balance",
                component="net_debt",
                sign=-1,
                value=100.0,
            ),
            ClaimAllocation(
                parent_line_id="cash",
                allocation_id="cash:same-balance",
                component="non_operating_assets",
                sign=1,
                value=100.0,
            ),
        ],
        component_values={
            "net_debt": -100.0,
            "non_operating_assets": 100.0,
        },
    )

    result = ledger.reconcile()

    assert not result.is_reconciled
    assert result.duplicate_allocations[0].allocation_id == "cash:same-balance"
    assert result.duplicate_allocations[0].components == (
        "net_debt",
        "non_operating_assets",
    )
    with pytest.raises(ValueError, match="does not reconcile"):
        ReconciledEVBridge.from_ledger(ledger)


@pytest.mark.parametrize(
    ("allocated_value", "expected_reconciled"),
    [(10_005_000_000.0, True), (10_005_010_000.0, False)],
)
def test_parent_tie_uses_dual_absolute_or_relative_tolerance(
    allocated_value: float,
    expected_reconciled: bool,
) -> None:
    ledger = ClaimLedger(
        reported_lines=[
            ReportedLine("debt", 10_000_000_000.0, "xbrl:debt")
        ],
        allocations=[
            ClaimAllocation(
                parent_line_id="debt",
                allocation_id="debt:funded",
                component="net_debt",
                sign=1,
                value=allocated_value,
            )
        ],
        component_values={"net_debt": allocated_value},
    )

    result = ledger.reconcile()

    assert result.is_reconciled is expected_reconciled
    assert bool(result.untied_parents) is (not expected_reconciled)


def test_reclassification_derives_component_value_from_unclaimed_line() -> None:
    ledger = ClaimLedger(
        reported_lines=[
            ReportedLine(
                "xbrl:Investment",
                12_000.0,
                "xbrl:Investment",
                semantic_type="asset",
            )
        ],
        allocations=[
            ClaimAllocation(
                parent_line_id="xbrl:Investment",
                allocation_id="xbrl:Investment",
                component="unclaimed",
                sign=1,
                value=12_000.0,
            )
        ],
        component_values={
            "unclaimed": 12_000.0,
            "non_operating_assets": 0.0,
        },
    )

    result = ledger.reclassify(
        reported_line="xbrl:Investment",
        from_component="unclaimed",
        to_component="non_operating_assets",
    )

    assert result.derived_component_values["unclaimed"] == 0.0
    assert result.derived_component_values["non_operating_assets"] == 12_000.0
    assert result.ledger.reconcile().is_reconciled


def test_reclassification_rejects_parent_split_across_named_claimants() -> None:
    ledger = ClaimLedger(
        reported_lines=[ReportedLine("cash", 100.0, "xbrl:cash")],
        allocations=[
            ClaimAllocation(
                parent_line_id="cash",
                allocation_id="cash:operating",
                component="net_debt",
                sign=-1,
                value=20.0,
            ),
            ClaimAllocation(
                parent_line_id="cash",
                allocation_id="cash:excess",
                component="non_operating_assets",
                sign=1,
                value=80.0,
            ),
        ],
        component_values={
            "net_debt": -20.0,
            "non_operating_assets": 80.0,
        },
    )

    with pytest.raises(ClaimReclassificationError) as exc_info:
        ledger.reclassify(
            reported_line="cash",
            from_component="unclaimed",
            to_component="non_operating_assets",
        )

    assert exc_info.value.incumbent_components == (
        "net_debt",
        "non_operating_assets",
    )
    assert "cash" in str(exc_info.value)


def test_component_tie_failure_names_component_and_values() -> None:
    ledger = ClaimLedger(
        reported_lines=[
            ReportedLine("debt", 80_000_000.0, "xbrl:debt")
        ],
        allocations=[
            ClaimAllocation(
                parent_line_id="debt",
                allocation_id="debt",
                component="net_debt",
                sign=1,
                value=80_000_000.0,
            )
        ],
        component_values={"net_debt": 100_000_000.0},
    )

    with pytest.raises(ValueError) as exc_info:
        ledger.require_reconciled()

    message = str(exc_info.value)
    assert "component 'net_debt' does not tie" in message
    assert "expected=100000000.0" in message
    assert "derived=80000000.0" in message


def test_duplicate_reported_line_ids_fail_before_tie_out() -> None:
    ledger = ClaimLedger(
        reported_lines=[
            ReportedLine("cash", 40.0, "ciq:cash"),
            ReportedLine("cash", 40.0, "xbrl:CashAndCashEquivalents"),
        ],
        allocations=[
            ClaimAllocation(
                parent_line_id="cash",
                allocation_id="cash:all",
                component="non_operating_assets",
                sign=1,
                value=40.0,
            )
        ],
        component_values={"non_operating_assets": 40.0},
    )

    result = ledger.reconcile()

    assert not result.is_reconciled
    assert result.duplicate_reported_line_ids == ("cash",)
    with pytest.raises(ValueError, match="duplicate reported line IDs: cash"):
        ledger.require_reconciled()


def test_currency_and_period_must_match_before_amounts_can_tie() -> None:
    ledger = ClaimLedger(
        reported_lines=[
            ReportedLine(
                "cash",
                100.0,
                "xbrl:Cash",
                currency="USD",
                period_end="2025-12-31",
                semantic_type="asset",
            ),
            ReportedLine(
                "debt",
                100.0,
                "ciq:Debt",
                currency="EUR",
                period_end="2026-03-31",
                semantic_type="liability",
            ),
        ],
        allocations=[
            ClaimAllocation("cash", "cash", "non_operating_assets", 1, 100.0),
            ClaimAllocation("debt", "debt", "net_debt", 1, 100.0),
        ],
        component_values={"non_operating_assets": 100.0, "net_debt": 100.0},
        currency="USD",
        period_end="2025-12-31",
    )

    result = ledger.reconcile()

    assert not result.is_reconciled
    assert result.currency_mismatches == ("debt",)
    assert result.period_mismatches == ("debt",)
    message = ledger.failure_message(result)
    assert "currency mismatch" in message
    assert "period mismatch" in message


def test_cash_reclassification_derives_target_polarity_and_preserves_equity() -> None:
    ledger = ClaimLedger(
        reported_lines=[
            ReportedLine(
                "cash",
                20.0,
                "xbrl:Cash",
                semantic_type="asset",
            )
        ],
        allocations=[
            ClaimAllocation(
                parent_line_id="cash",
                allocation_id="cash",
                component="net_debt",
                sign=-1,
                value=20.0,
            )
        ],
        component_values={"net_debt": -20.0, "non_operating_assets": 0.0},
    )
    before = ReconciledEVBridge.from_ledger(ledger).ev_to_equity_adjustment

    result = ledger.reclassify(
        reported_line="cash",
        from_component="net_debt",
        to_component="non_operating_assets",
    )

    moved = next(
        allocation
        for allocation in result.ledger.allocations
        if allocation.allocation_id == "cash"
    )
    assert moved.sign == 1
    assert result.derived_component_values["net_debt"] == 0.0
    assert result.derived_component_values["non_operating_assets"] == 20.0
    assert (
        ReconciledEVBridge.from_ledger(result.ledger).ev_to_equity_adjustment
        == before
    )


def test_semantically_unsafe_reclassification_is_rejected() -> None:
    ledger = ClaimLedger(
        reported_lines=[
            ReportedLine(
                "debt",
                20.0,
                "xbrl:Debt",
                semantic_type="liability",
            )
        ],
        allocations=[
            ClaimAllocation("debt", "debt", "net_debt", 1, 20.0)
        ],
        component_values={"net_debt": 20.0, "non_operating_assets": 0.0},
    )

    with pytest.raises(
        ClaimReclassificationError,
        match="liability.*non_operating_assets",
    ):
        ledger.reclassify(
            reported_line="debt",
            from_component="net_debt",
            to_component="non_operating_assets",
        )


def test_material_unclaimed_line_is_reconciled_but_not_decision_grade() -> None:
    ledger = ClaimLedger(
        reported_lines=[
            ReportedLine(
                "investment",
                50_000_000.0,
                "xbrl:MarketableSecurities",
                semantic_type="asset",
            )
        ],
        allocations=[
            ClaimAllocation(
                "investment",
                "investment",
                "unclaimed",
                1,
                50_000_000.0,
            )
        ],
        component_values={"unclaimed": 50_000_000.0},
    )

    result = ledger.reconcile()

    assert result.is_reconciled
    assert not result.is_decision_grade
    assert result.material_unclaimed_allocation_ids == ("investment",)
    with pytest.raises(ValueError, match="material unclaimed"):
        ledger.require_decision_grade()
