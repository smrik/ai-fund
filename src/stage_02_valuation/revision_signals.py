"""Revision signal integration for DCF input assembly."""

import logging

logger = logging.getLogger(__name__)

# Additive adjustment to growth_near based on analyst revision momentum.
# Units are absolute (e.g., 0.015 = +1.5 percentage points).
REVISION_GROWTH_BIAS: dict[str, float] = {
    "strong_positive": 0.015,   # +1.5% additive to growth_near
    "positive": 0.008,
    "neutral": 0.0,
    "negative": -0.008,
    "strong_negative": -0.015,
    "unavailable": 0.0,
}


def get_revision_growth_bias(ticker: str) -> tuple[float, str]:
    """
    Return (growth_near_additive_bias, source_lineage_note) for ticker.

    Looks up the most-recent revision signals stored in estimate_history and
    maps the revision_momentum label to an additive growth bias via
    REVISION_GROWTH_BIAS.

    Returns (0.0, "revision_unavailable") if signals are unavailable or if
    any error occurs during retrieval.
    """
    try:
        from src.stage_00_data.estimate_tracker import get_revision_signals

        sigs = get_revision_signals(ticker, lookback_days=90)
        if not sigs.available:
            return 0.0, "revision_unavailable"
        bias = REVISION_GROWTH_BIAS.get(sigs.revision_momentum, 0.0)
        return bias, f"revision_adj:{sigs.revision_momentum}"
    except Exception as exc:
        logger.debug("get_revision_growth_bias failed for %s: %s", ticker, exc)
        return 0.0, "revision_unavailable"
