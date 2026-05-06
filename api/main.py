from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from api.run_tracker import submit_background_run, update_run, get_run
from src.utils import coerce_ticker
from src.stage_04_pipeline.workspace_views import (
    build_ticker_workspace_payload,
    build_overview_payload,
    build_valuation_summary_payload,
    build_valuation_dcf_payload,
    build_valuation_comps_payload,
    build_valuation_assumptions_payload,
    build_wacc_payload,
    build_valuation_recommendations_payload,
    build_market_payload,
    build_research_payload,
    build_audit_payload,
    build_ticker_dossier_payload,
    load_latest_ticker_dossier_payload,  # noqa: F401 — patched by tests
    _attach_api_ticker_dossier,
    _normalize_assumptions_preview_payload,
    _normalize_wacc_preview_payload,
    _normalize_recommendations_preview_payload,
)


class WatchlistRefreshRequest(BaseModel):
    tickers: list[str] | None = None
    shortlist_size: int = Field(default=10, ge=1, le=25)
    export_xlsx: bool = False


class AssumptionsApplyRequest(BaseModel):
    selections: dict[str, str] = Field(default_factory=dict)
    custom_values: dict[str, float | None] = Field(default_factory=dict)


class WaccSelectionRequest(BaseModel):
    mode: str = "single_method"
    selected_method: str | None = None
    weights: dict[str, float] = Field(default_factory=dict)


class RecommendationsPreviewRequest(BaseModel):
    approved_fields: list[str] = Field(default_factory=list)


class RecommendationsApplyRequest(BaseModel):
    approved_fields: list[str] = Field(default_factory=list)


class AnalysisRunRequest(BaseModel):
    use_cache: bool = True
    force_refresh_agents: list[str] = Field(default_factory=list)


class TickerExportRequest(BaseModel):
    format: str = Field(default="html")
    source_mode: str = Field(default="latest_snapshot")
    template_strategy: str | None = None


class WatchlistExportRequest(BaseModel):
    format: str = Field(default="xlsx")
    source_mode: str = Field(default="saved_watchlist")
    shortlist_size: int = Field(default=10, ge=1, le=25)


def api_coerce_ticker(value: str) -> str:
    try:
        return coerce_ticker(value)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


def load_saved_watchlist(shortlist_size: int = 10) -> dict[str, Any]:
    from src.stage_04_pipeline.batch_funnel import load_saved_watchlist as _impl

    return _impl(shortlist_size=shortlist_size)


def run_deterministic_batch(**kwargs) -> dict[str, Any]:
    from src.stage_04_pipeline.batch_funnel import run_deterministic_batch as _impl

    return _impl(**kwargs)


def load_latest_snapshot_for_ticker(ticker: str) -> dict[str, Any] | None:
    from src.stage_04_pipeline.batch_funnel import load_latest_snapshot_for_ticker as _impl

    return _impl(ticker)


def run_deep_analysis_for_tickers(tickers, **kwargs) -> list[dict[str, Any]]:
    from src.stage_04_pipeline.batch_funnel import run_deep_analysis_for_tickers as _impl

    return _impl(tickers, **kwargs)


def run_ticker_export(
    *,
    ticker: str,
    export_format: str,
    source_mode: str,
    template_strategy: str | None = None,
    created_by: str = "api",
) -> dict[str, Any]:
    from src.stage_04_pipeline.export_service import run_ticker_export as _impl

    return _impl(
        ticker=ticker,
        export_format=export_format,
        source_mode=source_mode,
        template_strategy=template_strategy,
        created_by=created_by,
    )


def run_watchlist_export(
    *,
    export_format: str,
    source_mode: str,
    shortlist_size: int = 10,
    created_by: str = "api",
) -> dict[str, Any]:
    from src.stage_04_pipeline.export_service import run_watchlist_export as _impl

    return _impl(
        export_format=export_format,
        source_mode=source_mode,
        shortlist_size=shortlist_size,
        created_by=created_by,
    )





def list_saved_exports(*, ticker: str | None = None, scope: str | None = None, limit: int = 25) -> list[dict[str, Any]]:
    from src.stage_04_pipeline.export_service import list_saved_exports as _impl

    return _impl(ticker=ticker, scope=scope, limit=limit)


def load_saved_export(export_id: str) -> dict[str, Any] | None:
    from src.stage_04_pipeline.export_service import load_saved_export as _impl

    return _impl(export_id)


