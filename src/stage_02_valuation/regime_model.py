"""
Macro regime detection using Hidden Markov Model.

3 states: Risk-On / Neutral / Risk-Off
Features: SPY daily returns (20d rolling vol), VIX level, 2s10s spread, IG credit spread

The model is trained on ~2 years of daily data. Regime labels are assigned by
mapping HMM states to economic interpretation via emission means.
"""
from __future__ import annotations

import importlib.util
import logging
import pickle
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Literal, Optional

import numpy as np

if TYPE_CHECKING:
    import pandas as pd
    from hmmlearn.hmm import GaussianHMM

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

RegimeLabel = Literal["Risk-On", "Neutral", "Risk-Off"]

REGIME_SCENARIO_WEIGHTS: dict[str, dict[str, float]] = {
    "Risk-On":  {"bear": 0.10, "base": 0.55, "bull": 0.35},
    "Neutral":  {"bear": 0.20, "base": 0.60, "bull": 0.20},
    "Risk-Off": {"bear": 0.35, "base": 0.55, "bull": 0.10},
}

_BADGE_COLORS: dict[str, str] = {
    "Risk-On":  "#22c55e",
    "Neutral":  "#eab308",
    "Risk-Off": "#ef4444",
}


@dataclass
class RegimeState:
    label: RegimeLabel
    probabilities: dict[str, float]
    state_index: int
    as_of_date: str
    available: bool
    error: str | None = None


@dataclass
class ScenarioWeights:
    bear: float
    base: float
    bull: float
    regime: RegimeLabel

    def as_list(self) -> list:
        """Return as ScenarioSpec-compatible probability list [bear, base, bull]."""
        return [self.bear, self.base, self.bull]


# ---------------------------------------------------------------------------
# Model pickle path
# ---------------------------------------------------------------------------

def _model_path():
    from config import ROOT_DIR
    return ROOT_DIR / "data" / "regime_model.pkl"


def _has_hmmlearn() -> bool:
    return importlib.util.find_spec("hmmlearn") is not None


# ---------------------------------------------------------------------------
# Feature engineering
# ---------------------------------------------------------------------------

