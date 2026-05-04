from __future__ import annotations

from typing import Any

from src.contracts.ticker_dossier import (
    BackendValidation,
    CompanyIdentity,
    CompsSnapshot,
    ExportMetadata,
    HistoricalSeries,
    LatestSnapshot,
    LoadedBackendState,
    MarketSnapshot,
    QoeSnapshot,
    TICKER_DOSSIER_CONTRACT_VERSION,
    TickerDossier,
    ValuationSnapshot,
)


SOURCE_MODE_LATEST_SNAPSHOT = "latest_snapshot"
SOURCE_MODE_LOADED_BACKEND_STATE = "loaded_backend_state"


def _coerce_ticker(value: str) -> str:
    ticker = str(value or "").strip().upper()
    if not ticker:
        raise ValueError("ticker is required")
    return ticker


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def _scenario_probability_map(scenarios: dict[str, Any]) -> dict[str, float | None]:
    return {
        key: _as_float((value or {}).get("probability"))
        for key, value in scenarios.items()
        if isinstance(value, dict)
    }


def _default_overlays(payload: dict[str, Any]) -> dict[str, Any]:
    legacy_payload_keys = sorted(key for key in payload if key != "ticker_dossier")
    return {
        "api_view": {},
        "react_view": {},
        "excel_view": {"legacy_roots": legacy_payload_keys},
        "forecast_bridge": payload.get("forecast_bridge") or [],
        "html_view": {},
        "debug_view": {"legacy_payload_keys": legacy_payload_keys},
        "drift_test_view": {},
    }


def _payload_without_dossier(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key != "ticker_dossier"}


