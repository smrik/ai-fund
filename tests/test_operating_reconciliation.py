from __future__ import annotations

from dataclasses import replace

from src.stage_00_data.source_reconciliation import SourceAmount
from src.stage_02_valuation.operating_reconciliation import (
    ClampEvent,
    reconcile_operating_model,
)
from src.stage_02_valuation.valuation_types import ForecastDrivers


def _drivers() -> ForecastDrivers:
    return ForecastDrivers(
        revenue_base=365_000_000.0,
        revenue_growth_near=0.08,
        revenue_growth_mid=0.05,
        revenue_growth_terminal=0.025,
        ebit_margin_start=0.20,
        ebit_margin_target=0.23,
        tax_rate_start=0.21,
        tax_rate_target=0.22,
        capex_pct_start=20_000_000.0 / 365_000_000.0,
        capex_pct_target=0.06,
        da_pct_start=15_000_000.0 / 365_000_000.0,
        da_pct_target=0.045,
        dso_start=40.0,
        dso_target=38.0,
        dio_start=30.0,
        dio_target=28.0,
        dpo_start=35.0,
        dpo_target=37.0,
        wacc=0.09,
        exit_multiple=14.0,
        exit_metric="ev_ebitda",
        net_debt=100_000_000.0,
        shares_outstanding=50_000_000.0,
    )


def _amount(key: str, value: float) -> SourceAmount:
    return SourceAmount(
        ticker="TEST",
        source="sec_xbrl_companyfacts_v3",
        statement=(
            "CashFlowStatement"
            if key in {"capex", "da"}
            else "IncomeStatement"
            if key in {"revenue", "cost_of_revenue"}
            else "BalanceSheet"
        ),
        canonical_key=key,
        value=value,
        scale_factor=1.0,
        unit="USD",
        currency="USD",
        period_start=(
            "2025-01-01"
            if key in {"revenue", "cost_of_revenue", "capex", "da"}
            else None
        ),
        period_end="2025-12-31",
        period_kind="annual",
        fact_id=f"xbrl:{key}",
        source_locator=f"sec.example/{key}",
    )


def _reported() -> dict[str, SourceAmount]:
    cogs = 219_000_000.0
    return {
        "revenue": _amount("revenue", 365_000_000.0),
        "cost_of_revenue": _amount("cost_of_revenue", cogs),
        "accounts_receivable": _amount("accounts_receivable", 40_000_000.0),
        "inventory": _amount("inventory", 18_000_000.0),
        "accounts_payable": _amount("accounts_payable", 21_000_000.0),
        "capex": _amount("capex", 20_000_000.0),
        "da": _amount("da", 15_000_000.0),
    }


def test_operating_starts_tie_to_reported_statements() -> None:
    result = reconcile_operating_model(
        drivers=_drivers(),
        reported=_reported(),
        inventory_applicable=True,
    )

    assert result.status == "reconciled"
    assert result.reason_codes == ()
    assert {tie.name for tie in result.tie_outs} == {
        "dso_to_accounts_receivable",
        "dio_to_inventory",
        "dpo_to_accounts_payable",
        "capex_pct_to_cash_flow",
        "da_pct_to_cash_flow",
    }
    assert all(tie.status == "pass" for tie in result.tie_outs)
    assert result.unresolved_clamp_count == 0


def test_stale_working_capital_ratio_fails_closed() -> None:
    result = reconcile_operating_model(
        drivers=replace(_drivers(), dso_start=65.0),
        reported=_reported(),
        inventory_applicable=True,
    )

    assert result.status == "failed"
    assert "operating.dso_to_accounts_receivable_failed" in result.reason_codes
    failed = next(tie for tie in result.tie_outs if tie.status == "fail")
    assert failed.driver_name == "dso_start"
    assert failed.source_fact_ids == ("xbrl:revenue", "xbrl:accounts_receivable")


def test_non_inventory_business_can_mark_inventory_not_applicable() -> None:
    reported = _reported()
    del reported["inventory"]

    result = reconcile_operating_model(
        drivers=_drivers(),
        reported=reported,
        inventory_applicable=False,
    )

    assert result.status == "reconciled"
    assert "dio_to_inventory" not in {tie.name for tie in result.tie_outs}


def test_missing_required_reported_line_is_provisional_not_fabricated() -> None:
    reported = _reported()
    del reported["accounts_payable"]

    result = reconcile_operating_model(
        drivers=_drivers(),
        reported=reported,
        inventory_applicable=True,
    )

    assert result.status == "pending"
    assert "operating.accounts_payable_missing" in result.reason_codes


def test_non_usd_tie_out_translates_the_one_million_dollar_floor() -> None:
    reported = {
        key: replace(
            amount,
            unit="EUR",
            currency="EUR",
            usd_per_currency_unit=0.5,
            fx_date="2025-12-31",
            fx_source="fixture",
            fx_fingerprint="fx:eur-usd",
        )
        for key, amount in _reported().items()
    }
    reported["accounts_receivable"] = replace(
        reported["accounts_receivable"],
        value=41_500_000.0,
    )

    result = reconcile_operating_model(
        drivers=_drivers(),
        reported=reported,
        inventory_applicable=True,
    )

    dso = next(
        tie
        for tie in result.tie_outs
        if tie.name == "dso_to_accounts_receivable"
    )
    assert dso.difference == 1_500_000.0
    assert dso.tolerance == 2_000_000.0
    assert dso.status == "pass"


def test_non_usd_operating_sources_without_fx_provenance_fail_closed() -> None:
    reported = {
        key: replace(amount, unit="EUR", currency="EUR")
        for key, amount in _reported().items()
    }

    result = reconcile_operating_model(
        drivers=_drivers(),
        reported=reported,
        inventory_applicable=True,
    )

    assert result.status == "failed"
    assert "operating.fx_missing" in result.reason_codes
    assert result.tie_outs == ()


def test_fired_clamp_is_preserved_as_an_auditable_finding() -> None:
    result = reconcile_operating_model(
        drivers=_drivers(),
        reported=_reported(),
        inventory_applicable=True,
        clamp_events=(
            ClampEvent(
                field_name="da_pct_start",
                raw_value=0.0,
                resolved_value=0.005,
                lower_bound=0.005,
                upper_bound=0.25,
                default_value=0.04,
                source="ciq",
            ),
        ),
    )

    assert result.status == "reconciled"
    assert result.unresolved_clamp_count == 1
    assert result.clamp_events[0].bound_hit == "lower"
    assert "operating.clamp_fired" in result.reason_codes
    event_payload = result.to_dict()["clamp_events"][0]
    assert event_payload["was_clamped"] is True
    assert event_payload["bound_hit"] == "lower"
