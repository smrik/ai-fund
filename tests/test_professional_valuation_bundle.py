from __future__ import annotations

from datetime import date

import pytest

from src.contracts.professional_financial_model import (
    AvailabilityState,
    AvailabilityStatus,
    CheckResult,
    CheckStatus,
    DecisionEligibility,
    DependencyScope,
    LineSeries,
    ModelPeriod,
    ModelResult,
    ModuleBlocker,
    ModuleDependency,
    PeriodAxis,
    PeriodType,
    PeriodValue,
    ScheduleResult,
    StatementResult,
    ValuationMethod,
)
from src.stage_02_valuation.professional_valuation_bundle import (
    BridgeCategory,
    BridgeValue,
    CompsPolicy,
    DiscountTiming,
    FCFEPolicy,
    HistoricalTradingRangeInput,
    MethodDecisionPolicy,
    PeerValuationFact,
    ProfessionalValuationInputs,
    ReverseDCFPolicy,
    ReverseDCFVariable,
    SOTPComponent,
    SOTPInput,
    ScenarioValuationPolicy,
    SourcedValue,
    ValuationBasis,
    WACCMethodInput,
    build_professional_valuation_bundles,
)


HASH_A = "a" * 64


def _available() -> AvailabilityState:
    return AvailabilityState(status=AvailabilityStatus.AVAILABLE)


def _unavailable(code: str = "missing") -> AvailabilityState:
    return AvailabilityState(
        status=AvailabilityStatus.UNAVAILABLE,
        reason_code=code,
        message="Synthetic input is unavailable",
    )


def _line(key: str, values: tuple[float, ...], *, available: bool = True) -> LineSeries:
    periods = ("FY1", "FY2", "FY3")
    return LineSeries(
        line_key=key,
        method_id="synthetic_forecast",
        values=tuple(
            PeriodValue(
                period_key=period,
                value=value if available else None,
                state=_available() if available else _unavailable(),
                formula_id=f"synthetic:{key}",
                source_refs=(f"model:{key}:{period}",),
            )
            for period, value in zip(periods, values, strict=True)
        ),
    )


def _model_result(
    scenario: str = "Base",
    *,
    fcff: tuple[float, ...] = (100.0, 110.0, 120.0),
    fcfe: tuple[float, ...] = (89.0, 98.0, 107.0),
    after_tax_interest: tuple[float, ...] = (15.0, 16.0, 17.0),
    capex_values: tuple[float, ...] = (-20.0, -22.0, -24.0),
    cash_from_operations: tuple[float, ...] | None = None,
    net_income_common: tuple[float, ...] = (140.0, 154.0, 168.0),
    include_fcff: bool = True,
    include_fcfe_checks: bool = True,
) -> ModelResult:
    net_income_company = (140.0, 154.0, 168.0)
    nopat = (150.0, 165.0, 180.0)
    if cash_from_operations is None:
        cash_from_operations = tuple(
            fcff_value + net_income_value - nopat_value - capex_value
            for fcff_value, net_income_value, nopat_value, capex_value in zip(
                fcff,
                net_income_company,
                nopat,
                capex_values,
                strict=True,
            )
        )
    periods = PeriodAxis(
        periods=(
            ModelPeriod(index=1, key="FY1", end_date=date(2027, 6, 30), period_type=PeriodType.FISCAL_YEAR),
            ModelPeriod(index=2, key="FY2", end_date=date(2028, 6, 30), period_type=PeriodType.FISCAL_YEAR),
            ModelPeriod(index=3, key="FY3", end_date=date(2029, 6, 30), period_type=PeriodType.FISCAL_YEAR),
        )
    )
    statements = (
        StatementResult(
            statement_key="income_statement",
            lines=(
                _line("is.revenue", (1_000.0, 1_100.0, 1_200.0)),
                _line("is.ebitda", (250.0, 275.0, 300.0)),
                _line("is.net_income_company", net_income_company),
                _line("is.net_income_common", net_income_common),
                _line("tax.nopat", nopat),
            ),
        ),
    )
    schedule_lines = [
        _line("debt.after_tax_interest", after_tax_interest),
        _line("debt.net_borrowing", (4.0, 4.0, 4.0)),
        _line("cf.levered_fcf", fcfe),
        _line("cf.cash_from_operations", cash_from_operations),
        _line("cf.capex", capex_values),
        _line("shares.diluted_weighted_average", (95.0, 90.0, 80.0)),
    ]
    if include_fcff:
        schedule_lines.append(_line("cf.unlevered_fcf", fcff))
    checks = [
        CheckResult(check_id="core", status=CheckStatus.PASS, difference=0.0, tolerance=0.01),
    ]
    if include_fcfe_checks:
        checks.extend(
            CheckResult(check_id=check_id, status=CheckStatus.PASS, difference=0.0, tolerance=0.01)
            for check_id in ("debt_roll_forward", "interest_tie", "net_borrowing_tie")
        )
    return ModelResult(
        scenario_key=scenario,
        state=_available(),
        period_axis=periods,
        statements=statements,
        supporting_schedules=(ScheduleResult(schedule_key="valuation_support", lines=tuple(schedule_lines)),),
        check_results=tuple(checks),
        tolerances={check.check_id: check.tolerance if check.tolerance is not None else 0.0 for check in checks},
        input_hash=HASH_A,
    )


def _sourced(value: float, ref: str) -> SourcedValue:
    return SourcedValue(value=value, state=_available(), source_refs=(ref,))


