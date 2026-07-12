from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from src.contracts.professional_financial_model import (
    AvailabilityState,
    AvailabilityStatus,
    BridgeItem,
    CellClassification,
    CellKind,
    CheckResult,
    CheckStatus,
    DefinedNameMapping,
    DriverYearValue,
    EstimateStatus,
    FactFormulaStatus,
    InputValue,
    LineCellMapping,
    LineItemSpec,
    LineSeries,
    ModelInputSnapshot,
    ModelPeriod,
    ModelResult,
    NormalizedActual,
    PeriodAxis,
    PeriodType,
    PeriodValue,
    PROFESSIONAL_MODEL_CONTRACT_VERSION,
    PROFESSIONAL_WORKBOOK_SHEETS,
    ScenarioDriverPath,
    ScenarioInputSet,
    ScheduleResult,
    SourceFact,
    SourceManifest,
    StatementResult,
    SupplementalInputFact,
    SupplementalInputSnapshot,
    UnitKind,
    ValuationBundle,
    ValuationMethod,
    ValuationMethodResult,
    WACCMethodResult,
    WorkbookCheckCell,
    WorkbookManifest,
    WorkbookSourceIdentity,
)


from src.contracts.professional_financial_model import (
    CalculationVerificationRecord,
    ConsensusMappingMethod,
    ConsensusObservation,
    ConsensusPeriodType,
    ConsensusSnapshot,
    ConsensusStatistic,
    CurrentFullyDilutedSharesEvidence,
    DCFDiscountPeriodEvidence,
    DCFParameterGovernance,
    DCFParameterName,
    DCFParameterScope,
    DCFScenarioGovernance,
    DCFStubBridge,
    WACCMethodologyEvidence,
    WACCParityEvidence,
    DecisionEligibility,
    DependencyScope,
    DriverApprovalRecord,
    DriverApprovalState,
    DriverGroup,
    MethodAvailability,
    MethodDecisionStatus,
    ModuleBlocker,
    ModuleDependency,
    ModuleWorkflow,
    SourcePresentationRecord,
    WorkflowGate,
    WorkflowState,
    aggregate_package_workflow,
    aggregate_workflow_state,
)

SHA_A = "a" * 64
SHA_B = "b" * 64


def _available() -> AvailabilityState:
    return AvailabilityState(status=AvailabilityStatus.AVAILABLE)


def _source_fact(
    *,
    row: int = 3,
    column: int = 2,
    currency: str | None = "USD",
    ciq_run_id: int = 7,
) -> SourceFact:
    locator = f"B{row}"
    fact_id = SourceFact.stable_fact_id(
        ticker="MSFT",
        ciq_run_id=ciq_run_id,
        source_hash=SHA_A,
        workbook_sheet="Financial Statements",
        row_index=row,
        column_index=column,
    )
    return SourceFact(
        fact_id=fact_id,
        ticker="msft",
        ciq_run_id=ciq_run_id,
        source_file="MSFT_Standard.xlsx",
        source_path=r"C:\licensed\MSFT_Standard.xlsx",
        source_hash=SHA_A,
        workbook_sheet="Financial Statements",
        section="Income Statement",
        row_index=row,
        column_index=column,
        cell_locator=locator,
        row_label="Revenues",
        canonical_key="revenue",
        period_end=date(2025, 6, 30),
        period_type=PeriodType.FISCAL_YEAR,
        estimate_status=EstimateStatus.ACTUAL,
        formula_text="=SUM(B1:B2)",
        cached_value=0.0,
        displayed_value="0.0",
        formula_status=FactFormulaStatus.CALCULATED,
        calculation_type="FY25",
        unit="USD mm",
        unit_kind=UnitKind.CURRENCY,
        scale=1_000_000.0,
        currency=currency,
        dimensions={"segment": "Consolidated"},
        quality_state=_available(),
    )


def _supplemental_fact(key: str, value: float, **overrides) -> SupplementalInputFact:
    payload = {
        "field_key": key,
        "value": value,
        "state": _available(),
        "unit": "x",
        "unit_kind": UnitKind.MULTIPLE,
        "source_name": "CIQ Standard",
        "source_locator": f"Detailed Comps!{key}",
        "as_of_date": date(2026, 7, 11),
    }
    payload.update(overrides)
    return SupplementalInputFact(**payload)


def _supplemental_snapshot(*, fact_order: tuple[str, ...] | None = None) -> SupplementalInputSnapshot:
    keys = fact_order or (
        "current_price",
        "market_cap",
        "beta",
        "risk_free_rate",
        "equity_risk_premium",
        "total_debt",
        "cost_of_debt",
        "fx_rate",
    )
    facts = []
    for key in keys:
        overrides = {}
        if key in {"current_price", "market_cap", "total_debt"}:
            overrides = {"unit": "USD", "unit_kind": UnitKind.CURRENCY, "currency": "USD"}
        if key == "beta":
            overrides["method"] = "peer_median"
        if key == "risk_free_rate":
            overrides["duration"] = "10Y"
        facts.append(_supplemental_fact(key, 1.0, **overrides))
    return SupplementalInputSnapshot(
        ticker="MSFT",
        valuation_date=date(2026, 7, 11),
        currency="USD",
        peer_universe_version="ciq-msft-2026-07-11",
        peer_tickers=("ORCL", "GOOGL"),
        facts=tuple(facts),
    )


def _source_manifest(supplemental_hash: str) -> SourceManifest:
    return SourceManifest(
        ticker="MSFT",
        fiscal_convention="June year-end",
        workbook=WorkbookSourceIdentity(
            ticker="MSFT",
            source_file="MSFT_Standard.xlsx",
            source_path=r"C:\licensed\MSFT_Standard.xlsx",
            source_hash=SHA_A,
            file_modified_at=datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc),
            workbook_as_of_date=date(2026, 7, 11),
            fiscal_period_end=date(2026, 3, 31),
            currency="USD",
            unit_convention="USD mm",
            state=_available(),
        ),
        selected_ciq_run_id=7,
        parser_version="ibm_standard_v3",
        fact_count=1,
        fact_status_counts={"available": 1},
        supplemental_snapshot_hash=supplemental_hash,
    )


def _approved_assumption(key: str, value: float) -> InputValue:
    return InputValue(
        key=key,
        value=value,
        state=_available(),
        unit="%",
        unit_kind=UnitKind.PERCENT,
        source_ref="valuation-policy:2026-07-11",
        approval_ref="pm-decision:42",
    )