def build_ticker_dossier_from_export_payload(
    payload: dict[str, Any],
    *,
    source_mode: str,
    loaded_from: str | None = None,
    snapshot_id: int | None = None,
) -> TickerDossier:
    payload = _payload_without_dossier(dict(payload or {}))
    ticker = _coerce_ticker(str(payload.get("ticker") or ""))
    snapshot = payload.get("snapshot") if isinstance(payload.get("snapshot"), dict) else {}
    market = payload.get("market") if isinstance(payload.get("market"), dict) else {}
    valuation = payload.get("valuation") if isinstance(payload.get("valuation"), dict) else {}
    scenarios = payload.get("scenarios") if isinstance(payload.get("scenarios"), dict) else {}
    ciq_lineage = payload.get("ciq_lineage") if isinstance(payload.get("ciq_lineage"), dict) else {}
    comps_analysis = payload.get("comps_analysis") if isinstance(payload.get("comps_analysis"), dict) else {}
    peer_counts = comps_analysis.get("peer_counts") if isinstance(comps_analysis.get("peer_counts"), dict) else {}
    historical_multiples = comps_analysis.get("historical_multiples_summary")
    historical_metrics = (historical_multiples or {}).get("metrics") if isinstance(historical_multiples, dict) else {}
    display_name = str(_first_present(payload.get("company_name"), snapshot.get("company_name"), ticker) or ticker)
    generated_at = payload.get("generated_at")
    as_of_date = str(
        _first_present(
            snapshot.get("created_at"),
            ciq_lineage.get("snapshot_as_of_date"),
            (comps_analysis.get("source_lineage") or {}).get("as_of_date")
            if isinstance(comps_analysis.get("source_lineage"), dict)
            else None,
            generated_at,
        )
        or "unknown"
    )
    validation = BackendValidation(
        passed=True,
        warnings=[] if as_of_date != "unknown" else ["as_of_date could not be inferred from source payload"],
        missing_required_fields=[] if as_of_date != "unknown" else ["as_of_date"],
    )
    latest_snapshot = LatestSnapshot(
        company_identity=CompanyIdentity(
            ticker=ticker,
            display_name=display_name,
            sector=payload.get("sector") or snapshot.get("sector"),
            industry=payload.get("industry") or snapshot.get("industry"),
            exchange=payload.get("exchange") or snapshot.get("exchange"),
        ),
        market_snapshot=MarketSnapshot(
            as_of_date=as_of_date,
            price=_as_float(_first_present(market.get("price"), valuation.get("current_price"), snapshot.get("current_price"))),
            market_cap=_as_float(market.get("market_cap")),
            enterprise_value=_as_float(market.get("enterprise_value")),
            beta=_as_float(market.get("beta")),
            analyst_target=_as_float(market.get("analyst_target")),
            analyst_recommendation=market.get("analyst_recommendation"),
            num_analysts=_as_int(market.get("num_analysts")),
        ),
        valuation_snapshot=ValuationSnapshot(
            bear_iv=_as_float(_first_present(valuation.get("bear_iv"), valuation.get("iv_bear"))),
            base_iv=_as_float(_first_present(valuation.get("base_iv"), valuation.get("iv_base"))),
            bull_iv=_as_float(_first_present(valuation.get("bull_iv"), valuation.get("iv_bull"))),
            expected_iv=_as_float(valuation.get("expected_iv")),
            current_price=_as_float(_first_present(valuation.get("current_price"), market.get("price"), snapshot.get("current_price"))),
            upside_pct=_as_float(_first_present(valuation.get("upside_pct"), valuation.get("upside_pct_base"))),
            scenario_probabilities=_scenario_probability_map(scenarios),
        ),
        historical_series=HistoricalSeries(
            fcff=list(payload.get("forecast_bridge") or []),
            margin=list((historical_metrics or {}).get("margin", {}).get("series") or [])
            if isinstance((historical_metrics or {}).get("margin"), dict)
            else [],
        ),
        qoe_snapshot=QoeSnapshot(),
        comps_snapshot=CompsSnapshot(
            peer_count=_as_int(_first_present(ciq_lineage.get("peer_count"), peer_counts.get("clean"), peer_counts.get("raw"))),
            primary_metric=comps_analysis.get("primary_metric"),
            median_multiple=_as_float(comps_analysis.get("median_multiple")),
            valuation_range=comps_analysis.get("valuation_range") or {},
            audit_flags=list(comps_analysis.get("audit_flags") or []),
        ),
        source_lineage={
            "valuation_snapshot": payload.get("source_lineage") or {},
            "comps_snapshot": comps_analysis.get("source_lineage") or ciq_lineage,
        },
    )
    return TickerDossier(
        ticker=ticker,
        as_of_date=as_of_date,
        display_name=display_name,
        currency=str(payload.get("currency") or "USD"),
        latest_snapshot=latest_snapshot,
        loaded_backend_state=LoadedBackendState(
            backend_name="export-service",
            loaded_from=loaded_from,
            loaded_at=generated_at,
            source_mode=source_mode,
            validation=validation,
            field_mappings={
                "company_identity": "company_name/sector",
                "market_snapshot": "market",
                "valuation_snapshot": "valuation/scenarios",
                "historical_series": "forecast_bridge",
                "comps_snapshot": "comps_analysis/ciq_lineage",
            },
            adapter_state={
                "api_ready": True,
                "react_ready": True,
                "excel_ready": True,
                "html_ready": True,
            },
        ),
        source_lineage={
            "source_lineage": payload.get("source_lineage") or {},
            "ciq_lineage": ciq_lineage,
        },
        export_metadata=ExportMetadata(
            source_mode=source_mode,
            generated_at=generated_at,
            schema_version=payload.get("$schema_version"),
            snapshot_id=snapshot_id or snapshot.get("id"),
            source_label=source_mode,
        ),
        optional_overlays=_default_overlays(payload),
    )


def ticker_dossier_to_payload(dossier: TickerDossier | dict[str, Any]) -> dict[str, Any]:
    if isinstance(dossier, TickerDossier):
        return dossier.model_dump(mode="json")
    return TickerDossier.model_validate(dossier).model_dump(mode="json")


def build_ticker_dossier(ticker: str, source_mode: str = SOURCE_MODE_LATEST_SNAPSHOT) -> TickerDossier:
    ticker = _coerce_ticker(ticker)
    from src.stage_04_pipeline import export_service

    if source_mode == SOURCE_MODE_LATEST_SNAPSHOT:
        payload, snapshot_id = export_service._build_snapshot_ticker_payload(ticker)
        return build_ticker_dossier_from_export_payload(
            payload,
            source_mode=source_mode,
            snapshot_id=snapshot_id,
        )
    if source_mode == SOURCE_MODE_LOADED_BACKEND_STATE:
        payload = export_service._build_current_ticker_payload(ticker)
        return build_ticker_dossier_from_export_payload(payload, source_mode=source_mode)
    raise ValueError(f"Unsupported ticker dossier source mode: {source_mode}")


