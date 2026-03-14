from pathlib import Path


def test_deterministic_layers_do_not_import_judgment_modules():
    """Data + compute stages must never import stage_03_judgment."""
    repo_root = Path(__file__).resolve().parents[1]
    deterministic_roots = [
        repo_root / "src" / "stage_00_data",
        repo_root / "src" / "stage_01_screening",
        repo_root / "src" / "stage_02_valuation",
    ]

    disallowed_tokens = [
        "src.stage_03_judgment",
        "from src.stage_03_judgment",
        "import src.stage_03_judgment",
    ]

    # batch_runner.py is the CLI orchestration entry point; it is explicitly
    # allowed to call across layers as an orchestrator (not a library module).
    _excluded = {"batch_runner.py"}

    violations: list[str] = []
    for root in deterministic_roots:
        for py_file in root.rglob("*.py"):
            if py_file.name in _excluded:
                continue
            text = py_file.read_text(encoding="utf-8")
            if any(token in text for token in disallowed_tokens):
                rel = py_file.relative_to(repo_root)
                violations.append(str(rel))

    assert violations == [], f"Deterministic-layer imports from judgment layer found: {violations}"
