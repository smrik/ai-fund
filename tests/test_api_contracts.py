from __future__ import annotations

import tempfile
import time
from pathlib import Path

from fastapi.testclient import TestClient


def _canonical_dossier_payload() -> dict:
    return {
        "contract_name": "TickerDossier",
        "contract_version": "1.0.0",
        "ticker": "IBM",
        "as_of_date": "2026-04-30",
        "display_name": "Canonical Machines",
        "currency": "USD",
        "latest_snapshot": {
            "company_identity": {
                "ticker": "IBM",
                "display_name": "Canonical Machines",
                "sector": "Canonical Sector",
                "industry": "Canonical Industry",
                "exchange": "NYSE",
            },
            "market_snapshot": {
                "as_of_date": "2026-04-30",
                "price": 111.0,
                "analyst_target": 222.0,
                "analyst_recommendation": "canonical-rating",
            },
            "valuation_snapshot": {
                "bear_iv": 120.0,
                "base_iv": 155.0,
                "bull_iv": 210.0,
                "expected_iv": 166.0,
                "current_price": 112.0,
                "upside_pct": 0.35,
            },
            "historical_series": {},
            "qoe_snapshot": {"present": False, "score": None, "flags": []},
            "comps_snapshot": {},
            "source_lineage": {},
        },
        "loaded_backend_state": {"backend_name": "test", "source_mode": "latest_snapshot"},
        "source_lineage": {},
        "export_metadata": {"source_mode": "latest_snapshot", "snapshot_id": 44},
        "optional_overlays": {},
    }


def _install_legacy_ticker_mocks(monkeypatch) -> None:
    def _mock_both(name, func):
        monkeypatch.setattr(f"api.main.{name}", func)
        if hasattr(__import__("src.stage_04_pipeline.workspace_views", fromlist=[""]), name):
            monkeypatch.setattr(f"src.stage_04_pipeline.workspace_views.{name}", func)

    _mock_both(
        "load_saved_watchlist",
        lambda shortlist_size=10: {
            "rows": [
                {
                    "ticker": "IBM",
                    "company_name": "Legacy Watchlist",
                    "sector": "Legacy Watchlist Sector",
                    "price": 10.0,
                    "iv_bear": 11.0,
                    "iv_base": 20.0,
                    "iv_bull": 30.0,
                    "expected_iv": 22.0,
                    "upside_base_pct": 100.0,
                    "latest_action": "BUY",
                    "latest_conviction": "high",
                    "latest_snapshot_date": "2026-01-01",
                }
            ]
        },
    )
    _mock_both(
        "load_latest_snapshot_for_ticker",
        lambda ticker: {
            "id": 7,
            "ticker": ticker,
            "company_name": "Legacy Snapshot",
            "sector": "Legacy Snapshot Sector",
            "action": "REVIEW",
            "conviction": "medium",
            "current_price": 12.0,
            "base_iv": 24.0,
            "created_at": "2026-02-02",
            "memo": {
                "company_name": "Legacy Memo",
                "sector": "Legacy Memo Sector",
                "action": "WATCH",
                "conviction": "low",
                "one_liner": "Legacy one-liner.",
                "variant_thesis_prompt": "Legacy thesis prompt.",
                "date": "2026-02-03",
                "valuation": {
                    "current_price": 13.0,
                    "base": 25.0,
                    "bear": 15.0,
                    "bull": 35.0,
                    "upside_pct_base": 0.1,
                },
            },
        },
    )
    _mock_both(
        "get_market_data",
        lambda ticker, use_cache=True: {
            "name": "Legacy Market",
            "sector": "Legacy Market Sector",
            "current_price": 14.0,
            "analyst_target_mean": 40.0,
        },
    )
    _mock_both("get_analyst_ratings", lambda ticker: {"target_mean": 41.0, "recommendation": "legacy-rating"})
    _mock_both(
        "build_thesis_tracker_view",
        lambda ticker: {
            "stance": {"next_catalyst": {"title": "Legacy catalyst"}},
            "what_changed": {"summary_lines": ["Legacy tracker line"]},
        },
    )
    _mock_both(
        "build_news_materiality_view",
        lambda ticker: {"historical_brief": {"summary": "Legacy market pulse."}},
    )
    _mock_both(
        "build_dcf_audit_view",
        lambda ticker: {
            "model_integrity": {"tv_high_flag": False, "revenue_data_quality_flag": "legacy"},
            "scenario_summary": [{"scenario": "base", "intrinsic_value": 25.0}],
        },
    )


def test_api_allows_local_frontend_cors_requests(monkeypatch):
    from api.main import app

    monkeypatch.setattr(
        "api.main.load_saved_watchlist",
        lambda shortlist_size=10: {
            "rows": [{"ticker": "IBM", "company_name": "IBM"}],
            "shortlist": [{"ticker": "IBM"}],
            "saved_row_count": 1,
            "universe_row_count": 1,
            "shortlist_size": shortlist_size,
            "default_focus_ticker": "IBM",
            "last_updated": "2026-03-28",
        },
    )

    client = TestClient(app)
    preflight = client.options(
        "/api/watchlist/refresh",
        headers={
            "Origin": "http://127.0.0.1:4173",
            "Access-Control-Request-Method": "POST",
        },
    )
    get_response = client.get("/api/watchlist", headers={"Origin": "http://127.0.0.1:4173"})

    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == "http://127.0.0.1:4173"
    assert get_response.status_code == 200
    assert get_response.headers["access-control-allow-origin"] == "http://127.0.0.1:4173"


