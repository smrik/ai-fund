from __future__ import annotations

from datetime import date
import time
from types import SimpleNamespace

from fastapi.testclient import TestClient


def test_api_payload_uses_shared_provider_factory_and_workup_service(
    monkeypatch,
) -> None:
    from api.main import run_reconciled_valuation_workup_payload
    from src.stage_04_pipeline import valuation_provider_bindings
    from src.stage_04_pipeline import valuation_workup_service

    settings = SimpleNamespace(
        backend="openrouter",
        primary_model="primary",
        critic_model="critic",
    )
    bindings = object()
    observed: dict[str, object] = {}

    monkeypatch.setattr(
        valuation_provider_bindings.ProviderBindingSettings,
        "from_environment",
        lambda: settings,
    )
    monkeypatch.setattr(
        valuation_provider_bindings,
        "build_driver_family_bindings",
        lambda resolved: (
            bindings
            if resolved is settings
            else (_ for _ in ()).throw(AssertionError())
        ),
    )

    class _Manifest:
        def model_dump(self, *, mode: str) -> dict[str, object]:
            assert mode == "json"
            return {"records": [{"status": "blocked"}]}

    def _run(requests, **kwargs):
        observed["requests"] = tuple(requests)
        observed["kwargs"] = kwargs
        return _Manifest()

    monkeypatch.setattr(
        valuation_workup_service,
        "run_persisted_valuation_workups",
        _run,
    )

    payload = run_reconciled_valuation_workup_payload(
        "MSFT",
        execution_run_id="execution:api",
        analysis_as_of=date(2026, 7, 26),
        captured_at="2026-07-26T20:00:00Z",
        force_refresh=True,
    )

    assert observed["requests"] == ("MSFT",)
    kwargs = observed["kwargs"]
    assert kwargs["bindings"] is bindings
    assert kwargs["max_workers"] == 1
    assert kwargs["max_in_flight"] == 1
    assert kwargs["batch_run_id"] == "execution:api"
    assert kwargs["force_refresh"] is True
    assert payload == {
        "execution_run_id": "execution:api",
        "provider": "openrouter",
        "primary_model": "primary",
        "critic_model": "critic",
        "manifest": {"records": [{"status": "blocked"}]},
    }


def test_valuation_run_endpoint_uses_background_no_drop_path(
    monkeypatch,
) -> None:
    from api.main import app

    calls: list[dict[str, object]] = []

    def _run_payload(ticker: str, **kwargs: object) -> dict[str, object]:
        calls.append({"ticker": ticker, **kwargs})
        return {
            "execution_run_id": kwargs["execution_run_id"],
            "manifest": {
                "requested_count": 1,
                "unique_count": 1,
                "records": [
                    {
                        "ticker": ticker,
                        "status": "provisional",
                        "reason_code": "valuation.provisional",
                    }
                ],
            },
        }

    monkeypatch.setattr(
        "api.main.run_reconciled_valuation_workup_payload",
        _run_payload,
        raising=False,
    )
    client = TestClient(app)

    response = client.post(
        "/api/tickers/msft/valuation/run",
        json={
            "analysis_as_of": "2026-07-26",
            "force_refresh": True,
        },
    )

    assert response.status_code == 202
    queued = response.json()
    assert queued["ticker"] == "MSFT"
    assert queued["status"] == "queued"
    run_id = queued["run_id"]

    for _ in range(40):
        status = client.get(f"/api/runs/{run_id}")
        assert status.status_code == 200
        payload = status.json()
        if payload["status"] == "completed":
            assert payload["result"]["execution_run_id"] == run_id
            assert payload["result"]["manifest"]["records"][0][
                "ticker"
            ] == "MSFT"
            break
        time.sleep(0.01)
    else:  # pragma: no cover - diagnostic guard
        raise AssertionError("valuation run never completed")

    assert len(calls) == 1
    assert calls[0]["ticker"] == "MSFT"
    assert calls[0]["execution_run_id"] == run_id
    assert calls[0]["analysis_as_of"] == date(2026, 7, 26)
    assert calls[0]["force_refresh"] is True
    assert isinstance(calls[0]["captured_at"], str)


def test_valuation_run_endpoint_requires_an_as_of_date() -> None:
    from api.main import app

    client = TestClient(app)

    missing = client.post("/api/tickers/MSFT/valuation/run", json={})
    invalid = client.post(
        "/api/tickers/MSFT/valuation/run",
        json={"analysis_as_of": "not-a-date"},
    )

    assert missing.status_code == 422
    assert invalid.status_code == 422
