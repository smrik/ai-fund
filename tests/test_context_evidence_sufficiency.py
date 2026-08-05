"""Evidence sufficiency is separate from source authenticity.

`source_quality` only attests that evidence is real. A packet can hold six
authentic-but-boilerplate excerpts and a reported history a full fiscal year
behind the model, and still report `real`. These tests pin the separate
sufficiency state that reports what the packet can actually support.
"""

from __future__ import annotations

from src.stage_04_pipeline.evidence_packets import _context_evidence_sufficiency

_SNIPPET = [{"snippet_id": "snippet:filing:x:0", "text": "..."}]


def test_history_reaching_the_resolved_period_is_sufficient() -> None:
    result = _context_evidence_sufficiency(
        snippets=_SNIPPET,
        revenue_series=[{"period": "2026-06-30", "value": 331_839_000_000.0}],
        resolved_as_of_date="2026-06-30",
    )

    assert result["evidence_sufficiency"] == "sufficient"
    assert result["evidence_gaps"] == []


def test_history_behind_the_resolved_period_is_insufficient() -> None:
    """The packet-228 failure: FY2025 history against an FY2026 model."""
    result = _context_evidence_sufficiency(
        snippets=_SNIPPET,
        revenue_series=[
            {"period": "2024-06-30", "value": 245_122_000_000.0},
            {"period": "2025-06-30", "value": 281_724_000_000.0},
        ],
        resolved_as_of_date="2026-06-30",
    )

    assert result["evidence_sufficiency"] == "insufficient_evidence"
    assert result["evidence_gaps"] == ["history_behind_resolved_period"]


def test_missing_history_and_missing_excerpts_are_reported_separately() -> None:
    no_history = _context_evidence_sufficiency(
        snippets=_SNIPPET,
        revenue_series=[],
        resolved_as_of_date="2026-06-30",
    )
    no_excerpts = _context_evidence_sufficiency(
        snippets=[],
        revenue_series=[{"period": "2026-06-30", "value": 1.0}],
        resolved_as_of_date="2026-06-30",
    )

    assert no_history["evidence_gaps"] == ["no_reported_revenue_history"]
    assert no_excerpts["evidence_gaps"] == ["no_filing_excerpts"]


def test_gaps_accumulate_rather_than_short_circuit() -> None:
    result = _context_evidence_sufficiency(
        snippets=[],
        revenue_series=[],
        resolved_as_of_date="2026-06-30",
    )

    assert result["evidence_gaps"] == [
        "no_filing_excerpts",
        "no_reported_revenue_history",
    ]


def test_unresolved_period_does_not_invent_a_coverage_gap() -> None:
    """The legacy path resolves no period, so coverage cannot be judged."""
    result = _context_evidence_sufficiency(
        snippets=_SNIPPET,
        revenue_series=[{"period": "2019-06-30", "value": 1.0}],
        resolved_as_of_date=None,
    )

    assert result["evidence_sufficiency"] == "sufficient"
