from __future__ import annotations

from pathlib import Path


APP_PATH = Path("dashboard/app.py")
HELPER_PATH = Path("dashboard/deep_dive_sections.py")


def test_dashboard_wires_tracker_and_publishable_memo_surfaces():
    app_source = APP_PATH.read_text(encoding="utf-8")
    helper_source = HELPER_PATH.read_text(encoding="utf-8")

    assert "render_deep_dive_section" in app_source
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
    assert "Pillars" in helper_source
    assert "Catalysts" in helper_source
    assert "Continuity" in helper_source
    assert '"Publishable Memo"' in helper_source
    assert "build_publishable_memo_context" in helper_source
