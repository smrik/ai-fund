from __future__ import annotations

from importlib import import_module
from pathlib import Path


APP_PATH = Path("dashboard/app.py")
SECTIONS_INIT = Path("dashboard/sections/__init__.py")
SECTION_MODULES = {
    "overview",
    "valuation",
    "market",
    "research",
    "audit",
}
CHILD_MODULES = {
    "batch_funnel",
    "comps",
    "wacc_lab",
    "assumption_lab",
    "dcf_audit",
    "filings_browser",
    "export",
    "recommendations",
    "portfolio_risk",
    "macro",
    "revisions",
    "factor_exposure",
}


def test_dashboard_app_is_thin_shell_and_registry_router():
    source = APP_PATH.read_text(encoding="utf-8")

    assert SECTIONS_INIT.exists()
    assert "from dashboard.sections import SECTION_REGISTRY" in source
    assert "SECTION_REGISTRY[selected_primary_tab]" in source
    assert source.count('if selected_section == "') < 5
    assert len(source.splitlines()) < 800


def test_dashboard_sections_registry_exposes_expected_top_level_renderers():
    module = import_module("dashboard.sections")

    assert hasattr(module, "SECTION_REGISTRY")
    assert set(module.SECTION_REGISTRY) == {
        "Overview",
        "Valuation",
        "Market",
        "Research",
        "Audit",
    }

    for key, renderer in module.SECTION_REGISTRY.items():
        assert callable(renderer), key


def test_each_dashboard_section_module_exposes_render_contract():
    for name in SECTION_MODULES:
        module = import_module(f"dashboard.sections.{name}")
        assert hasattr(module, "render"), name
        assert callable(module.render), name


def test_dashboard_child_section_modules_exist_for_heavy_surfaces():
    for name in CHILD_MODULES:
        path = Path("dashboard/sections") / f"{name}.py"
        assert path.exists(), name
