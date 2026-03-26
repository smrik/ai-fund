from __future__ import annotations

from pathlib import Path


APP_PATH = Path("dashboard/app.py")
HELPER_PATH = Path("dashboard/deep_dive_sections.py")
RESEARCH_PATH = Path("dashboard/sections/research.py")


def test_dashboard_wires_tracker_and_publishable_memo_surfaces():
    app_source = APP_PATH.read_text(encoding="utf-8")
    helper_source = HELPER_PATH.read_text(encoding="utf-8")
    research_source = RESEARCH_PATH.read_text(encoding="utf-8")

    assert "build_research_board_view" in research_source
    assert "render_dossier_companion" in app_source
    assert '"Thesis Tracker"' in helper_source
    assert "build_thesis_tracker_view" in helper_source
    assert "build_thesis_diff_view" not in helper_source
    assert "upsert_tracker_state" in helper_source
    assert "upsert_tracked_catalyst" in helper_source
    assert '"pillar_states_json": json.dumps({}, sort_keys=True)' not in helper_source
    assert 'open_questions_json": json.dumps(memo.open_questions, sort_keys=True)' not in helper_source
    assert "tracker_catalyst_form" not in helper_source
    assert "st.json(" not in helper_source
    assert "What Changed Since Last Snapshot" in helper_source
    assert "Next Diligence Queue" in helper_source
    assert "Change details" in helper_source
    assert "Tracker data quality notes:" in helper_source
    assert "st.data_editor" in helper_source
    assert "tracker_catalyst_editor" in helper_source
    assert "pillar_board_summary" in helper_source
    assert "tracker_pillars_form" in helper_source
    assert "Edit Catalyst Board" in helper_source
    assert "_render_compact_list" in helper_source
    assert "_status_breakdown" in helper_source
    assert "pillars_tab, catalysts_tab, continuity_tab = st.tabs" not in helper_source
    assert '"Publishable Memo"' in helper_source
    assert "build_publishable_memo_context" in helper_source
    assert "render_thesis_tracker(" in research_source
    assert "render_publishable_memo(" in research_source
