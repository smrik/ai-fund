from __future__ import annotations

import pytest

from src.contracts.analysis_snapshot import AnalysisSnapshot


def _snapshot(**changes: object) -> AnalysisSnapshot:
    payload: dict[str, object] = {
        "ticker": "test",
        "as_of_date": "2026-07-26",
        "identity": {"cik": "0000000001", "currency": "USD"},
        "statements": {
            "facts": [
                {
                    "fact_id": "revenue:2025",
                    "value": 1000.0,
                    "accession": "0000000001-26-000001",
                }
            ]
        },
        "statement_reconciliation": {"status": "reconciled"},
        "claim_ledger": {"status": "reconciled", "net_debt": 100.0},
        "market_inputs": {"price": 10.0},
        "wacc_inputs": {"wacc": 0.09, "risk_free_rate": 0.04},
        "comps_inputs": {"peers": ["AAA", "BBB", "CCC"]},
        "approved_treatments": [],
        "evidence": {"fact:revenue": {"value": 1000.0}},
        "upstream_context": {"business": {"summary": "Test business."}},
        "source_fingerprints": {"xbrl": "xbrl-hash", "ciq": "ciq-hash"},
        "component_versions": {
            "statement_resolver": "v1",
            "evidence_compiler": "v1",
        },
        "captured_at": "2026-07-26T10:00:00Z",
    }
    payload.update(changes)
    return AnalysisSnapshot.model_validate(payload)


def test_snapshot_hash_ignores_capture_time_but_changes_with_semantic_evidence() -> None:
    first = _snapshot()
    recaptured = _snapshot(captured_at="2026-07-26T11:00:00Z")
    changed_fact = _snapshot(
        statements={
            "facts": [
                {
                    "fact_id": "revenue:2025",
                    "value": 1001.0,
                    "accession": "0000000001-26-000001",
                }
            ]
        }
    )

    assert first.ticker == "TEST"
    assert first.snapshot_hash == recaptured.snapshot_hash
    assert first.snapshot_hash != changed_fact.snapshot_hash


def test_snapshot_nested_evidence_is_deeply_immutable_and_hash_stable() -> None:
    snapshot = _snapshot()
    original_hash = snapshot.snapshot_hash

    with pytest.raises(TypeError):
        snapshot.statements["facts"][0]["value"] = 9999.0
    with pytest.raises(TypeError):
        snapshot.source_fingerprints["xbrl"] = "forged"

    assert snapshot.snapshot_hash == original_hash
    assert snapshot.statements["facts"][0]["value"] == 1000.0

    copied = snapshot.model_copy(
        update={"evidence": {"fact:new": {"values": [1, 2, 3]}}}
    )
    with pytest.raises(TypeError):
        copied.evidence["fact:new"]["values"].append(4)
