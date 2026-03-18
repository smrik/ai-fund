"""Deterministic story-to-numbers mapping for valuation drivers."""
from __future__ import annotations

import functools
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

import yaml

from config import ROOT_DIR


STORY_DRIVERS_PATH = ROOT_DIR / "config" / "story_drivers.yaml"
STORY_DRIVERS_PENDING_PATH = ROOT_DIR / "config" / "story_drivers_pending.yaml"


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


@dataclass(slots=True)
class StoryDriverProfile:
    moat_strength: int = 3
    pricing_power: int = 3
    cyclicality: str = "medium"
    capital_intensity: str = "medium"
    governance_risk: str = "medium"
    competitive_advantage_years: int = 7


def _sanitize_int(value: Any, low: int, high: int, default: int) -> int:
    try:
        ivalue = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, ivalue))


def _sanitize_bucket(value: Any, default: str) -> str:
    text = str(value or default).strip().lower()
    if text not in {"low", "medium", "high"}:
        return default
    return text


def _normalize_profile(payload: dict[str, Any] | None) -> StoryDriverProfile:
    data = payload or {}
    return StoryDriverProfile(
        moat_strength=_sanitize_int(data.get("moat_strength", 3), 1, 5, 3),
        pricing_power=_sanitize_int(data.get("pricing_power", 3), 1, 5, 3),
        cyclicality=_sanitize_bucket(data.get("cyclicality", "medium"), "medium"),
        capital_intensity=_sanitize_bucket(data.get("capital_intensity", "medium"), "medium"),
        governance_risk=_sanitize_bucket(data.get("governance_risk", "medium"), "medium"),
        competitive_advantage_years=_sanitize_int(data.get("competitive_advantage_years", 7), 1, 20, 7),
    )


@functools.lru_cache(maxsize=1)
def load_story_driver_overrides() -> dict[str, Any]:
    if not STORY_DRIVERS_PATH.exists():
        return {"global": {}, "sectors": {}, "tickers": {}}

    with STORY_DRIVERS_PATH.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}

    data.setdefault("global", {})
    data.setdefault("sectors", {})
    data.setdefault("tickers", {})
    return data


def _load_approved_pending(ticker: str) -> dict[str, Any] | None:
    """
    Check story_drivers_pending.yaml for an approved entry for this ticker.
    Returns the profile dict if status == 'approved', else None.
    Not cached — must read fresh each call so PM approvals take effect immediately.
    """
    if not STORY_DRIVERS_PENDING_PATH.exists():
        return None
    try:
        data = yaml.safe_load(STORY_DRIVERS_PENDING_PATH.read_text(encoding="utf-8")) or {}
    except Exception:
        return None
    entry = data.get(ticker.upper())
    if not isinstance(entry, dict):
        return None
    if str(entry.get("status", "")).lower() != "approved":
        return None
    return entry.get("profile")


def resolve_story_driver_profile(ticker: str, sector: str) -> tuple[StoryDriverProfile, str]:
    data = load_story_driver_overrides()

    base = _normalize_profile(data.get("global", {}))
    source = "story_global"

    sector_blob = data.get("sectors", {}).get(sector)
    if isinstance(sector_blob, dict):
        merged = {**asdict(base), **sector_blob}
        base = _normalize_profile(merged)
        source = "story_sector"

    # Check pending YAML first — approved pending entries win over static YAML tickers
    pending_profile = _load_approved_pending(ticker)
    if pending_profile is not None:
        merged = {**asdict(base), **pending_profile}
        base = _normalize_profile(merged)
        return base, "story_ticker_pending_approved"

    ticker_blob = data.get("tickers", {}).get(ticker.upper())
    if isinstance(ticker_blob, dict):
        merged = {**asdict(base), **ticker_blob}
        base = _normalize_profile(merged)
        source = "story_ticker"

    return base, source


def apply_story_driver_adjustments(drivers, story: StoryDriverProfile) -> dict[str, float | str]:
    """
    Deterministically map qualitative story profile to numeric driver adjustments.

    Returns an adjustment ledger for audit/export.
    """
    moat_delta = story.moat_strength - 3
    pricing_delta = story.pricing_power - 3

    cyc_growth_mult = {
        "low": 1.05,
        "medium": 1.00,
        "high": 0.90,
    }[story.cyclicality]
    cyc_wacc_add = {
        "low": -0.003,
        "medium": 0.0,
        "high": 0.010,
    }[story.cyclicality]
    capex_add = {
        "low": -0.005,
        "medium": 0.0,
        "high": 0.010,
    }[story.capital_intensity]
    da_add = {
        "low": -0.002,
        "medium": 0.0,
        "high": 0.005,
    }[story.capital_intensity]
    gov_wacc_add = {
        "low": -0.002,
        "medium": 0.0,
        "high": 0.010,
    }[story.governance_risk]

    growth_add = 0.005 * moat_delta + 0.003 * pricing_delta
    margin_add = 0.005 * moat_delta + 0.007 * pricing_delta

    # Apply growth/margin path adjustments.
    drivers.revenue_growth_near = _clamp((drivers.revenue_growth_near + growth_add) * cyc_growth_mult, -0.20, 0.50)
    drivers.revenue_growth_mid = _clamp((drivers.revenue_growth_mid + growth_add * 0.7) * cyc_growth_mult, -0.20, 0.40)
    drivers.ebit_margin_target = _clamp(drivers.ebit_margin_target + margin_add, 0.00, 0.80)

    # Risk and reinvestment policy adjustments.
    drivers.wacc = _clamp(drivers.wacc + cyc_wacc_add + gov_wacc_add, 0.03, 0.20)
    if drivers.cost_of_equity is not None:
        drivers.cost_of_equity = _clamp(drivers.cost_of_equity + cyc_wacc_add + gov_wacc_add, 0.04, 0.30)

    drivers.capex_pct_target = _clamp(drivers.capex_pct_target + capex_add, 0.00, 0.35)
    drivers.da_pct_target = _clamp(drivers.da_pct_target + da_add, 0.00, 0.25)

    # Longer advantage period implies heavier Gordon weighting.
    gordon_weight = _clamp(0.60 + (story.competitive_advantage_years - 7) * 0.02, 0.45, 0.75)
    drivers.terminal_blend_gordon_weight = gordon_weight
    drivers.terminal_blend_exit_weight = 1.0 - gordon_weight

    # Gap 2: Exit multiple compression for cyclicality and governance risk.
    cyc_exit_mult = {"low": 1.05, "medium": 1.00, "high": 0.90}[story.cyclicality]
    gov_exit_mult = {"low": 1.02, "medium": 1.00, "high": 0.90}[story.governance_risk]
    drivers.exit_multiple = _clamp(drivers.exit_multiple * cyc_exit_mult * gov_exit_mult, 2.0, 40.0)

    return {
        "growth_add": round(growth_add, 4),
        "margin_add": round(margin_add, 4),
        "cyclicality_growth_multiplier": round(cyc_growth_mult, 4),
        "cyclicality_wacc_add": round(cyc_wacc_add, 4),
        "governance_wacc_add": round(gov_wacc_add, 4),
        "capex_target_add": round(capex_add, 4),
        "da_target_add": round(da_add, 4),
        "terminal_blend_gordon_weight": round(gordon_weight, 4),
        "terminal_blend_exit_weight": round(1.0 - gordon_weight, 4),
        "exit_multiple_cyclicality_multiplier": round(cyc_exit_mult, 4),
        "exit_multiple_governance_multiplier": round(gov_exit_mult, 4),
    }

