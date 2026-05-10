from __future__ import annotations

from pathlib import Path


CONTRACT_DOC_PATH = Path("docs/design-docs/ticker-dossier-contract.md")
EPIC_DOC_PATH = Path("docs/plans/future/2026-04-02-epic-canonical-ticker-dossier-and-export-integrity.md")

CURRENT_EXPORT_COMMON_ROOTS = {
    "$schema_version",
    "generated_at",
    "ticker",
    "company_name",
    "sector",
    "market",
    "assumptions",
    "wacc",
    "valuation",
    "scenarios",
    "sensitivity",
    "terminal",
    "health_flags",
    "forecast_bridge",
    "source_lineage",
    "ciq_lineage",
    "comps_detail",
    "comps_analysis",
}


def test_ticker_dossier_contract_doc_and_plan_link_are_pinned():
    contract_doc = CONTRACT_DOC_PATH.read_text(encoding="utf-8")
    epic_doc = EPIC_DOC_PATH.read_text(encoding="utf-8")

    assert CONTRACT_DOC_PATH.exists()
    assert contract_doc.startswith("# TickerDossier Contract")
    assert "drift-test reference" in contract_doc
    assert "Required Top-Level Envelope Fields" in contract_doc
    assert "Required Sections" in contract_doc
    assert "Current Runtime Compatibility Roots" in contract_doc
    assert "V1 Adapter Enrichment" in contract_doc
    assert "not a new data collection path" in contract_doc
    assert "[docs/design-docs/ticker-dossier-contract.md](../../design-docs/ticker-dossier-contract.md)" in epic_doc

    for root in CURRENT_EXPORT_COMMON_ROOTS:
        assert f"`{root}`" in contract_doc


def test_current_and_snapshot_ticker_payload_share_documented_common_roots(monkeypatch):
    from src.stage_04_pipeline import export_service

    monkeypatch.setattr(export_service, "_coerce_ticker", lambda ticker: ticker.upper())
    monkeypatch.setattr(export_service, "_now", lambda: "2026-04-30T00:00:00+00:00")

    monkeypatch.setattr(
        export_service,
        "build_override_workbench",
        lambda ticker: {
            "company_name": "International Business Machines",
            "sector": "Technology",
            "current_price": 260.0,
            "fields": [],
        },
    )
    monkeypatch.setattr(
        export_service,
        "build_dcf_audit_view",
        lambda ticker: {
            "scenario_summary": [],
            "ev_bridge": {"intrinsic_value_per_share": 202.0},
            "terminal_bridge": {"terminal_growth": 0.03},
            "health_flags": {"ok": True},
            "forecast_bridge": [],
        },
    )
    monkeypatch.setattr(
        export_service,
        "build_comps_dashboard_view",
        lambda ticker: {
            "target_vs_peers": {"target": {}, "peer_medians": {}, "deltas": {}},
            "peer_counts": {"raw": 0, "clean": 0},
            "peers": [],
            "source_lineage": {"source_file": "IBM_comps.xlsx", "as_of_date": "2026-03-01"},
        },
    )
    monkeypatch.setattr(
        export_service,
        "build_wacc_workbench",
        lambda ticker, apply_overrides=True: {
            "effective_preview": {
                "wacc": 0.1,
                "cost_of_equity": 0.12,
                "equity_weight": 0.7,
                "debt_weight": 0.3,
            },
            "current_selection": {"selected_method": "blend"},
        },
    )
    monkeypatch.setattr(
        export_service,
        "build_research_board_view",
        lambda ticker: {
            "company_name": "International Business Machines",
            "analyst_target": 275.0,
            "tracker": {"pm_action": "Hold"},
            "publishable_memo_preview": "Research preview",
        },
    )
    monkeypatch.setattr(
        export_service,
        "list_report_snapshots",
        lambda ticker, limit=1: [{"id": 42}],
    )
    monkeypatch.setattr(
        export_service,
        "load_report_snapshot",
        lambda snapshot_id: {
            "company_name": "International Business Machines",
            "sector": "Technology",
            "current_price": 255.0,
            "action": "Hold",
            "base_iv": 202.0,
            "memo": {"valuation": {"bear": 190.0, "base": 202.0, "bull": 216.0}, "one_liner": "Snapshot memo"},
            "dashboard_snapshot": {
                "dcf_audit": {
                    "scenario_summary": [],
                    "terminal_bridge": {"terminal_growth": 0.03},
                    "health_flags": {"ok": True},
                    "forecast_bridge": [],
                },
                "comps_view": {
                    "target_vs_peers": {"target": {}, "peer_medians": {}, "deltas": {}},
                    "peer_counts": {"raw": 0, "clean": 0},
                    "peers": [],
                    "source_lineage": {"source_file": "IBM_comps_snapshot.xlsx", "as_of_date": "2026-02-28"},
                },
            },
        },
    )

    current_payload = export_service._build_current_ticker_payload("ibm")
    snapshot_payload, snapshot_id = export_service._build_snapshot_ticker_payload("ibm")

    assert snapshot_id == 42
    assert CURRENT_EXPORT_COMMON_ROOTS <= set(current_payload)
    assert CURRENT_EXPORT_COMMON_ROOTS <= set(snapshot_payload)
    assert current_payload["ticker_dossier"]["contract_name"] == "TickerDossier"
    assert snapshot_payload["ticker_dossier"]["contract_name"] == "TickerDossier"
    assert set(current_payload["ticker_dossier"]) == set(snapshot_payload["ticker_dossier"])
    assert current_payload["ticker_dossier"]["export_metadata"]["source_mode"] == "loaded_backend_state"
    assert snapshot_payload["ticker_dossier"]["export_metadata"]["source_mode"] == "latest_snapshot"
    assert "research" in current_payload
    assert "snapshot" not in current_payload
    assert "snapshot" in snapshot_payload
    assert "research" not in snapshot_payload
