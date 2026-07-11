import sqlite3
from types import SimpleNamespace

import pytest

from db.loader import load_evidence_packet
from db.schema import create_tables
from src.contracts.evidence_packet import EvidencePacketKind
from src.stage_04_pipeline import evidence_packets
from src.stage_04_pipeline.evidence_packets import build_evidence_packet


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_tables(conn)
    return conn


def test_accounting_packet_collects_retrieval_profile_sections_and_source_locators(monkeypatch):
    """Accounting packets must preserve deterministic filing provenance."""
    conn = _conn()
    monkeypatch.setattr("src.stage_04_pipeline.evidence_packets.get_connection", lambda: conn)
    calls = []

    def _filing_context(ticker, **kwargs):
        calls.append((ticker, kwargs))
        return SimpleNamespace(
            sources=[
                {
                    "accession_no": "000-accounting",
                    "form_type": "10-K",
                    "doc_name": "msft-10k.htm",
                    "filing_date": "2026-07-01",
                    "source_locator": "https://www.sec.gov/Archives/edgar/data/msft-10k.htm",
                }
            ],
            selected_chunks=[
                SimpleNamespace(
                    accession_no="000-accounting",
                    chunk_index=2,
                    text="Note 8 discloses operating lease liabilities.",
                    section_key="note_leases",
                    filing_date="2026-07-01",
                    score=0.99,
                ),
                SimpleNamespace(
                    accession_no="000-accounting",
                    chunk_index=5,
                    text="Note 12 discloses segment revenue and margin.",
                    section_key="note_segments",
                    filing_date="2026-07-01",
                    score=0.95,
                ),
                SimpleNamespace(
                    accession_no="000-accounting",
                    chunk_index=8,
                    text="Note 9 discloses income taxes and uncertain tax positions.",
                    section_key="note_taxes",
                    filing_date="2026-07-01",
                    score=0.94,
                ),
            ],
            retrieval_summary={
                "selected_section_keys": ["note_leases", "note_segments"],
                "section_coverage": {
                    "by_section_key": {"note_leases": 1, "note_segments": 1},
                },
                "selected_source_locators": [
                    "edgar://000-accounting/note_leases/2",
                    "edgar://000-accounting/note_segments/5",
                ],
                "topic_coverage": {
                    "leases": "retrieved",
                    "pensions": "searched_absent",
                },
            },
        )

    monkeypatch.setattr(
        "src.stage_04_pipeline.evidence_packets.get_agent_filing_context",
        _filing_context,
    )
    monkeypatch.setattr(
        "src.stage_04_pipeline.evidence_packets.build_valuation_inputs",
        lambda ticker: SimpleNamespace(
            as_of_date="2026-07-01",
            drivers=SimpleNamespace(
                net_debt=1200.0,
                non_operating_assets=400.0,
                lease_liabilities=250.0,
                minority_interest=30.0,
                preferred_equity=0.0,
                pension_deficit=15.0,
                shares_outstanding=7500.0,
            ),
        ),
    )

    packet = build_evidence_packet("msft", "accounting_ev_equity_bridge")

    assert packet.packet_kind == EvidencePacketKind.accounting
    assert packet.profile_name == "accounting_ev_equity_bridge"
    assert calls[0][1]["profile_name"] == "accounting_recast"
    assert packet.run_metadata["selected_section_keys"] == ["note_leases", "note_segments"]
    assert packet.run_metadata["selected_source_locators"] == [
        "edgar://000-accounting/note_leases/2",
        "edgar://000-accounting/note_segments/5",
    ]
    assert packet.source_refs[0].source_locator == "https://www.sec.gov/Archives/edgar/data/msft-10k.htm"

    facts = {fact.fact_name: fact.value for fact in packet.facts}
    assert facts["net_debt"] == 1200.0
    assert facts["non_operating_assets"] == 400.0
    assert facts["lease_liabilities"] == 250.0
    assert facts["minority_interest"] == 30.0
    assert facts["pension_deficit"] == 15.0
    assert facts["shares_outstanding"] == 7500.0
    assert facts["topic_coverage_note_leases"] == "selected"
    assert facts["topic_coverage_note_pension"] == "searched_absent"
    assert [snippet.metadata["section_key"] for snippet in packet.snippets] == [
        "note_leases",
        "note_segments",
    ]