def _model_input_snapshot() -> ModelInputSnapshot:
    supplemental = _supplemental_snapshot()
    source_fact = _source_fact()
    manifest = _source_manifest(supplemental.snapshot_hash)
    return ModelInputSnapshot(
        ticker="MSFT",
        fiscal_calendar="June year-end",
        currency="USD",
        source_manifest=manifest,
        selected_ciq_run_id=7,
        source_facts=(source_fact,),
        line_item_registry_version="registry-v1",
        normalized_actuals=(
            NormalizedActual(
                canonical_key="revenue",
                period_key="FY25",
                period_end=date(2025, 6, 30),
                value=0.0,
                unit="USD mm",
                unit_kind=UnitKind.CURRENCY,
                currency="USD",
                source_fact_ids=(source_fact.fact_id,),
                state=_available(),
            ),
        ),
        approved_assumptions=(_approved_assumption("terminal_growth", 0.03),),
        supplemental_input_snapshot=supplemental,
        supplemental_input_hash=supplemental.snapshot_hash,
    )


def _period_axis() -> PeriodAxis:
    return PeriodAxis(
        periods=(
            ModelPeriod(index=1, key="FY27", end_date=date(2027, 6, 30), period_type=PeriodType.FISCAL_YEAR),
            ModelPeriod(index=2, key="FY28", end_date=date(2028, 6, 30), period_type=PeriodType.FISCAL_YEAR),
        )
    )


def _line_series(line_key: str, values: tuple[float, float]) -> LineSeries:
    return LineSeries(
        line_key=line_key,
        method_id="driver:revenue-growth",
        values=tuple(
            PeriodValue(period_key=period_key, value=value, state=_available(), formula_id=f"formula:{line_key}")
            for period_key, value in zip(("FY27", "FY28"), values, strict=True)
        ),
    )


def _model_result(input_hash: str) -> ModelResult:
    return ModelResult(
        scenario_key="base",
        state=_available(),
        period_axis=_period_axis(),
        statements=(
            StatementResult(statement_key="income_statement", lines=(_line_series("revenue", (100.0, 110.0)),)),
        ),
        supporting_schedules=(
            ScheduleResult(schedule_key="working_capital", lines=(_line_series("accounts_receivable", (10.0, 11.0)),)),
        ),
        check_results=(CheckResult(check_id="statement_tie", status=CheckStatus.PASS, difference=0.0, tolerance=0.1),),
        tolerances={"statement_tie": 0.1},
        warnings=(),
        blockers=(),
        input_hash=input_hash,
    )


def _valuation_methods() -> tuple[ValuationMethodResult, ...]:
    methods = []
    for method in ValuationMethod:
        if method in {ValuationMethod.FCFF_DCF, ValuationMethod.REVERSE_DCF, ValuationMethod.COMPS}:
            methods.append(
                ValuationMethodResult(
                    method=method,
                    state=_available(),
                    value_per_share=100.0,
                    metrics={"basis": "source-backed"},
                    source_refs=("model-result:base",),
                )
            )
        else:
            methods.append(
                ValuationMethodResult(
                    method=method,
                    state=AvailabilityState(
                        status=AvailabilityStatus.UNAVAILABLE,
                        reason_code=f"{method.value}_not_supported",
                        message="Required source evidence is unavailable",
                    ),
                )
            )
    return tuple(methods)


def test_source_fact_round_trip_preserves_formula_zero_and_exact_provenance() -> None:
    fact = _source_fact()

    restored = SourceFact.model_validate_json(fact.model_dump_json())

    assert restored == fact
    assert restored.ticker == "MSFT"
    assert restored.cached_value == 0.0
    assert restored.formula_text == "=SUM(B1:B2)"
    assert restored.cell_locator == "B3"
    assert restored.fact_id == SourceFact.stable_fact_id(
        ticker="MSFT",
        ciq_run_id=7,
        source_hash=SHA_A,
        workbook_sheet="Financial Statements",
        row_index=3,
        column_index=2,
    )


def test_source_fact_rejects_unknown_version_bad_locator_and_currency_mismatch() -> None:
    payload = _source_fact().model_dump(mode="json")
    payload["contract_version"] = "99.0.0"
    with pytest.raises(ValidationError):
        SourceFact.model_validate(payload)

    payload = _source_fact().model_dump(mode="json")
    payload["cell_locator"] = "C3"
    with pytest.raises(ValidationError, match="cell_locator"):
        SourceFact.model_validate(payload)

    payload = _source_fact().model_dump(mode="json")
    payload["unit_kind"] = "percent"
    with pytest.raises(ValidationError, match="currency"):
        SourceFact.model_validate(payload)


def test_manifest_and_supplemental_snapshot_hashes_are_canonical_and_bound() -> None:
    ordered = _supplemental_snapshot()
    reversed_order = _supplemental_snapshot(fact_order=tuple(reversed(tuple(f.field_key for f in ordered.facts))))

    assert ordered.canonical_json() == reversed_order.canonical_json()
    assert ordered.snapshot_hash == reversed_order.snapshot_hash

    manifest_a = _source_manifest(ordered.snapshot_hash)
    manifest_b = SourceManifest.model_validate(manifest_a.model_dump(mode="json"))
    assert manifest_a.canonical_json() == manifest_b.canonical_json()
    assert manifest_a.manifest_hash == manifest_b.manifest_hash

    bad = manifest_a.model_dump(mode="json")
    bad["manifest_hash"] = SHA_B
    with pytest.raises(ValidationError, match="manifest_hash"):
        SourceManifest.model_validate(bad)


def test_supplemental_snapshot_requires_frozen_wacc_market_and_fx_facts() -> None:
    snapshot = _supplemental_snapshot()
    payload = snapshot.model_dump(mode="json")
    payload["facts"] = [fact for fact in payload["facts"] if fact["field_key"] != "beta"]
    payload["snapshot_hash"] = None

    with pytest.raises(ValidationError, match="required supplemental facts"):
        SupplementalInputSnapshot.model_validate(payload)

    bad_beta = next(fact for fact in snapshot.facts if fact.field_key == "beta").model_dump(mode="json")
    bad_beta["method"] = None
    with pytest.raises(ValidationError, match="method"):
        SupplementalInputFact.model_validate(bad_beta)

    duplicate_peers = snapshot.model_dump(mode="json")
    duplicate_peers["peer_tickers"] = ["ORCL", "orcl"]
    duplicate_peers["snapshot_hash"] = None
    with pytest.raises(ValidationError, match="duplicate peer tickers"):
        SupplementalInputSnapshot.model_validate(duplicate_peers)


