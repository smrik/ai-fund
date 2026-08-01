"""Story-profile evidence marshalling and the refusal path.

The story profile drives eight valuation drivers at full authority once approved. These tests pin
the property that makes that safe: it is authored from real filing evidence, with anchors, or it
is not authored at all.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.stage_04_pipeline.story_profile_context import (
    MAX_SNIPPET_CHARS,
    MIN_SNIPPETS_REQUIRED,
    build_story_profile_context,
)


def _snippet(snippet_id: str, text: str, source_ref_id: str = "filing:0001") -> SimpleNamespace:
    return SimpleNamespace(snippet_id=snippet_id, source_ref_id=source_ref_id, text=text, metadata={})


def _packet(snippets=None, facts=None, source_refs=None, ticker="MSFT") -> SimpleNamespace:
    return SimpleNamespace(
        ticker=ticker,
        packet_id=42,
        snippets=snippets or [],
        facts=facts or [],
        source_refs=source_refs or [],
    )


def _usable_packet() -> SimpleNamespace:
    return _packet(
        snippets=[
            _snippet("snip:1", "Our cloud platform benefits from significant switching costs."),
            _snippet("snip:2", "We have increased prices across the commercial portfolio."),
            _snippet("snip:3", "Capital expenditures rose materially to support AI capacity."),
        ],
        facts=[SimpleNamespace(fact_id="fact:1", fact_name="operating_margin", value=0.44, unit=None)],
        source_refs=[
            SimpleNamespace(
                source_ref_id="filing:0001",
                source_kind="filing",
                source_label="FY25 10-K",
                source_locator="https://sec.gov/x",
            )
        ],
    )


def test_context_carries_snippets_facts_and_anchors():
    ctx = build_story_profile_context(
        _usable_packet(), company_name="Microsoft Corporation", sector="Technology", industry="Software"
    )

    assert ctx.is_usable
    assert ctx.status == "ok"
    assert ctx.snippet_count == 3
    assert ctx.fact_count == 1
    # Anchors must include both snippet and fact ids so a score can be traced to a disclosure.
    assert "snip:1" in ctx.evidence_anchor_ids
    assert "fact:1" in ctx.evidence_anchor_ids
    assert "filing:0001" in ctx.source_ref_ids
    assert "switching costs" in ctx.context_text
    assert "MSFT" in ctx.context_text
    assert "Microsoft Corporation" in ctx.context_text


def test_refuses_when_evidence_is_missing():
    """An agent asked to score a moat with no filings will still answer confidently, and that
    answer would carry full driver authority once approved. Refusing is the correct outcome."""
    ctx = build_story_profile_context(_packet(), company_name="Nobody Inc", sector="Technology")

    assert not ctx.is_usable
    assert ctx.status == "insufficient_evidence"
    assert ctx.context_text == ""
    assert ctx.evidence_anchor_ids == ()
    assert ctx.detail and "recall" in ctx.detail


def test_refuses_just_below_the_evidence_threshold():
    ctx = build_story_profile_context(
        _packet(snippets=[_snippet("snip:1", "One lonely excerpt.")]),
        company_name="Thin Inc",
    )
    assert ctx.snippet_count == MIN_SNIPPETS_REQUIRED - 1
    assert not ctx.is_usable


def test_blank_snippets_do_not_count_toward_the_threshold():
    """Empty text must not satisfy the evidence bar just by being present in the packet."""
    ctx = build_story_profile_context(
        _packet(snippets=[_snippet("snip:1", "   "), _snippet("snip:2", ""), _snippet("snip:3", "real text here")])
    )
    assert ctx.snippet_count == 1
    assert not ctx.is_usable


def test_long_snippets_are_truncated():
    ctx = build_story_profile_context(
        _packet(snippets=[_snippet("snip:1", "x" * 10_000), _snippet("snip:2", "y" * 10_000)])
    )
    assert ctx.is_usable
    # Both truncated to the cap; total stays bounded regardless of filing size.
    assert len(ctx.context_text) < 2 * MAX_SNIPPET_CHARS + 2_000


def test_industry_packet_is_optional_upstream_context():
    """Decision 14: business analysis reads the industry view. Its absence narrows evidence but
    must not fail the run."""
    without = build_story_profile_context(_usable_packet())
    assert without.is_usable
    assert without.metadata["industry_context_used"] is False

    with_industry = build_story_profile_context(
        _usable_packet(),
        industry_packet=_packet(snippets=[_snippet("ind:1", "Cloud infrastructure demand is accelerating.")]),
    )
    assert with_industry.metadata["industry_context_used"] is True
    assert "INDUSTRY CONTEXT" in with_industry.context_text
    assert "accelerating" in with_industry.context_text


def test_agent_refuses_unusable_context():
    """The refusal has to hold at the agent boundary too, not only in the marshaller."""
    from src.stage_03_judgment.thesis_agent import ThesisAgent

    agent = ThesisAgent.__new__(ThesisAgent)  # no LLM client needed; must return before any call

    unusable = build_story_profile_context(_packet())
    assert agent.generate_story_profile_from_evidence(unusable) is None
    assert agent.generate_story_profile_from_evidence(None) is None


def test_pending_writer_persists_notes_and_evidence_trail(tmp_path):
    from src.stage_03_judgment.thesis_agent import write_story_driver_pending
    import yaml

    out = tmp_path / "story_drivers_pending.yaml"
    write_story_driver_pending(
        "MSFT",
        {
            "moat_strength": 5,
            "pricing_power": 5,
            "cyclicality": "low",
            "capital_intensity": "high",
            "governance_risk": "low",
            "competitive_advantage_years": 15,
            "rationale": "Switching costs and pricing actions support a wide moat.",
            "evidence_basis": "[snip:1] switching costs; [snip:2] price increases",
            "notes": ["Azure build-out is a phase, not steady-state reinvestment."],
            "evidence_anchor_ids": ["snip:1", "snip:2"],
            "source_ref_ids": ["filing:0001"],
        },
        path=out,
    )

    entry = yaml.safe_load(out.read_text(encoding="utf-8"))["MSFT"]
    assert entry["status"] == "pending"  # never auto-applies
    assert entry["profile"]["notes"] == ["Azure build-out is a phase, not steady-state reinvestment."]
    assert entry["evidence_anchor_ids"] == ["snip:1", "snip:2"]
    assert entry["source_ref_ids"] == ["filing:0001"]
    assert "switching costs" in entry["evidence_basis"]


def test_pending_notes_flow_into_the_resolved_profile(tmp_path, monkeypatch):
    """End of the seam: notes written by the agent must survive into StoryDriverProfile.notes,
    which is what downstream driver agents read."""
    import yaml

    from src.stage_02_valuation import story_drivers as sd

    pending = tmp_path / "pending.yaml"
    pending.write_text(
        yaml.dump(
            {
                "MSFT": {
                    "status": "approved",
                    "profile": {
                        "moat_strength": 5,
                        "pricing_power": 5,
                        "cyclicality": "low",
                        "capital_intensity": "high",
                        "governance_risk": "low",
                        "competitive_advantage_years": 15,
                        "notes": ["Patent cliff in FY28."],
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(sd, "STORY_DRIVERS_PENDING_PATH", pending)

    profile, source = sd.resolve_story_driver_profile(ticker="MSFT", sector="Technology")

    assert source == "story_ticker_pending_approved"
    assert profile.notes == ("Patent cliff in FY28.",)
    assert profile.moat_strength == 5
    # A reasoned, ticker-specific profile earns full authority over the drivers.
    assert sd.story_authority_for_source(source) == pytest.approx(1.0)


def test_relevance_ranking_prefers_competitive_disclosure_over_front_matter():
    """Taking excerpts in packet order fills the context with 10-K front matter. Measured on
    MSFT before this ranking: 1 boilerplate block, 4 generic descriptions, 1 about the
    sustainability report — none discussing competitive position."""
    ctx = build_story_profile_context(
        _packet(
            snippets=[
                _snippet("snip:boiler", "Readers are cautioned not to place undue reliance on forward-looking statements."),
                _snippet("snip:generic", "Founded in 1975, we develop and support software and services."),
                _snippet("snip:moat", "Our platform benefits from high switching costs and network effects, and we compete on pricing against alternative offerings."),
            ]
        )
    )

    assert ctx.is_usable
    blocks = [line for line in ctx.context_text.splitlines() if line.startswith("[")]
    # Pure boilerplate is dropped entirely.
    assert not any("undue reliance" in b for b in blocks)
    # The competitive-position excerpt outranks the generic one.
    assert "switching costs" in blocks[0]


def test_boilerplate_that_also_discusses_competition_is_kept():
    """Risk-factor sections mix cautionary language with real competitive disclosure; dropping
    on boilerplate markers alone would discard them."""
    ctx = build_story_profile_context(
        _packet(
            snippets=[
                _snippet("snip:1", "See Item 1A. We face intense competition and market share pressure from rivals."),
                _snippet("snip:2", "Our pricing power derives from premium contract value and high renewal rate."),
            ]
        )
    )
    assert ctx.is_usable
    assert ctx.snippet_count == 2
    assert any("intense competition" in line for line in ctx.context_text.splitlines())


def test_ranking_is_deterministic_for_equal_relevance():
    """Same inputs must yield the same context, or a rerun silently changes what the agent saw."""
    snippets = [
        _snippet("snip:a", "We compete in cloud infrastructure."),
        _snippet("snip:b", "We compete in productivity software."),
        _snippet("snip:c", "We compete in gaming."),
    ]
    first = build_story_profile_context(_packet(snippets=list(snippets)))
    second = build_story_profile_context(_packet(snippets=list(snippets)))
    assert first.context_text == second.context_text
    assert first.evidence_anchor_ids == second.evidence_anchor_ids