def test_accounting_packet_distinguishes_retrieval_missing_from_searched_absent(monkeypatch):
    conn = _conn()
    monkeypatch.setattr("src.stage_04_pipeline.evidence_packets.get_connection", lambda: conn)
    monkeypatch.setattr(
        "src.stage_04_pipeline.evidence_packets.get_agent_filing_context",
        lambda ticker, **kwargs: (_ for _ in ()).throw(RuntimeError("EDGAR unavailable")),
    )
    monkeypatch.setattr(
        "src.stage_04_pipeline.evidence_packets.build_valuation_inputs",
        lambda ticker: SimpleNamespace(as_of_date="2026-07-01", drivers=SimpleNamespace()),
    )

    packet = build_evidence_packet("msft", "accounting_contingencies_and_taxes")
    facts = {fact.fact_name: fact.value for fact in packet.facts}

    assert facts["topic_coverage_note_contingencies"] == "retrieval_unavailable"
    assert facts["topic_coverage_note_taxes"] == "retrieval_unavailable"

    monkeypatch.setattr(
        "src.stage_04_pipeline.evidence_packets.get_agent_filing_context",
        lambda ticker, **kwargs: SimpleNamespace(
            sources=[{"accession_no": "0001", "form_type": "10-K", "doc_name": "msft.htm"}],
            selected_chunks=[],
            retrieval_summary={
                "selected_section_keys": [],
                "section_coverage": {"by_section_key": {"notes_to_financials": 1}},
            },
        ),
    )
    searched_packet = build_evidence_packet("msft", "accounting_contingencies_and_taxes")
    searched_facts = {fact.fact_name: fact.value for fact in searched_packet.facts}
    assert searched_facts["topic_coverage_note_contingencies"] == "searched_absent"
    assert searched_facts["topic_coverage_note_taxes"] == "searched_absent"


def test_accounting_qoe_packet_contains_reported_and_deterministic_qoe_facts(monkeypatch):
    conn = _conn()
    monkeypatch.setattr("src.stage_04_pipeline.evidence_packets.get_connection", lambda: conn)
    monkeypatch.setattr(
        "src.stage_04_pipeline.evidence_packets.get_agent_filing_context",
        lambda ticker, **kwargs: SimpleNamespace(
            sources=[
                {
                    "accession_no": "qoe-10k",
                    "form_type": "10-K",
                    "doc_name": "msft.htm",
                    "filing_date": "2026-07-01",
                }
            ],
            selected_chunks=[
                SimpleNamespace(
                    accession_no="qoe-10k",
                    chunk_index=1,
                    text="Revenue recognition note describes contract assets and deferred revenue.",
                    section_key="note_revenue",
                    filing_date="2026-07-01",
                    score=0.97,
                )
            ],
            retrieval_summary={
                "selected_section_keys": ["note_revenue"],
                "section_coverage": {"by_section_key": {"note_revenue": 1}},
            },
        ),
    )
    monkeypatch.setattr(
        "src.stage_04_pipeline.evidence_packets.build_valuation_inputs",
        lambda ticker: SimpleNamespace(
            sector="Technology",
            as_of_date="2026-07-01",
            drivers=SimpleNamespace(
                revenue_growth_near=0.12,
                revenue_growth_mid=0.09,
                ebit_margin_start=0.44,
                ebit_margin_target=0.332,
                tax_rate_start=0.18,
                tax_rate_target=0.20,
            ),
            source_lineage={"ebit_margin_target": "story_sector"},
        ),
    )
    monkeypatch.setattr(
        "src.stage_04_pipeline.evidence_packets.get_historical_financials",
        lambda ticker, use_cache=True: {
            "operating_income": [128_500_000_000.0],
            "revenue": [300_000_000_000.0],
            "cffo": [100_000_000_000.0],
            "capex": [20_000_000_000.0],
            "da": [10_000_000_000.0],
            "sbc": 8_000_000_000.0,
            "effective_tax_rate_avg": 0.19,
        },
    )
    monkeypatch.setattr(
        "src.stage_04_pipeline.evidence_packets.get_market_data",
        lambda ticker, use_cache=True: {"sector": "Technology", "ebitda_ttm": 140_000_000_000.0},
    )
    monkeypatch.setattr(
        "src.stage_04_pipeline.evidence_packets.get_ciq_snapshot",
        lambda ticker: {"operating_income_ttm": 128_500_000_000.0, "da_ttm": 10_000_000_000.0},
    )
    monkeypatch.setattr(
        "src.stage_04_pipeline.evidence_packets.get_ciq_nwc_history",
        lambda ticker: [{"period_date": "2026-06-30", "dso": 45.0, "dio": 30.0, "dpo": 55.0}],
    )
    monkeypatch.setattr(
        "src.stage_04_pipeline.evidence_packets.compute_qoe_signals",
        lambda *args, **kwargs: {
            "qoe_score": 4,
            "qoe_flag": "green",
            "sloan_accruals_ratio": 0.02,
            "cash_conversion": 0.71,
            "dso_current": 45.0,
            "dso_baseline": 42.0,
            "dso_drift": 3.0,
            "signal_scores": {"accruals": "green"},
            "forensic_flag": "clear",
        },
    )

    packet = build_evidence_packet("msft", "accounting_qoe")

    assert packet.packet_kind == EvidencePacketKind.accounting
    assert packet.profile_name == "accounting_qoe"
    assert packet.run_metadata["retrieval_profile"] == "qoe"
    facts = {fact.fact_name: fact.value for fact in packet.facts}
    assert facts["reported_ebit"] == 128_500_000_000.0
    assert facts["sloan_accruals_ratio"] == 0.02
    assert facts["cash_conversion"] == 0.71
    assert facts["qoe_flag"] == "green"
    assert facts["ebit_margin_target"] == 0.332
    assert facts["topic_coverage_note_revenue"] == "selected"


