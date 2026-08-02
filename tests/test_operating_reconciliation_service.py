from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.stage_02_valuation.valuation_types import ForecastDrivers
from src.stage_04_pipeline.operating_reconciliation_service import (
    reconcile_operating_statement_facts,
)


def _drivers() -> ForecastDrivers:
    return ForecastDrivers(
        revenue_base=365.0,
        revenue_growth_near=0.08,
        revenue_growth_mid=0.05,
        revenue_growth_terminal=0.025,
        ebit_margin_start=0.20,
        ebit_margin_target=0.23,
        tax_rate_start=0.21,
        tax_rate_target=0.22,
        capex_pct_start=20.0 / 365.0,
        capex_pct_target=0.06,
        da_pct_start=15.0 / 365.0,
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
        net_debt=100.0,
        shares_outstanding=50.0,
    )


def _inputs() -> SimpleNamespace:
    return SimpleNamespace(
        ticker="TEST",
        drivers=_drivers(),
        claim_ledger={"unit_scale": 1_000_000.0},
        clamp_events=(),
    )


def _fact(
    key: str,
    value: float,
    *,
    source: str = "ciq_workbook_v1",
    scale_factor: float = 1_000_000.0,
    period_start: str | None = None,
    period_end: str = "2025-12-31",
    period_kind: str = "annual",
    suffix: str = "",
) -> dict:
    duration = key in {"revenue", "cost_of_revenue", "capex", "da"}
    statement = (
        "CashFlowStatement"
        if key in {"capex", "da"}
        else "IncomeStatement"
        if key in {"revenue", "cost_of_revenue"}
        else "BalanceSheet"
    )
    return {
        "ticker": "TEST",
        "source": source,
        "statement": statement,
        "canonical_key": key,
        "concept": key,
        "label": key.replace("_", " ").title(),
        "numeric_value": value,
        "scale_factor": scale_factor,
        "unit": "USD",
        "currency": "USD",
        "period_start": (
            period_start
            if duration
            else None
        ),
        "period_end": period_end,
        "period_kind": period_kind,
        "dimensions": {},
        "fact_id": f"{source}:{key}:{period_end}:{suffix}",
        "source_locator": f"fixture://{source}/{key}/{suffix}",
    }


def _facts(*, include_inventory: bool = True) -> list[dict]:
    facts = [
        _fact("revenue", 365.0, period_start="2025-01-01"),
        _fact("cost_of_revenue", 219.0, period_start="2025-01-01"),
        _fact("accounts_receivable", 40.0),
        _fact("accounts_payable", 21.0),
        _fact("capex", 20.0, period_start="2025-01-01"),
        _fact("da", 15.0, period_start="2025-01-01"),
    ]
    if include_inventory:
        facts.append(_fact("inventory", 18.0))
    return facts


def _run(facts: list[dict], *, status: str = "decision_grade") -> SimpleNamespace:
    return SimpleNamespace(
        ticker="TEST",
        selected_fact_ids=tuple(fact["fact_id"] for fact in facts),
        readiness=SimpleNamespace(status=status),
    )


def test_selected_operating_facts_reconcile_in_valuation_units() -> None:
    facts = _facts()
    artifact = reconcile_operating_statement_facts(
        valuation_inputs=_inputs(),
        statement_reconciliation_run=_run(facts),
        statement_facts=facts,
    )

    assert artifact.status == "reconciled"
    assert artifact.period_start == "2025-01-01"
    assert artifact.period_end == "2025-12-31"
    assert artifact.reporting_currency == "USD"
    assert artifact.inventory_applicable is True
    assert artifact.selected_fact_ids_by_role["revenue"].startswith(
        "ciq_workbook_v1:revenue"
    )
    assert all(tie.status == "pass" for tie in artifact.result.tie_outs)
    assert artifact.to_dict()["fingerprint"] == artifact.fingerprint


def test_non_numeric_selected_rows_do_not_block_role_selection() -> None:
    facts = _facts()
    non_numeric = _fact("commitments_and_contingencies", 0.0)
    non_numeric["numeric_value"] = None
    facts.append(non_numeric)

    artifact = reconcile_operating_statement_facts(
        valuation_inputs=_inputs(),
        statement_reconciliation_run=_run(facts),
        statement_facts=facts,
    )

    assert artifact.status == "reconciled"
    assert artifact.period_start == "2025-01-01"
    assert artifact.period_end == "2025-12-31"
    assert set(artifact.selected_fact_ids_by_role) >= {
        "revenue",
        "cost_of_revenue",
        "capex",
        "da",
        "accounts_receivable",
        "accounts_payable",
    }


def test_complete_statement_absence_marks_inventory_not_applicable() -> None:
    facts = _facts(include_inventory=False)
    artifact = reconcile_operating_statement_facts(
        valuation_inputs=_inputs(),
        statement_reconciliation_run=_run(facts),
        statement_facts=facts,
    )

    assert artifact.status == "reconciled"
    assert artifact.inventory_applicable is False
    assert "inventory" not in artifact.selected_fact_ids_by_role