def _bridge() -> tuple[BridgeValue, ...]:
    amounts = {
        BridgeCategory.CASH: 50.0,
        BridgeCategory.SHORT_TERM_INVESTMENTS: 20.0,
        BridgeCategory.LONG_TERM_INVESTMENTS: 10.0,
        BridgeCategory.OTHER_NON_OPERATING_ASSETS: 0.0,
        BridgeCategory.DEBT: 100.0,
        BridgeCategory.LEASE_LIABILITIES: 5.0,
        BridgeCategory.PREFERRED_STOCK: 0.0,
        BridgeCategory.MINORITY_INTEREST: 0.0,
        BridgeCategory.PENSION_DEFICIT: 0.0,
        BridgeCategory.OTHER_CLAIMS: 0.0,
    }
    return tuple(
        BridgeValue(
            category=category,
            amount=_sourced(amount, f"source:bridge:{category.value}"),
            claim_ids=(f"atomic:{category.value}",),
        )
        for category, amount in amounts.items()
    )


def _peers(*, basis: ValuationBasis = ValuationBasis.NTM) -> tuple[PeerValuationFact, ...]:
    # OUT is a deliberate IQR outlier. NEG has non-positive denominators and
    # must remain visible but excluded from the relevant statistics.
    facts = (
        ("P1", 2_000.0, 1_900.0, 1_000.0, 200.0, 100.0),
        ("P2", 2_200.0, 2_100.0, 1_000.0, 200.0, 100.0),
        ("P3", 2_400.0, 2_300.0, 1_000.0, 200.0, 100.0),
        ("P4", 2_600.0, 2_500.0, 1_000.0, 200.0, 100.0),
        ("OUT", 100_000.0, 90_000.0, 1_000.0, 200.0, 100.0),
        ("NEG", 1_000.0, 900.0, -10.0, 0.0, -2.0),
    )
    return tuple(
        PeerValuationFact(
            ticker=ticker,
            basis=basis,
            enterprise_value=ev,
            equity_value=equity,
            revenue=revenue,
            ebitda=ebitda,
            net_income=net_income,
            source_refs=(f"peer:{ticker}:{basis.value}",),
        )
        for ticker, ev, equity, revenue, ebitda, net_income in facts
    )


def _inputs(
    *,
    timing: DiscountTiming = DiscountTiming.END_YEAR,
    peer_basis: ValuationBasis = ValuationBasis.NTM,
    historical: HistoricalTradingRangeInput | None = None,
    sotp: SOTPInput | None = None,
    wacc_state: AvailabilityState | None = None,
) -> ProfessionalValuationInputs:
    if wacc_state is None:
        wacc_state = _available()
    return ProfessionalValuationInputs(
        ticker="SYN",
        current_price=_sourced(10.0, "market:price"),
        current_diluted_shares=_sourced(100.0, "market:current_diluted_shares"),
        bridge_items=_bridge(),
        wacc_methods=(
            WACCMethodInput(
                method_id="capm",
                state=wacc_state,
                wacc=0.10 if wacc_state.status is AvailabilityStatus.AVAILABLE else None,
                source_refs=("wacc:capm",) if wacc_state.status is AvailabilityStatus.AVAILABLE else (),
            ),
            WACCMethodInput(
                method_id="peer_cross_check",
                state=_available(),
                wacc=0.105,
                source_refs=("wacc:peer",),
            ),
        ),
        selected_wacc_policy="capm",
        scenario_policies=(
            ScenarioValuationPolicy(
                scenario_key="Base",
                forecast_period_keys=("FY1", "FY2", "FY3"),
                terminal_growth=_sourced(0.03, "policy:terminal_growth"),
                discount_timing=timing,
                terminal_value_dominance_limit=_sourced(
                    0.85,
                    "policy:terminal_value_dominance_limit",
                ),
            ),
        ),
        fcfe_policy=FCFEPolicy(
            cost_of_equity=_sourced(0.11, "wacc:cost_of_equity"),
            financing_claim_categories_reflected=(BridgeCategory.DEBT,),
            required_check_ids=("debt_roll_forward", "interest_tie", "net_borrowing_tie"),
        ),
        reverse_dcf_policy=ReverseDCFPolicy(
            variable=ReverseDCFVariable.TERMINAL_GROWTH,
            lower_bound=-0.20,
            upper_bound=0.095,
        ),
        peer_universe_version="synthetic-peers-v1",
        peer_facts=_peers(basis=peer_basis),
        comps_policy=CompsPolicy(
            basis=peer_basis,
            target_period_key="FY1",
            approved_multiples=("ev_revenue", "ev_ebitda", "pe"),
        ),
        historical_range=historical,
        sotp_input=sotp,
        wacc_sensitivity_deltas=(-0.01, 0.0, 0.01),
        terminal_growth_sensitivity_deltas=(-0.01, 0.0, 0.01),
    )


def _method(bundle, method: ValuationMethod):
    return next(result for result in bundle.valuation_methods if result.method is method)


