from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT_PATH = Path("scripts/manual/capture_react_dev_pages.py")
FRONTEND_README = Path("frontend/README.md")
REVIEW_LOOP_DOC = Path("docs/handbook/react-playwright-review-loop.md")
CLAUDE_SKILL = Path(".claude/skills/playwright-cli/SKILL.md")


def load_script_module():
    spec = importlib.util.spec_from_file_location("capture_react_dev_pages", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_react_dev_capture_script_exists_and_exposes_route_selection():
    assert SCRIPT_PATH.exists()

    module = load_script_module()

    smoke_names = [route.name for route in module.select_routes(full=False, one_page=None)]
    full_names = [route.name for route in module.select_routes(full=True, one_page=None)]
    market_only = [route.name for route in module.select_routes(full=False, one_page="market")]

    assert smoke_names == [
        "watchlist",
        "overview",
        "valuation-summary",
        "market",
        "research",
        "audit",
    ]
    assert full_names == [
        "watchlist",
        "overview",
        "valuation-summary",
        "valuation-dcf",
        "valuation-multiples",
        "valuation-recommendations",
        "market",
        "research",
        "audit",
    ]
    assert market_only == ["market"]


def test_react_dev_capture_script_resolves_real_cli_executables(monkeypatch):
    module = load_script_module()

    def fake_which(name: str):
        if name == "npx":
            return r"C:\Program Files\nodejs\npx.cmd"
        if name == "playwright-cli":
            return None
        return None

    monkeypatch.setattr(module.shutil, "which", fake_which)

    assert module.resolve_cli_command() == [r"C:\Program Files\nodejs\npx.cmd", "playwright-cli"]


def test_react_dev_capture_docs_explain_quiet_modes():
    frontend_readme = FRONTEND_README.read_text(encoding="utf-8")
    review_loop_doc = REVIEW_LOOP_DOC.read_text(encoding="utf-8")

    for contents in [frontend_readme, review_loop_doc]:
        assert "capture_react_dev_pages.py" in contents
        assert "--full" in contents
        assert "--one-page" in contents
        assert "output/playwright/dev-verify/" in contents


def test_claude_playwright_skill_recommends_repo_capture_helper():
    source = CLAUDE_SKILL.read_text(encoding="utf-8")

    assert "capture_react_dev_pages.py" in source
    assert "--one-page" in source
    assert "--full" in source