def test_watchlist_endpoint_returns_saved_universe_payload(monkeypatch):
    from api.main import app

    monkeypatch.setattr(
        "api.main.load_saved_watchlist",
        lambda shortlist_size=10: {
            "rows": [{"ticker": "IBM", "company_name": "IBM"}],
            "shortlist": [{"ticker": "IBM"}],
            "saved_row_count": 1,
            "universe_row_count": 1,
            "shortlist_size": shortlist_size,
            "default_focus_ticker": "IBM",
            "last_updated": "2026-03-28",
        },
    )

    client = TestClient(app)
    response = client.get("/api/watchlist")

    assert response.status_code == 200
    payload = response.json()
    assert payload["default_focus_ticker"] == "IBM"
    assert payload["rows"][0]["ticker"] == "IBM"
    assert payload["saved_row_count"] == 1


def test_watchlist_refresh_returns_run_id_and_run_status(monkeypatch):
    from api.main import app

    def _fake_run_deterministic_batch(**kwargs):
        return {"run": "done", "kwargs": kwargs}

    monkeypatch.setattr("api.main.run_deterministic_batch", _fake_run_deterministic_batch)

    client = TestClient(app)
    response = client.post("/api/watchlist/refresh", json={"tickers": ["IBM"], "shortlist_size": 3})

    assert response.status_code == 202
    run_id = response.json()["run_id"]
    assert run_id

    for _ in range(20):
        status = client.get(f"/api/runs/{run_id}")
        assert status.status_code == 200
        payload = status.json()
        if payload["status"] == "completed":
            assert payload["result"]["run"] == "done"
            assert payload["progress"] == 1.0
            break
        time.sleep(0.01)
    else:  # pragma: no cover - diagnostic guard
        raise AssertionError("run never completed")


def test_ticker_workspace_endpoint_returns_compact_strip(monkeypatch):
    from api.main import app

    monkeypatch.setattr(
        "api.main.build_ticker_workspace_payload",
        lambda ticker: {
            "ticker": ticker,
            "company_name": "IBM",
            "sector": "Technology",
            "action": "BUY",
            "conviction": "high",
            "current_price": 100.0,
            "base_iv": 125.0,
            "snapshot_id": 7,
            "last_snapshot_date": "2026-03-28T09:15:00+00:00",
        },
    )

    client = TestClient(app)
    response = client.get("/api/tickers/IBM/workspace")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ticker"] == "IBM"
    assert payload["current_price"] == 100.0
    assert payload["snapshot_id"] == 7


def test_ticker_overview_and_valuation_endpoints_return_helper_payloads(monkeypatch):
    from api.main import app

    monkeypatch.setattr(
        "api.main.build_ticker_overview_payload",
        lambda ticker: {"ticker": ticker, "snapshot_id": 7, "tracker": {"available": True}},
    )
    monkeypatch.setattr(
        "api.main.build_valuation_summary_payload",
        lambda ticker: {"ticker": ticker, "available": True, "weighted_iv": 123.0},
    )
    monkeypatch.setattr(
        "api.main.build_valuation_dcf_payload",
        lambda ticker: {"ticker": ticker, "available": True, "scenario_summary": [{"scenario": "base"}]},
    )
    monkeypatch.setattr(
        "api.main.build_valuation_comps_payload",
        lambda ticker: {"ticker": ticker, "available": True, "peer_counts": {"raw": 8}},
    )
    monkeypatch.setattr(
        "api.main.build_valuation_assumptions_payload",
        lambda ticker: {
            "ticker": ticker,
            "available": True,
            "fields": [{"field": "wacc", "initial_mode": "default"}],
            "audit_rows": [{"field": "wacc"}],
        },
    )
    monkeypatch.setattr(
        "api.main.build_valuation_wacc_payload",
        lambda ticker: {
            "ticker": ticker,
            "available": True,
            "methods": [{"method": "peer_bottom_up"}],
            "current_selection": {"mode": "single_method", "selected_method": "peer_bottom_up", "weights": {}},
        },
    )
    monkeypatch.setattr(
        "api.main.build_valuation_recommendations_payload",
        lambda ticker: {"ticker": ticker, "available": True, "recommendations": [{"field": "wacc"}]},
    )

    client = TestClient(app)

    overview = client.get("/api/tickers/IBM/overview")
    summary = client.get("/api/tickers/IBM/valuation/summary")
    dcf = client.get("/api/tickers/IBM/valuation/dcf")
    comps = client.get("/api/tickers/IBM/valuation/comps")
    assumptions = client.get("/api/tickers/IBM/valuation/assumptions")
    wacc = client.get("/api/tickers/IBM/valuation/wacc")
    recommendations = client.get("/api/tickers/IBM/valuation/recommendations")

    assert overview.status_code == 200
    assert overview.json()["tracker"]["available"] is True
    assert summary.status_code == 200
    assert summary.json()["weighted_iv"] == 123.0
    assert dcf.status_code == 200
    assert dcf.json()["scenario_summary"][0]["scenario"] == "base"
    assert comps.status_code == 200
    assert comps.json()["peer_counts"]["raw"] == 8
    assert assumptions.status_code == 200
    assert assumptions.json()["fields"][0]["field"] == "wacc"
    assert wacc.status_code == 200
    assert wacc.json()["methods"][0]["method"] == "peer_bottom_up"
    assert recommendations.status_code == 200
    assert recommendations.json()["recommendations"][0]["field"] == "wacc"


