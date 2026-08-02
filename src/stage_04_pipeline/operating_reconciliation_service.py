"""Bind the deterministic operating model to one frozen statement view."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Iterable, Mapping, Sequence

from src.contracts.judgment_runs import canonical_semantic_hash
from src.stage_00_data.source_reconciliation import (
    SourceAmount,
    reconciliation_tolerance,
    source_amount_from_statement_fact,
)
from src.stage_02_valuation.input_assembler import (
    ValuationInputsWithLineage,
    apply_reconciled_operating_starts,
)
from src.stage_02_valuation.operating_reconciliation import (
    OperatingReconciliationResult,
    reconcile_operating_model,
)
from src.stage_04_pipeline.statement_reconciliation_service import (
    TickerStatementReconciliationRun,
)


_DURATION_ROLES = ("revenue", "cost_of_revenue", "capex", "da")
_INSTANT_ROLES = ("accounts_receivable", "accounts_payable")
_ROLE_STATEMENTS = {
    "revenue": "incomestatement",
    "cost_of_revenue": "incomestatement",
    "accounts_receivable": "balancesheet",
    "accounts_payable": "balancesheet",
    "inventory": "balancesheet",
    "capex": "cashflowstatement",
    "da": "cashflowstatement",
}


@dataclass(frozen=True, slots=True)
class TickerOperatingReconciliation:
    """Auditable operating tie-out plus its exact reported-fact selection."""

    result: OperatingReconciliationResult
    selected_fact_ids_by_role: Mapping[str, str]
    period_start: str | None
    period_end: str | None
    period_kind: str | None
    reporting_currency: str | None
    inventory_applicable: bool | None
    selection_reason_codes: tuple[str, ...] = ()

    @property
    def status(self) -> str:
        return self.result.status

    @property
    def reason_codes(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                (*self.selection_reason_codes, *self.result.reason_codes)
            )
        )

    def _identity_payload(self) -> dict[str, Any]:
        return {
            "result": self.result.to_dict(),
            "selected_fact_ids_by_role": dict(
                sorted(self.selected_fact_ids_by_role.items())
            ),
            "period_start": self.period_start,
            "period_end": self.period_end,
            "period_kind": self.period_kind,
            "reporting_currency": self.reporting_currency,
            "inventory_applicable": self.inventory_applicable,
            "reason_codes": self.reason_codes,
        }

    @property
    def fingerprint(self) -> str:
        return canonical_semantic_hash(self._identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.result.to_dict(),
            "selected_fact_ids_by_role": dict(
                sorted(self.selected_fact_ids_by_role.items())
            ),
            "period_start": self.period_start,
            "period_end": self.period_end,
            "period_kind": self.period_kind,
            "reporting_currency": self.reporting_currency,
            "inventory_applicable": self.inventory_applicable,
            "reason_codes": self.reason_codes,
            "fingerprint": self.fingerprint,
        }


def _source_rank(source: str) -> int:
    normalized = str(source).strip().lower()
    if normalized.startswith("ciq"):
        return 0
    if "filing_presentation" in normalized:
        return 1
    if "derived_ltm" in normalized:
        return 2
    return 10


def _period_kind(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"ltm", "ttm"}:
        return "ltm"
    if normalized in {"annual", "fy"}:
        return "annual"
    return normalized or "duration"


def _amounts_agree(amounts: Sequence[SourceAmount]) -> bool:
    if len(amounts) < 2:
        return True
    anchor = amounts[0]
    for amount in amounts[1:]:
        fx_rate = (
            anchor.usd_per_currency_unit
            or amount.usd_per_currency_unit
            or 1.0
        )
        tolerance = reconciliation_tolerance(
            anchor.base_value,
            amount.base_value,
            monetary=True,
            usd_per_currency_unit=fx_rate,
        )
        if abs(anchor.normalized_value - amount.normalized_value) > tolerance:
            return False
    return True


def _select_amount(
    role: str,
    candidates: Iterable[SourceAmount],
) -> tuple[SourceAmount | None, str | None]:
    ordered = sorted(
        candidates,
        key=lambda amount: (
            _source_rank(amount.source),
            amount.fact_id,
        ),
    )
    if not ordered:
        return None, f"operating.{role}_missing"
    best_rank = _source_rank(ordered[0].source)
    preferred = tuple(
        amount
        for amount in ordered
        if _source_rank(amount.source) == best_rank
    )
    if not _amounts_agree(preferred):
        return None, f"operating.{role}_ambiguous"
    return preferred[0], None


def _empty_artifact(
    *,
    valuation_inputs: ValuationInputsWithLineage,
    reasons: Sequence[str],
    failed: bool,
    period_start: str | None = None,
    period_end: str | None = None,
    period_kind: str | None = None,
    reporting_currency: str | None = None,
    inventory_applicable: bool | None = None,
    selected: Mapping[str, str] | None = None,
) -> TickerOperatingReconciliation:
    reason_codes = list(dict.fromkeys(str(reason) for reason in reasons))
    clamp_events = tuple(valuation_inputs.clamp_events)
    if any(event.was_clamped for event in clamp_events):
        reason_codes.append("operating.clamp_fired")
    result = OperatingReconciliationResult(
        status="failed" if failed else "pending",
        tie_outs=(),
        clamp_events=clamp_events,
        reason_codes=tuple(dict.fromkeys(reason_codes)),
    )
    return TickerOperatingReconciliation(
        result=result,
        selected_fact_ids_by_role=dict(selected or {}),
        period_start=period_start,
        period_end=period_end,
        period_kind=period_kind,
        reporting_currency=reporting_currency,
        inventory_applicable=inventory_applicable,
        selection_reason_codes=tuple(reason_codes),
    )


def _compatibility_reasons(
    selected: Mapping[str, SourceAmount],
) -> tuple[str, ...]:
    amounts = tuple(selected.values())
    reasons: list[str] = []
    if any(amount.unit_kind != "currency_scalar" for amount in amounts):
        reasons.append("operating.unit_mismatch")
    currencies = {
        amount.unit_currency
        for amount in amounts
        if amount.unit_currency is not None
    }
    if len(currencies) != 1:
        reasons.append("operating.currency_mismatch")
        return tuple(reasons)
    reporting_currency = next(iter(currencies))
    if reporting_currency != "USD":
        if any(
            amount.usd_per_currency_unit is None
            or not amount.fx_fingerprint
            for amount in amounts
        ):
            reasons.append("operating.fx_missing")
        rates = {
            float(amount.usd_per_currency_unit)
            for amount in amounts
            if amount.usd_per_currency_unit is not None
        }
        fingerprints = {
            amount.fx_fingerprint
            for amount in amounts
            if amount.fx_fingerprint
        }
        if len(rates) > 1 or len(fingerprints) > 1:
            reasons.append("operating.fx_mismatch")
    return tuple(dict.fromkeys(reasons))


def reconcile_operating_statement_facts(
    *,
    valuation_inputs: ValuationInputsWithLineage,
    statement_reconciliation_run: TickerStatementReconciliationRun,
    statement_facts: Iterable[Mapping[str, Any]],
) -> TickerOperatingReconciliation:
    """Select one exact reported period and tie it to model starting drivers."""

    ticker = str(valuation_inputs.ticker).strip().upper()
    if ticker != str(statement_reconciliation_run.ticker).strip().upper():
        return _empty_artifact(
            valuation_inputs=valuation_inputs,
            reasons=("operating.ticker_mismatch",),
            failed=True,
        )

    selected_ids = set(statement_reconciliation_run.selected_fact_ids)
    if not selected_ids:
        return _empty_artifact(
            valuation_inputs=valuation_inputs,
            reasons=("operating.selected_view_empty",),
            failed=False,
        )
    selected_rows = tuple(
        fact
        for fact in statement_facts
        if str(fact.get("fact_id") or "") in selected_ids
    )
    loaded_ids = {
        str(fact.get("fact_id") or "")
        for fact in selected_rows
    }
    if loaded_ids != selected_ids:
        return _empty_artifact(
            valuation_inputs=valuation_inputs,
            reasons=("operating.selected_fact_missing",),
            failed=True,
        )

    amounts: list[SourceAmount] = []
    for fact in selected_rows:
        dimensions = fact.get("dimensions") or {}
        if dimensions:
            continue
        # The decision-grade selected view also carries non-numeric presentation
        # rows (for example, disclosure-only balance-sheet concepts). They are
        # valid statement evidence but cannot participate in an operating amount
        # or role selection.
        if fact.get("numeric_value") is None:
            continue
        try:
            amounts.append(source_amount_from_statement_fact(fact))
        except (KeyError, TypeError, ValueError):
            return _empty_artifact(
                valuation_inputs=valuation_inputs,
                reasons=("operating.selected_fact_invalid",),
                failed=True,
            )

    duration_windows: dict[
        tuple[str, str, str],
        dict[str, list[SourceAmount]],
    ] = {}
    for amount in amounts:
        if (
            amount.canonical_key not in _DURATION_ROLES
            or not amount.period_start
            or str(amount.statement).strip().lower()
            != _ROLE_STATEMENTS[amount.canonical_key]
        ):
            continue
        window = (
            amount.period_start,
            amount.period_end,
            _period_kind(amount.period_kind),
        )
        duration_windows.setdefault(window, {}).setdefault(
            amount.canonical_key,
            [],
        ).append(amount)
    complete_windows = tuple(
        window
        for window, roles in duration_windows.items()
        if all(role in roles for role in _DURATION_ROLES)
    )
    if not complete_windows:
        available_duration_roles = {
            amount.canonical_key
            for amount in amounts
            if (
                amount.canonical_key in _DURATION_ROLES
                and amount.period_start
                and str(amount.statement).strip().lower()
                == _ROLE_STATEMENTS[amount.canonical_key]
            )
        }
        missing_duration_roles = [
            role
            for role in _DURATION_ROLES
            if role not in available_duration_roles
        ]
        reasons = [
            f"operating.{role}_missing"
            for role in missing_duration_roles
        ]
        if not reasons:
            reasons = ["operating.duration_window_incomplete"]
        return _empty_artifact(
            valuation_inputs=valuation_inputs,
            reasons=reasons,
            failed=False,
        )
    ranked_windows = sorted(
        complete_windows,
        key=lambda window: (
            1 if window[2] == "ltm" else 0,
            window[1],
            window[0],
        ),
        reverse=True,
    )
    window = ranked_windows[0]
    same_vintage_windows = {
        candidate
        for candidate in complete_windows
        if candidate[1:] == window[1:]
    }
    if len(same_vintage_windows) > 1:
        return _empty_artifact(
            valuation_inputs=valuation_inputs,
            reasons=("operating.duration_window_ambiguous",),
            failed=True,
        )

    selected: dict[str, SourceAmount] = {}
    selection_reasons: list[str] = []
    roles_for_window = duration_windows[window]
    for role in _DURATION_ROLES:
        amount, reason = _select_amount(role, roles_for_window.get(role, ()))
        if reason:
            selection_reasons.append(reason)
        elif amount is not None:
            selected[role] = amount

    instant_roles = (*_INSTANT_ROLES, "inventory")
    for role in instant_roles:
        candidates = (
            amount
            for amount in amounts
            if amount.canonical_key == role
            and amount.period_end == window[1]
            and not amount.period_start
            and str(amount.statement).strip().lower()
            == _ROLE_STATEMENTS[role]
        )
        amount, reason = _select_amount(role, candidates)
        if amount is not None:
            selected[role] = amount
        elif role != "inventory" and reason:
            selection_reasons.append(reason)

    statement_status = str(
        statement_reconciliation_run.readiness.status
    ).strip()
    inventory_applicable: bool | None
    if "inventory" in selected:
        inventory_applicable = True
    elif statement_status == "decision_grade":
        inventory_applicable = False
    else:
        inventory_applicable = None
        selection_reasons.append(
            "operating.inventory_applicability_unknown"
        )
    if statement_status != "decision_grade":
        selection_reasons.append(
            "operating.statement_not_decision_grade"
        )

    compatibility_reasons = _compatibility_reasons(selected)
    selection_reasons.extend(compatibility_reasons)
    selected_fact_ids = {
        role: amount.fact_id
        for role, amount in selected.items()
    }
    if selection_reasons:
        failed = any(
            reason.endswith(("_ambiguous", "_mismatch", "_invalid"))
            or reason in {
                "operating.fx_missing",
                "operating.selected_fact_missing",
            }
            for reason in selection_reasons
        )
        reporting_currencies = {
            amount.unit_currency
            for amount in selected.values()
            if amount.unit_currency
        }
        return _empty_artifact(
            valuation_inputs=valuation_inputs,
            reasons=selection_reasons,
            failed=failed,
            period_start=window[0],
            period_end=window[1],
            period_kind=window[2],
            reporting_currency=(
                next(iter(reporting_currencies))
                if len(reporting_currencies) == 1
                else None
            ),
            inventory_applicable=inventory_applicable,
            selected=selected_fact_ids,
        )

    unit_scale = float(
        valuation_inputs.claim_ledger.get("unit_scale") or 0.0
    )
    if unit_scale <= 0:
        return _empty_artifact(
            valuation_inputs=valuation_inputs,
            reasons=("operating.valuation_unit_scale_invalid",),
            failed=True,
            period_start=window[0],
            period_end=window[1],
            period_kind=window[2],
            inventory_applicable=inventory_applicable,
            selected=selected_fact_ids,
        )
    reported = {
        role: amount
        for role, amount in selected.items()
        if role != "inventory" or inventory_applicable
    }
    try:
        apply_reconciled_operating_starts(
            valuation_inputs,
            selected_amounts=selected,
            inventory_applicable=bool(inventory_applicable),
        )
    except ValueError as exc:
        return _empty_artifact(
            valuation_inputs=valuation_inputs,
            reasons=(str(exc),),
            failed=True,
            period_start=window[0],
            period_end=window[1],
            period_kind=window[2],
            reporting_currency=next(
                iter(
                    {
                        amount.unit_currency
                        for amount in selected.values()
                        if amount.unit_currency
                    }
                ),
                None,
            ),
            inventory_applicable=inventory_applicable,
            selected=selected_fact_ids,
        )
    scaled_drivers = replace(
        valuation_inputs.drivers,
        revenue_base=(
            float(valuation_inputs.drivers.revenue_base) * unit_scale
        ),
    )
    result = reconcile_operating_model(
        drivers=scaled_drivers,
        reported=reported,
        inventory_applicable=bool(inventory_applicable),
        clamp_events=valuation_inputs.clamp_events,
    )
    reporting_currency = next(
        iter(
            {
                amount.unit_currency
                for amount in reported.values()
                if amount.unit_currency
            }
        ),
        None,
    )
    return TickerOperatingReconciliation(
        result=result,
        selected_fact_ids_by_role=selected_fact_ids,
        period_start=window[0],
        period_end=window[1],
        period_kind=window[2],
        reporting_currency=reporting_currency,
        inventory_applicable=inventory_applicable,
    )


def reconcile_ticker_operating_model(
    conn: Any,
    *,
    valuation_inputs: ValuationInputsWithLineage,
    statement_reconciliation_run: TickerStatementReconciliationRun,
) -> TickerOperatingReconciliation:
    """Load the frozen selected view and reconcile one ticker's model starts."""

    from db.loader import load_statement_facts

    facts = load_statement_facts(
        conn,
        str(valuation_inputs.ticker).strip().upper(),
    )
    return reconcile_operating_statement_facts(
        valuation_inputs=valuation_inputs,
        statement_reconciliation_run=statement_reconciliation_run,
        statement_facts=facts,
    )


__all__ = [
    "TickerOperatingReconciliation",
    "reconcile_operating_statement_facts",
    "reconcile_ticker_operating_model",
]