def _fetch_training_features(lookback_days: int = 504) -> pd.DataFrame | None:
    """
    Fetch and normalize macro features for HMM training.

    Returns DataFrame with columns: spy_vol_20d, vix, slope_2s10s, ig_spread
    (z-score normalized, datetime index), or None on failure.
    """
    try:
        import pandas as pd
        import yfinance as yf
    except ImportError as exc:
        logger.warning("yfinance/pandas not available: %s", exc)
        return None

    try:
        start_dt = (datetime.now(timezone.utc) - timedelta(days=lookback_days + 30)).strftime("%Y-%m-%d")

        # --- SPY returns & rolling vol ---
        spy = yf.download("SPY", start=start_dt, progress=False, auto_adjust=True)
        if spy is None or len(spy) < 30:
            logger.warning("regime_model: insufficient SPY data")
            return None

        spy_close = spy["Close"].squeeze()
        spy_returns = spy_close.pct_change()
        spy_vol = spy_returns.rolling(20).std() * np.sqrt(252)
        spy_vol = spy_vol.dropna()
        spy_vol.name = "spy_vol_20d"

        feature_df = spy_vol.to_frame()
        feature_df.index = pd.to_datetime(feature_df.index)

        # --- FRED macro series ---
        fred_available = False
        try:
            from src.stage_00_data.fred_client import get_macro_snapshot

            snapshot = get_macro_snapshot(lookback_days=lookback_days + 30)
            if snapshot.get("available"):
                series = snapshot["series"]

                def _series_to_df(series_id: str, col_name: str) -> pd.Series | None:
                    raw = series.get(series_id, {})
                    values = raw.get("values", [])
                    if not values:
                        return None
                    dates = [v[0] for v in values]
                    vals = [v[1] for v in values]
                    s = pd.Series(vals, index=pd.to_datetime(dates), name=col_name)
                    return s.dropna()

                vix_s = _series_to_df("VIXCLS", "vix")
                slope_s = _series_to_df("T10Y2Y", "slope_2s10s")
                ig_s = _series_to_df("BAMLC0A4CBBB", "ig_spread")

                for col_series in [vix_s, slope_s, ig_s]:
                    if col_series is not None and len(col_series) > 0:
                        col_series_reindexed = col_series.reindex(
                            feature_df.index, method="ffill"
                        )
                        feature_df[col_series.name] = col_series_reindexed
                        fred_available = True

        except Exception as fred_exc:
            logger.warning("regime_model: FRED unavailable — degraded mode: %s", fred_exc)

        if not fred_available:
            logger.info("regime_model: running in degraded mode (SPY vol only)")

        # Drop rows with any NaN
        feature_df = feature_df.dropna()

        if len(feature_df) < 60:
            logger.warning("regime_model: too few feature rows after dropna: %d", len(feature_df))
            return None

        # Trim to requested lookback
        cutoff = pd.Timestamp.now("UTC").tz_localize(None) - pd.Timedelta(days=lookback_days)
        feature_df = feature_df[feature_df.index >= cutoff]

        if len(feature_df) < 60:
            logger.warning("regime_model: too few rows after lookback trim: %d", len(feature_df))
            return None

        # Z-score normalize each column
        for col in feature_df.columns:
            col_std = feature_df[col].std()
            if col_std > 0:
                feature_df[col] = (feature_df[col] - feature_df[col].mean()) / col_std
            else:
                feature_df[col] = 0.0

        return feature_df

    except Exception as exc:
        logger.exception("regime_model: _fetch_training_features failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# State label assignment
# ---------------------------------------------------------------------------

def _assign_regime_labels(model, features_df: pd.DataFrame) -> dict[int, str]:
    """
    Map HMM state indices to regime labels based on emission means.

    Uses VIX column if available, otherwise spy_vol_20d.
    Highest mean → Risk-Off, lowest mean → Risk-On, middle → Neutral.
    """
    columns = list(features_df.columns)

    # Pick the discriminating feature column
    if "vix" in columns:
        feat_col = "vix"
    else:
        feat_col = "spy_vol_20d"

    feat_idx = columns.index(feat_col)
    means = model.means_[:, feat_idx]  # shape: (n_states,)

    sorted_states = sorted(range(len(means)), key=lambda i: means[i])
    # sorted_states[0] = lowest mean → Risk-On
    # sorted_states[-1] = highest mean → Risk-Off
    # middle = Neutral

    label_map: dict[int, str] = {}
    n = len(sorted_states)
    for rank, state_idx in enumerate(sorted_states):
        if rank == 0:
            label_map[state_idx] = "Risk-On"
        elif rank == n - 1:
            label_map[state_idx] = "Risk-Off"
        else:
            label_map[state_idx] = "Neutral"

    return label_map


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------

def train_regime_model(
    lookback_days: int = 504,
    n_states: int = 3,
) -> tuple[GaussianHMM | None, dict[int, str], str | None]:
    """
    Fetch features, fit GaussianHMM, save to disk.

    Returns (model, label_map, error_or_None).
    Never raises.
    """
    try:
        from hmmlearn.hmm import GaussianHMM
    except ImportError:
        return (None, {}, "hmmlearn not installed")

    try:
        features_df = _fetch_training_features(lookback_days=lookback_days)
        if features_df is None or len(features_df) < 60:
            return (None, {}, "Insufficient feature data for training")

        X = features_df.values.astype(np.float64)

        model = GaussianHMM(
            n_components=n_states,
            covariance_type="full",
            n_iter=100,
            random_state=42,
        )
        model.fit(X)

        label_map = _assign_regime_labels(model, features_df)

        # Persist model + metadata
        pkl_path = _model_path()
        pkl_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "model": model,
            "label_map": label_map,
            "feature_columns": list(features_df.columns),
            "trained_at": datetime.now(timezone.utc).isoformat(),
        }
        with open(pkl_path, "wb") as fh:
            pickle.dump(payload, fh, protocol=pickle.HIGHEST_PROTOCOL)

        logger.info(
            "regime_model: trained on %d rows, features=%s, label_map=%s",
            len(features_df),
            list(features_df.columns),
            label_map,
        )
        return (model, label_map, None)

    except Exception as exc:
        logger.exception("regime_model: train_regime_model failed: %s", exc)
        return (None, {}, str(exc))


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def _neutral_fallback(error: str | None = None) -> RegimeState:
    weights = REGIME_SCENARIO_WEIGHTS["Neutral"]
    return RegimeState(
        label="Neutral",
        probabilities=dict(weights),
        state_index=-1,
        as_of_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        available=False,
        error=error,
    )