def test_fcff_dcf_uses_explicit_timing_bridge_and_current_share_denominator() -> None:
    result = _model_result()
    end_year = build_professional_valuation_bundles((result,), _inputs())[0]
    mid_year = build_professional_valuation_bundles(
        (result,), _inputs(timing=DiscountTiming.MID_YEAR)
    )[0]

    end_dcf = _method(end_year, ValuationMethod.FCFF_DCF)
    mid_dcf = _method(mid_year, ValuationMethod.FCFF_DCF)
    assert end_dcf.state.status is AvailabilityStatus.AVAILABLE
    assert mid_dcf.value_per_share > end_dcf.value_per_share
    assert end_dcf.metrics["discount_timing"] == "end_year"
    assert end_dcf.metrics["terminal_discount_exponent"] == 3.0
    assert mid_dcf.metrics["explicit_first_discount_exponent"] == 0.5
    assert mid_dcf.metrics["explicit_last_discount_exponent"] == 2.5
    assert mid_dcf.metrics["terminal_discount_exponent"] == 3.0
    assert mid_dcf.metrics["pv_terminal_value"] == pytest.approx(
        mid_dcf.metrics["terminal_value"] / (1.10**3.0)
    )
    assert end_dcf.metrics["bridge_additions"] == pytest.approx(80.0)
    assert end_dcf.metrics["bridge_subtractions"] == pytest.approx(105.0)
    assert end_dcf.metrics["current_diluted_shares"] == 100.0
    assert end_dcf.metrics["terminal_shares_diagnostic"] == 80.0
    assert end_dcf.metrics["share_denominator_policy"] == "current_diluted_shares"
    assert end_dcf.metrics["terminal_share_count_used_in_denominator"] is False
    assert end_year.implied_per_share_reconciliation.status is CheckStatus.PASS
    assert end_year.implied_per_share_reconciliation.difference == pytest.approx(0.0)


def test_fcff_must_reconcile_to_integrated_unlevered_identity() -> None:
    good_bundle = build_professional_valuation_bundles(
        (_model_result(),),
        _inputs(),
    )[0]
    good = _method(good_bundle, ValuationMethod.FCFF_DCF)
    assert good.metrics["fcff_identity_max_abs_difference"] == pytest.approx(0.0)
    assert good.metrics["financing_items_excluded_from_fcff"] is True
    assert good.metrics["interest_tax_shield_added_to_fcff"] is False

    bad_bundle = build_professional_valuation_bundles(
        (
            _model_result(
                cash_from_operations=(111.0, 121.0, 132.0),
            ),
        ),
        _inputs(),
    )[0]
    bad = _method(bad_bundle, ValuationMethod.FCFF_DCF)
    assert bad_bundle.state.status is AvailabilityStatus.BLOCKING
    assert bad.state.status is AvailabilityStatus.BLOCKING
    assert "fcff_identity_not_reconciled" in bad_bundle.blockers

    sign_error_bundle = build_professional_valuation_bundles(
        (
            _model_result(
                capex_values=(20.0, 22.0, 24.0),
            ),
        ),
        _inputs(),
    )[0]
    assert "fcff_capex_sign_invalid" in sign_error_bundle.blockers


def test_bridge_requires_every_category_once_and_preserves_explicit_zero() -> None:
    inputs = _inputs()
    with pytest.raises(ValueError, match="unique atomic claim_ids"):
        BridgeValue(
            category=BridgeCategory.CASH,
            amount=_sourced(50.0, "source:bridge:cash"),
            claim_ids=("atomic:cash", "atomic:cash"),
        )

    duplicate = (*inputs.bridge_items, inputs.bridge_items[0])
    with pytest.raises(ValueError, match="duplicate bridge categories"):
        ProfessionalValuationInputs(**{**inputs.__dict__, "bridge_items": duplicate})

    bundle = build_professional_valuation_bundles((_model_result(),), inputs)[0]
    bridge = {item.key: item.amount for item in bundle.ev_equity_bridge}
    assert bridge[BridgeCategory.PREFERRED_STOCK.value] == 0.0
    assert bridge[BridgeCategory.OTHER_NON_OPERATING_ASSETS.value] == 0.0
    bridge_refs = {
        item.key: item.source_refs for item in bundle.ev_equity_bridge
    }
    assert (
        "bridge_claim:atomic:debt"
        in bridge_refs[BridgeCategory.DEBT.value]
    )

    duplicate_claim_bridge = (
        *inputs.bridge_items[:-1],
        BridgeValue(
            category=inputs.bridge_items[-1].category,
            amount=inputs.bridge_items[-1].amount,
            claim_ids=inputs.bridge_items[0].claim_ids,
        ),
    )
    with pytest.raises(ValueError, match="duplicate atomic claim IDs"):
        ProfessionalValuationInputs(
            **{**inputs.__dict__, "bridge_items": duplicate_claim_bridge}
        )


def test_fcfe_is_available_only_when_schedule_checks_and_identity_tie() -> None:
    with pytest.raises(ValueError, match="financing claim categories"):
        FCFEPolicy(
            cost_of_equity=_sourced(0.11, "wacc:cost_of_equity"),
            financing_claim_categories_reflected=(),
        )

    good_bundle = build_professional_valuation_bundles((_model_result(),), _inputs())[0]
    good = _method(good_bundle, ValuationMethod.FCFE)
    assert good.state.status is AvailabilityStatus.AVAILABLE
    assert good.metrics["identity_max_abs_difference"] == pytest.approx(0.0)
    assert good.metrics["share_denominator_policy"] == "current_diluted_shares"
    assert good.metrics["financing_claim_categories_reflected"] == "debt"
    assert good.metrics["interest_tax_shield_application_count"] == 1

    bad_bundle = build_professional_valuation_bundles(
        (_model_result(fcfe=(89.0, 98.0, 999.0)),), _inputs()
    )[0]
    bad = _method(bad_bundle, ValuationMethod.FCFE)
    assert bad.state.status is AvailabilityStatus.UNAVAILABLE
    assert bad.state.reason_code == "fcfe_identity_not_reconciled"

    unchecked_bundle = build_professional_valuation_bundles(
        (_model_result(include_fcfe_checks=False),), _inputs()
    )[0]
    unchecked = _method(unchecked_bundle, ValuationMethod.FCFE)
    assert unchecked.state.reason_code == "fcfe_schedule_checks_not_passed"

    negative_interest_bundle = build_professional_valuation_bundles(
        (
            _model_result(
                after_tax_interest=(-15.0, -16.0, -17.0),
                fcfe=(119.0, 130.0, 141.0),
            ),
        ),
        _inputs(),
    )[0]
    negative_interest = _method(
        negative_interest_bundle,
        ValuationMethod.FCFE,
    )
    assert (
        negative_interest.state.reason_code
        == "fcfe_after_tax_interest_sign_invalid"
    )


