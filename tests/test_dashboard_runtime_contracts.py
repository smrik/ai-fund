from __future__ import annotations

from dashboard import design_system
from dashboard.sections import _shared, audit, batch_funnel, valuation
from src.stage_02_valuation.templates.ic_memo import ICMemo, ValuationRange


class _DummyContext:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _MetricColumn:
    def metric(self, *args, **kwargs):
        return None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _sample_memo() -> ICMemo:
    return ICMemo(
        ticker="IBM",
        company_name="IBM",
        sector="Technology",
        action="BUY",
        conviction="medium",
        one_liner="Sample memo",
        variant_thesis_prompt="What is the durable edge?",
        valuation=ValuationRange(
            bear=80.0,
            base=100.0,
            bull=120.0,
            current_price=90.0,
            upside_pct_base=(100.0 / 90.0) - 1.0,
        ),
    )


def test_render_clean_table_omits_height_when_not_provided(monkeypatch):
    captured: dict[str, object] = {}

    def _fake_dataframe(payload, **kwargs):
        captured["payload"] = payload
        captured["kwargs"] = kwargs

    monkeypatch.setattr(_shared.st, "info", lambda *args, **kwargs: None)
    monkeypatch.setattr(_shared.st, "dataframe", _fake_dataframe)

    _shared.render_clean_table([{"ticker": "IBM", "score": 1.2}], column_order=None)

    assert captured["payload"] == [{"ticker": "IBM", "score": 1.2}]
    assert captured["kwargs"] == {"width": "stretch", "hide_index": True}


def test_render_ticker_strip_emits_inline_html_not_escaped_code(monkeypatch):
    captured: dict[str, object] = {}

    def _fake_markdown(payload, **kwargs):
        captured["payload"] = payload
        captured["kwargs"] = kwargs

    monkeypatch.setattr(design_system.st, "markdown", _fake_markdown)

    design_system.render_ticker_strip(
        ticker="IBM",
        company_name="IBM Corp",
        sector="Technology",
        action="BUY",
        conviction="high",
        current_price=100.0,
        base_iv=125.0,
        upside_pct_base=0.25,
        snapshot_label="archive:7",
    )

    html = str(captured["payload"])
    assert '<div class="ap-ticker-strip-metrics"><div class="ap-ticker-strip-metric">' in html
    assert captured["kwargs"] == {"unsafe_allow_html": True}


def test_valuation_summary_derives_bear_and_bull_upside_without_missing_attributes(monkeypatch):
    memo = _sample_memo()
    captured_rows: list[dict] = []

    monkeypatch.setattr(valuation.st, "markdown", lambda *args, **kwargs: None)
    monkeypatch.setattr(valuation.st, "columns", lambda count: [_MetricColumn() for _ in range(count)])
    monkeypatch.setattr(valuation.st, "expander", lambda *args, **kwargs: _DummyContext())
    monkeypatch.setattr(valuation.st, "segmented_control", lambda *args, **kwargs: "Summary")
    monkeypatch.setattr(valuation, "set_note_context", lambda *args, **kwargs: None)
    monkeypatch.setattr(valuation, "render_clean_table", lambda rows, **kwargs: captured_rows.extend(rows))
    monkeypatch.setattr(valuation.wacc_lab, "render", lambda *args, **kwargs: None)
    monkeypatch.setattr(valuation.assumption_lab, "render", lambda *args, **kwargs: None)
    monkeypatch.setattr(valuation.recommendations, "render", lambda *args, **kwargs: None)

    valuation.render(memo, session_state={"valuation_view": "Summary"})

    assert captured_rows == [
        {"Scenario": "Bear", "Intrinsic Value": "$80.00", "Upside / (Downside)": "-11.1%"},
        {"Scenario": "Base", "Intrinsic Value": "$100.00", "Upside / (Downside)": "+11.1%"},
        {"Scenario": "Bull", "Intrinsic Value": "$120.00", "Upside / (Downside)": "+33.3%"},
    ]


