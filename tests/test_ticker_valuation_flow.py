from __future__ import annotations

from scripts.manual import run_ticker_valuation_flow as flow


def test_collect_edgar_evidence_summary_counts_live_packet_refs() -> None:
    result = {
        "profile_runs": [
            {
                "profile_name": "earnings_update",
                "evidence_packet": {
                    "source_refs": [
                        {
                            "source_ref_id": "8k:0001193125-26-191457",
                            "source_kind": "8-K",
                            "source_label": "8-K 2026-04-29",
                        }
                    ]
                },
            },
            {
                "profile_name": "company_analysis",
                "evidence_packet": {
                    "source_refs": [
                        {
                            "source_ref_id": "filing:0000950170-25-100235",
                            "source_kind": "10-K",
                            "source_label": "10-K 2025-07-30",
                            "metadata": {"filing_date": "2025-07-30"},
                        },
                        {
                            "source_ref_id": "sec-metrics:10-K:2025-07-30",
                            "source_kind": "sec_xbrl",
                            "source_label": "10-K XBRL metrics 2025-07-30",
                        },
                    ]
                },
            },
        ],
        "evidence_packets": [
            {
                "packet_kind": "risk_review",
                "source_refs": [
                    {
                        "source_ref_id": "risk-filing:0001193125-26-191507",
                        "source_kind": "10-Q",
                        "source_label": "Risk context filing 2026-04-29",
                        "metadata": {"filing_date": "2026-04-29"},
                    },
                    {
                        "source_ref_id": "8k:0001193125-26-191457",
                        "source_kind": "8-K",
                        "source_label": "Duplicate ref",
                    },
                ],
            }
        ],
    }

    summary = flow.collect_edgar_evidence_summary(result)

    assert summary["source_ref_count"] == 4
    assert summary["filing_count"] == 3
    assert summary["latest_filing_date"] == "2026-04-29"
    assert summary["forms"] == {"10-K": 1, "10-Q": 1, "8-K": 1, "sec_xbrl": 1}
    assert summary["profiles"] == {"company_analysis": 2, "earnings_update": 1, "risk_review": 1}


def test_render_markdown_separates_edgar_cache_from_evidence_refs() -> None:
    markdown = flow.render_markdown(
        {
            "ticker": "MSFT",
            "run_started_at": "2026-06-06T15:00:00Z",
            "agent_mode": "heuristic",
            "agent_model": "local_heuristic",
            "openrouter_free": False,
            "database": {},
            "deterministic": {},
            "queue_items": [],
            "profile_runs": [],
            "data_freshness": {
                "market_cache_rows": [],
                "edgar_filing_cache": {"filing_count": 0, "latest_filing_date": None},
                "edgar_evidence_sources": {
                    "filing_count": 3,
                    "source_ref_count": 4,
                    "latest_filing_date": "2026-04-29",
                    "profiles": {"company_analysis": 2},
                },
            },
        }
    )

    assert "EDGAR filing cache: 0 filings" in markdown
    assert "EDGAR evidence used this run: 3 filing refs, 4 source refs" in markdown


def test_render_markdown_reports_ciq_template_ingest() -> None:
    markdown = flow.render_markdown(
        {
            "ticker": "MSFT",
            "run_started_at": "2026-06-06T15:00:00Z",
            "agent_mode": "heuristic",
            "agent_model": "local_heuristic",
            "openrouter_free": False,
            "database": {},
            "deterministic": {},
            "queue_items": [],
            "profile_runs": [],
            "data_freshness": {},
            "ciq_template_ingest": {
                "folder": "ciq/templates",
                "processed": 1,
                "skipped": 0,
                "failed": 0,
            },
        }
    )

    assert "CIQ template ingest: folder=ciq/templates processed=1 skipped=0 failed=0" in markdown


def test_render_markdown_renders_intrinsic_value_bridge_from_persisted_row() -> None:
    markdown = flow.render_markdown(
        {
            "ticker": "MSFT",
            "run_started_at": "2026-08-01T09:00:00Z",
            "agent_mode": "heuristic",
            "agent_model": "local_heuristic",
            "openrouter_free": False,
            "database": {},
            "deterministic": {
                "summary": {},
                "dcf": {"terminal_bridge": {"method_used": "blend"}},
                "batch_row": {
                    "price": 300.0,
                    "iv_base": 228.89,
                    "iv_blended": 228.89,
                    "iv_gordon": 161.40,
                    "iv_exit": 330.11,
                    "drivers_json": '{"terminal_blend_gordon_weight": 0.6, "terminal_blend_exit_weight": 0.4}',
                },
            },
            "queue_items": [],
            "profile_runs": [],
            "data_freshness": {},
        }
    )

    assert "### Intrinsic Value Bridge" in markdown
    assert "Headline blended IV (Base): $228.89" in markdown
    assert "Gordon component: $161.40" in markdown
    assert "Exit component: $330.11" in markdown
    assert "Method used: Blend" in markdown
    assert "60% Gordon / 40% Exit" in markdown


def test_render_markdown_reports_degenerate_intrinsic_value_methods() -> None:
    for method_label, method_used in (("Gordon-only", "gordon_only"), ("Exit-only", "exit_only")):
        markdown = flow.render_markdown(
            {
                "ticker": "MSFT",
                "deterministic": {
                    "summary": {},
                    "dcf": {"terminal_bridge": {"method_used": method_used}},
                    "batch_row": {
                        "iv_base": 228.89,
                        "iv_gordon": 161.40,
                        "iv_exit": 330.11,
                        "drivers_json": '{"terminal_blend_gordon_weight": 0.6, "terminal_blend_exit_weight": 0.4}',
                    },
                },
            }
        )

        assert f"Method used: {method_label}" in markdown
        assert "Blend weights: Blend weights were not applied." in markdown