def test_reverse_dcf_solves_and_replays_market_implied_growth_without_recommendation() -> None:
    bundle = build_professional_valuation_bundles((_model_result(),), _inputs())[0]
    reverse = _method(bundle, ValuationMethod.REVERSE_DCF)
    assert reverse.state.status is AvailabilityStatus.AVAILABLE
    assert reverse.value_per_share is None
    assert reverse.metrics["solve_variable"] == "terminal_growth"
    assert reverse.metrics["replay_value_per_share"] == pytest.approx(10.0, abs=1e-8)
    assert reverse.metrics["replay_difference_per_share"] == pytest.approx(0.0, abs=1e-8)
    assert not any(
        forbidden in key.lower()
        for key in reverse.metrics
        for forbidden in ("recommendation", "target_price", "probability", "blend")
    )


def test_decision_eligibility_is_explicit_and_diagnostics_never_become_targets() -> None:
    inputs = _inputs()
    bundle = build_professional_valuation_bundles((_model_result(),), inputs)[0]
    dcf = _method(bundle, ValuationMethod.FCFF_DCF)
    fcfe = _method(bundle, ValuationMethod.FCFE)
    reverse = _method(bundle, ValuationMethod.REVERSE_DCF)
    comps = _method(bundle, ValuationMethod.COMPS)
    historical = _method(bundle, ValuationMethod.HISTORICAL_RANGE)

    assert dcf.state.status is AvailabilityStatus.AVAILABLE
    assert dcf.metrics["decision_eligibility_status"] == "NEEDS_PM_REVIEW"
    assert dcf.metrics["decision_eligible"] is False
    assert fcfe.metrics["decision_eligibility_status"] == "INELIGIBLE"
    assert reverse.metrics["decision_eligibility_status"] == "INELIGIBLE"
    assert comps.metrics["decision_eligibility_status"] == "NEEDS_PM_REVIEW"
    assert historical.metrics["decision_eligibility_status"] == "INELIGIBLE"
    assert (
        dcf.decision_status.decision_eligibility
        is DecisionEligibility.NEEDS_PM_REVIEW
    )
    assert (
        fcfe.decision_status.decision_eligibility
        is DecisionEligibility.INELIGIBLE
    )
    assert historical.metrics["calculation_availability_status"] == "unavailable"

    approval = MethodDecisionPolicy(
        method=ValuationMethod.FCFF_DCF,
        scenario_key="Base",
        status=DecisionEligibility.ELIGIBLE,
        reason_code="pm_approved_fcff_method",
        message="PM approved the source-frozen FCFF method for decision use.",
        approved_input_hash=HASH_A,
        approval_ref="approval:fcff:v1",
        source_refs=("approval_record:fcff:v1",),
    )
    approved_inputs = ProfessionalValuationInputs(
        **{
            **inputs.__dict__,
            "method_decision_policies": (approval,),
        }
    )
    approved = _method(
        build_professional_valuation_bundles(
            (_model_result(),),
            approved_inputs,
        )[0],
        ValuationMethod.FCFF_DCF,
    )
    assert approved.metrics["terminal_value_dominance_control_status"] == "pass"
    assert approved.metrics["decision_eligibility_status"] == "ELIGIBLE"
    assert approved.metrics["decision_eligible"] is True
    assert approved.metrics["decision_approval_ref"] == "approval:fcff:v1"
    assert approved.metrics["approval_fingerprint_match"] is True
    assert (
        approved.decision_status.decision_eligibility
        is DecisionEligibility.ELIGIBLE
    )
    assert all(
        gate.reported_status == "PASS"
        for gate in approved.decision_status.required_gates
    )

    stale_approval = MethodDecisionPolicy(
        method=ValuationMethod.FCFF_DCF,
        scenario_key="Base",
        status=DecisionEligibility.ELIGIBLE,
        reason_code="pm_approved_fcff_method",
        message="PM approved a prior source-frozen FCFF method.",
        approved_input_hash="b" * 64,
        approval_ref="approval:fcff:stale",
        source_refs=("approval_record:fcff:stale",),
    )
    stale_inputs = ProfessionalValuationInputs(
        **{
            **inputs.__dict__,
            "method_decision_policies": (stale_approval,),
        }
    )
    stale = _method(
        build_professional_valuation_bundles(
            (_model_result(),),
            stale_inputs,
        )[0],
        ValuationMethod.FCFF_DCF,
    )
    assert stale.state.status is AvailabilityStatus.AVAILABLE
    assert stale.metrics["decision_eligibility_status"] == "NEEDS_PM_REVIEW"
    assert (
        stale.metrics["decision_eligibility_reason_code"]
        == "method_decision_approval_stale"
    )
    assert stale.metrics["approval_fingerprint_match"] is False
    assert stale.metrics["decision_eligible"] is False

    with pytest.raises(ValueError, match="diagnostic methods"):
        ProfessionalValuationInputs(
            **{
                **inputs.__dict__,
                "method_decision_policies": (
                    MethodDecisionPolicy(
                        method=ValuationMethod.REVERSE_DCF,
                        scenario_key="Base",
                        status=DecisionEligibility.ELIGIBLE,
                        reason_code="invalid_reverse_approval",
                        message="Synthetic invalid approval.",
                        approved_input_hash=HASH_A,
                        approval_ref="approval:reverse:v1",
                        source_refs=("approval_record:reverse:v1",),
                    ),
                ),
            }
        )


