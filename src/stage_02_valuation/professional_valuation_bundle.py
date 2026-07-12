"""Deterministic, source-frozen multi-method valuation for model v2.

This module is deliberately retrieval-free. It accepts frozen ``ModelResult``
objects plus explicit, source-backed valuation inputs and produces the strict
``ValuationBundle`` contract. Missing evidence is never coerced to zero and no
cross-method probability weighting, blended target, or recommendation is
calculated.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
import math
from statistics import median
from typing import Iterable, Mapping, Sequence

from src.contracts.professional_financial_model import (
    AvailabilityState,
    AvailabilityStatus,
    BridgeItem,
    CheckResult,
    CheckStatus,
    DecisionEligibility,
    DependencyScope,
    LineSeries,
    MethodAvailability,
    MethodDecisionStatus,
    ModelResult,
    ModuleBlocker,
    ModuleDependency,
    PeriodValue,
    SensitivityResult,
    ValuationBundle,
    ValuationMethod,
    ValuationMethodResult,
    WACCMethodResult,
    WorkflowGate,
)


FCFF_LINE_KEY = "cf.unlevered_fcf"
TERMINAL_SHARES_LINE_KEY = "shares.diluted_weighted_average"
REVENUE_LINE_KEY = "is.revenue"
EBITDA_LINE_KEY = "is.ebitda"
NET_INCOME_LINE_KEY = "is.net_income_common"
CFO_LINE_KEY = "cf.cash_from_operations"
NET_INCOME_COMPANY_LINE_KEY = "is.net_income_company"
NOPAT_LINE_KEY = "tax.nopat"
CAPEX_LINE_KEY = "cf.capex"


class DiscountTiming(str, Enum):
    END_YEAR = "end_year"
    MID_YEAR = "mid_year"


class ValuationBasis(str, Enum):
    LTM = "LTM"
    NTM = "NTM"


class ReverseDCFVariable(str, Enum):
    TERMINAL_GROWTH = "terminal_growth"
    TERMINAL_FCFF_MARGIN = "terminal_fcff_margin"


class BridgeCategory(str, Enum):
    CASH = "cash"
    SHORT_TERM_INVESTMENTS = "short_term_investments"
    LONG_TERM_INVESTMENTS = "long_term_investments"
    OTHER_NON_OPERATING_ASSETS = "other_non_operating_assets"
    DEBT = "debt"
    LEASE_LIABILITIES = "lease_liabilities"
    PREFERRED_STOCK = "preferred_stock"
    MINORITY_INTEREST = "minority_interest"
    PENSION_DEFICIT = "pension_deficit"
    OTHER_CLAIMS = "other_claims"


ADDITIVE_BRIDGE_CATEGORIES = frozenset(
    {
        BridgeCategory.CASH,
        BridgeCategory.SHORT_TERM_INVESTMENTS,
        BridgeCategory.LONG_TERM_INVESTMENTS,
        BridgeCategory.OTHER_NON_OPERATING_ASSETS,
    }
)
SUBTRACTIVE_BRIDGE_CATEGORIES = frozenset(set(BridgeCategory) - set(ADDITIVE_BRIDGE_CATEGORIES))


def _clean_refs(refs: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted({str(ref).strip() for ref in refs if str(ref).strip()}))


def _finite(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _clean_sha256(value: str, field_name: str) -> str:
    cleaned = str(value).strip().lower()
    if len(cleaned) != 64 or any(
        character not in "0123456789abcdef" for character in cleaned
    ):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 hex digest")
    return cleaned


def _available_state() -> AvailabilityState:
    return AvailabilityState(status=AvailabilityStatus.AVAILABLE)


def _unavailable_state(reason_code: str, message: str) -> AvailabilityState:
    return AvailabilityState(
        status=AvailabilityStatus.UNAVAILABLE,
        reason_code=reason_code,
        message=message,
    )


def _blocking_state(reason_code: str, message: str) -> AvailabilityState:
    return AvailabilityState(
        status=AvailabilityStatus.BLOCKING,
        reason_code=reason_code,
        message=message,
    )


@dataclass(frozen=True)
class SourcedValue:
    """A numeric value whose availability and exact lineage are explicit."""

    value: float | None
    state: AvailabilityState
    source_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        refs = _clean_refs(self.source_refs)
        object.__setattr__(self, "source_refs", refs)
        if self.state.status is AvailabilityStatus.AVAILABLE:
            if self.value is None or not _finite(self.value):
                raise ValueError("available sourced value requires a finite numeric value")
            if not refs:
                raise ValueError("available sourced value requires source_refs")
            object.__setattr__(self, "value", float(self.value))
        elif self.value is not None:
            raise ValueError("non-available sourced value cannot carry a value")


@dataclass(frozen=True)
class WACCMethodInput:
    method_id: str
    state: AvailabilityState
    wacc: float | None
    source_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        method_id = str(self.method_id).strip()
        refs = _clean_refs(self.source_refs)
        if not method_id:
            raise ValueError("WACC method_id is required")
        object.__setattr__(self, "method_id", method_id)
        object.__setattr__(self, "source_refs", refs)
        if self.state.status is AvailabilityStatus.AVAILABLE:
            if self.wacc is None or not _finite(self.wacc) or not 0.0 <= float(self.wacc) <= 1.0:
                raise ValueError("available WACC method requires wacc between zero and one")
            if not refs:
                raise ValueError("available WACC method requires source_refs")
            object.__setattr__(self, "wacc", float(self.wacc))
        elif self.wacc is not None:
            raise ValueError("non-available WACC method cannot carry wacc")


@dataclass(frozen=True)
class BridgeValue:
    category: BridgeCategory
    amount: SourcedValue
    claim_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        raw_claim_ids = tuple(str(claim_id).strip() for claim_id in self.claim_ids)
        if (
            not raw_claim_ids
            or any(not claim_id for claim_id in raw_claim_ids)
            or len(set(raw_claim_ids)) != len(raw_claim_ids)
        ):
            raise ValueError(
                "bridge value requires unique atomic claim_ids, including for explicit zero"
            )
        claim_ids = tuple(sorted(raw_claim_ids))
        object.__setattr__(self, "claim_ids", claim_ids)
        if (
            self.amount.state.status is AvailabilityStatus.AVAILABLE
            and self.amount.value is not None
            and self.amount.value < 0
        ):
            raise ValueError("bridge amounts must be non-negative; operation determines sign")


@dataclass(frozen=True)
class ScenarioValuationPolicy:
    scenario_key: str
    forecast_period_keys: tuple[str, ...]
    terminal_growth: SourcedValue
    discount_timing: DiscountTiming = DiscountTiming.END_YEAR
    fcff_identity_tolerance: float = 1e-6
    terminal_value_dominance_limit: SourcedValue | None = None

    def __post_init__(self) -> None:
        key = str(self.scenario_key).strip()
        periods = tuple(str(period).strip() for period in self.forecast_period_keys)
        if not key:
            raise ValueError("scenario_key is required")
        if not periods or any(not period for period in periods):
            raise ValueError("forecast_period_keys must be non-empty")
        if len(set(periods)) != len(periods):
            raise ValueError("forecast_period_keys contains duplicates")
        if not _finite(self.fcff_identity_tolerance) or self.fcff_identity_tolerance < 0:
            raise ValueError("fcff_identity_tolerance must be finite and non-negative")
        dominance_limit = self.terminal_value_dominance_limit
        if (
            dominance_limit is not None
            and dominance_limit.state.status is AvailabilityStatus.AVAILABLE
            and dominance_limit.value is not None
            and not 0.0 <= dominance_limit.value <= 1.0
        ):
            raise ValueError("terminal-value dominance limit must be between zero and one")
        object.__setattr__(self, "scenario_key", key)
        object.__setattr__(self, "forecast_period_keys", periods)
        object.__setattr__(self, "fcff_identity_tolerance", float(self.fcff_identity_tolerance))


@dataclass(frozen=True)
class MethodDecisionPolicy:
    """An explicit caller-supplied decision-use classification for one method."""

    method: ValuationMethod
    scenario_key: str
    status: DecisionEligibility
    reason_code: str
    message: str
    approved_input_hash: str | None = None
    approval_ref: str | None = None
    source_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        scenario_key = str(self.scenario_key).strip()
        reason_code = str(self.reason_code).strip()
        message = str(self.message).strip()
        approved_input_hash = (
            _clean_sha256(self.approved_input_hash, "approved_input_hash")
            if self.approved_input_hash is not None
            else None
        )
        approval_ref = str(self.approval_ref).strip() if self.approval_ref is not None else None
        source_refs = _clean_refs(self.source_refs)
        if not scenario_key or not reason_code or not message:
            raise ValueError(
                "method decision policy requires scenario_key, reason_code, and message"
            )
        if self.status is DecisionEligibility.ELIGIBLE:
            if not approval_ref or not source_refs or approved_input_hash is None:
                raise ValueError(
                    "eligible method decision policy requires approval_ref, "
                    "approved_input_hash, and source_refs"
                )
        elif approval_ref is not None or approved_input_hash is not None:
            raise ValueError(
                "non-eligible method decision policy cannot carry approval binding fields"
            )
        object.__setattr__(self, "scenario_key", scenario_key)
        object.__setattr__(self, "reason_code", reason_code)
        object.__setattr__(self, "message", message)
        object.__setattr__(self, "approved_input_hash", approved_input_hash)
        object.__setattr__(self, "approval_ref", approval_ref)
        object.__setattr__(self, "source_refs", source_refs)


@dataclass(frozen=True)
class FCFEPolicy:
    cost_of_equity: SourcedValue
    financing_claim_categories_reflected: tuple[BridgeCategory, ...]
    after_tax_interest_line_key: str = "debt.after_tax_interest"
    net_borrowing_line_key: str = "debt.net_borrowing"
    fcfe_line_key: str = "cf.levered_fcf"
    required_check_ids: tuple[str, ...] = (
        "debt_roll_forward",
        "interest_tie",
        "net_borrowing_tie",
    )
    reconciliation_tolerance: float = 1e-6

    def __post_init__(self) -> None:
        keys = (self.after_tax_interest_line_key, self.net_borrowing_line_key, self.fcfe_line_key)
        if any(not str(key).strip() for key in keys):
            raise ValueError("FCFE line keys are required")
        financing_categories = tuple(self.financing_claim_categories_reflected)
        supported_financing_categories = {
            BridgeCategory.DEBT,
            BridgeCategory.LEASE_LIABILITIES,
        }
        if (
            not financing_categories
            or len(set(financing_categories)) != len(financing_categories)
            or any(
                category not in supported_financing_categories
                for category in financing_categories
            )
        ):
            raise ValueError(
                "FCFE financing claim categories must explicitly and uniquely "
                "identify debt and/or lease liabilities reflected in the schedule"
            )
        checks = tuple(str(check).strip() for check in self.required_check_ids)
        if not checks or any(not check for check in checks) or len(set(checks)) != len(checks):
            raise ValueError("FCFE required_check_ids must be unique and non-empty")
        if not _finite(self.reconciliation_tolerance) or self.reconciliation_tolerance < 0:
            raise ValueError("FCFE reconciliation_tolerance must be finite and non-negative")
        object.__setattr__(self, "required_check_ids", checks)
        object.__setattr__(
            self,
            "financing_claim_categories_reflected",
            tuple(
                sorted(
                    financing_categories,
                    key=lambda category: list(BridgeCategory).index(category),
                )
            ),
        )


@dataclass(frozen=True)
class ReverseDCFPolicy:
    variable: ReverseDCFVariable
    lower_bound: float
    upper_bound: float
    fixed_terminal_growth: SourcedValue | None = None
    revenue_line_key: str = REVENUE_LINE_KEY
    solve_tolerance: float = 1e-10

    def __post_init__(self) -> None:
        if not _finite(self.lower_bound) or not _finite(self.upper_bound):
            raise ValueError("reverse DCF bounds must be finite")
        if float(self.lower_bound) >= float(self.upper_bound):
            raise ValueError("reverse DCF lower_bound must be below upper_bound")
        if not _finite(self.solve_tolerance) or self.solve_tolerance <= 0:
            raise ValueError("reverse DCF solve_tolerance must be positive")
        if self.variable is ReverseDCFVariable.TERMINAL_FCFF_MARGIN and self.fixed_terminal_growth is None:
            raise ValueError("terminal FCFF margin solve requires fixed_terminal_growth")
        if not str(self.revenue_line_key).strip():
            raise ValueError("reverse DCF revenue_line_key is required")


@dataclass(frozen=True)
class PeerValuationFact:
    ticker: str
    basis: ValuationBasis
    enterprise_value: float | None
    equity_value: float | None
    revenue: float | None
    ebitda: float | None
    net_income: float | None
    source_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        ticker = str(self.ticker).upper().strip()
        refs = _clean_refs(self.source_refs)
        if not ticker or not refs:
            raise ValueError("peer fact requires ticker and source_refs")
        for field_name in ("enterprise_value", "equity_value", "revenue", "ebitda", "net_income"):
            value = getattr(self, field_name)
            if value is not None:
                if not _finite(value):
                    raise ValueError(f"peer {field_name} must be finite when supplied")
                object.__setattr__(self, field_name, float(value))
        object.__setattr__(self, "ticker", ticker)
        object.__setattr__(self, "source_refs", refs)


@dataclass(frozen=True)
class CompsPolicy:
    basis: ValuationBasis
    target_period_key: str
    approved_multiples: tuple[str, ...] = ("ev_revenue", "ev_ebitda", "pe")
    outlier_iqr_multiplier: float = 1.5

    def __post_init__(self) -> None:
        supported = {"ev_revenue", "ev_ebitda", "pe"}
        period = str(self.target_period_key).strip()
        multiples = tuple(str(item).strip().lower() for item in self.approved_multiples)
        if not period or not multiples or any(item not in supported for item in multiples):
            raise ValueError("comps policy has a missing period or unsupported multiple")
        if len(set(multiples)) != len(multiples):
            raise ValueError("approved_multiples contains duplicates")
        if not _finite(self.outlier_iqr_multiplier) or self.outlier_iqr_multiplier <= 0:
            raise ValueError("outlier_iqr_multiplier must be positive")
        object.__setattr__(self, "target_period_key", period)
        object.__setattr__(self, "approved_multiples", multiples)


@dataclass(frozen=True)
class HistoricalTradingRangeInput:
    low_value_per_share: float
    median_value_per_share: float
    high_value_per_share: float
    period_start: date
    period_end: date
    basis_label: str
    source_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        values = (self.low_value_per_share, self.median_value_per_share, self.high_value_per_share)
        if any(not _finite(value) for value in values) or not values[0] <= values[1] <= values[2]:
            raise ValueError("historical range must contain finite low <= median <= high values")
        if self.period_start > self.period_end:
            raise ValueError("historical range dates are reversed")
        label = str(self.basis_label).strip()
        refs = _clean_refs(self.source_refs)
        if not label or not refs:
            raise ValueError("historical range requires basis_label and source_refs")
        object.__setattr__(self, "basis_label", label)
        object.__setattr__(self, "source_refs", refs)


@dataclass(frozen=True)
class SOTPComponent:
    segment_name: str
    metric_value: float
    selected_multiple: float
    source_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        name = str(self.segment_name).strip()
        refs = _clean_refs(self.source_refs)
        if not name or not refs or not _finite(self.metric_value) or not _finite(self.selected_multiple):
            raise ValueError("SOTP component requires a name, finite values, and source_refs")
        object.__setattr__(self, "segment_name", name)
        object.__setattr__(self, "metric_value", float(self.metric_value))
        object.__setattr__(self, "selected_multiple", float(self.selected_multiple))
        object.__setattr__(self, "source_refs", refs)


@dataclass(frozen=True)
class SOTPInput:
    components: tuple[SOTPComponent, ...]
    segment_economics_complete: bool
    peer_mapping_complete: bool
    allocations_complete: bool

    def __post_init__(self) -> None:
        names = [component.segment_name for component in self.components]
        if len(set(names)) != len(names):
            raise ValueError("duplicate SOTP segment names")


@dataclass(frozen=True)
class ProfessionalValuationInputs:
    ticker: str
    current_price: SourcedValue
    current_diluted_shares: SourcedValue
    bridge_items: tuple[BridgeValue, ...]
    wacc_methods: tuple[WACCMethodInput, ...]
    selected_wacc_policy: str
    scenario_policies: tuple[ScenarioValuationPolicy, ...]
    peer_universe_version: str
    method_decision_policies: tuple[MethodDecisionPolicy, ...] = ()
    module_dependencies: tuple[ModuleDependency, ...] = ()
    module_blockers: tuple[ModuleBlocker, ...] = ()
    allow_module_scoped_dependency_isolation: bool = False
    peer_facts: tuple[PeerValuationFact, ...] = ()
    comps_policy: CompsPolicy | None = None
    fcfe_policy: FCFEPolicy | None = None
    reverse_dcf_policy: ReverseDCFPolicy | None = None
    historical_range: HistoricalTradingRangeInput | None = None
    sotp_input: SOTPInput | None = None
    wacc_sensitivity_deltas: tuple[float, ...] = (-0.01, 0.0, 0.01)
    terminal_growth_sensitivity_deltas: tuple[float, ...] = (-0.01, 0.0, 0.01)

    def __post_init__(self) -> None:
        ticker = str(self.ticker).upper().strip()
        selected = str(self.selected_wacc_policy).strip()
        peer_version = str(self.peer_universe_version).strip()
        if not ticker or not selected or not peer_version:
            raise ValueError("ticker, selected_wacc_policy, and peer_universe_version are required")
        bridge_categories = [item.category for item in self.bridge_items]
        if len(set(bridge_categories)) != len(bridge_categories):
            raise ValueError("duplicate bridge categories")
        bridge_claim_ids = [
            claim_id
            for item in self.bridge_items
            for claim_id in item.claim_ids
        ]
        if len(set(bridge_claim_ids)) != len(bridge_claim_ids):
            raise ValueError("duplicate atomic claim IDs across EV-to-equity bridge categories")
        method_ids = [method.method_id for method in self.wacc_methods]
        if len(set(method_ids)) != len(method_ids):
            raise ValueError("duplicate WACC method IDs")
        if selected not in method_ids:
            raise ValueError("selected_wacc_policy must identify an input WACC method")
        scenarios = [policy.scenario_key for policy in self.scenario_policies]
        if len(set(scenarios)) != len(scenarios):
            raise ValueError("duplicate scenario valuation policies")
        peers = [(fact.ticker, fact.basis) for fact in self.peer_facts]
        if len(set(peers)) != len(peers):
            raise ValueError("duplicate peer facts for the same ticker and basis")
        decision_policy_keys = [
            (policy.scenario_key, policy.method)
            for policy in self.method_decision_policies
        ]
        if len(set(decision_policy_keys)) != len(decision_policy_keys):
            raise ValueError("duplicate method decision policies")
        unknown_decision_scenarios = sorted(
            {
                policy.scenario_key
                for policy in self.method_decision_policies
                if policy.scenario_key not in set(scenarios)
            }
        )
        if unknown_decision_scenarios:
            raise ValueError(
                "method decision policies reference unknown scenarios: "
                + ", ".join(unknown_decision_scenarios)
            )
        diagnostic_only_methods = {ValuationMethod.FCFE, ValuationMethod.REVERSE_DCF}
        if any(
            policy.method in diagnostic_only_methods
            and policy.status is DecisionEligibility.ELIGIBLE
            for policy in self.method_decision_policies
        ):
            raise ValueError("FCFE and reverse DCF are diagnostic methods and cannot be decision-eligible")
        module_blocker_ids = [blocker.blocker_id for blocker in self.module_blockers]
        if len(set(module_blocker_ids)) != len(module_blocker_ids):
            raise ValueError("duplicate valuation module blocker IDs")
        module_dependency_ids = [
            dependency.dependency_id for dependency in self.module_dependencies
        ]
        if len(set(module_dependency_ids)) != len(module_dependency_ids):
            raise ValueError("duplicate valuation module dependency IDs")
        supported_module_ids = {
            "valuation",
            *(method.value for method in ValuationMethod),
        }
        invalid_module_ids = sorted(
            {
                blocker.module_id
                for blocker in self.module_blockers
                if blocker.module_id not in supported_module_ids
                or (
                    blocker.scope is DependencyScope.MODULE_SCOPED
                    and blocker.module_id == "valuation"
                )
            }
        )
        if invalid_module_ids:
            raise ValueError(
                "valuation module blockers reference invalid module IDs: "
                + ", ".join(invalid_module_ids)
            )
        if not isinstance(self.allow_module_scoped_dependency_isolation, bool):
            raise ValueError("allow_module_scoped_dependency_isolation must be boolean")
        for name, values in (
            ("wacc_sensitivity_deltas", self.wacc_sensitivity_deltas),
            ("terminal_growth_sensitivity_deltas", self.terminal_growth_sensitivity_deltas),
        ):
            if not values or any(not _finite(value) for value in values):
                raise ValueError(f"{name} must contain finite values")
            if len(set(float(value) for value in values)) != len(values):
                raise ValueError(f"{name} contains duplicates")
        object.__setattr__(self, "ticker", ticker)
        object.__setattr__(self, "selected_wacc_policy", selected)
        object.__setattr__(self, "peer_universe_version", peer_version)
        object.__setattr__(
            self,
            "method_decision_policies",
            tuple(
                sorted(
                    self.method_decision_policies,
                    key=lambda policy: (
                        policy.scenario_key,
                        list(ValuationMethod).index(policy.method),
                    ),
                )
            ),
        )
        object.__setattr__(
            self,
            "module_dependencies",
            tuple(
                sorted(
                    self.module_dependencies,
                    key=lambda dependency: dependency.dependency_id,
                )
            ),
        )
        object.__setattr__(
            self,
            "module_blockers",
            tuple(
                sorted(
                    self.module_blockers,
                    key=lambda blocker: blocker.blocker_id,
                )
            ),
        )
        object.__setattr__(
            self,
            "wacc_sensitivity_deltas",
            tuple(float(value) for value in self.wacc_sensitivity_deltas),
        )
        object.__setattr__(
            self,
            "terminal_growth_sensitivity_deltas",
            tuple(float(value) for value in self.terminal_growth_sensitivity_deltas),
        )


@dataclass(frozen=True)
class _DCFComputation:
    fcff_values: tuple[float, ...]
    discount_exponents: tuple[float, ...]
    pv_explicit_fcff: float
    terminal_fcff_next: float
    terminal_value: float
    terminal_discount_exponent: float
    pv_terminal_value: float
    enterprise_value: float
    bridge_additions: float
    bridge_subtractions: float
    equity_value: float
    value_per_share: float
    terminal_shares: float | None
    source_refs: tuple[str, ...]


@dataclass(frozen=True)
class _FCFFOutcome:
    result: ValuationMethodResult
    computation: _DCFComputation | None
    blockers: tuple[str, ...]


@dataclass(frozen=True)
class _ValidatedFCFFForecast:
    values: tuple[float, ...] | None
    identity_max_abs_difference: float | None
    source_refs: tuple[str, ...]
    blockers: tuple[tuple[str, str], ...]


METHOD_ROLES: Mapping[ValuationMethod, str] = {
    ValuationMethod.FCFF_DCF: "intrinsic_enterprise_value",
    ValuationMethod.FCFE: "levered_cash_flow_cross_check",
    ValuationMethod.REVERSE_DCF: "market_implied_diagnostic",
    ValuationMethod.COMPS: "trading_comps_range",
    ValuationMethod.HISTORICAL_RANGE: "historical_context",
    ValuationMethod.SOTP: "segment_sum",
}
DIAGNOSTIC_ONLY_METHODS = frozenset(
    {ValuationMethod.FCFE, ValuationMethod.REVERSE_DCF}
)


def _blocker_has_proven_module_scope(
    inputs: ProfessionalValuationInputs,
    blocker: ModuleBlocker,
) -> bool:
    if (
        not inputs.allow_module_scoped_dependency_isolation
        or blocker.scope is not DependencyScope.MODULE_SCOPED
        or not blocker.dependency_ids
        or not blocker.scope_proof_refs
    ):
        return False
    dependency_by_id = {
        dependency.dependency_id: dependency
        for dependency in inputs.module_dependencies
    }
    resolved = tuple(
        dependency_by_id.get(dependency_id)
        for dependency_id in blocker.dependency_ids
    )
    return all(
        dependency is not None
        and dependency.scope is DependencyScope.MODULE_SCOPED
        and dependency.consumer_module == blocker.module_id
        and dependency.scope_proof_refs
        for dependency in resolved
    )


def _applicable_blockers(
    inputs: ProfessionalValuationInputs,
    method: ValuationMethod,
) -> tuple[ModuleBlocker, ...]:
    return tuple(
        blocker
        for blocker in inputs.module_blockers
        if not _blocker_has_proven_module_scope(inputs, blocker)
        or blocker.module_id == method.value
    )


def _blocker_source_refs(
    inputs: ProfessionalValuationInputs,
    blockers: Sequence[ModuleBlocker],
) -> tuple[str, ...]:
    dependency_by_id = {
        dependency.dependency_id: dependency
        for dependency in inputs.module_dependencies
    }
    refs: list[str] = []
    for blocker in blockers:
        refs.extend(blocker.scope_proof_refs)
        for dependency_id in blocker.dependency_ids:
            dependency = dependency_by_id.get(dependency_id)
            if dependency is not None:
                refs.extend(dependency.scope_proof_refs)
    return _clean_refs(refs)


def _copy_method_result(
    result: ValuationMethodResult,
    *,
    state: AvailabilityState | None = None,
    decision_status: MethodDecisionStatus | None = None,
    metrics: Mapping[str, str | int | float | bool | None] | None = None,
    source_refs: Iterable[str] = (),
) -> ValuationMethodResult:
    output_state = state or result.state
    retain_values = output_state.status is AvailabilityStatus.AVAILABLE
    return ValuationMethodResult(
        method=result.method,
        state=output_state,
        decision_status=decision_status,
        value_per_share=result.value_per_share if retain_values else None,
        low_value_per_share=result.low_value_per_share if retain_values else None,
        high_value_per_share=result.high_value_per_share if retain_values else None,
        metrics=dict(metrics if metrics is not None else result.metrics),
        source_refs=_clean_refs((*result.source_refs, *source_refs)),
    )


def _apply_method_dependencies(
    result: ValuationMethodResult,
    inputs: ProfessionalValuationInputs,
) -> ValuationMethodResult:
    blocked = _applicable_blockers(inputs, result.method)
    metrics = {
        **result.metrics,
        "module_blocker_count": len(blocked),
        "dependency_scoping_policy": (
            "proof_gated_module_scope"
            if inputs.allow_module_scoped_dependency_isolation
            else "global_fail_closed"
        ),
        "nonavailable_dependency_ids": ";".join(
            sorted(
                {
                    dependency_id
                    for blocker in blocked
                    for dependency_id in blocker.dependency_ids
                }
            )
        ),
        "module_blocker_ids": ";".join(
            blocker.blocker_id for blocker in blocked
        ),
        "pre_dependency_calculation_status": result.state.status.value,
    }
    source_refs = _blocker_source_refs(inputs, blocked)
    if not blocked:
        return _copy_method_result(result, metrics=metrics, source_refs=source_refs)

    blocker_ids = ", ".join(blocker.blocker_id for blocker in blocked)
    state = _blocking_state(
        "method_dependency_blocking",
        f"Method dependencies are blocking: {blocker_ids}",
    )
    return _copy_method_result(
        result,
        state=state,
        metrics=metrics,
        source_refs=source_refs,
    )


def _terminal_value_dominance(
    policy: ScenarioValuationPolicy,
    computation: _DCFComputation,
) -> tuple[str, float | None, float | None]:
    ratio = (
        computation.pv_terminal_value / computation.enterprise_value
        if computation.enterprise_value > 0
        else None
    )
    limit = policy.terminal_value_dominance_limit
    if ratio is None:
        return "enterprise_value_nonpositive", None, (
            float(limit.value)
            if limit is not None
            and limit.state.status is AvailabilityStatus.AVAILABLE
            and limit.value is not None
            else None
        )
    if limit is None:
        return "not_configured", ratio, None
    if limit.state.status is not AvailabilityStatus.AVAILABLE or limit.value is None:
        return "unavailable", ratio, None
    numeric_limit = float(limit.value)
    return (
        "pass" if ratio <= numeric_limit else "exceeds_limit",
        ratio,
        numeric_limit,
    )


def _annotate_method_decision_eligibility(
    result: ValuationMethodResult,
    inputs: ProfessionalValuationInputs,
    scenario_policy: ScenarioValuationPolicy,
    model_input_hash: str,
) -> ValuationMethodResult:
    result = _apply_method_dependencies(result, inputs)
    decision_policy = next(
        (
            policy
            for policy in inputs.method_decision_policies
            if policy.method is result.method
            and policy.scenario_key == scenario_policy.scenario_key
        ),
        None,
    )
    status: DecisionEligibility
    reason_code: str
    message: str
    approval_ref: str | None = None
    policy_source_refs: tuple[str, ...] = ()
    approved_input_hash: str | None = None

    if decision_policy is None:
        policy_status = DecisionEligibility.NEEDS_PM_REVIEW
        policy_reason_code = "method_decision_policy_not_supplied"
        policy_message = (
            "Calculation availability does not imply approval for decision use."
        )
        policy_approval_ref = None
        policy_source_refs = ()
        approval_gate_status = "NEEDS_PM_REVIEW"
    elif (
        decision_policy.status is DecisionEligibility.ELIGIBLE
        and decision_policy.approved_input_hash != model_input_hash
    ):
        policy_status = DecisionEligibility.NEEDS_PM_REVIEW
        policy_reason_code = "method_decision_approval_stale"
        policy_message = (
            "The approved model-input fingerprint does not match the current model."
        )
        policy_approval_ref = decision_policy.approval_ref
        policy_source_refs = decision_policy.source_refs
        approved_input_hash = decision_policy.approved_input_hash
        approval_gate_status = "STALE"
    else:
        policy_status = decision_policy.status
        policy_reason_code = decision_policy.reason_code
        policy_message = decision_policy.message
        policy_approval_ref = decision_policy.approval_ref
        policy_source_refs = decision_policy.source_refs
        approved_input_hash = decision_policy.approved_input_hash
        approval_gate_status = (
            "PASS"
            if decision_policy.status is DecisionEligibility.ELIGIBLE
            else decision_policy.status.value
        )

    if result.state.status is not AvailabilityStatus.AVAILABLE:
        status = DecisionEligibility.INELIGIBLE
        reason_code = "calculation_not_available"
        message = "A non-available calculation cannot be used as an approved decision target."
    elif result.method in DIAGNOSTIC_ONLY_METHODS:
        status = DecisionEligibility.INELIGIBLE
        reason_code = "method_is_diagnostic_only"
        message = "This method is a cross-check or market-implied diagnostic, not a target."
    elif result.method is ValuationMethod.FCFF_DCF:
        dominance_status = str(
            result.metrics.get("terminal_value_dominance_control_status", "not_configured")
        )
        if dominance_status == "exceeds_limit":
            status = DecisionEligibility.INELIGIBLE
            reason_code = "terminal_value_dominance_limit_exceeded"
            message = "Terminal value exceeds the supplied decision-use dominance limit."
        elif dominance_status != "pass":
            status = DecisionEligibility.NEEDS_PM_REVIEW
            reason_code = "terminal_value_dominance_control_not_passed"
            message = "A source-backed terminal-value dominance control must pass before decision use."
        else:
            status = policy_status
            reason_code = policy_reason_code
            message = policy_message
            approval_ref = policy_approval_ref
    else:
        status = policy_status
        reason_code = policy_reason_code
        message = policy_message
        approval_ref = policy_approval_ref

    module_id = result.method.value
    required_gates = [
        WorkflowGate(
            gate_id=f"{module_id}:calculation_verified",
            module_id=module_id,
            reported_status=(
                "PASS"
                if result.state.status is AvailabilityStatus.AVAILABLE
                else result.state.status.value
            ),
            message="The method calculation is source-backed and available.",
        )
    ]
    if result.method in DIAGNOSTIC_ONLY_METHODS:
        required_gates.append(
            WorkflowGate(
                gate_id=f"{module_id}:decision_use_role",
                module_id=module_id,
                reported_status="INELIGIBLE",
                message="The method is restricted to diagnostic or cross-check use.",
            )
        )
    else:
        required_gates.append(
            WorkflowGate(
                gate_id=f"{module_id}:approval_fingerprint",
                module_id=module_id,
                reported_status=approval_gate_status,
                message=policy_message,
            )
        )
    if result.method is ValuationMethod.FCFF_DCF:
        dominance_status = str(
            result.metrics.get(
                "terminal_value_dominance_control_status",
                "not_configured",
            )
        )
        required_gates.append(
            WorkflowGate(
                gate_id="fcff_dcf:terminal_value_dominance",
                module_id=module_id,
                reported_status=(
                    "PASS"
                    if dominance_status == "pass"
                    else "FAIL"
                    if dominance_status == "exceeds_limit"
                    else "NEEDS_PM_REVIEW"
                ),
                message="Terminal-value dominance must pass its source-backed limit.",
            )
        )
    method_availability = (
        MethodAvailability.AVAILABLE
        if result.state.status is AvailabilityStatus.AVAILABLE
        else MethodAvailability.UNVERIFIED
        if result.state.status is AvailabilityStatus.PM_REQUIRED
        else MethodAvailability.UNAVAILABLE
    )
    decision_status = MethodDecisionStatus(
        availability=method_availability,
        decision_eligibility=status,
        required_gates=tuple(required_gates),
    )

    metrics = {
        **result.metrics,
        "approved_model_input_hash": approved_input_hash,
        "approval_fingerprint_match": (
            approved_input_hash == model_input_hash
            if approved_input_hash is not None
            else None
        ),
        "calculation_availability_status": result.state.status.value,
        "current_model_input_hash": model_input_hash,
        "decision_approval_ref": approval_ref,
        "decision_eligibility_message": message,
        "decision_eligibility_reason_code": reason_code,
        "decision_eligibility_status": status.value,
        "decision_eligible": status is DecisionEligibility.ELIGIBLE,
        "method_aggregation_policy": "none",
        "method_role": METHOD_ROLES[result.method],
    }
    return _copy_method_result(
        result,
        decision_status=decision_status,
        metrics=metrics,
        source_refs=policy_source_refs,
    )


def _line_map(model_result: ModelResult) -> dict[str, LineSeries]:
    lines: dict[str, LineSeries] = {}
    for container in (*model_result.statements, *model_result.supporting_schedules):
        for line in container.lines:
            if line.line_key in lines:
                raise ValueError(f"duplicate model line across result containers: {line.line_key}")
            lines[line.line_key] = line
    return lines


def _period_value(lines: Mapping[str, LineSeries], line_key: str, period_key: str) -> PeriodValue | None:
    line = lines.get(line_key)
    if line is None:
        return None
    for value in line.values:
        if value.period_key == period_key:
            return value
    return None


def _number(value: PeriodValue | None) -> float | None:
    if value is None or value.state.status is not AvailabilityStatus.AVAILABLE:
        return None
    if not _finite(value.value):
        return None
    return float(value.value)


def _validate_fcff_forecast(
    model_result: ModelResult,
    policy: ScenarioValuationPolicy,
    lines: Mapping[str, LineSeries],
) -> _ValidatedFCFFForecast:
    blockers: list[tuple[str, str]] = []
    values: list[float] = []
    identity_differences: list[float] = []
    identity_missing: list[str] = []
    capex_sign_invalid_periods: list[str] = []
    source_refs: set[str] = {f"model_result:{model_result.result_hash}"}

    if model_result.state.status is not AvailabilityStatus.AVAILABLE:
        blockers.append(
            (
                "model_result_not_available",
                "The scenario model result is not available",
            )
        )

    axis_keys = tuple(period.key for period in model_result.period_axis.periods)
    missing_axis_periods = tuple(
        period for period in policy.forecast_period_keys if period not in axis_keys
    )
    axis_positions = tuple(
        axis_keys.index(period)
        for period in policy.forecast_period_keys
        if period in axis_keys
    )
    expected_positions = tuple(range(len(policy.forecast_period_keys)))
    if missing_axis_periods or axis_positions != expected_positions:
        blockers.append(
            (
                "forecast_period_axis_invalid",
                "Forecast valuation periods must cover the model axis "
                "contiguously from the first period",
            )
        )

    if lines.get(FCFF_LINE_KEY) is None:
        blockers.append(
            (
                "fcff_line_unavailable",
                f"Required FCFF line {FCFF_LINE_KEY!r} is absent",
            )
        )
    else:
        for period_key in policy.forecast_period_keys:
            period_value = _period_value(lines, FCFF_LINE_KEY, period_key)
            fcff_number = _number(period_value)
            if fcff_number is None:
                blockers.append(
                    (
                        "fcff_period_unavailable",
                        f"FCFF is unavailable for forecast period {period_key}",
                    )
                )
            else:
                values.append(fcff_number)
                source_refs.update(period_value.source_refs)

            identity_values: dict[str, float] = {}
            for identity_line_key in (
                CFO_LINE_KEY,
                NET_INCOME_COMPANY_LINE_KEY,
                NOPAT_LINE_KEY,
                CAPEX_LINE_KEY,
            ):
                identity_period_value = _period_value(
                    lines,
                    identity_line_key,
                    period_key,
                )
                identity_number = _number(identity_period_value)
                if identity_number is None:
                    identity_missing.append(
                        f"{identity_line_key}:{period_key}"
                    )
                else:
                    identity_values[identity_line_key] = identity_number
                    source_refs.update(identity_period_value.source_refs)
                    if (
                        identity_line_key == CAPEX_LINE_KEY
                        and identity_number > policy.fcff_identity_tolerance
                    ):
                        capex_sign_invalid_periods.append(period_key)
            if fcff_number is not None and len(identity_values) == 4:
                expected_fcff = (
                    identity_values[CFO_LINE_KEY]
                    - identity_values[NET_INCOME_COMPANY_LINE_KEY]
                    + identity_values[NOPAT_LINE_KEY]
                    + identity_values[CAPEX_LINE_KEY]
                )
                identity_differences.append(fcff_number - expected_fcff)

    if identity_missing:
        blockers.append(
            (
                "fcff_identity_inputs_unavailable",
                "Integrated FCFF identity inputs are unavailable: "
                + ", ".join(sorted(identity_missing)),
            )
        )
    if capex_sign_invalid_periods:
        blockers.append(
            (
                "fcff_capex_sign_invalid",
                "FCFF requires capex as a non-positive cash outflow in periods: "
                + ", ".join(sorted(capex_sign_invalid_periods)),
            )
        )
    maximum_difference = max(
        (abs(value) for value in identity_differences),
        default=None,
    )
    if (
        maximum_difference is not None
        and maximum_difference > policy.fcff_identity_tolerance
    ):
        blockers.append(
            (
                "fcff_identity_not_reconciled",
                "Unlevered FCFF does not reconcile to CFO less net income "
                "plus NOPAT plus capex",
            )
        )

    return _ValidatedFCFFForecast(
        values=tuple(values) if not blockers else None,
        identity_max_abs_difference=maximum_difference,
        source_refs=_clean_refs(source_refs),
        blockers=tuple(dict.fromkeys(blockers)),
    )


def _bridge_contract(
    inputs: ProfessionalValuationInputs,
) -> tuple[tuple[BridgeItem, ...], tuple[str, ...]]:
    by_category = {item.category: item for item in inputs.bridge_items}
    blockers: list[str] = []
    output: list[BridgeItem] = []
    for category in BridgeCategory:
        item = by_category.get(category)
        if item is None:
            blockers.append(f"bridge_missing:{category.value}")
            continue
        if item.amount.state.status is not AvailabilityStatus.AVAILABLE or item.amount.value is None:
            blockers.append(f"bridge_unavailable:{category.value}")
            continue
        output.append(
            BridgeItem(
                key=category.value,
                amount=float(item.amount.value),
                operation="add" if category in ADDITIVE_BRIDGE_CATEGORIES else "subtract",
                source_refs=(
                    *item.amount.source_refs,
                    *(f"bridge_claim:{claim_id}" for claim_id in item.claim_ids),
                ),
            )
        )
    return tuple(output), tuple(blockers)


def _bridge_totals(bridge: Sequence[BridgeItem]) -> tuple[float, float]:
    additions = sum(item.amount for item in bridge if item.operation == "add")
    subtractions = sum(item.amount for item in bridge if item.operation == "subtract")
    return additions, subtractions


def _selected_wacc(inputs: ProfessionalValuationInputs) -> WACCMethodInput:
    return next(method for method in inputs.wacc_methods if method.method_id == inputs.selected_wacc_policy)


def _wacc_contract(inputs: ProfessionalValuationInputs) -> tuple[WACCMethodResult, ...]:
    return tuple(
        WACCMethodResult(
            method_id=method.method_id,
            state=method.state,
            wacc=method.wacc,
            selected=method.method_id == inputs.selected_wacc_policy,
            source_refs=method.source_refs,
        )
        for method in inputs.wacc_methods
    )


def _discount_exponents(count: int, timing: DiscountTiming) -> tuple[float, ...]:
    if timing is DiscountTiming.MID_YEAR:
        return tuple(index - 0.5 for index in range(1, count + 1))
    return tuple(float(index) for index in range(1, count + 1))


def _calculate_dcf(
    *,
    fcff_values: Sequence[float],
    wacc: float,
    terminal_growth: float,
    timing: DiscountTiming,
    bridge: Sequence[BridgeItem],
    current_shares: float,
    terminal_shares: float | None,
    source_refs: Iterable[str],
) -> _DCFComputation | None:
    if not fcff_values or current_shares <= 0 or wacc <= terminal_growth or wacc <= 0 or wacc > 1:
        return None
    if not all(_finite(value) for value in fcff_values):
        return None
    terminal_fcff_next = float(fcff_values[-1]) * (1.0 + terminal_growth)
    if terminal_fcff_next <= 0:
        return None
    exponents = _discount_exponents(len(fcff_values), timing)
    # The continuing value is measured at the end of the final explicit
    # forecast period. Mid-year timing applies to explicit annual FCFF only.
    terminal_exponent = float(len(fcff_values))
    pv_explicit = sum(
        float(fcff) / ((1.0 + wacc) ** exponent)
        for fcff, exponent in zip(fcff_values, exponents, strict=True)
    )
    terminal_value = terminal_fcff_next / (wacc - terminal_growth)
    pv_terminal = terminal_value / ((1.0 + wacc) ** terminal_exponent)
    enterprise_value = pv_explicit + pv_terminal
    additions, subtractions = _bridge_totals(bridge)
    equity_value = enterprise_value + additions - subtractions
    return _DCFComputation(
        fcff_values=tuple(float(value) for value in fcff_values),
        discount_exponents=exponents,
        pv_explicit_fcff=pv_explicit,
        terminal_fcff_next=terminal_fcff_next,
        terminal_value=terminal_value,
        terminal_discount_exponent=terminal_exponent,
        pv_terminal_value=pv_terminal,
        enterprise_value=enterprise_value,
        bridge_additions=additions,
        bridge_subtractions=subtractions,
        equity_value=equity_value,
        value_per_share=equity_value / current_shares,
        terminal_shares=terminal_shares,
        source_refs=_clean_refs(source_refs),
    )


def _blocked_method(method: ValuationMethod, reason_code: str, message: str) -> ValuationMethodResult:
    return ValuationMethodResult(method=method, state=_blocking_state(reason_code, message))


def _unavailable_method(method: ValuationMethod, reason_code: str, message: str) -> ValuationMethodResult:
    return ValuationMethodResult(method=method, state=_unavailable_state(reason_code, message))

def _fcff_dcf(
    model_result: ModelResult,
    policy: ScenarioValuationPolicy,
    inputs: ProfessionalValuationInputs,
    lines: Mapping[str, LineSeries],
    bridge: Sequence[BridgeItem],
    bridge_blockers: Sequence[str],
) -> _FCFFOutcome:
    selected = _selected_wacc(inputs)
    blockers: list[str] = []
    reason_code = "fcff_dcf_inputs_unavailable"
    message = "FCFF DCF inputs are incomplete"

    def add_blocker(code: str, detail: str) -> None:
        nonlocal reason_code, message
        if not blockers:
            reason_code, message = code, detail
        blockers.append(code)

    fcff_forecast = _validate_fcff_forecast(model_result, policy, lines)
    for blocker_code, blocker_message in fcff_forecast.blockers:
        add_blocker(blocker_code, blocker_message)
    for blocker in _applicable_blockers(inputs, ValuationMethod.FCFF_DCF):
        add_blocker(
            f"module_blocker:{blocker.blocker_id}",
            f"Classified valuation module blocker is active: {blocker.blocker_id}",
        )
    if selected.state.status is not AvailabilityStatus.AVAILABLE or selected.wacc is None:
        add_blocker("selected_wacc_unavailable", "The selected WACC is not source-backed and available")
    elif selected.wacc <= 0:
        add_blocker("selected_wacc_invalid", "The selected WACC must be positive")

    current_shares = inputs.current_diluted_shares.value
    if (
        inputs.current_diluted_shares.state.status is not AvailabilityStatus.AVAILABLE
        or current_shares is None
        or current_shares <= 0
    ):
        add_blocker(
            "current_diluted_shares_unavailable",
            "Current diluted shares are unavailable or non-positive",
        )
    if bridge_blockers:
        if not blockers:
            reason_code = "ev_equity_bridge_incomplete"
            message = "Every bridge category requires an explicit source-backed value, including zero"
        blockers.extend(bridge_blockers)

    terminal_growth = policy.terminal_growth.value
    if policy.terminal_growth.state.status is not AvailabilityStatus.AVAILABLE or terminal_growth is None:
        add_blocker("terminal_growth_unavailable", "Terminal growth is unavailable")

    fcff_values = list(fcff_forecast.values or ())
    source_refs: set[str] = {
        *fcff_forecast.source_refs,
        *selected.source_refs,
        *inputs.current_diluted_shares.source_refs,
        *policy.terminal_growth.source_refs,
    }
    if policy.terminal_value_dominance_limit is not None:
        source_refs.update(policy.terminal_value_dominance_limit.source_refs)
    for item in bridge:
        source_refs.update(item.source_refs)

    terminal_shares = _number(_period_value(lines, TERMINAL_SHARES_LINE_KEY, policy.forecast_period_keys[-1]))
    if blockers:
        return _FCFFOutcome(
            result=_blocked_method(ValuationMethod.FCFF_DCF, reason_code, message),
            computation=None,
            blockers=tuple(blockers),
        )

    assert selected.wacc is not None and terminal_growth is not None and current_shares is not None
    if selected.wacc <= terminal_growth:
        return _FCFFOutcome(
            result=_blocked_method(
                ValuationMethod.FCFF_DCF,
                "terminal_denominator_invalid",
                "Selected WACC must exceed terminal growth",
            ),
            computation=None,
            blockers=("terminal_denominator_invalid",),
        )
    computation = _calculate_dcf(
        fcff_values=fcff_values,
        wacc=selected.wacc,
        terminal_growth=terminal_growth,
        timing=policy.discount_timing,
        bridge=bridge,
        current_shares=current_shares,
        terminal_shares=terminal_shares,
        source_refs=source_refs,
    )
    if computation is None:
        return _FCFFOutcome(
            result=_blocked_method(
                ValuationMethod.FCFF_DCF,
                "fcff_terminal_value_invalid",
                "FCFF terminal value cannot be calculated from the supplied forecast and policy",
            ),
            computation=None,
            blockers=("fcff_terminal_value_invalid",),
        )
    dominance_status, dominance_ratio, dominance_limit = _terminal_value_dominance(
        policy,
        computation,
    )
    maximum_fcff_identity_difference = (
        fcff_forecast.identity_max_abs_difference or 0.0
    )
    metrics = {
        "bridge_additions": computation.bridge_additions,
        "bridge_atomic_claim_count": sum(
            len(item.claim_ids) for item in inputs.bridge_items
        ),
        "bridge_subtractions": computation.bridge_subtractions,
        "current_diluted_shares": current_shares,
        "discount_timing": policy.discount_timing.value,
        "enterprise_value": computation.enterprise_value,
        "equity_value": computation.equity_value,
        "explicit_first_discount_exponent": computation.discount_exponents[0],
        "explicit_last_discount_exponent": computation.discount_exponents[-1],
        "explicit_period_count": len(fcff_values),
        "fcff_identity_formula": (
            "cash_from_operations - net_income_company + nopat + capex"
        ),
        "fcff_identity_max_abs_difference": maximum_fcff_identity_difference,
        "fcff_identity_tolerance": policy.fcff_identity_tolerance,
        "financing_items_excluded_from_fcff": True,
        "gordon_identity_difference": computation.terminal_value
        - computation.terminal_fcff_next / (selected.wacc - terminal_growth),
        "implied_value_per_share": computation.value_per_share,
        "interest_tax_shield_added_to_fcff": False,
        "method_aggregation_policy": "none",
        "pv_explicit_fcff": computation.pv_explicit_fcff,
        "pv_terminal_value": computation.pv_terminal_value,
        "selected_wacc": selected.wacc,
        "share_denominator_policy": "current_diluted_shares",
        "share_denominator_basis": "current_fully_diluted",
        "terminal_discount_exponent": computation.terminal_discount_exponent,
        "terminal_fcff_next": computation.terminal_fcff_next,
        "terminal_growth": terminal_growth,
        "terminal_share_count_used_in_denominator": False,
        "terminal_shares_diagnostic": terminal_shares,
        "terminal_value": computation.terminal_value,
        "terminal_value_dominance_control_status": dominance_status,
        "terminal_value_dominance_limit": dominance_limit,
        "terminal_value_percent_enterprise_value": dominance_ratio,
    }
    return _FCFFOutcome(
        result=ValuationMethodResult(
            method=ValuationMethod.FCFF_DCF,
            state=_available_state(),
            value_per_share=computation.value_per_share,
            metrics=metrics,
            source_refs=computation.source_refs,
        ),
        computation=computation,
        blockers=(),
    )

def _fcfe_cross_check(
    model_result: ModelResult,
    policy: ScenarioValuationPolicy,
    inputs: ProfessionalValuationInputs,
    lines: Mapping[str, LineSeries],
    bridge: Sequence[BridgeItem],
    fcff: _FCFFOutcome,
) -> ValuationMethodResult:
    fcfe_policy = inputs.fcfe_policy
    if fcfe_policy is None:
        return _unavailable_method(
            ValuationMethod.FCFE,
            "fcfe_policy_not_supplied",
            "FCFE requires explicit schedule line and cost-of-equity policy",
        )
    fcff_forecast = _validate_fcff_forecast(model_result, policy, lines)
    if fcff_forecast.values is None:
        return ValuationMethodResult(
            method=ValuationMethod.FCFE,
            state=_unavailable_state(
                "fcfe_fcff_forecast_unavailable",
                "FCFE requires a validated integrated FCFF forecast",
            ),
            metrics={
                "fcff_forecast_blocker_ids": ";".join(
                    code for code, _ in fcff_forecast.blockers
                )
            },
            source_refs=fcff_forecast.source_refs,
        )
    cost_of_equity = fcfe_policy.cost_of_equity.value
    if fcfe_policy.cost_of_equity.state.status is not AvailabilityStatus.AVAILABLE or cost_of_equity is None:
        return _unavailable_method(
            ValuationMethod.FCFE,
            "cost_of_equity_unavailable",
            "FCFE cost of equity is not source-backed and available",
        )
    current_shares = inputs.current_diluted_shares.value
    if (
        inputs.current_diluted_shares.state.status
        is not AvailabilityStatus.AVAILABLE
        or current_shares is None
        or current_shares <= 0
    ):
        return _unavailable_method(
            ValuationMethod.FCFE,
            "fcfe_share_denominator_unavailable",
            "FCFE requires positive source-backed current diluted shares",
        )
    terminal_growth = policy.terminal_growth.value
    if (
        policy.terminal_growth.state.status is not AvailabilityStatus.AVAILABLE
        or terminal_growth is None
    ):
        return _unavailable_method(
            ValuationMethod.FCFE,
            "fcfe_terminal_growth_unavailable",
            "FCFE requires source-backed terminal growth",
        )
    financing_claim_keys = {
        category.value
        for category in fcfe_policy.financing_claim_categories_reflected
    }
    required_bridge_keys = {
        category.value
        for category in BridgeCategory
        if category.value not in financing_claim_keys
    }
    available_bridge_keys = {item.key for item in bridge}
    missing_bridge_keys = tuple(
        sorted(required_bridge_keys - available_bridge_keys)
    )
    if missing_bridge_keys:
        return ValuationMethodResult(
            method=ValuationMethod.FCFE,
            state=_unavailable_state(
                "fcfe_bridge_incomplete",
                "FCFE requires every non-financing bridge claim exactly once",
            ),
            metrics={"missing_bridge_keys": ";".join(missing_bridge_keys)},
        )

    check_by_id = {check.check_id: check for check in model_result.check_results}
    failed_checks = tuple(
        check_id
        for check_id in fcfe_policy.required_check_ids
        if check_id not in check_by_id or check_by_id[check_id].status is not CheckStatus.PASS
    )
    if failed_checks:
        return ValuationMethodResult(
            method=ValuationMethod.FCFE,
            state=_unavailable_state(
                "fcfe_schedule_checks_not_passed",
                "Debt, interest, and net-borrowing schedule checks must all pass",
            ),
            metrics={"failed_or_missing_check_ids": ",".join(failed_checks)},
        )

    fcfe_values: list[float] = []
    identity_differences: list[float] = []
    source_refs: set[str] = {
        *fcff_forecast.source_refs,
        *fcfe_policy.cost_of_equity.source_refs,
        *inputs.current_diluted_shares.source_refs,
        *policy.terminal_growth.source_refs,
    }
    for index, period_key in enumerate(policy.forecast_period_keys):
        fcfe_value = _period_value(lines, fcfe_policy.fcfe_line_key, period_key)
        after_tax_interest_value = _period_value(lines, fcfe_policy.after_tax_interest_line_key, period_key)
        net_borrowing_value = _period_value(lines, fcfe_policy.net_borrowing_line_key, period_key)
        fcfe_number = _number(fcfe_value)
        after_tax_interest = _number(after_tax_interest_value)
        net_borrowing = _number(net_borrowing_value)
        if fcfe_number is None or after_tax_interest is None or net_borrowing is None:
            return _unavailable_method(
                ValuationMethod.FCFE,
                "fcfe_schedule_line_unavailable",
                f"FCFE schedule inputs are unavailable for {period_key}",
            )
        if after_tax_interest < 0:
            return _unavailable_method(
                ValuationMethod.FCFE,
                "fcfe_after_tax_interest_sign_invalid",
                "After-tax interest must be supplied as a non-negative financing cost",
            )
        expected = fcff_forecast.values[index] - after_tax_interest + net_borrowing
        identity_differences.append(fcfe_number - expected)
        fcfe_values.append(fcfe_number)
        source_refs.update(fcfe_value.source_refs)
        source_refs.update(after_tax_interest_value.source_refs)
        source_refs.update(net_borrowing_value.source_refs)

    maximum_difference = max(abs(value) for value in identity_differences)
    if maximum_difference > fcfe_policy.reconciliation_tolerance:
        return ValuationMethodResult(
            method=ValuationMethod.FCFE,
            state=_unavailable_state(
                "fcfe_identity_not_reconciled",
                "Model FCFE does not reconcile to FCFF less after-tax interest plus net borrowing",
            ),
            metrics={
                "identity_max_abs_difference": maximum_difference,
                "identity_tolerance": fcfe_policy.reconciliation_tolerance,
            },
            source_refs=source_refs,
        )

    terminal_growth = float(terminal_growth)
    if cost_of_equity <= terminal_growth:
        return _unavailable_method(
            ValuationMethod.FCFE,
            "fcfe_terminal_denominator_invalid",
            "Cost of equity must exceed terminal growth",
        )
    exponents = _discount_exponents(len(fcfe_values), policy.discount_timing)
    pv_explicit = sum(
        value / ((1.0 + cost_of_equity) ** exponent)
        for value, exponent in zip(fcfe_values, exponents, strict=True)
    )
    terminal_fcfe_next = fcfe_values[-1] * (1.0 + terminal_growth)
    if terminal_fcfe_next <= 0:
        return _unavailable_method(
            ValuationMethod.FCFE,
            "fcfe_terminal_cash_flow_nonpositive",
            "Terminal FCFE must be positive for a Gordon continuing value",
        )
    terminal_value = terminal_fcfe_next / (cost_of_equity - terminal_growth)
    terminal_discount_exponent = float(len(fcfe_values))
    pv_terminal = terminal_value / (
        (1.0 + cost_of_equity) ** terminal_discount_exponent
    )

    # The policy explicitly identifies financing claims already reflected in
    # after-tax interest and net borrowing. Only those claims are excluded from
    # the bridge, preventing an implicit assumption about lease treatment.
    fcfe_bridge = tuple(
        item
        for item in bridge
        if item.key not in financing_claim_keys
    )
    additions, subtractions = _bridge_totals(fcfe_bridge)
    for item in fcfe_bridge:
        source_refs.update(item.source_refs)
    equity_value = pv_explicit + pv_terminal + additions - subtractions
    current_shares = float(current_shares)
    value_per_share = equity_value / current_shares
    return ValuationMethodResult(
        method=ValuationMethod.FCFE,
        state=_available_state(),
        value_per_share=value_per_share,
        metrics={
            "bridge_additions_excluding_financing_claims": additions,
            "bridge_subtractions_excluding_financing_claims": subtractions,
            "cost_of_equity": cost_of_equity,
            "equity_value": equity_value,
            "fcfe_less_fcff_value_per_share": (
                value_per_share - fcff.computation.value_per_share
                if fcff.computation is not None
                else None
            ),
            "fcff_dcf_calculation_available": fcff.computation is not None,
            "financing_claim_categories_reflected": ";".join(
                sorted(financing_claim_keys)
            ),
            "financing_claims_not_double_counted": True,
            "identity_max_abs_difference": maximum_difference,
            "identity_tolerance": fcfe_policy.reconciliation_tolerance,
            "interest_tax_shield_application_count": 1,
            "pv_explicit_fcfe": pv_explicit,
            "pv_terminal_fcfe": pv_terminal,
            "share_denominator_policy": "current_diluted_shares",
            "share_denominator_basis": "current_fully_diluted",
            "terminal_discount_exponent": terminal_discount_exponent,
            "terminal_fcfe_next": terminal_fcfe_next,
            "terminal_value": terminal_value,
        },
        source_refs=source_refs,
    )

def _bisect_root(function, lower: float, upper: float, tolerance: float) -> float | None:
    low_value = function(lower)
    high_value = function(upper)
    if low_value is None or high_value is None or not _finite(low_value) or not _finite(high_value):
        return None
    if abs(low_value) <= tolerance:
        return lower
    if abs(high_value) <= tolerance:
        return upper
    if low_value * high_value > 0:
        return None
    low, high = lower, upper
    for _ in range(240):
        midpoint = (low + high) / 2.0
        midpoint_value = function(midpoint)
        if midpoint_value is None or not _finite(midpoint_value):
            return None
        if abs(midpoint_value) <= tolerance or abs(high - low) <= tolerance:
            return midpoint
        if low_value * midpoint_value <= 0:
            high = midpoint
        else:
            low = midpoint
            low_value = midpoint_value
    return (low + high) / 2.0


def _reverse_dcf(
    model_result: ModelResult,
    policy: ScenarioValuationPolicy,
    inputs: ProfessionalValuationInputs,
    lines: Mapping[str, LineSeries],
    fcff: _FCFFOutcome,
) -> ValuationMethodResult:
    reverse_policy = inputs.reverse_dcf_policy
    if reverse_policy is None:
        return _unavailable_method(
            ValuationMethod.REVERSE_DCF,
            "reverse_dcf_policy_not_supplied",
            "Reverse DCF requires an explicit solve policy",
        )
    if fcff.computation is None:
        return _unavailable_method(
            ValuationMethod.REVERSE_DCF,
            "reverse_dcf_fcff_dependency_unavailable",
            "Reverse DCF requires the frozen FCFF forecast and bridge",
        )
    if inputs.current_price.state.status is not AvailabilityStatus.AVAILABLE or inputs.current_price.value is None:
        return _unavailable_method(
            ValuationMethod.REVERSE_DCF,
            "current_price_unavailable",
            "Reverse DCF requires a source-backed current price",
        )
    current_price = float(inputs.current_price.value)
    if current_price < 0:
        return _unavailable_method(
            ValuationMethod.REVERSE_DCF,
            "current_price_invalid",
            "Reverse DCF current price must be non-negative",
        )
    current_shares = float(inputs.current_diluted_shares.value)
    selected = _selected_wacc(inputs)
    assert selected.wacc is not None
    wacc = selected.wacc
    target_equity_value = current_price * current_shares
    target_enterprise_value = (
        target_equity_value
        - fcff.computation.bridge_additions
        + fcff.computation.bridge_subtractions
    )
    terminal_exponent = fcff.computation.terminal_discount_exponent
    explicit_pv = fcff.computation.pv_explicit_fcff
    source_refs: set[str] = {
        f"model_result:{model_result.result_hash}",
        *inputs.current_price.source_refs,
        *inputs.current_diluted_shares.source_refs,
        *selected.source_refs,
        *fcff.computation.source_refs,
    }

    def equity_from_terminal_value(terminal_value: float) -> float:
        pv_terminal = terminal_value / ((1.0 + wacc) ** terminal_exponent)
        return (
            explicit_pv
            + pv_terminal
            + fcff.computation.bridge_additions
            - fcff.computation.bridge_subtractions
        )

    if reverse_policy.variable is ReverseDCFVariable.TERMINAL_GROWTH:
        lower = max(float(reverse_policy.lower_bound), -0.999999)
        upper = min(float(reverse_policy.upper_bound), wacc - 1e-9)
        if lower >= upper:
            return _unavailable_method(
                ValuationMethod.REVERSE_DCF,
                "reverse_dcf_bounds_invalid_for_wacc",
                "Terminal-growth solve bounds do not leave a valid WACC spread",
            )

        def objective(variable: float) -> float | None:
            terminal_fcff = fcff.computation.fcff_values[-1] * (1.0 + variable)
            if terminal_fcff <= 0 or wacc <= variable:
                return None
            terminal_value = terminal_fcff / (wacc - variable)
            return equity_from_terminal_value(terminal_value) / current_shares - current_price

        implied = _bisect_root(objective, lower, upper, reverse_policy.solve_tolerance)
        if implied is None:
            return _unavailable_method(
                ValuationMethod.REVERSE_DCF,
                "reverse_dcf_no_solution",
                "Current price is not replayable within the supplied terminal-growth bounds",
            )
        terminal_fcff = fcff.computation.fcff_values[-1] * (1.0 + implied)
        terminal_value = terminal_fcff / (wacc - implied)
        fixed_growth = None
    else:
        fixed = reverse_policy.fixed_terminal_growth
        if fixed is None or fixed.state.status is not AvailabilityStatus.AVAILABLE or fixed.value is None:
            return _unavailable_method(
                ValuationMethod.REVERSE_DCF,
                "reverse_dcf_fixed_growth_unavailable",
                "Terminal FCFF margin solve requires source-backed fixed terminal growth",
            )
        fixed_growth = float(fixed.value)
        source_refs.update(fixed.source_refs)
        if wacc <= fixed_growth:
            return _unavailable_method(
                ValuationMethod.REVERSE_DCF,
                "reverse_dcf_terminal_denominator_invalid",
                "Selected WACC must exceed fixed terminal growth",
            )
        revenue = _number(
            _period_value(lines, reverse_policy.revenue_line_key, policy.forecast_period_keys[-1])
        )
        if revenue is None:
            return _unavailable_method(
                ValuationMethod.REVERSE_DCF,
                "reverse_dcf_revenue_unavailable",
                "Terminal FCFF margin solve requires terminal forecast revenue",
            )
        terminal_revenue = revenue * (1.0 + fixed_growth)
        if terminal_revenue <= 0:
            return _unavailable_method(
                ValuationMethod.REVERSE_DCF,
                "reverse_dcf_terminal_revenue_nonpositive",
                "Terminal revenue must be positive for the margin solve",
            )

        def objective(variable: float) -> float:
            terminal_value_local = terminal_revenue * variable / (wacc - fixed_growth)
            return equity_from_terminal_value(terminal_value_local) / current_shares - current_price

        implied = _bisect_root(
            objective,
            float(reverse_policy.lower_bound),
            float(reverse_policy.upper_bound),
            reverse_policy.solve_tolerance,
        )
        if implied is None:
            return _unavailable_method(
                ValuationMethod.REVERSE_DCF,
                "reverse_dcf_no_solution",
                "Current price is not replayable within the supplied terminal-margin bounds",
            )
        terminal_fcff = terminal_revenue * implied
        terminal_value = terminal_fcff / (wacc - fixed_growth)

    replay_equity_value = equity_from_terminal_value(terminal_value)
    replay_per_share = replay_equity_value / current_shares
    return ValuationMethodResult(
        method=ValuationMethod.REVERSE_DCF,
        state=_available_state(),
        metrics={
            "current_price": current_price,
            "fixed_terminal_growth": fixed_growth,
            "implied_variable": implied,
            "market_equity_value": target_equity_value,
            "market_enterprise_value": target_enterprise_value,
            "replay_difference_per_share": replay_per_share - current_price,
            "replay_equity_value": replay_equity_value,
            "replay_value_per_share": replay_per_share,
            "solve_lower_bound": reverse_policy.lower_bound,
            "solve_upper_bound": reverse_policy.upper_bound,
            "solve_variable": reverse_policy.variable.value,
            "terminal_fcff": terminal_fcff,
            "terminal_value": terminal_value,
        },
        source_refs=source_refs,
    )

def _linear_percentile(values: Sequence[float], percentile: float) -> float:
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    location = (len(ordered) - 1) * percentile
    lower = math.floor(location)
    upper = math.ceil(location)
    if lower == upper:
        return ordered[lower]
    weight = location - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _comps_method(
    inputs: ProfessionalValuationInputs,
    lines: Mapping[str, LineSeries],
    bridge: Sequence[BridgeItem],
    bridge_blockers: Sequence[str],
) -> ValuationMethodResult:
    policy = inputs.comps_policy
    if policy is None:
        return _unavailable_method(
            ValuationMethod.COMPS,
            "comps_policy_not_supplied",
            "Trading comps require an explicit basis and approved multiple set",
        )
    if (
        inputs.current_diluted_shares.state.status is not AvailabilityStatus.AVAILABLE
        or inputs.current_diluted_shares.value is None
        or inputs.current_diluted_shares.value <= 0
    ):
        return _unavailable_method(
            ValuationMethod.COMPS,
            "comps_share_denominator_unavailable",
            "Trading comps require current diluted shares",
        )
    ev_based_methods = tuple(
        method for method in policy.approved_multiples if method != "pe"
    )
    if ev_based_methods and bridge_blockers:
        return _unavailable_method(
            ValuationMethod.COMPS,
            "comps_bridge_incomplete",
            "EV-based trading comps require a complete EV-to-equity bridge",
        )

    same_basis = tuple(fact for fact in inputs.peer_facts if fact.basis is policy.basis)
    excluded_basis_count = len(inputs.peer_facts) - len(same_basis)
    if not same_basis:
        return _unavailable_method(
            ValuationMethod.COMPS,
            "comps_basis_unavailable",
            f"No peer facts are available on the approved {policy.basis.value} basis",
        )
    metric_fields = {
        "ev_revenue": ("enterprise_value", "revenue", REVENUE_LINE_KEY),
        "ev_ebitda": ("enterprise_value", "ebitda", EBITDA_LINE_KEY),
        "pe": ("equity_value", "net_income", NET_INCOME_LINE_KEY),
    }
    current_shares = float(inputs.current_diluted_shares.value)
    additions, subtractions = _bridge_totals(bridge)
    metrics: dict[str, str | int | float | bool | None] = {
        "basis_label": policy.basis.value,
        "excluded_basis_peer_count": excluded_basis_count,
        "method_aggregation_policy": "none",
        "share_denominator_policy": "current_diluted_shares",
        "share_denominator_basis": "current_fully_diluted",
        "target_period_key": policy.target_period_key,
    }
    exclusions: list[str] = []
    indications: list[float] = []
    source_refs: set[str] = set(inputs.current_diluted_shares.source_refs)
    if ev_based_methods:
        for item in bridge:
            source_refs.update(item.source_refs)

    for method in policy.approved_multiples:
        numerator_field, denominator_field, target_line = metric_fields[method]
        metrics[f"{method}_peer_numerator_field"] = numerator_field
        metrics[f"{method}_peer_denominator_field"] = denominator_field
        metrics[f"{method}_target_denominator_line_key"] = target_line
        observations: list[tuple[str, float]] = []
        missing_count = 0
        nm_count = 0
        negative_numerator_count = 0
        for fact in same_basis:
            source_refs.update(fact.source_refs)
            numerator = getattr(fact, numerator_field)
            denominator = getattr(fact, denominator_field)
            if numerator is None or denominator is None:
                missing_count += 1
                exclusions.append(f"{fact.ticker}:{method}_missing")
                continue
            if denominator <= 0:
                nm_count += 1
                exclusions.append(f"{fact.ticker}:{method}_nm_denominator")
                continue
            if numerator < 0:
                negative_numerator_count += 1
                exclusions.append(f"{fact.ticker}:{method}_negative_numerator")
                continue
            observations.append((fact.ticker, numerator / denominator))

        outlier_tickers: set[str] = set()
        if len(observations) >= 4:
            raw_values = [value for _, value in observations]
            q1 = _linear_percentile(raw_values, 0.25)
            q3 = _linear_percentile(raw_values, 0.75)
            iqr = q3 - q1
            lower_fence = q1 - policy.outlier_iqr_multiplier * iqr
            upper_fence = q3 + policy.outlier_iqr_multiplier * iqr
            outlier_tickers = {
                ticker
                for ticker, value in observations
                if value < lower_fence or value > upper_fence
            }
        kept = [(ticker, value) for ticker, value in observations if ticker not in outlier_tickers]
        exclusions.extend(f"{ticker}:{method}_outlier" for ticker in sorted(outlier_tickers))
        metrics[f"{method}_missing_count"] = missing_count
        metrics[f"{method}_negative_numerator_count"] = negative_numerator_count
        metrics[f"{method}_nm_count"] = nm_count
        metrics[f"{method}_nonpositive_count"] = nm_count + negative_numerator_count
        metrics[f"{method}_outlier_count"] = len(outlier_tickers)
        metrics[f"{method}_valid_peer_count"] = len(kept)
        if not kept:
            metrics[f"{method}_median_multiple"] = None
            metrics[f"{method}_implied_per_share"] = None
            continue

        selected_multiple = median(value for _, value in kept)
        metrics[f"{method}_median_multiple"] = selected_multiple
        target_period_value = _period_value(lines, target_line, policy.target_period_key)
        target_value = _number(target_period_value)
        if target_value is None:
            metrics[f"{method}_target_metric_unavailable"] = True
            metrics[f"{method}_implied_per_share"] = None
            continue
        metrics[f"{method}_target_metric"] = target_value
        if target_value <= 0:
            metrics[f"{method}_target_nm"] = True
            metrics[f"{method}_implied_per_share"] = None
            source_refs.update(target_period_value.source_refs)
            continue
        metrics[f"{method}_target_nm"] = False
        source_refs.update(target_period_value.source_refs)
        if method == "pe":
            implied_equity_value = selected_multiple * target_value
        else:
            implied_enterprise_value = selected_multiple * target_value
            implied_equity_value = implied_enterprise_value + additions - subtractions
            metrics[f"{method}_implied_enterprise_value"] = implied_enterprise_value
        implied_per_share = implied_equity_value / current_shares
        metrics[f"{method}_implied_equity_value"] = implied_equity_value
        metrics[f"{method}_implied_per_share"] = implied_per_share
        indications.append(implied_per_share)

    metrics["excluded_peer_reasons"] = ";".join(sorted(set(exclusions)))
    if not indications:
        return ValuationMethodResult(
            method=ValuationMethod.COMPS,
            state=_unavailable_state(
                "comps_no_valid_indication",
                "No approved basis-consistent peer multiple has a valid target metric",
            ),
            metrics=metrics,
            source_refs=source_refs,
        )
    return ValuationMethodResult(
        method=ValuationMethod.COMPS,
        state=_available_state(),
        value_per_share=None,
        low_value_per_share=min(indications),
        high_value_per_share=max(indications),
        metrics=metrics,
        source_refs=source_refs,
    )


def _historical_range(inputs: ProfessionalValuationInputs) -> ValuationMethodResult:
    historical = inputs.historical_range
    if historical is None:
        return _unavailable_method(
            ValuationMethod.HISTORICAL_RANGE,
            "historical_range_not_supplied",
            "A coherent source-backed historical period and basis were not supplied",
        )
    return ValuationMethodResult(
        method=ValuationMethod.HISTORICAL_RANGE,
        state=_available_state(),
        value_per_share=historical.median_value_per_share,
        low_value_per_share=historical.low_value_per_share,
        high_value_per_share=historical.high_value_per_share,
        metrics={
            "basis_label": historical.basis_label,
            "period_end": historical.period_end.isoformat(),
            "period_start": historical.period_start.isoformat(),
        },
        source_refs=historical.source_refs,
    )


def _metric_key(value: str) -> str:
    cleaned = "".join(character.lower() if character.isalnum() else "_" for character in value)
    return "_".join(part for part in cleaned.split("_") if part)


def _sotp_method(
    inputs: ProfessionalValuationInputs,
    bridge: Sequence[BridgeItem],
    bridge_blockers: Sequence[str],
) -> ValuationMethodResult:
    sotp = inputs.sotp_input
    if sotp is None:
        return _unavailable_method(
            ValuationMethod.SOTP,
            "sotp_not_supplied",
            "SOTP is unavailable until segment economics, peers, and allocations are supplied",
        )
    eligibility = (
        (
            sotp.segment_economics_complete,
            "sotp_segment_economics_incomplete",
            "Segment economics are incomplete",
        ),
        (
            sotp.peer_mapping_complete,
            "sotp_peer_mapping_incomplete",
            "Segment peer mappings are incomplete",
        ),
        (
            sotp.allocations_complete,
            "sotp_allocations_incomplete",
            "Corporate and balance-sheet allocations are incomplete",
        ),
    )
    for condition, reason_code, message in eligibility:
        if not condition:
            return _unavailable_method(ValuationMethod.SOTP, reason_code, message)
    if len(sotp.components) < 2:
        return _unavailable_method(
            ValuationMethod.SOTP,
            "sotp_insufficient_segments",
            "SOTP requires at least two independently valued segments",
        )
    if any(component.metric_value < 0 or component.selected_multiple <= 0 for component in sotp.components):
        return _unavailable_method(
            ValuationMethod.SOTP,
            "sotp_component_metric_invalid",
            "SOTP component metrics must be non-negative and selected multiples positive",
        )
    if bridge_blockers:
        return _unavailable_method(
            ValuationMethod.SOTP,
            "sotp_bridge_incomplete",
            "SOTP requires a complete EV-to-equity bridge",
        )
    if (
        inputs.current_diluted_shares.state.status is not AvailabilityStatus.AVAILABLE
        or inputs.current_diluted_shares.value is None
        or inputs.current_diluted_shares.value <= 0
    ):
        return _unavailable_method(
            ValuationMethod.SOTP,
            "sotp_share_denominator_unavailable",
            "SOTP requires current diluted shares",
        )
    metrics: dict[str, str | int | float | bool | None] = {
        "segment_count": len(sotp.components),
        "share_denominator_policy": "current_diluted_shares",
    }
    source_refs: set[str] = set(inputs.current_diluted_shares.source_refs)
    enterprise_value = 0.0
    for component in sotp.components:
        component_value = component.metric_value * component.selected_multiple
        enterprise_value += component_value
        key = _metric_key(component.segment_name)
        metrics[f"component_{key}_metric"] = component.metric_value
        metrics[f"component_{key}_multiple"] = component.selected_multiple
        metrics[f"component_{key}_enterprise_value"] = component_value
        source_refs.update(component.source_refs)
    additions, subtractions = _bridge_totals(bridge)
    for item in bridge:
        source_refs.update(item.source_refs)
    equity_value = enterprise_value + additions - subtractions
    value_per_share = equity_value / float(inputs.current_diluted_shares.value)
    metrics.update(
        {
            "bridge_additions": additions,
            "bridge_subtractions": subtractions,
            "enterprise_value": enterprise_value,
            "equity_value": equity_value,
        }
    )
    return ValuationMethodResult(
        method=ValuationMethod.SOTP,
        state=_available_state(),
        value_per_share=value_per_share,
        metrics=metrics,
        source_refs=source_refs,
    )

def _sensitivity_grid(
    policy: ScenarioValuationPolicy,
    inputs: ProfessionalValuationInputs,
    bridge: Sequence[BridgeItem],
    fcff: _FCFFOutcome,
) -> SensitivityResult:
    if fcff.computation is None:
        return SensitivityResult(
            sensitivity_id="fcff_wacc_terminal_growth",
            state=_unavailable_state(
                "sensitivity_fcff_dependency_unavailable",
                "FCFF sensitivity requires an available FCFF DCF",
            ),
        )
    selected = _selected_wacc(inputs)
    assert selected.wacc is not None
    assert policy.terminal_growth.value is not None
    current_shares = float(inputs.current_diluted_shares.value)
    outputs: dict[str, int | float | None] = {}
    valid_count = 0
    invalid_count = 0
    for wacc_delta in sorted(inputs.wacc_sensitivity_deltas):
        for growth_delta in sorted(inputs.terminal_growth_sensitivity_deltas):
            wacc = selected.wacc + wacc_delta
            growth = float(policy.terminal_growth.value) + growth_delta
            computation = _calculate_dcf(
                fcff_values=fcff.computation.fcff_values,
                wacc=wacc,
                terminal_growth=growth,
                timing=policy.discount_timing,
                bridge=bridge,
                current_shares=current_shares,
                terminal_shares=fcff.computation.terminal_shares,
                source_refs=(),
            )
            key = f"value_per_share__wacc_{wacc:.6f}__growth_{growth:.6f}"
            if computation is None:
                outputs[key] = None
                invalid_count += 1
            else:
                outputs[key] = computation.value_per_share
                valid_count += 1
    outputs["invalid_cell_count"] = invalid_count
    outputs["valid_cell_count"] = valid_count
    state = (
        _available_state()
        if valid_count
        else _unavailable_state(
            "sensitivity_no_valid_cells",
            "No WACC and terminal-growth sensitivity pair has a valid spread",
        )
    )
    return SensitivityResult(
        sensitivity_id="fcff_wacc_terminal_growth",
        state=state,
        outputs=outputs,
    )


def _terminal_diagnostics(
    policy: ScenarioValuationPolicy,
    inputs: ProfessionalValuationInputs,
    fcff: _FCFFOutcome,
) -> dict[str, str | int | float | bool | None]:
    if fcff.computation is None:
        return {
            "reason_code": fcff.result.state.reason_code,
            "status": "blocked",
        }
    selected = _selected_wacc(inputs)
    assert selected.wacc is not None and policy.terminal_growth.value is not None
    computation = fcff.computation
    dominance_status, dominance_ratio, dominance_limit = _terminal_value_dominance(
        policy,
        computation,
    )
    return {
        "continuing_value_share_count_policy": "current_diluted_shares",
        "discount_timing": policy.discount_timing.value,
        "enterprise_value": computation.enterprise_value,
        "gordon_identity_difference": computation.terminal_value
        - computation.terminal_fcff_next / (selected.wacc - float(policy.terminal_growth.value)),
        "method_aggregation_policy": "none",
        "pv_terminal_value": computation.pv_terminal_value,
        "selected_wacc": selected.wacc,
        "terminal_discount_exponent": computation.terminal_discount_exponent,
        "terminal_fcff_next": computation.terminal_fcff_next,
        "terminal_growth": policy.terminal_growth.value,
        "terminal_shares_diagnostic": computation.terminal_shares,
        "terminal_value": computation.terminal_value,
        "terminal_value_dominance_control_status": dominance_status,
        "terminal_value_dominance_limit": dominance_limit,
        "terminal_value_percent_enterprise_value": dominance_ratio,
    }


def _per_share_reconciliation(
    inputs: ProfessionalValuationInputs,
    fcff: _FCFFOutcome,
) -> CheckResult:
    if fcff.computation is None or fcff.result.value_per_share is None:
        return CheckResult(
            check_id="valuation.per_share_reconciliation",
            status=CheckStatus.BLOCKED,
            tolerance=1e-9,
            message="FCFF equity value or current diluted shares are unavailable",
        )
    shares = float(inputs.current_diluted_shares.value)
    replay = fcff.computation.equity_value / shares
    difference = replay - fcff.result.value_per_share
    return CheckResult(
        check_id="valuation.per_share_reconciliation",
        status=CheckStatus.PASS if abs(difference) <= 1e-9 else CheckStatus.FAIL,
        difference=difference,
        tolerance=1e-9,
        message="Equity value is divided by current diluted shares; terminal shares are diagnostic only",
    )


def _build_one_bundle(
    model_result: ModelResult,
    policy: ScenarioValuationPolicy,
    inputs: ProfessionalValuationInputs,
) -> ValuationBundle:
    lines = _line_map(model_result)
    bridge, bridge_blockers = _bridge_contract(inputs)
    fcff = _fcff_dcf(model_result, policy, inputs, lines, bridge, bridge_blockers)
    raw_methods = (
        fcff.result,
        _fcfe_cross_check(model_result, policy, inputs, lines, bridge, fcff),
        _reverse_dcf(model_result, policy, inputs, lines, fcff),
        _comps_method(inputs, lines, bridge, bridge_blockers),
        _historical_range(inputs),
        _sotp_method(inputs, bridge, bridge_blockers),
    )
    methods = tuple(
        _annotate_method_decision_eligibility(
            method,
            inputs,
            policy,
            model_result.input_hash,
        )
        for method in raw_methods
    )
    blockers = tuple(fcff.blockers)
    state = (
        _available_state()
        if not blockers
        else _blocking_state(
            "valuation_core_blocked",
            "Core FCFF valuation is blocked by missing or invalid inputs",
        )
    )
    warnings: list[str] = []
    if inputs.allow_module_scoped_dependency_isolation:
        warnings.append("module_scoped_dependency_isolation_enabled")
    if fcff.computation is not None:
        dominance_status, _, _ = _terminal_value_dominance(
            policy,
            fcff.computation,
        )
        if dominance_status == "exceeds_limit":
            warnings.append("terminal_value_dominance_limit_exceeded")
        elif dominance_status != "pass":
            warnings.append("terminal_value_dominance_control_not_available")
    if (
        fcff.computation is not None
        and fcff.computation.terminal_shares is not None
        and inputs.current_diluted_shares.value is not None
        and not math.isclose(
            fcff.computation.terminal_shares,
            float(inputs.current_diluted_shares.value),
            rel_tol=0.0,
            abs_tol=1e-12,
        )
    ):
        warnings.append("terminal_shares_are_diagnostic_only")
    return ValuationBundle(
        scenario_key=model_result.scenario_key,
        state=state,
        input_hash=model_result.input_hash,
        result_hash=str(model_result.result_hash),
        wacc_methods=_wacc_contract(inputs),
        selected_wacc_policy=inputs.selected_wacc_policy,
        valuation_methods=methods,
        peer_universe_version=inputs.peer_universe_version,
        peer_tickers=tuple(sorted({fact.ticker for fact in inputs.peer_facts})),
        terminal_value_diagnostics=_terminal_diagnostics(policy, inputs, fcff),
        ev_equity_bridge=bridge,
        sensitivities=(_sensitivity_grid(policy, inputs, bridge, fcff),),
        implied_per_share_reconciliation=_per_share_reconciliation(inputs, fcff),
        warnings=tuple(warnings),
        blockers=blockers,
    )


def build_professional_valuation_bundles(
    scenario_results: Sequence[ModelResult],
    inputs: ProfessionalValuationInputs,
) -> tuple[ValuationBundle, ...]:
    """Build one strict valuation bundle per frozen scenario result.

    The scenario result and scenario valuation policy sets must match exactly.
    This is a structural contract check: missing evidence inside either object is
    represented as a typed blocked/unavailable result, while an absent scenario
    object is a caller error and is rejected.
    """

    result_by_scenario: dict[str, ModelResult] = {}
    for result in scenario_results:
        if result.scenario_key in result_by_scenario:
            raise ValueError(f"duplicate scenario model result: {result.scenario_key}")
        result_by_scenario[result.scenario_key] = result
    policy_by_scenario = {policy.scenario_key: policy for policy in inputs.scenario_policies}
    if not result_by_scenario:
        raise ValueError("at least one scenario model result is required")
    if set(result_by_scenario) != set(policy_by_scenario):
        missing_policies = sorted(set(result_by_scenario) - set(policy_by_scenario))
        missing_results = sorted(set(policy_by_scenario) - set(result_by_scenario))
        raise ValueError(
            "scenario result/policy sets do not match: "
            f"missing_policies={missing_policies}, missing_results={missing_results}"
        )
    return tuple(
        _build_one_bundle(result_by_scenario[key], policy_by_scenario[key], inputs)
        for key in sorted(result_by_scenario)
    )


__all__ = [
    "BridgeCategory",
    "BridgeValue",
    "CompsPolicy",
    "DiscountTiming",
    "FCFEPolicy",
    "HistoricalTradingRangeInput",
    "MethodDecisionPolicy",
    "PeerValuationFact",
    "ProfessionalValuationInputs",
    "ReverseDCFPolicy",
    "ReverseDCFVariable",
    "SOTPComponent",
    "SOTPInput",
    "ScenarioValuationPolicy",
    "SourcedValue",
    "ValuationBasis",
    "WACCMethodInput",
    "build_professional_valuation_bundles",
]