def test_valuation_assumptions_and_wacc_are_first_class_views(monkeypatch):
    memo = _sample_memo()
    routed: list[str] = []

    monkeypatch.setattr(valuation.st, "markdown", lambda *args, **kwargs: None)
    monkeypatch.setattr(valuation.st, "columns", lambda count: [_MetricColumn() for _ in range(count)])
    monkeypatch.setattr(valuation.st, "segmented_control", lambda *args, **kwargs: "Assumptions")
    monkeypatch.setattr(valuation, "set_note_context", lambda *args, **kwargs: None)
    monkeypatch.setattr(valuation.assumption_lab, "render", lambda *args, **kwargs: routed.append("assumptions"))
    monkeypatch.setattr(valuation.wacc_lab, "render", lambda *args, **kwargs: routed.append("wacc"))

    valuation.render(memo, session_state={"valuation_view": "Assumptions"})

    monkeypatch.setattr(valuation.st, "segmented_control", lambda *args, **kwargs: "WACC")
    valuation.render(memo, session_state={"valuation_view": "WACC"})

    assert routed == ["assumptions", "wacc"]


def test_audit_routes_batch_funnel_without_loaded_memo(monkeypatch):
    routed: dict[str, object] = {}

    monkeypatch.setattr(audit.st, "segmented_control", lambda *args, **kwargs: "Batch Funnel")
    monkeypatch.setattr(audit, "set_note_context", lambda *args, **kwargs: None)
    monkeypatch.setattr(audit.batch_funnel, "render", lambda memo, session_state=None: routed.update({"memo": memo, "state": session_state}))

    state = {"audit_view": "Batch Funnel"}
    audit.render(None, session_state=state)

    assert routed == {"memo": None, "state": state}


def test_render_drilldown_button_queues_navigation_before_rerun(monkeypatch):
    state: dict[str, object] = {}
    reruns: list[str] = []

    monkeypatch.setattr(_shared.st, "button", lambda *args, **kwargs: True)
    monkeypatch.setattr(_shared.st, "rerun", lambda: reruns.append("rerun"))

    _shared.render_drilldown_button(
        "Open Valuation",
        target_tab="Valuation",
        target_key="valuation_view",
        target_value="Assumptions",
        session_state=state,
        key="open_valuation_test",
    )

    assert state["_pending_nav"] == {
        "selected_primary_tab": "Valuation",
        "target_key": "valuation_view",
        "target_value": "Assumptions",
    }
    assert reruns == ["rerun"]


def test_batch_funnel_restores_saved_watchlist_without_rerun(monkeypatch):
    saved_watchlist = {
        "last_updated": "2026-03-28",
        "universe_row_count": 2,
        "saved_row_count": 2,
        "shortlist_size": 1,
        "default_focus_ticker": "AAA",
        "selected_tickers": ["AAA"],
        "shortlist": [
            {
                "ticker": "AAA",
                "company_name": "Alpha",
                "expected_upside_pct": 25.0,
                "upside_base_pct": 20.0,
                "margin_of_safety": 35.0,
                "latest_action": "BUY",
                "latest_snapshot_date": "2026-03-28T00:00:00Z",
                "ranking_metric": "expected_upside_pct",
            }
        ],
        "rows": [
            {
                "ticker": "BBB",
                "company_name": "Bravo",
                "price": 20.0,
                "iv_bear": 18.0,
                "iv_base": 22.0,
                "iv_bull": 26.0,
                "expected_upside_pct": 12.0,
                "upside_base_pct": 10.0,
                "margin_of_safety": 8.0,
                "analyst_target": 24.0,
                "latest_action": "HOLD",
                "latest_conviction": "medium",
                "latest_snapshot_date": "2026-03-27",
            },
            {
                "ticker": "AAA",
                "company_name": "Alpha",
                "current_price": 10.0,
                "bear_iv": 8.0,
                "base_iv": 15.0,
                "bull_iv": 18.0,
                "expected_upside_pct": 25.0,
                "upside_base_pct": 20.0,
                "margin_of_safety": 35.0,
                "analyst_target_mean": 13.0,
                "action": "BUY",
                "conviction": "high",
                "created_at": "2026-03-28T00:00:00Z",
            },
        ],
    }
    state = {"batch_funnel_view": None, "batch_funnel_runs": [], "batch_funnel_shortlist_size": 10}
    captured_tables: list[list[dict]] = []

    monkeypatch.setattr(batch_funnel, "load_saved_watchlist", lambda shortlist_size=10: saved_watchlist)
    monkeypatch.setattr(batch_funnel.st, "markdown", lambda *args, **kwargs: None)
    monkeypatch.setattr(batch_funnel.st, "subheader", lambda *args, **kwargs: None)
    monkeypatch.setattr(batch_funnel.st, "caption", lambda *args, **kwargs: None)
    monkeypatch.setattr(batch_funnel.st, "expander", lambda *args, **kwargs: _DummyContext())
    monkeypatch.setattr(batch_funnel.st, "text_area", lambda *args, **kwargs: "")
    monkeypatch.setattr(batch_funnel.st, "number_input", lambda *args, **kwargs: 10)
    monkeypatch.setattr(batch_funnel.st, "checkbox", lambda *args, **kwargs: True)
    monkeypatch.setattr(batch_funnel.st, "button", lambda *args, **kwargs: False)
    monkeypatch.setattr(batch_funnel.st, "info", lambda *args, **kwargs: None)
    monkeypatch.setattr(batch_funnel.st, "warning", lambda *args, **kwargs: None)
    monkeypatch.setattr(batch_funnel.st, "selectbox", lambda *args, **kwargs: "AAA")
    monkeypatch.setattr(batch_funnel.st, "multiselect", lambda *args, **kwargs: ["AAA"])
    monkeypatch.setattr(batch_funnel.st, "spinner", lambda *args, **kwargs: _DummyContext())
    monkeypatch.setattr(batch_funnel.st, "progress", lambda *args, **kwargs: _DummyContext())
    monkeypatch.setattr(batch_funnel.st, "empty", lambda *args, **kwargs: _DummyContext())
    monkeypatch.setattr(
        batch_funnel.st,
        "columns",
        lambda count, *args, **kwargs: [_MetricColumn() for _ in range(count if isinstance(count, int) else len(count))],
    )
    monkeypatch.setattr(batch_funnel.st, "rerun", lambda: None)
    monkeypatch.setattr(batch_funnel, "render_clean_table", lambda rows, **kwargs: captured_tables.append(list(rows)))

    batch_funnel.render(None, session_state=state)

    assert state["batch_funnel_view"] == saved_watchlist
    assert [row["ticker"] for row in captured_tables[0]] == ["AAA", "BBB"]
    assert captured_tables[0][0]["latest_action"] == "BUY"
    assert captured_tables[0][0]["latest_snapshot_date"] == "2026-03-28T00:00:00Z"