@pytest.mark.parametrize(
    "profile_name",
    (
        "accounting_qoe",
        "accounting_ev_equity_bridge",
        "accounting_contingencies_and_taxes",
        "accounting_segments_and_disclosure",
    ),
)
def test_all_accounting_packets_include_structured_xbrl_fact_provenance(
    monkeypatch,
    profile_name,
):
    conn = _conn()
    monkeypatch.setattr("src.stage_04_pipeline.evidence_packets.get_connection", lambda: conn)
    monkeypatch.setattr(
        "src.stage_04_pipeline.evidence_packets.get_agent_filing_context",
        lambda ticker, **kwargs: SimpleNamespace(
            sources=[],
            selected_chunks=[],
            retrieval_summary={},
        ),
    )
    monkeypatch.setattr(
        "src.stage_04_pipeline.evidence_packets.build_valuation_inputs",
        lambda ticker: SimpleNamespace(
            as_of_date="2026-07-01",
            sector="Technology",
            drivers=SimpleNamespace(),
            source_lineage={},
        ),
    )
    monkeypatch.setattr(
        "src.stage_04_pipeline.evidence_packets.get_historical_financials",
        lambda ticker, use_cache=True: {},
    )
    monkeypatch.setattr(
        "src.stage_04_pipeline.evidence_packets.get_market_data",
        lambda ticker, use_cache=True: {},
    )
    monkeypatch.setattr(
        "src.stage_04_pipeline.evidence_packets.get_ciq_snapshot",
        lambda ticker: {},
    )
    monkeypatch.setattr(
        "src.stage_04_pipeline.evidence_packets.get_ciq_nwc_history",
        lambda ticker: [],
    )
    monkeypatch.setattr(
        "src.stage_04_pipeline.evidence_packets.compute_qoe_signals",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        "src.stage_04_pipeline.evidence_packets.get_xbrl_fact_evidence",
        lambda ticker, concepts, max_facts_per_concept=None: {
            "status": "ok",
            "cik": "0000789019",
            "fact_count": 1,
            "errors": [],
            "facts": [
                {
                    "fact_id": "xbrl:MSFT:0000950170-25-100235:us-gaap:Cash:D1",
                    "fact_name": "us-gaap:CashAndCashEquivalentsAtCarryingValue",
                    "value": 100.0,
                    "numeric_value": 100.0,
                    "unit": "USD",
                    "period": "2025-06-30",
                    "source_locator": "https://www.sec.gov/Archives/edgar/data/789019/000095017025100235-index.html",
                    "metadata": {
                        "source": "sec_xbrl_companyfacts_v3",
                        "taxonomy": "us-gaap",
                        "label": "Cash and cash equivalents",
                        "accession": "0000950170-25-100235",
                        "filing_date": "2025-07-30",
                        "form_type": "10-K",
                        "context_ref": "D1",
                        "dimensions": {},
                        "statement_type": "BalanceSheet",
                    },
                }
            ],
        },
    )

    packet = build_evidence_packet("msft", profile_name)

    xbrl_facts = [
        fact for fact in packet.facts
        if fact.metadata.get("fact_role") == "xbrl_structured_fact"
    ]
    assert len(xbrl_facts) == 1
    assert xbrl_facts[0].value == 100.0
    assert xbrl_facts[0].unit == "USD"
    assert xbrl_facts[0].metadata["accession"] == "0000950170-25-100235"
    assert xbrl_facts[0].metadata["source_locator"].endswith("-index.html")
    assert any(
        ref.source_kind == "sec_xbrl_fact"
        and ref.source_locator.endswith("-index.html")
        for ref in packet.source_refs
    )
    assert packet.run_metadata["xbrl_fact_count"] == 1
    assert packet.run_metadata["xbrl_retrieval_status"] == "ok"


