from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from config import DOSSIER_NOTE_EXTENSION, DOSSIER_ROOT, USE_COMPANY_NAME_IN_FOLDER


NOTE_TEMPLATES: dict[str, dict[str, str | int]] = {
    "company_hub": {"filename": "00 Company Hub", "title": "00 Company Hub", "section_kind": "hub", "is_private": 0},
    "business": {"filename": "01 Business & Industry", "title": "01 Business & Industry", "section_kind": "business", "is_private": 0},
    "financial_history": {"filename": "02 Financial History", "title": "02 Financial History", "section_kind": "financial_history", "is_private": 0},
    "management": {"filename": "03 Management & Capital Allocation", "title": "03 Management & Capital Allocation", "section_kind": "management", "is_private": 0},
    "valuation": {"filename": "04 Valuation", "title": "04 Valuation", "section_kind": "valuation", "is_private": 0},
    "risks_catalysts": {"filename": "05 Risks & Catalysts", "title": "05 Risks & Catalysts", "section_kind": "risks_catalysts", "is_private": 0},
    "thesis": {"filename": "06 Thesis", "title": "06 Thesis", "section_kind": "thesis", "is_private": 0},
    "decision_log": {"filename": "07 Decision Log", "title": "07 Decision Log", "section_kind": "decision_log", "is_private": 0},
    "review_log": {"filename": "08 Review Log", "title": "08 Review Log", "section_kind": "review_log", "is_private": 0},
    "kpi_tracker": {"filename": "09 KPI Tracker", "title": "09 KPI Tracker", "section_kind": "kpi_tracker", "is_private": 0},
    "publishable_memo": {"filename": "10 Publishable Memo", "title": "10 Publishable Memo", "section_kind": "publishable_memo", "is_private": 0},
}

WORKSPACE_DIRS = ("Notes", "Notes/Sources", "Model", "Exports", "Filings", "Decks", "Transcripts", "Private")


def _coerce_ticker(ticker: str) -> str:
    value = (ticker or "").strip().upper()
    if not value:
        raise ValueError("ticker is required")
    return value


def _sanitize_path_component(value: str) -> str:
    sanitized = re.sub(r'[\\/:*?"<>|]+', "", (value or "").strip())
    return re.sub(r"\s+", " ", sanitized).strip()


def build_dossier_path(ticker: str, company_name: str | None) -> Path:
    dossier_ticker = _coerce_ticker(ticker)
    clean_company_name = _sanitize_path_component(company_name or "")
    if USE_COMPANY_NAME_IN_FOLDER and clean_company_name:
        folder_name = f"{dossier_ticker} {clean_company_name}"
    else:
        folder_name = dossier_ticker
    return DOSSIER_ROOT / folder_name


def _note_path(root_path: Path, note_slug: str) -> Path:
    note_meta = NOTE_TEMPLATES[note_slug]
    return root_path / "Notes" / f"{note_meta['filename']}{DOSSIER_NOTE_EXTENSION}"


def _source_note_path(root_path: Path, source_id: str, title: str) -> Path:
    clean_title = _sanitize_path_component(title) or "Source Note"
    return root_path / "Notes" / "Sources" / f"{source_id} {clean_title}{DOSSIER_NOTE_EXTENSION}"


def _default_note_body(ticker: str, company_name: str | None, note_slug: str) -> str:
    note_meta = NOTE_TEMPLATES[note_slug]
    title = str(note_meta["title"])
    lines = [
        "---",
        f"ticker: {_coerce_ticker(ticker)}",
        f"company_name: {company_name or ''}",
        f"note_slug: {note_slug}",
        f"section_kind: {note_meta['section_kind']}",
        "---",
        "",
        f"# {title}",
        "",
    ]
    if note_slug == "company_hub":
        lines.extend(
            [
                "## Status",
                "",
                "- thesis_version:",
                "- model_version:",
                "- next_review_date:",
                "",
                "## Linked Workbook",
                "",
                "- path:",
                "",
                "## Top Sources",
                "",
                "- Add `S-001` style sources here.",
            ]
        )
    elif note_slug == "publishable_memo":
        lines.extend(
            [
                "## Summary",
                "",
                "## Business",
                "",
                "## Thesis",
                "",
                "## Valuation",
                "",
                "## Risks",
                "",
                "## Catalysts",
                "",
                "## Sources",
            ]
        )
    else:
        lines.append(f"Working note for `{note_meta['section_kind']}`.")
    lines.append("")
    return "\n".join(lines)


