"""
CompsModel — IQR-cleaned, similarity-weighted trading comps valuation.

Deterministic layer only — no LLM.

Improvements over the simple median×metric approach in ciq_adapter:
  1. Tukey IQR fence outlier removal per metric (skipped if < 4 peers)
  2. Log-market-cap proximity weights for the base (weighted median)
  3. Bear / Base / Bull range: 25th pct / weighted median / 75th pct
  4. Automatic metric selection: forward > LTM, TEV/EBITDA > TEV/EBIT > PE

Entry point:
    from src.stage_02_valuation.comps_model import run_comps_model
    result = run_comps_model(comps_detail, net_debt_mm=..., shares_mm=...)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import logging

logger = logging.getLogger(__name__)


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class PeerMultipleResult:
    """Bear/base/bull outputs for one valuation multiple."""
    metric: str
    n_raw: int                     # peers with valid data before cleaning
    n_clean: int                   # peers after IQR cleaning
    outliers_removed: list[str]    # peer tickers excluded as outliers
    bear_multiple: float | None    # 25th pct of cleaned set
    base_multiple: float | None    # similarity-weighted median
    bull_multiple: float | None    # 75th pct of cleaned set
    bear_iv: float | None          # implied price per share
    base_iv: float | None
    bull_iv: float | None


@dataclass
class CompsResult:
    """Comps model output: headline range + per-metric detail."""
    ticker: str
    peer_count_raw: int
    peer_count_clean: int           # after applying primary metric cleaning
    primary_metric: str             # metric driving headline bear/base/bull
    bear_iv: float | None
    base_iv: float | None
    bull_iv: float | None
    blended_base_iv: float | None   # equal-weight mean of available base IVs
    metrics: dict[str, PeerMultipleResult] = field(default_factory=dict)
    similarity_weighted: bool = False
    similarity_method: str = "market_cap_only"
    similarity_model: str | None = None
    peer_similarity_scores: dict[str, float] = field(default_factory=dict)
    weighting_formula: str = ""
    notes: str = ""


# ── Private helpers ───────────────────────────────────────────────────────────

def _rnd(v: float | None, n: int = 4) -> float | None:
    return round(v, n) if v is not None else None


def _percentile(sorted_vals: list[float], pct: float) -> float:
    """Linear interpolation percentile. Requires sorted input."""
    n = len(sorted_vals)
    if n == 0:
        raise ValueError("empty list")
    if n == 1:
        return sorted_vals[0]
    idx = pct * (n - 1)
    lo = int(idx)
    hi = lo + 1
    if hi >= n:
        return sorted_vals[-1]
    frac = idx - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def _weighted_percentile(values: list[float], weights: list[float], pct: float) -> float:
    """Weighted percentile using cumulative normalised weights."""
    if not values:
        raise ValueError("empty list")
    pairs = sorted(zip(values, weights), key=lambda x: x[0])
    total = sum(max(w, 0.0) for _, w in pairs)
    if total <= 0:
        return _percentile(sorted(values), pct)
    cum = 0.0
    threshold = max(0.0, min(1.0, pct))
    for value, weight in pairs:
        cum += max(weight, 0.0) / total
        if cum >= threshold:
            return value
    return pairs[-1][0]


def _iqr_clean(
    values: list[float],
    tickers: list[str],
    iqr_factor: float = 1.5,
) -> tuple[list[float], list[str], list[str]]:
    """
    Tukey fence outlier removal.
    Skips cleaning when < 4 observations to avoid over-trimming small peer sets.
    Returns (clean_values, clean_tickers, removed_tickers).
    """
    if len(values) < 4:
        return values, tickers, []
    s = sorted(values)
    q1 = _percentile(s, 0.25)
    q3 = _percentile(s, 0.75)
    iqr = q3 - q1
    lo_fence = q1 - iqr_factor * iqr
    hi_fence = q3 + iqr_factor * iqr
    clean_v, clean_t, removed = [], [], []
    for v, t in zip(values, tickers):
        if lo_fence <= v <= hi_fence:
            clean_v.append(v)
            clean_t.append(t)
        else:
            removed.append(t)
    return clean_v, clean_t, removed


def _similarity_weights(
    clean_mktcaps: list[float | None],
    target_mktcap: float | None,
    similarity_scores: list[float | None] | None = None,
    market_cap_blend_weight: float = 0.40,
    description_blend_weight: float = 0.60,
) -> list[float]:
    """
    Log-market-cap proximity weights: exp(-|log(peer/target)|).
    Returns normalised weights summing to 1.
    Falls back to equal weights if target_mktcap is unavailable.
    """
    n = len(clean_mktcaps)
    if n == 0:
        return []
    market_raw = []
    for cap in clean_mktcaps:
        if target_mktcap is None or target_mktcap <= 0 or cap is None or cap <= 0:
            market_raw.append(1.0)
        else:
            dist = abs(math.log(cap / target_mktcap))
            market_raw.append(math.exp(-dist))

    use_similarity = bool(similarity_scores) and any(score is not None for score in similarity_scores or [])
    weights = []
    for i, market_weight in enumerate(market_raw):
        if use_similarity:
            score = similarity_scores[i] if similarity_scores and i < len(similarity_scores) else None
            desc_weight = market_weight if score is None else max(0.0, min(1.0, float(score)))
            weights.append(
                market_cap_blend_weight * market_weight
                + description_blend_weight * desc_weight
            )
        else:
            weights.append(market_weight)

    total = sum(weights)
    if total <= 0:
        return [1.0 / n] * n
    return [w / total for w in weights]


def _weighted_median(values: list[float], weights: list[float]) -> float:
    """Weighted median: value at which cumulative weight first reaches 0.5."""
    if not values:
        raise ValueError("empty")
    if len(values) == 1:
        return values[0]
    pairs = sorted(zip(values, weights), key=lambda x: x[0])
    total = sum(w for _, w in pairs)
    cum = 0.0
    for v, w in pairs:
        cum += w / total
        if cum >= 0.5:
            return v
    return pairs[-1][0]


def _build_peer_data(
    peers: list[dict],
    metric_name: str,
    min_val: float,
    max_val: float,
) -> tuple[list[str], list[float], dict[str, float | None]]:
    """Extract (tickers, multiples, ticker→mktcap) for a metric."""
    tickers: list[str] = []
    multiples: list[float] = []
    cap_map: dict[str, float | None] = {}
    for p in peers:
        v = p.get(metric_name)
        if v is not None and min_val < float(v) < max_val:
            t = str(p["ticker"])
            tickers.append(t)
            multiples.append(float(v))
            cap_map[t] = p.get("market_cap_mm")
    return tickers, multiples, cap_map


def _ev_multiple_to_price(
    multiple: float,
    target_metric_mm: float,
    net_debt_mm: float,
    shares_mm: float,
) -> float | None:
    """TEV/X × target_X_mm → implied EV_mm → implied equity_mm → $/share."""
    if shares_mm <= 0:
        return None
    implied_equity_mm = multiple * target_metric_mm - net_debt_mm
    return implied_equity_mm / shares_mm  # mm / mm = $ per share


def _pe_to_price(multiple: float, eps: float) -> float | None:
    return multiple * eps if eps > 0 else None


def _process_ev_metric(
    metric_name: str,
    peers: list[dict],
    target_metric_mm: float | None,
    target_mktcap_mm: float | None,
    net_debt_mm: float,
    shares_mm: float,
    similarity_scores: dict[str, float] | None = None,
) -> PeerMultipleResult | None:
    """Process one EV-based multiple (TEV/EBITDA or TEV/EBIT)."""
    if target_metric_mm is None or shares_mm <= 0:
        return None

    tickers, multiples, cap_map = _build_peer_data(peers, metric_name, 0.0, 100.0)
    if not multiples:
        return None

    n_raw = len(multiples)
    clean_v, clean_t, removed = _iqr_clean(multiples, tickers)
    if not clean_v:
        return None

    clean_caps = [cap_map.get(t) for t in clean_t]
    score_list = [similarity_scores.get(t) if similarity_scores else None for t in clean_t]
    weights = _similarity_weights(clean_caps, target_mktcap_mm, score_list)

    bear_m = _weighted_percentile(clean_v, weights, 0.25)
    base_m = _weighted_median(clean_v, weights)
    bull_m = _weighted_percentile(clean_v, weights, 0.75)

    def _iv(m: float) -> float | None:
        return _ev_multiple_to_price(m, target_metric_mm, net_debt_mm, shares_mm)

    return PeerMultipleResult(
        metric=metric_name,
        n_raw=n_raw,
        n_clean=len(clean_v),
        outliers_removed=removed,
        bear_multiple=_rnd(bear_m),
        base_multiple=_rnd(base_m),
        bull_multiple=_rnd(bull_m),
        bear_iv=_rnd(_iv(bear_m)),
        base_iv=_rnd(_iv(base_m)),
        bull_iv=_rnd(_iv(bull_m)),
    )


def _process_pe_metric(
    metric_name: str,
    peers: list[dict],
    target_eps: float | None,
    target_mktcap_mm: float | None,
    similarity_scores: dict[str, float] | None = None,
) -> PeerMultipleResult | None:
    """Process P/E multiple."""
    if target_eps is None or target_eps <= 0:
        return None

    tickers, multiples, cap_map = _build_peer_data(peers, metric_name, 0.0, 150.0)
    if not multiples:
        return None

    n_raw = len(multiples)
    clean_v, clean_t, removed = _iqr_clean(multiples, tickers)
    if not clean_v:
        return None

    clean_caps = [cap_map.get(t) for t in clean_t]
    score_list = [similarity_scores.get(t) if similarity_scores else None for t in clean_t]
    weights = _similarity_weights(clean_caps, target_mktcap_mm, score_list)

    bear_m = _weighted_percentile(clean_v, weights, 0.25)
    base_m = _weighted_median(clean_v, weights)
    bull_m = _weighted_percentile(clean_v, weights, 0.75)

    return PeerMultipleResult(
        metric=metric_name,
        n_raw=n_raw,
        n_clean=len(clean_v),
        outliers_removed=removed,
        bear_multiple=_rnd(bear_m),
        base_multiple=_rnd(base_m),
        bull_multiple=_rnd(bull_m),
        bear_iv=_rnd(_pe_to_price(bear_m, target_eps)),
        base_iv=_rnd(_pe_to_price(base_m, target_eps)),
        bull_iv=_rnd(_pe_to_price(bull_m, target_eps)),
    )


# ── Metric selection ──────────────────────────────────────────────────────────

# Ordered preference: forward > LTM, EBITDA > EBIT > PE
_METRIC_PRIORITY = [
    "tev_ebitda_fwd",
    "tev_ebitda_ltm",
    "tev_ebit_fwd",
    "tev_ebit_ltm",
    "pe_ltm",
]
# Minimum clean peers required to use a forward metric
_MIN_PEERS_FOR_FWD = 3


def _select_primary(metrics: dict[str, PeerMultipleResult]) -> str | None:
    for m in _METRIC_PRIORITY:
        if m in metrics and metrics[m].n_clean >= 2:
            return m
    return None


# ── yfinance peer adapter ─────────────────────────────────────────────────────

def build_comps_detail_from_yfinance(
    target_ticker: str,
    peer_data: list[dict],
    target_data: dict,
) -> dict | None:
    """
    Convert yfinance peer list into the comps_detail format consumed by run_comps_model().

    Args:
        target_ticker: ticker symbol for the company being valued.
        peer_data: list of dicts from get_peer_multiples() — each has keys
                   ticker, market_cap_mm, ebitda_mm, ev_ebitda, pe_trailing.
        target_data: dict from get_market_data() for the target ticker.

    Returns:
        comps_detail dict with "target" and "peers" keys, or None if no usable peers.
    """
    if not peer_data:
        return None

    mktcap = target_data.get("market_cap")
    ebitda = target_data.get("ebitda_ttm")
    tev = target_data.get("enterprise_value")

    # Gap 8: read ebit_ltm_mm and eps_ltm if caller pre-computed and passed them
    ebit_ltm_mm = target_data.get("ebit_ltm_mm")  # caller may supply in $mm already
    eps_ltm = target_data.get("eps_ltm")

    target = {
        "ticker": target_ticker.upper(),
        "market_cap_mm": mktcap / 1e6 if mktcap else None,
        "tev_mm": tev / 1e6 if tev else None,
        "ebitda_ltm_mm": ebitda / 1e6 if ebitda else None,
        "ebit_ltm_mm": ebit_ltm_mm,
        "eps_ltm": eps_ltm,
    }

    peers = []
    for p in peer_data:
        ev_ebitda = p.get("ev_ebitda")
        # Derive tev_ebitda_ltm from ev_ebitda ratio directly
        peers.append({
            "ticker": p.get("ticker", ""),
            "market_cap_mm": p.get("market_cap_mm"),
            "tev_ebitda_ltm": ev_ebitda if ev_ebitda and 0 < ev_ebitda < 100 else None,
            "tev_ebit_ltm": None,
            "tev_ebitda_fwd": None,
            "tev_ebit_fwd": None,
            "pe_ltm": p.get("pe_trailing") if p.get("pe_trailing") and 0 < p.get("pe_trailing") < 150 else None,
        })

    usable = [p for p in peers if p.get("tev_ebitda_ltm") is not None or p.get("pe_ltm") is not None]
    if not usable:
        return None

    return {"target": target, "peers": peers, "medians": {}, "source": "yfinance"}


# ── Public entry point ────────────────────────────────────────────────────────

def run_comps_model(
    comps_detail: dict[str, Any] | None,
    net_debt_mm: float | None = None,
    shares_mm: float | None = None,
    similarity_scores: dict[str, float] | None = None,
) -> CompsResult | None:
    """
    Run the full comps model.

    Args:
        comps_detail: output of get_ciq_comps_detail() — dict with
                      "target", "peers", "medians" keys.
        net_debt_mm:  target net debt in USD millions.
                      Derived from target tev_mm - market_cap_mm if None.
        shares_mm:    target shares outstanding in millions.
                      Required for EV-based multiples; PE doesn't need it.

    Returns:
        CompsResult or None if insufficient data.
    """
    if not comps_detail:
        return None

    target = comps_detail.get("target") or {}
    peers = comps_detail.get("peers") or []
    if not peers:
        return None

    ticker = str(target.get("ticker") or "UNKNOWN")
    target_mktcap_mm: float | None = target.get("market_cap_mm")
    target_tev_mm: float | None = target.get("tev_mm")
    target_ebitda_mm: float | None = target.get("ebitda_ltm_mm")
    target_ebit_mm: float | None = target.get("ebit_ltm_mm")
    target_eps: float | None = target.get("eps_ltm")

    # Derive net_debt from TEV - mktcap if not explicitly provided
    if net_debt_mm is None:
        if target_tev_mm is not None and target_mktcap_mm is not None:
            net_debt_mm = target_tev_mm - target_mktcap_mm
        else:
            net_debt_mm = 0.0

    _shares = shares_mm if (shares_mm is not None and shares_mm > 0) else 0.0
    have_shares = _shares > 0

    notes_parts: list[str] = []
    if not have_shares:
        notes_parts.append("shares_mm not provided — EV multiples skipped")

    metrics: dict[str, PeerMultipleResult] = {}

    # TEV/EBITDA forward (require ≥ _MIN_PEERS_FOR_FWD clean peers)
    r = _process_ev_metric("tev_ebitda_fwd", peers, target_ebitda_mm, target_mktcap_mm, net_debt_mm, _shares, similarity_scores)
    if r and r.n_clean >= _MIN_PEERS_FOR_FWD:
        metrics["tev_ebitda_fwd"] = r

    # TEV/EBITDA LTM
    r = _process_ev_metric("tev_ebitda_ltm", peers, target_ebitda_mm, target_mktcap_mm, net_debt_mm, _shares, similarity_scores)
    if r:
        metrics["tev_ebitda_ltm"] = r

    # TEV/EBIT forward (require ≥ _MIN_PEERS_FOR_FWD)
    r = _process_ev_metric("tev_ebit_fwd", peers, target_ebit_mm, target_mktcap_mm, net_debt_mm, _shares, similarity_scores)
    if r and r.n_clean >= _MIN_PEERS_FOR_FWD:
        metrics["tev_ebit_fwd"] = r

    # TEV/EBIT LTM
    r = _process_ev_metric("tev_ebit_ltm", peers, target_ebit_mm, target_mktcap_mm, net_debt_mm, _shares, similarity_scores)
    if r:
        metrics["tev_ebit_ltm"] = r

    # P/E LTM (no shares needed)
    r = _process_pe_metric("pe_ltm", peers, target_eps, target_mktcap_mm, similarity_scores)
    if r:
        metrics["pe_ltm"] = r

    if not metrics:
        return None

    primary = _select_primary(metrics)
    if primary is None:
        return None

    primary_result = metrics[primary]

    # Blended base: equal-weight mean across all available base IVs
    base_ivs = [m.base_iv for m in metrics.values() if m.base_iv is not None]
    blended_base = _rnd(sum(base_ivs) / len(base_ivs)) if base_ivs else None

    notes = "; ".join(notes_parts) if notes_parts else (
        f"primary={primary}; {len(metrics)} metrics computed; "
        f"{primary_result.n_clean}/{primary_result.n_raw} peers after IQR cleaning"
    )

    return CompsResult(
        ticker=ticker,
        peer_count_raw=len(peers),
        peer_count_clean=primary_result.n_clean,
        primary_metric=primary,
        bear_iv=primary_result.bear_iv,
        base_iv=primary_result.base_iv,
        bull_iv=primary_result.bull_iv,
        blended_base_iv=blended_base,
        metrics=metrics,
        similarity_weighted=(
            (target_mktcap_mm is not None and target_mktcap_mm > 0)
            or bool(similarity_scores)
        ),
        similarity_method="embedding_cosine" if similarity_scores else "market_cap_only",
        similarity_model="all-MiniLM-L6-v2" if similarity_scores else None,
        peer_similarity_scores=dict(similarity_scores or {}),
        weighting_formula="0.60*description_similarity + 0.40*market_cap_proximity"
        if similarity_scores
        else "market_cap_proximity_only",
        notes=notes,
    )