def test_provisional_statement_cannot_infer_inventory_non_applicability() -> None:
    facts = _facts(include_inventory=False)
    artifact = reconcile_operating_statement_facts(
        valuation_inputs=_inputs(),
        statement_reconciliation_run=_run(facts, status="provisional"),
        statement_facts=facts,
    )

    assert artifact.status == "pending"
    assert (
        "operating.inventory_applicability_unknown"
        in artifact.reason_codes
    )
    assert "operating.statement_not_decision_grade" in artifact.reason_codes


def test_duration_roles_cannot_be_union_across_different_windows() -> None:
    facts = _facts()
    for fact in facts:
        if fact["canonical_key"] in {"capex", "da"}:
            fact["period_start"] = "2024-10-01"
            fact["period_kind"] = "ltm"
    artifact = reconcile_operating_statement_facts(
        valuation_inputs=_inputs(),
        statement_reconciliation_run=_run(facts),
        statement_facts=facts,
    )

    assert artifact.status == "pending"
    assert "operating.duration_window_incomplete" in artifact.reason_codes
    assert artifact.selected_fact_ids_by_role == {}


def test_materially_different_duplicate_role_fails_closed() -> None:
    facts = _facts()
    facts.append(
        _fact(
            "revenue",
            300.0,
            period_start="2025-01-01",
            suffix="conflict",
        )
    )
    artifact = reconcile_operating_statement_facts(
        valuation_inputs=_inputs(),
        statement_reconciliation_run=_run(facts),
        statement_facts=facts,
    )

    assert artifact.status == "failed"
    assert "operating.revenue_ambiguous" in artifact.reason_codes


def test_da_uses_cash_flow_statement_not_same_label_income_row() -> None:
    facts = _facts()
    income_da = _fact(
        "da",
        0.0,
        period_start="2025-01-01",
        suffix="income-statement-zero",
    )
    income_da["statement"] = "IncomeStatement"
    facts.append(income_da)

    artifact = reconcile_operating_statement_facts(
        valuation_inputs=_inputs(),
        statement_reconciliation_run=_run(facts),
        statement_facts=facts,
    )

    assert artifact.status == "reconciled"
    assert artifact.selected_fact_ids_by_role["da"].endswith(
        "ciq_workbook_v1:da:2025-12-31:"
    )


def test_reconciled_statement_facts_replace_unreconciled_observed_starts() -> None:
    facts = _facts()
    reported_values = {
        "revenue": 1_000.0,
        "cost_of_revenue": 600.0,
        "accounts_receivable": 200.0,
        "inventory": 120.0,
        "accounts_payable": 300.0,
        "capex": 360.0,
        "da": 108.0,
    }
    for fact in facts:
        fact["numeric_value"] = reported_values[fact["canonical_key"]]

    inputs = _inputs()
    inputs.source_lineage = {}
    artifact = reconcile_operating_statement_facts(
        valuation_inputs=inputs,
        statement_reconciliation_run=_run(facts),
        statement_facts=facts,
    )

    assert artifact.status == "reconciled"
    assert inputs.drivers.revenue_base == pytest.approx(1_000.0)
    assert inputs.drivers.dso_start == pytest.approx(73.0)
    assert inputs.drivers.dio_start == pytest.approx(73.0)
    assert inputs.drivers.dpo_start == pytest.approx(182.5)
    assert inputs.drivers.capex_pct_start == pytest.approx(0.36)
    assert inputs.drivers.da_pct_start == pytest.approx(0.108)
    assert inputs.source_lineage["capex_pct_start"].startswith(
        "reconciled_statement:"
    )
    capex_tie = next(
        tie for tie in artifact.result.tie_outs if tie.name == "capex_pct_to_cash_flow"
    )
    assert set(capex_tie.source_fact_ids) == {
        artifact.selected_fact_ids_by_role["revenue"],
        artifact.selected_fact_ids_by_role["capex"],
    }
    assert all(tie.status == "pass" for tie in artifact.result.tie_outs)


def test_missing_reconciled_role_fails_closed_without_ratio_fallback() -> None:
    facts = [fact for fact in _facts() if fact["canonical_key"] != "capex"]
    inputs = _inputs()
    inputs.source_lineage = {}
    previous_capex = inputs.drivers.capex_pct_start

    artifact = reconcile_operating_statement_facts(
        valuation_inputs=inputs,
        statement_reconciliation_run=_run(facts),
        statement_facts=facts,
    )

    assert artifact.status != "reconciled"
    assert "operating.capex_missing" in artifact.reason_codes
    assert inputs.drivers.capex_pct_start == previous_capex
    assert "capex_pct_start" not in inputs.source_lineage


def test_reconciled_starts_leave_forecast_and_judgment_drivers_untouched() -> None:
    facts = _facts()
    inputs = _inputs()
    inputs.source_lineage = {}
    protected = {
        field: getattr(inputs.drivers, field)
        for field in (
            "revenue_growth_near",
            "revenue_growth_mid",
            "revenue_growth_terminal",
            "ebit_margin_target",
            "tax_rate_target",
            "capex_pct_target",
            "da_pct_target",
            "dso_target",
            "dio_target",
            "dpo_target",
        )
    }

    artifact = reconcile_operating_statement_facts(
        valuation_inputs=inputs,
        statement_reconciliation_run=_run(facts),
        statement_facts=facts,
    )

    assert artifact.status == "reconciled"
    assert {
        field: getattr(inputs.drivers, field)
        for field in protected
    } == protected
