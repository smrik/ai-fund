"""Tests for macro regime detection."""
import pytest
from unittest.mock import patch

from src.stage_02_valuation.regime_model import (
    RegimeState,
    ScenarioWeights,
    get_scenario_weights,
    REGIME_SCENARIO_WEIGHTS,
    get_regime_badge_html,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_regime(label: str, available: bool = True) -> RegimeState:
    return RegimeState(
        label=label,
        probabilities={label: 1.0},
        state_index=0,
        as_of_date="2026-03-17",
        available=available,
        error=None,
    )


# ---------------------------------------------------------------------------
# REGIME_SCENARIO_WEIGHTS table tests
# ---------------------------------------------------------------------------

def test_regime_scenario_weights_sum_to_one():
    """For every regime, bear + base + bull must sum to 1.0."""
    for label, weights in REGIME_SCENARIO_WEIGHTS.items():
        total = weights["bear"] + weights["base"] + weights["bull"]
        assert total == pytest.approx(1.0, abs=1e-9), (
            f"Weights for '{label}' sum to {total}, not 1.0"
        )


# ---------------------------------------------------------------------------
# get_scenario_weights tests
# ---------------------------------------------------------------------------

def test_get_scenario_weights_neutral_default():
    """None regime should return Neutral weights (0.20 / 0.60 / 0.20)."""
    weights = get_scenario_weights(None)
    assert weights.bear == pytest.approx(0.20)
    assert weights.base == pytest.approx(0.60)
    assert weights.bull == pytest.approx(0.20)
    assert weights.regime == "Neutral"


def test_get_scenario_weights_unavailable_regime():
    """RegimeState with available=False must return Neutral weights."""
    unavailable = _make_regime("Risk-Off", available=False)
    weights = get_scenario_weights(unavailable)
    assert weights.bear == pytest.approx(0.20)
    assert weights.base == pytest.approx(0.60)
    assert weights.bull == pytest.approx(0.20)
    assert weights.regime == "Neutral"


def test_get_scenario_weights_risk_off():
    """Risk-Off regime must return bear=0.35."""
    risk_off = _make_regime("Risk-Off")
    weights = get_scenario_weights(risk_off)
    assert weights.bear == pytest.approx(0.35)
    assert weights.regime == "Risk-Off"


def test_get_scenario_weights_risk_on():
    """Risk-On regime must return bull >= 0.30."""
    risk_on = _make_regime("Risk-On")
    weights = get_scenario_weights(risk_on)
    assert weights.bull >= 0.30
    assert weights.regime == "Risk-On"


# ---------------------------------------------------------------------------
# ScenarioWeights.as_list tests
# ---------------------------------------------------------------------------

def test_scenario_weights_as_list():
    """ScenarioWeights.as_list() must return [bear, base, bull] as 3-element list."""
    sw = ScenarioWeights(bear=0.20, base=0.60, bull=0.20, regime="Neutral")
    result = sw.as_list()
    assert isinstance(result, list)
    assert len(result) == 3
    assert result[0] == pytest.approx(0.20)  # bear
    assert result[1] == pytest.approx(0.60)  # base
    assert result[2] == pytest.approx(0.20)  # bull


# ---------------------------------------------------------------------------
# get_regime_badge_html tests
# ---------------------------------------------------------------------------

def test_regime_badge_html_risk_on():
    """Risk-On badge must include the green colour code or 'Risk-On' text."""
    regime = _make_regime("Risk-On")
    html = get_regime_badge_html(regime)
    assert isinstance(html, str)
    assert "#22c55e" in html or "Risk-On" in html


def test_regime_badge_html_risk_off():
    """Risk-Off badge must include a red colour code or 'Risk-Off' text."""
    regime = _make_regime("Risk-Off")
    html = get_regime_badge_html(regime)
    assert isinstance(html, str)
    assert "#ef4444" in html or "Risk-Off" in html


# ---------------------------------------------------------------------------
# RegimeState dataclass test
# ---------------------------------------------------------------------------

def test_regime_state_dataclass():
    """RegimeState can be instantiated with required fields."""
    state = RegimeState(
        label="Neutral",
        probabilities={"Risk-On": 0.3, "Neutral": 0.5, "Risk-Off": 0.2},
        state_index=1,
        as_of_date="2026-03-17",
        available=True,
    )
    assert state.label == "Neutral"
    assert state.available is True
    assert state.error is None  # optional field defaults to None


# ---------------------------------------------------------------------------
# detect_current_regime — fallback-to-Neutral test
# ---------------------------------------------------------------------------

def test_detect_current_regime_no_data_returns_neutral():
    """When _fetch_training_features returns None, detect_current_regime falls back to Neutral."""
    with patch(
        "src.stage_02_valuation.regime_model._fetch_training_features",
        return_value=None,
    ):
        # Also patch _model_path().exists() to False so it tries to train (and fails)
        with patch(
            "src.stage_02_valuation.regime_model._model_path",
        ) as mock_path:
            mock_path_obj = mock_path.return_value
            mock_path_obj.exists.return_value = False

            from src.stage_02_valuation.regime_model import detect_current_regime
            result = detect_current_regime(retrain=False)

    assert isinstance(result, RegimeState)
    assert result.label == "Neutral"
    assert result.available is False