def test_company_analysis_packet_uses_filing_context_and_sec_metrics(monkeypatch):
    conn = _conn()
    monkeypatch.setattr("src.stage_04_pipeline.evidence_packets.get_connection", lambda: conn)
    monkeypatch.setattr(
        "src.stage_04_pipeline.evidence_packets.get_agent_filing_context",
        lambda ticker, **kwargs: SimpleNamespace(
            sources=[
                {
                    "accession_no": "0001",
                    "form_type": "10-K",
                    "doc_name": "ibm-10k.htm",
                    "filing_date": "2026-02-01",
                }
            ],
            selected_chunks=[
                SimpleNamespace(
                    accession_no="0001",
                    chunk_index=0,
                    text="Revenue growth remained resilient across software and consulting.",
                    section_key="mda",
                    filing_date="2026-02-01",
                    score=0.91,
                )
            ],
            retrieval_summary={"selected_chunk_count": 1},
        ),
    )
    monkeypatch.setattr(
        "src.stage_04_pipeline.evidence_packets.get_sec_filing_metrics",
        lambda ticker: SimpleNamespace(
            source_form="10-K",
            source_filing_date="2026-02-01",
            metric_source="sec_xbrl_companyfacts",
            revenue_cagr_3y=0.08,
            ebit_margin_avg_3y=0.19,
            gross_margin_avg_3y=0.52,
            net_debt_to_ebitda=None,
            fcf_yield=None,
            revenue_series=[
                {"period": "2024-12-31", "value": 100.0},
                {"period": "2025-12-31", "value": 108.0},
            ],
            ebit_series=[
                {"period": "2024-12-31", "value": 19.0},
                {"period": "2025-12-31", "value": 20.5},
            ],
        ),
    )
    monkeypatch.setattr(
        "src.stage_04_pipeline.evidence_packets.build_valuation_inputs",
        lambda ticker: SimpleNamespace(
            as_of_date="2026-05-15",
            drivers=SimpleNamespace(
                revenue_growth_near=0.07,
                ebit_margin_start=0.18,
                ebit_margin_target=0.20,
            ),
        ),
    )

    packet = build_evidence_packet("ibm", "company_analysis")

    assert packet.packet_kind == EvidencePacketKind.company_analysis
    assert packet.run_metadata["source_quality"] == "real"
    assert packet.source_refs[0].source_ref_id == "filing:0001"
    assert packet.source_refs[1].source_ref_id == "sec-metrics:10-K:2026-02-01"
    assert packet.snippets[0].source_ref_id == "filing:0001"
    fact_names = {fact.fact_name for fact in packet.facts}
    assert {
        "filing_source_count",
        "filing_selected_chunk_count",
        "revenue_cagr_3y",
        "revenue_series_annual",
        "model_assumption_revenue_growth_near",
    } <= fact_names
    # Retrieval plumbing must not surface as evidence facts.
    assert not any(name.startswith("filing_section_count_") for name in fact_names)

    persisted = load_evidence_packet(conn, packet.packet_id)
    assert persisted is not None
    assert persisted["run_metadata"]["source_quality"] == "real"
    assert persisted["snippets"][0]["metadata"]["section_key"] == "mda"


def test_earnings_update_packet_uses_recent_8k_and_market_data(monkeypatch):
    conn = _conn()
    monkeypatch.setattr("src.stage_04_pipeline.evidence_packets.get_connection", lambda: conn)
    monkeypatch.setattr(
        "src.stage_04_pipeline.evidence_packets.get_8k_texts",
        lambda ticker, limit=3, max_chars_each=4000: [
            {
                "accession_no": "8k-1",
                "filing_date": "2026-05-01",
                "text": "Management raised full-year guidance and cited improving demand trends.",
            }
        ],
    )
    monkeypatch.setattr(
        "src.stage_04_pipeline.evidence_packets.build_valuation_inputs",
        lambda ticker: SimpleNamespace(
            as_of_date="2026-05-15",
            drivers=SimpleNamespace(
                revenue_growth_near=0.07,
                revenue_growth_mid=0.05,
                ebit_margin_start=0.16,
                ebit_margin_target=0.18,
            ),
            source_lineage={"revenue_growth_near": "ciq_consensus"},
        ),
    )
    monkeypatch.setattr(
        "src.stage_04_pipeline.evidence_packets.get_market_data",
        lambda ticker, use_cache=True: {
            "current_price": 125.0,
            "analyst_target_mean": 140.0,
            "analyst_recommendation": "buy",
            "number_of_analysts": 18,
        },
    )

    packet = build_evidence_packet("ibm", "earnings_update")

    assert packet.packet_kind == EvidencePacketKind.earnings_update
    assert packet.run_metadata["source_quality"] == "real"
    ref_ids = [ref.source_ref_id for ref in packet.source_refs]
    assert ref_ids[0] == "8k:8k-1"
    assert "model-assumptions:ibm" in ref_ids
    assert "market:latest" in ref_ids
    assert packet.snippets[0].text.startswith("Management raised full-year guidance")
    fact_names = {fact.fact_name for fact in packet.facts}
    assert {"current_price", "analyst_target_mean", "analyst_recommendation", "number_of_analysts"} <= fact_names
    assert {"model_assumption_revenue_growth_near", "model_assumption_ebit_margin_target"} <= fact_names
    # Assumption facts carry their provenance so agents can state the basis.
    growth_fact = next(f for f in packet.facts if f.fact_name == "model_assumption_revenue_growth_near")
    assert growth_fact.metadata["source_lineage"] == "ciq_consensus"


