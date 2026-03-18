import math

import pytest

from src.stage_02_valuation.wacc import (
    PeerData,
    SIZE_PREMIA,
    _get_size_premium,
    compute_wacc,
    relever_beta,
    unlever_beta,
)


def test_unlever_beta_known_value():
    beta_u = unlever_beta(1.2, 0.5, 0.21)
    assert beta_u == pytest.approx(0.8602, rel=1e-3)


def test_relever_beta_known_value():
    beta_l = relever_beta(0.860215, 0.5, 0.21)
    assert beta_l == pytest.approx(1.2, rel=1e-3)


def test_unlever_relever_round_trip():
    original = 1.35
    de_ratio = 0.42
    tax_rate = 0.25
    unlevered = unlever_beta(original, de_ratio, tax_rate)
    relevered = relever_beta(unlevered, de_ratio, tax_rate)
    assert relevered == pytest.approx(original, rel=1e-9)


@pytest.mark.parametrize(
    "market_cap,expected",
    [
        # >= 75B → interpolated floor (0.0)
        (80_000_000_000.0, 0.000),
        # 20B: between 6B (1.0%) and 30B (0.5%) → alpha=14/24 → ~0.7083%
        (20_000_000_000.0, pytest.approx(0.007083, rel=1e-3)),
        # 5B: between 1.25B (1.5%) and 6B (1.0%) → alpha=3.75/4.75 → ~1.105%
        (5_000_000_000.0, pytest.approx(0.011053, rel=1e-3)),
        # 1B: between 250M (2.5%) and 1.25B (1.5%) → alpha=0.75 → 1.75%
        (1_000_000_000.0, pytest.approx(0.01750, rel=1e-3)),
        # <= 250M → interpolated ceiling (2.5%)
        (100_000_000.0, 0.025),
        (None, SIZE_PREMIA["mid"]),
        (-1.0, SIZE_PREMIA["mid"]),
    ],
)
def test_get_size_premium_brackets(market_cap, expected):
    assert _get_size_premium(market_cap) == expected


def test_compute_wacc_with_peer_median_beta():
    target = PeerData(ticker="TGT", market_cap=10_000_000_000.0, total_debt=2_000_000_000.0, cash=0.0, cost_of_debt=0.06, tax_rate=0.21)
    peers = [
        PeerData(ticker="P1", beta=1.2, market_cap=20_000_000_000.0, total_debt=5_000_000_000.0, cash=1_000_000_000.0, tax_rate=0.21),
        PeerData(ticker="P2", beta=0.8, market_cap=8_000_000_000.0, total_debt=1_000_000_000.0, cash=0.0, tax_rate=0.21),
        PeerData(ticker="P3", beta=1.5, market_cap=30_000_000_000.0, total_debt=10_000_000_000.0, cash=2_000_000_000.0, tax_rate=0.21),
    ]

    result = compute_wacc(target, peers)

    assert result.beta_unlevered_median == pytest.approx(1.0364, rel=1e-3)
    assert result.beta_relevered == pytest.approx(1.2002, rel=1e-3)
    # 10B target: size_premium = 0.010 + (4/24) * (0.005-0.010) = 0.009167 (interpolated)
    # cost_of_equity = 0.045 + 1.2002 * 0.05 + 0.009167 = 0.11418
    assert result.cost_of_equity == pytest.approx(0.11418, rel=1e-3)
    assert result.wacc == pytest.approx(0.10305, rel=1e-3)


def test_compute_wacc_self_beta_fallback_when_no_peers():
    target = PeerData(ticker="SELF", beta=1.1, market_cap=5_000_000_000.0, total_debt=1_000_000_000.0, cash=0.0)

    result = compute_wacc(target, [])

    assert result.peers_used == ["SELF (self)"]
    assert result.beta_unlevered_median < 1.1
    assert result.beta_relevered > result.beta_unlevered_median


def test_compute_wacc_market_beta_fallback_when_no_beta():
    target = PeerData(ticker="NOBETA", beta=None, market_cap=5_000_000_000.0, total_debt=0.0, cash=0.0)

    result = compute_wacc(target, [])

    assert result.peers_used == ["market (fallback)"]
    assert result.beta_unlevered_median == 1.0


def test_compute_wacc_zero_debt_company_has_full_equity_weight():
    target = PeerData(ticker="NODEBT", beta=1.0, market_cap=3_000_000_000.0, total_debt=0.0, cash=0.0)
    peers = [PeerData(ticker="P", beta=1.0, market_cap=4_000_000_000.0, total_debt=0.0, cash=0.0)]

    result = compute_wacc(target, peers)

    assert result.debt_weight == 0.0
    assert result.equity_weight == 1.0


def test_compute_wacc_populates_audit_trail_fields():
    target = PeerData(ticker="AUD", beta=1.0, market_cap=6_000_000_000.0, total_debt=1_000_000_000.0, cash=200_000_000.0)
    peers = [PeerData(ticker="P", beta=1.1, market_cap=7_000_000_000.0, total_debt=1_000_000_000.0, cash=100_000_000.0)]

    result = compute_wacc(target, peers)

    assert isinstance(result.peers_used, list)
    assert len(result.peers_used) >= 1
    assert isinstance(result.peer_betas_unlevered, list)
    assert len(result.peer_betas_unlevered) >= 1
    assert result.target_market_cap == 6_000_000_000.0
    assert result.target_net_debt == 800_000_000.0
    assert result.target_de_ratio > 0
