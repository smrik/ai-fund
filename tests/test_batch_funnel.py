from __future__ import annotations

from dashboard.sections import batch_funnel as dashboard_batch_funnel
from src.stage_04_pipeline import batch_funnel


def test_select_top_candidates_prefers_expected_upside_and_filters_non_dcf():
    results = [
        {
            "ticker": "AAA",
            "company_name": "Alpha",
            "model_applicability_status": "dcf_applicable",
            "expected_upside_pct": 18.0,
            "upside_base_pct": 12.0,
            "margin_of_safety": 25.0,
        },
        {
            "ticker": "BBB",
            "company_name": "Bravo",
            "model_applicability_status": "alt_model_required",
            "expected_upside_pct": 50.0,
            "upside_base_pct": 40.0,
            "margin_of_safety": 40.0,
        },
        {
            "ticker": "CCC",
            "company_name": "Charlie",
            "model_applicability_status": "dcf_applicable",
            "expected_upside_pct": None,
            "upside_base_pct": 21.0,
            "margin_of_safety": 10.0,
        },
        {
            "ticker": "DDD",
            "company_name": "Delta",
            "model_applicability_status": "dcf_applicable",
            "expected_upside_pct": 18.0,
            "upside_base_pct": 15.0,
            "margin_of_safety": 30.0,
        },
    ]

    shortlist = batch_funnel.select_top_candidates(results, shortlist_size=3)

    assert [row["ticker"] for row in shortlist] == ["DDD", "AAA", "CCC"]
    assert shortlist[0]["ranking_metric"] == "expected_upside_pct"
    assert shortlist[-1]["ranking_metric"] == "upside_base_pct"


def test_run_deep_analysis_for_tickers_collects_snapshots_and_recommendations(monkeypatch):
    saved_snapshots: list[tuple[str, object, dict]] = []
    recommendation_writes: list[dict] = []

    class _FakeOrchestrator:
        def __init__(self):
            self.last_run_trace = [{"agent": "FilingsAgent", "status": "executed"}]

        def run(self, ticker, *, use_cache=True, force_refresh_agents=None):
            return {"ticker": ticker, "company_name": f"Company {ticker}"}

        def collect_recommendations(self, ticker):
            return {"ticker": ticker, "action": "BUY"}

    monkeypatch.setattr(batch_funnel, "PipelineOrchestrator", _FakeOrchestrator)
    monkeypatch.setattr(batch_funnel, "build_dcf_audit_view", lambda ticker, risk_output=None: {"ticker": ticker, "kind": "dcf"})
    monkeypatch.setattr(batch_funnel, "build_filings_browser_view", lambda ticker: {"ticker": ticker, "kind": "filings"})
    monkeypatch.setattr(batch_funnel, "build_comps_dashboard_view", lambda ticker: {"ticker": ticker, "kind": "comps"})
    monkeypatch.setattr(batch_funnel, "build_news_materiality_view", lambda ticker: {"ticker": ticker, "kind": "market"})
    monkeypatch.setattr(batch_funnel, "write_recommendations", lambda payload: recommendation_writes.append(payload))

    def _fake_save_report_snapshot(ticker, memo, **kwargs):
        saved_snapshots.append((ticker, memo, kwargs))
        return len(saved_snapshots)

    monkeypatch.setattr(batch_funnel, "save_report_snapshot", _fake_save_report_snapshot)

    rows = batch_funnel.run_deep_analysis_for_tickers(["IBM", "MSFT"], use_cache=True, force_refresh_agents=["RiskAgent"])

    assert [row["ticker"] for row in rows] == ["IBM", "MSFT"]
    assert [row["snapshot_id"] for row in rows] == [1, 2]
    assert all(row["status"] == "ok" for row in rows)
    assert recommendation_writes == [
        {"ticker": "IBM", "action": "BUY"},
        {"ticker": "MSFT", "action": "BUY"},
    ]
    assert saved_snapshots[0][2]["dcf_audit"] == {"ticker": "IBM", "kind": "dcf"}


def test_run_deterministic_batch_forwards_progress_callback(monkeypatch):
    progress_events: list[dict] = []

    monkeypatch.setattr(
        batch_funnel,
        "run_batch",
        lambda **kwargs: (
            kwargs["progress_callback"]({"completed": 1, "total": 2, "ticker": "IBM", "status": "valued"}),
            [{"ticker": "IBM", "model_applicability_status": "dcf_applicable", "expected_upside_pct": 12.0}],
        )[1],
    )

    result = batch_funnel.run_deterministic_batch(
        tickers=["IBM", "MSFT"],
        shortlist_size=5,
        progress_callback=lambda payload: progress_events.append(dict(payload)),
    )

    assert progress_events == [{"completed": 1, "total": 2, "ticker": "IBM", "status": "valued"}]
    assert result["selected_tickers"] == ["IBM"]


def test_load_latest_snapshot_for_ticker_returns_latest_payload(monkeypatch):
    monkeypatch.setattr(batch_funnel, "list_report_snapshots", lambda ticker, limit=1: [{"id": 42}])
    monkeypatch.setattr(batch_funnel, "load_report_snapshot", lambda snapshot_id: {"id": snapshot_id, "ticker": "IBM"})

    loaded = batch_funnel.load_latest_snapshot_for_ticker("IBM")

    assert loaded == {"id": 42, "ticker": "IBM"}


def test_dashboard_watchlist_rows_are_normalized_and_ranked_best_first():
    watchlist_view = {
        "saved_at": "2026-03-28T10:00:00Z",
        "universe_size": 2,
        "shortlist_size": 1,
        "rows": [
            {
                "ticker": "BBB",
                "company_name": "Bravo",
                "current_price": 20.0,
                "bear_iv": 18.0,
                "base_iv": 24.0,
                "bull_iv": 30.0,
                "expected_upside_pct": 12.0,
                "upside_base_pct": 10.0,
                "margin_of_safety": 8.0,
                "analyst_target_mean": 25.0,
                "action": "HOLD",
                "conviction": "medium",
                "created_at": "2026-03-27T00:00:00Z",
            },
            {
                "ticker": "AAA",
                "company_name": "Alpha",
                "price": 10.0,
                "iv_bear": 8.0,
                "iv_base": 15.0,
                "iv_bull": 18.0,
                "expected_upside_pct": 25.0,
                "upside_base_pct": 20.0,
                "margin_of_safety": 35.0,
                "analyst_target": 13.0,
                "latest_action": "BUY",
                "latest_conviction": "high",
                "latest_snapshot_date": "2026-03-28",
            },
        ],
    }

    rows = dashboard_batch_funnel._build_watchlist_rows(watchlist_view)

    assert [row["ticker"] for row in rows] == ["AAA", "BBB"]
    assert rows[0]["price"] == 10.0
    assert rows[0]["iv_base"] == 15.0
    assert rows[0]["analyst_target"] == 13.0
    assert rows[0]["latest_action"] == "BUY"
    assert rows[0]["latest_conviction"] == "high"
    assert rows[0]["latest_snapshot_date"] == "2026-03-28"