def build_best_available_ticker_dossier(ticker: str) -> TickerDossier:
    try:
        return build_ticker_dossier(ticker, SOURCE_MODE_LATEST_SNAPSHOT)
    except FileNotFoundError:
        return build_ticker_dossier(ticker, SOURCE_MODE_LOADED_BACKEND_STATE)


def workspace_payload_from_dossier(dossier: TickerDossier | dict[str, Any]) -> dict[str, Any]:
    dossier = TickerDossier.model_validate(dossier)
    snapshot = dossier.latest_snapshot
    valuation = snapshot.valuation_snapshot
    market = snapshot.market_snapshot
    current_price = _first_present(market.price, valuation.current_price)
    return {
        "ticker": dossier.ticker,
        "company_name": dossier.display_name,
        "sector": snapshot.company_identity.sector,
        "action": market.analyst_recommendation,
        "conviction": None,
        "current_price": current_price,
        "base_iv": valuation.base_iv,
        "bear_iv": valuation.bear_iv,
        "bull_iv": valuation.bull_iv,
        "weighted_iv": valuation.expected_iv,
        "upside_pct_base": valuation.upside_pct,
        "analyst_target": market.analyst_target,
        "analyst_recommendation": market.analyst_recommendation,
        "latest_snapshot_date": dossier.as_of_date,
        "snapshot_available": dossier.export_metadata.snapshot_id is not None,
        "last_snapshot_id": dossier.export_metadata.snapshot_id,
        "snapshot_id": dossier.export_metadata.snapshot_id,
        "last_snapshot_date": dossier.as_of_date,
        "latest_action": market.analyst_recommendation,
        "latest_conviction": None,
        "ticker_dossier_contract_version": TICKER_DOSSIER_CONTRACT_VERSION,
    }


def overview_payload_from_dossier(dossier: TickerDossier | dict[str, Any]) -> dict[str, Any]:
    dossier = TickerDossier.model_validate(dossier)
    workspace = workspace_payload_from_dossier(dossier)
    valuation = dossier.latest_snapshot.valuation_snapshot
    valuation_pulse = None
    current_price = _first_present(valuation.current_price, dossier.latest_snapshot.market_snapshot.price)
    if valuation.base_iv is not None and current_price is not None:
        valuation_pulse = f"Base IV ${valuation.base_iv:,.2f} versus current price ${current_price:,.2f}."
    return {
        "ticker": dossier.ticker,
        "company_name": dossier.display_name,
        "one_liner": None,
        "variant_thesis_prompt": None,
        "market_pulse": None,
        "valuation_pulse": valuation_pulse,
        "thesis_changes": [],
        "next_catalyst": None,
        "workspace": workspace,
        "ticker_dossier_contract_version": TICKER_DOSSIER_CONTRACT_VERSION,
    }


def valuation_summary_payload_from_dossier(dossier: TickerDossier | dict[str, Any]) -> dict[str, Any]:
    dossier = TickerDossier.model_validate(dossier)
    valuation = dossier.latest_snapshot.valuation_snapshot
    market = dossier.latest_snapshot.market_snapshot
    current_price = _first_present(valuation.current_price, market.price)
    why_it_matters = None
    if valuation.base_iv is not None and current_price is not None:
        why_it_matters = f"Base IV ${valuation.base_iv:,.2f} versus current price ${current_price:,.2f}."
    return {
        "ticker": dossier.ticker,
        "current_price": current_price,
        "base_iv": valuation.base_iv,
        "bear_iv": valuation.bear_iv,
        "bull_iv": valuation.bull_iv,
        "weighted_iv": valuation.expected_iv,
        "upside_pct_base": valuation.upside_pct,
        "analyst_target": market.analyst_target,
        "conviction": None,
        "memo_date": dossier.as_of_date,
        "why_it_matters": why_it_matters,
        "readiness": {},
        "summary": {},
        "ticker_dossier_contract_version": TICKER_DOSSIER_CONTRACT_VERSION,
    }
