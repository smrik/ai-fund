"""Tests for src/stage_02_valuation/comps_model.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from src.stage_02_valuation.comps_model import (
    CompsResult,
    PeerMultipleResult,
    _iqr_clean,
    _percentile,
    _weighted_percentile,
    _similarity_weights,
    _weighted_median,
    _ev_multiple_to_price,
    _pe_to_price,
    _select_primary,
    run_comps_model,
)


# ── _percentile ───────────────────────────────────────────────────────────────

def test_percentile_single():
    assert _percentile([5.0], 0.5) == 5.0


def test_percentile_interpolation():
    vals = [0.0, 10.0]
    assert _percentile(vals, 0.0) == 0.0
    assert _percentile(vals, 1.0) == 10.0
    assert _percentile(vals, 0.5) == 5.0


def test_percentile_four_values():
    vals = [1.0, 2.0, 3.0, 4.0]
    assert _percentile(vals, 0.25) == pytest.approx(1.75, abs=1e-9)
    assert _percentile(vals, 0.75) == pytest.approx(3.25, abs=1e-9)


def test_percentile_raises_on_empty():
    with pytest.raises(ValueError):
        _percentile([], 0.5)


# ── _iqr_clean ────────────────────────────────────────────────────────────────

def test_iqr_clean_removes_outlier():
    values = [10.0, 11.0, 12.0, 13.0, 100.0]
    tickers = ["A", "B", "C", "D", "OUTLIER"]
    clean_v, clean_t, removed = _iqr_clean(values, tickers)
    assert "OUTLIER" in removed
    assert 100.0 not in clean_v


def test_iqr_clean_skips_when_fewer_than_4():
    values = [10.0, 11.0, 100.0]
    tickers = ["A", "B", "C"]
    clean_v, clean_t, removed = _iqr_clean(values, tickers)
    assert clean_v == values  # no cleaning with < 4 obs
    assert removed == []


def test_iqr_clean_tight_cluster_no_removal():
    values = [10.0, 10.5, 11.0, 11.5]
    tickers = ["A", "B", "C", "D"]
    clean_v, _, removed = _iqr_clean(values, tickers)
    assert removed == []
    assert len(clean_v) == 4


# ── _similarity_weights ───────────────────────────────────────────────────────

def test_similarity_weights_equal_size():
    caps = [5000.0, 5000.0, 5000.0]
    weights = _similarity_weights(caps, target_mktcap=5000.0)
    assert len(weights) == 3
    assert all(w == pytest.approx(1 / 3, abs=1e-9) for w in weights)


def test_similarity_weights_closer_peer_higher_weight():
    caps = [500.0, 5000.0]   # target is 5000
    weights = _similarity_weights(caps, target_mktcap=5000.0)
    assert weights[1] > weights[0]  # peer at 5000 should outweigh peer at 500


def test_similarity_weights_sum_to_one():
    caps = [1000.0, 3000.0, 8000.0, None]
    weights = _similarity_weights(caps, target_mktcap=4000.0)
    assert sum(weights) == pytest.approx(1.0, abs=1e-9)


def test_similarity_weights_no_target_returns_equal():
    caps = [1000.0, 2000.0, 3000.0]
    weights = _similarity_weights(caps, target_mktcap=None)
    assert all(w == pytest.approx(1 / 3, abs=1e-9) for w in weights)


def test_similarity_weights_blend_business_similarity_with_market_cap():
    caps = [5000.0, 5000.0]
    weights = _similarity_weights(
        caps,
        target_mktcap=5000.0,
        similarity_scores=[0.10, 0.90],
        market_cap_blend_weight=0.40,
        description_blend_weight=0.60,
    )
    assert sum(weights) == pytest.approx(1.0, abs=1e-9)
    assert weights[1] > weights[0]


# ── _weighted_median ──────────────────────────────────────────────────────────

def test_weighted_median_equal_weights():
    vals = [1.0, 2.0, 3.0]
    weights = [1 / 3, 1 / 3, 1 / 3]
    result = _weighted_median(vals, weights)
    assert result == 2.0


def test_weighted_median_heavy_on_low():
    vals = [1.0, 2.0, 3.0]
    weights = [0.8, 0.1, 0.1]
    result = _weighted_median(vals, weights)
    assert result == 1.0  # median shifts to low end due to weight


def test_weighted_median_single():
    assert _weighted_median([42.0], [1.0]) == 42.0


def test_weighted_percentile_biases_toward_high_weight_value():
    vals = [8.0, 10.0, 12.0]
    weights = [0.1, 0.2, 0.7]
    assert _weighted_percentile(vals, weights, 0.25) > 9.0
    assert _weighted_percentile(vals, weights, 0.75) >= 12.0


# ── _ev_multiple_to_price ─────────────────────────────────────────────────────

def test_ev_multiple_to_price_basic():
    # 10× EBITDA of 1000mm, net debt 2000mm, 100mm shares
    # EV = 10000mm; equity = 8000mm; price = 80
    price = _ev_multiple_to_price(10.0, 1000.0, 2000.0, 100.0)
    assert price == pytest.approx(80.0, abs=1e-6)


def test_ev_multiple_to_price_zero_shares():
    assert _ev_multiple_to_price(10.0, 1000.0, 0.0, 0.0) is None


# ── _pe_to_price ──────────────────────────────────────────────────────────────

def test_pe_to_price_basic():
    assert _pe_to_price(20.0, 5.0) == pytest.approx(100.0)


def test_pe_to_price_negative_eps():
    assert _pe_to_price(20.0, -1.0) is None


# ── _select_primary ───────────────────────────────────────────────────────────

def test_select_primary_prefers_forward():
    metrics = {
        "tev_ebitda_ltm": PeerMultipleResult(
            metric="tev_ebitda_ltm", n_raw=5, n_clean=4, outliers_removed=[],
            bear_multiple=8.0, base_multiple=10.0, bull_multiple=12.0,
            bear_iv=80.0, base_iv=100.0, bull_iv=120.0,
        ),
        "tev_ebitda_fwd": PeerMultipleResult(
            metric="tev_ebitda_fwd", n_raw=5, n_clean=3, outliers_removed=[],
            bear_multiple=7.0, base_multiple=9.0, bull_multiple=11.0,
            bear_iv=70.0, base_iv=90.0, bull_iv=110.0,
        ),
    }
    assert _select_primary(metrics) == "tev_ebitda_fwd"


def test_select_primary_falls_back_when_fwd_insufficient():
    # Only 1 clean peer for fwd — falls back to LTM
    metrics = {
        "tev_ebitda_fwd": PeerMultipleResult(
            metric="tev_ebitda_fwd", n_raw=1, n_clean=1, outliers_removed=[],
            bear_multiple=9.0, base_multiple=9.0, bull_multiple=9.0,
            bear_iv=90.0, base_iv=90.0, bull_iv=90.0,
        ),
        "tev_ebitda_ltm": PeerMultipleResult(
            metric="tev_ebitda_ltm", n_raw=4, n_clean=3, outliers_removed=[],
            bear_multiple=8.0, base_multiple=10.0, bull_multiple=12.0,
            bear_iv=80.0, base_iv=100.0, bull_iv=120.0,
        ),
    }
    assert _select_primary(metrics) == "tev_ebitda_ltm"


def test_select_primary_empty_returns_none():
    assert _select_primary({}) is None


# ── run_comps_model ───────────────────────────────────────────────────────────

def _make_comps_detail(
    ebitda_mm=1000.0,
    ebit_mm=800.0,
    eps=5.0,
    mktcap_mm=5000.0,
    tev_mm=7000.0,
    peer_tev_ebitda=None,
    peer_pe=None,
):
    """Build a minimal comps_detail dict for testing."""
    peers = []
    if peer_tev_ebitda is None:
        peer_tev_ebitda = [8.0, 9.0, 10.0, 11.0, 12.0]
    if peer_pe is None:
        peer_pe = [15.0, 18.0, 20.0, 22.0, 25.0]

    for i, (tev_e, pe) in enumerate(zip(peer_tev_ebitda, peer_pe)):
        peers.append({
            "ticker": f"PEER{i}",
            "market_cap_mm": mktcap_mm * (0.5 + i * 0.2),
            "tev_mm": None,
            "revenue_ltm_mm": None,
            "ebitda_ltm_mm": None,
            "ebit_ltm_mm": None,
            "eps_ltm": None,
            "tev_ebitda_ltm": tev_e,
            "tev_ebitda_fwd": None,
            "tev_ebit_ltm": tev_e - 1.0,
            "tev_ebit_fwd": None,
            "pe_ltm": pe,
        })

    return {
        "target": {
            "ticker": "TARGET",
            "market_cap_mm": mktcap_mm,
            "tev_mm": tev_mm,
            "revenue_ltm_mm": 5000.0,
            "ebitda_ltm_mm": ebitda_mm,
            "ebit_ltm_mm": ebit_mm,
            "eps_ltm": eps,
            "tev_ebitda_ltm": tev_mm / ebitda_mm if ebitda_mm else None,
            "tev_ebitda_fwd": None,
            "tev_ebit_ltm": None,
            "tev_ebit_fwd": None,
            "pe_ltm": None,
        },
        "peers": peers,
        "medians": {},
    }


def test_run_comps_model_returns_comps_result():
    detail = _make_comps_detail()
    result = run_comps_model(detail, net_debt_mm=2000.0, shares_mm=50.0)
    assert isinstance(result, CompsResult)
    assert result.ticker == "TARGET"
    assert result.base_iv is not None
    assert result.bear_iv <= result.base_iv <= result.bull_iv


def test_run_comps_model_bear_lt_base_lt_bull():
    detail = _make_comps_detail(peer_tev_ebitda=[8.0, 9.0, 10.0, 11.0, 12.0])
    result = run_comps_model(detail, net_debt_mm=2000.0, shares_mm=50.0)
    assert result.bear_iv < result.base_iv < result.bull_iv


def test_run_comps_model_returns_none_on_empty_detail():
    assert run_comps_model(None) is None
    assert run_comps_model({}) is None


def test_run_comps_model_returns_none_with_no_peers():
    detail = _make_comps_detail()
    detail["peers"] = []
    assert run_comps_model(detail, net_debt_mm=0.0, shares_mm=50.0) is None


def test_run_comps_model_pe_fallback_without_shares():
    """Without shares_mm, EV multiples fail; PE should still work."""
    detail = _make_comps_detail(eps=5.0)
    result = run_comps_model(detail, net_debt_mm=None, shares_mm=None)
    # With shares=0, only PE can produce IVs
    assert result is not None
    assert result.primary_metric == "pe_ltm"
    assert result.base_iv is not None


def test_run_comps_model_blended_base_is_mean_of_available():
    detail = _make_comps_detail(ebitda_mm=1000.0, ebit_mm=800.0, eps=5.0)
    result = run_comps_model(detail, net_debt_mm=2000.0, shares_mm=50.0)
    assert result is not None
    base_ivs = [m.base_iv for m in result.metrics.values() if m.base_iv is not None]
    if len(base_ivs) >= 2:
        expected = sum(base_ivs) / len(base_ivs)
        assert result.blended_base_iv == pytest.approx(expected, abs=0.0001)


def test_run_comps_model_iqr_removes_extreme_outlier():
    # 80× is within the hard cap (<100) but is an IQR outlier vs tight cluster of [9,10,11,12]
    peers_tev_ebitda = [9.0, 10.0, 11.0, 12.0, 80.0]
    detail = _make_comps_detail(peer_tev_ebitda=peers_tev_ebitda)
    result = run_comps_model(detail, net_debt_mm=2000.0, shares_mm=50.0)
    assert result is not None
    ltm_result = result.metrics.get("tev_ebitda_ltm")
    if ltm_result:
        assert "PEER4" in ltm_result.outliers_removed
        assert ltm_result.n_clean < ltm_result.n_raw


def test_run_comps_model_similarity_weighted_flag():
    detail = _make_comps_detail(mktcap_mm=5000.0)
    result = run_comps_model(detail, net_debt_mm=2000.0, shares_mm=50.0)
    assert result.similarity_weighted is True


def test_run_comps_model_uses_similarity_scores_in_result_metadata():
    detail = _make_comps_detail(
        mktcap_mm=5000.0,
        peer_tev_ebitda=[8.0, 12.0, 20.0, 21.0, 22.0],
    )
    similarity_scores = {
        "PEER0": 0.05,
        "PEER1": 0.10,
        "PEER2": 0.90,
        "PEER3": 0.85,
        "PEER4": 0.80,
    }
    result = run_comps_model(
        detail,
        net_debt_mm=2000.0,
        shares_mm=50.0,
        similarity_scores=similarity_scores,
    )
    assert result is not None
    assert result.similarity_weighted is True
    assert result.similarity_method == "embedding_cosine"
    assert result.peer_similarity_scores["PEER2"] == pytest.approx(0.90)


def test_run_comps_model_derives_net_debt_from_tev_mktcap():
    """net_debt derived as tev_mm - market_cap_mm when not provided."""
    # tev=7000, mktcap=5000 → net_debt=2000mm
    # shares=50mm, ebitda=1000mm, peer mult=10 → EV=10000mm, equity=8000mm, price=160
    detail = _make_comps_detail(ebitda_mm=1000.0, mktcap_mm=5000.0, tev_mm=7000.0,
                                  peer_tev_ebitda=[10.0, 10.0, 10.0, 10.0, 10.0])
    result = run_comps_model(detail, net_debt_mm=None, shares_mm=50.0)
    assert result is not None
    # base_iv should be 160 (10×1000 - 2000)/50
    if result.primary_metric in ("tev_ebitda_ltm", "tev_ebitda_fwd"):
        assert result.base_iv == pytest.approx(160.0, abs=1.0)
