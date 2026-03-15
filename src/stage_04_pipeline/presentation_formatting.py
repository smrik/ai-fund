from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any


_DEFAULT_DECIMALS: dict[str, int] = {
    "pct": 1,
    "percent": 1,
    "price": 2,
    "usd": 1,
    "days": 1,
    "x": 1,
    "multiple": 1,
    "count": 0,
    "raw": 1,
}


def _wrap_negative(text: str, value: float | int | None) -> str:
    if value is None:
        return "-"
    return f"({text})" if float(value) < 0 else text


def _format_decimal(value: float | int, decimals: int) -> str:
    return f"{abs(float(value)):,.{decimals}f}"


def _round_half_up(value: float | int, decimals: int) -> Decimal:
    quant = "1" if decimals <= 0 else "1." + ("0" * decimals)
    return Decimal(str(float(value))).quantize(Decimal(quant), rounding=ROUND_HALF_UP)


def abbreviate_number(value: float | int | None, *, decimals: int = 1) -> str:
    if value is None:
        return "-"

    numeric = float(value)
    magnitude = abs(numeric)
    thresholds = (
        (1_000_000_000_000, "T"),
        (1_000_000_000, "B"),
        (1_000_000, "M"),
        (1_000, "K"),
    )
    for threshold, suffix in thresholds:
        if magnitude >= threshold:
            scaled = _round_half_up(magnitude / threshold, decimals)
            body = f"{scaled:,.{decimals}f}{suffix}"
            return f"-{body}" if numeric < 0 else body
    body = f"{_round_half_up(magnitude, decimals):,.{decimals}f}"
    return f"-{body}" if numeric < 0 else body


def format_negative(value: float | int | None, *, style: str = "parentheses") -> str:
    if value is None:
        return "-"
    body = _format_decimal(value, 1)
    if float(value) >= 0 or style != "parentheses":
        return body if float(value) >= 0 else f"-{body}"
    return f"({body})"


def format_percent(value: float | None, *, input_mode: str = "decimal", decimals: int = 1) -> str:
    if value is None:
        return "-"
    numeric = float(value)
    scaled = numeric if input_mode == "whole" else numeric * 100.0
    body = f"{abs(scaled):,.{decimals}f}%"
    return _wrap_negative(body, scaled)


def format_metric_value(value: float | int | None, *, kind: str, decimals: int | None = None) -> str:
    if value is None:
        return "-"

    numeric = float(value)
    digits = _DEFAULT_DECIMALS.get(kind, 1) if decimals is None else decimals

    if kind in {"pct", "percent"}:
        return format_percent(numeric, input_mode="decimal", decimals=digits)
    if kind in {"x", "multiple"}:
        body = f"{abs(numeric):,.{digits}f}x"
        return _wrap_negative(body, numeric)
    if kind == "days":
        body = f"{abs(numeric):,.{digits}f}d"
        return _wrap_negative(body, numeric)
    if kind == "usd":
        body = f"${abbreviate_number(abs(numeric), decimals=digits)}"
        return _wrap_negative(body, numeric)
    if kind == "price":
        body = f"${abs(numeric):,.{digits}f}"
        return _wrap_negative(body, numeric)
    if kind == "count":
        body = f"{abs(numeric):,.0f}"
        return _wrap_negative(body, numeric)
    body = f"{abs(numeric):,.{digits}f}"
    return _wrap_negative(body, numeric)


def format_table_value(value: object, *, kind: str | None = None) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (float, int)):
        return format_metric_value(value, kind=kind or "raw")
    return str(value)


def style_dataframe_rows(rows: list[dict], schema: dict[str, str]) -> list[dict]:
    styled: list[dict] = []
    for row in rows:
        styled_row: dict[str, Any] = {}
        for key, value in row.items():
            styled_row[key] = format_table_value(value, kind=schema.get(key))
        styled.append(styled_row)
    return styled
