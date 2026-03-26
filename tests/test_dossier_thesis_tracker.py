from __future__ import annotations

from contextlib import contextmanager
import json
import sqlite3

from db.schema import create_tables
from src.stage_02_valuation.templates.ic_memo import ICMemo, ValuationRange


@contextmanager
def _db_factory():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_tables(conn)

    def _factory():
        return conn

    try:
        yield _factory
    finally:
        conn.close()


def _build_memo(
    *,
    ticker: str = "IBM",
    action: str = "WATCH",
    conviction: str = "medium",
    base_iv: float = 110.0,
    current_price: float = 100.0,
    key_catalysts: list[str] | None = None,
    key_risks: list[str] | None = None,
    open_questions: list[str] | None = None,
    thesis_pillars: list[dict] | None = None,
    structured_catalysts: list[dict] | None = None,
):
    return ICMemo(
        ticker=ticker,
        company_name="IBM",
        sector="Technology",
        action=action,
        conviction=conviction,
        one_liner="Stub memo",
        key_catalysts=key_catalysts or [],
        key_risks=key_risks or [],
        open_questions=open_questions or [],
        thesis_pillars=thesis_pillars or [],
        structured_catalysts=structured_catalysts or [],
        valuation=ValuationRange(bear=90.0, base=base_iv, bull=130.0, current_price=current_price),
    )


