from __future__ import annotations


def test_build_multiples_dashboard_view_returns_target_historical_multiple_series(monkeypatch):
    from src.stage_04_pipeline import multiples_dashboard

    monkeypatch.setattr(
        multiples_dashboard.market_data,
        "get_market_data",
        lambda ticker: {
            "ticker": "IBM",
            "name": "IBM",
            "current_price": 100.0,
            "market_cap": 1_000.0,
            "enterprise_value": 1_200.0,
            "pe_trailing": 20.0,
            "ev_ebitda": 10.0,
            "ev_revenue": 4.0,
            "price_to_book": 2.0,
            "price_to_sales": 3.0,
        },
    )
    monkeypatch.setattr(
        multiples_dashboard.market_data,
        "get_price_history",
        lambda ticker, period="5y": [
            {"date": "2022-12-31", "close": 80.0},
            {"date": "2023-12-31", "close": 90.0},
            {"date": "2024-12-31", "close": 110.0},
            {"date": "2025-12-31", "close": 120.0},
            {"date": "2026-03-15", "close": 100.0},
        ],
    )

    view = multiples_dashboard.build_multiples_dashboard_view("IBM", period="5y")

    assert view["available"] is True
    assert view["history_points"] == 5
    assert set(view["metrics"]) == {"pe_trailing", "ev_ebitda", "ev_revenue", "price_to_book"}
    pe_series = view["metrics"]["pe_trailing"]["series"]
    assert pe_series[0]["multiple"] == 16.0
    assert pe_series[-1]["multiple"] == 20.0
    assert view["metrics"]["pe_trailing"]["summary"]["current"] == 20.0
    assert view["metrics"]["ev_ebitda"]["summary"]["max"] > view["metrics"]["ev_ebitda"]["summary"]["min"]
    assert view["metrics"]["price_to_book"]["summary"]["current_percentile"] is not None


def test_build_multiples_dashboard_view_handles_missing_inputs(monkeypatch):
    from src.stage_04_pipeline import multiples_dashboard

    monkeypatch.setattr(
        multiples_dashboard.market_data,
        "get_market_data",
        lambda ticker: {"ticker": "IBM", "name": "IBM", "current_price": None},
    )
    monkeypatch.setattr(
        multiples_dashboard.market_data,
        "get_price_history",
        lambda ticker, period="5y": [],
    )

    view = multiples_dashboard.build_multiples_dashboard_view("IBM", period="5y")

    assert view["available"] is False
    assert "Current price unavailable for historical multiples" in view["audit_flags"]