def test_model_input_snapshot_rejects_duplicate_facts_mixed_runs_and_unapproved_assumptions() -> None:
    model_input = _model_input_snapshot()

    duplicate = model_input.model_copy(update={"source_facts": (model_input.source_facts[0], model_input.source_facts[0]), "content_hash": None})
    with pytest.raises(ValidationError, match="duplicate source fact IDs"):
        ModelInputSnapshot.model_validate(duplicate.model_dump(mode="json"))

    other_run = _source_fact(ciq_run_id=8)
    mixed = model_input.model_copy(update={"source_facts": (other_run,), "content_hash": None})
    with pytest.raises(ValidationError, match="selected CIQ run"):
        ModelInputSnapshot.model_validate(mixed.model_dump(mode="json"))

    unapproved = InputValue(
        key="terminal_growth",
        state=AvailabilityState(
            status=AvailabilityStatus.PM_REQUIRED,
            reason_code="pm_policy_open",
            message="PM approval is required",
        ),
        unit="%",
        unit_kind=UnitKind.PERCENT,
    )
    bad_assumption = model_input.model_copy(update={"approved_assumptions": (unapproved,), "content_hash": None})
    with pytest.raises(ValidationError, match="approved assumptions"):
        ModelInputSnapshot.model_validate(bad_assumption.model_dump(mode="json"))

    available_but_unapproved = InputValue(
        key="terminal_growth",
        value=0.03,
        state=_available(),
        unit="%",
        unit_kind=UnitKind.PERCENT,
        source_ref="analyst-draft:1",
    )
    missing_approval = model_input.model_copy(
        update={"approved_assumptions": (available_but_unapproved,), "content_hash": None}
    )
    with pytest.raises(ValidationError, match="approval_ref"):
        ModelInputSnapshot.model_validate(missing_approval.model_dump(mode="json"))

    expanded_manifest = SourceManifest.model_validate(
        model_input.source_manifest.model_copy(
            update={"fact_count": 2, "fact_status_counts": {"available": 2}, "manifest_hash": None}
        ).model_dump(mode="json")
    )
    count_mismatch = model_input.model_copy(
        update={"source_manifest": expanded_manifest, "content_hash": None}
    )
    with pytest.raises(ValidationError, match="source fact count"):
        ModelInputSnapshot.model_validate(count_mismatch.model_dump(mode="json"))


def test_model_input_snapshot_is_byte_stable_under_unordered_input() -> None:
    snapshot = _model_input_snapshot()
    supplemental = _supplemental_snapshot(fact_order=tuple(reversed(tuple(f.field_key for f in snapshot.supplemental_input_snapshot.facts))))
    rebuilt = snapshot.model_copy(
        update={
            "supplemental_input_snapshot": supplemental,
            "supplemental_input_hash": supplemental.snapshot_hash,
            "content_hash": None,
        }
    )
    rebuilt = ModelInputSnapshot.model_validate(rebuilt.model_dump(mode="json"))

    assert snapshot.content_hash == rebuilt.content_hash
    assert snapshot.canonical_json() == rebuilt.canonical_json()


def test_line_item_spec_requires_explicit_missing_policy_and_dependencies() -> None:
    spec = LineItemSpec(
        canonical_key="revenue",
        display_label="Revenue",
        statement_or_schedule="income_statement",
        sign_convention="positive_credit",
        source_mappings=("Revenues", "Total Revenues"),
        required=True,
        material=True,
        historical_aggregation_rule="latest_for_period",
        forecast_method="segment_growth",
        dependencies=("segment_revenue",),
        scenario_drivers=("revenue_growth",),
        presentation_order=10,
        missing_data_policy=AvailabilityStatus.PM_REQUIRED,
    )
    assert spec.missing_data_policy is AvailabilityStatus.PM_REQUIRED

    with pytest.raises(ValidationError):
        LineItemSpec.model_validate({**spec.model_dump(mode="json"), "missing_data_policy": "guess"})


def test_scenario_has_no_probability_and_represents_pm_required_inputs_explicitly() -> None:
    pm_required = InputValue(
        key="ebit_margin_target",
        state=AvailabilityState(
            status=AvailabilityStatus.PM_REQUIRED,
            reason_code="margin_policy_open",
            message="PM must approve the terminal margin path",
        ),
        unit="%",
        unit_kind=UnitKind.PERCENT,
    )
    scenario = ScenarioInputSet(
        scenario_key="base",
        parent_scenario_key=None,
        state=AvailabilityState(
            status=AvailabilityStatus.PM_REQUIRED,
            reason_code="scenario_incomplete",
            message="One or more drivers require PM approval",
        ),
        required_driver_keys=("revenue_growth", "ebit_margin_target"),
        driver_values=(pm_required,),
        year_paths=(
            ScenarioDriverPath(
                driver_key="revenue_growth",
                values=(
                    DriverYearValue(year=1, value=0.10, state=_available(), source_ref="consensus:FY27"),
                    DriverYearValue(year=2, value=0.08, state=_available(), source_ref="model-fade:FY28"),
                ),
            ),
        ),
        approved_overrides=(),
        evidence_queue_ids=("pmq:42",),
        provenance={"source": "model-input"},
    )
    assert scenario.state.status is AvailabilityStatus.PM_REQUIRED

    payload = scenario.model_dump(mode="json")
    payload["probability"] = 0.60
    with pytest.raises(ValidationError, match="probability"):
        ScenarioInputSet.model_validate(payload)

    payload = scenario.model_dump(mode="json")
    payload["state"] = {"status": "available"}
    with pytest.raises(ValidationError, match="PM_REQUIRED"):
        ScenarioInputSet.model_validate(payload)


def test_model_result_rejects_incomplete_period_axes_and_binds_result_hash() -> None:
    result = _model_result(SHA_A)
    restored = ModelResult.model_validate_json(result.model_dump_json())
    assert restored.result_hash == result.result_hash
    assert restored.canonical_json() == result.canonical_json()

    payload = result.model_dump(mode="json")
    payload["statements"][0]["lines"][0]["values"] = payload["statements"][0]["lines"][0]["values"][:1]
    payload["result_hash"] = None
    with pytest.raises(ValidationError, match="period axis"):
        ModelResult.model_validate(payload)