def detect_current_regime(retrain: bool = False) -> RegimeState:
    """
    Detect the current macro regime.

    Loads saved model or retrains if needed. Falls back to Neutral on any error.
    Never raises.
    """
    try:

        model = None
        label_map: dict[int, str] = {}
        feature_columns: list[str] = []

        pkl_path = _model_path()

        if not _has_hmmlearn():
            return _neutral_fallback(error="hmmlearn not installed")

        # --- Load or train ---
        if not retrain and pkl_path.exists():
            try:
                with open(pkl_path, "rb") as fh:
                    payload = pickle.load(fh)
                model = payload["model"]
                label_map = payload["label_map"]
                feature_columns = payload.get("feature_columns", [])
            except Exception as load_exc:
                logger.warning("regime_model: failed to load pickle, retraining: %s", load_exc)
                model = None

        if model is None:
            model, label_map, err = train_regime_model()
            if model is None:
                return _neutral_fallback(error=err or "Model training failed")
            # reload feature_columns from freshly saved pickle
            try:
                with open(pkl_path, "rb") as fh:
                    payload = pickle.load(fh)
                feature_columns = payload.get("feature_columns", [])
            except Exception:
                pass

        # --- Fetch current features ---
        features_df = _fetch_training_features(lookback_days=504)
        if features_df is None or len(features_df) == 0:
            return _neutral_fallback(error="Feature fetch failed for prediction")

        # Align columns to what the model was trained on
        if feature_columns:
            missing = [c for c in feature_columns if c not in features_df.columns]
            if missing:
                return _neutral_fallback(
                    error=f"Missing feature columns for prediction: {missing}"
                )
            features_df = features_df[feature_columns]

        X = features_df.values.astype(np.float64)

        # --- Predict all states ---
        hidden_states = model.predict(X)
        current_state_idx = int(hidden_states[-1])

        # --- State probabilities for the last observation ---
        state_probs_all = model.predict_proba(X)  # shape (T, n_states)
        last_probs = state_probs_all[-1]  # shape (n_states,)

        prob_dict: dict[str, float] = {}
        for s_idx, prob in enumerate(last_probs):
            s_label = label_map.get(s_idx, "Neutral")
            prob_dict[s_label] = prob_dict.get(s_label, 0.0) + float(prob)

        current_label: RegimeLabel = label_map.get(current_state_idx, "Neutral")  # type: ignore[assignment]
        as_of = str(features_df.index[-1])[:10]

        return RegimeState(
            label=current_label,
            probabilities=prob_dict,
            state_index=current_state_idx,
            as_of_date=as_of,
            available=True,
            error=None,
        )

    except Exception as exc:
        logger.exception("regime_model: detect_current_regime failed: %s", exc)
        return _neutral_fallback(error=str(exc))


# ---------------------------------------------------------------------------
# Scenario weights
# ---------------------------------------------------------------------------

def get_scenario_weights(regime: Optional[RegimeState] = None) -> ScenarioWeights:
    """
    Return bear/base/bull scenario weights for the given regime.

    Falls back to Neutral weights if regime is None or unavailable.
    """
    if regime is None or not regime.available:
        label: RegimeLabel = "Neutral"
    else:
        label = regime.label

    w = REGIME_SCENARIO_WEIGHTS.get(label, REGIME_SCENARIO_WEIGHTS["Neutral"])
    return ScenarioWeights(
        bear=w["bear"],
        base=w["base"],
        bull=w["bull"],
        regime=label,
    )


# ---------------------------------------------------------------------------
# Dashboard badge
# ---------------------------------------------------------------------------

def get_regime_badge_html(regime: RegimeState) -> str:
    """
    Return an HTML badge string colour-coded by regime label.

    Green for Risk-On, yellow for Neutral, red for Risk-Off.
    """
    color = _BADGE_COLORS.get(regime.label, _BADGE_COLORS["Neutral"])
    return (
        f'<span style="background:{color};color:#fff;padding:3px 10px;'
        f'border-radius:4px;font-weight:700">{regime.label}</span>'
    )
