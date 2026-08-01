"""Pure source and statement reconciliation for decision-grade histories.

This module compares normalized evidence only. It does not select accounting
treatments, mutate valuation inputs, call an LLM, or write the PM queue.
"""

from __future__ import annotations

from datetime import date

from dataclasses import dataclass, field
import hashlib
import json
import math
import re
from typing import Any, Iterable, Literal, Mapping, Sequence


ABSOLUTE_CURRENCY_TOLERANCE = 1_000_000.0
RELATIVE_TOLERANCE = 0.0005

ComparisonStatus = Literal[
    "matched",
    "material_disagreement",
    "currency_mismatch",
    "unit_mismatch",
    "sign_rule_mismatch",
    "fx_missing",
    "fx_mismatch",
]
ReconciliationStatus = Literal["pass", "review_required", "not_comparable"]
StatementCheckStatus = Literal["pass", "fail", "not_ready"]
ReadinessStatus = Literal["decision_grade", "provisional", "blocked"]

_CANONICAL_CONCEPT_ALIASES = {
    "revenue": "revenue",
    "revenues": "revenue",
    "netsales": "revenue",
    "salesrevenuenet": "revenue",
    "revenuefromcontractwithcustomerexcludingassessedtax": "revenue",
    "operatingincome": "operating_income",
    "operatingincomeloss": "operating_income",
    "netincomeloss": "net_income",
    "netincome": "net_income",
    "grossprofit": "gross_profit",
    "costofrevenue": "cost_of_revenue",
    "costofgoodssold": "cost_of_revenue",
    "costofsales": "cost_of_revenue",
    "capitalexpenditure": "capex",
    "capitalexpenditures": "capex",
    "paymentstoacquirepropertyplantandequipment": "capex",
    "paymentstoacquireproductiveassets": "capex",
    "additionstopropertyandequipment": "capex",
    "purchasesofpropertyplantandequipment": "capex",
    "depreciationandamortization": "da",
    "depreciationamort": "da",
    "depreciationdepletionandamortization": "da",
    "depreciationdepletionandamortizationpropertyplantandequipment": "da",
    "da": "da",
    "accountsreceivable": "accounts_receivable",
    "accountsreceivablenetcurrent": "accounts_receivable",
    "accountsnotesandloansreceivablenetcurrent": "accounts_receivable",
    "receivablesnetcurrent": "accounts_receivable",
    "accountspayable": "accounts_payable",
    "accountspayablecurrent": "accounts_payable",
    "inventory": "inventory",
    "inventories": "inventory",
    "inventorynet": "inventory",
    "incometaxexpensebenefit": "income_tax",
    "incometaxexpense": "income_tax",
    "tax": "income_tax",
    "weightedaveragenumberofdilutedsharesoutstanding": "diluted_weighted_average_shares",
    "weightedavgdilutedsharesout": "diluted_weighted_average_shares",
    "weightedaveragenumberofsharesoutstandingbasic": "basic_weighted_average_shares",
    "commonstocksharesoutstanding": "shares_outstanding",
    "sharesoutstanding": "shares_outstanding",
    "earningspersharediluted": "diluted_eps",
    "assets": "assets",
    "totalassets": "assets",
    "liabilities": "liabilities",
    "totalliabilities": "liabilities",
    "stockholdersequity": "equity_parent",
    "stockholdersequityincludingportionattributabletononcontrollinginterest": "equity_including_nci",
    "totalstockholdersequity": "equity_parent",
    "totalequity": "equity_including_nci",
    "minorityinterest": "noncontrolling_interest",
    "noncontrollinginterestinconsolidatedentity": "noncontrolling_interest",
    "liabilitiesandstockholdersequity": "liabilities_and_equity",
    "liabilitiesandpartnerscapital": "liabilities_and_equity",
    "cash": "cash_and_equivalents",
    "cashandequivalents": "cash_and_equivalents",
    "cashandcashequivalentsatcarryingvalue": "cash_and_equivalents",
    "cashcashequivalentsrestrictedcashandrestrictedcashequivalents": "cash_including_restricted",
    "cashandcashequivalentsperiodincreasedecrease": "net_change_in_cash_and_equivalents",
    "cashcashequivalentsrestrictedcashandrestrictedcashequivalentsperiodincreasedecreaseincludingexchangerateeffect": "net_change_in_cash_including_restricted",
    "cashcashequivalentsrestrictedcashandrestrictedcashequivalentsperiodincreasedecreaseexcludingexchangerateeffect": "net_change_in_cash_including_restricted",
    "netcashprovidedbyusedinoperatingactivities": "operating_cash_flow",
    "netcashfromoperations": "operating_cash_flow",
    "netcashprovidedbyoperatingactivities": "operating_cash_flow",
    # CIQ workbook row names. Provider vocabulary, not issuer-specific branches.
    "cashfromops": "operating_cash_flow",
    "cashfromoperations": "operating_cash_flow",
    "netchangeincash": "net_change_in_cash_and_equivalents",
    "netcashprovidedbyusedininvestingactivities": "investing_cash_flow",
    "netcashprovidedbyusedinfinancingactivities": "financing_cash_flow",
}


def reconciliation_tolerance(
    left: float,
    right: float,
    *,
    monetary: bool,
    usd_per_currency_unit: float = 1.0,
) -> float:
    """Apply the PM-set 0.05% gross tolerance and $1m monetary floor."""

    relative = RELATIVE_TOLERANCE * max(abs(left), abs(right))
    if not monetary:
        return max(1e-9, relative)
    if (
        not math.isfinite(float(usd_per_currency_unit))
        or float(usd_per_currency_unit) <= 0
    ):
        raise ValueError("usd_per_currency_unit must be finite and positive")
    reporting_currency_floor = (
        ABSOLUTE_CURRENCY_TOLERANCE / float(usd_per_currency_unit)
    )
    return max(reporting_currency_floor, relative)


def _within_tolerance(difference: float, tolerance: float) -> bool:
    return difference <= tolerance or math.isclose(
        difference,
        tolerance,
        rel_tol=1e-12,
        abs_tol=1e-6,
    )