def test_build_thesis_tracker_view_returns_pm_cockpit_contract(monkeypatch):
    from src.stage_04_pipeline import dossier_index, dossier_view, report_archive

    with _db_factory() as factory:
        monkeypatch.setattr(dossier_index, "get_connection", factory)
        monkeypatch.setattr(dossier_view, "get_connection", factory)
        monkeypatch.setattr(report_archive, "get_connection", factory)
        timestamps = iter(["2026-03-18T20:00:00+00:00", "2026-03-18T21:00:00+00:00"])
        monkeypatch.setattr(report_archive, "_now", lambda: next(timestamps))

        report_archive.save_report_snapshot(
            "IBM",
            _build_memo(
                action="WATCH",
                conviction="low",
                key_catalysts=["Margin recovery"],
                key_risks=["Execution slippage"],
                open_questions=["Can consulting stabilize?"],
            ),
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
                conviction="high",
                base_iv=125.0,
                current_price=103.0,
                key_catalysts=["Margin recovery", "Mainframe cycle"],
                key_risks=["Execution slippage", "AI monetization timing"],
                open_questions=["Can consulting stabilize?", "Can software mix hold?"],
                thesis_pillars=[
                    {
                        "pillar_id": "pillar-1",
                        "title": "Software mix shift",
                        "description": "Software mix lifts margins.",
                        "falsifier": "Mix stalls",
                        "evidence_basis": "Segment disclosures",
                    },
                    {
                        "pillar_id": "pillar-2",
                        "title": "Mainframe cycle",
                        "description": "Refresh helps mix.",
                        "falsifier": "Refresh stalls",
                        "evidence_basis": "Product cycle timing",
                    },
                ],
                structured_catalysts=[
                    {
                        "catalyst_key": "cat-1",
                        "title": "Mainframe cycle",
                        "description": "Refresh helps mix",
                        "expected_window": "12m",
                        "importance": "high",
                    },
                    {
                        "catalyst_key": "cat-2",
                        "title": "Consulting stabilization",
                        "description": "Services mix stops deteriorating",
                        "expected_window": "next quarter",
                        "importance": "medium",
                    },
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
                "pm_conviction": "high",
                "summary_note": "Watching consulting execution.",
                "pillar_states_json": json.dumps(
                    {
                        "pillar-1": {"status": "monitor", "note": "Margins improving slowly."},
                        "pillar-2": {"status": "intact", "note": "Cycle still supportive."},
                    },
                    sort_keys=True,
                ),
                "open_questions_json": json.dumps(["Can consulting stabilize?"], sort_keys=True),
                "last_reviewed_at": "2026-03-18T21:30:00Z",
                "latest_snapshot_id": 2,
                "metadata_json": json.dumps({"source": "pm"}, sort_keys=True),
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
                "expected_date": "2026-06-30",
                "expected_window_start": "2026-05-01",
                "expected_window_end": "2026-07-31",
                "status_reason": "Need evidence from next quarter.",
                "source_origin": "agent",
                "source_snapshot_id": 2,
                "evidence_json": json.dumps({"source": "archive"}, sort_keys=True),
            }
        )
        dossier_index.upsert_tracked_catalyst(
            {
                "ticker": "IBM",
                "catalyst_key": "cat-2",
                "title": "Consulting stabilization",
                "description": "Services mix stops deteriorating",
                "priority": "medium",
                "status": "open",
                "expected_date": None,
                "expected_window_start": None,
                "expected_window_end": None,
                "status_reason": "",
                "source_origin": "agent",
                "source_snapshot_id": 2,
                "evidence_json": json.dumps({"source": "archive"}, sort_keys=True),
            }
        )
        dossier_index.upsert_tracked_catalyst(
            {
                "ticker": "IBM",
                "catalyst_key": "cat-3",
                "title": "Legacy issue resolved",
                "description": "A prior concern is now closed.",
                "priority": "low",
                "status": "resolved",
                "expected_date": None,
                "expected_window_start": None,
                "expected_window_end": None,
                "status_reason": "Resolved in the latest quarter.",
                "source_origin": "pm",
                "source_snapshot_id": 2,
                "evidence_json": json.dumps({"source": "pm"}, sort_keys=True),
            }
        )
        dossier_index.insert_decision_log_entry(
            {
                "ticker": "IBM",
                "decision_ts": "2026-03-18T22:15:00+00:00",
                "decision_title": "Raise to Buy",
                "action": "BUY",
                "conviction": "high",
                "beliefs_text": "Margin mix is improving.",
                "evidence_text": "Latest quarter supported the shift.",
                "assumptions_text": "Execution holds.",
                "falsifiers_text": "If mix stalls, thesis weakens.",
                "review_due_date": "2026-04-30",
                "snapshot_id": 2,
                "model_checkpoint_id": None,
                "private_notes_text": "Internal only.",
                "created_by": "pm",
            }
        )
        dossier_index.insert_review_log_entry(
            {
                "ticker": "IBM",
                "review_ts": "2026-03-18T22:20:00+00:00",
                "review_title": "Q1 Review",
                "period_type": "quarterly",
                "expectations_vs_outcomes_text": "Outcomes mostly matched.",
                "factual_error_text": "",
                "interpretive_error_text": "Underweighted services pressure.",
                "behavioral_error_text": "",
                "thesis_status": "monitor",
                "model_status": "current",
                "action_taken_text": "Hold and monitor.",
                "linked_decision_id": None,
                "linked_snapshot_id": 2,
                "private_notes_text": "Internal only.",
                "created_by": "pm",
            }
        )
        dossier_index.insert_model_checkpoint(
            {
                "ticker": "IBM",
                "checkpoint_ts": "2026-03-18T22:10:00+00:00",
                "model_version": "v02",
                "artifact_key": "ibm-model-v02",
                "snapshot_id": 2,
                "valuation_json": json.dumps(
                    {
                        "base_iv": 125.0,
                        "bear_iv": 90.0,
                        "bull_iv": 140.0,
                        "current_price": 103.0,
                        "upside_pct": 0.213592233,
                    },
                    sort_keys=True,
                ),
                "drivers_summary_json": json.dumps({"wacc": 0.094, "margin": 0.225}, sort_keys=True),
                "change_reason": "Updated after latest quarter.",
                "thesis_version": "t02",
                "source_ids_json": json.dumps(["S-001", "S-002"], sort_keys=True),
                "created_by": "pm",
            }
        )

        thesis_view = dossier_view.build_thesis_tracker_view("IBM")

        assert thesis_view["available"] is True
        assert set(thesis_view).issuperset(
            {"available", "stance", "what_changed", "pillar_board", "catalyst_board", "continuity", "next_queue", "audit_flags"}
        )
        assert thesis_view["stance"]["pm_action"] == "BUY"
        assert thesis_view["stance"]["pm_conviction"] == "high"
        assert thesis_view["stance"]["overall_status"] == "monitor"
        assert thesis_view["stance"]["latest_archived_action"] == "BUY"
        assert thesis_view["stance"]["base_iv"] == 125.0
        assert thesis_view["stance"]["current_price"] == 103.0
        assert thesis_view["what_changed"]["action_delta"] == {"from": "WATCH", "to": "BUY"}
        assert thesis_view["what_changed"]["conviction_delta"] == {"from": "low", "to": "high"}
        assert thesis_view["what_changed"]["base_iv_delta"] == 15.0
        assert thesis_view["what_changed"]["catalysts_added"] == ["Mainframe cycle", "Consulting stabilization"]
        assert "Action changed from WATCH to BUY." in thesis_view["what_changed"]["summary_lines"]
        assert thesis_view["what_changed"]["risks_added"] == ["AI monetization timing"]
        assert thesis_view["what_changed"]["open_questions_added"] == ["Can software mix hold?"]
        assert thesis_view["pillar_board"][0]["pillar_id"] == "pillar-1"
        assert thesis_view["pillar_board"][0]["pm_status"] == "monitor"
        assert thesis_view["pillar_board"][0]["pm_note"] == "Margins improving slowly."
        assert [row["title"] for row in thesis_view["catalyst_board"]["urgent_open"]] == ["Consulting stabilization"]
        assert [row["title"] for row in thesis_view["catalyst_board"]["watching"]] == ["Mainframe cycle"]
        assert [row["title"] for row in thesis_view["catalyst_board"]["resolved"]] == ["Legacy issue resolved"]
        assert thesis_view["continuity"]["latest_decision"]["decision_title"] == "Raise to Buy"
        assert thesis_view["continuity"]["latest_review"]["review_title"] == "Q1 Review"
        assert thesis_view["continuity"]["latest_checkpoint"]["model_version"] == "v02"
        assert thesis_view["next_queue"]["open_questions"] == ["Can consulting stabilize?"]
        assert thesis_view["next_queue"]["open_question_count"] == 1
        assert thesis_view["next_queue"]["upcoming_catalyst_count"] == 2
        assert thesis_view["audit_flags"] == []


