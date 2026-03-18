"""Tests for Beneish M-Score and Altman Z-Score forensic signals."""
import pytest

from src.stage_03_judgment.forensic_scores import (
    compute_beneish_m_score,
    compute_altman_z_score,
    compute_forensic_signals,
)

# ---------------------------------------------------------------------------
# Synthetic financial history — newest first, values in millions
# ---------------------------------------------------------------------------

SYNTH_HIST = {
    "revenue":      [50000.0, 45000.0, 40000.0],
    "gross_profit": [15000.0, 13000.0, 11500.0],
    "net_income":   [3000.0,  2500.0,  2000.0],
    "total_assets": [80000.0, 75000.0, 70000.0],
    "capex":        [2000.0,  1800.0,  1600.0],
    "da":           [3000.0,  2800.0,  2500.0],
    "cffo":         [5000.0,  4500.0,  4000.0],
}


# ---------------------------------------------------------------------------
# Beneish M-Score tests
# ---------------------------------------------------------------------------

def test_beneish_m_score_returns_dict():
    result = compute_beneish_m_score(SYNTH_HIST)
    assert isinstance(result, dict)
    assert "m_score" in result
    assert "zone" in result


def test_beneish_m_score_zone_values():
    result = compute_beneish_m_score(SYNTH_HIST)
    valid_zones = {"manipulator", "grey", "non_manipulator", "unavailable"}
    assert result["zone"] in valid_zones


def test_beneish_sgi_computed():
    """SGI = rev_t / rev_p = 50000 / 45000 ≈ 1.111."""
    result = compute_beneish_m_score(SYNTH_HIST)
    components = result["components"]
    assert "SGI" in components
    assert components["SGI"] is not None
    assert components["SGI"] == pytest.approx(50000 / 45000, rel=1e-4)


def test_beneish_depi_computed():
    """DEPI should be computed and non-None given full da + capex series."""
    result = compute_beneish_m_score(SYNTH_HIST)
    components = result["components"]
    assert "DEPI" in components
    assert components["DEPI"] is not None


def test_beneish_tata_computed():
    """TATA = (net_income - cffo) / total_assets = (3000 - 5000) / 80000 = -0.025."""
    result = compute_beneish_m_score(SYNTH_HIST)
    components = result["components"]
    assert "TATA" in components
    assert components["TATA"] is not None
    assert components["TATA"] == pytest.approx(-0.025, rel=1e-4)


# ---------------------------------------------------------------------------
# Altman Z-Score tests
# ---------------------------------------------------------------------------

def test_altman_z_score_returns_dict():
    result = compute_altman_z_score(SYNTH_HIST, market_cap_mm=45000.0)
    assert isinstance(result, dict)
    assert "z_score" in result
    assert "zone" in result


def test_altman_zone_values():
    result = compute_altman_z_score(SYNTH_HIST, market_cap_mm=45000.0)
    valid_zones = {"safe", "grey", "distress", "unavailable"}
    assert result["zone"] in valid_zones


# ---------------------------------------------------------------------------
# Combined forensic_signals tests
# ---------------------------------------------------------------------------

def test_forensic_signals_combined():
    result = compute_forensic_signals(SYNTH_HIST, market_cap_mm=45000.0)
    assert isinstance(result, dict)
    assert "forensic_flag" in result
    assert result["forensic_flag"] in ("green", "amber", "red")


def test_forensic_missing_data_returns_unavailable():
    """Empty hist dict must not raise and must signal unavailability."""
    result = compute_forensic_signals({}, market_cap_mm=None)
    assert isinstance(result, dict)
    # Should not crash
    assert "forensic_flag" in result
    # Beneish and Altman sub-dicts must be present
    assert "beneish" in result
    assert "altman" in result
    # Neither score should claim to be available
    assert result["beneish"].get("available") is False
    assert result["altman"].get("available") is False


def test_forensic_m_score_manipulation_flag():
    """
    Construct a hist where NI >> CFFO and total_assets are small, producing a
    large positive TATA.  SGI and GMI also flag deteriorating quality.
    Expected: TATA ≈ (8000-100)/9000 ≈ 0.878; combined score pushes into grey
    or manipulator zone (M-Score > -2.50).
    """
    suspicious_hist = {
        # Rapid revenue growth — SGI = 15000/10000 = 1.5
        "revenue":      [15000.0, 10000.0],
        # Gross margin deterioration — GMI > 1 (prior GM was higher)
        "gross_profit": [3000.0,  3200.0],   # GM_p=32%, GM_t=20% → GMI=1.6
        # Very high NI relative to CFFO
        "net_income":   [8000.0,  2000.0],
        # Small total assets to amplify TATA ratio
        "total_assets": [9000.0,  8500.0],
        "capex":        [500.0,   400.0],
        "da":           [600.0,   500.0],    # DEPI ≈ (500/900)/(600/1100) = 1.018
        "cffo":         [100.0,   1500.0],   # tiny CFFO → TATA = (8000-100)/9000 ≈ 0.878
    }
    result = compute_beneish_m_score(suspicious_hist)
    assert result["zone"] in ("grey", "manipulator"), (
        f"Expected grey or manipulator, got {result['zone']} "
        f"(m_score={result['m_score']}, components={result['components']})"
    )