def test_terminal_value_dominance_control_gates_decision_use_without_hiding_value() -> None:
    inputs = _inputs()
    approval = MethodDecisionPolicy(
        method=ValuationMethod.FCFF_DCF,
        scenario_key="Base",
        status=DecisionEligibility.ELIGIBLE,
        reason_code="pm_approved_fcff_method",
        message="PM approved the source-frozen FCFF method for decision use.",
        approved_input_hash=HASH_A,
        approval_ref="approval:fcff:v1",
        source_refs=("approval_record:fcff:v1",),
    )
    strict_policy = ScenarioValuationPolicy(
        scenario_key="Base",
        forecast_period_keys=("FY1", "FY2", "FY3"),
        terminal_growth=_sourced(0.03, "policy:terminal_growth"),
        terminal_value_dominance_limit=_sourced(
            0.80,
            "policy:strict_terminal_value_limit",
        ),
    )
    strict_inputs = ProfessionalValuationInputs(
        **{
            **inputs.__dict__,
            "method_decision_policies": (approval,),
            "scenario_policies": (strict_policy,),
        }
    )
    strict_bundle = build_professional_valuation_bundles(
        (_model_result(),),
        strict_inputs,
    )[0]
    strict_dcf = _method(strict_bundle, ValuationMethod.FCFF_DCF)
    assert strict_dcf.state.status is AvailabilityStatus.AVAILABLE
    assert strict_dcf.value_per_share is not None
    assert (
        strict_dcf.metrics["terminal_value_dominance_control_status"]
        == "exceeds_limit"
    )
    assert strict_dcf.metrics["decision_eligibility_status"] == "INELIGIBLE"
    assert "terminal_value_dominance_limit_exceeded" in strict_bundle.warnings

    no_limit_policy = ScenarioValuationPolicy(
        scenario_key="Base",
        forecast_period_keys=("FY1", "FY2", "FY3"),
        terminal_growth=_sourced(0.03, "policy:terminal_growth"),
    )
    no_limit_inputs = ProfessionalValuationInputs(
        **{
            **inputs.__dict__,
            "method_decision_policies": (approval,),
            "scenario_policies": (no_limit_policy,),
        }
    )
    no_limit_dcf = _method(
        build_professional_valuation_bundles(
            (_model_result(),),
            no_limit_inputs,
        )[0],
        ValuationMethod.FCFF_DCF,
    )
    assert no_limit_dcf.state.status is AvailabilityStatus.AVAILABLE
    assert no_limit_dcf.metrics["decision_eligibility_status"] == "NEEDS_PM_REVIEW"
    assert (
        no_limit_dcf.metrics["decision_eligibility_reason_code"]
        == "terminal_value_dominance_control_not_passed"
    )


def test_comps_are_basis_consistent_and_flag_negative_and_outlier_observations() -> None:
    bundle = build_professional_valuation_bundles((_model_result(),), _inputs())[0]
    comps = _method(bundle, ValuationMethod.COMPS)
    assert comps.state.status is AvailabilityStatus.AVAILABLE
    assert comps.value_per_share is None  # no hidden aggregation across multiples
    assert comps.metrics["basis_label"] == "NTM"
    assert comps.metrics["ev_revenue_nonpositive_count"] == 1
    assert comps.metrics["ev_revenue_nm_count"] == 1
    assert comps.metrics["ev_revenue_negative_numerator_count"] == 0
    assert comps.metrics["ev_revenue_peer_numerator_field"] == "enterprise_value"
    assert comps.metrics["ev_revenue_peer_denominator_field"] == "revenue"
    assert comps.metrics["ev_ebitda_peer_denominator_field"] == "ebitda"
    assert comps.metrics["pe_peer_numerator_field"] == "equity_value"
    assert comps.metrics["pe_peer_denominator_field"] == "net_income"
    assert comps.metrics["ev_revenue_outlier_count"] == 1
    assert comps.metrics["ev_revenue_valid_peer_count"] == 4
    assert comps.metrics["ev_revenue_median_multiple"] == pytest.approx(2.3)
    assert comps.metrics["ev_revenue_implied_per_share"] == pytest.approx(22.75)
    assert "NEG:ev_revenue_nm_denominator" in comps.metrics["excluded_peer_reasons"]
    assert "OUT:ev_revenue_outlier" in comps.metrics["excluded_peer_reasons"]


