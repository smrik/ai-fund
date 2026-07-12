from __future__ import annotations

import json
from pathlib import Path

from scripts.manual import run_analyst_prep_pack as prep


def _flow_result(*, forecast_bridge_json: str = "[]", fcfe_iv_base=None) -> dict:
    return {
        "ticker": "MSFT",
        "decision_ready": False,
        "source_preflight": {
            "schema_version": "professional_model_preflight_v1",
            "ticker": "MSFT",
            "status": "blocked",
            "blockers": ["formula_reference_errors:24"],
            "source": {
                "source_file": "MSFT_Standard.xlsx",
                "sha256": "abc",
                "run_id": 17,
            },
        },
        "deterministic": {
            "batch_row": {
                "ticker": "MSFT",
                "price": 385.10,
                "iv_base": 266.69,
                "forecast_bridge_json": forecast_bridge_json,
                "fcfe_iv_base": fcfe_iv_base,
            }
        },
    }


def test_run_bound_valuation_json_preserves_source_preflight_and_forecast(tmp_path: Path) -> None:
    forecast = json.dumps(
        [
            {
                "year": 1,
                "revenue": 100_000_000.0,
                "ebit": 40_000_000.0,
                "nopat": 32_000_000.0,
                "da": 5_000_000.0,
                "capex": 8_000_000.0,
                "delta_nwc": 1_000_000.0,
                "fcff": 28_000_000.0,
            }
        ]
    )
    result = _flow_result(forecast_bridge_json=forecast)

    descriptor = prep.build_run_bound_valuation_payload(
        "MSFT",
        result,
        output_dir=tmp_path,
        run_stamp="20260712T000000Z",
    )

    assert descriptor["status"] == "available"
    assert descriptor["advanced_model_input"]["status"] == "available"
    payload = json.loads(Path(descriptor["path"]).read_text(encoding="utf-8"))
    assert payload["source_preflight"] == result["source_preflight"]
    assert payload["excel_flat"]["forecast"][0]["year"] == 1
    assert descriptor["source_binding"]["run_id"] == 17


def test_run_bound_payload_types_missing_forecast_and_removes_unavailable_fcfe(tmp_path: Path) -> None:
    descriptor = prep.build_run_bound_valuation_payload(
        "MSFT",
        _flow_result(fcfe_iv_base=199.76),
        output_dir=tmp_path,
        run_stamp="20260712T000001Z",
    )

    assert descriptor["status"] == "incompatible"
    advanced = descriptor["advanced_model_input"]
    assert advanced["status"] == "unavailable"
    assert advanced["reason_code"] == "excel_flat_forecast_unavailable"
    assert advanced["required_contract"] == "excel_flat.forecast"
    assert advanced["row_count"] == 0
    assert advanced["contract_issues"] == ["excel_flat.forecast is empty"]
    payload = json.loads(Path(descriptor["path"]).read_text(encoding="utf-8"))
    assert payload["method_availability"]["fcfe"]["status"] == "unavailable"
    assert "legacy_value_omitted" in payload["method_availability"]["fcfe"]
    assert "fcfe_iv_base" not in payload["valuation"]
    assert all(row.get("key") != "fcfe_iv_base" for row in payload["excel_flat"]["valuation"])


def test_run_bound_payload_rejects_malformed_nonempty_forecast(tmp_path: Path) -> None:
    descriptor = prep.build_run_bound_valuation_payload(
        "MSFT",
        _flow_result(forecast_bridge_json=json.dumps([{"year": 1, "fcff": 1_000_000.0}])),
        output_dir=tmp_path,
        run_stamp="20260712T000001Z-bad",
    )

    advanced = descriptor["advanced_model_input"]
    assert descriptor["status"] == "incompatible"
    assert advanced["status"] == "unavailable"
    assert advanced["reason_code"] == "excel_flat_forecast_incompatible"
    assert advanced["row_count"] == 1
    assert any("revenue_mm" in issue for issue in advanced["contract_issues"])



def test_run_bound_payload_fails_closed_without_current_batch_row(tmp_path: Path) -> None:
    descriptor = prep.build_run_bound_valuation_payload(
        "MSFT",
        {"ticker": "MSFT", "source_preflight": {"status": "blocked"}, "deterministic": {}},
        output_dir=tmp_path,
        run_stamp="20260712T000002Z",
    )

    assert descriptor["status"] == "unavailable"
    assert descriptor["reason_code"] == "current_run_batch_row_unavailable"
    assert descriptor["path"] is None


def test_excel_export_uses_only_explicit_current_run_json(tmp_path: Path, monkeypatch) -> None:
    valuation_json = tmp_path / "MSFT-run-valuation.json"
    valuation_json.write_text("{}", encoding="utf-8")
    calls: dict[str, object] = {}

    def _fake_build(ticker, *, json_path=None, guided_workup_path=None):
        calls.update(
            ticker=ticker,
            json_path=json_path,
            guided_workup_path=guided_workup_path,
        )
        return tmp_path / "MSFT_advanced_dcf_model.xlsx"

    monkeypatch.setattr(prep, "_build_advanced_model", _fake_build)
    result = prep.export_current_run_xlsx(
        "MSFT",
        {
            "status": "available",
            "path": str(valuation_json),
            "advanced_model_input": {"status": "available"},
        },
        decision_ready=False,
        guided_workup_path=tmp_path / "MSFT-flow.json",
    )

    assert calls["json_path"] == valuation_json
    assert result["status"] == "diagnostic_blocked"
    assert result["strategy"] == "advanced_dcf_model"


def test_excel_export_never_falls_back_when_forecast_contract_is_unavailable(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        prep,
        "_build_advanced_model",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not build")),
    )

    result = prep.export_current_run_xlsx(
        "MSFT",
        {
            "status": "incompatible",
            "path": str(tmp_path / "MSFT.json"),
            "advanced_model_input": {
                "status": "unavailable",
                "reason_code": "excel_flat_forecast_unavailable",
                "required_contract": "excel_flat.forecast",
            },
        },
        decision_ready=False,
    )

    assert result["status"] == "unavailable"
    assert result["reason_code"] == "excel_flat_forecast_unavailable"
    assert result["stale_latest_fallback_used"] is False
