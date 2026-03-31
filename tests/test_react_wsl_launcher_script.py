from __future__ import annotations

import subprocess
from pathlib import Path


SCRIPT_PATH = Path("scripts/manual/launch-react-wsl.sh")
REQ_PATH = Path("requirements-api.txt")
API_CLIENT_PATH = Path("frontend/src/lib/api.ts")


def test_react_wsl_launcher_script_exists_and_supports_preview():
    assert SCRIPT_PATH.exists()
    source = SCRIPT_PATH.read_text(encoding="utf-8")

    assert "ensure_venv()" in source
    assert "start_api()" in source
    assert "start_frontend()" in source
    assert "wait_for_ready()" in source
    assert "stop_all()" in source
    assert "show_status()" in source
    assert "requirements-api.txt" in source
    assert '"$VENV_DIR/bin/python" -m pip install -r "$REQ_FILE"' in source
    assert "--preview" in source
    assert "--stop" in source
    assert "--status" in source
    assert "uvicorn api.main:app" in source
    assert "npm run build" in source
    assert "serve_frontend_dist.py" in source
    assert "--reload" not in source


def test_frontend_api_client_supports_explicit_api_base():
    source = API_CLIENT_PATH.read_text(encoding="utf-8")

    assert 'import.meta.env.VITE_API_BASE' in source
    assert 'const API_BASE' in source


def test_requirements_api_file_exists_and_stays_lightweight():
    assert REQ_PATH.exists()
    contents = REQ_PATH.read_text(encoding="utf-8")

    for package in [
        "fastapi",
        "uvicorn[standard]",
        "pydantic",
        "httpx",
        "pandas",
        "numpy",
        "yfinance",
        "edgartools",
        "statsmodels",
        "scikit-learn",
    ]:
        assert package in contents

    for package in [
        "torch",
        "hmmlearn",
        "sentence-transformers",
        "anthropic",
        "openai",
        "streamlit",
        "xlwings",
        "ib_insync",
        "jupyter",
        "mkdocs",
        "pytest",
    ]:
        assert package not in contents


def test_react_wsl_launcher_preview_describes_review_stack():
    result = subprocess.run(
        ["bash", SCRIPT_PATH.as_posix(), "--preview"],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "Alpha Pod React WSL launcher preview" in result.stdout
    assert "requirements-api.txt" in result.stdout
    assert "npm --prefix frontend run build" in result.stdout or 'npm run build' in result.stdout
    assert "serve_frontend_dist.py" in result.stdout
    assert "playwright-cli open" in result.stdout
    assert "launch-react-wsl.sh --status" in result.stdout
    assert "launch-react-wsl.sh --stop" in result.stdout