def test_comps_nm_target_and_pe_only_bridge_independence_are_explicit() -> None:
    inputs = _inputs()
    target_nm_bundle = build_professional_valuation_bundles(
        (
            _model_result(
                net_income_common=(-10.0, 154.0, 168.0),
            ),
        ),
        inputs,
    )[0]
    target_nm = _method(target_nm_bundle, ValuationMethod.COMPS)
    assert target_nm.state.status is AvailabilityStatus.AVAILABLE
    assert target_nm.metrics["pe_target_metric"] == -10.0
    assert target_nm.metrics["pe_target_nm"] is True
    assert target_nm.metrics["pe_implied_per_share"] is None
    assert target_nm.metrics["ev_revenue_implied_per_share"] is not None

    pe_only_inputs = ProfessionalValuationInputs(
        **{
            **inputs.__dict__,
            "bridge_items": inputs.bridge_items[:-1],
            "comps_policy": CompsPolicy(
                basis=ValuationBasis.NTM,
                target_period_key="FY1",
                approved_multiples=("pe",),
            ),
        }
    )
    pe_only_bundle = build_professional_valuation_bundles(
        (_model_result(),),
        pe_only_inputs,
    )[0]
    assert pe_only_bundle.state.status is AvailabilityStatus.BLOCKING
    pe_only = _method(pe_only_bundle, ValuationMethod.COMPS)
    assert pe_only.state.status is AvailabilityStatus.AVAILABLE
    assert pe_only.metrics["pe_implied_per_share"] is not None
    assert "ev_revenue_implied_per_share" not in pe_only.metrics


def test_comps_reject_mixed_basis_instead_of_silently_combining_ltm_and_ntm() -> None:
    inputs = _inputs()
    mixed = (*inputs.peer_facts, *_peers(basis=ValuationBasis.LTM))
    mixed_inputs = ProfessionalValuationInputs(**{**inputs.__dict__, "peer_facts": mixed})
    bundle = build_professional_valuation_bundles((_model_result(),), mixed_inputs)[0]
    comps = _method(bundle, ValuationMethod.COMPS)
    assert comps.metrics["basis_label"] == "NTM"
    assert comps.metrics["excluded_basis_peer_count"] == 6


def test_historical_range_and_sotp_are_typed_unavailable_until_supported() -> None:
    bundle = build_professional_valuation_bundles((_model_result(),), _inputs())[0]
    historical = _method(bundle, ValuationMethod.HISTORICAL_RANGE)
    sotp = _method(bundle, ValuationMethod.SOTP)
    assert historical.state.status is AvailabilityStatus.UNAVAILABLE
    assert historical.state.reason_code == "historical_range_not_supplied"
    assert sotp.state.status is AvailabilityStatus.UNAVAILABLE
    assert sotp.state.reason_code == "sotp_not_supplied"

    ineligible = SOTPInput(
        components=(
            SOTPComponent("Cloud", 500.0, 8.0, ("sotp:cloud",)),
            SOTPComponent("Devices", 100.0, 4.0, ("sotp:devices",)),
        ),
        segment_economics_complete=True,
        peer_mapping_complete=False,
        allocations_complete=True,
    )
    ineligible_bundle = build_professional_valuation_bundles(
        (_model_result(),), _inputs(sotp=ineligible)
    )[0]
    assert _method(ineligible_bundle, ValuationMethod.SOTP).state.reason_code == "sotp_peer_mapping_incomplete"


def test_supported_historical_range_and_sotp_are_calculated_without_cross_method_blend() -> None:
    historical = HistoricalTradingRangeInput(
        low_value_per_share=8.0,
        median_value_per_share=12.0,
        high_value_per_share=16.0,
        period_start=date(2021, 1, 1),
        period_end=date(2025, 12, 31),
        basis_label="NTM EV/Revenue observed range",
        source_refs=("history:range",),
    )
    sotp = SOTPInput(
        components=(
            SOTPComponent("Cloud", 500.0, 8.0, ("sotp:cloud",)),
            SOTPComponent("Devices", 100.0, 4.0, ("sotp:devices",)),
        ),
        segment_economics_complete=True,
        peer_mapping_complete=True,
        allocations_complete=True,
    )
    bundle = build_professional_valuation_bundles(
        (_model_result(),), _inputs(historical=historical, sotp=sotp)
    )[0]
    history_result = _method(bundle, ValuationMethod.HISTORICAL_RANGE)
    sotp_result = _method(bundle, ValuationMethod.SOTP)
    assert history_result.value_per_share == 12.0
    assert history_result.low_value_per_share == 8.0
    assert history_result.high_value_per_share == 16.0
    assert sotp_result.value_per_share == pytest.approx((4_400.0 - 25.0) / 100.0)
    assert sotp_result.metrics["segment_count"] == 2
    assert history_result.metrics["method_role"] == "historical_context"
    assert sotp_result.metrics["method_role"] == "segment_sum"
    assert (
        _method(bundle, ValuationMethod.FCFF_DCF).metrics["method_role"]
        == "intrinsic_enterprise_value"
    )
    assert (
        _method(bundle, ValuationMethod.FCFE).metrics["method_role"]
        == "levered_cash_flow_cross_check"
    )
    assert (
        _method(bundle, ValuationMethod.REVERSE_DCF).metrics["method_role"]
        == "market_implied_diagnostic"
    )
    assert (
        _method(bundle, ValuationMethod.COMPS).metrics["method_role"]
        == "trading_comps_range"
    )
    assert all(
        method.metrics["method_aggregation_policy"] == "none"
        for method in bundle.valuation_methods
    )
    dumped = bundle.model_dump(mode="json")
    assert "probability" not in str(dumped).lower()
    assert "blended_target" not in str(dumped).lower()


