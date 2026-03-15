from __future__ import annotations

from src.stage_04_pipeline.presentation_formatting import (
    abbreviate_number,
    format_metric_value,
    format_negative,
    format_percent,
    style_dataframe_rows,
)


def test_abbreviate_number_uses_k_m_b_suffixes():
    assert abbreviate_number(10_000) == "10.0K"
    assert abbreviate_number(1_250_000) == "1.3M"
    assert abbreviate_number(3_400_000_000) == "3.4B"


def test_format_percent_supports_decimal_and_whole_inputs():
    assert format_percent(0.10) == "10.0%"
    assert format_percent(10.0, input_mode="whole") == "10.0%"
    assert format_percent(-0.125) == "(12.5%)"


def test_format_negative_uses_parentheses():
    assert format_negative(-12.5) == "(12.5)"
    assert format_negative(12.5) == "12.5"
    assert format_negative(None) == "-"


def test_format_metric_value_handles_common_dashboard_units():
    assert format_metric_value(0.153, kind="pct") == "15.3%"
    assert format_metric_value(12.345, kind="x") == "12.3x"
    assert format_metric_value(12.345, kind="days") == "12.3d"
    assert format_metric_value(1_250_000, kind="usd") == "$1.3M"
    assert format_metric_value(-1_250_000, kind="usd") == "($1.3M)"
    assert format_metric_value(123.456, kind="price") == "$123.46"


def test_style_dataframe_rows_applies_schema_driven_formatting():
    rows = [
        {
            "name": "IBM",
            "margin": 0.125,
            "multiple": 13.21,
            "value": -1_250_000,
        }
    ]

    styled = style_dataframe_rows(rows, {"margin": "pct", "multiple": "x", "value": "usd"})

    assert styled == [
        {
            "name": "IBM",
            "margin": "12.5%",
            "multiple": "13.2x",
            "value": "($1.3M)",
        }
    ]
