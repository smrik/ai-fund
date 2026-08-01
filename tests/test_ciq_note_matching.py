"""Data-driven CIQ line-item discovery for accounting classification."""
from __future__ import annotations

from src.stage_04_pipeline.ciq_note_matching import (
    derive_note_section,
    find_classification_candidates,
    summarize_candidates,
)


def _row(metric_key: str, value, period="2026-03-31", label=None, calc="LTM") -> dict:
    return {
        "metric_key": metric_key,
        "row_label": label or metric_key.replace("_", " ").title(),
        "period_date": period,
        "calc_type": calc,
        "value_num": value,
    }


def test_unknown_metric_routes_to_a_governing_note_by_its_own_tokens():
    assert (
        derive_note_section(
            "customer_contract_liability_adjustment",
            "Customer contract liability adjustment",
        )
        == "note_revenue"
    )


def test_all_latest_nonzero_metrics_are_discoverable_across_pages():
    rows = [
        _row("unanticipated_alpha", 10.0),
        _row("unanticipated_beta", 20.0),
        _row("unanticipated_gamma", 30.0),
    ]

    first = find_classification_candidates(rows, limit=2)
    second = find_classification_candidates(rows, limit=2, offset=2)

    assert first.total_candidate_metrics == 3
    assert first.shown == 2
    assert first.withheld == 1
    assert second.offset == 2
    assert second.shown == 1
    assert second.withheld == 0
    assert {item.metric_key for item in (*first.items, *second.items)} == {
        "unanticipated_alpha",
        "unanticipated_beta",
        "unanticipated_gamma",
    }


def test_nonzero_adjustment_language_outranks_a_larger_financial_identity():
    candidates = find_classification_candidates(
        [
            _row("total_assets", 1_000_000.0),
            _row("small_restructuring_charge", 5.0),
        ],
        scale_base=100_000.0,
    )

    assert [item.metric_key for item in candidates.items] == [
        "small_restructuring_charge",
        "total_assets",
    ]
    assert candidates.items[0].signals == ("adjustment_language",)


def test_zero_valued_adjustment_lines_are_disclosed_but_do_not_rank():
    candidates = find_classification_candidates(
        [
            _row("oil_and_gas_impairment", 0.0),
            _row("total_assets", 1_000.0),
        ]
    )

    assert [item.metric_key for item in candidates.items] == ["total_assets"]
    assert candidates.zero_valued_adjustment_lines == ("oil_and_gas_impairment",)


def test_latest_period_wins_per_metric():
    candidates = find_classification_candidates(
        [
            _row("total_leases", 70_000.0, period="2025-06-30", calc="FY25"),
            _row("total_leases", 85_170.0, period="2026-03-31", calc="LTM"),
        ],
        {"note_leases"},
    )

    assert len(candidates.items) == 1
    assert candidates.items[0].value == 85_170.0
    assert candidates.items[0].calc_type == "LTM"


def test_nulls_are_excluded_from_population_and_candidates():
    candidates = find_classification_candidates(
        [_row("total_leases", None), _row("total_operating_leases", 22_238.0)]
    )

    assert candidates.total_populated_metrics == 1
    assert [item.metric_key for item in candidates.items] == ["total_operating_leases"]


def test_broad_notes_do_not_count_as_exact_governing_note_coverage():
    candidates = find_classification_candidates(
        [_row("debt", 125_432.0)],
        {"notes_to_financials"},
    )

    assert candidates.items[0].note_section_key == "note_debt"
    assert not candidates.items[0].note_available
    assert not candidates.items[0].has_governing_note


def test_order_is_deterministic_when_rank_and_magnitude_are_equal():
    rows = [_row("zeta_metric", 10.0), _row("alpha_metric", 10.0)]

    first = find_classification_candidates(rows)
    second = find_classification_candidates(list(reversed(rows)))

    assert [item.metric_key for item in first.items] == ["alpha_metric", "zeta_metric"]
    assert first.items == second.items


def test_summary_exposes_page_coverage_and_note_groups():
    candidates = find_classification_candidates(
        [
            _row("operating_lease_obligation", 100.0),
            _row("debt", 90.0),
            _row("unmapped_metric", 80.0),
            _row("restructuring_charge", 0.0),
        ],
        {"note_leases"},
        ticker="msft",
        limit=2,
    )

    summary = summarize_candidates(candidates)

    assert summary["ticker"] == "MSFT"
    assert summary["total_populated_metrics"] == 4
    assert summary["total_candidate_metrics"] == 3
    assert summary["offset"] == 0
    assert summary["shown"] == 2
    assert summary["withheld"] == 1
    assert summary["zero_valued_adjustment_lines"] == ["restructuring_charge"]
    assert summary["by_note"] == {"_unmatched": 1, "note_leases": 1}
