from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]

DETERMINISTIC_ROOTS = (
    REPO_ROOT / "src" / "stage_00_data",
    REPO_ROOT / "src" / "stage_01_screening",
    REPO_ROOT / "src" / "stage_02_valuation",
)

STREAMLIT_SCAN_ROOTS = (
    REPO_ROOT / "main.py",
    REPO_ROOT / "setup.py",
    REPO_ROOT / "src",
    REPO_ROOT / "ciq",
    REPO_ROOT / "db",
)

PRINT_SCAN_ROOTS = (
    REPO_ROOT / "main.py",
    REPO_ROOT / "setup.py",
    REPO_ROOT / "src",
    REPO_ROOT / "ciq",
    REPO_ROOT / "db",
    REPO_ROOT / "dashboard",
)

SQLITE_SCAN_ROOTS = (
    REPO_ROOT / "main.py",
    REPO_ROOT / "setup.py",
    REPO_ROOT / "src",
    REPO_ROOT / "ciq",
    REPO_ROOT / "dashboard",
)

PRINT_ALLOWLIST = {
    "ciq/ciq_refresh.py",
    "ciq/ingest.py",
    "db/schema.py",
    "main.py",
    "setup.py",
    "src/portfolio/tracker.py",
    "src/stage_01_screening/seed_universe.py",
    "src/stage_01_screening/stage1_filter.py",
    "src/stage_01_screening/stage2_filter.py",
    "src/stage_01_screening/stage2_short_filter.py",
    "src/stage_02_valuation/create_template.py",
    "src/stage_04_pipeline/daily_refresh.py",
    "src/stage_04_pipeline/refresh.py",
}

SQLITE_CONNECT_ALLOWLIST = {
    "dashboard/sections/portfolio_risk.py",
    "src/portfolio/tracker.py",
    "src/stage_00_data/ciq_adapter.py",
    "src/stage_00_data/company_descriptions.py",
    "src/stage_00_data/filing_retrieval.py",
    "src/stage_00_data/market_data.py",
    "src/stage_00_data/peer_similarity.py",
    "src/stage_00_data/sec_filing_metrics.py",
    "src/stage_01_screening/stage2_filter.py",
    "src/stage_01_screening/stage2_short_filter.py",
    "src/stage_02_valuation/batch_runner.py",
    "src/stage_04_pipeline/filings_browser.py",
    "src/stage_04_pipeline/news_materiality.py",
    "src/stage_04_pipeline/refresh.py",
}


def _iter_python_files(*roots: Path) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        if root.is_file():
            files.append(root)
            continue
        files.extend(sorted(root.rglob("*.py")))
    return files


def _parse_python_file(py_file: Path) -> ast.AST:
    try:
        return ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    except SyntaxError as exc:  # pragma: no cover - parsing failure is a hard stop
        raise AssertionError(f"Failed to parse {py_file}: {exc}") from exc


def _relative_path(py_file: Path) -> str:
    return py_file.relative_to(REPO_ROOT).as_posix()


def _sqlite3_aliases(tree: ast.AST) -> tuple[set[str], set[str]]:
    module_aliases = {"sqlite3"}
    connect_aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "sqlite3":
                    module_aliases.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module == "sqlite3":
            for alias in node.names:
                if alias.name == "connect":
                    connect_aliases.add(alias.asname or alias.name)
    return module_aliases, connect_aliases


def test_deterministic_layers_do_not_import_judgment_modules():
    """Data + compute stages must never import stage_03_judgment."""
    disallowed_tokens = [
        "src.stage_03_judgment",
        "from src.stage_03_judgment",
        "import src.stage_03_judgment",
    ]

    # batch_runner.py is the CLI orchestration entry point; it is explicitly
    # allowed to call across layers as an orchestrator (not a library module).
    excluded = {"batch_runner.py"}

    violations: list[str] = []
    for root in DETERMINISTIC_ROOTS:
        for py_file in sorted(root.rglob("*.py")):
            if py_file.name in excluded:
                continue
            text = py_file.read_text(encoding="utf-8")
            if any(token in text for token in disallowed_tokens):
                violations.append(_relative_path(py_file))

    assert violations == [], f"Deterministic-layer imports from judgment layer found: {violations}"


def test_non_dashboard_modules_do_not_import_streamlit():
    """Only dashboard modules may import Streamlit."""
    violations: list[str] = []

    for py_file in _iter_python_files(*STREAMLIT_SCAN_ROOTS):
        tree = _parse_python_file(py_file)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported = {alias.name.split(".", maxsplit=1)[0] for alias in node.names}
                if "streamlit" in imported:
                    violations.append(f"{_relative_path(py_file)}:{node.lineno}")
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module == "streamlit" or module.startswith("streamlit."):
                    violations.append(f"{_relative_path(py_file)}:{node.lineno}")

    assert violations == [], f"Non-dashboard Streamlit imports found: {violations}"


def test_no_bare_print_calls_in_library_modules():
    """Keep bare print() calls fenced to the current operator debt set."""
    violations: list[str] = []

    for py_file in _iter_python_files(*PRINT_SCAN_ROOTS):
        rel = _relative_path(py_file)
        if rel in PRINT_ALLOWLIST:
            continue

        tree = _parse_python_file(py_file)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "print":
                violations.append(f"{rel}:{node.lineno}")

    assert violations == [], f"Bare print() calls found outside allowlist: {violations}"


def test_no_new_sqlite_connect_calls_outside_db_or_current_debt_sites():
    """Freeze current raw sqlite3.connect() debt and block new call sites."""
    violations: list[str] = []

    for py_file in _iter_python_files(*SQLITE_SCAN_ROOTS):
        rel = _relative_path(py_file)
        if rel in SQLITE_CONNECT_ALLOWLIST:
            continue

        tree = _parse_python_file(py_file)
        sqlite_aliases, connect_aliases = _sqlite3_aliases(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue

            func = node.func
            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                if func.attr == "connect" and func.value.id in sqlite_aliases:
                    violations.append(f"{rel}:{node.lineno}")
                continue

            if isinstance(func, ast.Name) and func.id in connect_aliases:
                violations.append(f"{rel}:{node.lineno}")

    assert violations == [], f"New sqlite3.connect() call sites found outside frozen allowlist: {violations}"
