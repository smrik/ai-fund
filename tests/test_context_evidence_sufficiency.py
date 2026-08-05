"""Evidence sufficiency is separate from source authenticity.

`source_quality` only attests that evidence is real. A packet can hold six
authentic-but-boilerplate excerpts and a reported history a full fiscal year
behind the model, and still report `real`. These tests pin the separate
sufficiency state that reports what the packet can actually support.
"""

from __future__ import annotations

from src.stage_04_pipeline.evidence.context import (
    ContextEvidenceSnapshot,
    project_business_context,
)

_FILING_SECTIONS = (
    {
        "ticker": "MSFT",
        "form_type": "10-K",
        "accession_no": "0000789019-26-000001",
        "doc_name": "msft.htm",
        "filing_date": "2026-07-30",
        "section_key": "business",
        "section_text": "Item 1. Business overview of Microsoft Corporation.",
    },
    {
        "ticker": "MSFT",
        "form_type": "10-K",
        "accession_no": "0000789019-26-000001",
        "doc_name": "msft.htm",
        "filing_date": "2026-07-30",
        "section_key": "mda",
        "section_text": "Item 7. MD&A overview of Microsoft Corporation.",
    },
)


def _make_snapshot(
    *,
    revenue_series: list[dict[str, float | str]],
    resolved_as_of_date: str | None = "2026-06-30",
    sections: tuple[dict[str, object], ...] = _FILING_SECTIONS,
) -> ContextEvidenceSnapshot:
    facts = []
    if revenue_series:
        facts.append(
            {
                "fact_id": "fact:company_analysis:revenue_series_annual",
                "fact_name": "revenue_series_annual",
                "value": revenue_series,
            }
        )
    return ContextEvidenceSnapshot(
        ticker="MSFT",
        db_path=":memory:",
        financial_as_of_date=resolved_as_of_date or "",
        ciq_run_id=20,
        source_refs=(),
        reported_facts=tuple(facts),
        filing_sections=sections,
    )


def test_history_reaching_the_resolved_period_is_sufficient() -> None:
    snapshot = _make_snapshot(
        revenue_series=[{"period": "2026-06-30", "value": 331_839_000_000.0}],
        resolved_as_of_date="2026-06-30",
    )
    material = project_business_context(snapshot)

    assert material.run_metadata["evidence_sufficiency"] == "sufficient"
    assert material.run_metadata["evidence_gaps"] == []


def test_history_behind_the_resolved_period_is_insufficient() -> None:
    snapshot = _make_snapshot(
        revenue_series=[
            {"period": "2024-06-30", "value": 245_122_000_000.0},
            {"period": "2025-06-30", "value": 281_724_000_000.0},
        ],
        resolved_as_of_date="2026-06-30",
    )
    material = project_business_context(snapshot)

    assert material.run_metadata["evidence_sufficiency"] == "insufficient_evidence"
    assert "history_behind_resolved_period" in material.run_metadata["evidence_gaps"]


def test_missing_history_and_missing_excerpts_are_reported_separately() -> None:
    no_history = project_business_context(
        _make_snapshot(
            revenue_series=[],
            resolved_as_of_date="2026-06-30",
        )
    )
    no_excerpts = project_business_context(
        _make_snapshot(
            revenue_series=[{"period": "2026-06-30", "value": 1.0}],
            resolved_as_of_date="2026-06-30",
            sections=(),
        )
    )

    assert "missing_reported_revenue_history" in no_history.run_metadata["evidence_gaps"]
    assert "missing_latest_business_section" in no_excerpts.run_metadata["evidence_gaps"]
    assert "missing_latest_mda" in no_excerpts.run_metadata["evidence_gaps"]


def test_gaps_accumulate_rather_than_short_circuit() -> None:
    material = project_business_context(
        _make_snapshot(
            revenue_series=[],
            resolved_as_of_date="2026-06-30",
            sections=(),
        )
    )

    assert "missing_latest_business_section" in material.run_metadata["evidence_gaps"]
    assert "missing_latest_mda" in material.run_metadata["evidence_gaps"]
    assert "missing_reported_revenue_history" in material.run_metadata["evidence_gaps"]


def test_unresolved_period_does_not_invent_a_coverage_gap() -> None:
    snapshot = _make_snapshot(
        revenue_series=[{"period": "2019-06-30", "value": 1.0}],
        resolved_as_of_date="",
    )
    material = project_business_context(snapshot)

    assert material.run_metadata["evidence_sufficiency"] == "sufficient"
