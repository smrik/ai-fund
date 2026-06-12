from __future__ import annotations

from types import SimpleNamespace

from src.stage_02_valuation.public_comps_fallback import (
    build_public_market_fallback_comps_detail,
    fallback_peer_tickers,
)


def test_fallback_peer_tickers_prefers_explicit_peers():
    assert fallback_peer_tickers("TEST", "Technology", explicit_peers=["AAA", "TEST", "bbb"]) == ["AAA", "BBB"]


def test_build_public_market_fallback_comps_detail_builds_medians_and_lineage():
    market_data_client = SimpleNamespace(
        get_peer_multiples=lambda peers: [
            {"ticker": "AAA", "market_cap_mm": 1000.0, "ev_ebitda": 10.0, "pe_trailing": 18.0},
            {"ticker": "BBB", "market_cap_mm": 1200.0, "ev_ebitda": 14.0, "pe_trailing": 20.0},
            {"ticker": "CCC", "market_cap_mm": 1400.0, "ev_ebitda": 16.0, "pe_trailing": 22.0},
        ],
    )

    detail = build_public_market_fallback_comps_detail(
        "TEST",
        market={
            "ticker": "TEST",
            "current_price": 100.0,
            "sector": "Technology",
            "revenue_ttm": 1_000_000_000.0,
            "operating_margin": 0.20,
            "pe_trailing": 25.0,
            "ev_ebitda": 12.0,
        },
        explicit_peers=["AAA", "BBB", "CCC"],
        market_data_client=market_data_client,
    )

    assert detail is not None
    assert detail["medians"]["tev_ebitda_ltm"] == 14.0
    assert detail["medians"]["pe_ltm"] == 20.0
    assert detail["source_lineage"]["source"] == "public_market_yfinance_fallback"
    assert detail["source_lineage"]["peer_universe"] == ["AAA", "BBB", "CCC"]
    assert detail["target"]["eps_ltm"] == 4.0
