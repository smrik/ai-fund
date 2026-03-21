from __future__ import annotations

from importlib import import_module
from pathlib import Path


APP_PATH = Path("dashboard/app.py")


def test_dashboard_app_delegates_deep_dive_rendering_to_helper_module():
    source = APP_PATH.read_text(encoding="utf-8")

    assert "from dashboard.deep_dive_sections import render_deep_dive_section" in source
    assert 'if selected_section == "Company Hub":' not in source
    assert 'if selected_section == "Business":' not in source
    assert 'if selected_section == "Sources":' not in source
    assert 'if selected_section == "Model & Valuation":' not in source
    assert 'if selected_section == "Thesis Tracker":' not in source
    assert 'if selected_section == "Decision Log":' not in source
    assert 'if selected_section == "Review Log":' not in source
    assert 'if selected_section == "Publishable Memo":' not in source
    assert "render_deep_dive_section(" in source


def test_deep_dive_helper_module_exposes_expected_section_registry():
    module = import_module("dashboard.deep_dive_sections")

    expected_sections = {
        "Company Hub",
        "Business",
        "Model & Valuation",
        "Sources",
        "Thesis Tracker",
        "Decision Log",
        "Review Log",
        "Publishable Memo",
    }

    assert hasattr(module, "DEEP_DIVE_RENDERERS")
    assert hasattr(module, "render_deep_dive_section")
    assert expected_sections == set(module.DEEP_DIVE_RENDERERS)
