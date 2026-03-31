from __future__ import annotations

import logging
from typing import Any

import streamlit as st

from src.stage_04_pipeline.batch_funnel import (
    load_latest_snapshot_for_ticker,
    run_deep_analysis_for_tickers,
    run_deterministic_batch,
)

try:
    from src.stage_04_pipeline.batch_funnel import load_saved_watchlist
except ImportError:  # pragma: no cover - fallback for the in-progress data helper
    load_saved_watchlist = None  # type: ignore[assignment]

from ._shared import render_clean_table, set_note_context

logger = logging.getLogger(__name__)

_WATCHLIST_TABLE_COLUMNS = [
    "ticker",
    "company_name",
    "price",
    "iv_bear",
    "iv_base",
    "iv_bull",
    "expected_iv",
    "analyst_target",
    "latest_action",
    "latest_conviction",
    "latest_snapshot_date",
    "expected_upside_pct",
    "upside_base_pct",
    "margin_of_safety",
    "model_applicability_status",
]


def _parse_ticker_text(raw_text: str) -> list[str]:
    parts = raw_text.replace("\n", ",").split(",")
    return [part.strip().upper() for part in parts if part.strip()]


def _pick_value(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row and row[key] is not None:
            return row[key]
    return None


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _normalize_watchlist_row(row: dict[str, Any]) -> dict[str, Any]:
    ticker = str(_pick_value(row, "ticker", "symbol") or "").strip().upper()
    latest_snapshot_date = _pick_value(row, "latest_snapshot_date", "created_at", "saved_at", "snapshot_date")
    normalized = {
        "ticker": ticker,
        "company_name": _pick_value(row, "company_name", "name", "company"),
        "price": _coerce_float(_pick_value(row, "price", "current_price", "last_price")),
        "iv_bear": _coerce_float(_pick_value(row, "iv_bear", "bear_iv", "bear")),
        "iv_base": _coerce_float(_pick_value(row, "iv_base", "base_iv", "base")),
        "iv_bull": _coerce_float(_pick_value(row, "iv_bull", "bull_iv", "bull")),
        "expected_iv": _coerce_float(_pick_value(row, "expected_iv", "weighted_iv", "risk_adjusted_expected_iv")),
        "analyst_target": _coerce_float(_pick_value(row, "analyst_target", "analyst_target_mean", "target_price")),
        "latest_action": _pick_value(row, "latest_action", "action"),
        "latest_conviction": _pick_value(row, "latest_conviction", "conviction"),
        "latest_snapshot_date": latest_snapshot_date,
        "expected_upside_pct": _coerce_float(_pick_value(row, "expected_upside_pct")),
        "upside_base_pct": _coerce_float(_pick_value(row, "upside_base_pct")),
        "margin_of_safety": _coerce_float(_pick_value(row, "margin_of_safety")),
        "ranking_metric": _pick_value(row, "ranking_metric", "score_source"),
        "ranking_value": _coerce_float(_pick_value(row, "ranking_value", "ranking_score")),
        "model_applicability_status": _pick_value(row, "model_applicability_status"),
    }
    if normalized["ranking_metric"] is None:
        if normalized["expected_upside_pct"] is not None:
            normalized["ranking_metric"] = "expected_upside_pct"
        elif normalized["upside_base_pct"] is not None:
            normalized["ranking_metric"] = "upside_base_pct"
        else:
            normalized["ranking_metric"] = "margin_of_safety"
    if normalized["latest_action"] is None:
        normalized["latest_action"] = _pick_value(row, "action")
    if normalized["latest_conviction"] is None:
        normalized["latest_conviction"] = _pick_value(row, "conviction")
    if normalized["latest_snapshot_date"] is None:
        normalized["latest_snapshot_date"] = _pick_value(row, "created_at", "saved_at")
    return normalized


def _watchlist_sort_key(row: dict[str, Any]) -> tuple[float, float, float, float, str]:
    def _sort_value(value: Any) -> float:
        return value if isinstance(value, (int, float)) else float("-inf")

    return (
        _sort_value(row.get("expected_upside_pct")),
        _sort_value(row.get("upside_base_pct")),
        _sort_value(row.get("ranking_value")),
        _sort_value(row.get("margin_of_safety")),
        str(row.get("ticker") or ""),
    )


def _watchlist_source_rows(funnel_view: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("rows", "results", "watchlist_rows", "items"):
        rows = funnel_view.get(key) or []
        if rows:
            return [dict(row) for row in rows]
    return []


def _build_watchlist_rows(funnel_view: dict[str, Any]) -> list[dict[str, Any]]:
    rows = [_normalize_watchlist_row(row) for row in _watchlist_source_rows(funnel_view)]
    rows.sort(key=_watchlist_sort_key, reverse=True)
    return rows


def _watchlist_metadata(funnel_view: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    saved_at = _pick_value(funnel_view, "last_updated", "saved_at", "last_saved_at", "generated_at", "updated_at")
    universe_size = _pick_value(funnel_view, "universe_row_count", "universe_size")
    shortlist = funnel_view.get("shortlist") or []
    focus_ticker = _pick_value(funnel_view, "focus_ticker", "selected_ticker", "default_focus_ticker")
    if focus_ticker is None and rows:
        focus_ticker = rows[0].get("ticker")
    try:
        universe_count = int(universe_size) if universe_size is not None else len(rows)
    except (TypeError, ValueError):
        universe_count = len(rows)
    return {
        "saved_at": saved_at,
        "universe_size": universe_count,
        "saved_rows": _pick_value(funnel_view, "saved_row_count") or len(rows),
        "shortlist_size": _pick_value(funnel_view, "shortlist_size") or len(shortlist),
        "focus_ticker": focus_ticker,
    }


def _hydrate_snapshot_into_state(state: Any, loaded: dict[str, Any]) -> None:
    state["_pending_snapshot"] = loaded


def _build_progress_callback(progress_bar, status_box):
    def _on_progress(payload: dict[str, Any]) -> None:
        total = max(int(payload.get("total") or 0), 1)
        completed = min(int(payload.get("completed") or 0), total)
        percent = int((completed / total) * 100)
        ticker = payload.get("ticker")
        status = payload.get("status") or "running"
        if status == "complete":
            message = f"Deterministic batch complete. {completed}/{total} tickers processed."
        elif ticker:
            message = f"{completed}/{total} processed: {ticker} ({status})"
        else:
            message = f"Preparing deterministic batch for {total} tickers..."
        progress_bar.progress(percent, text=message)
        status_box.caption(message)

    return _on_progress


def _load_saved_watchlist_view(state: Any) -> dict[str, Any] | None:
    current = state.get("batch_funnel_view")
    if current:
        return current
    loader = globals().get("load_saved_watchlist")
    if not callable(loader):
        return None
    try:
        loaded = loader(shortlist_size=int(state.get("batch_funnel_shortlist_size", 10) or 10))
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.warning("Saved watchlist load failed: %s", exc, extra={"step": "batch_funnel"})
        return None
    if loaded:
        state["batch_funnel_view"] = loaded
        state.setdefault("batch_funnel_runs", [])
    return state.get("batch_funnel_view")


def _shortlist_rows(funnel_view: dict[str, Any]) -> list[dict[str, Any]]:
    shortlist = funnel_view.get("shortlist") or []
    return [
        {
            "ticker": row.get("ticker"),
            "company_name": row.get("company_name"),
            "expected_upside_pct": row.get("expected_upside_pct"),
            "upside_base_pct": row.get("upside_base_pct"),
            "margin_of_safety": row.get("margin_of_safety"),
            "ranking_metric": row.get("ranking_metric"),
            "latest_action": row.get("latest_action"),
            "latest_snapshot_date": row.get("latest_snapshot_date"),
        }
        for row in shortlist
    ]


def render(memo, session_state: Any | None = None) -> None:
    del memo
    state = session_state or st.session_state
    set_note_context(state, page="Audit", subpage="Batch Funnel", item="Batch Funnel")

    _load_saved_watchlist_view(state)
    funnel_view = state.get("batch_funnel_view") or {}
    watchlist_rows = _build_watchlist_rows(funnel_view)
    metadata = _watchlist_metadata(funnel_view, watchlist_rows)

    st.subheader("Universe Watchlist")
    st.caption(
        "Saved deterministic universe results first, then manual refresh and ticker drilldown. "
        "Open the latest archived snapshot when you want the full memo; rerun deep analysis only when needed."
    )

    metrics = st.columns(4)
    metrics[0].metric("Last Updated", str(metadata.get("saved_at") or "—"))
    metrics[1].metric("Universe Rows", str(metadata.get("universe_size") or 0))
    metrics[2].metric("Saved Rows", str(metadata.get("saved_rows") or 0))
    metrics[3].metric("Shortlist", str(metadata.get("shortlist_size") or 0))

    st.markdown("#### Saved Watchlist")
    if watchlist_rows:
        render_clean_table(
            watchlist_rows,
            column_order=_WATCHLIST_TABLE_COLUMNS,
            height=520,
        )
    else:
        st.info("No saved watchlist is available yet. Use Refresh Batch to generate one from the universe.")

    with st.expander("Refresh batch", expanded=False):
        ticker_text = st.text_area(
            "Universe tickers",
            key="batch_funnel_tickers",
            placeholder="Leave blank to use config/universe.csv, or enter tickers separated by commas/new lines.",
            help="When blank, the deterministic batch runner uses config/universe.csv.",
        )
        shortlist_size = int(
            st.number_input(
                "Shortlist size",
                min_value=1,
                max_value=25,
                value=int(state.get("batch_funnel_shortlist_size", 10) or 10),
                step=1,
                key="batch_funnel_shortlist_size",
            )
        )
        export_xlsx = st.checkbox("Export Excel workbook during deterministic batch", key="batch_funnel_export_xlsx")
        if st.button("Refresh Batch", type="primary", key="batch_funnel_run_batch"):
            tickers = _parse_ticker_text(ticker_text)
            progress_box = st.progress(0, text="Preparing deterministic batch...")
            status_box = st.empty()
            with st.spinner("Running deterministic batch valuation..."):
                run_deterministic_batch(
                    tickers=tickers or None,
                    shortlist_size=shortlist_size,
                    export_xlsx=export_xlsx,
                    progress_callback=_build_progress_callback(progress_box, status_box),
                )
                if callable(load_saved_watchlist):
                    state["batch_funnel_view"] = load_saved_watchlist(shortlist_size=shortlist_size)
                else:
                    state["batch_funnel_view"] = {}
                state["batch_funnel_runs"] = []
            st.rerun()

    available_tickers = [row.get("ticker") for row in watchlist_rows if row.get("ticker")]
    if not available_tickers:
        return

    default_focus = metadata.get("focus_ticker")
    if default_focus not in available_tickers:
        default_focus = available_tickers[0]
    focus_index = available_tickers.index(default_focus) if default_focus in available_tickers else 0
    focus_ticker = st.selectbox(
        "Ticker for drilldown",
        options=available_tickers,
        index=focus_index,
        key="batch_funnel_focus_ticker",
        help="Use this to open the latest archived ticker snapshot or run a manual deep analysis.",
    )

    action_col1, action_col2 = st.columns(2, gap="large")
    with action_col1:
        if st.button("Open Latest Snapshot", key="batch_funnel_open_snapshot"):
            loaded = load_latest_snapshot_for_ticker(focus_ticker)
            if loaded is None:
                st.warning(f"No archived snapshot found for {focus_ticker}. Run deep analysis manually if you want to create one.")
            else:
                _hydrate_snapshot_into_state(state, loaded)
                st.rerun()
    with action_col2:
        use_agent_cache = st.checkbox(
            "Use agent cache for deep analysis",
            value=True,
            key="batch_funnel_use_cache",
        )
        action_label = (
            "Run Deep Analysis For Focus Ticker"
            if not next((row for row in watchlist_rows if row.get("ticker") == focus_ticker and row.get("latest_snapshot_date")), None)
            else "Rerun Deep Analysis For Focus Ticker"
        )
        if st.button(action_label, key="batch_funnel_run_focus_analysis"):
            with st.spinner("Running full deep analysis for the selected ticker..."):
                state["batch_funnel_runs"] = run_deep_analysis_for_tickers(
                    [focus_ticker],
                    use_cache=use_agent_cache,
                )
                if callable(load_saved_watchlist):
                    state["batch_funnel_view"] = load_saved_watchlist(
                        shortlist_size=int(state.get("batch_funnel_shortlist_size", 10) or 10)
                    )
            st.rerun()

    shortlist_rows = _shortlist_rows(funnel_view)
    if shortlist_rows:
        st.markdown("#### Deep Analysis Shortlist")
        render_clean_table(
            shortlist_rows,
            column_order=[
                "ticker",
                "company_name",
                "expected_upside_pct",
                "upside_base_pct",
                "margin_of_safety",
                "ranking_metric",
                "latest_action",
                "latest_snapshot_date",
            ],
        )

        shortlist_options = [str(row.get("ticker")) for row in funnel_view.get("shortlist") or [] if row.get("ticker")]
        default_selection = funnel_view.get("selected_tickers") or shortlist_options
        selected_tickers = st.multiselect(
            "Tickers for full deep analysis",
            options=shortlist_options,
            default=default_selection,
            key="batch_funnel_selected_tickers",
            help="Defaults to the best-ranked deterministic shortlist. Remove names if you want to conserve agent/API usage further.",
        )
        if st.button("Run Full Deep Analysis For Selected Shortlist", key="batch_funnel_run_deep_analysis"):
            if not selected_tickers:
                st.warning("Select at least one ticker before running deep analysis.")
            else:
                with st.spinner("Running full deep analysis on the selected shortlist..."):
                    state["batch_funnel_runs"] = run_deep_analysis_for_tickers(
                        selected_tickers,
                        use_cache=use_agent_cache,
                    )
                    if callable(load_saved_watchlist):
                        state["batch_funnel_view"] = load_saved_watchlist(
                            shortlist_size=int(state.get("batch_funnel_shortlist_size", 10) or 10)
                        )
                st.rerun()

    run_rows = state.get("batch_funnel_runs") or []
    if run_rows:
        st.markdown("#### Deep Analysis Runs")
        render_clean_table(run_rows, column_order=["ticker", "status", "snapshot_id", "run_trace_steps", "error"])
