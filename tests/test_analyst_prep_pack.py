from __future__ import annotations

from types import SimpleNamespace

import pytest


def test_analyst_prep_pack_maps_drivers_flags_and_public_comps(monkeypatch):
    from src.stage_04_pipeline import analyst_prep_pack

    monkeypatch.setattr(
        analyst_prep_pack,
        "build_override_workbench",
        lambda ticker: {
            "ticker": "IBM",
            "available": True,
            "fields": [
                {
                    "field": "revenue_growth_near",
                    "label": "Revenue Growth (Near)",
                    "baseline_value": 0.06,
                    "effective_value": 0.08,
                    "effective_source": "ciq_consensus",
                    "unit": "pct",
                },
                {
                    "field": "wacc",
                    "label": "WACC",
                    "baseline_value": 0.09,
                    "effective_value": 0.095,
                    "effective_source": "wacc_peer_beta",
                    "unit": "pct",
                },
                {
                    "field": "exit_multiple",
                    "label": "Exit Multiple",
                    "baseline_value": 11.0,
                    "effective_value": 12.0,
                    "effective_source": "public_market_yfinance_fallback",
                    "unit": "x",
                },
            ],
            "default_resolution": {
                "status": "review_required",
                "fields": [
                    {
                        "field": "exit_multiple",
                        "severity": "high",
                        "needs_pm_review": True,
                        "reason": "Public fallback used.",
                        "preferred_replacement_source": "CIQ comps",
                        "source": "public_market_yfinance_fallback",
                    },
                    {
                        "field": "dso_start",
                        "severity": "medium",
                        "needs_pm_review": False,
                        "reason": "Resolved from statement-derived working capital.",
                        "preferred_replacement_source": "statement_derived",
                        "source": "statement_derived",
                    }
                ],
            },
            "ciq_lineage": {"snapshot_source_file": "ciq.xlsx"},
        },
    )
    monkeypatch.setattr(
        analyst_prep_pack,
        "build_dcf_audit_view",
        lambda ticker: {
            "ticker": "IBM",
            "available": True,
            "current_price": 100.0,
            "scenario_summary": [{"scenario": "Base", "intrinsic_value": 150.0}],
        },
    )
    monkeypatch.setattr(
        analyst_prep_pack,
        "build_comps_dashboard_view",
        lambda ticker: {
            "available": True,
            "primary_metric": "tev_ebitda_ltm",
            "peer_counts": {"raw": 4, "clean": 3},
            "source_lineage": {"source": "public_market_yfinance_fallback", "source_file": "public_market_yfinance_fallback"},
            "target_vs_peers": {"deltas": {"tev_ebitda_ltm": -1.5}},
            "audit_flags": ["No CIQ comps detail available; using public market yfinance fallback comps"],
        },
    )
    monkeypatch.setattr(analyst_prep_pack, "build_research_board_view", lambda ticker: {"available": True})
    monkeypatch.setattr(
        analyst_prep_pack,
        "build_valuation_inputs",
        lambda ticker, apply_overrides=True: SimpleNamespace(
            drivers=SimpleNamespace(revenue_growth_terminal=0.025),
            source_lineage={"revenue_growth_terminal": "sector_prior"},
        ),
    )
    monkeypatch.setattr(
        analyst_prep_pack,
        "_load_store_state",
        lambda ticker: (
            [
                {
                    "packet_id": 7,
                    "profile_name": "company_analysis",
                    "run_metadata": {"source_quality": "real"},
                    "facts": [{"fact_id": "fact:growth", "label": "Growth", "value": 8.0, "unit": "%"}],
                    "observations": [],
                }
            ],
            [
                {
                    "item_id": 9,
                    "ticker": "IBM",
                    "profile_name": "company_analysis",
                    "item_type": "assumption_change_pack",
                    "status": "pending",
                    "summary": "Review growth.",
                    "evidence_anchor_ids": ["fact:growth"],
                    "evidence_packet_ids": ["7"],
                    "proposal_pack": {
                        "proposals": [
                            {
                                "assumption_name": "revenue_growth_near",
                                "proposal_mode": "target",
                                "proposed_target_value": 0.10,
                            }
                        ]
                    },
                }
            ],
        ),
    )

    pack = analyst_prep_pack.build_analyst_prep_pack("ibm")

    assert pack.ticker == "IBM"
    assert pack.source_quality == "real"
    assert any(card.card_id == "IBM:valuation_setup" for card in pack.thesis_cards)
    growth = next(card for card in pack.driver_cards if card.assumption_name == "revenue_growth_near")
    assert growth.proposed_or_effective_value == 0.10
    assert growth.pm_review_status == "review_required"
    exit_multiple = next(card for card in pack.driver_cards if card.assumption_name == "exit_multiple")
    assert exit_multiple.pm_review_status == "review_required"
    assert any(flag.flag_id == "segment_data_missing" for flag in pack.missing_data)
    assert any(flag.flag_id == "public_comps_fallback" for flag in pack.missing_data)
    assert any(flag.flag_id == "default_resolution:exit_multiple" for flag in pack.missing_data)
    assert not any(flag.flag_id == "default_resolution:dso_start" for flag in pack.missing_data)
    assert pack.comps_card is not None
    assert pack.comps_card.peer_set_quality == "partial"
    assert pack.evidence_packet_ids == [7]


