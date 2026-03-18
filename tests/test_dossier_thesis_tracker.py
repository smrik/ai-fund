from __future__ import annotations

import sqlite3
from pathlib import Path

from db.schema import create_tables
from src.stage_02_valuation.templates.ic_memo import ICMemo, ValuationRange


def _temp_conn_factory(db_path: Path):
    def _factory():
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        create_tables(conn)
        return conn

    return _factory


def _build_memo(
    *,
    ticker: str = "IBM",
    action: str = "WATCH",
    base_iv: float = 110.0,
    current_price: float = 100.0,
    key_catalysts: list[str] | None = None,
    thesis_pillars: list[dict] | None = None,
    structured_catalysts: list[dict] | None = None,
):
    return ICMemo(
        ticker=ticker,
        company_name="IBM",
        sector="Technology",
        action=action,
        conviction="medium",
        one_liner="Stub memo",
        key_catalysts=key_catalysts or [],
        thesis_pillars=thesis_pillars or [],
        structured_catalysts=structured_catalysts or [],
        valuation=ValuationRange(bear=90.0, base=base_iv, bull=130.0, current_price=current_price),
    )


def test_build_thesis_diff_view_uses_archive_and_current_tracker_state(monkeypatch, tmp_path):
    from src.stage_04_pipeline import dossier_index, dossier_view, report_archive

    db_path = tmp_path / "tracker.db"
    factory = _temp_conn_factory(db_path)
    monkeypatch.setattr(dossier_index, "get_connection", factory)
    monkeypatch.setattr(dossier_view, "get_connection", factory)
    monkeypatch.setattr(report_archive, "get_connection", factory)
    timestamps = iter(["2026-03-18T20:00:00+00:00", "2026-03-18T21:00:00+00:00"])
    monkeypatch.setattr(report_archive, "_now", lambda: next(timestamps))

    report_archive.save_report_snapshot(
        "IBM",
        _build_memo(action="WATCH", key_catalysts=["Margin recovery"]),
        dcf_audit=None,
        comps_view=None,
        market_intel_view=None,
        filings_browser_view=None,
        run_trace=[],
    )
    report_archive.save_report_snapshot(
        "IBM",
        _build_memo(
            action="BUY",
            base_iv=125.0,
            current_price=103.0,
            key_catalysts=["Margin recovery", "Mainframe cycle"],
            thesis_pillars=[
                {
                    "pillar_id": "pillar-1",
                    "title": "Software mix shift",
                    "description": "Software mix lifts margins.",
                    "falsifier": "Mix stalls",
                    "evidence_basis": "Segment disclosures",
                }
            ],
            structured_catalysts=[
                {
                    "catalyst_key": "cat-1",
                    "title": "Mainframe cycle",
                    "description": "Refresh helps mix",
                    "expected_window": "12m",
                    "importance": "high",
                }
            ],
        ),
        dcf_audit=None,
        comps_view=None,
        market_intel_view=None,
        filings_browser_view=None,
        run_trace=[],
    )

    dossier_index.upsert_tracker_state(
        {
            "ticker": "IBM",
            "overall_status": "monitor",
            "pm_action": "BUY",
            "pm_conviction": "medium",
            "summary_note": "Watching consulting execution.",
            "pillar_states_json": '{"pillar-1": {"status": "monitor"}}',
            "open_questions_json": '["Can consulting stabilize?"]',
            "last_reviewed_at": "2026-03-18T21:30:00Z",
            "latest_snapshot_id": 2,
            "metadata_json": "{}",
        }
    )
    dossier_index.upsert_tracked_catalyst(
        {
            "ticker": "IBM",
            "catalyst_key": "cat-1",
            "title": "Mainframe cycle",
            "description": "Refresh helps mix",
            "priority": "high",
            "status": "watching",
            "expected_date": None,
            "expected_window_start": None,
            "expected_window_end": None,
            "status_reason": "Need evidence from next quarter.",
            "source_origin": "agent",
            "source_snapshot_id": 2,
            "evidence_json": "{}",
        }
    )

    thesis_view = dossier_view.build_thesis_diff_view("IBM")

    assert thesis_view["available"] is True
    assert thesis_view["latest_snapshot"]["action"] == "BUY"
    assert thesis_view["prior_snapshot"]["action"] == "WATCH"
    assert thesis_view["snapshot_diff"]["action_changed"] is True
    assert thesis_view["snapshot_diff"]["added_catalysts"] == ["Mainframe cycle"]
    assert thesis_view["current_tracker_state"]["overall_status"] == "monitor"
    assert thesis_view["catalysts"][0]["status"] == "watching"
