from __future__ import annotations

from src.stage_04_pipeline.evidence.assembly import PacketMaterial, assemble_packet


def test_assemble_packet_validates_material_without_acquiring_sources() -> None:
    source_ref = {
        "source_ref_id": "sec_10k_2026",
        "source_kind": "sec_filing",
        "source_label": "MSFT FY2026 10-K",
        "source_locator": "edgar:0000789019-26-000001",
    }
    revenue_fact = {
        "fact_id": "fact_rev_1",
        "fact_name": "revenue_series_annual",
        "value": [
            {"period": "FY2022", "amount": 198270000000.0, "unit": "USD"},
        ],
    }
    business_snippet = {
        "snippet_id": "snip_1",
        "source_ref_id": "sec_10k_2026",
        "text": "Microsoft operates in three segments.",
    }
    material = PacketMaterial(
        source_refs=(source_ref,),
        facts=(revenue_fact,),
        snippets=(business_snippet,),
        run_metadata={"source_quality": "real", "evidence_sufficiency": "sufficient"},
    )

    packet = assemble_packet(
        ticker="msft",
        profile_name="company_analysis",
        material=material,
    )

    assert packet.ticker == "MSFT"
    assert packet.facts[0].fact_name == "revenue_series_annual"
    assert packet.run_metadata["evidence_sufficiency"] == "sufficient"
    assert packet.run_metadata["source_quality"] == "real"