def test_valuation_bundle_requires_every_method_as_available_or_typed_unavailable() -> None:
    model_input = _model_input_snapshot()
    result = _model_result(model_input.content_hash)
    bundle = ValuationBundle(
        scenario_key="base",
        state=AvailabilityState(
            status=AvailabilityStatus.BLOCKING,
            reason_code="policy_gates_open",
            message="Diagnostic valuation only",
        ),
        input_hash=model_input.content_hash,
        result_hash=result.result_hash,
        wacc_methods=(
            WACCMethodResult(
                method_id="peer_bottom_up",
                state=AvailabilityState(
                    status=AvailabilityStatus.UNAVAILABLE,
                    reason_code="beta_missing",
                    message="No source-backed beta",
                ),
                selected=True,
            ),
        ),
        selected_wacc_policy="peer_bottom_up",
        valuation_methods=_valuation_methods(),
        peer_universe_version="ciq-msft-2026-07-11",
        peer_tickers=("GOOGL", "ORCL"),
        terminal_value_diagnostics={"basis": "NTM"},
        ev_equity_bridge=(BridgeItem(key="net_debt", amount=47_204.0, operation="subtract", source_refs=("fact:net-debt",)),),
        sensitivities=(),
        implied_per_share_reconciliation=CheckResult(
            check_id="per_share_tie",
            status=CheckStatus.PASS,
            difference=0.0,
            tolerance=0.01,
        ),
        blockers=("policy_gates_open",),
    )
    sotp = next(item for item in bundle.valuation_methods if item.method is ValuationMethod.SOTP)
    assert sotp.state.status is AvailabilityStatus.UNAVAILABLE

    payload = bundle.model_dump(mode="json")
    payload["probability_weighted_value"] = 110.0
    with pytest.raises(ValidationError, match="probability_weighted_value"):
        ValuationBundle.model_validate(payload)

    payload = bundle.model_dump(mode="json")
    payload["valuation_methods"] = payload["valuation_methods"][:-1]
    payload["bundle_hash"] = None
    with pytest.raises(ValidationError, match="valuation methods"):
        ValuationBundle.model_validate(payload)

    payload = bundle.model_dump(mode="json")
    payload["valuation_methods"][0]["metrics"]["scenario_probability"] = 0.60
    payload["bundle_hash"] = None
    with pytest.raises(ValidationError, match="probability-weighted valuation"):
        ValuationBundle.model_validate(payload)


def test_workbook_manifest_has_fixed_sheet_order_unique_cells_and_stable_hash() -> None:
    manifest = WorkbookManifest(
        ticker="MSFT",
        source_hash=SHA_A,
        model_input_hash=SHA_B,
        result_hash="c" * 64,
        sheet_order=PROFESSIONAL_WORKBOOK_SHEETS,
        line_cell_mappings=(
            LineCellMapping(canonical_key="revenue", scenario_key="base", period_key="FY27", sheet="Income_Statement", cell="F10"),
        ),
        cell_classifications=(
            CellClassification(sheet="Income_Statement", cell="F10", kind=CellKind.FORMULA),
        ),
        defined_names=(DefinedNameMapping(name="Model_Revenue_FY27", sheet="Income_Statement", cell="F10"),),
        check_cells=(WorkbookCheckCell(check_id="balance_sheet", sheet="Checks", cell="B10"),),
        renderer_version="artifact-tool-1",
        recalculation_state=AvailabilityState(
            status=AvailabilityStatus.BLOCKING,
            reason_code="recalculation_not_run",
            message="Diagnostic workbook has not passed deterministic recalc",
        ),
        parity_results=(CheckResult(check_id="backend_iv", status=CheckStatus.PASS, difference=0.0, tolerance=0.01),),
        blockers=("recalculation_not_run",),
    )
    assert WorkbookManifest.model_validate_json(manifest.model_dump_json()).manifest_hash == manifest.manifest_hash

    bad_order = manifest.model_dump(mode="json")
    bad_order["sheet_order"] = list(reversed(bad_order["sheet_order"]))
    bad_order["manifest_hash"] = None
    with pytest.raises(ValidationError, match="sheet_order"):
        WorkbookManifest.model_validate(bad_order)

    duplicate = manifest.model_dump(mode="json")
    duplicate["cell_classifications"].append(duplicate["cell_classifications"][0])
    duplicate["manifest_hash"] = None
    with pytest.raises(ValidationError, match="duplicate cell classifications"):
        WorkbookManifest.model_validate(duplicate)


def test_contract_version_constant_is_stable() -> None:
    assert PROFESSIONAL_MODEL_CONTRACT_VERSION == "1.0.0"
@pytest.mark.parametrize(
    ("statuses", "expected"),
    (
        ((), WorkflowState.UNVERIFIED),
        (("PASS",), WorkflowState.FULL),
        ((" pass ",), WorkflowState.FULL),
        (("",), WorkflowState.UNVERIFIED),
        ((None,), WorkflowState.UNVERIFIED),
        (("UNKNOWN",), WorkflowState.UNVERIFIED),
        (("READY",), WorkflowState.UNVERIFIED),
        (("CALCULATED",), WorkflowState.UNVERIFIED),
        (("DEGRADED",), WorkflowState.BLOCKED),
        (("UNAVAILABLE",), WorkflowState.BLOCKED),
        (("REVIEW",), WorkflowState.NEEDS_PM_REVIEW),
        (("PM_REQUIRED",), WorkflowState.NEEDS_PM_REVIEW),
        (("PASS", "UNKNOWN"), WorkflowState.PARTIAL),
        (("PASS", "PARTIAL"), WorkflowState.PARTIAL),
        (("PASS", "REVIEW"), WorkflowState.NEEDS_PM_REVIEW),
        (("PASS", "FAIL"), WorkflowState.BLOCKED),
        (("PASS", "PASS"), WorkflowState.FULL),
    ),
)
def test_workflow_state_truth_table_is_positive_pass_only(
    statuses: tuple[str | None, ...],
    expected: WorkflowState,
) -> None:
    aggregation = aggregate_workflow_state(statuses)

    assert aggregation.state is expected
    assert aggregation.required_gate_count == len(statuses)
    if expected is WorkflowState.FULL:
        assert len(aggregation.passed_gate_ids) == len(statuses)


def test_workflow_gates_ignore_optional_evidence_but_never_infer_full_from_nothing() -> None:
    optional_failure = WorkflowGate(
        gate_id="diagnostic",
        module_id="valuation",
        reported_status="FAIL",
        required_for_full=False,
    )
    assert aggregate_workflow_state((optional_failure,)).state is WorkflowState.UNVERIFIED

    duplicate = WorkflowGate(
        gate_id="required",
        module_id="valuation",
        reported_status="PASS",
    )
    with pytest.raises(ValueError, match="duplicate required"):
        aggregate_workflow_state((duplicate, duplicate))


def _passing_module(module_id: str, *, required: bool) -> ModuleWorkflow:
    return ModuleWorkflow(
        module_id=module_id,
        gates=(
            WorkflowGate(
                gate_id=f"{module_id}:gate",
                module_id=module_id,
                reported_status="PASS",
            ),
        ),
        required_for_package_full=required,
    )