def test_batch_funnel_missing_snapshot_keeps_deep_analysis_manual(monkeypatch):
    state = {
        "batch_funnel_view": {
            "last_updated": "2026-03-28",
            "universe_row_count": 1,
            "saved_row_count": 1,
            "shortlist_size": 1,
            "selected_tickers": ["IBM"],
            "default_focus_ticker": "IBM",
            "shortlist": [
                {
                    "ticker": "IBM",
                    "company_name": "IBM",
                    "expected_upside_pct": 20.0,
                    "upside_base_pct": 15.0,
                    "margin_of_safety": 25.0,
                    "ranking_metric": "expected_upside_pct",
                }
            ],
            "rows": [
                {
                    "ticker": "IBM",
                    "company_name": "IBM",
                    "price": 10.0,
                    "iv_bear": 8.0,
                    "iv_base": 12.0,
                    "iv_bull": 15.0,
                    "expected_upside_pct": 20.0,
                    "upside_base_pct": 15.0,
                    "margin_of_safety": 25.0,
                }
            ],
        },
        "batch_funnel_runs": [],
    }
    run_calls: list[tuple[tuple[str, ...], dict]] = []

    monkeypatch.setattr(batch_funnel, "load_latest_snapshot_for_ticker", lambda ticker: None)
    monkeypatch.setattr(batch_funnel, "load_saved_watchlist", lambda shortlist_size=10: state["batch_funnel_view"])
    monkeypatch.setattr(batch_funnel, "run_deep_analysis_for_tickers", lambda tickers, **kwargs: run_calls.append((tuple(tickers), kwargs)) or [{"ticker": tickers[0], "status": "ok"}])
    monkeypatch.setattr(batch_funnel.st, "markdown", lambda *args, **kwargs: None)
    monkeypatch.setattr(batch_funnel.st, "subheader", lambda *args, **kwargs: None)
    monkeypatch.setattr(batch_funnel.st, "caption", lambda *args, **kwargs: None)
    monkeypatch.setattr(batch_funnel.st, "expander", lambda *args, **kwargs: _DummyContext())
    monkeypatch.setattr(batch_funnel.st, "text_area", lambda *args, **kwargs: "")
    monkeypatch.setattr(batch_funnel.st, "number_input", lambda *args, **kwargs: 10)
    monkeypatch.setattr(batch_funnel.st, "checkbox", lambda *args, **kwargs: True)
    monkeypatch.setattr(batch_funnel.st, "info", lambda *args, **kwargs: None)
    monkeypatch.setattr(batch_funnel.st, "warning", lambda *args, **kwargs: None)
    monkeypatch.setattr(batch_funnel.st, "selectbox", lambda *args, **kwargs: "IBM")
    monkeypatch.setattr(batch_funnel.st, "multiselect", lambda *args, **kwargs: ["IBM"])
    monkeypatch.setattr(batch_funnel.st, "spinner", lambda *args, **kwargs: _DummyContext())
    monkeypatch.setattr(batch_funnel.st, "progress", lambda *args, **kwargs: _DummyContext())
    monkeypatch.setattr(batch_funnel.st, "empty", lambda *args, **kwargs: _DummyContext())
    monkeypatch.setattr(
        batch_funnel.st,
        "columns",
        lambda count, *args, **kwargs: [_MetricColumn() for _ in range(count if isinstance(count, int) else len(count))],
    )
    monkeypatch.setattr(batch_funnel.st, "button", lambda label, **kwargs: label == "Run Deep Analysis For Focus Ticker")
    monkeypatch.setattr(batch_funnel.st, "rerun", lambda: None)
    monkeypatch.setattr(batch_funnel, "render_clean_table", lambda *args, **kwargs: None)

    batch_funnel.render(None, session_state=state)

    assert run_calls == [(("IBM",), {"use_cache": True})]


