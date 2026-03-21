from __future__ import annotations

from pathlib import Path


APP_PATH = Path("dashboard/app.py")
HELPER_PATH = Path("dashboard/deep_dive_sections.py")


def test_dashboard_wires_tracker_and_publishable_memo_surfaces():
    app_source = APP_PATH.read_text(encoding="utf-8")
    helper_source = HELPER_PATH.read_text(encoding="utf-8")

    assert "render_deep_dive_section" in app_source
    assert '"Thesis Tracker"' in helper_source
    assert "build_thesis_diff_view" in helper_source
    assert "upsert_tracker_state" in helper_source
    assert "upsert_tracked_catalyst" in helper_source
    assert '"Publishable Memo"' in helper_source
    assert "build_publishable_memo_context" in helper_source
