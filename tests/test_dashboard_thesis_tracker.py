from __future__ import annotations

from pathlib import Path


APP_PATH = Path("dashboard/app.py")


def test_dashboard_wires_tracker_and_publishable_memo_surfaces():
    source = APP_PATH.read_text(encoding="utf-8")

    assert 'selected_section == "Thesis Tracker"' in source
    assert "build_thesis_diff_view" in source
    assert "upsert_tracker_state" in source
    assert "upsert_tracked_catalyst" in source
    assert 'selected_section == "Publishable Memo"' in source
    assert "build_publishable_memo_context" in source