def _slug(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


# The canonical keys an LTM window must carry before it can support a valuation.
# PM decision 6 targets five annual periods plus LTM and says LTM is built only from
# period-compatible facts, so readiness is measured against these keys rather than
# against every presented line item.
LTM_REQUIRED_CANONICAL_KEYS = frozenset(
    {
        "revenue",
        "operating_income",
        "net_income",
        "da",
        "capex",
        "operating_cash_flow",
    }
)


def canonical_statement_key(
    concept: str | None,
    label: str | None = None,
) -> str:
    """Map common XBRL/CIQ names without issuer-specific branches."""

    raw_concept = str(concept or "")
    local_concept = raw_concept.rsplit(":", 1)[-1]
    if ":" not in raw_concept and "_" in local_concept:
        _, candidate = local_concept.split("_", 1)
        if candidate[:1].isupper():
            local_concept = candidate
    for candidate in (local_concept, label):
        token = _slug(candidate)
        if token in _CANONICAL_CONCEPT_ALIASES:
            return _CANONICAL_CONCEPT_ALIASES[token]
    fallback = re.sub(
        r"[^a-z0-9]+",
        "_",
        str(label or local_concept or "unknown").lower(),
    ).strip("_")
    return fallback or "unknown"


def _dimension_key(dimensions: Mapping[str, str]) -> tuple[tuple[str, str], ...]:
    return tuple(
        sorted((str(key), str(value)) for key, value in dimensions.items())
    )


def _unit_semantics(
    unit: str | None,
    currency: str | None,
) -> tuple[str, str | None]:
    """Return a deterministic quantity kind and embedded currency.

    Currency scalars, currency-per-share quantities, shares, and pure ratios
    are deliberately distinct. A populated ``currency`` field alone never
    turns a per-share value into a currency scalar.
    """

    raw = str(unit or "").strip()
    token = raw.lower().replace("\\", "/")
    token = re.sub(r"\s+", "", token)
    token = token.replace("iso4217:", "").replace("xbrli:", "")
    normalized_currency = str(currency or "").strip().upper() or None

    if token in {"share", "shares"}:
        return "shares", None
    if token in {"pure", "dimensionless", "ratio", "percent", "%"}:
        return "dimensionless", None

    per_share_match = re.fullmatch(
        r"([a-z]{3})(?:/|per)shares?",
        token,
    )
    if per_share_match:
        return "currency_per_share", per_share_match.group(1).upper()

    if re.fullmatch(r"[a-z]{3}", token):
        return "currency_scalar", token.upper()
    if not token and normalized_currency:
        return "currency_scalar", normalized_currency
    if not token:
        return "unknown", normalized_currency
    return f"other:{token}", normalized_currency


@dataclass(frozen=True)
class SourceAmount:
    ticker: str
    source: str
    statement: str
    canonical_key: str
    value: float
    scale_factor: float
    unit: str | None
    currency: str | None
    period_end: str
    fact_id: str
    source_locator: str | None
    period_start: str | None = None
    period_kind: str | None = None
    dimensions: Mapping[str, str] = field(default_factory=dict)
    vintage: str | None = None
    economic_sign: int = 1
    sign_rule: str | None = None
    usd_per_currency_unit: float | None = None
    fx_date: str | None = None
    fx_source: str | None = None
    fx_fingerprint: str | None = None
    statement_role: str | None = None
    presentation_path: str | None = None
    context_ref: str | None = None

    def __post_init__(self) -> None:
        if not str(self.ticker).strip():
            raise ValueError("source amount requires ticker")
        if not str(self.canonical_key).strip():
            raise ValueError("source amount requires canonical_key")
        if not math.isfinite(float(self.value)):
            raise ValueError("source amount value must be finite")
        if not math.isfinite(float(self.scale_factor)) or self.scale_factor <= 0:
            raise ValueError("source amount scale_factor must be finite and positive")
        if self.economic_sign not in {-1, 1}:
            raise ValueError("source amount economic_sign must be -1 or 1")
        if self.usd_per_currency_unit is not None and (
            not math.isfinite(float(self.usd_per_currency_unit))
            or float(self.usd_per_currency_unit) <= 0
        ):
            raise ValueError(
                "source amount usd_per_currency_unit must be finite and positive"
            )

    @property
    def base_value(self) -> float:
        return float(self.value) * float(self.scale_factor)

    @property
    def normalized_value(self) -> float:
        return self.base_value * self.economic_sign

    @property
    def unit_kind(self) -> str:
        return _unit_semantics(self.unit, self.currency)[0]

    @property
    def unit_currency(self) -> str | None:
        return _unit_semantics(self.unit, self.currency)[1]

    @property
    def monetary(self) -> bool:
        return self.unit_kind == "currency_scalar"


@dataclass(frozen=True)
class SourceComparison:
    ticker: str
    statement: str
    canonical_key: str
    period_end: str
    xbrl_fact_id: str
    ciq_fact_id: str
    xbrl_base_value: float
    ciq_base_value: float
    difference: float | None
    tolerance: float | None
    status: ComparisonStatus


@dataclass(frozen=True)
class ExpectedSourceQuantity:
    ticker: str
    statement: str
    canonical_key: str
    period_end: str
    period_start: str | None = None
    period_kind: str | None = None


@dataclass(frozen=True)
class ReconciliationFinding:
    finding_id: str
    ticker: str
    finding_type: str
    severity: Literal["warning", "blocking"]
    title: str
    description: str
    canonical_key: str
    statement: str
    period_end: str
    source_fact_ids: tuple[str, ...]
    source_locators: tuple[str, ...]
    observed_values: Mapping[str, float | str | None]
    tolerance: float | None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def blocking(self) -> bool:
        return self.severity == "blocking"

    def as_queue_payload(self) -> dict[str, Any]:
        """Return a serialization boundary consumable by the PM queue adapter."""

        return {
            "ticker": self.ticker,
            "profile_name": "statement_reconciliation",
            "item_type": "advisory_finding",
            "title": self.title,
            "summary": self.description,
            "status": "pending",
            "evidence_anchor_ids": list(self.source_fact_ids),
            "qualitative_importance": "high" if self.blocking else "medium",
            "adapter_links": {"reconciliation_finding_id": self.finding_id},
            "metadata": {
                "reconciliation_finding_id": self.finding_id,
                "blocking": self.blocking,
                "source_locators": list(self.source_locators),
                "finding_metadata": {
                    "finding_type": self.finding_type,
                    "canonical_key": self.canonical_key,
                    "statement": self.statement,
                    "period_end": self.period_end,
                    "observed_values": dict(self.observed_values),
                    "tolerance": self.tolerance,
                    **dict(self.metadata),
                },
            },
        }


@dataclass(frozen=True)
class SourceReconciliationResult:
    status: ReconciliationStatus
    decision_grade: bool
    comparisons: tuple[SourceComparison, ...]
    findings: tuple[ReconciliationFinding, ...]
    overlap_count: int
    coverage_attested: bool = False
    expected_quantity_count: int = 0
    missing_expected_count: int = 0


@dataclass(frozen=True)
class StatementCheckResult:
    check_name: str
    status: StatementCheckStatus
    expected_value: float | None
    actual_value: float | None
    difference: float | None
    tolerance: float | None
    source_fact_ids: tuple[str, ...]
    finding: ReconciliationFinding | None

    @property
    def ready(self) -> bool:
        return self.status == "pass"


@dataclass(frozen=True)
class StatementReadinessResult:
    status: ReadinessStatus
    decision_grade: bool
    annual_period_count: int
    ltm_status: str
    source_reconciliation: SourceReconciliationResult
    checks: tuple[StatementCheckResult, ...]
    findings: tuple[ReconciliationFinding, ...]
    reason_codes: tuple[str, ...]


def _default_sign_normalization(
    *,
    source: str,
    canonical_key: str,
) -> tuple[int, str | None]:
    """Return documented provider display-sign semantics without taking abs()."""

    if canonical_key != "capex":
        return 1, None
    if source.lower().startswith("ciq"):
        return -1, "cash_outflow_positive_v1"
    if source.lower().startswith("sec_xbrl"):
        return 1, "cash_outflow_positive_v1"
    return 1, None


def source_amount_from_statement_fact(
    fact: Mapping[str, Any],
    *,
    canonical_key: str | None = None,
) -> SourceAmount:
    """Adapt a persisted statement-fact row to the comparison contract."""

    numeric_value = fact.get("numeric_value")
    if numeric_value is None:
        raise ValueError("statement fact has no numeric_value")
    dimensions = fact.get("dimensions")
    if dimensions is None:
        metadata = fact.get("metadata") or {}
        dimensions = metadata.get("dimensions") or {}
    metadata = fact.get("metadata") or {}
    context = fact.get("context") or metadata.get("context") or {}
    hierarchy = fact.get("hierarchy") or metadata.get("hierarchy") or {}
    normalization = context.get("normalization") or {}
    fx = context.get("fx") or {}
    period_end = fact.get("period_end") or metadata.get("period_end")
    if not period_end:
        raise ValueError("statement fact has no period_end")
    source = str(fact.get("source") or metadata.get("source") or "")
    resolved_canonical_key = (
        canonical_key
        or str(fact.get("canonical_key") or "")
        or canonical_statement_key(
            str(fact.get("concept") or fact.get("fact_name") or ""),
            str(fact.get("label") or metadata.get("label") or ""),
        )
    )
    explicit_economic_sign = (
        fact.get("economic_sign")
        if fact.get("economic_sign") is not None
        else normalization.get("economic_sign")
    )
    explicit_sign_rule = (
        fact.get("sign_rule") or normalization.get("sign_rule")
    )
    default_economic_sign, default_sign_rule = _default_sign_normalization(
        source=source,
        canonical_key=resolved_canonical_key,
    )
    return SourceAmount(
        ticker=str(fact["ticker"]).upper(),
        source=source,
        statement=str(
            fact.get("statement") or metadata.get("statement_type") or ""
        ),
        canonical_key=resolved_canonical_key,
        value=float(numeric_value),
        scale_factor=float(fact.get("scale_factor") or 1.0),
        unit=(
            str(fact["unit"])
            if fact.get("unit") is not None
            else None
        ),
        currency=(
            str(fact["currency"]).upper()
            if fact.get("currency")
            else None
        ),
        period_start=(
            str(fact.get("period_start") or metadata.get("period_start"))
            if fact.get("period_start") or metadata.get("period_start")
            else None
        ),
        period_end=str(period_end),
        period_kind=(
            str(fact["period_kind"]) if fact.get("period_kind") else None
        ),
        dimensions={
            str(key): str(value)
            for key, value in dict(dimensions).items()
        },
        vintage=(
            str(
                fact.get("filing_date")
                or metadata.get("filing_date")
                or fact.get("source_run_id")
            )
            if (
                fact.get("filing_date")
                or metadata.get("filing_date")
                or fact.get("source_run_id")
            )
            else None
        ),
        economic_sign=int(
            explicit_economic_sign
            if explicit_economic_sign is not None
            else default_economic_sign
        ),
        sign_rule=(
            str(explicit_sign_rule)
            if explicit_sign_rule
            else default_sign_rule
            if explicit_economic_sign is None
            else None
        ),
        usd_per_currency_unit=(
            float(
                fact.get("usd_per_currency_unit")
                or fx.get("usd_per_currency_unit")
            )
            if (
                fact.get("usd_per_currency_unit") is not None
                or fx.get("usd_per_currency_unit") is not None
            )
            else None
        ),
        fx_date=(
            str(fact.get("fx_date") or fx.get("date"))
            if fact.get("fx_date") or fx.get("date")
            else None
        ),
        fx_source=(
            str(fact.get("fx_source") or fx.get("source"))
            if fact.get("fx_source") or fx.get("source")
            else None
        ),
        fx_fingerprint=(
            str(fact.get("fx_fingerprint") or fx.get("fingerprint"))
            if fact.get("fx_fingerprint") or fx.get("fingerprint")
            else None
        ),
        statement_role=(
            str(
                fact.get("statement_role")
                or hierarchy.get("statement_role")
            )
            if fact.get("statement_role") or hierarchy.get("statement_role")
            else None
        ),
        presentation_path=(
            str(
                fact.get("presentation_path")
                or hierarchy.get("presentation_path")
            )
            if fact.get("presentation_path")
            or hierarchy.get("presentation_path")
            else None
        ),
        context_ref=(
            str(fact.get("context_ref"))
            if fact.get("context_ref")
            else None
        ),
        fact_id=str(fact["fact_id"]),
        source_locator=(
            str(fact["source_locator"])
            if fact.get("source_locator")
            else None
        ),
    )


def _check_finding(
    *,
    finding_type: str,
    title: str,
    description: str,
    anchor: SourceAmount,
    source_amounts: Iterable[SourceAmount],
    observed_values: Mapping[str, float | str | None],
    tolerance: float | None,
) -> ReconciliationFinding:
    amounts = tuple(source_amounts)
    identity = json.dumps(
        {
            "finding_type": finding_type,
            "ticker": anchor.ticker.upper(),
            "period_end": anchor.period_end,
            "source_fact_ids": sorted(amount.fact_id for amount in amounts),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return ReconciliationFinding(
        finding_id=(
            f"statement-check:"
            f"{hashlib.sha256(identity.encode()).hexdigest()[:24]}"
        ),
        ticker=anchor.ticker.upper(),
        finding_type=finding_type,
        severity="blocking",
        title=title,
        description=description,
        canonical_key=finding_type,
        statement=anchor.statement,
        period_end=anchor.period_end,
        source_fact_ids=tuple(amount.fact_id for amount in amounts),
        source_locators=tuple(
            amount.source_locator
            for amount in amounts
            if amount.source_locator
        ),
        observed_values=dict(observed_values),
        tolerance=tolerance,
    )


def validate_balance_sheet_identity(
    *,
    assets: SourceAmount,
    liabilities_and_equity: SourceAmount | None = None,
    liabilities: SourceAmount | None = None,
    equity: SourceAmount | None = None,
) -> StatementCheckResult:
    """Validate Assets = Liabilities + Equity using available face totals."""

    if liabilities_and_equity is not None:
        rhs = liabilities_and_equity.base_value
        rhs_amounts = (liabilities_and_equity,)
        observed = {
            "assets": assets.base_value,
            "liabilities_and_equity": rhs,
        }
    elif liabilities is not None and equity is not None:
        rhs = liabilities.base_value + equity.base_value
        rhs_amounts = (liabilities, equity)
        observed = {
            "assets": assets.base_value,
            "liabilities": liabilities.base_value,
            "equity": equity.base_value,
        }
    else:
        available = tuple(
            amount
            for amount in (assets, liabilities_and_equity, liabilities, equity)
            if amount is not None
        )
        finding = _check_finding(
            finding_type="balance_sheet_identity_not_ready",
            title="Balance-sheet identity cannot be tested",
            description=(
                "Assets are present, but neither liabilities-and-equity nor "
                "both liabilities and equity are available."
            ),
            anchor=assets,
            source_amounts=available,
            observed_values={
                amount.canonical_key: amount.base_value for amount in available
            },
            tolerance=None,
        )
        return StatementCheckResult(
            check_name="balance_sheet_identity",
            status="not_ready",
            expected_value=None,
            actual_value=assets.base_value,
            difference=None,
            tolerance=None,
            source_fact_ids=tuple(amount.fact_id for amount in available),
            finding=finding,
        )

    all_amounts = (assets, *rhs_amounts)
    difference = abs(assets.base_value - rhs)
    tolerance = reconciliation_tolerance(
        assets.base_value,
        rhs,
        monetary=any(amount.monetary for amount in all_amounts),
    )
    status: StatementCheckStatus = (
        "pass" if _within_tolerance(difference, tolerance) else "fail"
    )
    finding = None
    if status == "fail":
        finding = _check_finding(
            finding_type="balance_sheet_identity_failure",
            title="Balance sheet does not balance",
            description=(
                f"Assets differ from liabilities plus equity by {difference:g}, "
                f"above the {tolerance:g} tolerance."
            ),
            anchor=assets,
            source_amounts=all_amounts,
            observed_values=observed,
            tolerance=tolerance,
        )
    return StatementCheckResult(
        check_name="balance_sheet_identity",
        status=status,
        expected_value=rhs,
        actual_value=assets.base_value,
        difference=difference,
        tolerance=tolerance,
        source_fact_ids=tuple(amount.fact_id for amount in all_amounts),
        finding=finding,
    )


def validate_cash_bridge(
    *,
    beginning_cash: SourceAmount | None,
    net_change: SourceAmount | None,
    ending_cash: SourceAmount | None,
) -> StatementCheckResult:
    """Validate beginning cash + reported change = ending cash."""

    available = tuple(
        amount
        for amount in (beginning_cash, net_change, ending_cash)
        if amount is not None
    )
    if (
        beginning_cash is None
        or net_change is None
        or ending_cash is None
    ):
        if not available:
            raise ValueError("cash bridge requires at least one source amount")
        anchor = available[-1]
        finding = _check_finding(
            finding_type="cash_flow_to_cash_bridge_not_ready",
            title="Cash-flow-to-cash bridge cannot be tested",
            description=(
                "Beginning cash, net change in cash, and ending cash are all "
                "required before the bridge can become decision-grade."
            ),
            anchor=anchor,
            source_amounts=available,
            observed_values={
                amount.canonical_key: amount.base_value for amount in available
            },
            tolerance=None,
        )
        return StatementCheckResult(
            check_name="cash_flow_to_cash_bridge",
            status="not_ready",
            expected_value=None,
            actual_value=(
                ending_cash.base_value if ending_cash is not None else None
            ),
            difference=None,
            tolerance=None,
            source_fact_ids=tuple(amount.fact_id for amount in available),
            finding=finding,
        )

    expected = beginning_cash.base_value + net_change.base_value
    actual = ending_cash.base_value
    difference = abs(expected - actual)
    tolerance = reconciliation_tolerance(
        expected,
        actual,
        monetary=any(amount.monetary for amount in available),
    )
    status: StatementCheckStatus = (
        "pass" if _within_tolerance(difference, tolerance) else "fail"
    )
    finding = None
    if status == "fail":
        finding = _check_finding(
            finding_type="cash_flow_to_cash_bridge_failure",
            title="Cash flow does not bridge to ending cash",
            description=(
                f"Beginning cash plus net change differs from ending cash by "
                f"{difference:g}, above the {tolerance:g} tolerance."
            ),
            anchor=ending_cash,
            source_amounts=available,
            observed_values={
                "beginning_cash": beginning_cash.base_value,
                "net_change_in_cash": net_change.base_value,
                "ending_cash": ending_cash.base_value,
            },
            tolerance=tolerance,
        )
    return StatementCheckResult(
        check_name="cash_flow_to_cash_bridge",
        status=status,
        expected_value=expected,
        actual_value=actual,
        difference=difference,
        tolerance=tolerance,
        source_fact_ids=tuple(amount.fact_id for amount in available),
        finding=finding,
    )


def validate_calculation_rollup(
    *,
    parent: SourceAmount,
    components: Sequence[SourceAmount],
    weights: Sequence[float] | None = None,
) -> StatementCheckResult:
    """Validate an available source calculation relationship.

    XBRL calculation-linkbase weights can be passed explicitly; ordinary
    additive rollups use the default weight of ``1`` for every component.
    """

    if not components:
        finding = _check_finding(
            finding_type="source_calculation_rollup_not_ready",
            title=f"{parent.canonical_key}: calculation rollup is incomplete",
            description="The source parent exists but has no available components.",
            anchor=parent,
            source_amounts=(parent,),
            observed_values={"parent": parent.base_value},
            tolerance=None,
        )
        return StatementCheckResult(
            check_name="source_calculation_rollup",
            status="not_ready",
            expected_value=None,
            actual_value=parent.base_value,
            difference=None,
            tolerance=None,
            source_fact_ids=(parent.fact_id,),
            finding=finding,
        )
    resolved_weights = (
        tuple(float(weight) for weight in weights)
        if weights is not None
        else tuple(1.0 for _ in components)
    )
    if len(resolved_weights) != len(components):
        raise ValueError("calculation rollup weights must match components")
    expected = sum(
        amount.base_value * weight
        for amount, weight in zip(components, resolved_weights)
    )
    actual = parent.base_value
    difference = abs(expected - actual)
    all_amounts = (parent, *components)
    tolerance = reconciliation_tolerance(
        expected,
        actual,
        monetary=any(amount.monetary for amount in all_amounts),
    )
    status: StatementCheckStatus = (
        "pass" if _within_tolerance(difference, tolerance) else "fail"
    )
    finding = None
    if status == "fail":
        finding = _check_finding(
            finding_type="source_calculation_rollup_failure",
            title=f"{parent.canonical_key}: source calculation does not roll up",
            description=(
                f"Weighted components differ from the reported parent by "
                f"{difference:g}, above the {tolerance:g} tolerance."
            ),
            anchor=parent,
            source_amounts=all_amounts,
            observed_values={
                "parent": actual,
                **{
                    f"component:{amount.fact_id}": amount.base_value * weight
                    for amount, weight in zip(components, resolved_weights)
                },
            },
            tolerance=tolerance,
        )
    return StatementCheckResult(
        check_name="source_calculation_rollup",
        status=status,
        expected_value=expected,
        actual_value=actual,
        difference=difference,
        tolerance=tolerance,
        source_fact_ids=tuple(amount.fact_id for amount in all_amounts),
        finding=finding,
    )


def assess_statement_readiness(
    *,
    source_reconciliation: SourceReconciliationResult,
    checks: Sequence[StatementCheckResult],
    annual_period_count: int,
    ltm_status: str,
    complete_presentation_history: bool = True,
) -> StatementReadinessResult:
    """Aggregate deterministic prerequisites without mutating downstream state."""

    resolved_checks = tuple(checks)
    reason_codes: list[str] = []
    blocked = False
    if source_reconciliation.status == "review_required":
        reason_codes.append("source_reconciliation_failed")
        blocked = True
    elif not source_reconciliation.coverage_attested:
        reason_codes.append("source_coverage_not_attested")
    elif source_reconciliation.status != "pass":
        reason_codes.append("source_overlap_not_ready")
    elif not source_reconciliation.decision_grade:
        reason_codes.append(
            "source_coverage_not_attested"
            if not source_reconciliation.coverage_attested
            else "source_overlap_inventory_incomplete"
        )

    check_names = {check.check_name for check in resolved_checks}
    for required in ("balance_sheet_identity", "cash_flow_to_cash_bridge"):
        if required not in check_names:
            reason_codes.append(f"{required}_missing")
    for check in resolved_checks:
        if check.status == "fail":
            reason_codes.append(f"{check.check_name}_failed")
            blocked = True
        elif check.status == "not_ready":
            reason_codes.append(f"{check.check_name}_not_ready")

    if annual_period_count < 3:
        reason_codes.append("insufficient_annual_history")
    if not complete_presentation_history:
        reason_codes.append("complete_presentation_history_missing")
    if ltm_status not in {"constructed", "source_provided"}:
        reason_codes.append("ltm_not_ready")

    unique_reasons = tuple(dict.fromkeys(reason_codes))
    status: ReadinessStatus = (
        "blocked"
        if blocked
        else "provisional"
        if unique_reasons
        else "decision_grade"
    )
    findings = tuple(
        [
            *source_reconciliation.findings,
            *[
                check.finding
                for check in resolved_checks
                if check.finding is not None
            ],
        ]
    )
    return StatementReadinessResult(
        status=status,
        decision_grade=status == "decision_grade",
        annual_period_count=int(annual_period_count),
        ltm_status=str(ltm_status),
        source_reconciliation=source_reconciliation,
        checks=resolved_checks,
        findings=findings,
        reason_codes=unique_reasons,
    )


def _period_starts_describe_one_window(
    left_start: str | None,
    right_start: str | None,
) -> bool:
    """Allow the inclusive/exclusive start convention to differ by one day.

    Providers disagree on how a duration is dated: CIQ starts a fiscal year on the
    prior year-end, XBRL on the day after. CALM FY2025 is 2024-06-01 -> 2025-05-31 in
    CIQ and 2024-06-02 -> 2025-05-31 in XBRL. Treating those as different windows made
    every duration fact fail to pair across sources.

    One day is the whole convention gap. A 53-week fiscal year differs from a 52-week
    year by seven days, so this tolerance cannot merge genuinely different windows.
    """

    if left_start == right_start:
        return True
    if not (left_start and right_start):
        return False
    try:
        left_date = date.fromisoformat(str(left_start))
        right_date = date.fromisoformat(str(right_start))
    except ValueError:
        return False
    return abs((left_date - right_date).days) <= 1


def _period_compatible(left: SourceAmount, right: SourceAmount) -> bool:
    if left.period_end != right.period_end:
        return False
    if (left.period_start or right.period_start) and not (
        _period_starts_describe_one_window(left.period_start, right.period_start)
    ):
        return False
    left_kind = (left.period_kind or "").lower()
    right_kind = (right.period_kind or "").lower()
    if (
        left_kind
        and right_kind
        and "reported" not in {left_kind, right_kind}
        and left_kind != right_kind
    ):
        return False
    return True


def _quantity_overlap(left: SourceAmount, right: SourceAmount) -> bool:
    return (
        left.ticker.upper() == right.ticker.upper()
        and left.statement == right.statement
        and left.canonical_key == right.canonical_key
        and _dimension_key(left.dimensions) == _dimension_key(right.dimensions)
        and _period_compatible(left, right)
    )


# Canonical keys a provider may legitimately present on more than one statement. Net
# income is the same quantity whether it is reported on the income statement (XBRL) or
# as the opening line of an indirect cash flow statement (CIQ).
_STATEMENT_AGNOSTIC_KEYS = frozenset({"net_income"})


# Canonical keys that are alternate presentations of one quantity. Pairing them lets
# the value tolerance arbitrate: identical figures pass, and a filer with material
# restricted-cash movement surfaces as a disagreement instead of a silent "missing".
_ALTERNATE_CANONICAL_KEYS: tuple[frozenset[str], ...] = (
    frozenset(
        {
            "net_change_in_cash_and_equivalents",
            "net_change_in_cash_including_restricted",
        }
    ),
)


def _keys_compatible(expected_key: str, amount_key: str) -> bool:
    if expected_key == amount_key:
        return True
    return any(
        expected_key in group and amount_key in group
        for group in _ALTERNATE_CANONICAL_KEYS
    )


def _statements_compatible(
    expected: ExpectedSourceQuantity,
    amount: SourceAmount,
) -> bool:
    if expected.statement == amount.statement:
        return True
    return expected.canonical_key in _STATEMENT_AGNOSTIC_KEYS


def _expected_matches_amount(
    expected: ExpectedSourceQuantity,
    amount: SourceAmount,
) -> bool:
    return (
        expected.ticker.upper() == amount.ticker.upper()
        and _statements_compatible(expected, amount)
        and _keys_compatible(expected.canonical_key, amount.canonical_key)
        and expected.period_end == amount.period_end
        and (
            expected.period_start is None
            or _period_starts_describe_one_window(
                expected.period_start,
                amount.period_start,
            )
        )
        and (
            expected.period_kind is None
            or expected.period_kind == amount.period_kind
        )
    )


def _non_comparable_window_finding(
    expected: ExpectedSourceQuantity,
    counterpart_amounts: Sequence[SourceAmount],
) -> ReconciliationFinding | None:
    """Distinguish "different fiscal window" from "no data at all".

    PM decision 2026-07-31: where providers report genuinely different fiscal windows
    (CALM FY2023 is 371 days in XBRL, a 53-week year, against 365 in CIQ) the periods
    are non-comparable. Refusing to pair them is correct; treating that refusal as a
    blocking data failure is not — the limitation is known, and blocking on it stops the
    periods that *do* pair from ever counting toward decision-grade.
    """

    same_key = [
        amount
        for amount in counterpart_amounts
        if _keys_compatible(expected.canonical_key, amount.canonical_key)
        and amount.period_end == expected.period_end
        and amount.period_start != expected.period_start
    ]
    if not same_key:
        return None
    identity = {
        "type": "non_comparable_fiscal_window",
        "ticker": expected.ticker.upper(),
        "canonical_key": expected.canonical_key,
        "period_end": expected.period_end,
        "expected_period_start": expected.period_start,
        "counterpart_period_starts": sorted(
            {str(amount.period_start) for amount in same_key}
        ),
    }
    return ReconciliationFinding(
        finding_id="reconciliation:"
        + hashlib.sha256(
            json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        ticker=expected.ticker.upper(),
        finding_type="non_comparable_fiscal_window",
        severity="warning",
        title=f"{expected.canonical_key}: fiscal windows are not comparable",
        description=(
            f"Both sources report {expected.canonical_key} ending "
            f"{expected.period_end}, but over different windows "
            f"({expected.period_start} versus "
            + ", ".join(sorted({str(a.period_start) for a in same_key}))
            + "). A 52-week and a 53-week year are different economic periods, so the "
            "figures are not compared."
        ),
        canonical_key=expected.canonical_key,
        statement=expected.statement,
        period_end=expected.period_end,
        source_fact_ids=tuple(sorted({a.fact_id for a in same_key})),
        source_locators=tuple(
            sorted({a.source_locator for a in same_key if a.source_locator})
        ),
        observed_values={
            f"{a.source}:{a.period_start}": a.base_value for a in same_key
        },
        tolerance=None,
    )


def _missing_expected_finding(
    expected: ExpectedSourceQuantity,
    *,
    xbrl_matches: Sequence[SourceAmount],
    ciq_matches: Sequence[SourceAmount],
) -> ReconciliationFinding:
    identity = {
        "ticker": expected.ticker.upper(),
        "statement": expected.statement,
        "canonical_key": expected.canonical_key,
        "period_start": expected.period_start,
        "period_end": expected.period_end,
        "period_kind": expected.period_kind,
        "xbrl_present": bool(xbrl_matches),
        "ciq_present": bool(ciq_matches),
    }
    finding_id = "reconciliation:" + hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    available = [*xbrl_matches, *ciq_matches]
    return ReconciliationFinding(
        finding_id=finding_id,
        ticker=expected.ticker.upper(),
        finding_type="missing_source_overlap",
        severity="blocking",
        title=f"{expected.canonical_key}: expected source overlap missing",
        description=(
            f"The coverage manifests require {expected.canonical_key} for "
            f"{expected.period_end}, but "
            f"{'XBRL' if not xbrl_matches else 'CIQ'} has no comparable fact."
        ),
        canonical_key=expected.canonical_key,
        statement=expected.statement,
        period_end=expected.period_end,
        source_fact_ids=tuple(
            sorted({amount.fact_id for amount in available})
        ),
        source_locators=tuple(
            sorted(
                {
                    amount.source_locator
                    for amount in available
                    if amount.source_locator
                }
            )
        ),
        observed_values={
            "xbrl": "present" if xbrl_matches else "missing",
            "ciq": "present" if ciq_matches else "missing",
        },
        tolerance=None,
        metadata={"expected_quantity": identity},
    )


def _amount_sort_key(amount: SourceAmount) -> tuple[Any, ...]:
    return (
        amount.ticker.upper(),
        amount.statement,
        amount.canonical_key,
        amount.period_end,
        amount.period_start or "",
        _dimension_key(amount.dimensions),
        amount.vintage or "",
        amount.fact_id,
    )


def _finding_id(
    finding_type: str,
    left: SourceAmount,
    right: SourceAmount,
) -> str:
    payload = json.dumps(
        {
            "finding_type": finding_type,
            "ticker": left.ticker.upper(),
            "canonical_key": left.canonical_key,
            "period_end": left.period_end,
            "source_fact_ids": sorted([left.fact_id, right.fact_id]),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"source-reconciliation:{hashlib.sha256(payload.encode()).hexdigest()[:24]}"


def _source_refs(
    left: SourceAmount,
    right: SourceAmount,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    fact_ids = (left.fact_id, right.fact_id)
    locators = tuple(
        locator
        for locator in (left.source_locator, right.source_locator)
        if locator
    )
    return fact_ids, locators


def _compare_pair(
    xbrl: SourceAmount,
    ciq: SourceAmount,
) -> tuple[SourceComparison, ReconciliationFinding | None]:
    fact_ids, locators = _source_refs(xbrl, ciq)

    def incompatible(
        *,
        status: ComparisonStatus,
        title: str,
        description: str,
        observed_values: Mapping[str, float | str | None],
        metadata: Mapping[str, Any] | None = None,
    ) -> tuple[SourceComparison, ReconciliationFinding]:
        finding = ReconciliationFinding(
            finding_id=_finding_id(status, xbrl, ciq),
            ticker=xbrl.ticker.upper(),
            finding_type=status,
            severity="blocking",
            title=title,
            description=description,
            canonical_key=xbrl.canonical_key,
            statement=xbrl.statement,
            period_end=xbrl.period_end,
            source_fact_ids=fact_ids,
            source_locators=locators,
            observed_values=observed_values,
            tolerance=None,
            metadata=dict(metadata or {}),
        )
        comparison = SourceComparison(
            ticker=xbrl.ticker.upper(),
            statement=xbrl.statement,
            canonical_key=xbrl.canonical_key,
            period_end=xbrl.period_end,
            xbrl_fact_id=xbrl.fact_id,
            ciq_fact_id=ciq.fact_id,
            xbrl_base_value=xbrl.normalized_value,
            ciq_base_value=ciq.normalized_value,
            difference=None,
            tolerance=None,
            status=status,
        )
        return comparison, finding

    if (
        {xbrl.unit_kind, ciq.unit_kind}
        == {"unknown", "currency_scalar"}
        and (not xbrl.currency or not ciq.currency)
    ):
        return incompatible(
            status="currency_mismatch",
            title=f"{xbrl.canonical_key}: source currency metadata missing",
            description=(
                f"XBRL reports {xbrl.currency or xbrl.unit}; CIQ reports "
                f"{ciq.currency or ciq.unit} for {xbrl.period_end}."
            ),
            observed_values={
                xbrl.source: xbrl.currency or xbrl.unit,
                ciq.source: ciq.currency or ciq.unit,
            },
        )

    if xbrl.unit_kind != ciq.unit_kind:
        return incompatible(
            status="unit_mismatch",
            title=f"{xbrl.canonical_key}: source units do not match",
            description=(
                f"XBRL reports {xbrl.unit} ({xbrl.unit_kind}); CIQ reports "
                f"{ciq.unit} ({ciq.unit_kind}) "
                f"for {xbrl.period_end}."
            ),
            observed_values={xbrl.source: xbrl.unit, ciq.source: ciq.unit},
        )

    if (
        xbrl.unit_kind in {"currency_scalar", "currency_per_share"}
        and (
            not xbrl.unit_currency
            or not ciq.unit_currency
            or xbrl.unit_currency != ciq.unit_currency
            or (
                (xbrl.currency is not None or ciq.currency is not None)
                and xbrl.currency != ciq.currency
            )
        )
    ):
        return incompatible(
            status="currency_mismatch",
            title=f"{xbrl.canonical_key}: source currencies do not match",
            description=(
                f"XBRL reports {xbrl.currency or xbrl.unit_currency}; CIQ "
                f"reports {ciq.currency or ciq.unit_currency} for "
                f"{xbrl.period_end}. No FX conversion was assumed."
            ),
            observed_values={
                xbrl.source: xbrl.currency or xbrl.unit_currency,
                ciq.source: ciq.currency or ciq.unit_currency,
            },
        )

    if (
        xbrl.economic_sign != 1
        or ciq.economic_sign != 1
    ) and (
        not xbrl.sign_rule
        or not ciq.sign_rule
        or xbrl.sign_rule != ciq.sign_rule
    ):
        return incompatible(
            status="sign_rule_mismatch",
            title=f"{xbrl.canonical_key}: economic sign rules do not match",
            description=(
                f"XBRL uses {xbrl.sign_rule or 'no sign rule'}; CIQ uses "
                f"{ciq.sign_rule or 'no sign rule'} for {xbrl.period_end}."
            ),
            observed_values={
                xbrl.source: xbrl.sign_rule,
                ciq.source: ciq.sign_rule,
            },
        )

    usd_per_currency_unit = 1.0
    if xbrl.monetary and xbrl.unit_currency != "USD":
        fx_fields = (
            xbrl.usd_per_currency_unit,
            ciq.usd_per_currency_unit,
            xbrl.fx_date,
            ciq.fx_date,
            xbrl.fx_source,
            ciq.fx_source,
            xbrl.fx_fingerprint,
            ciq.fx_fingerprint,
        )
        if any(value in {None, ""} for value in fx_fields):
            return incompatible(
                status="fx_missing",
                title=f"{xbrl.canonical_key}: USD tolerance FX context missing",
                description=(
                    f"The PM-set USD 1m floor cannot be applied to "
                    f"{xbrl.unit_currency} for {xbrl.period_end} without a "
                    "dated, fingerprinted FX input."
                ),
                observed_values={
                    xbrl.source: xbrl.usd_per_currency_unit,
                    ciq.source: ciq.usd_per_currency_unit,
                },
            )
        if (
            not math.isclose(
                float(xbrl.usd_per_currency_unit),
                float(ciq.usd_per_currency_unit),
                rel_tol=1e-12,
                abs_tol=0.0,
            )
            or xbrl.fx_date != ciq.fx_date
            or xbrl.fx_source != ciq.fx_source
            or xbrl.fx_fingerprint != ciq.fx_fingerprint
        ):
            return incompatible(
                status="fx_mismatch",
                title=f"{xbrl.canonical_key}: FX contexts do not match",
                description=(
                    f"XBRL and CIQ are not bound to the same FX input for "
                    f"{xbrl.period_end}."
                ),
                observed_values={
                    xbrl.source: xbrl.fx_fingerprint,
                    ciq.source: ciq.fx_fingerprint,
                },
            )
        usd_per_currency_unit = float(xbrl.usd_per_currency_unit)

    difference = abs(xbrl.normalized_value - ciq.normalized_value)
    tolerance = reconciliation_tolerance(
        xbrl.normalized_value,
        ciq.normalized_value,
        monetary=xbrl.monetary or ciq.monetary,
        usd_per_currency_unit=usd_per_currency_unit,
    )
    status = (
        "matched"
        if _within_tolerance(difference, tolerance)
        else "material_disagreement"
    )
    comparison = SourceComparison(
        ticker=xbrl.ticker.upper(),
        statement=xbrl.statement,
        canonical_key=xbrl.canonical_key,
        period_end=xbrl.period_end,
        xbrl_fact_id=xbrl.fact_id,
        ciq_fact_id=ciq.fact_id,
        xbrl_base_value=xbrl.normalized_value,
        ciq_base_value=ciq.normalized_value,
        difference=difference,
        tolerance=tolerance,
        status=status,
    )
    if status == "matched":
        return comparison, None
    finding = ReconciliationFinding(
        finding_id=_finding_id(status, xbrl, ciq),
        ticker=xbrl.ticker.upper(),
        finding_type=status,
        severity=_disagreement_severity(
            xbrl.normalized_value,
            ciq.normalized_value,
        ),
        title=f"{xbrl.canonical_key}: CIQ and XBRL disagree",
        description=(
            f"XBRL reports {xbrl.normalized_value:g}; CIQ reports "
            f"{ciq.normalized_value:g} for {xbrl.period_end}. The "
            f"{difference:g} difference exceeds the {tolerance:g} tolerance."
        ),
        canonical_key=xbrl.canonical_key,
        statement=xbrl.statement,
        period_end=xbrl.period_end,
        source_fact_ids=fact_ids,
        source_locators=locators,
        observed_values={
            xbrl.source: xbrl.normalized_value,
            ciq.source: ciq.normalized_value,
        },
        tolerance=tolerance,
        metadata={
            "reported_values": {
                xbrl.source: xbrl.base_value,
                ciq.source: ciq.base_value,
            },
            "sign_rule": xbrl.sign_rule or ciq.sign_rule,
            "fx": (
                {
                    "date": xbrl.fx_date,
                    "source": xbrl.fx_source,
                    "fingerprint": xbrl.fx_fingerprint,
                    "usd_per_currency_unit": usd_per_currency_unit,
                }
                if xbrl.monetary and xbrl.unit_currency != "USD"
                else None
            ),
        },
    )
    return comparison, finding


def reconcile_statement_sources(
    xbrl_amounts: Sequence[SourceAmount],
    ciq_amounts: Sequence[SourceAmount],
    *,
    expected_quantities: Sequence[ExpectedSourceQuantity] | None = None,
) -> SourceReconciliationResult:
    """Compare every consolidated overlapping quantity at the same period."""

    comparisons: list[SourceComparison] = []
    findings: list[ReconciliationFinding] = []
    for xbrl in sorted(xbrl_amounts, key=_amount_sort_key):
        for ciq in sorted(ciq_amounts, key=_amount_sort_key):
            if not _quantity_overlap(xbrl, ciq):
                continue
            comparison, finding = _compare_pair(xbrl, ciq)
            comparisons.append(comparison)
            if finding is not None:
                findings.append(finding)
    expected = tuple(expected_quantities or ())
    missing_expected_count = 0
    if expected_quantities is not None:
        for quantity in expected:
            xbrl_matches = tuple(
                amount
                for amount in xbrl_amounts
                if _expected_matches_amount(quantity, amount)
            )
            ciq_matches = tuple(
                amount
                for amount in ciq_amounts
                if _expected_matches_amount(quantity, amount)
            )
            if xbrl_matches and ciq_matches:
                continue
            counterpart = ciq_amounts if not ciq_matches else xbrl_amounts
            window_finding = _non_comparable_window_finding(quantity, counterpart)
            if window_finding is not None:
                findings.append(window_finding)
                continue
            missing_expected_count += 1
            findings.append(
                _missing_expected_finding(
                    quantity,
                    xbrl_matches=xbrl_matches,
                    ciq_matches=ciq_matches,
                )
            )
    if not comparisons and not findings:
        return SourceReconciliationResult(
            status="not_comparable",
            decision_grade=False,
            comparisons=(),
            findings=(),
            overlap_count=0,
            coverage_attested=expected_quantities is not None,
            expected_quantity_count=len(expected),
            missing_expected_count=missing_expected_count,
        )
    status: ReconciliationStatus = _reconciliation_status(findings)
    decision_grade = bool(
        expected_quantities is not None
        and expected
        and not findings
        and comparisons
    )
    return SourceReconciliationResult(
        status=status,
        decision_grade=decision_grade,
        comparisons=tuple(comparisons),
        findings=tuple(findings),
        overlap_count=len(comparisons),
        coverage_attested=expected_quantities is not None,
        expected_quantity_count=len(expected),
        missing_expected_count=missing_expected_count,
    )


# PM decision 2026-07-31: for the DCF path the filing is authoritative, so a figure
# disagreement resolves to the XBRL value and the gap is recorded for PM review rather
# than halting the ticker. Structural failures — one source having no such fact, or an
# incomparable unit, currency, or sign rule — remain blocking.
#
# Scope: statement reconciliation only. Comparables read `ciq_comps_snapshot` through a
# separate path and keep Capital IQ's cross-company consistency untouched.
MATERIAL_DISAGREEMENT_SEVERITY = "warning"


def _disagreement_severity(
    xbrl_value: float,
    ciq_value: float,
) -> str:
    """Separate a classification difference from a structural source failure.

    A few percent between the filing and Capital IQ is a classification difference —
    attributable-to-parent versus including noncontrolling interests, or a line grouped
    differently. The filing wins and the gap is logged.

    Two patterns are not classification differences and still block, because each is a
    parse or convention failure that has shipped a wrong valuation before:

    * one side reports zero while the other reports a real amount — this is the D&A=0
      parse bug that understated base intrinsic value by roughly 18%;
    * the two values carry opposite signs — a sign-convention error, not a difference of
      opinion about what the number contains.
    """

    if (xbrl_value == 0.0) != (ciq_value == 0.0):
        return "blocking"
    if xbrl_value * ciq_value < 0.0:
        return "blocking"
    return MATERIAL_DISAGREEMENT_SEVERITY


def _reconciliation_status(
    findings: Sequence[ReconciliationFinding],
) -> ReconciliationStatus:
    """Only blocking-severity findings stop a ticker.

    Severity was recorded but never read, so a warning — a known, expected limitation
    such as a non-comparable fiscal window — blocked as hard as a real disagreement.
    Warnings stay visible and still hold the result short of decision-grade.
    """

    return (
        "review_required"
        if any(str(getattr(f, "severity", "")) == "blocking" for f in findings)
        else "pass"
    )


def reconcile_persisted_statement_facts(
    facts: Sequence[Mapping[str, Any]],
    *,
    expected_quantities: Sequence[ExpectedSourceQuantity] | None = None,
) -> SourceReconciliationResult:
    """Adapt and reconcile the current immutable vintage from each source."""

    xbrl_amounts: list[SourceAmount] = []
    ciq_amounts: list[SourceAmount] = []
    for fact in _current_reconciliation_facts(facts):
        if fact.get("numeric_value") is None:
            continue
        source = str(fact.get("source") or "").lower()
        if source.startswith("sec_xbrl"):
            xbrl_amounts.append(source_amount_from_statement_fact(fact))
        elif source.startswith("ciq"):
            ciq_amounts.append(source_amount_from_statement_fact(fact))
    return reconcile_statement_sources(
        xbrl_amounts,
        ciq_amounts,
        expected_quantities=expected_quantities,
    )


def _fact_quantity_identity(
    fact: Mapping[str, Any],
) -> tuple[Any, ...]:
    dimensions = fact.get("dimensions") or {}
    hierarchy = fact.get("hierarchy") or {}
    context = fact.get("context") or {}
    unit_kind, unit_currency = _unit_semantics(
        str(fact.get("unit")) if fact.get("unit") is not None else None,
        str(fact.get("currency")) if fact.get("currency") else None,
    )
    return (
        str(fact.get("ticker") or "").upper(),
        str(fact.get("statement") or ""),
        str(
            fact.get("statement_role")
            or hierarchy.get("statement_role")
            or ""
        ),
        canonical_statement_key(
            str(fact.get("concept") or fact.get("fact_name") or ""),
            str(fact.get("label") or ""),
        ),
        str(fact.get("period_start") or ""),
        str(fact.get("period_end") or fact.get("period") or ""),
        str(fact.get("period_kind") or ""),
        unit_kind,
        unit_currency or "",
        str(
            fact.get("presentation_path")
            or hierarchy.get("presentation_path")
            or ""
        ),
        str(fact.get("context_ref") or context.get("context_ref") or ""),
        _dimension_key(
            {
                str(key): str(value)
                for key, value in dict(dimensions).items()
            }
        ),
    )


def _xbrl_source_priority(source: str) -> int:
    if source.startswith("sec_xbrl_filing_presentation"):
        return 3
    if source.startswith("sec_xbrl_derived_ltm"):
        return 2
    return 1


def _current_reconciliation_facts(
    facts: Sequence[Mapping[str, Any]],
) -> tuple[Mapping[str, Any], ...]:
    """Select current source vintages without deleting the immutable history."""

    numeric = [
        fact
        for fact in facts
        if fact.get("numeric_value") is not None
    ]
    ciq_run_by_ticker: dict[str, int] = {}
    for fact in numeric:
        source = str(fact.get("source") or "").lower()
        run_id = fact.get("source_run_id")
        if not source.startswith("ciq") or run_id is None:
            continue
        ticker = str(fact.get("ticker") or "").upper()
        ciq_run_by_ticker[ticker] = max(
            ciq_run_by_ticker.get(ticker, int(run_id)),
            int(run_id),
        )

    selected_xbrl: dict[
        tuple[Any, ...],
        tuple[tuple[Any, ...], Mapping[str, Any]],
    ] = {}
    selected_other: list[Mapping[str, Any]] = []
    for fact in numeric:
        source = str(fact.get("source") or "").lower()
        if source.startswith("sec_xbrl"):
            identity = _fact_quantity_identity(fact)
            vintage = (
                _xbrl_source_priority(source),
                str(fact.get("filing_date") or ""),
                str(fact.get("accession") or ""),
                int(fact.get("source_run_id") or 0),
                str(fact.get("ingestion_fingerprint") or ""),
                str(fact.get("fact_id") or ""),
            )
            previous = selected_xbrl.get(identity)
            if previous is None or vintage > previous[0]:
                selected_xbrl[identity] = (vintage, fact)
            continue
        if source.startswith("ciq"):
            ticker = str(fact.get("ticker") or "").upper()
            latest_run = ciq_run_by_ticker.get(ticker)
            run_id = fact.get("source_run_id")
            if latest_run is not None and (
                run_id is None or int(run_id) != latest_run
            ):
                continue
        selected_other.append(fact)

    return tuple(
        [
            *(
                item[1]
                for _, item in sorted(
                    selected_xbrl.items(),
                    key=lambda pair: pair[0],
                )
            ),
            *selected_other,
        ]
    )


__all__ = [
    "ABSOLUTE_CURRENCY_TOLERANCE",
    "ExpectedSourceQuantity",
    "RELATIVE_TOLERANCE",
    "ReconciliationFinding",
    "SourceAmount",
    "SourceComparison",
    "SourceReconciliationResult",
    "StatementCheckResult",
    "StatementReadinessResult",
    "assess_statement_readiness",
    "canonical_statement_key",
    "reconcile_persisted_statement_facts",
    "reconcile_statement_sources",
    "reconciliation_tolerance",
    "source_amount_from_statement_fact",
    "validate_balance_sheet_identity",
    "validate_calculation_rollup",
    "validate_cash_bridge",
]
