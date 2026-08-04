from __future__ import annotations

from fastapi.testclient import TestClient


def test_terminal_outcomes_endpoint_exposes_bounded_read_only_history(
    monkeypatch,
) -> None:
    from api.main import app

    calls: list[tuple[str, int]] = []

    def _payload(ticker: str, *, limit: int) -> dict[str, object]:
        calls.append((ticker, limit))
        if not 1 <= limit <= 250:
            raise ValueError("limit must be between 1 and 250")
        return {
            "ticker": ticker,
            "count": 1,
            "limit": limit,
            "outcomes": [
                {
                    "outcome_id": "outcome:001",
                    "execution_run_id": "execution:001",
                    "status": "provisional",
                    "reason_code": "valuation.provisional",
                    "analysis_snapshot_hash": "snapshot:001",
                }
            ],
        }

    monkeypatch.setattr(
        "api.main.build_ticker_terminal_outcomes_payload",
        _payload,
        raising=False,
    )
    client = TestClient(app)

    response = client.get(
        "/api/tickers/msft/valuation/outcomes",
        params={"limit": 7},
    )

    assert response.status_code == 200
    assert calls == [("MSFT", 7)]
    assert response.json() == {
        "ticker": "MSFT",
        "count": 1,
        "limit": 7,
        "outcomes": [
            {
                "outcome_id": "outcome:001",
                "execution_run_id": "execution:001",
                "status": "provisional",
                "reason_code": "valuation.provisional",
                "analysis_snapshot_hash": "snapshot:001",
            }
        ],
    }
    assert client.post(
        "/api/tickers/MSFT/valuation/outcomes"
    ).status_code == 405
    invalid_limit = client.get(
        "/api/tickers/MSFT/valuation/outcomes",
        params={"limit": 251},
    )
    assert invalid_limit.status_code == 400
