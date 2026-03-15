from __future__ import annotations

from types import SimpleNamespace


def test_build_comps_dashboard_view_returns_metric_switching_and_football_field(monkeypatch):
    from src.stage_04_pipeline import comps_dashboard

    monkeypatch.setattr(
        comps_dashboard,
        "get_ciq_comps_detail",
        lambda ticker: {
            "target": {
                "ticker": "IBM",
                "market_cap_mm": 100000.0,
                "tev_mm": 120000.0,
                "tev_ebitda_ltm": 10.5,
                "tev_ebitda_fwd": 9.9,
                "tev_ebit_ltm": 14.2,
                "pe_ltm": 18.1,
                "ebitda_ltm_mm": 11428.6,
                "ebit_ltm_mm": 8450.0,
                "source_file": "ibm_snapshot.xlsx",
                "as_of_date": "2026-03-15",
            },
            "peers": [
                {
                    "ticker": "ORCL",
                    "tev_ebitda_ltm": 11.0,
                    "tev_ebit_ltm": 16.0,
                    "pe_ltm": 20.0,
                    "revenue_growth": 0.07,
                    "ebit_margin": 0.27,
                    "net_debt_to_ebitda": 1.8,
                },
                {
                    "ticker": "ACN",
                    "tev_ebitda_ltm": 13.0,
                    "tev_ebit_ltm": 18.0,
                    "pe_ltm": 24.0,
                    "revenue_growth": 0.05,
                    "ebit_margin": 0.18,
                    "net_debt_to_ebitda": 0.6,
                },
            ],
            "medians": {
                "tev_ebitda_ltm": 12.0,
                "tev_ebit_ltm": 17.0,
                "pe_ltm": 22.0,
            },
        },
    )
    monkeypatch.setattr(
        comps_dashboard.market_data,
        "get_market_data",
        lambda ticker: {
            "name": "IBM",
            "sector": "Technology",
            "industry": "IT Services",
            "current_price": 105.0,
            "shares_outstanding": 900_000_000,
            "analyst_target_mean": 118.0,
            "revenue_growth": 0.03,
            "operating_margin": 0.16,
        },
    )
    monkeypatch.setattr(
        comps_dashboard.peer_similarity,
        "score_peer_similarity",
        lambda ticker, peers, embedding_model: {"ACN": 0.8, "ORCL": 0.4},
    )
    monkeypatch.setattr(
        comps_dashboard,
        "run_comps_model",
        lambda comps_detail, net_debt_mm=None, shares_mm=None, similarity_scores=None: SimpleNamespace(
            bear_iv=95.0,
            base_iv=110.0,
            bull_iv=125.0,
            blended_base_iv=108.0,
            primary_metric="tev_ebitda_ltm",
            similarity_method="embedding_cosine",
            similarity_model="all-MiniLM-L6-v2",
            weighting_formula="0.60*description_similarity + 0.40*market_cap_proximity",
            notes="primary=tev_ebitda_ltm",
            peer_count_raw=2,
            peer_count_clean=1,
            metrics={
                "tev_ebitda_ltm": SimpleNamespace(
                    outliers_removed=["ORCL"],
                    bear_multiple=10.0,
                    base_multiple=11.5,
                    bull_multiple=12.5,
                    bear_iv=95.0,
                    base_iv=110.0,
                    bull_iv=125.0,
                ),
                "pe_ltm": SimpleNamespace(
                    outliers_removed=[],
                    bear_multiple=19.0,
                    base_multiple=21.0,
                    bull_multiple=24.0,
                    bear_iv=98.0,
                    base_iv=112.0,
                    bull_iv=129.0,
                ),
            },
        ),
    )
    monkeypatch.setattr(
        comps_dashboard,
        "build_multiples_dashboard_view",
        lambda ticker, period="5y": {
            "available": True,
            "period": period,
            "metrics": {
                "pe_trailing": {
                    "current": 18.1,
                    "summary": {"current_percentile": 0.65},
                }
            },
        },
    )

    view = comps_dashboard.build_comps_dashboard_view("IBM")

    assert view["available"] is True
    assert view["selected_metric_default"] == "tev_ebitda_ltm"
    assert {option["key"] for option in view["metric_options"]} == {"tev_ebitda_ltm", "pe_ltm"}
    assert view["valuation_range_by_metric"]["tev_ebitda_ltm"]["base"] == 110.0
    assert view["valuation_range_by_metric"]["pe_ltm"]["bull"] == 129.0
    assert view["target_vs_peers"]["peer_medians"]["tev_ebitda_ltm"] == 12.0
    assert view["target_vs_peers"]["target"]["revenue_growth"] == 0.03
    assert round(view["target_vs_peers"]["deltas"]["tev_ebitda_ltm"], 2) == -1.5
    assert round(view["target_vs_peers"]["deltas"]["net_debt_to_ebitda"], 2) == 0.55
    assert view["football_field"]["range_min"] == 95.0
    assert view["football_field"]["range_max"] == 129.0
    labels = {marker["label"] for marker in view["football_field"]["markers"]}
    assert "Current Price" in labels
    assert "Analyst Target Mean" in labels
    assert "TEV / EBITDA LTM Base" in labels
    assert view["historical_multiples_summary"]["metrics"]["pe_trailing"]["summary"]["current_percentile"] == 0.65
    assert view["compare_to_target"]["target"]["tev_ebitda_ltm"] == 10.5
    assert "Outliers removed from tev_ebitda_ltm: ORCL" in view["audit_flags"]
    assert abs(sum(row["model_weight"] for row in view["peers"]) - 1.0) < 1e-9


def test_build_comps_dashboard_view_survives_similarity_failure(monkeypatch):
    from src.stage_04_pipeline import comps_dashboard

    monkeypatch.setattr(
        comps_dashboard,
        "get_ciq_comps_detail",
        lambda ticker: {
            "target": {"ticker": "IBM", "market_cap_mm": 100000.0, "tev_mm": 120000.0},
            "peers": [{"ticker": "ORCL"}],
            "medians": {},
        },
    )
    monkeypatch.setattr(
        comps_dashboard.market_data,
        "get_market_data",
        lambda ticker: {"current_price": 105.0, "shares_outstanding": 900_000_000},
    )
    monkeypatch.setattr(
        comps_dashboard.peer_similarity,
        "score_peer_similarity",
        lambda ticker, peers, embedding_model: (_ for _ in ()).throw(RuntimeError("embedding cache offline")),
    )
    monkeypatch.setattr(comps_dashboard, "run_comps_model", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        comps_dashboard,
        "build_multiples_dashboard_view",
        lambda ticker, period="5y": {"available": False, "metrics": {}, "audit_flags": ["history unavailable"]},
    )

    view = comps_dashboard.build_comps_dashboard_view("IBM")

    assert view["available"] is True
    assert "Peer similarity unavailable: embedding cache offline" in view["audit_flags"]
    assert view["historical_multiples_summary"]["available"] is False


def test_build_comps_dashboard_view_handles_missing_ciq_data(monkeypatch):
    from src.stage_04_pipeline import comps_dashboard

    monkeypatch.setattr(comps_dashboard, "get_ciq_comps_detail", lambda ticker: None)

    view = comps_dashboard.build_comps_dashboard_view("ibm")

    assert view["ticker"] == "IBM"
    assert view["available"] is False
    assert view["target"] == {}
    assert view["peers"] == []
    assert view["valuation_range"] == {}
    assert view["valuation_range_by_metric"] == {}
    assert view["football_field"]["markers"] == []
    assert view["audit_flags"] == ["No CIQ comps detail available"]