def test_module_scoping_requires_dependency_proof_and_preserves_global_full_gate() -> None:
    modules = (
        _passing_module("core", required=True),
        _passing_module("source", required=False),
        _passing_module("sotp", required=False),
    )
    dependency = ModuleDependency(
        dependency_id="segment-source",
        provider_module="source",
        consumer_module="sotp",
        scope=DependencyScope.MODULE_SCOPED,
        required_for_package_full=False,
        scope_proof_refs=("contract:segment-only",),
    )
    blocker = ModuleBlocker(
        blocker_id="segments-unavailable",
        module_id="sotp",
        dependency_ids=("segment-source",),
        scope=DependencyScope.MODULE_SCOPED,
        scope_proof_refs=("classification:segments",),
    )

    scoped = aggregate_package_workflow(
        modules,
        dependencies=(dependency,),
        blockers=(blocker,),
    )
    assert scoped.module_states["sotp"] is WorkflowState.BLOCKED
    assert scoped.state is WorkflowState.FULL
    assert scoped.global_blocker_ids == ()

    unproved = blocker.model_copy(
        update={"dependency_ids": ("unknown-dependency",)}
    )
    global_result = aggregate_package_workflow(
        modules,
        dependencies=(dependency,),
        blockers=(unproved,),
    )
    assert global_result.state is WorkflowState.BLOCKED
    assert global_result.global_blocker_ids == ("segments-unavailable",)

    required_dependency = dependency.model_copy(
        update={"required_for_package_full": True}
    )
    required_result = aggregate_package_workflow(
        modules,
        dependencies=(required_dependency,),
        blockers=(blocker,),
    )
    assert required_result.state is WorkflowState.BLOCKED
    assert "sotp" in required_result.required_modules


def test_module_scoped_contracts_reject_unproved_classification() -> None:
    with pytest.raises(ValidationError, match="scope proof"):
        ModuleDependency(
            dependency_id="d1",
            provider_module="source",
            consumer_module="sotp",
            scope=DependencyScope.MODULE_SCOPED,
        )
    with pytest.raises(ValidationError, match="dependencies and deterministic scope proof"):
        ModuleBlocker(
            blocker_id="b1",
            module_id="sotp",
            scope=DependencyScope.MODULE_SCOPED,
        )


def test_method_availability_is_separate_from_decision_eligibility() -> None:
    pass_gate = WorkflowGate(
        gate_id="valuation-policy",
        module_id="valuation",
        reported_status="PASS",
    )
    eligible = MethodDecisionStatus(
        availability=MethodAvailability.AVAILABLE,
        decision_eligibility=DecisionEligibility.ELIGIBLE,
        required_gates=(pass_gate,),
    )
    assert eligible.decision_eligibility is DecisionEligibility.ELIGIBLE

    with pytest.raises(ValidationError, match="every decision gate"):
        MethodDecisionStatus(
            availability=MethodAvailability.AVAILABLE,
            decision_eligibility=DecisionEligibility.ELIGIBLE,
        )
    with pytest.raises(ValidationError, match="fully available"):
        MethodDecisionStatus(
            availability=MethodAvailability.DEGRADED,
            decision_eligibility=DecisionEligibility.ELIGIBLE,
            required_gates=(pass_gate,),
        )

    legacy_available = ValuationMethodResult(
        method=ValuationMethod.FCFF_DCF,
        state=_available(),
        value_per_share=100.0,
    )
    assert legacy_available.decision_status is not None
    assert legacy_available.decision_status.availability is MethodAvailability.AVAILABLE
    assert (
        legacy_available.decision_status.decision_eligibility
        is DecisionEligibility.UNVERIFIED
    )
    with pytest.raises(ValidationError, match="identify method availability"):
        ValuationMethodResult(
            method=ValuationMethod.FCFF_DCF,
            state=_available(),
            value_per_share=100.0,
            decision_status=MethodDecisionStatus(
                availability=MethodAvailability.UNAVAILABLE,
                decision_eligibility=DecisionEligibility.INELIGIBLE,
            ),
        )



def _approved_driver_record() -> DriverApprovalRecord:
    return DriverApprovalRecord(
        driver_key="terminal_growth",
        scenario_key="Base",
        driver_group=DriverGroup.FINANCE_SEMANTIC,
        current_driver_fingerprint=SHA_A,
        approved_driver_fingerprint=SHA_A,
        approval_state=DriverApprovalState.APPROVED,
        approval_ref="pm-decision:42",
        approved_by="pm",
        approved_at=datetime(2026, 7, 12, 10, 0, tzinfo=timezone.utc),
    )


def test_driver_approval_fingerprint_stales_without_auto_approval_or_revival() -> None:
    mechanical = DriverApprovalRecord(
        driver_key="days_in_year",
        driver_group=DriverGroup.MECHANICAL,
        current_driver_fingerprint=SHA_A,
    )
    assert mechanical.approval_state is DriverApprovalState.UNAPPROVED

    approved = _approved_driver_record()
    assert approved.approval_state is DriverApprovalState.APPROVED
    assert approved.record_hash is not None

    stale = approved.with_current_fingerprint(SHA_B)
    assert stale.approval_state is DriverApprovalState.STALE
    assert stale.record_hash != approved.record_hash

    reverted = stale.with_current_fingerprint(SHA_A)
    assert reverted.approval_state is DriverApprovalState.STALE

    constructed_stale = DriverApprovalRecord(
        **{
            **approved.model_dump(mode="python"),
            "current_driver_fingerprint": SHA_B,
            "record_hash": None,
        }
    )
    assert constructed_stale.approval_state is DriverApprovalState.STALE

    with pytest.raises(ValidationError, match="approval metadata"):
        DriverApprovalRecord(
            driver_key="terminal_growth",
            driver_group=DriverGroup.FINANCE_SEMANTIC,
            current_driver_fingerprint=SHA_A,
            approved_driver_fingerprint=SHA_A,
            approval_state=DriverApprovalState.APPROVED,
        )


    blank_metadata = approved.model_dump(mode="python")
    blank_metadata["approval_ref"] = " "
    blank_metadata["record_hash"] = None
    with pytest.raises(ValidationError, match="approval_ref"):
        DriverApprovalRecord.model_validate(blank_metadata)

