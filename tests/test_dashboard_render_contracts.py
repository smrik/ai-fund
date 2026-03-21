from __future__ import annotations

from pathlib import Path


APP_PATH = Path("dashboard/app.py")
HELPER_PATH = Path("dashboard/deep_dive_sections.py")


def test_dashboard_uses_shared_presentation_formatting_module():
    source = APP_PATH.read_text(encoding="utf-8")

    assert "src.stage_04_pipeline.presentation_formatting" in source


def test_dashboard_does_not_use_deprecated_use_container_width_api():
    source = APP_PATH.read_text(encoding="utf-8")

    assert "use_container_width=" not in source


def test_dashboard_wires_new_research_surface_payloads():
    source = APP_PATH.read_text(encoding="utf-8")

    assert "coverage_summary" in source
    assert "retrieval_profiles" in source
    assert "historical_brief" in source
    assert "quarterly_headlines" in source
    assert "metric_options" in source
    assert "football_field" in source
    assert "historical_multiples_summary" in source


def test_dashboard_exposes_deep_dive_workspace_group():
    app_source = APP_PATH.read_text(encoding="utf-8")
    helper_source = HELPER_PATH.read_text(encoding="utf-8")

    assert '"Deep Dive"' in app_source
    assert "render_deep_dive_section" in app_source
    assert '"Company Hub"' in helper_source
    assert '"Model & Valuation"' in helper_source
    assert '"Sources"' in helper_source
    assert "ensure_dossier_workspace" in helper_source
    assert "upsert_dossier_source" in helper_source
