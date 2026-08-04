"""Deterministic story-to-numbers mapping for valuation drivers."""
from __future__ import annotations

import functools
from dataclasses import dataclass, asdict
from typing import Any

import yaml

from config import ROOT_DIR


STORY_DRIVERS_PATH = ROOT_DIR / "config" / "story_drivers.yaml"
STORY_DRIVERS_PENDING_PATH = ROOT_DIR / "config" / "story_drivers_pending.yaml"


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


@dataclass(slots=True)
class StoryDriverProfile:
    """Qualitative business assessment, in two deliberately separate halves.

    The typed fields above `notes` are the *scored base*: they feed
    `apply_story_driver_adjustments` and move numbers under clamps. They are
    intentionally a small, closed vocabulary so the mapping stays auditable.

    `notes` is the open half. No fixed schema can anticipate every business, so
    anything the scores cannot express — a pending patent cliff, a founder
    transition, a segment that behaves nothing like the consolidated entity —
    belongs here as free text. Notes are carried forward as context for later
    agents and never enter the arithmetic; see `apply_story_driver_adjustments`.
    """

    moat_strength: int = 3
    pricing_power: int = 3
    cyclicality: str = "medium"
    capital_intensity: str = "medium"
    governance_risk: str = "medium"
    competitive_advantage_years: int = 7
    notes: tuple[str, ...] = ()


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


MAX_STORY_NOTES = 12
MAX_STORY_NOTE_CHARS = 600


def _sanitize_notes(value: Any) -> tuple[str, ...]:
    """Accept a list of strings or a single string; bound count and length.

    Notes are agent-authored free text, so this is a boundary: cap them so a
    verbose agent cannot bloat every downstream packet, but do not otherwise
    interpret them.
    """
    if value is None:
        return ()
    items = value if isinstance(value, (list, tuple)) else [value]
    cleaned: list[str] = []
    for item in items:
        text = str(item).strip()
        if text:
            cleaned.append(text[:MAX_STORY_NOTE_CHARS])
    return tuple(cleaned[:MAX_STORY_NOTES])


def _normalize_profile(payload: dict[str, Any] | None) -> StoryDriverProfile:
    data = payload or {}
    return StoryDriverProfile(
        moat_strength=_sanitize_int(data.get("moat_strength", 3), 1, 5, 3),
        pricing_power=_sanitize_int(data.get("pricing_power", 3), 1, 5, 3),
        cyclicality=_sanitize_bucket(data.get("cyclicality", "medium"), "medium"),
        capital_intensity=_sanitize_bucket(data.get("capital_intensity", "medium"), "medium"),
        governance_risk=_sanitize_bucket(data.get("governance_risk", "medium"), "medium"),
        competitive_advantage_years=_sanitize_int(data.get("competitive_advantage_years", 7), 1, 20, 7),
        notes=_sanitize_notes(data.get("notes")),
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


# How much authority a profile gets over the numbers, by where it came from.
# A sector row is a stereotype -- every Technology ticker scores identically -- so it keeps
# roughly its original timid influence (0.4 x the widened coefficients ~= the pre-2026-07-24
# values). A ticker-specific profile is a reasoned assessment of one business and gets full
# authority. This is what makes widening the coefficients safe: reasoning earns the swing,
# a default does not.
STORY_AUTHORITY_BY_SOURCE: dict[str, float] = {
    "story_global": 0.4,
    "story_sector": 0.4,
    "story_ticker": 1.0,
    "story_ticker_pending_approved": 1.0,
}
DEFAULT_STORY_AUTHORITY = 1.0


def story_authority_for_source(source: str) -> float:
    return STORY_AUTHORITY_BY_SOURCE.get(str(source or "").strip(), DEFAULT_STORY_AUTHORITY)


def apply_story_driver_adjustments(
    drivers,
    story: StoryDriverProfile,
    authority: float = DEFAULT_STORY_AUTHORITY,
) -> dict[str, float | str]:
    """
    Deterministically map qualitative story profile to numeric driver adjustments.

    `authority` scales every adjustment, so a sector-default profile moves the model less
    than a reasoned, ticker-specific one. Use `story_authority_for_source` to derive it.

    Returns an adjustment ledger for audit/export.
    """
    authority = _clamp(float(authority), 0.0, 1.0)
    moat_delta = story.moat_strength - 3
    pricing_delta = story.pricing_power - 3

    cyc_growth_mult = {
        "low": 1.08,
        "medium": 1.00,
        "high": 0.85,
    }[story.cyclicality]
    cyc_wacc_add = {
        "low": -0.005,
        "medium": 0.0,
        "high": 0.015,
    }[story.cyclicality]
    capex_add = {
        "low": -0.010,
        "medium": 0.0,
        "high": 0.020,
    }[story.capital_intensity]
    da_add = {
        "low": -0.004,
        "medium": 0.0,
        "high": 0.010,
    }[story.capital_intensity]
    gov_wacc_add = {
        "low": -0.004,
        "medium": 0.0,
        "high": 0.015,
    }[story.governance_risk]

    # Coefficients widened ~2.5-3x on 2026-07-24 (PM-approved). Rationale: these were sized
    # for a sector-default profile, where timidity is correct. Once the profile is a reasoned
    # assessment of a specific business, it has to be able to outweigh the mechanical sector
    # blend that sets ebit_margin_target -- otherwise the reasoning is cosmetic. Previously a
    # perfect 5/5 franchise could add 2.4pp of margin against a blend that removes ~10pp for a
    # high-margin compounder. Now a 5/5 adds 6.6pp and a 4/4 adds 3.3pp.
    # All adjustments remain bounded by the _clamp calls below.
    growth_add = 0.010 * moat_delta + 0.008 * pricing_delta
    margin_add = 0.015 * moat_delta + 0.018 * pricing_delta

    # Scale every adjustment by how much the profile has earned. Multiplicative factors are
    # scaled around their neutral value of 1.0 so authority=0 is a true no-op.
    growth_add *= authority
    margin_add *= authority
    cyc_wacc_add *= authority
    gov_wacc_add *= authority
    capex_add *= authority
    da_add *= authority
    cyc_growth_mult = 1.0 + (cyc_growth_mult - 1.0) * authority

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
    gordon_weight = _clamp(
        0.60 + (story.competitive_advantage_years - 7) * 0.025 * authority, 0.45, 0.75
    )
    drivers.terminal_blend_gordon_weight = gordon_weight
    drivers.terminal_blend_exit_weight = 1.0 - gordon_weight

    # Gap 2: Exit multiple compression for cyclicality and governance risk.
    cyc_exit_mult = {"low": 1.08, "medium": 1.00, "high": 0.85}[story.cyclicality]
    gov_exit_mult = {"low": 1.04, "medium": 1.00, "high": 0.85}[story.governance_risk]
    cyc_exit_mult = 1.0 + (cyc_exit_mult - 1.0) * authority
    gov_exit_mult = 1.0 + (gov_exit_mult - 1.0) * authority
    drivers.exit_multiple = _clamp(drivers.exit_multiple * cyc_exit_mult * gov_exit_mult, 2.0, 40.0)

    # story.notes is deliberately absent from every calculation above. Free text must never
    # move a number implicitly; it is surfaced here so downstream agents inherit it as
    # reasoning context and can raise their own bounded, PM-reviewable proposals from it.
    return {
        "qualitative_notes": list(story.notes),
        "story_authority": round(authority, 4),
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
