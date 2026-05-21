import sqlite3

from db.loader import load_evidence_packet
from db.schema import create_tables
from src.contracts.evidence_packet import EvidencePacketKind
from src.stage_04_pipeline.evidence_packets import build_evidence_packet


def test_build_evidence_packet_uses_profile_builder_and_persists(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_tables(conn)

    monkeypatch.setattr("src.stage_04_pipeline.evidence_packets.get_connection", lambda: conn)

    def _stub_collect_inputs(ticker: str, profile_name: str) -> dict:
        return {
            "source_refs": [
                {
                    "source_ref_id": f"src:{profile_name}:1",
                    "source_kind": "stub",
                    "source_label": f"{profile_name} source",
                    "source_locator": f"stub://{ticker}/{profile_name}",
                }
            ],
            "facts": [{"fact_id": f"fact:{profile_name}:1", "fact_name": "stub_fact", "value": 1}],
            "snippets": [
                {
                    "snippet_id": f"snippet:{profile_name}:1",
                    "source_ref_id": f"src:{profile_name}:1",
                    "text": f"{profile_name} evidence snippet",
                }
            ],
            "run_metadata": {"stubbed": True},
        }

    monkeypatch.setattr("src.stage_04_pipeline.evidence_packets._collect_profile_inputs", _stub_collect_inputs)

    cases = [
        ("earnings_update", EvidencePacketKind.earnings_update),
        ("company_analysis", EvidencePacketKind.company_analysis),
        ("industry_analysis", EvidencePacketKind.industry_analysis),
        ("comps_analysis", EvidencePacketKind.comps_analysis),
        ("valuation_review", EvidencePacketKind.valuation_review),
    ]

    for profile_name, packet_kind in cases:
        packet = build_evidence_packet("ibm", profile_name)

        assert packet.packet_id is not None
        assert packet.ticker == "IBM"
        assert packet.profile_name == profile_name
        assert packet.packet_kind == packet_kind
        assert packet.source_refs[0].source_ref_id == f"src:{profile_name}:1"
        assert packet.facts[0].fact_id == f"fact:{profile_name}:1"
        assert packet.run_metadata["stubbed"] is True

        persisted = load_evidence_packet(conn, packet.packet_id)
        assert persisted is not None
        assert persisted["packet_kind"] == packet_kind.value