def test_extract_total_revenue_facts_handles_single_space_table_layout():
    # Real 8-K layout: '$' only on the first column, single spaces between values.
    text = "Operating income $ 3,672 3,526 4% Total Revenue $ 82,886 70,066 18%"
    facts = evidence_packets._extract_total_revenue_facts(text)
    assert facts["latest_quarter_total_revenue_mm"] == 82886.0
    assert facts["prior_year_quarter_total_revenue_mm"] == 70066.0
    assert facts["latest_quarter_revenue_yoy_pct"] == 18.3

    # A percent-change column must never be misread as prior-year revenue.
    facts = evidence_packets._extract_total_revenue_facts("Total revenue $ 82,886 18")
    assert facts == {"latest_quarter_total_revenue_mm": 82886.0}

    # Change columns can look ratio-comparable, but YTD totals cannot be below
    # their corresponding latest-quarter totals.
    facts = evidence_packets._extract_total_revenue_facts("Total revenue 100 90 10 11")
    assert facts == {
        "latest_quarter_total_revenue_mm": 100.0,
        "prior_year_quarter_total_revenue_mm": 90.0,
        "latest_quarter_revenue_yoy_pct": 11.11,
    }


def test_valuation_review_packet_uses_inputs_and_dcf_scenarios(monkeypatch):
    conn = _conn()
    monkeypatch.setattr("src.stage_04_pipeline.evidence_packets.get_connection", lambda: conn)
    monkeypatch.setattr(
        "src.stage_04_pipeline.evidence_packets.build_valuation_inputs",
        lambda ticker: SimpleNamespace(
            as_of_date="2026-05-15",
            drivers=SimpleNamespace(
                revenue_growth_near=0.07,
                revenue_growth_mid=0.05,
                ebit_margin_target=0.18,
                wacc=0.09,
                exit_multiple=12.0,
            ),
            source_lineage={"revenue_growth_near": "ciq_consensus", "wacc": "wacc_methodology:peer_bottom_up"},
        ),
    )
    monkeypatch.setattr(
        "src.stage_04_pipeline.evidence_packets.default_scenario_specs",
        lambda: [SimpleNamespace(name="base"), SimpleNamespace(name="bull")],
    )
    monkeypatch.setattr(
        "src.stage_04_pipeline.evidence_packets.run_dcf_professional",
        lambda drivers, spec: SimpleNamespace(intrinsic_value_per_share=150.0 if spec.name == "base" else 180.0),
    )

    packet = build_evidence_packet("ibm", "valuation_review")

    assert packet.packet_kind == EvidencePacketKind.valuation_review
    assert packet.run_metadata["source_quality"] == "real"
    fact_names = {fact.fact_name for fact in packet.facts}
    assert "revenue_growth_near" in fact_names
    assert "scenario_iv_base" in fact_names
    assert "scenario_iv_bull" in fact_names
    driver_fact = next(fact for fact in packet.facts if fact.fact_name == "wacc")
    assert driver_fact.metadata["source_lineage"] == "wacc_methodology:peer_bottom_up"


def test_valuation_review_omits_expected_value_when_a_dcf_scenario_fails(monkeypatch):
    conn = _conn()
    monkeypatch.setattr("src.stage_04_pipeline.evidence_packets.get_connection", lambda: conn)
    monkeypatch.setattr(
        "src.stage_04_pipeline.evidence_packets.build_valuation_inputs",
        lambda ticker: SimpleNamespace(
            as_of_date="2026-05-15",
            drivers=SimpleNamespace(
                revenue_growth_near=0.07,
                revenue_growth_mid=0.05,
                ebit_margin_target=0.18,
                wacc=0.09,
                exit_multiple=12.0,
            ),
            source_lineage={},
        ),
    )
    monkeypatch.setattr(
        "src.stage_04_pipeline.evidence_packets.build_dcf_audit_view",
        lambda ticker: {},
    )
    monkeypatch.setattr(
        "src.stage_04_pipeline.evidence_packets.default_scenario_specs",
        lambda: [
            SimpleNamespace(name="bear", probability=0.2),
            SimpleNamespace(name="base", probability=0.6),
            SimpleNamespace(name="bull", probability=0.2),
        ],
    )

    def _run_dcf(drivers, spec):
        if spec.name == "bull":
            raise RuntimeError("bull scenario failed")
        return SimpleNamespace(intrinsic_value_per_share={"bear": 80.0, "base": 110.0}[spec.name])

    monkeypatch.setattr("src.stage_04_pipeline.evidence_packets.run_dcf_professional", _run_dcf)
    monkeypatch.setattr(
        "src.stage_04_pipeline.evidence_packets.get_market_data",
        lambda ticker, use_cache=True: {"current_price": 100.0},
    )

    packet = build_evidence_packet("ibm", "valuation_review")

    fact_names = {fact.fact_name for fact in packet.facts}
    assert "scenario_upside_pct_bear" in fact_names
    assert "scenario_upside_pct_base" in fact_names
    assert "expected_iv_probability_weighted" not in fact_names
    assert "expected_upside_pct" not in fact_names
    scenario_status = next(
        status for status in packet.run_metadata["collector_statuses"] if status["collector"] == "dcf_scenarios"
    )
    assert scenario_status["status"] == "partial"
    assert scenario_status["scenario_fact_count"] == 2