def ensure_dossier_note_templates(ticker: str, company_name: str | None) -> dict[str, Path]:
    root_path = build_dossier_path(ticker, company_name)
    (root_path / "Notes").mkdir(parents=True, exist_ok=True)
    note_paths: dict[str, Path] = {}
    for note_slug in NOTE_TEMPLATES:
        path = _note_path(root_path, note_slug)
        if not path.exists():
            path.write_text(_default_note_body(ticker, company_name, note_slug), encoding="utf-8")
        note_paths[note_slug] = path
    return note_paths


def ensure_dossier_workspace(ticker: str, company_name: str | None) -> dict[str, Any]:
    root_path = build_dossier_path(ticker, company_name)
    for relative_dir in WORKSPACE_DIRS:
        (root_path / relative_dir).mkdir(parents=True, exist_ok=True)
    note_paths = ensure_dossier_note_templates(ticker, company_name)
    return {
        "ticker": _coerce_ticker(ticker),
        "company_name": company_name,
        "root_path": str(root_path),
        "notes_root_path": str(root_path / "Notes"),
        "model_root_path": str(root_path / "Model"),
        "exports_root_path": str(root_path / "Exports"),
        "filings_root_path": str(root_path / "Filings"),
        "note_paths": {key: str(value) for key, value in note_paths.items()},
    }


def _locate_dossier_root(ticker: str) -> Path:
    dossier_ticker = _coerce_ticker(ticker)
    ticker_only = DOSSIER_ROOT / dossier_ticker
    if ticker_only.exists():
        return ticker_only
    matches = sorted(path for path in DOSSIER_ROOT.glob(f"{dossier_ticker}*") if path.is_dir())
    if matches:
        return matches[0]
    raise FileNotFoundError(f"No dossier workspace found for {dossier_ticker}")


def read_dossier_note(ticker: str, note_slug: str) -> str:
    if note_slug not in NOTE_TEMPLATES:
        raise KeyError(f"Unknown note slug: {note_slug}")
    root_path = _locate_dossier_root(ticker)
    return _note_path(root_path, note_slug).read_text(encoding="utf-8")


def write_dossier_note(ticker: str, note_slug: str, content: str) -> None:
    if note_slug not in NOTE_TEMPLATES:
        raise KeyError(f"Unknown note slug: {note_slug}")
    root_path = _locate_dossier_root(ticker)
    _note_path(root_path, note_slug).write_text(content, encoding="utf-8")


def ensure_dossier_source_note(ticker: str, source_id: str, title: str) -> Path:
    root_path = _locate_dossier_root(ticker)
    path = _source_note_path(root_path, source_id, title)
    if not path.exists():
        lines = [
            "---",
            f"ticker: {_coerce_ticker(ticker)}",
            f"source_id: {source_id}",
            f"title: {title}",
            "---",
            "",
            f"# {source_id} — {title}",
            "",
            "## Why It Matters",
            "",
            "## Key Evidence",
            "",
            "## Limitations",
            "",
        ]
        path.write_text("\n".join(lines), encoding="utf-8")
    return path


def normalize_linked_artifact_path(path_value: str | Path, *, path_mode: str = "absolute") -> dict[str, Any]:
    raw_value = Path(path_value) if not isinstance(path_value, Path) and path_mode != "uri" else path_value
    if path_mode not in {"repo_relative", "dossier_relative", "absolute", "uri"}:
        raise ValueError(f"Unsupported path_mode: {path_mode}")
    if path_mode == "absolute":
        path_text = str(Path(raw_value).resolve())
    else:
        path_text = str(raw_value).replace("\\", "/")
    return {"path_mode": path_mode, "path_value": path_text}
