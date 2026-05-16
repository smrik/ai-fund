import pytest
from src.contracts.peer_universe import PeerCandidate, PeerUniverse, InclusionState


def test_peer_candidate_core_when_both_sector_and_industry_match():
    """Both sector + industry match → sector_score=1.0 → should reach core threshold."""
    c = PeerCandidate(
        target_ticker="AAPL",
        peer_ticker="MSFT",
        sources=["ciq"],
        sector_match=True,
        industry_match=True,
        business_description_similarity=0.80,
        metric_similarity=0.72,
        size_similarity=0.65,
        growth_similarity=0.60,
        margin_similarity=0.70,
        capital_intensity_similarity=0.55,
    )
    # composite = 0.80*0.35 + 0.72*0.35 + 1.0*0.15 + 0.65*0.15 = 0.28+0.252+0.15+0.0975 = 0.7795
    assert c.composite_score == pytest.approx(0.7795, abs=0.01)
    assert c.inclusion_state == InclusionState.core


def test_peer_candidate_peripheral_when_sector_only():
    """sector_match only (no industry) → sector_score=0.6 → peripheral range."""
    c = PeerCandidate(
        target_ticker="AAPL",
        peer_ticker="GOOG",
        sources=["ciq"],
        sector_match=True,
        industry_match=False,
        business_description_similarity=0.70,
        metric_similarity=0.65,
        size_similarity=0.60,
        growth_similarity=0.55,
        margin_similarity=0.60,
        capital_intensity_similarity=0.50,
    )
    # composite = 0.70*0.35 + 0.65*0.35 + 0.6*0.15 + 0.60*0.15 = 0.245+0.2275+0.09+0.09 = 0.6525
    assert c.composite_score == pytest.approx(0.6525, abs=0.01)
    assert c.inclusion_state == InclusionState.peripheral


def test_peer_candidate_excluded_below_threshold():
    c = PeerCandidate(
        target_ticker="X", peer_ticker="Y", sources=["test"],
        sector_match=False, industry_match=False,
        business_description_similarity=0.30, metric_similarity=0.30,
        size_similarity=0.30, growth_similarity=0.30,
        margin_similarity=0.30, capital_intensity_similarity=0.30,
    )
    assert c.inclusion_state == InclusionState.excluded


def test_peer_universe_core_peers_list():
    c = PeerCandidate(
        target_ticker="AAPL", peer_ticker="MSFT", sources=["ciq"],
        sector_match=True, industry_match=True,
        business_description_similarity=0.90, metric_similarity=0.85,
        size_similarity=0.80, growth_similarity=0.75,
        margin_similarity=0.80, capital_intensity_similarity=0.70,
    )
    u = PeerUniverse(target_ticker="AAPL", candidates=[c])
    assert "MSFT" in u.core_peers
    assert u.peripheral_peers == []


def test_peer_universe_round_trip():
    c = PeerCandidate(
        target_ticker="AAPL", peer_ticker="MSFT", sources=["ciq"],
        sector_match=True, industry_match=True,
        business_description_similarity=0.9, metric_similarity=0.8,
        size_similarity=0.7, growth_similarity=0.7,
        margin_similarity=0.8, capital_intensity_similarity=0.6,
    )
    u = PeerUniverse(target_ticker="AAPL", candidates=[c])
    dumped = u.model_dump(mode="json")
    restored = PeerUniverse.model_validate(dumped)
    assert restored.target_ticker == "AAPL"
    assert restored.core_peers == ["MSFT"]


def test_pm_override_promotes_excluded_peer():
    c = PeerCandidate(
        target_ticker="X", peer_ticker="Y", sources=["pm"],
        sector_match=False, industry_match=False,
        business_description_similarity=0.20, metric_similarity=0.20,
        size_similarity=0.20, growth_similarity=0.20,
        margin_similarity=0.20, capital_intensity_similarity=0.20,
        pm_override_state="included",
        pm_override_reason="Closest proxy available",
    )
    assert c.inclusion_state == InclusionState.excluded    # raw score still low
    assert c.effective_inclusion == InclusionState.core    # PM override wins


def test_tickers_uppercased():
    c = PeerCandidate(
        target_ticker="aapl", peer_ticker="msft", sources=[],
        sector_match=True, industry_match=True,
        business_description_similarity=0.8, metric_similarity=0.8,
        size_similarity=0.8, growth_similarity=0.8,
        margin_similarity=0.8, capital_intensity_similarity=0.8,
    )
    assert c.target_ticker == "AAPL"
    assert c.peer_ticker == "MSFT"