def test_build_thesis_tracker_view_handles_no_archive_history(monkeypatch):
    from src.stage_04_pipeline import dossier_index, dossier_view

    with _db_factory() as factory:
        monkeypatch.setattr(dossier_index, "get_connection", factory)
        monkeypatch.setattr(dossier_view, "get_connection", factory)

        thesis_view = dossier_view.build_thesis_tracker_view("IBM")

        assert thesis_view["available"] is False
        assert thesis_view["stance"] == {}
        assert thesis_view["what_changed"] == {}
        assert thesis_view["pillar_board"] == []
        assert thesis_view["catalyst_board"] == {"urgent_open": [], "watching": [], "resolved": []}
        assert thesis_view["continuity"] == {}
        assert thesis_view["next_queue"] == {}
        assert thesis_view["audit_flags"] == ["no_archived_snapshot"]


def test_build_thesis_diff_view_uses_tracker_view_legacy_shim(monkeypatch):
    from src.stage_04_pipeline import dossier_index, dossier_view, report_archive

    with _db_factory() as factory:
        monkeypatch.setattr(dossier_index, "get_connection", factory)
        monkeypatch.setattr(dossier_view, "get_connection", factory)
        monkeypatch.setattr(report_archive, "get_connection", factory)
        timestamps = iter(["2026-03-18T20:00:00+00:00", "2026-03-18T21:00:00+00:00"])
        monkeypatch.setattr(report_archive, "_now", lambda: next(timestamps))

        report_archive.save_report_snapshot(
            "IBM",
            _build_memo(action="WATCH", conviction="low", key_catalysts=["Margin recovery"]),
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
                conviction="high",
                base_iv=125.0,
                current_price=103.0,
                key_catalysts=["Margin recovery", "Mainframe cycle"],
                key_risks=["Execution slippage"],
                open_questions=["Can consulting stabilize?"],
            ),
            dcf_audit=None,
            comps_view=None,
            market_intel_view=None,
            filings_browser_view=None,
            run_trace=[],
        )

        monkeypatch.setattr(
            dossier_view,
            "build_thesis_tracker_view",
            lambda ticker: {
                "ticker": ticker,
                "available": True,
                "latest_snapshot": {"id": 2, "action": "BUY", "conviction": "high", "base_iv": 125.0},
                "prior_snapshot": {"id": 1, "action": "WATCH", "conviction": "low", "base_iv": 110.0},
                "stance": {
                    "pm_action": "BUY",
                    "pm_conviction": "high",
                    "overall_status": "monitor",
                    "last_reviewed_at": "2026-03-18T21:30:00Z",
                },
                "what_changed": {
                    "action_delta": {"from": "WATCH", "to": "BUY"},
                    "conviction_delta": {"from": "low", "to": "high"},
                    "base_iv_delta": 999.0,
                    "catalysts_added": ["Mainframe cycle"],
                    "catalysts_removed": [],
                    "risks_added": [],
                    "risks_removed": [],
                    "open_questions_added": [],
                    "open_questions_closed": [],
                },
                "pillar_board": [],
                "catalyst_board": {
                    "urgent_open": [{"catalyst_key": "cat-1", "title": "Mainframe cycle"}],
                    "watching": [],
                    "resolved": [],
                },
                "continuity": {},
                "next_queue": {},
                "audit_flags": ["legacy"],
            },
            raising=False,
        )

        thesis_view = dossier_view.build_thesis_diff_view("IBM")

        assert thesis_view["available"] is True
        assert thesis_view["latest_snapshot"]["base_iv"] == 125.0
        assert thesis_view["prior_snapshot"]["base_iv"] == 110.0
        assert thesis_view["snapshot_diff"]["action_changed"] is True
        assert thesis_view["snapshot_diff"]["conviction_changed"] is True
        assert thesis_view["snapshot_diff"]["base_iv_delta"] == 999.0
        assert thesis_view["snapshot_diff"]["added_catalysts"] == ["Mainframe cycle"]
        assert thesis_view["current_tracker_state"]["pm_action"] == "BUY"
        assert thesis_view["current_tracker_state"]["pm_conviction"] == "high"
        assert [row["title"] for row in thesis_view["catalysts"]] == ["Mainframe cycle"]


