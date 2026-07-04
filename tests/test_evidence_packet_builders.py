import sqlite3
from types import SimpleNamespace

from db.loader import load_evidence_packet
from db.schema import create_tables
from src.contracts.evidence_packet import EvidencePacketKind
from src.stage_04_pipeline.evidence_packets import build_evidence_packet


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_tables(conn)
    return conn


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
        ),
    )

    packet = build_evidence_packet("ibm", "company_analysis")

    assert packet.packet_kind == EvidencePacketKind.company_analysis
    assert packet.run_metadata["source_quality"] == "real"
    assert packet.source_refs[0].source_ref_id == "filing:0001"
    assert packet.source_refs[1].source_ref_id == "sec-metrics:10-K:2026-02-01"
    assert packet.snippets[0].source_ref_id == "filing:0001"
    fact_names = {fact.fact_name for fact in packet.facts}
    assert {"filing_source_count", "filing_selected_chunk_count", "revenue_cagr_3y"} <= fact_names

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
    assert packet.source_refs[0].source_ref_id == "8k:8k-1"
    assert packet.source_refs[1].source_ref_id == "market:latest"
    assert packet.snippets[0].text.startswith("Management raised full-year guidance")
    fact_names = {fact.fact_name for fact in packet.facts}
    assert {"current_price", "analyst_target_mean", "analyst_recommendation", "number_of_analysts"} <= fact_names


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