def resolve_export_download_path(export_id: str, artifact_key: str | None = None):
    from src.stage_04_pipeline.export_service import resolve_export_download_path as _impl

    return _impl(export_id, artifact_key=artifact_key)


def get_market_data(ticker: str, use_cache: bool = True) -> dict[str, Any]:
    from src.stage_00_data.market_data import get_market_data as _impl

    return _impl(ticker, use_cache=use_cache)


def get_analyst_ratings(ticker: str) -> dict[str, Any]:
    from src.stage_00_data.market_data import get_analyst_ratings as _impl

    return _impl(ticker)


def get_revision_signals(ticker: str) -> Any:
    from src.stage_00_data.estimate_tracker import get_revision_signals as _impl

    return _impl(ticker)


def get_macro_snapshot(lookback_days: int = 5) -> dict[str, Any]:
    from src.stage_00_data.fred_client import get_macro_snapshot as _impl

    return _impl(lookback_days=lookback_days)


def get_yield_curve() -> dict[str, Any]:
    from src.stage_00_data.fred_client import get_yield_curve as _impl

    return _impl()


def detect_current_regime() -> Any:
    from src.stage_02_valuation.regime_model import detect_current_regime as _impl

    return _impl()


def get_scenario_weights(regime: Any | None = None) -> Any:
    from src.stage_02_valuation.regime_model import get_scenario_weights as _impl

    return _impl(regime)


def decompose_factor_exposure(ticker: str) -> Any:
    from src.stage_02_valuation.factor_model import decompose_factor_exposure as _impl

    return _impl(ticker)


def get_factor_summary_text(exposure: Any) -> str:
    from src.stage_02_valuation.factor_model import get_factor_summary_text as _impl

    return _impl(exposure)


def build_dcf_audit_view(ticker: str) -> dict[str, Any]:
    from src.stage_04_pipeline.dcf_audit import build_dcf_audit_view as _impl

    return _impl(ticker)


def build_comps_dashboard_view(ticker: str) -> dict[str, Any]:
    from src.stage_04_pipeline.comps_dashboard import build_comps_dashboard_view as _impl

    return _impl(ticker)


def build_filings_browser_view(ticker: str) -> dict[str, Any]:
    from src.stage_04_pipeline.filings_browser import build_filings_browser_view as _impl

    return _impl(ticker)


def build_news_materiality_view(ticker: str) -> dict[str, Any]:
    from src.stage_04_pipeline.news_materiality import build_news_materiality_view as _impl

    return _impl(ticker)


def build_override_workbench(ticker: str) -> dict[str, Any]:
    from src.stage_04_pipeline.override_workbench import build_override_workbench as _impl

    return _impl(ticker)


def apply_override_selections(
    ticker: str,
    selections: dict[str, str],
    custom_values: dict[str, float | None] | None = None,
    actor: str = "api",
) -> dict[str, Any]:
    from src.stage_04_pipeline.override_workbench import apply_override_selections as _impl

    return _impl(ticker, selections=selections, custom_values=custom_values or {}, actor=actor)


def preview_override_selections(
    ticker: str,
    selections: dict[str, str],
    custom_values: dict[str, float | None] | None = None,
) -> dict[str, Any]:
    from src.stage_04_pipeline.override_workbench import preview_override_selections as _impl

    return _impl(ticker, selections=selections, custom_values=custom_values or {})


def build_research_board_view(ticker: str) -> dict[str, Any]:
    from src.stage_04_pipeline.dossier_view import build_research_board_view as _impl

    return _impl(ticker)


def build_thesis_tracker_view(ticker: str) -> dict[str, Any]:
    from src.stage_04_pipeline.dossier_view import build_thesis_tracker_view as _impl

    return _impl(ticker)


def build_publishable_memo_context(ticker: str) -> dict[str, Any]:
    from src.stage_04_pipeline.dossier_view import build_publishable_memo_context as _impl

    return _impl(ticker)


def build_wacc_workbench(ticker: str, apply_overrides: bool = True) -> dict[str, Any]:
    from src.stage_04_pipeline.wacc_workbench import build_wacc_workbench as _impl

    return _impl(ticker, apply_overrides=apply_overrides)