def test_valuation_assumptions_helper_separates_audit_families(monkeypatch):
    from api.extracted import build_valuation_assumptions_payload

    monkeypatch.setattr(
        "api.extracted.build_override_workbench",
        lambda ticker: {
            "ticker": ticker,
            "available": True,
            "fields": [],
            "assumption_register": {"ticker": ticker, "entries": []},
        },
    )
    monkeypatch.setattr(
        "src.stage_04_pipeline.override_workbench.load_override_audit_history",
        lambda ticker, limit=50: [{"field": "wacc"}],
    )
    monkeypatch.setattr(
        "src.stage_04_pipeline.override_workbench.load_assumption_register_audit_history",
        lambda ticker, limit=50: [{"assumption_name": "wacc"}],
    )

    payload = build_valuation_assumptions_payload("ibm")

    assert payload["ticker"] == "IBM"
    assert payload["override_audit_rows"] == [{"field": "wacc"}]
    assert payload["audit_rows"] == payload["override_audit_rows"]
    assert payload["assumption_register_audit_rows"] == [{"assumption_name": "wacc"}]


def test_ticker_dossier_endpoint_exposes_canonical_contract(monkeypatch):
    from api.main import app

    monkeypatch.setattr(
        "api.main.build_ticker_dossier_payload",
        lambda ticker, source_mode=None: {
            "contract_name": "TickerDossier",
            "contract_version": "1.0.0",
            "ticker": ticker,
            "as_of_date": "2026-04-30T00:00:00+00:00",
            "display_name": "International Business Machines",
            "currency": "USD",
            "latest_snapshot": {
                "company_identity": {"ticker": ticker, "display_name": "International Business Machines"},
                "market_snapshot": {"as_of_date": "2026-04-30T00:00:00+00:00"},
                "valuation_snapshot": {"base_iv": 202.0},
            },
            "loaded_backend_state": {"source_mode": source_mode or "latest_snapshot"},
            "source_lineage": {},
            "export_metadata": {"source_mode": source_mode or "latest_snapshot"},
            "optional_overlays": {},
        },
    )

    client = TestClient(app)
    response = client.get("/api/tickers/IBM/dossier?source_mode=loaded_backend_state")

    assert response.status_code == 200
    payload = response.json()
    assert payload["contract_name"] == "TickerDossier"
    assert payload["contract_version"] == "1.0.0"
    assert payload["export_metadata"]["source_mode"] == "loaded_backend_state"


def test_ticker_dossier_payload_reads_persisted_latest_snapshot_before_builder(monkeypatch):
    from api.main import build_ticker_dossier_payload

    calls: list[tuple[str, str | None]] = []
    persisted = {
        "contract_name": "TickerDossier",
        "contract_version": "1.0.0",
        "ticker": "IBM",
        "as_of_date": "2026-04-30",
        "display_name": "International Business Machines",
        "export_metadata": {"source_mode": "latest_snapshot"},
    }

    def _load(ticker: str, source_mode: str | None = None):
        calls.append((ticker, source_mode))
        return persisted

    def _build(_ticker: str, _source_mode: str):  # pragma: no cover - should not be reached
        raise AssertionError("builder fallback should not run when persisted dossier exists")

    monkeypatch.setattr("src.stage_04_pipeline.workspace_views.load_latest_ticker_dossier_payload", _load)
    monkeypatch.setattr("src.stage_04_pipeline.workspace_views.build_ticker_dossier_from_source", _build)
    monkeypatch.setattr("api.main.load_latest_ticker_dossier_payload", _load)
    monkeypatch.setattr("api.main.build_ticker_dossier_from_source", _build)

    payload = build_ticker_dossier_payload("IBM")

    assert payload is persisted
    assert calls == [("IBM", "latest_snapshot")]


def test_ticker_dossier_payload_falls_back_from_snapshot_builder_to_backend_state(monkeypatch):
    from api.main import build_ticker_dossier_payload

    build_calls: list[tuple[str, str]] = []

    monkeypatch.setattr("src.stage_04_pipeline.workspace_views.load_latest_ticker_dossier_payload", lambda ticker, source_mode=None: None)
    monkeypatch.setattr("api.main.load_latest_ticker_dossier_payload", lambda ticker, source_mode=None: None)

    def _build(ticker: str, source_mode: str):
        build_calls.append((ticker, source_mode))
        if source_mode == "latest_snapshot":
            raise FileNotFoundError("no archived snapshot")
        return {
            "contract_name": "TickerDossier",
            "contract_version": "1.0.0",
            "ticker": ticker,
            "as_of_date": "2026-04-30",
            "display_name": "International Business Machines",
            "export_metadata": {"source_mode": source_mode},
        }

    monkeypatch.setattr("src.stage_04_pipeline.workspace_views.build_ticker_dossier_from_source", _build)
    monkeypatch.setattr("api.main.build_ticker_dossier_from_source", _build)

    payload = build_ticker_dossier_payload("IBM")

    assert payload["export_metadata"]["source_mode"] == "loaded_backend_state"
    assert build_calls == [("IBM", "latest_snapshot"), ("IBM", "loaded_backend_state")]


