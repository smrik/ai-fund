from __future__ import annotations


def _legacy_payload() -> dict:
    return {
        "$schema_version": "1.0",
        "generated_at": "2026-04-30T00:00:00+00:00",
        "ticker": "IBM",
        "company_name": "International Business Machines",
        "sector": "Technology",
        "industry": "IT Services",
        "exchange": "NYSE",
        "country": "United States",
        "market": {"price": 260.0, "analyst_target": 275.0, "analyst_recommendation": "Hold"},
        "assumptions": {},
        "wacc": {},
        "valuation": {"iv_bear": 190.0, "iv_base": 202.0, "iv_bull": 216.0, "expected_iv": 205.0, "current_price": 260.0},
        "scenarios": {"base": {"probability": 0.6, "iv": 202.0}},
        "terminal": {},
        "health_flags": {},
        "forecast_bridge": [{"year": 2027, "fcff_mm": 100.0}],
        "source_lineage": {"wacc": "override"},
        "ciq_lineage": {"snapshot_source_file": "IBM_comps.xlsx", "snapshot_as_of_date": "2026-03-01", "peer_count": 4},
        "comps_detail": {},
        "comps_analysis": {
            "primary_metric": "tev_ebitda_ltm",
            "peer_counts": {"raw": 5, "clean": 4},
            "valuation_range": {"base": 202.0},
            "audit_flags": ["Outliers removed"],
            "source_lineage": {"source_file": "IBM_comps.xlsx", "as_of_date": "2026-03-01"},
        },
    }


def test_ticker_dossier_model_validates_required_envelope_and_round_trips_json():
    from src.contracts.ticker_dossier import TickerDossier
    from src.stage_04_pipeline.ticker_dossier import build_ticker_dossier_from_export_payload

    dossier = build_ticker_dossier_from_export_payload(
        _legacy_payload(),
        source_mode="loaded_backend_state",
    )
    payload = dossier.model_dump(mode="json")
    restored = TickerDossier.model_validate_json(dossier.model_dump_json())

    assert payload["contract_name"] == "TickerDossier"
    assert payload["contract_version"] == "1.0.0"
    assert payload["ticker"] == "IBM"
    assert payload["display_name"] == "International Business Machines"
    assert payload["latest_snapshot"]["company_identity"]["ticker"] == "IBM"
    assert payload["latest_snapshot"]["company_identity"]["industry"] == "IT Services"
    assert payload["latest_snapshot"]["company_identity"]["exchange"] == "NYSE"
    assert payload["latest_snapshot"]["company_identity"]["country"] == "United States"
    assert payload["latest_snapshot"]["market_snapshot"]["price"] == 260.0
    assert payload["latest_snapshot"]["valuation_snapshot"]["base_iv"] == 202.0
    assert payload["latest_snapshot"]["historical_series"]["fcff"][0]["year"] == 2027
    assert payload["latest_snapshot"]["comps_snapshot"]["peer_count"] == 4
    assert payload["loaded_backend_state"]["source_mode"] == "loaded_backend_state"
    assert payload["export_metadata"]["source_mode"] == "loaded_backend_state"
    assert set(payload["optional_overlays"]) == {
        "api_view",
        "react_view",
        "excel_view",
        "forecast_bridge",
        "html_view",
        "debug_view",
        "drift_test_view",
    }
    assert restored == dossier


def test_qoe_snapshot_maps_score_flags_and_additive_details():
    from src.stage_04_pipeline.ticker_dossier import build_ticker_dossier_from_export_payload

    payload = _legacy_payload()
    payload["qoe"] = {
        "qoe_score": 2.5,
        "qoe_flag": "amber",
        "deterministic": {"signal_scores": {"accruals": "red", "cash_conversion": "green"}},
        "llm": {
            "normalized_ebit": 92.0,
            "reported_ebit": 100.0,
            "ebit_haircut_pct": -8.0,
            "dcf_ebit_override_pending": True,
            "revenue_recognition_flags": ["Bill-and-hold disclosure"],
            "auditor_flags": ["Auditor change"],
            "llm_confidence": "medium",
        },
        "pm_summary": "QoE needs review.",
    }

    dossier = build_ticker_dossier_from_export_payload(payload, source_mode="loaded_backend_state")
    qoe = dossier.model_dump(mode="json")["latest_snapshot"]["qoe_snapshot"]

    assert qoe["present"] is True
    assert qoe["score"] == 2.5
    assert qoe["flags"] == [
        "amber",
        "accruals:red",
        "Bill-and-hold disclosure",
        "Auditor change",
        "dcf_ebit_override_pending",
    ]
    assert qoe["deterministic"]["signal_scores"]["accruals"] == "red"
    assert qoe["normalized_ebit"] == 92.0
    assert qoe["pm_summary"] == "QoE needs review."


def test_historical_series_maps_existing_payload_sources_and_stays_empty_when_absent():
    from src.stage_04_pipeline.ticker_dossier import build_ticker_dossier_from_export_payload

    payload = _legacy_payload()
    payload["historical_series"] = {
        "revenue": [{"period": "2025", "value": 1000.0}],
        "ebit": [{"period": "2025", "value": 180.0}],
    }
    payload["drivers_raw"] = {
        "ebit_margin_series": [{"period": "2025", "value": 0.18}],
    }

    dossier = build_ticker_dossier_from_export_payload(payload, source_mode="loaded_backend_state")
    series = dossier.model_dump(mode="json")["latest_snapshot"]["historical_series"]

    assert series["revenue"] == [{"period": "2025", "value": 1000.0}]
    assert series["ebit"] == [{"period": "2025", "value": 180.0}]
    assert series["margin"] == [{"period": "2025", "value": 0.18}]
    assert series["fcff"] == [{"year": 2027, "fcff_mm": 100.0}]

    empty_payload = _legacy_payload()
    empty_payload.pop("forecast_bridge")
    empty_series = build_ticker_dossier_from_export_payload(
        empty_payload,
        source_mode="loaded_backend_state",
    ).model_dump(mode="json")["latest_snapshot"]["historical_series"]

    assert empty_series == {"revenue": [], "ebit": [], "fcff": [], "margin": []}


def test_legacy_workspace_and_summary_payloads_can_be_derived_from_dossier():
    from src.stage_04_pipeline.ticker_dossier import (
        build_ticker_dossier_from_export_payload,
        valuation_summary_payload_from_dossier,
        workspace_payload_from_dossier,
    )

    dossier = build_ticker_dossier_from_export_payload(_legacy_payload(), source_mode="loaded_backend_state")
    workspace = workspace_payload_from_dossier(dossier)
    summary = valuation_summary_payload_from_dossier(dossier)

    assert workspace["ticker"] == "IBM"
    assert workspace["base_iv"] == 202.0
    assert workspace["ticker_dossier_contract_version"] == "1.0.0"
    assert summary["weighted_iv"] == 205.0
    assert summary["why_it_matters"] == "Base IV $202.00 versus current price $260.00."