def test_source_presentation_keeps_raw_normalized_derived_and_error_layers_distinct() -> None:
    record = SourcePresentationRecord(
        source_id="fact:revenue",
        canonical_key="revenue",
        raw_value=1_000_000_000.0,
        normalized_value=1_000.0,
        derived_value=1_100.0,
        transform="raw / 1e6; derived = normalized * fx",
        unit="USD mm",
        unit_kind=UnitKind.CURRENCY,
        scale=1_000_000.0,
        currency="USD",
        period_type=PeriodType.FISCAL_YEAR,
        period_start=date(2024, 7, 1),
        period_end=date(2025, 6, 30),
        formula_status=FactFormulaStatus.CALCULATED,
        source_refs=("fact:revenue",),
        downstream_dependencies=("income_statement.revenue", "dcf.fcff"),
        state=_available(),
    )
    assert record.raw_value == 1_000_000_000.0
    assert record.normalized_value == 1_000.0
    assert record.derived_value == 1_100.0
    assert record.downstream_dependencies == ("dcf.fcff", "income_statement.revenue")

    payload = record.model_dump(mode="python")
    payload["period_start"] = None
    with pytest.raises(ValidationError, match="exact start and end"):
        SourcePresentationRecord.model_validate(payload)

    payload = record.model_dump(mode="python")
    payload["formula_status"] = FactFormulaStatus.ERROR
    with pytest.raises(ValidationError, match="error details"):
        SourcePresentationRecord.model_validate(payload)


def _calculation_verification(**updates) -> CalculationVerificationRecord:
    payload = {
        "workbook_sha256": SHA_A,
        "model_input_hash": SHA_B,
        "workbook_model_input_hash": SHA_B,
        "model_input_hash_parity": CheckStatus.PASS,
        "precalculation_formula_text_hash": SHA_A,
        "formula_text_expectation_bound": True,
        "formula_text_hash": SHA_A,
        "expected_formula_text_hash": SHA_A,
        "formula_text_parity": CheckStatus.PASS,
        "formula_count": 10,
        "cached_formula_count": 10,
        "cache_population": CheckStatus.PASS,
        "formula_error_count": 0,
        "formula_error_scan": CheckStatus.PASS,
        "engine": "Microsoft Excel",
        "engine_version": "16.0",
        "calculation_completed": True,
        "verified_at": datetime(2026, 7, 12, 10, 0, tzinfo=timezone.utc),
    }
    payload.update(updates)
    return CalculationVerificationRecord(**payload)


@pytest.mark.parametrize(
    ("updates", "expected"),
    (
        ({}, WorkflowState.FULL),
        ({"calculation_completed": False}, WorkflowState.PARTIAL),
        ({"formula_text_expectation_bound": False}, WorkflowState.PARTIAL),
        ({"model_input_hash_parity": CheckStatus.FAIL}, WorkflowState.BLOCKED),
        ({"formula_text_parity": CheckStatus.REVIEW}, WorkflowState.NEEDS_PM_REVIEW),
        ({"formula_text_parity": CheckStatus.FAIL}, WorkflowState.BLOCKED),
        ({"cache_population": CheckStatus.BLOCKED}, WorkflowState.BLOCKED),
        ({"formula_error_scan": CheckStatus.FAIL}, WorkflowState.BLOCKED),
    ),
)
def test_calculation_verification_state_is_derived_from_positive_evidence(
    updates: dict[str, object],
    expected: WorkflowState,
) -> None:
    record = _calculation_verification(
        **updates,
        verification_state=WorkflowState.FULL,
    )
    assert record.verification_state is expected


def test_calculation_verification_rejects_false_passes_and_binds_hash() -> None:
    with pytest.raises(ValidationError, match="matching formula hashes"):
        _calculation_verification(formula_text_hash=SHA_B)
    with pytest.raises(ValidationError, match="model-input PASS"):
        _calculation_verification(workbook_model_input_hash="c" * 64)
    with pytest.raises(ValidationError, match="every formula cache"):
        _calculation_verification(cached_formula_count=9)
    with pytest.raises(ValidationError, match="zero formula errors"):
        _calculation_verification(
            formula_error_count=1,
            formula_errors=("Checks!B5:#REF!",),
        )
    with pytest.raises(ValidationError, match="timezone-aware"):
        _calculation_verification(verified_at=datetime(2026, 7, 12, 10, 0))

    record = _calculation_verification()
    payload = record.model_dump(mode="python")
    payload["engine_version"] = "17.0"
    with pytest.raises(ValidationError, match="verification_hash"):
        CalculationVerificationRecord.model_validate(payload)


def _minimal_workbook_manifest(
    *,
    recalculated: bool,
    parity_status: CheckStatus = CheckStatus.PASS,
    verification: CalculationVerificationRecord | None = None,
) -> WorkbookManifest:
    return WorkbookManifest(
        ticker="MSFT",
        source_hash=SHA_A,
        model_input_hash=SHA_B,
        result_hash="c" * 64,
        sheet_order=PROFESSIONAL_WORKBOOK_SHEETS,
        line_cell_mappings=(),
        cell_classifications=(),
        defined_names=(),
        check_cells=(),
        renderer_version="artifact-tool-1",
        recalculation_state=(
            _available()
            if recalculated
            else AvailabilityState(
                status=AvailabilityStatus.BLOCKING,
                reason_code="recalculation_not_verified",
                message="Native calculation verification is required",
            )
        ),
        parity_results=(
            CheckResult(check_id="backend_parity", status=parity_status),
        ),
        calculation_verification=verification,
        expected_formula_text_hash=SHA_A,
        blockers=() if recalculated else ("recalculation_not_verified",),
    )


def test_workbook_availability_requires_full_calculation_record_and_positive_parity() -> None:
    verified = _minimal_workbook_manifest(
        recalculated=True,
        verification=_calculation_verification(),
    )
    assert verified.recalculation_state.status is AvailabilityStatus.AVAILABLE

    with pytest.raises(ValidationError, match="FULL calculation verification"):
        _minimal_workbook_manifest(recalculated=True, verification=None)
    with pytest.raises(ValidationError, match="positive parity PASS"):
        _minimal_workbook_manifest(
            recalculated=True,
            parity_status=CheckStatus.REVIEW,
            verification=_calculation_verification(),
        )
    mismatched_baseline = verified.model_dump(mode="python")
    mismatched_baseline["expected_formula_text_hash"] = "c" * 64
    mismatched_baseline["manifest_hash"] = None
    with pytest.raises(ValidationError, match="formula baseline mismatch"):
        WorkbookManifest.model_validate(mismatched_baseline)