def test_missing_core_fcff_or_selected_wacc_fails_closed() -> None:
    missing_fcff = build_professional_valuation_bundles(
        (_model_result(include_fcff=False),), _inputs()
    )[0]
    assert missing_fcff.state.status is AvailabilityStatus.BLOCKING
    assert _method(missing_fcff, ValuationMethod.FCFF_DCF).state.reason_code == "fcff_line_unavailable"

    unavailable_wacc = _unavailable("wacc_missing")
    missing_wacc = build_professional_valuation_bundles(
        (_model_result(),), _inputs(wacc_state=unavailable_wacc)
    )[0]
    assert missing_wacc.state.status is AvailabilityStatus.BLOCKING
    assert _method(missing_wacc, ValuationMethod.FCFF_DCF).state.reason_code == "selected_wacc_unavailable"
    assert (
        _method(missing_wacc, ValuationMethod.FCFE).state.status
        is AvailabilityStatus.AVAILABLE
    )
    assert (
        _method(missing_wacc, ValuationMethod.REVERSE_DCF).state.status
        is AvailabilityStatus.UNAVAILABLE
    )

    inputs = _inputs()
    debt_missing_inputs = ProfessionalValuationInputs(
        **{
            **inputs.__dict__,
            "bridge_items": tuple(
                item
                for item in inputs.bridge_items
                if item.category is not BridgeCategory.DEBT
            ),
        }
    )
    debt_missing = build_professional_valuation_bundles(
        (_model_result(),),
        debt_missing_inputs,
    )[0]
    assert debt_missing.state.status is AvailabilityStatus.BLOCKING
    debt_missing_fcfe = _method(debt_missing, ValuationMethod.FCFE)
    assert debt_missing_fcfe.state.status is AvailabilityStatus.AVAILABLE
    assert debt_missing_fcfe.metrics["fcff_dcf_calculation_available"] is False


def test_module_dependency_isolation_is_opt_in_and_global_fail_closed_by_default() -> None:
    inputs = _inputs()
    comps_dependency = ModuleDependency(
        dependency_id="source.comps_peer_set",
        provider_module="sources",
        consumer_module=ValuationMethod.COMPS.value,
        scope=DependencyScope.MODULE_SCOPED,
        scope_proof_refs=("scope_proof:comps_peer_set",),
    )
    comps_blocker = ModuleBlocker(
        blocker_id="blocker.comps_peer_set",
        module_id=ValuationMethod.COMPS.value,
        dependency_ids=(comps_dependency.dependency_id,),
        scope=DependencyScope.MODULE_SCOPED,
        scope_proof_refs=("blocker_proof:comps_peer_set",),
    )
    default_inputs = ProfessionalValuationInputs(
        **{
            **inputs.__dict__,
            "module_dependencies": (comps_dependency,),
            "module_blockers": (comps_blocker,),
        }
    )
    default_bundle = build_professional_valuation_bundles(
        (_model_result(),),
        default_inputs,
    )[0]
    assert default_bundle.state.status is AvailabilityStatus.BLOCKING
    assert "module_blocker:blocker.comps_peer_set" in default_bundle.blockers
    assert (
        _method(default_bundle, ValuationMethod.FCFF_DCF).metrics[
            "dependency_scoping_policy"
        ]
        == "global_fail_closed"
    )

    isolated_inputs = ProfessionalValuationInputs(
        **{
            **inputs.__dict__,
            "allow_module_scoped_dependency_isolation": True,
            "module_dependencies": (comps_dependency,),
            "module_blockers": (comps_blocker,),
        }
    )
    isolated_bundle = build_professional_valuation_bundles(
        (_model_result(),),
        isolated_inputs,
    )[0]
    assert isolated_bundle.state.status is AvailabilityStatus.AVAILABLE
    assert (
        _method(isolated_bundle, ValuationMethod.FCFF_DCF).state.status
        is AvailabilityStatus.AVAILABLE
    )
    isolated_comps = _method(isolated_bundle, ValuationMethod.COMPS)
    assert isolated_comps.state.status is AvailabilityStatus.BLOCKING
    assert isolated_comps.state.reason_code == "method_dependency_blocking"
    assert (
        isolated_comps.metrics["nonavailable_dependency_ids"]
        == "source.comps_peer_set"
    )
    assert "module_scoped_dependency_isolation_enabled" in isolated_bundle.warnings

    unproven_blocker = ModuleBlocker(
        blocker_id="blocker.unproven_comps",
        module_id=ValuationMethod.COMPS.value,
        scope=DependencyScope.UNPROVEN,
    )
    unproven_inputs = ProfessionalValuationInputs(
        **{
            **inputs.__dict__,
            "allow_module_scoped_dependency_isolation": True,
            "module_blockers": (unproven_blocker,),
        }
    )
    unproven_bundle = build_professional_valuation_bundles(
        (_model_result(),),
        unproven_inputs,
    )[0]
    assert unproven_bundle.state.status is AvailabilityStatus.BLOCKING
    assert "module_blocker:blocker.unproven_comps" in unproven_bundle.blockers

    price_dependency = ModuleDependency(
        dependency_id="source.current_price",
        provider_module="sources",
        consumer_module=ValuationMethod.REVERSE_DCF.value,
        scope=DependencyScope.MODULE_SCOPED,
        scope_proof_refs=("scope_proof:current_price",),
    )
    price_blocker = ModuleBlocker(
        blocker_id="blocker.current_price",
        module_id=ValuationMethod.REVERSE_DCF.value,
        dependency_ids=(price_dependency.dependency_id,),
        scope=DependencyScope.MODULE_SCOPED,
        scope_proof_refs=("blocker_proof:current_price",),
    )
    first_order = ProfessionalValuationInputs(
        **{
            **inputs.__dict__,
            "allow_module_scoped_dependency_isolation": True,
            "module_dependencies": (
                comps_dependency,
                price_dependency,
            ),
            "module_blockers": (comps_blocker, price_blocker),
        }
    )
    second_order = ProfessionalValuationInputs(
        **{
            **inputs.__dict__,
            "allow_module_scoped_dependency_isolation": True,
            "module_dependencies": (
                price_dependency,
                comps_dependency,
            ),
            "module_blockers": (price_blocker, comps_blocker),
        }
    )
    assert build_professional_valuation_bundles(
        (_model_result(),),
        first_order,
    )[0].canonical_bytes() == build_professional_valuation_bundles(
        (_model_result(),),
        second_order,
    )[0].canonical_bytes()