def test_valuation_review_reports_missing_market_price_status(monkeypatch):
    conn = _conn()
    monkeypatch.setattr("src.stage_04_pipeline.evidence_packets.get_connection", lambda: conn)
    monkeypatch.setattr(
        "src.stage_04_pipeline.evidence_packets.build_valuation_inputs",
        lambda ticker: SimpleNamespace(
            as_of_date="2026-05-15",
            drivers=SimpleNamespace(wacc=0.09, exit_multiple=12.0),
            source_lineage={},
        ),
    )
    monkeypatch.setattr(
        "src.stage_04_pipeline.evidence_packets.build_dcf_audit_view",
        lambda ticker: {},
    )
    monkeypatch.setattr(
        "src.stage_04_pipeline.evidence_packets.default_scenario_specs",
        lambda: [SimpleNamespace(name="base", probability=1.0)],
    )
    monkeypatch.setattr(
        "src.stage_04_pipeline.evidence_packets.run_dcf_professional",
        lambda drivers, spec: SimpleNamespace(intrinsic_value_per_share=120.0),
    )
    monkeypatch.setattr(
        "src.stage_04_pipeline.evidence_packets.get_market_data",
        lambda ticker, use_cache=True: {},
    )

    packet = build_evidence_packet("ibm", "valuation_review")

    market_status = next(
        status for status in packet.run_metadata["collector_statuses"] if status["collector"] == "market_price"
    )
    assert market_status["status"] == "missing"


def test_industry_analysis_packet_uses_valuation_and_filing_context(monkeypatch):
    conn = _conn()
    monkeypatch.setattr("src.stage_04_pipeline.evidence_packets.get_connection", lambda: conn)
    monkeypatch.setattr(
        "src.stage_04_pipeline.evidence_packets.build_valuation_inputs",
        lambda ticker: SimpleNamespace(
            company_name="International Business Machines",
            sector="Technology",
            industry="IT Services",
            as_of_date="2026-05-15",
            drivers=SimpleNamespace(
                revenue_growth_near=0.07,
                revenue_growth_mid=0.05,
                ebit_margin_target=0.18,
                terminal_growth=0.025,
            ),
        ),
    )
    monkeypatch.setattr(
        "src.stage_04_pipeline.evidence_packets.get_agent_filing_context",
        lambda ticker, **kwargs: SimpleNamespace(
            sources=[
                {
                    "accession_no": "industry-10k",
                    "form_type": "10-K",
                    "doc_name": "ibm-10k.htm",
                    "filing_date": "2026-02-01",
                }
            ],
            selected_chunks=[
                SimpleNamespace(
                    accession_no="industry-10k",
                    chunk_index=3,
                    text="Hybrid cloud and AI services remain key industry demand drivers.",
                    section_key="business",
                    filing_date="2026-02-01",
                    score=0.88,
                )
            ],
        ),
    )

    packet = build_evidence_packet("ibm", "industry_analysis")

    assert packet.packet_kind == EvidencePacketKind.industry_analysis
    assert packet.run_metadata["source_quality"] == "real"
    fact_names = {fact.fact_name for fact in packet.facts}
    assert {"company_name", "sector", "industry", "revenue_growth_near", "revenue_growth_mid"} <= fact_names
    assert packet.snippets[0].source_ref_id == "industry-filing:industry-10k"


def test_comps_analysis_packet_uses_dashboard_payload(monkeypatch):
    conn = _conn()
    monkeypatch.setattr("src.stage_04_pipeline.evidence_packets.get_connection", lambda: conn)
    monkeypatch.setattr(
        "src.stage_04_pipeline.evidence_packets.build_comps_dashboard_view",
        lambda ticker: {
            "available": True,
            "peer_counts": {"raw": 12, "clean": 9},
            "primary_metric": "tev_ebitda_ltm",
            "target_vs_peers": {"peer_medians": {"tev_ebitda_ltm": 11.5, "pe_ltm": 18.2}},
            "source_lineage": {"as_of_date": "2026-05-10", "source_file": "ciq.xlsx"},
        },
    )

    packet = build_evidence_packet("ibm", "comps_analysis")

    assert packet.packet_kind == EvidencePacketKind.comps_analysis
    assert packet.run_metadata["source_quality"] == "real"
    assert packet.source_refs[0].source_ref_id == "comps:dashboard"
    fact_names = {fact.fact_name for fact in packet.facts}
    assert {"peer_count_raw", "peer_count_clean", "primary_metric", "tev_ebitda_ltm", "pe_ltm"} <= fact_names


