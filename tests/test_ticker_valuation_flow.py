from __future__ import annotations

import argparse
from pathlib import Path

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


def test_heuristic_agent_context_is_available_without_live_provider_setup() -> None:
    """Local heuristic rehearsals must not require a live OpenAI client."""

    with flow.heuristic_agent_runs(True):
        pass


def test_source_preflight_binds_exact_workbook_and_ingest_run(tmp_path: Path, monkeypatch) -> None:
    workbook = tmp_path / "MSFT_Standard.xlsx"
    workbook.write_bytes(b"test workbook")
    db_path = tmp_path / "isolated.db"
    db_path.write_bytes(b"")
    observed: dict[str, object] = {}

    def _fake_build_preflight_manifest(**kwargs):
        observed.update(kwargs)
        return {
            "schema_version": "professional_model_preflight_v1",
            "ticker": "MSFT",
            "status": "blocked",
            "blockers": ["formula_reference_errors:24"],
            "warnings": [],
            "source": {
                "path": str(workbook),
                "source_file": workbook.name,
                "sha256": "abc",
                "run_id": 17,
                "db_path": str(db_path),
            },
            "workbook": {"formula_error_count": 24, "cached_error_count": 0},
        }

    monkeypatch.setattr(flow, "_build_professional_source_preflight", _fake_build_preflight_manifest)

    manifest = flow.derive_source_preflight(
        "MSFT",
        {
            "ticker": "MSFT",
            "ciq_source_file": str(workbook),
            "ciq_run_id": 17,
            "ciq_comps_run_id": 17,
        },
        {"path": str(db_path)},
    )

    assert observed == {
        "ticker": "MSFT",
        "workbook_path": workbook.resolve(),
        "db_path": db_path.resolve(),
        "require_ingested": True,
    }
    assert manifest["status"] == "blocked"
    assert manifest["model_binding"] == {
        "status": "matched",
        "expected_run_ids": [17],
        "observed_run_id": 17,
        "expected_source_file": workbook.name,
        "observed_source_file": workbook.name,
        "db_path": str(db_path.resolve()),
    }


def test_source_preflight_fails_closed_when_workbook_is_missing(tmp_path: Path, monkeypatch) -> None:
    def _missing(**_kwargs):
        raise RuntimeError("no exact workbook")

    monkeypatch.setattr(flow, "_resolve_professional_workbook", _missing)
    manifest = flow.derive_source_preflight(
        "MSFT",
        {"ticker": "MSFT", "ciq_run_id": 9},
        {"path": str(tmp_path / "isolated.db")},
    )

    assert manifest["status"] == "blocked"
    assert manifest["source"]["run_id"] is None
    assert manifest["workbook"]["formula_error_count"] == "unavailable"
    assert manifest["blockers"][0].startswith("source_preflight_unavailable:RuntimeError:")


def test_decision_gate_blocks_missing_or_blocked_source_preflight() -> None:
    missing = flow.attach_decision_readiness(
        {"agent_mode": "live", "errors": [], "profile_runs": [], "deterministic": {}}
    )
    assert missing["decision_ready"] is False
    assert "source_preflight_missing" in missing["decision_blockers"]

    blocked = flow.attach_decision_readiness(
        {
            "agent_mode": "live",
            "errors": [],
            "profile_runs": [],
            "deterministic": {},
            "source_preflight": {
                "status": "blocked",
                "blockers": ["formula_reference_errors:24"],
            },
        }
    )
    assert blocked["decision_ready"] is False
    assert "source_preflight:formula_reference_errors:24" in blocked["decision_blockers"]


def test_heuristic_execution_metadata_has_no_llm_route() -> None:
    args = argparse.Namespace(
        agent_mode="heuristic",
        use_openrouter_free=True,
        openrouter_model="openrouter/free",
    )

    metadata = flow.agent_execution_metadata(args)

    assert metadata == {
        "mode": "heuristic",
        "route": "local_deterministic_heuristic",
        "llm_route": None,
        "llm_model": None,
        "openrouter_requested_but_ignored": True,
    }


def test_markdown_labels_blocked_run_diagnostic_not_pm_reviewable() -> None:
    markdown = flow.render_markdown(
        {
            "ticker": "MSFT",
            "run_started_at": "2026-07-12T00:00:00Z",
            "agent_mode": "heuristic",
            "agent_model": None,
            "agent_execution": {
                "mode": "heuristic",
                "route": "local_deterministic_heuristic",
                "llm_route": None,
                "llm_model": None,
            },
            "openrouter_free": False,
            "database": {},
            "deterministic": {},
            "queue_items": [],
            "profile_runs": [],
            "data_freshness": {},
            "source_preflight": {
                "status": "blocked",
                "blockers": ["formula_reference_errors:24"],
                "source": {"source_file": "MSFT_Standard.xlsx", "run_id": 17, "sha256": "abc"},
            },
            "decision_ready": False,
            "decision_blockers": [
                "source_preflight:formula_reference_errors:24",
                "heuristic_mode_not_investment_grade",
            ],
        }
    )

    assert "Decision-ready: False" in markdown
    assert "Source preflight: blocked" in markdown
    assert "Diagnostic only" in markdown
    assert "no LLM route" in markdown