def test_ticker_api_consumers_prefer_canonical_dossier_facts_and_preserve_legacy_fields(monkeypatch):
    from api.main import build_overview_payload, build_ticker_workspace_payload, build_valuation_summary_payload

    dossier = _canonical_dossier_payload()
    build_calls: list[tuple[str, str | None]] = []

    def _build_dossier(ticker: str, source_mode: str | None = None) -> dict:
        build_calls.append((ticker, source_mode))
        return dossier

    _install_legacy_ticker_mocks(monkeypatch)
    monkeypatch.setattr("src.stage_04_pipeline.workspace_views.build_ticker_dossier_payload", _build_dossier)
    monkeypatch.setattr("api.main.build_ticker_dossier_payload", _build_dossier)

    workspace = build_ticker_workspace_payload("ibm")
    overview = build_overview_payload("ibm")
    summary = build_valuation_summary_payload("ibm")

    assert workspace["company_name"] == "Canonical Machines"
    assert workspace["sector"] == "Canonical Sector"
    assert workspace["current_price"] == 111.0
    assert workspace["base_iv"] == 155.0
    assert workspace["bear_iv"] == 120.0
    assert workspace["bull_iv"] == 210.0
    assert workspace["weighted_iv"] == 166.0
    assert workspace["upside_pct_base"] == 0.35
    assert workspace["analyst_target"] == 222.0
    assert workspace["latest_snapshot_date"] == "2026-04-30"
    assert workspace["snapshot_id"] == 44
    assert workspace["action"] == "REVIEW"
    assert workspace["conviction"] == "medium"
    assert workspace["ticker_dossier"] is dossier
    assert workspace["ticker_dossier_contract_version"] == "1.0.0"

    assert overview["company_name"] == "Canonical Machines"
    assert overview["one_liner"] == "Legacy one-liner."
    assert overview["variant_thesis_prompt"] == "Legacy thesis prompt."
    assert overview["market_pulse"] == "Legacy market pulse."
    assert overview["thesis_changes"] == ["Legacy tracker line"]
    assert overview["next_catalyst"] == "Legacy catalyst"
    assert overview["valuation_pulse"] == "Base IV $155.00 versus current price $111.00."
    assert overview["workspace"]["company_name"] == "Canonical Machines"
    assert overview["ticker_dossier"] is dossier

    assert summary["current_price"] == 111.0
    assert summary["base_iv"] == 155.0
    assert summary["weighted_iv"] == 166.0
    assert summary["upside_pct_base"] == 35.0
    assert summary["analyst_target"] == 222.0
    assert summary["memo_date"] == "2026-04-30"
    assert summary["why_it_matters"] == "Base IV $155.00 versus current price $111.00."
    assert summary["conviction"] == "medium"
    assert summary["readiness"] == {"tv_high_flag": False, "revenue_data_quality_flag": "legacy"}
    assert summary["summary"]["scenario_summary"][0]["intrinsic_value"] == 25.0
    assert summary["ticker_dossier"] is dossier

    assert build_calls == [("IBM", None), ("IBM", None), ("IBM", None)]


