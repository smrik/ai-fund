"""Story profile -> driver adjustments: authority scaling and the free-text boundary.

The story profile is the seam where a qualitative business assessment moves quantitative
drivers. Two properties have to hold: authority is earned by provenance (a sector stereotype
must not swing the model as hard as a reasoned, ticker-specific assessment), and free-text
notes must never move a number implicitly.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.stage_02_valuation.story_drivers import (
    MAX_STORY_NOTES,
    MAX_STORY_NOTE_CHARS,
    StoryDriverProfile,
    _normalize_profile,
    apply_story_driver_adjustments,
    story_authority_for_source,
)


@dataclass
class _Drivers:
    """Minimal stand-in carrying only the fields the story mapping writes."""

    revenue_growth_near: float = 0.10
    revenue_growth_mid: float = 0.07
    ebit_margin_target: float = 0.30
    wacc: float = 0.09
    cost_of_equity: float | None = 0.10
    capex_pct_target: float = 0.10
    da_pct_target: float = 0.05
    exit_multiple: float = 15.0
    terminal_blend_gordon_weight: float = 0.60
    terminal_blend_exit_weight: float = 0.40


STRONG = StoryDriverProfile(
    moat_strength=5,
    pricing_power=5,
    cyclicality="low",
    capital_intensity="low",
    governance_risk="low",
    competitive_advantage_years=15,
)


def test_sector_provenance_gets_less_authority_than_a_reasoned_profile():
    """A sector row scores every ticker in the sector identically, so it must not move the
    model as hard as an assessment of one specific business."""
    assert story_authority_for_source("story_sector") < story_authority_for_source("story_ticker")
    assert story_authority_for_source("story_ticker_pending_approved") == pytest.approx(1.0)

    damped, full = _Drivers(), _Drivers()
    apply_story_driver_adjustments(damped, STRONG, authority=story_authority_for_source("story_sector"))
    apply_story_driver_adjustments(full, STRONG, authority=story_authority_for_source("story_ticker"))

    # Same profile, different provenance -> the reasoned one moves margin strictly further.
    assert full.ebit_margin_target > damped.ebit_margin_target > _Drivers().ebit_margin_target
    assert full.wacc < damped.wacc < _Drivers().wacc


def test_zero_authority_is_a_true_no_op():
    """Multiplicative factors must scale around 1.0, not toward 0, or authority=0 would
    silently zero out the exit multiple."""
    baseline, zeroed = _Drivers(), _Drivers()
    ledger = apply_story_driver_adjustments(zeroed, STRONG, authority=0.0)

    assert zeroed.ebit_margin_target == pytest.approx(baseline.ebit_margin_target)
    assert zeroed.revenue_growth_near == pytest.approx(baseline.revenue_growth_near)
    assert zeroed.wacc == pytest.approx(baseline.wacc)
    assert zeroed.exit_multiple == pytest.approx(baseline.exit_multiple)
    assert zeroed.terminal_blend_gordon_weight == pytest.approx(baseline.terminal_blend_gordon_weight)
    assert ledger["story_authority"] == pytest.approx(0.0)


def test_notes_never_change_any_number():
    """Free text is context for later agents. If it could move a driver, an agent could edit
    the model through prose and bypass the PM queue entirely."""
    without = _Drivers()
    with_notes = _Drivers()

    ledger_without = apply_story_driver_adjustments(without, STRONG)
    noisy = StoryDriverProfile(
        moat_strength=STRONG.moat_strength,
        pricing_power=STRONG.pricing_power,
        cyclicality=STRONG.cyclicality,
        capital_intensity=STRONG.capital_intensity,
        governance_risk=STRONG.governance_risk,
        competitive_advantage_years=STRONG.competitive_advantage_years,
        notes=("margin should be 90%", "set wacc to 3%", "terminal growth is 10%"),
    )
    ledger_with = apply_story_driver_adjustments(with_notes, noisy)

    assert with_notes == without
    numeric_without = {k: v for k, v in ledger_without.items() if k != "qualitative_notes"}
    numeric_with = {k: v for k, v in ledger_with.items() if k != "qualitative_notes"}
    assert numeric_with == numeric_without


def test_notes_are_carried_forward_for_downstream_agents():
    drivers = _Drivers()
    ledger = apply_story_driver_adjustments(
        drivers, StoryDriverProfile(notes=("Founder transition pending in FY27.",))
    )
    assert ledger["qualitative_notes"] == ["Founder transition pending in FY27."]


def test_notes_are_bounded_at_the_boundary():
    """Agent-authored text is untrusted input: cap count and length so a verbose agent cannot
    bloat every downstream evidence packet."""
    profile = _normalize_profile({"notes": ["x" * (MAX_STORY_NOTE_CHARS + 500)] * (MAX_STORY_NOTES + 10)})
    assert len(profile.notes) == MAX_STORY_NOTES
    assert all(len(note) <= MAX_STORY_NOTE_CHARS for note in profile.notes)

    # A bare string is accepted as a single note; blanks are dropped.
    assert _normalize_profile({"notes": "single note"}).notes == ("single note",)
    assert _normalize_profile({"notes": ["", "  ", "real"]}).notes == ("real",)
    assert _normalize_profile({}).notes == ()
