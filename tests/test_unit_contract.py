from __future__ import annotations

import math

import pytest

from src.stage_00_data.unit_contract import (
    CanonicalUnit,
    UnitContractError,
    normalize_source_value,
)


def test_normalizes_msft_money_and_shares_to_absolute_values() -> None:
    revenue = normalize_source_value(
        value=331_839.0,
        raw_unit="USD",
        raw_scale=1_000_000.0,
        canonical_unit=CanonicalUnit.USD,
        source_ref="ciq:run-20:revenue",
    )
    shares = normalize_source_value(
        value=7_453.0,
        raw_unit="shares",
        raw_scale=1_000_000.0,
        canonical_unit=CanonicalUnit.SHARES,
        source_ref="ciq:run-20:diluted-shares",
    )

    assert revenue.value == 331_839_000_000.0
    assert revenue.canonical_scale == 1.0
    assert revenue.raw_value == 331_839.0
    assert revenue.raw_scale == 1_000_000.0
    assert revenue.source_ref == "ciq:run-20:revenue"
    assert shares.value == 7_453_000_000.0
    assert shares.unit is CanonicalUnit.SHARES


def test_different_raw_scales_normalize_to_the_same_value() -> None:
    absolute = normalize_source_value(
        value=331_839_000_000.0,
        raw_unit="USD",
        raw_scale=1.0,
        canonical_unit=CanonicalUnit.USD,
    )
    millions = normalize_source_value(
        value=331_839.0,
        raw_unit="USD",
        raw_scale=1_000_000.0,
        canonical_unit=CanonicalUnit.USD,
    )

    assert absolute.value == millions.value


@pytest.mark.parametrize(
    ("raw_unit", "raw_scale", "raw_value", "canonical_unit", "expected"),
    [
        ("%", 0.01, 67.944, CanonicalUnit.DECIMAL, 0.67944),
        ("decimal", 1.0, 0.67944, CanonicalUnit.DECIMAL, 0.67944),
        ("USD/share", 1.0, 494.42, CanonicalUnit.USD_PER_SHARE, 494.42),
        ("multiple", 1.0, 17.83753, CanonicalUnit.MULTIPLE, 17.83753),
        ("days", 1.0, 45.0, CanonicalUnit.DAYS, 45.0),
        ("months", 1.0, 12.0, CanonicalUnit.MONTHS, 12.0),
    ],
)
def test_normalizes_supported_semantic_units(
    raw_unit: str,
    raw_scale: float,
    raw_value: float,
    canonical_unit: CanonicalUnit,
    expected: float,
) -> None:
    normalized = normalize_source_value(
        value=raw_value,
        raw_unit=raw_unit,
        raw_scale=raw_scale,
        canonical_unit=canonical_unit,
    )

    assert normalized.value == pytest.approx(expected)
    assert normalized.unit is canonical_unit
    assert normalized.canonical_scale == 1.0


@pytest.mark.parametrize(
    ("value", "raw_scale"),
    [
        (math.nan, 1.0),
        (math.inf, 1.0),
        (1.0, math.nan),
        (1.0, math.inf),
        (1.0, 0.0),
        (1.0, -1.0),
    ],
)
def test_rejects_non_finite_values_and_invalid_scales(
    value: float,
    raw_scale: float,
) -> None:
    with pytest.raises(UnitContractError):
        normalize_source_value(
            value=value,
            raw_unit="USD",
            raw_scale=raw_scale,
            canonical_unit=CanonicalUnit.USD,
        )


@pytest.mark.parametrize(
    ("raw_unit", "raw_scale", "canonical_unit"),
    [
        (None, 1.0, CanonicalUnit.USD),
        ("%", 0.01, CanonicalUnit.USD),
        ("USD", 1.0, CanonicalUnit.SHARES),
        ("%", 1.0, CanonicalUnit.DECIMAL),
        ("decimal", 0.01, CanonicalUnit.DECIMAL),
        ("USD/share", 1_000_000.0, CanonicalUnit.USD_PER_SHARE),
        ("multiple", 100.0, CanonicalUnit.MULTIPLE),
    ],
)
def test_rejects_missing_or_incompatible_unit_declarations(
    raw_unit: str | None,
    raw_scale: float,
    canonical_unit: CanonicalUnit,
) -> None:
    with pytest.raises(UnitContractError):
        normalize_source_value(
            value=1.0,
            raw_unit=raw_unit,
            raw_scale=raw_scale,
            canonical_unit=canonical_unit,
        )