def test_build_thesis_diff_view_does_not_flag_change_without_prior_snapshot(monkeypatch):
    from src.stage_04_pipeline import dossier_index, dossier_view, report_archive

    with _db_factory() as factory:
        monkeypatch.setattr(dossier_index, "get_connection", factory)
        monkeypatch.setattr(dossier_view, "get_connection", factory)
        monkeypatch.setattr(report_archive, "get_connection", factory)
        monkeypatch.setattr(report_archive, "_now", lambda: "2026-03-18T20:00:00+00:00")

        report_archive.save_report_snapshot(
            "IBM",
            _build_memo(action="BUY", conviction="high", key_catalysts=["Margin recovery"]),
            dcf_audit=None,
            comps_view=None,
            market_intel_view=None,
            filings_browser_view=None,
            run_trace=[],
        )

        thesis_view = dossier_view.build_thesis_diff_view("IBM")

        assert thesis_view["snapshot_diff"]["action_changed"] is False
        assert thesis_view["snapshot_diff"]["conviction_changed"] is False


def test_build_thesis_tracker_view_preserves_pm_state_across_title_matched_ids(monkeypatch):
    from src.stage_04_pipeline import dossier_index, dossier_view, report_archive

    with _db_factory() as factory:
        monkeypatch.setattr(dossier_index, "get_connection", factory)
        monkeypatch.setattr(dossier_view, "get_connection", factory)
        monkeypatch.setattr(report_archive, "get_connection", factory)
        timestamps = iter(["2026-03-18T20:00:00+00:00", "2026-03-18T21:00:00+00:00"])
        monkeypatch.setattr(report_archive, "_now", lambda: next(timestamps))

        report_archive.save_report_snapshot(
            "IBM",
            _build_memo(
                key_catalysts=["Margin recovery"],
                thesis_pillars=[
                    {
                        "pillar_id": "legacy-pillar-core-thesis",
                        "title": "Core Thesis",
                        "description": "Margin recovery drives the case.",
                        "falsifier": "",
                        "evidence_basis": "",
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
                "pm_action": "WATCH",
                "pm_conviction": "medium",
                "summary_note": "Legacy tracker state.",
                "pillar_states_json": json.dumps(
                    {"legacy-pillar-core-thesis": {"status": "monitor", "note": "Old note.", "title_slug": "core-thesis"}},
                    sort_keys=True,
                ),
                "open_questions_json": json.dumps([], sort_keys=True),
                "last_reviewed_at": "2026-03-18T20:30:00Z",
                "latest_snapshot_id": 1,
                "metadata_json": json.dumps({}, sort_keys=True),
            }
        )
        dossier_index.upsert_tracked_catalyst(
            {
                "ticker": "IBM",
                "catalyst_key": "legacy-catalyst-margin-recovery",
                "title": "Margin recovery",
                "description": "Legacy key entry",
                "priority": "high",
                "status": "watching",
                "expected_date": None,
                "expected_window_start": None,
                "expected_window_end": None,
                "status_reason": "Tracking legacy state.",
                "source_origin": "pm",
                "source_snapshot_id": 1,
                "evidence_json": json.dumps({}, sort_keys=True),
            }
        )

        report_archive.save_report_snapshot(
            "IBM",
            _build_memo(
                structured_catalysts=[
                    {
                        "catalyst_key": "cat-structured",
                        "title": "Margin recovery",
                        "description": "Structured key entry",
                        "expected_window": "next quarter",
                        "importance": "high",
                    }
                ],
                thesis_pillars=[
                    {
                        "pillar_id": "pillar-structured",
                        "title": "Core Thesis",
                        "description": "Margin recovery drives the case.",
                        "falsifier": "",
                        "evidence_basis": "",
                    }
                ],
            ),
            dcf_audit=None,
            comps_view=None,
            market_intel_view=None,
            filings_browser_view=None,
            run_trace=[],
        )

        thesis_view = dossier_view.build_thesis_tracker_view("IBM")

        assert thesis_view["pillar_board"][0]["pm_status"] == "monitor"
        assert thesis_view["pillar_board"][0]["pm_note"] == "Old note."
        assert thesis_view["catalyst_board"]["watching"][0]["title"] == "Margin recovery"


def test_build_thesis_tracker_view_dedupes_upcoming_catalysts_by_title_and_status(monkeypatch):
    from src.stage_04_pipeline import dossier_index, dossier_view, report_archive

    with _db_factory() as factory:
        monkeypatch.setattr(dossier_index, "get_connection", factory)
        monkeypatch.setattr(dossier_view, "get_connection", factory)
        monkeypatch.setattr(report_archive, "get_connection", factory)
        timestamps = iter(["2026-03-18T20:00:00+00:00", "2026-03-18T21:00:00+00:00"])
        monkeypatch.setattr(report_archive, "_now", lambda: next(timestamps))

        report_archive.save_report_snapshot(
            "IBM",
            _build_memo(key_catalysts=["Q1 earnings"]),
            dcf_audit=None,
            comps_view=None,
            market_intel_view=None,
            filings_browser_view=None,
            run_trace=[],
        )
        report_archive.save_report_snapshot(
            "IBM",
            _build_memo(
                structured_catalysts=[
                    {"catalyst_key": "cat-1", "title": "Q1 earnings", "description": "archive row"},
                    {"catalyst_key": "cat-2", "title": "Q1 earnings", "description": "duplicate archive row"},
                ],
            ),
            dcf_audit=None,
            comps_view=None,
            market_intel_view=None,
            filings_browser_view=None,
            run_trace=[],
        )
        dossier_index.upsert_tracked_catalyst(
            {
                "ticker": "IBM",
                "catalyst_key": "cat-1",
                "title": "Q1 earnings",
                "description": "pm row",
                "priority": "high",
                "status": "watching",
                "expected_date": None,
                "expected_window_start": None,
                "expected_window_end": None,
                "status_reason": "waiting",
                "source_origin": "pm",
                "source_snapshot_id": 2,
                "evidence_json": json.dumps({}, sort_keys=True),
            }
        )

        thesis_view = dossier_view.build_thesis_tracker_view("IBM")

        assert thesis_view["next_queue"]["upcoming_catalyst_count"] == 1
        assert [row["title"] for row in thesis_view["next_queue"]["upcoming_catalysts"]] == ["Q1 earnings"]