def test_ticker_api_consumers_fall_back_to_legacy_payloads_when_dossier_fails(monkeypatch):
    from api.main import build_ticker_workspace_payload

    _install_legacy_ticker_mocks(monkeypatch)
    monkeypatch.setattr("src.stage_04_pipeline.workspace_views.build_ticker_dossier_payload", lambda ticker, source_mode=None: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr("api.main.build_ticker_dossier_payload", lambda ticker, source_mode=None: (_ for _ in ()).throw(RuntimeError("boom")))

    payload = build_ticker_workspace_payload("IBM")

    assert payload["company_name"] == "Legacy Snapshot"
    assert payload["sector"] == "Legacy Snapshot Sector"
    assert payload["current_price"] == 12.0
    assert payload["base_iv"] == 24.0
    assert payload["action"] == "REVIEW"
    assert payload["conviction"] == "medium"
    assert "ticker_dossier" not in payload


def test_market_research_audit_and_valuation_action_endpoints_return_existing_helpers(monkeypatch):
    from api.main import app

    monkeypatch.setattr(
        "api.main.build_market_payload",
        lambda ticker: {
            "ticker": ticker,
            "analyst_snapshot": {"recommendation": "hold"},
            "historical_brief": {"summary": "Historical brief", "event_timeline": [{"summary": "Event"}]},
            "quarterly_headlines": [{"title": "Headline"}],
            "revisions": {"revision_momentum": "positive"},
            "macro": {"regime": {"label": "Neutral"}, "scenario_weights": {"base": 0.6}, "yield_curve": {"maturities": [["2Y", 2, 4.1]]}},
            "sentiment_summary": {"direction": "bearish", "key_bullish_themes": [], "key_bearish_themes": []},
            "factor_exposure": {"available": True, "market_beta": 0.8},
            "audit_flags": ["Limited historical brief uses limited local evidence"],
        },
    )
    monkeypatch.setattr("api.main.build_research_payload", lambda ticker: {"ticker": ticker, "tracker": {"available": True}})
    monkeypatch.setattr("api.main.build_audit_payload", lambda ticker: {"ticker": ticker, "available": True, "audit_flags": []})
    monkeypatch.setattr(
        "api.main.apply_override_selections",
        lambda ticker, selections, custom_values, actor="api": {
            "ticker": ticker,
            "actor": actor,
            "selections": selections,
            "custom_values": custom_values,
        },
    )
    monkeypatch.setattr(
        "api.main.preview_override_selections",
        lambda ticker, selections, custom_values: {
            "ticker": ticker,
            "current_iv": {"base": 100.0},
            "proposed_iv": {"base": 110.0},
            "selections": selections,
            "custom_values": custom_values,
        },
    )
    monkeypatch.setattr(
        "api.main.preview_wacc_methodology_selection",
        lambda ticker, mode, selected_method=None, weights=None: {
            "ticker": ticker,
            "selection": {"mode": mode, "selected_method": selected_method, "weights": weights or {}},
            "effective_wacc": 0.075,
            "current_wacc": 0.082,
        },
    )
    monkeypatch.setattr(
        "api.main.apply_wacc_methodology_selection",
        lambda ticker, mode, selected_method=None, weights=None, actor="api": {
            "ticker": ticker,
            "selection": {"mode": mode, "selected_method": selected_method, "weights": weights or {}},
            "effective_wacc": 0.074,
        },
    )
    monkeypatch.setattr(
        "api.main.preview_recommendations_with_approvals",
        lambda ticker, approved_fields: {
            "ticker": ticker,
            "current_iv": {"base": 100.0},
            "proposed_iv": {"base": 108.0},
            "approved_fields": approved_fields,
        },
    )
    monkeypatch.setattr(
        "api.main.apply_recommendations_to_overrides",
        lambda ticker, approved_fields=None, actor="api": {
            "ticker": ticker,
            "applied_count": len(approved_fields or []),
            "approved_fields": approved_fields or [],
            "actor": actor,
        },
    )

    client = TestClient(app)

    market = client.get("/api/tickers/IBM/market")
    research = client.get("/api/tickers/IBM/research")
    audit = client.get("/api/tickers/IBM/audit")
    assumptions_preview = client.post(
        "/api/tickers/IBM/valuation/assumptions/preview",
        json={"selections": {"wacc": "agent"}, "custom_values": {"wacc": 0.12}},
    )
    apply_response = client.post(
        "/api/tickers/IBM/valuation/assumptions/apply",
        json={"selections": {"wacc": "agent"}, "custom_values": {"wacc": 0.12}},
    )
    wacc_preview = client.post(
        "/api/tickers/IBM/valuation/wacc/preview",
        json={"mode": "single_method", "selected_method": "peer_bottom_up"},
    )
    wacc_apply = client.post(
        "/api/tickers/IBM/valuation/wacc/apply",
        json={"mode": "single_method", "selected_method": "peer_bottom_up"},
    )
    recommendations_preview = client.post(
        "/api/tickers/IBM/valuation/recommendations/preview",
        json={"approved_fields": ["wacc"]},
    )
    recommendations_apply = client.post(
        "/api/tickers/IBM/valuation/recommendations/apply",
        json={"approved_fields": ["wacc"]},
    )

    assert market.status_code == 200
    market_payload = market.json()
    assert market_payload["analyst_snapshot"]["recommendation"] == "hold"
    assert market_payload["historical_brief"]["event_timeline"][0]["summary"] == "Event"
    assert market_payload["revisions"]["revision_momentum"] == "positive"
    assert market_payload["macro"]["regime"]["label"] == "Neutral"
    assert market_payload["factor_exposure"]["market_beta"] == 0.8
    assert market_payload["audit_flags"][0] == "Limited historical brief uses limited local evidence"
    assert research.status_code == 200
    assert research.json()["tracker"]["available"] is True
    assert audit.status_code == 200
    assert audit.json()["available"] is True
    assert assumptions_preview.status_code == 200
    assert assumptions_preview.json()["proposed_iv"]["base"] == 110.0
    assert apply_response.status_code == 202
    assert wacc_preview.status_code == 200
    assert wacc_preview.json()["selection"]["selected_method"] == "peer_bottom_up"
    assert wacc_apply.status_code == 202
    assert recommendations_preview.status_code == 200
    assert recommendations_preview.json()["proposed_iv"]["base"] == 108.0
    assert recommendations_apply.status_code == 202

    run_id = apply_response.json()["run_id"]
    assert run_id
    for _ in range(20):
        status = client.get(f"/api/runs/{run_id}")
        assert status.status_code == 200
        payload = status.json()
        if payload["status"] == "completed":
            assert payload["result"]["ticker"] == "IBM"
            assert payload["result"]["selections"]["wacc"] == "agent"
            break
        time.sleep(0.01)
    else:  # pragma: no cover - diagnostic guard
        raise AssertionError("assumptions apply never completed")

    wacc_run_id = wacc_apply.json()["run_id"]
    for _ in range(20):
        status = client.get(f"/api/runs/{wacc_run_id}")
        assert status.status_code == 200
        payload = status.json()
        if payload["status"] == "completed":
            assert payload["result"]["ticker"] == "IBM"
            assert payload["result"]["selection"]["selected_method"] == "peer_bottom_up"
            break
        time.sleep(0.01)
    else:  # pragma: no cover - diagnostic guard
        raise AssertionError("wacc apply never completed")

    recommendations_run_id = recommendations_apply.json()["run_id"]
    for _ in range(20):
        status = client.get(f"/api/runs/{recommendations_run_id}")
        assert status.status_code == 200
        payload = status.json()
        if payload["status"] == "completed":
            assert payload["result"]["ticker"] == "IBM"
            assert payload["result"]["applied_count"] == 1
            assert payload["result"]["approved_fields"] == ["wacc"]
            break
        time.sleep(0.01)
    else:  # pragma: no cover - diagnostic guard
        raise AssertionError("recommendations apply never completed")


def test_preview_endpoints_normalize_empty_helper_payloads(monkeypatch):
    from api.main import app

    monkeypatch.setattr("api.main.preview_override_selections", lambda ticker, selections, custom_values: {})
    monkeypatch.setattr(
        "api.main.preview_wacc_methodology_selection",
        lambda ticker, mode, selected_method=None, weights=None: {},
    )
    monkeypatch.setattr("api.main.preview_recommendations_with_approvals", lambda ticker, approved_fields: {})

    client = TestClient(app)

    assumptions_preview = client.post("/api/tickers/IBM/valuation/assumptions/preview", json={})
    wacc_preview = client.post("/api/tickers/IBM/valuation/wacc/preview", json={})
    recommendations_preview = client.post("/api/tickers/IBM/valuation/recommendations/preview", json={})

    assert assumptions_preview.status_code == 200
    assert assumptions_preview.json() == {
        "ticker": "IBM",
        "resolved_values": {},
        "current_iv": {},
        "proposed_iv": {},
        "current_expected_iv": None,
        "proposed_expected_iv": None,
        "delta_pct": {},
    }
    assert wacc_preview.status_code == 200
    assert wacc_preview.json() == {
        "ticker": "IBM",
        "selection": {"mode": "single_method", "selected_method": None, "weights": {}},
        "effective_wacc": None,
        "current_wacc": None,
        "current_iv": {},
        "proposed_iv": {},
        "current_expected_iv": None,
        "proposed_expected_iv": None,
        "method_result": None,
    }
    assert recommendations_preview.status_code == 200
    assert recommendations_preview.json() == {
        "ticker": "IBM",
        "current_iv": {},
        "proposed_iv": {},
        "delta_pct": {},
    }


def test_policy_and_pending_change_endpoints(monkeypatch):
    from api.main import app

    monkeypatch.setattr(
        "api.main.load_valuation_policy_payload",
        lambda: {
            "contract_version": "1.0.0",
            "policy_id": None,
            "created_at": "2026-01-01T00:00:00Z",
            "actor": "config_bootstrap",
            "global_defaults": {"risk_free_rate": 0.045, "equity_risk_premium": 0.05},
            "sector_defaults": {},
            "source_ref": "config/config.yaml",
            "notes": None,
        },
    )
    monkeypatch.setattr(
        "api.main.preview_valuation_policy_payload",
        lambda payload: {
            "current_policy": {"global_defaults": {"risk_free_rate": 0.045, "equity_risk_premium": 0.05}},
            "proposed_policy": {"global_defaults": {"risk_free_rate": 0.039, "equity_risk_premium": 0.05}},
            "changed_fields": {"global_defaults.risk_free_rate": {"prior": 0.045, "new": 0.039}},
        },
    )
    monkeypatch.setattr("api.main.save_valuation_policy_payload", lambda payload, actor="api": {"policy_id": 7, "actor": actor})
    monkeypatch.setattr(
        "api.main.parse_damodaran_policy_drafts_payload",
        lambda: {"parsed_count": 1, "drafts": [{"field": "equity_risk_premium", "value": 0.052}], "rejected_files": []},
    )
    monkeypatch.setattr(
        "api.main.list_pending_assumptions_payload",
        lambda ticker: {"ticker": ticker, "pending_changes": [{"change_id": 1, "assumption_name": "wacc"}]},
    )
    monkeypatch.setattr(
        "api.main.preview_pending_assumptions_payload",
        lambda ticker, change_ids, manual_values=None: {
            "ticker": ticker,
            "selected_change_ids": change_ids,
            "proposed_iv": {"base": 108.0},
            "conflicts": [],
        },
    )
    monkeypatch.setattr(
        "api.main.apply_pending_assumptions_payload",
        lambda ticker, change_ids, actor="api": {"ticker": ticker, "applied_count": len(change_ids), "actor": actor},
    )

    client = TestClient(app)

    policy = client.get("/api/valuation/policy")
    policy_preview = client.post("/api/valuation/policy/preview", json={"global_defaults": {"risk_free_rate": 0.039}})
    policy_save = client.put("/api/valuation/policy", json={"global_defaults": {"risk_free_rate": 0.039}})
    damodaran = client.post("/api/valuation/policy/damodaran/parse")
    pending = client.get("/api/tickers/IBM/valuation/pending-changes")
    pending_preview = client.post("/api/tickers/IBM/valuation/pending-changes/preview", json={"change_ids": [1]})
    pending_apply = client.post("/api/tickers/IBM/valuation/pending-changes/apply", json={"change_ids": [1]})

    assert policy.status_code == 200
    assert policy.json()["global_defaults"]["risk_free_rate"] == 0.045
    assert policy_preview.status_code == 200
    assert policy_preview.json()["changed_fields"]["global_defaults.risk_free_rate"]["new"] == 0.039
    assert policy_save.status_code == 200
    assert policy_save.json()["policy_id"] == 7
    assert damodaran.status_code == 200
    assert damodaran.json()["parsed_count"] == 1
    assert pending.status_code == 200
    assert pending.json()["pending_changes"][0]["change_id"] == 1
    assert pending_preview.status_code == 200
    assert pending_preview.json()["proposed_iv"]["base"] == 108.0
    assert pending_apply.status_code == 202
    run_id = pending_apply.json()["run_id"]
    for _ in range(20):
        status = client.get(f"/api/runs/{run_id}")
        assert status.status_code == 200
        payload = status.json()
        if payload["status"] == "completed":
            assert payload["result"]["applied_count"] == 1
            break
        time.sleep(0.01)
    else:  # pragma: no cover
        raise AssertionError("pending apply never completed")


def test_analysis_run_returns_run_id_and_completion_status(monkeypatch):
    from api.main import app

    def _fake_run_deep_analysis_for_tickers(tickers, **kwargs):
        return [{"ticker": tickers[0], "status": "ok", "snapshot_id": 99, "run_trace_steps": 4}]

    monkeypatch.setattr("api.main.run_deep_analysis_for_tickers", _fake_run_deep_analysis_for_tickers)

    client = TestClient(app)
    response = client.post("/api/tickers/IBM/analysis/run", json={"use_cache": False})

    assert response.status_code == 202
    run_id = response.json()["run_id"]
    assert run_id

    for _ in range(20):
        status = client.get(f"/api/runs/{run_id}")
        assert status.status_code == 200
        payload = status.json()
        if payload["status"] == "completed":
            assert payload["result"][0]["status"] == "ok"
            assert payload["progress"] == 1.0
            break
        time.sleep(0.01)
    else:  # pragma: no cover - diagnostic guard
        raise AssertionError("analysis run never completed")


def test_agentic_handoff_endpoints(monkeypatch):
    from api.main import app

    monkeypatch.setattr(
        "api.main.run_agentic_handoff_profile_payload",
        lambda ticker, profile_name: {
            "ticker": ticker,
            "profile_name": profile_name,
            "evidence_packet": {"packet_id": 1},
            "observation_count": 2,
            "queue_item_count": 1,
            "queue_item_ids": [11],
        },
    )
    monkeypatch.setattr(
        "api.main.list_evidence_packets_payload",
        lambda ticker: {"ticker": ticker, "evidence_packets": [{"packet_id": 1, "packet_kind": "earnings_update"}]},
    )
    monkeypatch.setattr(
        "api.main.list_pm_decision_queue_payload",
        lambda ticker, **kwargs: {"ticker": ticker, "items": [{"item_id": 11, "status": "pending"}], "filters": kwargs},
    )
    monkeypatch.setattr(
        "api.main.preview_pm_decision_queue_payload",
        lambda ticker, item_id: {"item": {"item_id": item_id}, "preview": {"proposed_iv": {"base": 110.0}}},
    )
    monkeypatch.setattr(
        "api.main.edit_pm_decision_queue_payload",
        lambda ticker, item_id, proposal_pack, actor="api": {"item_id": item_id, "status": "pending", "pm_edited_proposal_pack": proposal_pack},
    )
    monkeypatch.setattr(
        "api.main.approve_pm_decision_queue_payload",
        lambda ticker, item_id, actor="api": {"item_id": item_id, "status": "approved"},
    )
    monkeypatch.setattr(
        "api.main.reject_pm_decision_queue_payload",
        lambda ticker, item_id, actor="api", reason=None: {"item_id": item_id, "status": "rejected", "reason": reason},
    )
    monkeypatch.setattr(
        "api.main.defer_pm_decision_queue_payload",
        lambda ticker, item_id, actor="api", reason=None: {"item_id": item_id, "status": "deferred", "reason": reason},
    )

    client = TestClient(app)

    run_response = client.post("/api/tickers/IBM/agentic-handoff/earnings_update/run")
    packets_response = client.get("/api/tickers/IBM/evidence-packets")
    queue_response = client.get("/api/tickers/IBM/pm-decision-queue?status=pending")
    preview_response = client.post("/api/tickers/IBM/pm-decision-queue/11/preview")
    edit_response = client.post(
        "/api/tickers/IBM/pm-decision-queue/11/edit",
        json={"proposal_pack": {"pack_id": "pack:edit", "proposals": []}},
    )
    approve_response = client.post("/api/tickers/IBM/pm-decision-queue/11/approve")
    reject_response = client.post("/api/tickers/IBM/pm-decision-queue/11/reject", json={"reason": "not enough evidence"})
    defer_response = client.post("/api/tickers/IBM/pm-decision-queue/11/defer", json={"reason": "wait for next quarter"})

    assert run_response.status_code == 200
    assert run_response.json()["queue_item_ids"] == [11]
    assert packets_response.status_code == 200
    assert packets_response.json()["evidence_packets"][0]["packet_kind"] == "earnings_update"
    assert queue_response.status_code == 200
    assert queue_response.json()["items"][0]["status"] == "pending"
    assert preview_response.status_code == 200
    assert preview_response.json()["preview"]["proposed_iv"]["base"] == 110.0
    assert edit_response.status_code == 200
    assert edit_response.json()["pm_edited_proposal_pack"]["pack_id"] == "pack:edit"
    assert approve_response.status_code == 200
    assert approve_response.json()["status"] == "approved"
    assert reject_response.status_code == 200
    assert reject_response.json()["reason"] == "not enough evidence"
    assert defer_response.status_code == 200
    assert defer_response.json()["reason"] == "wait for next quarter"


def test_open_latest_snapshot_returns_latest_payload(monkeypatch):
    from api.main import app

    monkeypatch.setattr(
        "api.main.load_latest_snapshot_for_ticker",
        lambda ticker: {"id": 42, "ticker": ticker, "memo": {"ticker": ticker}},
    )

    client = TestClient(app)
    response = client.post("/api/tickers/IBM/snapshot/open-latest")

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == 42
    assert payload["ticker"] == "IBM"


def test_analysis_run_accepts_empty_body_for_frontend_trigger(monkeypatch):
    from api.main import app

    monkeypatch.setattr(
        "api.main.run_deep_analysis_for_tickers",
        lambda tickers, **kwargs: [{"ticker": tickers[0], "status": "ok", "kwargs": kwargs}],
    )

    client = TestClient(app)
    response = client.post("/api/tickers/IBM/analysis/run")

    assert response.status_code == 202
    assert response.json()["ticker"] == "IBM"


def _workspace_tempdir(name: str) -> Path:
    path = Path(tempfile.mkdtemp(prefix=f"{name}-"))
    return path


def test_ticker_export_endpoints_create_list_and_download_exports(monkeypatch):
    from api.main import app

    tmp_path = _workspace_tempdir("api-export")
    artifact_path = tmp_path / "ibm-memo.html"
    artifact_path.write_text("<html>memo</html>", encoding="utf-8")

    def _fake_run_ticker_export(*, ticker, export_format, source_mode, template_strategy, created_by):
        assert ticker == "IBM"
        assert export_format == "html"
        assert source_mode == "latest_snapshot"
        assert template_strategy is None
        assert created_by == "api"
        return {
            "export_id": "exp-1",
            "ticker": ticker,
            "scope": "ticker",
            "status": "completed",
            "export_format": export_format,
            "source_mode": source_mode,
            "primary_artifact_key": "html_report",
        }

    monkeypatch.setattr("api.main.run_ticker_export", _fake_run_ticker_export)
    monkeypatch.setattr("api.main.load_latest_snapshot_for_ticker", lambda ticker: {"ticker": ticker, "id": 7})
    monkeypatch.setattr(
        "api.main.list_saved_exports",
        lambda ticker=None, scope=None, limit=25: [
            {
                "export_id": "exp-1",
                "ticker": ticker,
                "scope": "ticker",
                "status": "completed",
                "export_format": "html",
                "source_mode": "latest_snapshot",
                "artifacts": [{"artifact_key": "html_report", "title": "IBM Memo"}],
            }
        ],
    )
    monkeypatch.setattr(
        "api.main.load_saved_export",
        lambda export_id: {
            "export_id": export_id,
            "ticker": "IBM",
            "scope": "ticker",
            "status": "completed",
            "export_format": "html",
            "source_mode": "latest_snapshot",
            "artifacts": [{"artifact_key": "html_report", "title": "IBM Memo"}],
        },
    )
    monkeypatch.setattr("api.main.resolve_export_download_path", lambda export_id, artifact_key=None: artifact_path)

    client = TestClient(app)
    create_response = client.post("/api/tickers/IBM/exports", json={"format": "html", "source_mode": "latest_snapshot"})
    list_response = client.get("/api/tickers/IBM/exports")
    detail_response = client.get("/api/exports/exp-1")
    download_response = client.get("/api/exports/exp-1/download")

    assert create_response.status_code == 202
    run_id = create_response.json()["run_id"]
    assert run_id

    for _ in range(20):
        status = client.get(f"/api/runs/{run_id}")
        assert status.status_code == 200
        payload = status.json()
        if payload["status"] == "completed":
            assert payload["result"]["export_id"] == "exp-1"
            break
        time.sleep(0.01)
    else:  # pragma: no cover - diagnostic guard
        raise AssertionError("ticker export never completed")

    assert list_response.status_code == 200
    assert list_response.json()["exports"][0]["export_id"] == "exp-1"
    assert detail_response.status_code == 200
    assert detail_response.json()["export_id"] == "exp-1"
    assert download_response.status_code == 200
    assert "text/html" in download_response.headers["content-type"]


def test_watchlist_export_endpoints_create_and_list_batch_exports(monkeypatch):
    from api.main import app

    monkeypatch.setattr(
        "api.main.run_watchlist_export",
        lambda *, export_format, source_mode, shortlist_size, created_by: {
            "export_id": "batch-1",
            "scope": "batch",
            "status": "completed",
            "export_format": export_format,
            "source_mode": source_mode,
            "shortlist_size": shortlist_size,
        },
    )
    monkeypatch.setattr(
        "api.main.list_saved_exports",
        lambda ticker=None, scope=None, limit=25: [
            {
                "export_id": "batch-1",
                "scope": scope,
                "status": "completed",
                "export_format": "xlsx",
                "source_mode": "saved_watchlist",
            }
        ],
    )

    client = TestClient(app)
    create_response = client.post("/api/watchlist/exports", json={"format": "xlsx", "source_mode": "saved_watchlist", "shortlist_size": 12})
    list_response = client.get("/api/watchlist/exports")

    assert create_response.status_code == 202
    run_id = create_response.json()["run_id"]
    assert run_id

    for _ in range(20):
        status = client.get(f"/api/runs/{run_id}")
        assert status.status_code == 200
        payload = status.json()
        if payload["status"] == "completed":
            assert payload["result"]["export_id"] == "batch-1"
            break
        time.sleep(0.01)
    else:  # pragma: no cover - diagnostic guard
        raise AssertionError("watchlist export never completed")

    assert list_response.status_code == 200
    assert list_response.json()["exports"][0]["export_id"] == "batch-1"