def test_comps_analysis_uses_model_exit_metric_family_for_spread(monkeypatch):
    conn = _conn()
    monkeypatch.setattr("src.stage_04_pipeline.evidence_packets.get_connection", lambda: conn)
    views = {
        "XOM": {
            "available": True,
            "peer_counts": {"raw": 8, "clean": 7},
            "primary_metric": "tev_ebitda_ltm",
            "target_vs_peers": {"peer_medians": {"tev_ebit_fwd": 12.5}},
        },
        "CVX": {
            "available": True,
            "peer_counts": {"raw": 8, "clean": 7},
            "primary_metric": "tev_ebitda_ltm",
            "target_vs_peers": {"peer_medians": {"tev_ebitda_fwd": 12.5}},
        },
    }
    monkeypatch.setattr(
        "src.stage_04_pipeline.evidence_packets.build_comps_dashboard_view",
        lambda ticker: views[ticker],
    )
    monkeypatch.setattr(
        "src.stage_04_pipeline.evidence_packets.build_valuation_inputs",
        lambda ticker: SimpleNamespace(
            as_of_date="2026-05-15",
            drivers=SimpleNamespace(exit_multiple=10.0, exit_metric="ev_ebit"),
        ),
    )

    packet = build_evidence_packet("XOM", "comps_analysis")
    facts_by_name = {fact.fact_name: fact for fact in packet.facts}
    assert facts_by_name["model_assumption_exit_metric"].value == "ev_ebit"
    assert facts_by_name["model_exit_multiple_minus_peer_median_tev_ebit_fwd"].value == -2.5
    assert "model_exit_multiple_minus_peer_median_tev_ebitda_ltm" not in facts_by_name

    packet_without_like_for_like_median = build_evidence_packet("CVX", "comps_analysis")
    assert not any(
        fact.fact_name.startswith("model_exit_multiple_minus_peer_median_")
        for fact in packet_without_like_for_like_median.facts
    )

    guidance = " ".join(
        evidence_packets.get_agentic_handoff_profile("comps_analysis").prompt_guidance
    )
    assert "model_assumption_exit_metric" in guidance
    assert "tev_ebit_* for ev_ebit" in guidance
    assert "never against pe_* facts" in guidance


def test_risk_review_packet_uses_valuation_market_and_filing_context(monkeypatch):
    conn = _conn()
    monkeypatch.setattr("src.stage_04_pipeline.evidence_packets.get_connection", lambda: conn)
    monkeypatch.setattr(
        "src.stage_04_pipeline.evidence_packets.build_valuation_inputs",
        lambda ticker: SimpleNamespace(
            as_of_date="2026-05-15",
            drivers=SimpleNamespace(
                wacc=0.09,
                net_debt=1_200.0,
                revenue_growth_near=0.07,
                ebit_margin_target=0.18,
            ),
        ),
    )
    monkeypatch.setattr(
        "src.stage_04_pipeline.evidence_packets.get_market_data",
        lambda ticker, use_cache=True: {"beta": 1.15, "short_ratio": 2.2, "current_price": 125.0},
    )
    monkeypatch.setattr(
        "src.stage_04_pipeline.evidence_packets.get_agent_filing_context",
        lambda ticker, **kwargs: SimpleNamespace(
            sources=[
                {
                    "accession_no": "risk-10k",
                    "form_type": "10-K",
                    "doc_name": "ibm-10k.htm",
                    "filing_date": "2026-02-01",
                }
            ],
            selected_chunks=[
                SimpleNamespace(
                    accession_no="risk-10k",
                    chunk_index=7,
                    text="Execution risk remains tied to transformation and client spending cycles.",
                    section_key="risk_factors",
                    filing_date="2026-02-01",
                    score=0.9,
                )
            ],
        ),
    )

    packet = build_evidence_packet("ibm", "risk_review")

    assert packet.packet_kind == EvidencePacketKind.risk_review
    assert packet.run_metadata["source_quality"] == "real"
    fact_names = {fact.fact_name for fact in packet.facts}
    assert {"wacc", "net_debt", "beta", "short_ratio"} <= fact_names
    assert packet.snippets[0].source_ref_id == "risk-filing:risk-10k"