def _eligible_method(module_id: str) -> MethodDecisionStatus:
    return MethodDecisionStatus(
        availability=MethodAvailability.AVAILABLE,
        decision_eligibility=DecisionEligibility.ELIGIBLE,
        required_gates=(
            WorkflowGate(
                gate_id=f"{module_id}:source",
                module_id=module_id,
                reported_status="PASS",
            ),
        ),
    )


def _consensus_observation(
    observation_id: str,
    *,
    metric: str = "REVENUE",
    source_metric: str | None = None,
    period_type: ConsensusPeriodType = ConsensusPeriodType.FY,
    period_end: date = date(2027, 6, 30),
    d_and_a_ref: str | None = None,
) -> ConsensusObservation:
    source_metric = source_metric or metric
    transformation = (
        "EBITDA minus consensus D&A"
        if source_metric == "EBITDA" and metric == "EBIT"
        else "identity"
    )
    return ConsensusObservation(
        observation_id=observation_id,
        metric=metric,
        source_metric=source_metric,
        statistic=ConsensusStatistic.MEAN,
        value=100.0,
        value_state=_available(),
        method_status=_eligible_method("consensus"),
        period_type=period_type,
        period_label=f"{period_type.value} observation",
        period_end=period_end,
        unit="USD mm",
        unit_kind=UnitKind.CURRENCY,
        scale=1_000_000.0,
        currency="USD",
        analyst_count=12,
        analyst_count_state=_available(),
        source_name="Capital IQ",
        source_locator=f"Consensus!{observation_id}",
        source_as_of_date=date(2026, 7, 12),
        transformation=transformation,
        consensus_d_and_a_observation_id=d_and_a_ref,
    )


@pytest.mark.parametrize("period_type", tuple(ConsensusPeriodType))
def test_consensus_observation_preserves_exact_period_type_and_end_date(
    period_type: ConsensusPeriodType,
) -> None:
    end = date(2027, 12, 31)
    observation = _consensus_observation(
        f"revenue:{period_type.value}",
        period_type=period_type,
        period_end=end,
    )

    assert observation.period_type is period_type
    assert observation.period_end == end
    assert observation.analyst_count == 12
    assert observation.source_locator.startswith("Consensus!")


def test_consensus_rejects_calendar_fiscal_alias_and_non_exact_mapping() -> None:
    observation = _consensus_observation(
        "revenue:cy27",
        period_type=ConsensusPeriodType.CY,
        period_end=date(2027, 12, 31),
    )
    payload = observation.model_dump(mode="python")
    payload["mapping_method"] = "CY_PLUS_ONE_TO_FY1"
    with pytest.raises(ValidationError, match=r"CY\+1 to FY1"):
        ConsensusObservation.model_validate(payload)

    payload = observation.model_dump(mode="python")
    payload.update(
        {
            "mapping_method": ConsensusMappingMethod.EXACT_PERIOD_END,
            "mapped_model_period_key": "FY28",
            "mapped_model_period_end": date(2028, 6, 30),
        }
    )
    with pytest.raises(ValidationError, match="exact source period end"):
        ConsensusObservation.model_validate(payload)


def test_consensus_ebitda_to_ebit_requires_same_period_available_consensus_da() -> None:
    ebit = _consensus_observation(
        "ebit:fy27",
        metric="EBIT",
        source_metric="EBITDA",
        d_and_a_ref="da:fy27",
    )
    d_and_a = _consensus_observation(
        "da:fy27",
        metric="D_AND_A",
    )
    snapshot = ConsensusSnapshot(
        ticker="MSFT",
        as_of_date=date(2026, 7, 12),
        source_name="Capital IQ",
        source_snapshot_locator="run:consensus:42",
        observations=(ebit, d_and_a),
    )
    assert snapshot.snapshot_hash is not None

    payload = ebit.model_dump(mode="python")
    payload["consensus_d_and_a_observation_id"] = None
    with pytest.raises(ValidationError, match="requires a consensus D&A"):
        ConsensusObservation.model_validate(payload)

    with pytest.raises(ValidationError, match="unknown consensus D&A"):
        ConsensusSnapshot(
            ticker="MSFT",
            as_of_date=date(2026, 7, 12),
            source_name="Capital IQ",
            source_snapshot_locator="run:consensus:42",
            observations=(ebit,),
        )

    wrong_period_da = _consensus_observation(
        "da:fy27",
        metric="D_AND_A",
        period_end=date(2028, 6, 30),
    )
    with pytest.raises(ValidationError, match="periods/statistics must match"):
        ConsensusSnapshot(
            ticker="MSFT",
            as_of_date=date(2026, 7, 12),
            source_name="Capital IQ",
            source_snapshot_locator="run:consensus:42",
            observations=(ebit, wrong_period_da),
        )


def test_consensus_decision_eligibility_requires_analyst_availability() -> None:
    observation = _consensus_observation("revenue:fy27")
    payload = observation.model_dump(mode="python")
    payload["analyst_count"] = None
    payload["analyst_count_state"] = {
        "status": AvailabilityStatus.UNAVAILABLE,
        "reason_code": "analyst_count_missing",
        "message": "Analyst coverage count is not source-backed",
    }
    with pytest.raises(ValidationError, match="decision-eligible consensus"):
        ConsensusObservation.model_validate(payload)


def _stub_bridge() -> DCFStubBridge:
    return DCFStubBridge(
        bridge_id="base:fy26",
        scenario_key="Base",
        annual_period_start=date(2025, 7, 1),
        annual_period_end=date(2026, 6, 30),
        ytd_period_start=date(2025, 7, 1),
        ytd_period_end=date(2026, 3, 31),
        stub_period_start=date(2026, 4, 1),
        stub_period_end=date(2026, 6, 30),
        annual_fcff=120.0,
        ytd_fcff=90.0,
        stub_fcff=30.0,
        unit="USD mm",
        unit_kind=UnitKind.CURRENCY,
        currency="USD",
        source_refs=("historical:YTD", "forecast:Q4-stub"),
    )


def test_dcf_stub_bridge_enforces_contiguous_annual_ytd_plus_stub() -> None:
    bridge = _stub_bridge()
    assert bridge.reconciliation_status is CheckStatus.PASS

    payload = bridge.model_dump(mode="python")
    payload["annual_fcff"] = 121.0
    with pytest.raises(ValidationError, match="YTD FCFF plus stub FCFF"):
        DCFStubBridge.model_validate(payload)

    payload = bridge.model_dump(mode="python")
    payload["stub_period_start"] = date(2026, 4, 2)
    with pytest.raises(ValidationError, match="contiguous YTD plus fiscal stub"):
        DCFStubBridge.model_validate(payload)


