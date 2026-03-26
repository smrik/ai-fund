from __future__ import annotations

from pathlib import Path


def test_ensure_dossier_workspace_creates_expected_tree_and_templates(monkeypatch, tmp_path):
    from src.stage_04_pipeline import dossier_workspace

    monkeypatch.setattr(dossier_workspace, "DOSSIER_ROOT", tmp_path / "dossiers")

    workspace = dossier_workspace.ensure_dossier_workspace("ibm", "International Business Machines")

    root_path = Path(workspace["root_path"])
    assert root_path.name == "IBM International Business Machines"
    assert root_path.exists()

    for folder_name in ("Notes", "Model", "Exports", "Filings", "Decks", "Transcripts", "Private"):
        assert (root_path / folder_name).is_dir()

    note_paths = workspace["note_paths"]
    assert "company_hub" in note_paths
    assert "publishable_memo" in note_paths
    assert "research_notebook" in note_paths
    assert Path(note_paths["company_hub"]).exists()
    assert Path(note_paths["publishable_memo"]).exists()
    assert Path(note_paths["research_notebook"]).exists()

    hub_text = dossier_workspace.read_dossier_note("IBM", "company_hub")
    assert "ticker: IBM" in hub_text
    assert "company_name: International Business Machines" in hub_text


def test_ensure_dossier_workspace_is_idempotent(monkeypatch, tmp_path):
    from src.stage_04_pipeline import dossier_workspace

    monkeypatch.setattr(dossier_workspace, "DOSSIER_ROOT", tmp_path / "dossiers")

    first = dossier_workspace.ensure_dossier_workspace("IBM", "International Business Machines")
    second = dossier_workspace.ensure_dossier_workspace("IBM", "International Business Machines")

    assert first["root_path"] == second["root_path"]
    assert first["note_paths"] == second["note_paths"]


def test_build_dossier_path_falls_back_to_ticker_only(monkeypatch, tmp_path):
    from src.stage_04_pipeline import dossier_workspace

    monkeypatch.setattr(dossier_workspace, "DOSSIER_ROOT", tmp_path / "dossiers")
    monkeypatch.setattr(dossier_workspace, "USE_COMPANY_NAME_IN_FOLDER", True)

    assert dossier_workspace.build_dossier_path("msft", None) == tmp_path / "dossiers" / "MSFT"