def test_analyst_prep_synthesis_packet_uses_prep_pack_payload(monkeypatch):
    conn = _conn()
    monkeypatch.setattr("src.stage_04_pipeline.evidence_packets.get_connection", lambda: conn)
    monkeypatch.setattr(
        "src.stage_04_pipeline.analyst_prep_pack.build_analyst_prep_payload",
        lambda ticker: {
            "ticker": ticker,
            "source_quality": "real",
            "thesis_cards": [
                {
                    "card_id": "IBM:valuation_setup",
                    "title": "Valuation Setup",
                    "claim": "Base DCF IV is above current price.",
                    "business_evidence_summary": "Deterministic DCF bridge provides the starting valuation gap.",
                    "model_implication": "Review revenue growth and WACC before trusting the spread.",
                    "linked_assumption_fields": ["revenue_growth_near", "wacc"],
                    "evidence_anchor_ids": ["deterministic:dcf:base_iv"],
                    "what_would_change_mind": "A stale CIQ refresh or rejected PM Queue item would invalidate the spread.",
                }
            ],
            "driver_cards": [
                {
                    "assumption_name": "wacc",
                    "current_value": 0.09,
                    "proposed_or_effective_value": 0.095,
                    "pm_review_status": "review_required",
                    "source": "wacc_peer_beta",
                    "rationale": "Current deterministic model source: wacc_peer_beta.",
                }
            ],
            "missing_data": [
                {
                    "flag_id": "segment_data_missing",
                    "label": "Segment evidence missing",
                    "severity": "medium",
                    "reason": "No deterministic segment rows were found.",
                    "suggested_check": "Refresh CIQ segment tabs.",
                }
            ],
            "evidence_packet_ids": [7],
        },
    )

    packet = build_evidence_packet("ibm", "analyst_prep_synthesis")

    assert packet.packet_kind == EvidencePacketKind.analyst_prep_synthesis
    assert packet.run_metadata["source_quality"] == "real"
    assert packet.run_metadata["evidence_packet_ids"] == [7]
    assert packet.source_refs[0].source_ref_id == "analyst-prep:ibm"
    fact_names = {fact.fact_name for fact in packet.facts}
    assert {"analyst_prep_thesis_card_count", "analyst_prep_driver_wacc"} <= fact_names
    assert packet.snippets[0].snippet_id == "snippet:analyst_prep:thesis:1"
    assert packet.snippets[1].snippet_id == "snippet:analyst_prep:missing:1"


def test_industry_and_risk_packets_require_text_context_for_real_quality(monkeypatch):
    conn = _conn()
    monkeypatch.setattr("src.stage_04_pipeline.evidence_packets.get_connection", lambda: conn)
    monkeypatch.setattr(
        "src.stage_04_pipeline.evidence_packets.build_valuation_inputs",
        lambda ticker: SimpleNamespace(
            company_name="International Business Machines",
            sector="Technology",
            industry="IT Services",
            as_of_date="2026-05-15",
            drivers=SimpleNamespace(
                revenue_growth_near=0.07,
                revenue_growth_mid=0.05,
                ebit_margin_target=0.18,
                terminal_growth=0.025,
                wacc=0.09,
                net_debt=1_200.0,
            ),
        ),
    )
    monkeypatch.setattr(
        "src.stage_04_pipeline.evidence_packets.get_market_data",
        lambda ticker, use_cache=True: {"beta": 1.15, "short_ratio": 2.2, "current_price": 125.0},
    )
    monkeypatch.setattr(
        "src.stage_04_pipeline.evidence_packets.get_agent_filing_context",
        lambda ticker, **kwargs: SimpleNamespace(sources=[], selected_chunks=[]),
    )

    industry_packet = build_evidence_packet("ibm", "industry_analysis")
    risk_packet = build_evidence_packet("ibm", "risk_review")

    assert industry_packet.run_metadata["source_quality"] == "partial"
    assert industry_packet.run_metadata["reason"] == "missing_industry_context"
    assert industry_packet.snippets == []

    assert risk_packet.run_metadata["source_quality"] == "partial"
    assert risk_packet.run_metadata["reason"] == "missing_risk_context"
    assert risk_packet.snippets == []


def test_missing_profile_sources_mark_packets_partial_or_placeholder(monkeypatch):
    conn = _conn()
    monkeypatch.setattr("src.stage_04_pipeline.evidence_packets.get_connection", lambda: conn)
    monkeypatch.setattr(
        "src.stage_04_pipeline.evidence_packets.get_8k_texts",
        lambda ticker, limit=3, max_chars_each=4000: [],
    )
    monkeypatch.setattr(
        "src.stage_04_pipeline.evidence_packets.build_valuation_inputs",
        lambda ticker: None,
    )
    monkeypatch.setattr(
        "src.stage_04_pipeline.evidence_packets.get_market_data",
        lambda ticker, use_cache=True: {"current_price": 125.0},
    )
    monkeypatch.setattr(
        "src.stage_04_pipeline.evidence_packets.build_comps_dashboard_view",
        lambda ticker: {"available": False},
    )

    earnings_packet = build_evidence_packet("ibm", "earnings_update")
    comps_packet = build_evidence_packet("ibm", "comps_analysis")

    assert earnings_packet.run_metadata["source_quality"] == "partial"
    assert earnings_packet.run_metadata["reason"] == "missing_recent_earnings_context"
    assert earnings_packet.snippets == []
    assert earnings_packet.facts[0].fact_name == "current_price"

    assert comps_packet.run_metadata["source_quality"] == "placeholder"
    assert comps_packet.run_metadata["reason"] == "missing_real_comps_inputs"
    assert comps_packet.facts == []
