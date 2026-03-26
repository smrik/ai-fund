from __future__ import annotations

import re
from typing import Any, Iterable, Mapping

import streamlit as st

from src.stage_04_pipeline.presentation_formatting import (
    format_metric_value,
    style_dataframe_rows,
)

NOTEBOOK_TYPES = [
    "thesis",
    "risk",
    "catalyst",
    "question",
    "decision",
    "review",
    "evidence",
    "general",
]


def to_display_value(value: float | None, unit: str) -> float:
    if value is None:
        return 0.0
    if unit == "pct":
        return float(value) * 100.0
    if unit == "usd":
        return float(value) / 1_000_000.0
    return float(value)


def from_display_value(value: float, unit: str) -> float:
    if unit == "pct":
        return float(value) / 100.0
    if unit == "usd":
        return float(value) * 1_000_000.0
    return float(value)


def format_unit_value(value: float | None, unit: str) -> str:
    if unit == "pct":
        return format_metric_value(value, kind="percent")
    if unit == "usd":
        if value is None:
            return "—"
        return f"${value / 1_000_000:,.1f}m"
    if unit == "x":
        return format_metric_value(value, kind="x")
    if unit == "days":
        return format_metric_value(value, kind="raw")
    return format_metric_value(value, kind="raw")


def input_step(unit: str) -> float:
    return {
        "pct": 0.25,
        "usd": 1.0,
        "x": 0.25,
        "days": 1.0,
    }.get(unit, 0.1)


def rec_unit(field: str) -> str:
    if field in {
        "revenue_growth_near",
        "revenue_growth_mid",
        "ebit_margin_start",
        "ebit_margin_target",
        "tax_rate_start",
        "tax_rate_target",
        "capex_pct_start",
        "capex_pct_target",
        "da_pct_start",
        "da_pct_target",
    }:
        return "pct"
    if field in {
        "net_debt",
        "non_operating_assets",
        "lease_liabilities",
        "minority_interest",
        "preferred_equity",
        "pension_deficit",
    }:
        return "usd"
    if field in {"exit_multiple"}:
        return "x"
    return "raw"


def fix_text(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", str(text)).strip()


def fmt_sens_table(rows: list[dict]) -> list[dict]:
    formatted: list[dict] = []
    for row in rows or []:
        formatted.append(
            {
                key: (f"${value:,.2f}" if isinstance(value, (int, float)) and key != "wacc_pct" else value)
                for key, value in row.items()
            }
        )
    return formatted


def metric_label(metric_key: str) -> str:
    return str(metric_key).replace("_", " ").upper()


def get_state(session_state: Any | None = None) -> Any:
    return session_state if session_state is not None else st.session_state


def get_cached_view(session_state: Any, key: str, builder, *args, **kwargs):
    state = get_state(session_state)
    current = state.get(key)
    if current is None:
        try:
            current = builder(*args, **kwargs)
        except Exception as exc:
            return {"available": False, "error": str(exc)}
        state[key] = current
    return current


def set_state(session_state: Any, key: str, value: Any) -> None:
    state = get_state(session_state)
    state[key] = value


def set_note_context(session_state: Any, *, page: str, subpage: str, item: str | None = None) -> None:
    state = get_state(session_state)
    state["note_context"] = {
        "page": page,
        "subpage": subpage,
        "item": item or subpage,
    }


def text_to_lines(value: str | None) -> list[str]:
    return [line.strip() for line in (value or "").splitlines() if line.strip()]


def render_change_list(title: str, items: Iterable[str]) -> None:
    st.markdown(f"**{title}**")
    items = list(items)
    if not items:
        st.caption("None.")
        return
    for item in items:
        st.write(f"- {item}")


def render_compact_list(title: str, items: Iterable[str], *, max_items: int = 3) -> None:
    st.markdown(f"**{title}**")
    items = list(items)
    if not items:
        st.caption("None.")
        return
    for item in items[:max_items]:
        st.write(f"- {item}")
    remaining = len(items) - max_items
    if remaining > 0:
        st.caption(f"+ {remaining} more")


def render_kv_card(title: str, lines: Iterable[str]) -> None:
    st.markdown(f"#### {title}")
    lines = list(lines)
    if not lines:
        st.caption("None.")
        return
    for line in lines:
        st.write(line)


def status_breakdown(rows: list[dict], field: str) -> str:
    counts: dict[str, int] = {}
    for row in rows:
        key = str(row.get(field) or "unknown").lower()
        counts[key] = counts.get(key, 0) + 1
    if not counts:
        return "None."
    return " · ".join(f"{label}: {count}" for label, count in sorted(counts.items()))


def render_clean_table(
    rows: list[dict],
    schema: Mapping[str, str] | None = None,
    *,
    column_order: list[str] | None = None,
    height: int | None = None,
) -> None:
    if not rows:
        st.info("No rows to display.")
        return
    payload = style_dataframe_rows(rows, dict(schema or {})) if schema else rows
    if column_order:
        payload = [{key: row.get(key) for key in column_order} for row in payload]
    st.dataframe(payload, width="stretch", hide_index=True, height=height)


def render_drilldown_button(
    label: str,
    *,
    target_tab: str,
    session_state: Any,
    target_key: str | None = None,
    target_value: str | None = None,
    key: str,
) -> None:
    if st.button(label, key=key):
        set_state(session_state, "selected_primary_tab", target_tab)
        if target_key and target_value:
            set_state(session_state, target_key, target_value)
        st.rerun()


def normalize_football_field_payload(football_field: dict | None) -> dict:
    football_field = dict(football_field or {})
    if football_field.get("ranges"):
        return football_field
    markers = football_field.get("markers") or []
    ranges: list[dict] = []
    marker_lookup: dict[str, dict] = {}
    for marker in markers:
        if marker.get("type") == "range_point" and marker.get("metric") and marker.get("band"):
            marker_lookup.setdefault(str(marker["metric"]), {})[str(marker["band"])] = marker
    for metric, band_map in marker_lookup.items():
        label = (band_map.get("base") or band_map.get("bear") or band_map.get("bull") or {}).get("label") or metric
        ranges.append(
            {
                "metric": metric,
                "label": label.rsplit(" ", 1)[0] if " " in label else label,
                "bear": (band_map.get("bear") or {}).get("value"),
                "base": (band_map.get("base") or {}).get("value"),
                "bull": (band_map.get("bull") or {}).get("value"),
            }
        )
    football_field["ranges"] = ranges
    return football_field


__all__ = [
    "NOTEBOOK_TYPES",
    "format_metric_value",
    "fix_text",
    "fmt_sens_table",
    "format_unit_value",
    "from_display_value",
    "get_cached_view",
    "get_state",
    "input_step",
    "metric_label",
    "normalize_football_field_payload",
    "rec_unit",
    "render_change_list",
    "render_clean_table",
    "render_compact_list",
    "render_drilldown_button",
    "render_kv_card",
    "set_state",
    "set_note_context",
    "status_breakdown",
    "text_to_lines",
    "to_display_value",
]