def test_sensitivity_grid_and_bundle_hash_are_deterministic() -> None:
    first = build_professional_valuation_bundles((_model_result(),), _inputs())[0]
    second = build_professional_valuation_bundles((_model_result(),), _inputs())[0]
    assert first.bundle_hash == second.bundle_hash
    assert first.canonical_bytes() == second.canonical_bytes()
    sensitivity = first.sensitivities[0]
    assert sensitivity.state.status is AvailabilityStatus.AVAILABLE
    assert sensitivity.outputs["valid_cell_count"] == 9
    assert len([key for key in sensitivity.outputs if key.startswith("value_per_share__")]) == 9


def test_reverse_dcf_can_solve_market_implied_terminal_fcff_margin() -> None:
    inputs = _inputs()
    margin_policy = ReverseDCFPolicy(
        variable=ReverseDCFVariable.TERMINAL_FCFF_MARGIN,
        lower_bound=-0.25,
        upper_bound=0.50,
        fixed_terminal_growth=_sourced(0.025, "policy:reverse_fixed_growth"),
    )
    margin_inputs = ProfessionalValuationInputs(
        **{**inputs.__dict__, "reverse_dcf_policy": margin_policy}
    )
    bundle = build_professional_valuation_bundles((_model_result(),), margin_inputs)[0]
    reverse = _method(bundle, ValuationMethod.REVERSE_DCF)
    assert reverse.state.status is AvailabilityStatus.AVAILABLE
    assert reverse.metrics["solve_variable"] == "terminal_fcff_margin"
    assert reverse.metrics["replay_value_per_share"] == pytest.approx(10.0, abs=1e-8)


def test_all_scenarios_are_valued_independently_and_sorted_deterministically() -> None:
    inputs = _inputs()
    bear_policy = ScenarioValuationPolicy(
        scenario_key="Bear",
        forecast_period_keys=("FY1", "FY2", "FY3"),
        terminal_growth=_sourced(0.01, "policy:bear_terminal_growth"),
        discount_timing=DiscountTiming.END_YEAR,
    )
    multi_inputs = ProfessionalValuationInputs(
        **{**inputs.__dict__, "scenario_policies": (*inputs.scenario_policies, bear_policy)}
    )
    bundles = build_professional_valuation_bundles(
        (_model_result("Base"), _model_result("Bear", fcff=(80.0, 82.0, 84.0), fcfe=(69.0, 70.0, 71.0))),
        multi_inputs,
    )
    assert tuple(bundle.scenario_key for bundle in bundles) == ("Base", "Bear")
    base_value = _method(bundles[0], ValuationMethod.FCFF_DCF).value_per_share
    bear_value = _method(bundles[1], ValuationMethod.FCFF_DCF).value_per_share
    assert bear_value < base_value
    assert bundles[0].bundle_hash != bundles[1].bundle_hash


def test_reversed_forecast_periods_and_incomplete_bridge_fail_closed() -> None:
    inputs = _inputs()
    reversed_policy = ScenarioValuationPolicy(
        scenario_key="Base",
        forecast_period_keys=("FY3", "FY2", "FY1"),
        terminal_growth=_sourced(0.03, "policy:terminal_growth"),
    )
    reversed_inputs = ProfessionalValuationInputs(
        **{**inputs.__dict__, "scenario_policies": (reversed_policy,)}
    )
    reversed_bundle = build_professional_valuation_bundles((_model_result(),), reversed_inputs)[0]
    assert reversed_bundle.state.status is AvailabilityStatus.BLOCKING
    assert _method(reversed_bundle, ValuationMethod.FCFF_DCF).state.reason_code == "forecast_period_axis_invalid"

    skipped_policy = ScenarioValuationPolicy(
        scenario_key="Base",
        forecast_period_keys=("FY1", "FY3"),
        terminal_growth=_sourced(0.03, "policy:terminal_growth"),
    )
    skipped_inputs = ProfessionalValuationInputs(
        **{**inputs.__dict__, "scenario_policies": (skipped_policy,)}
    )
    skipped_bundle = build_professional_valuation_bundles(
        (_model_result(),),
        skipped_inputs,
    )[0]
    assert skipped_bundle.state.status is AvailabilityStatus.BLOCKING
    assert (
        _method(skipped_bundle, ValuationMethod.FCFF_DCF).state.reason_code
        == "forecast_period_axis_invalid"
    )

    incomplete_inputs = ProfessionalValuationInputs(
        **{**inputs.__dict__, "bridge_items": inputs.bridge_items[:-1]}
    )
    incomplete_bundle = build_professional_valuation_bundles((_model_result(),), incomplete_inputs)[0]
    assert incomplete_bundle.state.status is AvailabilityStatus.BLOCKING
    assert "bridge_missing:other_claims" in incomplete_bundle.blockers


def test_bridge_sign_is_operation_driven_and_negative_amounts_are_rejected() -> None:
    with pytest.raises(ValueError, match="bridge amounts must be non-negative"):
        BridgeValue(
            category=BridgeCategory.DEBT,
            amount=_sourced(-1.0, "source:negative_debt"),
            claim_ids=("atomic:debt",),
        )
