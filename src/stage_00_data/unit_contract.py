"""Canonical unit boundary between deterministic ingestion and computation.

Source-specific values may carry a scale, but values returned from this module
are always in their canonical computation unit with an effective scale of one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math


class UnitContractError(ValueError):
    """Raised when a source value cannot safely cross the unit boundary."""


class CanonicalUnit(str, Enum):
    """Finite semantic units accepted by deterministic computation."""

    USD = "USD"
    SHARES = "shares"
    DECIMAL = "decimal"
    USD_PER_SHARE = "USD/share"
    MULTIPLE = "multiple"
    DAYS = "days"
    MONTHS = "months"


@dataclass(frozen=True, slots=True)
class NormalizedValue:
    """A canonical value plus immutable raw-source provenance."""

    value: float
    unit: CanonicalUnit
    raw_value: float
    raw_unit: str
    raw_scale: float
    source_ref: str | None = None
    canonical_scale: float = field(default=1.0, init=False)


_VARIABLE_SCALE_UNITS: dict[CanonicalUnit, frozenset[str]] = {
    CanonicalUnit.USD: frozenset({"usd"}),
    CanonicalUnit.SHARES: frozenset({"share", "shares"}),
}

_FIXED_SCALE_UNITS: dict[CanonicalUnit, dict[str, float]] = {
    CanonicalUnit.DECIMAL: {
        "%": 0.01,
        "percent": 0.01,
        "percentage point": 0.01,
        "percentage points": 0.01,
        "decimal": 1.0,
    },
    CanonicalUnit.USD_PER_SHARE: {
        "usd/share": 1.0,
        "usd per share": 1.0,
    },
    CanonicalUnit.MULTIPLE: {"multiple": 1.0, "x": 1.0},
    CanonicalUnit.DAYS: {"day": 1.0, "days": 1.0},
    CanonicalUnit.MONTHS: {"month": 1.0, "months": 1.0},
}


def normalize_source_value(
    *,
    value: float,
    raw_unit: str | None,
    raw_scale: float,
    canonical_unit: CanonicalUnit,
    source_ref: str | None = None,
) -> NormalizedValue:
    """Normalize one declared source value into a canonical computation unit.

    Money and share counts may use any finite positive source scale. Other
    semantic units have a fixed scale so percentage-point/decimal mistakes and
    accidental display scaling fail closed.
    """

    raw_value = float(value)
    scale = float(raw_scale)
    if not math.isfinite(raw_value):
        raise UnitContractError("unit_contract.value_not_finite")
    if not math.isfinite(scale) or scale <= 0:
        raise UnitContractError("unit_contract.scale_invalid")
    if raw_unit is None or not str(raw_unit).strip():
        raise UnitContractError("unit_contract.raw_unit_missing")
    if not isinstance(canonical_unit, CanonicalUnit):
        raise UnitContractError("unit_contract.canonical_unit_invalid")

    declared_unit = str(raw_unit).strip()
    normalized_unit = declared_unit.casefold()
    variable_units = _VARIABLE_SCALE_UNITS.get(canonical_unit)
    if variable_units is not None:
        if normalized_unit not in variable_units:
            raise UnitContractError("unit_contract.unit_mismatch")
    else:
        fixed_scales = _FIXED_SCALE_UNITS[canonical_unit]
        expected_scale = fixed_scales.get(normalized_unit)
        if expected_scale is None:
            raise UnitContractError("unit_contract.unit_mismatch")
        if not math.isclose(scale, expected_scale, rel_tol=0.0, abs_tol=1e-12):
            raise UnitContractError("unit_contract.scale_mismatch")

    canonical_value = raw_value * scale
    if not math.isfinite(canonical_value):
        raise UnitContractError("unit_contract.normalized_value_not_finite")

    return NormalizedValue(
        value=canonical_value,
        unit=canonical_unit,
        raw_value=raw_value,
        raw_unit=declared_unit,
        raw_scale=scale,
        source_ref=source_ref,
    )
