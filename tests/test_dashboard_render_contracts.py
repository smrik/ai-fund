from __future__ import annotations

from pathlib import Path


APP_PATH = Path("dashboard/app.py")
HELPER_PATH = Path("dashboard/deep_dive_sections.py")
STREAMLIT_CONFIG_PATH = Path(".streamlit/config.toml")
DESIGN_SYSTEM_PATH = Path("dashboard/design_system.py")
SECTIONS_INIT_PATH = Path("dashboard/sections/__init__.py")
SECTIONS_SHARED_PATH = Path("dashboard/sections/_shared.py")
VALUATION_PATH = Path("dashboard/sections/valuation.py")
MARKET_PATH = Path("dashboard/sections/market.py")
RESEARCH_PATH = Path("dashboard/sections/research.py")
AUDIT_PATH = Path("dashboard/sections/audit.py")


def test_dashboard_uses_shared_presentation_formatting_module():
    source = SECTIONS_SHARED_PATH.read_text(encoding="utf-8")

    assert "src.stage_04_pipeline.presentation_formatting" in source


def test_dashboard_does_not_use_deprecated_use_container_width_api():
    source = APP_PATH.read_text(encoding="utf-8")

    assert "use_container_width=" not in source


def test_dashboard_wires_new_research_surface_payloads():
    valuation_source = VALUATION_PATH.read_text(encoding="utf-8")
    market_source = MARKET_PATH.read_text(encoding="utf-8")
    research_source = RESEARCH_PATH.read_text(encoding="utf-8")
    audit_source = AUDIT_PATH.read_text(encoding="utf-8")

    assert "build_research_board_view" in research_source
    assert "historical_brief" in market_source
    assert "quarterly_headlines" in market_source
    assert "render_comparables" in valuation_source
    assert "render_multiples" in valuation_source
    assert '"Assumptions"' in valuation_source
    assert '"WACC"' in valuation_source
    assert '"Recommendations"' in valuation_source
    assert "football_field" in Path("dashboard/sections/comps.py").read_text(encoding="utf-8")
    assert "coverage_summary" in audit_source
    assert "retrieval_profiles" in Path("dashboard/sections/filings_browser.py").read_text(encoding="utf-8")


def test_dashboard_exposes_deep_dive_workspace_group():
    app_source = APP_PATH.read_text(encoding="utf-8")
    helper_source = HELPER_PATH.read_text(encoding="utf-8")

    assert '"Deep Dive"' not in app_source
    assert 'selected_primary_tab = st.segmented_control(' in app_source
    assert 'selected_primary_tab = st.selectbox(' not in app_source
    assert "SECTION_REGISTRY" in app_source
    assert '"Company Hub"' in helper_source
    assert '"Model & Valuation"' in helper_source
    assert '"Sources"' in helper_source
    assert "ensure_dossier_workspace" in helper_source
    assert "upsert_dossier_source" in helper_source


def test_dashboard_uses_reduced_navigation_and_dark_streamlit_theme():
    app_source = APP_PATH.read_text(encoding="utf-8")

    assert "st.tabs(" not in app_source
    assert STREAMLIT_CONFIG_PATH.exists()


def test_dashboard_uses_extracted_design_system_and_shell_header():
    app_source = APP_PATH.read_text(encoding="utf-8")

    assert DESIGN_SYSTEM_PATH.exists()
    assert "from dashboard.design_system import DASHBOARD_CSS, render_shell_header, render_ticker_strip" in app_source
    assert "from dashboard.sections import SECTION_REGISTRY" in app_source
    assert "render_shell_header(" in app_source
    assert "render_ticker_strip(" in app_source
    assert 'selected_primary_tab = st.segmented_control(' in app_source
    assert 'selected_group = st.selectbox(' not in app_source
    assert 'selected_section = st.selectbox(' not in app_source
    assert "| Agent | Role |" not in app_source
    assert "Three ways to use the dashboard" in app_source
    assert '"selected_primary_tab": "Audit"' in app_source
    assert '"audit_view": "Batch Funnel"' in app_source
    assert '_ensure_nav_selection("selected_primary_tab", "Overview" if memo is not None else "Audit", available_primary_tabs)' in app_source
    assert '"Refresh Single Ticker"' in app_source
    assert '"refresh_single_ticker"' in app_source


def test_dashboard_shell_uses_five_primary_tabs_and_dossier_companion():
    app_source = APP_PATH.read_text(encoding="utf-8")
    companion_source = Path("dashboard/dossier_companion.py").read_text(encoding="utf-8")
    audit_source = AUDIT_PATH.read_text(encoding="utf-8")

    assert "SECTION_REGISTRY" in app_source
    assert "_ensure_nav_selection(" in app_source
    assert "def _build_page_context(" in app_source
    assert '"Overview"' in app_source
    assert '"Valuation"' in app_source
    assert '"Market"' in app_source
    assert '"Research"' in app_source
    assert '"Audit"' in app_source
    assert '"Ops"' not in app_source
    assert "render_dossier_companion(" in app_source
    assert '"notes_rail_open"' in app_source
    assert 'with st.popover("Open Notes")' not in app_source
    assert 'st.toggle("Show Notes Rail", key="notes_rail_open")' in app_source
    assert '"item": selected_primary_tab' not in app_source
    assert 'st.session_state.get("note_context")' in app_source
    assert 'default=st.session_state["selected_primary_tab"]' not in app_source
    assert 'default=st.session_state.get("valuation_view", "Summary")' not in app_source
    assert 'default=st.session_state.get("market_view", "Summary")' not in app_source
    assert 'default=st.session_state.get("audit_view", "Overview")' not in app_source
    assert '"Batch Funnel"' in audit_source
    assert 'if memo is None and selected_primary_tab == "Audit":' in app_source
    assert 'st.session_state["audit_view"] = "Batch Funnel"' in app_source
    assert 'load_saved_watchlist' in Path("dashboard/sections/batch_funnel.py").read_text(encoding="utf-8")
    assert 'st.session_state[scratch_key] = scratch_text' not in companion_source
    assert '"block_ts": memo.date' not in companion_source
    assert "_build_note_block_row(" in companion_source
    assert "_current_note_block_ts()" in companion_source
    assert '"Business"' in audit_source


def test_dashboard_uses_compact_strip_outside_overview():
    app_source = APP_PATH.read_text(encoding="utf-8")
    design_source = DESIGN_SYSTEM_PATH.read_text(encoding="utf-8")

    assert 'if memo is None or selected_primary_tab == "Overview":' in app_source
    assert 'elif memo is not None and selected_primary_tab == "Overview":' in app_source
    assert "def render_ticker_strip(" in design_source
    assert ".ap-ticker-strip" in design_source


def test_design_system_centralizes_tokens_and_reduces_important_usage():
    design_source = DESIGN_SYSTEM_PATH.read_text(encoding="utf-8")
    app_source = APP_PATH.read_text(encoding="utf-8")

    assert "Inter Tight" in design_source
    assert "Playfair Display" in design_source
    assert "JetBrains Mono" in design_source
    assert "--ap-background" in design_source
    assert "--ap-accent" in design_source
    assert design_source.count("!important") < 50
    assert app_source.count("!important") < 10
