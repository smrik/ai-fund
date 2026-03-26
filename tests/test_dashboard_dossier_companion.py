from __future__ import annotations

import json
from types import SimpleNamespace

from dashboard import dossier_companion


def test_build_note_block_row_uses_creation_timestamp_and_item_context(monkeypatch):
    monkeypatch.setattr(dossier_companion, "_current_note_block_ts", lambda: "2026-03-26T10:11:12+00:00")

    row = dossier_companion._build_note_block_row(
        memo=SimpleNamespace(ticker="IBM"),
        block_type="evidence",
        title="Lease note flagged",
        body="The filing note shows lease liabilities still elevated.",
        page_context={
            "page": "Audit",
            "subpage": "Filings & Evidence",
            "item": "10-K | 2025-12-31 | 0001 · Notes",
        },
        linked_sources=["S-001"],
        linked_artifacts=["filing_pdf"],
        pin_to_report=True,
        linked_snapshot_id=42,
    )

    assert row["block_ts"] == "2026-03-26T10:11:12+00:00"
    assert row["linked_snapshot_id"] == 42
    assert row["pinned_to_report"] == 1
    assert json.loads(row["linked_sources_json"]) == ["S-001"]
    assert json.loads(row["linked_artifacts_json"]) == ["filing_pdf"]
    assert json.loads(row["source_context_json"]) == {
        "item": "10-K | 2025-12-31 | 0001 · Notes",
        "page": "Audit",
        "subpage": "Filings & Evidence",
    }


def test_build_note_block_row_falls_back_to_subpage_for_missing_item(monkeypatch):
    monkeypatch.setattr(dossier_companion, "_current_note_block_ts", lambda: "2026-03-26T10:11:12+00:00")

    row = dossier_companion._build_note_block_row(
        memo=SimpleNamespace(ticker="IBM"),
        block_type="thesis",
        title="Core thesis",
        body="Base case still relies on software mix.",
        page_context={"page": "Research", "subpage": "Tracker"},
        linked_sources=[],
        linked_artifacts=[],
        pin_to_report=False,
        linked_snapshot_id=None,
    )

    assert json.loads(row["source_context_json"]) == {
        "item": "Tracker",
        "page": "Research",
        "subpage": "Tracker",
    }