def test_dcf_discount_period_requires_exact_dated_act365_midpoint() -> None:
    valuation_at = datetime(2026, 3, 31, tzinfo=timezone.utc)
    period_start = datetime(2026, 4, 1, tzinfo=timezone.utc)
    period_end = datetime(2026, 6, 30, tzinfo=timezone.utc)
    midpoint = period_start + (period_end - period_start) / 2
    years = (midpoint - valuation_at).total_seconds() / (365 * 24 * 60 * 60)
    evidence = DCFDiscountPeriodEvidence(
        period_id="base:stub",
        scenario_key="Base",
        valuation_at=valuation_at,
        cash_flow_period_start_at=period_start,
        cash_flow_period_end_at=period_end,
        cash_flow_midpoint_at=midpoint,
        discount_period_years=years,
        source_refs=("calendar:MSFT-FY26",),
    )
    assert evidence.day_count_convention == "ACT/365"

    payload = evidence.model_dump(mode="python")
    payload["discount_period_years"] = 1.0
    with pytest.raises(ValidationError, match="ACT/365 midpoint timing"):
        DCFDiscountPeriodEvidence.model_validate(payload)

    payload = evidence.model_dump(mode="python")
    payload["cash_flow_midpoint_at"] = midpoint + timedelta(days=1)
    with pytest.raises(ValidationError, match="exact dated midpoint"):
        DCFDiscountPeriodEvidence.model_validate(payload)


def _governed_parameter(
    parameter: DCFParameterName,
    value: float,
    *,
    scope: DCFParameterScope = DCFParameterScope.SCENARIO_SPECIFIC,
    approval: DriverApprovalRecord | None = None,
) -> DCFParameterGovernance:
    return DCFParameterGovernance(
        parameter=parameter,
        scenario_key="Base",
        value=value,
        driver_fingerprint=SHA_A,
        scope=scope,
        shared_scenario_keys=("Base", "Upside", "Downside")
        if scope is DCFParameterScope.SHARED_APPROVED
        else (),
        approval_record=approval,
        source_refs=(f"policy:{parameter.value}",),
    )


def test_dcf_governance_requires_explicit_shared_approval_and_wacc_above_g() -> None:
    approval = DriverApprovalRecord(
        driver_key="shared_wacc",
        driver_group=DriverGroup.FINANCE_SEMANTIC,
        current_driver_fingerprint=SHA_A,
        approved_driver_fingerprint=SHA_A,
        approval_state=DriverApprovalState.APPROVED,
        approval_ref="pm-decision:wacc",
        approved_by="pm",
        approved_at=datetime(2026, 7, 12, tzinfo=timezone.utc),
    )
    shared_wacc = _governed_parameter(
        DCFParameterName.WACC,
        0.10,
        scope=DCFParameterScope.SHARED_APPROVED,
        approval=approval,
    )
    governance = DCFScenarioGovernance(
        scenario_key="Base",
        parameters=(
            shared_wacc,
            _governed_parameter(DCFParameterName.TERMINAL_GROWTH, 0.03),
            _governed_parameter(DCFParameterName.TAX_RATE, 0.20),
        ),
    )
    assert governance.governance_hash is not None

    with pytest.raises(ValidationError, match="matching PM approval"):
        _governed_parameter(
            DCFParameterName.WACC,
            0.10,
            scope=DCFParameterScope.SHARED_APPROVED,
        )

    bad_wacc = _governed_parameter(DCFParameterName.WACC, 0.02)
    with pytest.raises(ValidationError, match="WACC greater than terminal growth"):
        DCFScenarioGovernance(
            scenario_key="Base",
            parameters=(
                bad_wacc,
                _governed_parameter(DCFParameterName.TERMINAL_GROWTH, 0.03),
                _governed_parameter(DCFParameterName.TAX_RATE, 0.20),
            ),
        )


def test_current_fds_is_positive_dated_and_source_backed() -> None:
    evidence = CurrentFullyDilutedSharesEvidence(
        shares=7_432.0,
        as_of_date=date(2026, 3, 31),
        valuation_date=date(2026, 7, 12),
        unit="shares mm",
        scale=1_000_000.0,
        source_name="Capital IQ",
        source_locator="Market Data!FDS",
        source_refs=("fact:current-fds",),
        state=_available(),
        method_status=_eligible_method("current_fds"),
    )
    assert evidence.shares > 0

    payload = evidence.model_dump(mode="python")
    payload["shares"] = 0.0
    with pytest.raises(ValidationError):
        CurrentFullyDilutedSharesEvidence.model_validate(payload)

    payload = evidence.model_dump(mode="python")
    payload["as_of_date"] = date(2026, 8, 1)
    with pytest.raises(ValidationError, match="cannot exceed valuation date"):
        CurrentFullyDilutedSharesEvidence.model_validate(payload)


def test_wacc_methodology_is_immutable_and_parity_is_capped_at_one_basis_point() -> None:
    methodology = WACCMethodologyEvidence(
        methodology_id="peer_bottom_up",
        methodology_version="v2",
        as_of_date=date(2026, 7, 12),
        output_wacc=0.10,
        inputs={"risk_free_rate": 0.04, "equity_risk_premium": 0.05},
        source_refs=("market:risk-free", "peers:beta"),
        method_status=_eligible_method("wacc"),
    )
    assert methodology.methodology_hash is not None

    one_bp = WACCParityEvidence(
        methodology_id="peer_bottom_up",
        methodology_version="v2",
        methodology_hash=methodology.methodology_hash,
        as_of_date=date(2026, 7, 12),
        backend_wacc=0.10,
        workbook_wacc=0.1001,
        backend_source_ref="backend:wacc",
        workbook_sheet="WACC",
        workbook_cell="B12",
    )
    assert one_bp.parity_status is CheckStatus.PASS
    assert one_bp.difference_basis_points == pytest.approx(1.0)

    over_one_bp = one_bp.model_copy(
        update={"workbook_wacc": 0.1001001}
    )
    over_one_bp = WACCParityEvidence.model_validate(
        {
            **over_one_bp.model_dump(mode="python"),
            "parity_status": CheckStatus.PASS,
        }
    )
    assert over_one_bp.parity_status is CheckStatus.FAIL

    with pytest.raises(ValidationError):
        WACCParityEvidence(
            methodology_id="peer_bottom_up",
            methodology_version="v2",
            methodology_hash=methodology.methodology_hash,
            as_of_date=date(2026, 7, 12),
            backend_wacc=0.10,
            workbook_wacc=0.10,
            tolerance_basis_points=1.01,
            backend_source_ref="backend:wacc",
            workbook_sheet="WACC",
            workbook_cell="B12",
        )