def preview_wacc_methodology_selection(
    ticker: str,
    *,
    mode: str,
    selected_method: str | None = None,
    weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    from src.stage_04_pipeline.wacc_workbench import preview_wacc_methodology_selection as _impl

    return _impl(ticker, mode=mode, selected_method=selected_method, weights=weights)


def apply_wacc_methodology_selection(
    ticker: str,
    *,
    mode: str,
    selected_method: str | None = None,
    weights: dict[str, float] | None = None,
    actor: str = "api",
) -> dict[str, Any]:
    from src.stage_04_pipeline.wacc_workbench import apply_wacc_methodology_selection as _impl

    return _impl(ticker, mode=mode, selected_method=selected_method, weights=weights, actor=actor)


def load_wacc_methodology_audit_history(ticker: str, limit: int = 50) -> list[dict[str, Any]]:
    from src.stage_04_pipeline.wacc_workbench import load_wacc_methodology_audit_history as _impl

    return _impl(ticker, limit=limit)


def load_recommendations(ticker: str):
    from src.stage_04_pipeline.recommendations import load_recommendations as _impl

    return _impl(ticker)


def preview_recommendations_with_approvals(ticker: str, approved_fields: list[str]) -> dict[str, Any]:
    from src.stage_04_pipeline.recommendations import preview_with_approvals as _impl

    return _impl(ticker, approved_fields)


def apply_recommendations_to_overrides(
    ticker: str,
    approved_fields: list[str] | None = None,
    actor: str = "api",
) -> dict[str, Any]:
    from src.stage_04_pipeline.recommendations import apply_approved_to_overrides as _impl

    return _impl(ticker, approved_fields=approved_fields, actor=actor)


build_ticker_overview_payload = build_overview_payload


build_valuation_wacc_payload = build_wacc_payload


def create_app() -> FastAPI:
    @asynccontextmanager
    async def _lifespan(_app: FastAPI):
        from db.schema import create_tables, get_connection

        with get_connection() as conn:
            create_tables(conn)
        yield

    app = FastAPI(title="Alpha Pod API", version="0.1.0", lifespan=_lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:4173",
            "http://localhost:4173",
            "http://127.0.0.1:8000",
            "http://localhost:8000",
        ],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/watchlist")
    def get_watchlist(shortlist_size: int = 10) -> dict[str, Any]:
        return load_saved_watchlist(shortlist_size=shortlist_size)

    @app.post("/api/watchlist/refresh", status_code=202)
    def refresh_watchlist(payload: WatchlistRefreshRequest) -> dict[str, Any]:
        tickers = [api_coerce_ticker(value) for value in (payload.tickers or [])]

        def _runner(run_id: str) -> dict[str, Any]:
            def _on_progress(event: dict[str, Any]) -> None:
                total = max(int(event.get("total") or 0), 1)
                completed = min(int(event.get("completed") or 0), total)
                progress = completed / total
                message = event.get("ticker")
                status = event.get("status")
                update_run(
                    run_id,
                    status="running",
                    progress=progress,
                    message=f"{status}:{message}" if status and message else status,
                )

            return run_deterministic_batch(
                tickers=tickers or None,
                shortlist_size=payload.shortlist_size,
                export_xlsx=payload.export_xlsx,
                progress_callback=_on_progress,
            )

        run_id = submit_background_run(
            "watchlist_refresh",
            _runner,
            metadata={"shortlist_size": payload.shortlist_size, "ticker_count": len(tickers)},
        )
        return {"run_id": run_id, "status": "queued"}

    @app.get("/api/watchlist/exports")
    def get_watchlist_exports(limit: int = 25) -> dict[str, Any]:
        return {"exports": list_saved_exports(scope="batch", limit=limit)}

    @app.post("/api/watchlist/exports", status_code=202)
    def create_watchlist_export(payload: WatchlistExportRequest | None = None) -> dict[str, Any]:
        request_payload = payload or WatchlistExportRequest()

        def _runner(_run_id: str) -> dict[str, Any]:
            return run_watchlist_export(
                export_format=request_payload.format,
                source_mode=request_payload.source_mode,
                shortlist_size=request_payload.shortlist_size,
                created_by="api",
            )

        run_id = submit_background_run(
            "watchlist_export",
            _runner,
            metadata=request_payload.model_dump(),
        )
        return {"run_id": run_id, "status": "queued"}

    @app.get("/api/runs/{run_id}")
    def get_run_status(run_id: str) -> dict[str, Any]:
        run = get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        return run

    @app.get("/api/tickers/{ticker}/workspace")
    def get_ticker_workspace(ticker: str) -> dict[str, Any]:
        return build_ticker_workspace_payload(ticker)

    @app.get("/api/tickers/{ticker}/overview")
    def get_ticker_overview(ticker: str) -> dict[str, Any]:
        return build_ticker_overview_payload(ticker)

    @app.get("/api/tickers/{ticker}/dossier")
    def get_ticker_dossier(ticker: str, source_mode: str | None = None) -> dict[str, Any]:
        ticker = api_coerce_ticker(ticker)
        try:
            return build_ticker_dossier_payload(ticker, source_mode=source_mode)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/tickers/{ticker}/valuation/summary")
    def get_ticker_valuation_summary(ticker: str) -> dict[str, Any]:
        return build_valuation_summary_payload(ticker)

    @app.get("/api/tickers/{ticker}/valuation/dcf")
    def get_ticker_valuation_dcf(ticker: str) -> dict[str, Any]:
        return build_valuation_dcf_payload(ticker)

    @app.get("/api/tickers/{ticker}/valuation/comps")
    def get_ticker_valuation_comps(ticker: str) -> dict[str, Any]:
        return build_valuation_comps_payload(ticker)

    @app.get("/api/tickers/{ticker}/valuation/assumptions")
    def get_ticker_valuation_assumptions(ticker: str) -> dict[str, Any]:
        return build_valuation_assumptions_payload(ticker)

    @app.post("/api/tickers/{ticker}/valuation/assumptions/preview")
    def preview_ticker_valuation_assumptions(
        ticker: str,
        payload: AssumptionsApplyRequest | None = None,
    ) -> dict[str, Any]:
        ticker = api_coerce_ticker(ticker)
        selections = (payload.selections if payload else {})
        custom_values = (payload.custom_values if payload else {})
        preview = preview_override_selections(
            ticker,
            selections=selections,
            custom_values=custom_values,
        )
        return _normalize_assumptions_preview_payload(ticker, preview)

    @app.post("/api/tickers/{ticker}/valuation/assumptions/apply", status_code=202)
    def apply_ticker_valuation_assumptions(
        ticker: str,
        payload: AssumptionsApplyRequest | None = None,
    ) -> dict[str, Any]:
        ticker = api_coerce_ticker(ticker)
        selections = (payload.selections if payload else {})
        custom_values = (payload.custom_values if payload else {})

        def _runner(_run_id: str) -> dict[str, Any]:
            return apply_override_selections(
                ticker,
                selections=selections,
                custom_values=custom_values,
                actor="api",
            )

        run_id = submit_background_run("valuation_assumptions_apply", _runner, ticker=ticker)
        return {"run_id": run_id, "status": "queued"}

    @app.get("/api/tickers/{ticker}/valuation/wacc")
    def get_ticker_wacc(ticker: str) -> dict[str, Any]:
        return build_valuation_wacc_payload(ticker)

    @app.post("/api/tickers/{ticker}/valuation/wacc/preview")
    def preview_ticker_wacc(
        ticker: str,
        payload: WaccSelectionRequest | None = None,
    ) -> dict[str, Any]:
        ticker = api_coerce_ticker(ticker)
        request_payload = payload or WaccSelectionRequest()
        preview = preview_wacc_methodology_selection(
            ticker,
            mode=request_payload.mode,
            selected_method=request_payload.selected_method,
            weights=request_payload.weights,
        )
        return _normalize_wacc_preview_payload(ticker, preview, request_payload)

    @app.post("/api/tickers/{ticker}/valuation/wacc/apply", status_code=202)
    def apply_ticker_wacc(
        ticker: str,
        payload: WaccSelectionRequest | None = None,
    ) -> dict[str, Any]:
        ticker = api_coerce_ticker(ticker)
        request_payload = payload or WaccSelectionRequest()

        def _runner(_run_id: str) -> dict[str, Any]:
            return apply_wacc_methodology_selection(
                ticker,
                mode=request_payload.mode,
                selected_method=request_payload.selected_method,
                weights=request_payload.weights,
                actor="api",
            )

        run_id = submit_background_run("valuation_wacc_apply", _runner, ticker=ticker)
        return {"run_id": run_id, "status": "queued"}

    @app.get("/api/tickers/{ticker}/valuation/recommendations")
    def get_ticker_valuation_recommendations(ticker: str) -> dict[str, Any]:
        return build_valuation_recommendations_payload(ticker)

    @app.post("/api/tickers/{ticker}/valuation/recommendations/preview")
    def preview_ticker_valuation_recommendations(
        ticker: str,
        payload: RecommendationsPreviewRequest | None = None,
    ) -> dict[str, Any]:
        ticker = api_coerce_ticker(ticker)
        request_payload = payload or RecommendationsPreviewRequest()
        preview = preview_recommendations_with_approvals(ticker, request_payload.approved_fields)
        return _normalize_recommendations_preview_payload(ticker, preview)

    @app.post("/api/tickers/{ticker}/valuation/recommendations/apply", status_code=202)
    def apply_ticker_valuation_recommendations(
        ticker: str,
        payload: RecommendationsApplyRequest | None = None,
    ) -> dict[str, Any]:
        ticker = api_coerce_ticker(ticker)
        request_payload = payload or RecommendationsApplyRequest()

        def _runner(_run_id: str) -> dict[str, Any]:
            return apply_recommendations_to_overrides(
                ticker,
                approved_fields=request_payload.approved_fields,
                actor="api",
            )

        run_id = submit_background_run("valuation_recommendations_apply", _runner, ticker=ticker)
        return {"run_id": run_id, "status": "queued"}

    @app.get("/api/tickers/{ticker}/market")
    def get_ticker_market(ticker: str) -> dict[str, Any]:
        return build_market_payload(ticker)

    @app.get("/api/tickers/{ticker}/research")
    def get_ticker_research(ticker: str) -> dict[str, Any]:
        return build_research_payload(ticker)

    @app.get("/api/tickers/{ticker}/audit")
    def get_ticker_audit(ticker: str) -> dict[str, Any]:
        return build_audit_payload(ticker)

    @app.get("/api/tickers/{ticker}/exports")
    def get_ticker_exports(ticker: str, limit: int = 25) -> dict[str, Any]:
        ticker = api_coerce_ticker(ticker)
        return {"exports": list_saved_exports(ticker=ticker, scope="ticker", limit=limit)}

    @app.post("/api/tickers/{ticker}/exports", status_code=202)
    def create_ticker_export(ticker: str, payload: TickerExportRequest | None = None) -> dict[str, Any]:
        ticker = api_coerce_ticker(ticker)
        request_payload = payload or TickerExportRequest()
        if request_payload.source_mode == "latest_snapshot" and load_latest_snapshot_for_ticker(ticker) is None:
            raise HTTPException(status_code=409, detail="no archived snapshot found for export")

        def _runner(_run_id: str) -> dict[str, Any]:
            return run_ticker_export(
                ticker=ticker,
                export_format=request_payload.format,
                source_mode=request_payload.source_mode,
                template_strategy=request_payload.template_strategy,
                created_by="api",
            )

        run_id = submit_background_run(
            "ticker_export",
            _runner,
            ticker=ticker,
            metadata=request_payload.model_dump(),
        )
        return {"run_id": run_id, "status": "queued", "ticker": ticker}

    @app.get("/api/exports/{export_id}")
    def get_export_detail(export_id: str) -> dict[str, Any]:
        payload = load_saved_export(export_id)
        if payload is None:
            raise HTTPException(status_code=404, detail="export not found")
        return payload

    @app.get("/api/exports/{export_id}/download")
    def download_export(export_id: str):
        try:
            path = resolve_export_download_path(export_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return FileResponse(path=path, filename=path.name)

    @app.get("/api/exports/{export_id}/artifacts/{artifact_key}")
    def download_export_artifact(export_id: str, artifact_key: str):
        try:
            path = resolve_export_download_path(export_id, artifact_key=artifact_key)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return FileResponse(path=path, filename=path.name)

    @app.post("/api/tickers/{ticker}/analysis/run", status_code=202)
    def run_ticker_analysis(ticker: str, payload: AnalysisRunRequest | None = None) -> dict[str, Any]:
        ticker = api_coerce_ticker(ticker)
        request_payload = payload or AnalysisRunRequest()

        def _runner(_run_id: str) -> list[dict[str, Any]]:
            return run_deep_analysis_for_tickers(
                [ticker],
                use_cache=request_payload.use_cache,
                force_refresh_agents=request_payload.force_refresh_agents,
            )

        run_id = submit_background_run(
            "deep_analysis",
            _runner,
            ticker=ticker,
            metadata=request_payload.model_dump(),
        )
        return {"run_id": run_id, "status": "queued", "ticker": ticker}

    @app.post("/api/tickers/{ticker}/snapshot/open-latest")
    def open_ticker_latest_snapshot(ticker: str) -> dict[str, Any]:
        ticker = api_coerce_ticker(ticker)
        payload = load_latest_snapshot_for_ticker(ticker)
        if payload is None:
            raise HTTPException(status_code=404, detail="no archived snapshot found")
        return _attach_api_ticker_dossier(dict(payload), ticker, source_mode="latest_snapshot")

    return app




app = create_app()