def test_analyst_prep_driver_cards_mark_true_cross_profile_conflicts(monkeypatch):
    from src.stage_04_pipeline import analyst_prep_pack

    monkeypatch.setattr(
        analyst_prep_pack,
        "build_override_workbench",
        lambda ticker: {
            "ticker": "IBM",
            "available": True,
            "fields": [
                {
                    "field": "revenue_growth_near",
                    "label": "Revenue Growth (Near)",
                    "baseline_value": 0.06,
                    "effective_value": 0.08,
                    "effective_source": "ciq_consensus",
                    "unit": "pct",
                }
            ],
            "default_resolution": {"status": "ok", "fields": []},
        },
    )
    monkeypatch.setattr(
        analyst_prep_pack,
        "build_dcf_audit_view",
        lambda ticker: {"ticker": "IBM", "available": True, "current_price": 100.0, "scenario_summary": []},
    )
    monkeypatch.setattr(analyst_prep_pack, "build_comps_dashboard_view", lambda ticker: {"available": False})
    monkeypatch.setattr(analyst_prep_pack, "build_research_board_view", lambda ticker: {"available": True})
    monkeypatch.setattr(
        analyst_prep_pack,
        "build_valuation_inputs",
        lambda ticker, apply_overrides=True: SimpleNamespace(
            drivers=SimpleNamespace(revenue_growth_terminal=0.025),
            source_lineage={"revenue_growth_terminal": "sector_prior"},
        ),
    )
    monkeypatch.setattr(
        analyst_prep_pack,
        "_load_store_state",
        lambda ticker: (
            [],
            [
                {
                    "item_id": 1,
                    "ticker": "IBM",
                    "profile_name": "company_analysis",
                    "item_type": "assumption_change_pack",
                    "status": "pending",
                    "proposal_pack": {
                        "proposals": [
                            {
                                "assumption_name": "revenue_growth_near",
                                "proposal_mode": "target",
                                "proposed_target_value": 0.10,
                            }
                        ]
                    },
                },
                {
                    "item_id": 2,
                    "ticker": "IBM",
                    "profile_name": "industry_analysis",
                    "item_type": "assumption_change_pack",
                    "status": "previewed",
                    "proposal_pack": {
                        "proposals": [
                            {
                                "assumption_name": "revenue_growth_near",
                                "proposal_mode": "target",
                                "proposed_target_value": 0.05,
                            }
                        ]
                    },
                },
            ],
        ),
    )

    pack = analyst_prep_pack.build_analyst_prep_pack("IBM")

    growth = next(card for card in pack.driver_cards if card.assumption_name == "revenue_growth_near")
    assert growth.pm_review_status == "conflict"
    assert "different values" in growth.rationale
    assert pack.conflict_groups[0]["conflict_level"] == "conflict"


def test_segment_driver_rows_parse_explicit_ciq_segment_records():
    from src.stage_04_pipeline.analyst_prep_pack import _segment_driver_rows_from_records

    records = [
        {
            "ticker": "IBM",
            "source_file": "ciq.xlsx",
            "sheet_name": "Segment Detail",
            "section_name": "Reportable Segment Revenue",
            "row_label": "Software Revenue",
            "metric_key": "software_revenue",
            "period_date": "2025-12-31",
            "value_num": 120.0,
        },
        {
            "ticker": "IBM",
            "source_file": "ciq.xlsx",
            "sheet_name": "Segment Detail",
            "section_name": "Reportable Segment Revenue",
            "row_label": "Software Revenue",
            "metric_key": "software_revenue",
            "period_date": "2024-12-31",
            "value_num": 100.0,
        },
        {
            "ticker": "IBM",
            "source_file": "ciq.xlsx",
            "sheet_name": "Segment Detail",
            "section_name": "Reportable Segment Margin",
            "row_label": "Software Margin",
            "metric_key": "software_margin",
            "period_date": "2025-12-31",
            "value_num": 35.0,
        },
        {
            "ticker": "IBM",
            "source_file": "ciq.xlsx",
            "sheet_name": "Segment Detail",
            "section_name": "Reportable Segment Revenue",
            "row_label": "Consulting Revenue",
            "metric_key": "consulting_revenue",
            "period_date": "2025-12-31",
            "value_num": 80.0,
        },
        {
            "ticker": "IBM",
            "source_file": "ciq.xlsx",
            "sheet_name": "Financial Statements",
            "section_name": "Income Statement",
            "row_label": "Revenue",
            "metric_key": "revenue",
            "period_date": "2025-12-31",
            "value_num": 999.0,
        },
    ]

    rows = _segment_driver_rows_from_records("IBM", records)

    software = next(row for row in rows if row.segment == "Software")
    consulting = next(row for row in rows if row.segment == "Consulting")
    assert software.revenue_growth == pytest.approx(0.2)
    assert software.margin == pytest.approx(0.35)
    assert software.revenue_mix == pytest.approx(0.6)
    assert software.quality == "real"
    assert consulting.revenue_mix == pytest.approx(0.4)
    assert consulting.quality == "partial"
    assert all(row.segment != "Revenue" for row in rows)
