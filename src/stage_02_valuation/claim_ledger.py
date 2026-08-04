"""Pure exact-once reconciliation for the enterprise-value equity bridge."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from math import isclose
from typing import Any, Iterable, Mapping


ABSOLUTE_TOLERANCE_USD = 1_000_000.0
RELATIVE_TOLERANCE = 0.0005
EV_BRIDGE_COMPONENTS = frozenset(
    {
        "net_debt",
        "lease_liabilities",
        "non_operating_assets",
        "minority_interest",
        "preferred_equity",
        "pension_deficit",
        "options_value",
        "convertibles_value",
    }
)


@dataclass(frozen=True, slots=True)
class ReportedLine:
    line_id: str
    value: float
    source_ref: str
    currency: str | None = None
    period_end: str | None = None
    period_type: str | None = None
    semantic_type: str = "unknown"


@dataclass(frozen=True, slots=True)
class ClaimAllocation:
    parent_line_id: str
    allocation_id: str
    component: str
    sign: int
    value: float


@dataclass(frozen=True, slots=True)
class TieOut:
    name: str
    expected: float
    actual: float
    tolerance: float


@dataclass(frozen=True, slots=True)
class DuplicateAllocation:
    allocation_id: str
    components: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    duplicate_reported_line_ids: tuple[str, ...] = ()
    duplicate_allocations: tuple[DuplicateAllocation, ...] = ()
    unknown_parent_ids: tuple[str, ...] = ()
    currency_mismatches: tuple[str, ...] = ()
    period_mismatches: tuple[str, ...] = ()
    period_type_mismatches: tuple[str, ...] = ()
    semantic_errors: tuple[str, ...] = ()
    untied_parents: tuple[TieOut, ...] = ()
    untied_components: tuple[TieOut, ...] = ()
    unclaimed_allocation_ids: tuple[str, ...] = ()
    material_unclaimed_allocation_ids: tuple[str, ...] = ()

    @property
    def is_reconciled(self) -> bool:
        return not (
            self.duplicate_reported_line_ids
            or self.duplicate_allocations
            or self.unknown_parent_ids
            or self.currency_mismatches
            or self.period_mismatches
            or self.period_type_mismatches
            or self.semantic_errors
            or self.untied_parents
            or self.untied_components
        )

    @property
    def is_decision_grade(self) -> bool:
        return self.is_reconciled and not self.material_unclaimed_allocation_ids


class UnreconciledClaimLedgerError(ValueError):
    """Raised when valuation code attempts to consume an untied claim ledger."""

    def __init__(
        self,
        message: str,
        *,
        result: ReconciliationResult | None = None,
    ) -> None:
        super().__init__(message)
        self.result = result

    def to_dict(self) -> dict[str, Any]:
        result = self.result
        return {
            "status": "blocked",
            "reason_code": "claim_ledger_not_decision_grade",
            "message": str(self),
            "reconciliation": (
                _reconciliation_to_dict(result) if result is not None else None
            ),
        }


class ClaimReclassificationError(ValueError):
    """Raised when a proposed reclassification cannot preserve exact-once claims."""

    def __init__(
        self,
        message: str,
        *,
        reported_line: str,
        incumbent_components: Iterable[str] = (),
    ) -> None:
        super().__init__(message)
        self.reported_line = reported_line
        self.incumbent_components = tuple(sorted(set(incumbent_components)))


@dataclass(frozen=True, slots=True)
class ReclassificationResult:
    ledger: "ClaimLedger"
    reported_line: str
    from_component: str
    to_component: str
    reported_value: float
    derived_component_values: Mapping[str, float]


@dataclass(frozen=True, slots=True)
class ReclassificationBatchResult:
    ledger: "ClaimLedger"
    results: tuple[ReclassificationResult, ...]


def reconciliation_tolerance(expected: float, actual_gross: float) -> float:
    return max(
        ABSOLUTE_TOLERANCE_USD,
        RELATIVE_TOLERANCE * max(abs(expected), abs(actual_gross)),
    )


def _ties(expected: float, actual: float, actual_gross: float) -> tuple[bool, float]:
    tolerance = reconciliation_tolerance(expected, actual_gross)
    return isclose(expected, actual, rel_tol=0.0, abs_tol=tolerance), tolerance


_ASSET_SEMANTICS = frozenset(
    {
        "asset",
        "cash",
        "investment",
        "non_operating_asset",
    }
)
_LIABILITY_SEMANTICS = frozenset(
    {
        "liability",
        "debt",
        "lease_liability",
        "pension_liability",
        "financing_liability",
    }
)
_EQUITY_CLAIM_SEMANTICS = frozenset(
    {
        "equity_claim",
        "minority_interest",
        "preferred_equity",
        "option_claim",
        "convertible_claim",
    }
)
_CLAIM_COMPONENTS = EV_BRIDGE_COMPONENTS - {
    "net_debt",
    "non_operating_assets",
}


def _normalized_semantic(value: str | None) -> str:
    return str(value or "unknown").strip().lower()


def _target_polarity(component: str, semantic_type: str) -> int | None:
    """Return the bridge contribution sign implied by accounting semantics.

    ``None`` means the target is not safe for the reported-line semantic. This
    deliberately does not infer treatment from the old allocation sign: the
    sign is a consequence of the destination, not an agent-authored input.
    """

    semantic = _normalized_semantic(semantic_type)
    if semantic in {"", "unknown", "unspecified"}:
        return None
    if component == "unclaimed":
        return 1
    if component == "non_operating_assets":
        return 1 if semantic in _ASSET_SEMANTICS else None
    if component == "net_debt":
        if semantic in _ASSET_SEMANTICS:
            return -1
        if semantic in _LIABILITY_SEMANTICS | _EQUITY_CLAIM_SEMANTICS:
            return 1
        return None
    if component in _CLAIM_COMPONENTS:
        return (
            1
            if semantic in _LIABILITY_SEMANTICS | _EQUITY_CLAIM_SEMANTICS
            else None
        )
    return None


def _reconciliation_to_dict(result: ReconciliationResult) -> dict[str, Any]:
    return {
        "is_reconciled": result.is_reconciled,
        "is_decision_grade": result.is_decision_grade,
        "duplicate_reported_line_ids": list(
            result.duplicate_reported_line_ids
        ),
        "duplicate_allocations": [
            asdict(item) for item in result.duplicate_allocations
        ],
        "unknown_parent_ids": list(result.unknown_parent_ids),
        "currency_mismatches": list(result.currency_mismatches),
        "period_mismatches": list(result.period_mismatches),
        "period_type_mismatches": list(result.period_type_mismatches),
        "semantic_errors": list(result.semantic_errors),
        "untied_parents": [asdict(item) for item in result.untied_parents],
        "untied_components": [
            asdict(item) for item in result.untied_components
        ],
        "unclaimed_allocation_ids": list(result.unclaimed_allocation_ids),
        "material_unclaimed_allocation_ids": list(
            result.material_unclaimed_allocation_ids
        ),
    }


class ClaimLedger:
    """Allocate reported parent balances into signed EV-bridge components."""

    def __init__(
        self,
        *,
        reported_lines: Iterable[ReportedLine],
        allocations: Iterable[ClaimAllocation],
        component_values: Mapping[str, float],
        unit: str = "USD",
        currency: str = "USD",
        period_end: str | None = None,
        period_type: str = "instant",
    ) -> None:
        self.reported_lines = tuple(reported_lines)
        self.allocations = tuple(allocations)
        self.component_values = {
            str(component): float(value)
            for component, value in component_values.items()
        }
        self.unit = str(unit)
        self.currency = str(currency).strip().upper()
        self.period_end = (
            str(period_end).strip() if period_end is not None else None
        )
        self.period_type = str(period_type).strip().lower()

    def reconcile(self) -> ReconciliationResult:
        reported_line_counts = Counter(
            line.line_id for line in self.reported_lines
        )
        duplicate_reported_line_ids = tuple(
            line_id
            for line_id, count in sorted(reported_line_counts.items())
            if count > 1
        )
        allocation_counts = Counter(
            allocation.allocation_id for allocation in self.allocations
        )
        duplicate_allocations = tuple(
            DuplicateAllocation(
                allocation_id=allocation_id,
                components=tuple(
                    sorted(
                        {
                            allocation.component
                            for allocation in self.allocations
                            if allocation.allocation_id == allocation_id
                        }
                    )
                ),
            )
            for allocation_id, count in sorted(allocation_counts.items())
            if count > 1
        )

        parents = {line.line_id: line for line in self.reported_lines}
        unknown_parents = tuple(
            sorted(
                {
                    allocation.parent_line_id
                    for allocation in self.allocations
                    if allocation.parent_line_id not in parents
                }
            )
        )

        allocations_by_parent: dict[str, list[ClaimAllocation]] = defaultdict(list)
        allocations_by_component: dict[str, list[ClaimAllocation]] = defaultdict(list)
        for allocation in self.allocations:
            allocations_by_parent[allocation.parent_line_id].append(allocation)
            allocations_by_component[allocation.component].append(allocation)

        currency_mismatches = tuple(
            sorted(
                line.line_id
                for line in self.reported_lines
                if line.currency is not None
                and str(line.currency).strip().upper() != self.currency
            )
        )
        period_mismatches = tuple(
            sorted(
                line.line_id
                for line in self.reported_lines
                if self.period_end is not None
                and line.period_end is not None
                and str(line.period_end).strip() != self.period_end
            )
        )
        period_type_mismatches = tuple(
            sorted(
                line.line_id
                for line in self.reported_lines
                if line.period_type is not None
                and str(line.period_type).strip().lower() != self.period_type
            )
        )
        semantic_errors: list[str] = []
        for allocation in self.allocations:
            line = parents.get(allocation.parent_line_id)
            if line is None:
                continue
            if allocation.sign not in {-1, 1}:
                semantic_errors.append(
                    f"{allocation.allocation_id}: sign must be +1 or -1"
                )
                continue
            semantic = _normalized_semantic(line.semantic_type)
            if semantic in {"unknown", "unspecified", ""}:
                continue
            expected_sign = _target_polarity(
                allocation.component,
                semantic,
            )
            if expected_sign is None:
                semantic_errors.append(
                    f"{allocation.allocation_id}: {semantic} cannot feed "
                    f"{allocation.component}"
                )
            elif allocation.sign != expected_sign:
                semantic_errors.append(
                    f"{allocation.allocation_id}: {semantic} in "
                    f"{allocation.component} requires sign {expected_sign:+d}, "
                    f"not {allocation.sign:+d}"
                )

        untied_parents: list[TieOut] = []
        for parent_id, line in parents.items():
            parts = allocations_by_parent.get(parent_id, [])
            actual = sum(abs(allocation.value) for allocation in parts)
            ties, tolerance = _ties(line.value, actual, actual)
            if not ties:
                untied_parents.append(
                    TieOut(
                        name=parent_id,
                        expected=float(line.value),
                        actual=float(actual),
                        tolerance=tolerance,
                    )
                )

        untied_components: list[TieOut] = []
        component_names = set(self.component_values) | set(allocations_by_component)
        for component in sorted(component_names):
            parts = allocations_by_component.get(component, [])
            actual = sum(
                allocation.sign * allocation.value for allocation in parts
            )
            expected = self.component_values.get(component, 0.0)
            gross = sum(abs(allocation.value) for allocation in parts)
            ties, tolerance = _ties(expected, actual, gross)
            if not ties:
                untied_components.append(
                    TieOut(
                        name=component,
                        expected=float(expected),
                        actual=float(actual),
                        tolerance=tolerance,
                    )
                )

        unclaimed_allocation_ids = tuple(
            sorted(
                allocation.allocation_id
                for allocation in self.allocations
                if allocation.component == "unclaimed"
            )
        )
        reported_gross = sum(abs(line.value) for line in self.reported_lines)
        materiality_tolerance = reconciliation_tolerance(
            reported_gross,
            reported_gross,
        )
        material_unclaimed_allocation_ids = tuple(
            sorted(
                allocation.allocation_id
                for allocation in self.allocations
                if allocation.component == "unclaimed"
                and abs(allocation.value) > materiality_tolerance
            )
        )

        return ReconciliationResult(
            duplicate_reported_line_ids=duplicate_reported_line_ids,
            duplicate_allocations=duplicate_allocations,
            unknown_parent_ids=unknown_parents,
            currency_mismatches=currency_mismatches,
            period_mismatches=period_mismatches,
            period_type_mismatches=period_type_mismatches,
            semantic_errors=tuple(sorted(semantic_errors)),
            untied_parents=tuple(untied_parents),
            untied_components=tuple(untied_components),
            unclaimed_allocation_ids=unclaimed_allocation_ids,
            material_unclaimed_allocation_ids=(
                material_unclaimed_allocation_ids
            ),
        )

    def failure_message(self, result: ReconciliationResult | None = None) -> str:
        result = result or self.reconcile()
        failures: list[str] = []
        if result.duplicate_reported_line_ids:
            failures.append(
                "duplicate reported line IDs: "
                + ", ".join(result.duplicate_reported_line_ids)
            )
        for duplicate in result.duplicate_allocations:
            failures.append(
                f"allocation {duplicate.allocation_id!r} is claimed by "
                + ", ".join(duplicate.components)
            )
        if result.unknown_parent_ids:
            failures.append(
                "unknown reported lines: " + ", ".join(result.unknown_parent_ids)
            )
        if result.currency_mismatches:
            failures.append(
                f"currency mismatch against {self.currency}: "
                + ", ".join(result.currency_mismatches)
            )
        if result.period_mismatches:
            failures.append(
                f"period mismatch against {self.period_end}: "
                + ", ".join(result.period_mismatches)
            )
        if result.period_type_mismatches:
            failures.append(
                f"period semantics mismatch against {self.period_type}: "
                + ", ".join(result.period_type_mismatches)
            )
        failures.extend(result.semantic_errors)
        for tie in result.untied_parents:
            failures.append(
                f"reported line {tie.name!r} does not tie "
                f"(reported={tie.expected}, allocated={tie.actual}, "
                f"tolerance={tie.tolerance})"
            )
        for tie in result.untied_components:
            failures.append(
                f"component {tie.name!r} does not tie "
                f"(expected={tie.expected}, derived={tie.actual}, "
                f"tolerance={tie.tolerance})"
            )
        return "; ".join(failures) or "unknown reconciliation failure"

    def require_reconciled(self) -> ReconciliationResult:
        result = self.reconcile()
        if not result.is_reconciled:
            raise UnreconciledClaimLedgerError(
                "EV bridge claim ledger does not reconcile: "
                + self.failure_message(result),
                result=result,
            )
        return result

    def require_decision_grade(self) -> ReconciliationResult:
        result = self.require_reconciled()
        if result.material_unclaimed_allocation_ids:
            raise UnreconciledClaimLedgerError(
                "EV bridge claim ledger has material unclaimed lines: "
                + ", ".join(result.material_unclaimed_allocation_ids),
                result=result,
            )
        return result

    def to_dict(self) -> dict[str, Any]:
        result = self.reconcile()
        return {
            "unit": self.unit,
            "currency": self.currency,
            "period_end": self.period_end,
            "period_type": self.period_type,
            "reported_lines": [asdict(line) for line in self.reported_lines],
            "allocations": [asdict(allocation) for allocation in self.allocations],
            "component_values": dict(self.component_values),
            "reconciliation": {
                **_reconciliation_to_dict(result),
                "failure_message": (
                    None if result.is_reconciled else self.failure_message(result)
                ),
            },
            "fingerprint": self.fingerprint,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ClaimLedger":
        unit = str(payload.get("unit") or "USD")
        if unit != "USD":
            raise ValueError(
                "claim ledger is not in canonical USD; rebuild it from Step 1"
            )
        return cls(
            reported_lines=[
                ReportedLine(**dict(item))
                for item in payload.get("reported_lines") or []
            ],
            allocations=[
                ClaimAllocation(**dict(item))
                for item in payload.get("allocations") or []
            ],
            component_values=payload.get("component_values") or {},
            unit=unit,
            currency=str(payload.get("currency") or "USD"),
            period_end=(
                str(payload["period_end"])
                if payload.get("period_end") is not None
                else None
            ),
            period_type=str(payload.get("period_type") or "instant"),
        )

    @property
    def fingerprint(self) -> str:
        payload = {
            "reported_lines": [asdict(line) for line in self.reported_lines],
            "allocations": [asdict(item) for item in self.allocations],
            "component_values": dict(sorted(self.component_values.items())),
            "unit": self.unit,
            "currency": self.currency,
            "period_end": self.period_end,
            "period_type": self.period_type,
        }
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return sha256(encoded).hexdigest()

    def reclassify(
        self,
        *,
        reported_line: str,
        from_component: str,
        to_component: str,
    ) -> ReclassificationResult:
        """Move a reported line between components and derive all resulting values.

        The proposal supplies identity and treatment only. It never supplies a
        monetary amount. A parent split across incumbent components cannot be
        reclassified as a whole because that would consume already-claimed
        quantities a second time.
        """

        line_id = str(reported_line).strip()
        source_component = str(from_component).strip()
        target_component = str(to_component).strip()
        exact = [
            allocation
            for allocation in self.allocations
            if allocation.allocation_id == line_id
        ]
        matches = exact or [
            allocation
            for allocation in self.allocations
            if allocation.parent_line_id == line_id
        ]
        if not matches:
            raise ClaimReclassificationError(
                f"reported line {line_id!r} is not present in the claim ledger",
                reported_line=line_id,
            )

        incumbents = {allocation.component for allocation in matches}
        if incumbents != {source_component}:
            incumbent_text = ", ".join(sorted(incumbents))
            raise ClaimReclassificationError(
                f"reported line {line_id!r} is already claimed by "
                f"{incumbent_text}; it cannot be reclassified from "
                f"{source_component!r} to {target_component!r}",
                reported_line=line_id,
                incumbent_components=incumbents,
            )
        if source_component == target_component:
            raise ClaimReclassificationError(
                f"reported line {line_id!r} is already claimed by "
                f"{target_component}; the proposed reclassification is a duplicate",
                reported_line=line_id,
                incumbent_components=incumbents,
            )

        allocation_ids = {allocation.allocation_id for allocation in matches}
        parent_ids = {allocation.parent_line_id for allocation in matches}
        matched_lines = [
            line for line in self.reported_lines if line.line_id in parent_ids
        ]
        semantic_types = {
            _normalized_semantic(line.semantic_type) for line in matched_lines
        }
        if len(semantic_types) != 1:
            raise ClaimReclassificationError(
                f"reported line {line_id!r} has ambiguous accounting semantics: "
                + ", ".join(sorted(semantic_types)),
                reported_line=line_id,
                incumbent_components=incumbents,
            )
        semantic_type = next(iter(semantic_types), "unknown")
        target_sign = _target_polarity(target_component, semantic_type)
        if target_sign is None:
            raise ClaimReclassificationError(
                f"reported line {line_id!r} has {semantic_type} semantics, "
                f"which cannot be safely reclassified to {target_component!r}",
                reported_line=line_id,
                incumbent_components=incumbents,
            )

        source_value = sum(
            allocation.sign * allocation.value for allocation in matches
        )
        target_value = sum(
            target_sign * allocation.value for allocation in matches
        )
        updated_allocations = [
            ClaimAllocation(
                parent_line_id=allocation.parent_line_id,
                allocation_id=allocation.allocation_id,
                component=(
                    target_component
                    if allocation.allocation_id in allocation_ids
                    else allocation.component
                ),
                sign=(
                    target_sign
                    if allocation.allocation_id in allocation_ids
                    else allocation.sign
                ),
                value=allocation.value,
            )
            for allocation in self.allocations
        ]
        component_values = dict(self.component_values)
        component_values[source_component] = (
            component_values.get(source_component, 0.0) - source_value
        )
        component_values[target_component] = (
            component_values.get(target_component, 0.0) + target_value
        )
        updated = ClaimLedger(
            reported_lines=self.reported_lines,
            allocations=updated_allocations,
            component_values=component_values,
            unit=self.unit,
            currency=self.currency,
            period_end=self.period_end,
            period_type=self.period_type,
        )
        updated.require_reconciled()
        return ReclassificationResult(
            ledger=updated,
            reported_line=line_id,
            from_component=source_component,
            to_component=target_component,
            reported_value=sum(abs(allocation.value) for allocation in matches),
            derived_component_values=dict(component_values),
        )

    def reclassify_many(
        self,
        proposals: Iterable[Mapping[str, str]],
    ) -> ReclassificationBatchResult:
        """Apply a proposal family cumulatively and return only if all tie.

        The original ledger is immutable. If any proposal is invalid, this
        method raises before exposing a partially applied batch, so callers
        cannot queue two changes derived from incompatible ledger states.
        """

        working = self
        results: list[ReclassificationResult] = []
        for proposal in proposals:
            result = working.reclassify(
                reported_line=str(proposal.get("reported_line") or ""),
                from_component=str(proposal.get("from_component") or ""),
                to_component=str(proposal.get("to_component") or ""),
            )
            working = result.ledger
            results.append(result)
        working.require_reconciled()
        return ReclassificationBatchResult(
            ledger=working,
            results=tuple(results),
        )


@dataclass(frozen=True, slots=True)
class ReconciledEVBridge:
    net_debt: float
    lease_liabilities: float = 0.0
    non_operating_assets: float = 0.0
    minority_interest: float = 0.0
    preferred_equity: float = 0.0
    pension_deficit: float = 0.0
    options_value: float = 0.0
    convertibles_value: float = 0.0

    @classmethod
    def from_ledger(cls, ledger: ClaimLedger) -> "ReconciledEVBridge":
        ledger.require_reconciled()
        components = ledger.component_values
        return cls(
            net_debt=components.get("net_debt", 0.0),
            lease_liabilities=components.get("lease_liabilities", 0.0),
            non_operating_assets=components.get("non_operating_assets", 0.0),
            minority_interest=components.get("minority_interest", 0.0),
            preferred_equity=components.get("preferred_equity", 0.0),
            pension_deficit=components.get("pension_deficit", 0.0),
            options_value=components.get("options_value", 0.0),
            convertibles_value=components.get("convertibles_value", 0.0),
        )

    @property
    def ev_to_equity_adjustment(self) -> float:
        return (
            self.net_debt
            + self.lease_liabilities
            + self.minority_interest
            + self.preferred_equity
            + self.pension_deficit
            + self.options_value
            + self.convertibles_value
            - self.non_operating_assets
        )

    def equity_value(self, *, enterprise_value: float) -> float:
        return float(enterprise_value) - self.ev_to_equity_adjustment
