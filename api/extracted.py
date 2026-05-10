from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field

from src.utils import coerce_ticker, safe_float


class WaccSelectionRequest(BaseModel):
    mode: str = "single_method"
    selected_method: str | None = None
    weights: dict[str, float] = Field(default_factory=dict)


def api_coerce_ticker(value: str) -> str:
    try:
        return coerce_ticker(value)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


def _pick_value(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _percent_points_to_fraction(value: Any) -> float | None:
    amount = safe_float(value)
    if amount is None:
        return None
    return amount / 100.0


def _fraction_to_percent_points(value: Any) -> float | None:
    amount = safe_float(value)
    if amount is None:
        return None
    return amount * 100.0


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


def load_latest_ticker_dossier_payload(ticker: str, source_mode: str | None = None) -> dict[str, Any] | None:
    from db.ticker_dossier import load_latest_ticker_dossier
    from src.stage_04_pipeline.ticker_dossier import ticker_dossier_to_payload

    dossier = load_latest_ticker_dossier(ticker, source_mode=source_mode)
    if dossier is None:
        return None
    return ticker_dossier_to_payload(dossier)


def build_ticker_dossier_from_source(ticker: str, source_mode: str) -> dict[str, Any]:
    from src.stage_04_pipeline.ticker_dossier import build_ticker_dossier, ticker_dossier_to_payload

    return ticker_dossier_to_payload(build_ticker_dossier(ticker, source_mode))


def build_ticker_dossier_payload(ticker: str, source_mode: str | None = None) -> dict[str, Any]:
    from src.stage_04_pipeline.ticker_dossier import (
        SOURCE_MODE_LATEST_SNAPSHOT,
        SOURCE_MODE_LOADED_BACKEND_STATE,
    )

    preferred_source_mode = source_mode or SOURCE_MODE_LATEST_SNAPSHOT
    persisted = load_latest_ticker_dossier_payload(ticker, source_mode=preferred_source_mode)
    if persisted is not None:
        return persisted

    if source_mode:
        return build_ticker_dossier_from_source(ticker, source_mode)

    try:
        return build_ticker_dossier_from_source(ticker, SOURCE_MODE_LATEST_SNAPSHOT)
    except FileNotFoundError:
        return build_ticker_dossier_from_source(ticker, SOURCE_MODE_LOADED_BACKEND_STATE)


_DOSSIER_NOT_PROVIDED = object()


def _attach_api_ticker_dossier(
    payload: dict[str, Any],
    ticker: str,
    source_mode: str | None = None,
    dossier_payload: dict[str, Any] | None | object = _DOSSIER_NOT_PROVIDED,
) -> dict[str, Any]:
    if dossier_payload is _DOSSIER_NOT_PROVIDED:
        try:
            dossier_payload = build_ticker_dossier_payload(ticker, source_mode=source_mode)
        except Exception:  # pragma: no cover - compatibility shim must not hide legacy endpoints
            return payload
    if not isinstance(dossier_payload, dict):
        return payload
    payload["ticker_dossier"] = dossier_payload
    payload["ticker_dossier_contract_version"] = dossier_payload.get("contract_version")
    return payload


def _load_api_ticker_dossier_payload(ticker: str, source_mode: str | None = None) -> dict[str, Any] | None:
    try:
        return build_ticker_dossier_payload(ticker, source_mode=source_mode)
    except Exception:  # pragma: no cover - legacy endpoints should survive missing dossier state
        return None


def _canonical_payload_from_dossier(dossier_payload: dict[str, Any], adapter_name: str) -> dict[str, Any]:
    from src.stage_04_pipeline import ticker_dossier as dossier_adapters

    adapter = getattr(dossier_adapters, adapter_name)
    return dict(adapter(dossier_payload))


def _prefer_keys_from(source: dict[str, Any], target: dict[str, Any], keys: list[str]) -> None:
    for key in keys:
        if key in source:
            target[key] = source.get(key)


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


def _normalize_assumptions_preview_payload(ticker: str, payload: dict[str, Any] | None) -> dict[str, Any]:
    preview = payload or {}
    return {
        "ticker": ticker,
        "resolved_values": preview.get("resolved_values") or {},
        "current_iv": preview.get("current_iv") or {},
        "proposed_iv": preview.get("proposed_iv") or {},
        "current_expected_iv": preview.get("current_expected_iv"),
        "proposed_expected_iv": preview.get("proposed_expected_iv"),
        "delta_pct": preview.get("delta_pct") or {},
    }


def _normalize_wacc_preview_payload(
    ticker: str,
    payload: dict[str, Any] | None,
    request_payload: WaccSelectionRequest,
) -> dict[str, Any]:
    preview = payload or {}
    selection = preview.get("selection")
    if not isinstance(selection, dict):
        selection = {
            "mode": request_payload.mode,
            "selected_method": request_payload.selected_method,
            "weights": request_payload.weights,
        }
    return {
        "ticker": ticker,
        "selection": selection,
        "effective_wacc": preview.get("effective_wacc"),
        "current_wacc": preview.get("current_wacc"),
        "current_iv": preview.get("current_iv") or {},
        "proposed_iv": preview.get("proposed_iv") or {},
        "current_expected_iv": preview.get("current_expected_iv"),
        "proposed_expected_iv": preview.get("proposed_expected_iv"),
        "method_result": preview.get("method_result"),
    }


def _normalize_recommendations_preview_payload(ticker: str, payload: dict[str, Any] | None) -> dict[str, Any]:
    preview = payload or {}
    return {
        "ticker": ticker,
        "current_iv": preview.get("current_iv") or {},
        "proposed_iv": preview.get("proposed_iv") or {},
        "delta_pct": preview.get("delta_pct") or {},
    }


def _watchlist_row_for_ticker(ticker: str) -> dict[str, Any]:
    payload = load_saved_watchlist(shortlist_size=10) or {}
    for row in payload.get("rows") or []:
        row_ticker = str((row or {}).get("ticker") or "").upper()
        if row_ticker == ticker:
            return dict(row)
    return {}


def _snapshot_payload(ticker: str) -> dict[str, Any] | None:
    try:
        return load_latest_snapshot_for_ticker(ticker)
    except Exception:  # pragma: no cover - defensive guard
        return None


def _memo_payload(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    memo = (snapshot or {}).get("memo") or {}
    return dict(memo) if isinstance(memo, dict) else {}


def _valuation_payload(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    valuation = _memo_payload(snapshot).get("valuation") or {}
    return dict(valuation) if isinstance(valuation, dict) else {}


def build_ticker_workspace_payload(ticker: str, dossier_payload: dict[str, Any] | None | object = _DOSSIER_NOT_PROVIDED) -> dict[str, Any]:
    ticker = api_coerce_ticker(ticker)
    if dossier_payload is _DOSSIER_NOT_PROVIDED:
        dossier_payload = _load_api_ticker_dossier_payload(ticker)
    watchlist_row = _watchlist_row_for_ticker(ticker)
    snapshot = _snapshot_payload(ticker)
    memo = _memo_payload(snapshot)
    valuation = _valuation_payload(snapshot)

    market = {}
    analyst = {}
    try:
        market = get_market_data(ticker, use_cache=True)
        analyst = get_analyst_ratings(ticker)
    except Exception:  # pragma: no cover - thin scaffold should still render
        market = {}
        analyst = {}

    current_price = _pick_value(
        (snapshot or {}).get("current_price"),
        valuation.get("current_price"),
        watchlist_row.get("price"),
        market.get("current_price"),
    )
    base_iv = _pick_value(
        (snapshot or {}).get("base_iv"),
        valuation.get("base"),
        watchlist_row.get("iv_base"),
    )
    upside_pct_base = _pick_value(
        valuation.get("upside_pct_base"),
        _percent_points_to_fraction(watchlist_row.get("upside_base_pct")),
    )

    payload = {
        "ticker": ticker,
        "company_name": _pick_value(
            (snapshot or {}).get("company_name"),
            memo.get("company_name"),
            watchlist_row.get("company_name"),
            market.get("name"),
            ticker,
        ),
        "sector": _pick_value((snapshot or {}).get("sector"), memo.get("sector"), watchlist_row.get("sector"), market.get("sector")),
        "action": _pick_value((snapshot or {}).get("action"), memo.get("action"), watchlist_row.get("latest_action")),
        "conviction": _pick_value(
            (snapshot or {}).get("conviction"),
            memo.get("conviction"),
            watchlist_row.get("latest_conviction"),
        ),
        "current_price": safe_float(current_price),
        "base_iv": safe_float(base_iv),
        "bear_iv": safe_float(_pick_value(valuation.get("bear"), watchlist_row.get("iv_bear"))),
        "bull_iv": safe_float(_pick_value(valuation.get("bull"), watchlist_row.get("iv_bull"))),
        "weighted_iv": safe_float(_pick_value(watchlist_row.get("expected_iv"), watchlist_row.get("weighted_iv"))),
        "upside_pct_base": safe_float(upside_pct_base),
        "analyst_target": safe_float(_pick_value(analyst.get("target_mean"), market.get("analyst_target_mean"))),
        "analyst_recommendation": _pick_value(analyst.get("recommendation"), market.get("analyst_recommendation")),
        "latest_snapshot_date": _pick_value(
            (snapshot or {}).get("created_at"),
            watchlist_row.get("latest_snapshot_date"),
        ),
        "snapshot_available": snapshot is not None,
        "last_snapshot_id": (snapshot or {}).get("id"),
        "snapshot_id": (snapshot or {}).get("id"),
        "last_snapshot_date": _pick_value(
            (snapshot or {}).get("created_at"),
            watchlist_row.get("latest_snapshot_date"),
        ),
        "latest_action": _pick_value((snapshot or {}).get("action"), memo.get("action"), watchlist_row.get("latest_action")),
        "latest_conviction": _pick_value(
            (snapshot or {}).get("conviction"),
            memo.get("conviction"),
            watchlist_row.get("latest_conviction"),
        ),
    }
    if isinstance(dossier_payload, dict):
        try:
            canonical = _canonical_payload_from_dossier(dossier_payload, "workspace_payload_from_dossier")
        except Exception:
            canonical = {}
        _prefer_keys_from(
            canonical,
            payload,
            [
                "ticker",
                "company_name",
                "sector",
                "current_price",
                "base_iv",
                "bear_iv",
                "bull_iv",
                "weighted_iv",
                "upside_pct_base",
                "analyst_target",
                "analyst_recommendation",
                "latest_snapshot_date",
                "snapshot_available",
                "last_snapshot_id",
                "snapshot_id",
                "last_snapshot_date",
                "ticker_dossier_contract_version",
                "assumption_register_summary",
            ],
        )
    return _attach_api_ticker_dossier(payload, ticker, dossier_payload=dossier_payload)


def build_overview_payload(ticker: str) -> dict[str, Any]:
    ticker = api_coerce_ticker(ticker)
    dossier_payload = _load_api_ticker_dossier_payload(ticker)
    workspace = build_ticker_workspace_payload(ticker, dossier_payload=dossier_payload)
    snapshot = _snapshot_payload(ticker)
    memo = _memo_payload(snapshot)
    tracker = build_thesis_tracker_view(ticker)
    market = build_news_materiality_view(ticker)

    next_catalyst = ((tracker.get("stance") or {}).get("next_catalyst") or {}).get("title")
    valuation_pulse = None
    if workspace.get("current_price") is not None and workspace.get("base_iv") is not None:
        valuation_pulse = (
            f"Base IV ${workspace['base_iv']:,.2f} versus current price ${workspace['current_price']:,.2f}."
        )

    market_pulse = ((market.get("historical_brief") or {}).get("summary")) or market.get("summary")

    payload = {
        "ticker": ticker,
        "company_name": workspace.get("company_name"),
        "one_liner": memo.get("one_liner"),
        "variant_thesis_prompt": memo.get("variant_thesis_prompt"),
        "market_pulse": market_pulse,
        "valuation_pulse": valuation_pulse,
        "thesis_changes": ((tracker.get("what_changed") or {}).get("summary_lines")) or [],
        "next_catalyst": next_catalyst,
        "workspace": workspace,
    }
    if isinstance(dossier_payload, dict):
        try:
            canonical = _canonical_payload_from_dossier(dossier_payload, "overview_payload_from_dossier")
        except Exception:
            canonical = {}
        _prefer_keys_from(canonical, payload, ["ticker", "company_name", "valuation_pulse", "ticker_dossier_contract_version"])
        payload["workspace"] = workspace
    return _attach_api_ticker_dossier(payload, ticker, dossier_payload=dossier_payload)


build_ticker_overview_payload = build_overview_payload


def build_valuation_summary_payload(ticker: str) -> dict[str, Any]:
    ticker = api_coerce_ticker(ticker)
    dossier_payload = _load_api_ticker_dossier_payload(ticker)
    watchlist_row = _watchlist_row_for_ticker(ticker)
    snapshot = _snapshot_payload(ticker)
    memo = _memo_payload(snapshot)
    valuation = _valuation_payload(snapshot)
    summary = build_dcf_audit_view(ticker)

    analyst_target = watchlist_row.get("analyst_target")
    if analyst_target is None:
        try:
            analyst_target = get_market_data(ticker, use_cache=True).get("analyst_target_mean")
        except Exception:
            analyst_target = None

    payload = {
        "ticker": ticker,
        "current_price": safe_float(
            _pick_value((snapshot or {}).get("current_price"), valuation.get("current_price"), watchlist_row.get("price"))
        ),
        "base_iv": safe_float(_pick_value((snapshot or {}).get("base_iv"), valuation.get("base"), watchlist_row.get("iv_base"))),
        "bear_iv": safe_float(_pick_value(valuation.get("bear"), watchlist_row.get("iv_bear"))),
        "bull_iv": safe_float(_pick_value(valuation.get("bull"), watchlist_row.get("iv_bull"))),
        "weighted_iv": safe_float(_pick_value(watchlist_row.get("expected_iv"), watchlist_row.get("weighted_iv"))),
        "upside_pct_base": safe_float(
            _pick_value(_fraction_to_percent_points(valuation.get("upside_pct_base")), watchlist_row.get("upside_base_pct"))
        ),
        "analyst_target": safe_float(analyst_target),
        "conviction": _pick_value((snapshot or {}).get("conviction"), memo.get("conviction"), watchlist_row.get("latest_conviction")),
        "memo_date": _pick_value((snapshot or {}).get("created_at"), memo.get("date"), watchlist_row.get("latest_snapshot_date")),
        "why_it_matters": (
            f"Base IV ${safe_float(_pick_value((snapshot or {}).get('base_iv'), valuation.get('base'), watchlist_row.get('iv_base'))) or 0:,.2f}"
            f" versus current price ${safe_float(_pick_value((snapshot or {}).get('current_price'), valuation.get('current_price'), watchlist_row.get('price'))) or 0:,.2f}."
            if _pick_value((snapshot or {}).get("base_iv"), valuation.get("base"), watchlist_row.get("iv_base")) is not None
            and _pick_value((snapshot or {}).get("current_price"), valuation.get("current_price"), watchlist_row.get("price")) is not None
            else None
        ),
        "readiness": summary.get("model_integrity") or {},
        "summary": summary,
    }
    if isinstance(dossier_payload, dict):
        try:
            canonical = _canonical_payload_from_dossier(dossier_payload, "valuation_summary_payload_from_dossier")
        except Exception:
            canonical = {}
        _prefer_keys_from(
            canonical,
            payload,
            [
                "ticker",
                "current_price",
                "base_iv",
                "bear_iv",
                "bull_iv",
                "weighted_iv",
                "upside_pct_base",
                "analyst_target",
                "memo_date",
                "why_it_matters",
                "ticker_dossier_contract_version",
                "assumption_register_summary",
            ],
        )
    return _attach_api_ticker_dossier(payload, ticker, dossier_payload=dossier_payload)


def build_valuation_dcf_payload(ticker: str) -> dict[str, Any]:
    ticker = api_coerce_ticker(ticker)
    return build_dcf_audit_view(ticker)


def build_valuation_comps_payload(ticker: str) -> dict[str, Any]:
    ticker = api_coerce_ticker(ticker)
    return build_comps_dashboard_view(ticker)


def build_valuation_assumptions_payload(ticker: str) -> dict[str, Any]:
    ticker = api_coerce_ticker(ticker)
    workbench = build_override_workbench(ticker)
    payload = {
        "ticker": ticker,
        "available": bool(workbench.get("available")),
        **workbench,
    }
    from src.stage_04_pipeline.override_workbench import load_override_audit_history
    from src.stage_04_pipeline.override_workbench import load_assumption_register_audit_history

    override_audit_rows = load_override_audit_history(ticker, limit=50)
    payload["override_audit_rows"] = override_audit_rows
    payload["assumption_register_audit_rows"] = load_assumption_register_audit_history(ticker, limit=50)
    payload["audit_rows"] = override_audit_rows
    return payload


def build_wacc_payload(ticker: str) -> dict[str, Any]:
    ticker = api_coerce_ticker(ticker)
    workbench = build_wacc_workbench(ticker, apply_overrides=True)
    selection = workbench.get("current_selection") or {}
    effective_preview = workbench.get("effective_preview") or {}
    return {
        "ticker": ticker,
        "available": bool(workbench.get("available")),
        "current_wacc": effective_preview.get("wacc"),
        "proposed_wacc": effective_preview.get("expected_method_wacc"),
        "method": selection.get("selected_method") or selection.get("mode"),
        "audit_rows": load_wacc_methodology_audit_history(ticker, limit=25),
        "current_selection": selection,
        "effective_preview": effective_preview,
        "methods": workbench.get("methods") or [],
    }


build_valuation_wacc_payload = build_wacc_payload


def build_valuation_recommendations_payload(ticker: str) -> dict[str, Any]:
    ticker = api_coerce_ticker(ticker)
    recs = load_recommendations(ticker)
    if recs is None:
        return {
            "ticker": ticker,
            "available": False,
            "generated_at": None,
            "current_iv_base": None,
            "recommendations": [],
        }
    return {
        "ticker": ticker,
        "available": True,
        "generated_at": recs.generated_at,
        "current_iv_base": recs.current_iv_base,
        "recommendations": jsonable_encoder(recs.recommendations),
    }


def build_market_payload(ticker: str) -> dict[str, Any]:
    ticker = api_coerce_ticker(ticker)
    market = build_news_materiality_view(ticker)
    market["ticker"] = ticker

    try:
        revisions = get_revision_signals(ticker)
        market["revisions"] = jsonable_encoder(revisions)
    except Exception:
        market["revisions"] = {
            "ticker": ticker,
            "available": False,
            "revision_momentum": "unavailable",
            "error": "Revision signals unavailable",
        }

    try:
        regime = detect_current_regime()
        scenario_weights = get_scenario_weights(regime)
        macro_snapshot = get_macro_snapshot(lookback_days=5)
        yield_curve = get_yield_curve()
        market["macro"] = {
            "regime": jsonable_encoder(regime),
            "scenario_weights": jsonable_encoder(scenario_weights),
            "snapshot": macro_snapshot,
            "yield_curve": yield_curve,
        }
    except Exception:
        market["macro"] = {
            "regime": {"label": "Neutral", "available": False, "error": "Macro unavailable"},
            "scenario_weights": {"bear": 0.2, "base": 0.6, "bull": 0.2, "regime": "Neutral"},
            "snapshot": {"available": False, "series": {}, "error": "Macro unavailable"},
            "yield_curve": {"available": False, "maturities": [], "error": "Macro unavailable"},
        }

    try:
        factor_exposure = decompose_factor_exposure(ticker)
        market["factor_exposure"] = {
            **jsonable_encoder(factor_exposure),
            "summary_text": get_factor_summary_text(factor_exposure),
        }
    except Exception:
        market["factor_exposure"] = {
            "ticker": ticker,
            "available": False,
            "error": "Factor exposure unavailable",
            "summary_text": "Factor exposure unavailable.",
        }

    market["audit_flags"] = list(market.get("audit_flags") or [])
    return market


def build_research_payload(ticker: str) -> dict[str, Any]:
    ticker = api_coerce_ticker(ticker)
    payload = build_research_board_view(ticker)
    payload["ticker"] = ticker
    return payload


def build_audit_payload(ticker: str) -> dict[str, Any]:
    ticker = api_coerce_ticker(ticker)
    return {
        "ticker": ticker,
        "dcf_audit": build_dcf_audit_view(ticker),
        "filings_browser": build_filings_browser_view(ticker),
        "comps": build_comps_dashboard_view(ticker),
    }