def test_batch_funnel_open_snapshot_queues_pending_snapshot(monkeypatch):
    state = {
        "batch_funnel_view": {
            "last_updated": "2026-03-28",
            "universe_row_count": 1,
            "saved_row_count": 1,
            "shortlist_size": 1,
            "selected_tickers": ["IBM"],
            "default_focus_ticker": "IBM",
            "shortlist": [],
            "rows": [{"ticker": "IBM", "company_name": "IBM", "price": 10.0}],
        },
        "batch_funnel_runs": [],
    }
    reruns: list[str] = []
    loaded_snapshot = {"id": 7, "memo": {"ticker": "IBM"}, "dashboard_snapshot": {}}

    monkeypatch.setattr(batch_funnel, "load_latest_snapshot_for_ticker", lambda ticker: loaded_snapshot)
    monkeypatch.setattr(batch_funnel.st, "markdown", lambda *args, **kwargs: None)
    monkeypatch.setattr(batch_funnel.st, "subheader", lambda *args, **kwargs: None)
    monkeypatch.setattr(batch_funnel.st, "caption", lambda *args, **kwargs: None)
    monkeypatch.setattr(batch_funnel.st, "expander", lambda *args, **kwargs: _DummyContext())
    monkeypatch.setattr(batch_funnel.st, "text_area", lambda *args, **kwargs: "")
    monkeypatch.setattr(batch_funnel.st, "number_input", lambda *args, **kwargs: 10)
    monkeypatch.setattr(batch_funnel.st, "checkbox", lambda *args, **kwargs: True)
    monkeypatch.setattr(batch_funnel.st, "info", lambda *args, **kwargs: None)
    monkeypatch.setattr(batch_funnel.st, "warning", lambda *args, **kwargs: None)
    monkeypatch.setattr(batch_funnel.st, "selectbox", lambda *args, **kwargs: "IBM")
    monkeypatch.setattr(batch_funnel.st, "multiselect", lambda *args, **kwargs: [])
    monkeypatch.setattr(batch_funnel.st, "spinner", lambda *args, **kwargs: _DummyContext())
    monkeypatch.setattr(batch_funnel.st, "progress", lambda *args, **kwargs: _DummyContext())
    monkeypatch.setattr(batch_funnel.st, "empty", lambda *args, **kwargs: _DummyContext())
    monkeypatch.setattr(
        batch_funnel.st,
        "columns",
        lambda count, *args, **kwargs: [_MetricColumn() for _ in range(count if isinstance(count, int) else len(count))],
    )
    monkeypatch.setattr(batch_funnel.st, "button", lambda label, **kwargs: label == "Open Latest Snapshot")
    monkeypatch.setattr(batch_funnel.st, "rerun", lambda: reruns.append("rerun"))
    monkeypatch.setattr(batch_funnel, "render_clean_table", lambda *args, **kwargs: None)

    batch_funnel.render(None, session_state=state)

    assert state["_pending_snapshot"] == loaded_snapshot
    assert reruns == ["rerun"]
