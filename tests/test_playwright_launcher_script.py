from __future__ import annotations

from pathlib import Path


SCRIPT_PATH = Path("scripts/manual/launch-streamlit-playwright-cli.ps1")


def test_playwright_launcher_script_exists_and_documents_host_usage():
    assert SCRIPT_PATH.exists()
    source = SCRIPT_PATH.read_text(encoding="utf-8")

    assert "playwright-cli open" in source
    assert "streamlit run dashboard/app.py" in source
    assert "Run this from a normal local PowerShell session" in source
    assert "ca ai-fund" in source
    assert "Preview" in source
