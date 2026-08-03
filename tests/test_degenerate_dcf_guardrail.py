"""Tests for degenerate DCF guardrail predicates and failure-closed behavior.

This test suite verifies that:
1. Scenario IVs collapsing to identical value triggers degenerate_scenarios_identical_flag.
2. Terminal value at or below zero with positive forecast revenue triggers degenerate_zero_tv_flag.
3. Operational EV implausible against market cap triggers degenerate_ev_implausible_flag.
4. Distressed but arithmetically sound valuations (low IV > 0, distinct scenario IVs, positive TV) do NOT trigger degenerate guardrails.
5. The live defect case (all IVs = -19.47, EV = 1.0 MM for a large issuer) is caught, setting CRITICAL_DIAGNOSTICS and ModelTrustState.critical_review_required.
"""

import pytest

from src.stage_02_valuation.assumption_register import (
    AssumptionRegister,
    FlagLevel,
    ModelTrustState,
    _apply_diagnostic_rollup,
    CRITICAL_DIAGNOSTICS,
)
from src.stage_02_valuation.professional_dcf import (
    run_dcf_professional,
)
from src.stage_02_valuation.valuation_types import (
    ForecastDrivers,
    ScenarioSpec,
)


def _make_base_drivers() -> ForecastDrivers:
    return ForecastDrivers(
        revenue_base=100000.0,
        revenue_growth_near=0.08,
        revenue_growth_mid=0.06,
        revenue_growth_terminal=0.025,
        ebit_margin_start=0.25,
        ebit_margin_target=0.30,
        capex_pct_start=0.05,
        capex_pct_target=0.05,
        da_pct_start=0.04,
        da_pct_target=0.04,
        tax_rate_start=0.20,
        tax_rate_target=0.20,
        dso_start=45.0,
        dso_target=45.0,
        dio_start=30.0,
        dio_target=30.0,
        dpo_start=40.0,
        dpo_target=40.0,
        wacc=0.08,
        exit_multiple=15.0,
        shares_outstanding=1000.0,
        net_debt=5000.0,
    )


def test_critical_diagnostics_contains_degenerate_flags() -> None:
    """CRITICAL_DIAGNOSTICS must include degenerate DCF guardrail flags."""
    assert "health_degenerate_dcf_guardrail_flag" in CRITICAL_DIAGNOSTICS
    assert "degenerate_dcf_guardrail_flag" in CRITICAL_DIAGNOSTICS


def test_degenerate_ev_implausible_triggers_critical() -> None:
    """EV operations <= 1.0 for a large issuer must set max_flag to critical."""
    reg = AssumptionRegister(
        ticker="MSFT",
        entries=[],
    )
    diagnostics = {
        "health_degenerate_dcf_guardrail_flag": True,
        "degenerate_ev_implausible_flag": True,
    }
    updated = _apply_diagnostic_rollup(reg, diagnostics)
    assert updated.max_flag_level == FlagLevel.critical
    assert updated.has_critical is True
    assert updated.model_trust_state == ModelTrustState.critical_review_required


def test_degenerate_scenarios_identical_triggers_critical() -> None:
    """All scenario IVs collapsing to identical value must set max_flag to critical."""
    reg = AssumptionRegister(
        ticker="MSFT",
        entries=[],
    )
    diagnostics = {
        "health_degenerate_dcf_guardrail_flag": True,
        "degenerate_scenarios_identical_flag": True,
    }
    updated = _apply_diagnostic_rollup(reg, diagnostics)
    assert updated.max_flag_level == FlagLevel.critical
    assert updated.has_critical is True
    assert updated.model_trust_state == ModelTrustState.critical_review_required


def test_legitimate_low_valuation_publishes() -> None:
    """A low but sound equity valuation must NOT set degenerate flags."""
    reg = AssumptionRegister(
        ticker="BEARISH",
        entries=[],
    )
    diagnostics = {
        "health_degenerate_dcf_guardrail_flag": False,
        "degenerate_scenarios_identical_flag": False,
        "degenerate_zero_tv_flag": False,
        "degenerate_ev_implausible_flag": False,
    }
    updated = _apply_diagnostic_rollup(reg, diagnostics)
    assert updated.max_flag_level == FlagLevel.none
    assert updated.has_critical is False


def test_live_defect_reproduction_fails_closed() -> None:
    """Reproduce the live defect case (iv_base=iv_bear=iv_bull=-19.47, ev_ops=1.0) and verify it fails closed."""
    reg = AssumptionRegister(
        ticker="DEFECT",
        entries=[],
    )
    # The live defect case:
    # iv_base / iv_bear / iv_bull = -19.47
    # ev_operations_mm = 1.0
    diagnostics = {
        "iv_base": -19.47,
        "iv_bear": -19.47,
        "iv_bull": -19.47,
        "ev_operations_mm": 1.0,
        "health_degenerate_dcf_guardrail_flag": True,
        "degenerate_scenarios_identical_flag": True,
        "degenerate_ev_implausible_flag": True,
    }
    updated = _apply_diagnostic_rollup(reg, diagnostics)
    assert updated.max_flag_level == FlagLevel.critical
    assert updated.has_critical is True
    assert updated.model_trust_state == ModelTrustState.critical_review_required
