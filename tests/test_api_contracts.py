from __future__ import annotations

import time
import uuid
from pathlib import Path

from fastapi.testclient import TestClient


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

    monkeypatch.setattr("api.main.load_latest_ticker_dossier_payload", _load)
    monkeypatch.setattr("api.main.build_ticker_dossier_from_source", _build)

    payload = build_ticker_dossier_payload("IBM")

    assert payload is persisted
    assert calls == [("IBM", "latest_snapshot")]


def test_ticker_dossier_payload_falls_back_from_snapshot_builder_to_backend_state(monkeypatch):
    from api.main import build_ticker_dossier_payload

    build_calls: list[tuple[str, str]] = []

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

    monkeypatch.setattr("api.main.build_ticker_dossier_from_source", _build)

    payload = build_ticker_dossier_payload("IBM")

    assert payload["export_metadata"]["source_mode"] == "loaded_backend_state"
    assert build_calls == [("IBM", "latest_snapshot"), ("IBM", "loaded_backend_state")]


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
    root = Path(".tmp-tests") / "api-contracts"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{name}-{uuid.uuid4().hex}"
    path.mkdir(parents=True, exist_ok=False)
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
