from __future__ import annotations

from datetime import date
import json
from pathlib import Path

from ciq import ciq_refresh
from tests.ciq_test_utils import create_ibm_style_workbook


def test_default_template_name_matches_canonical_cleandata_workbook() -> None:
    assert ciq_refresh.DEFAULT_TEMPLATE_NAME == "ciq_cleandata.xlsx"


def test_resolve_ciq_symbol_prefers_explicit_symbol() -> None:
    assert ciq_refresh.resolve_ciq_symbol("CALM", ciq_symbol="NASDAQ:CALM") == "NASDAQ:CALM"


def test_resolve_ciq_symbol_accepts_explicit_exchange() -> None:
    assert ciq_refresh.resolve_ciq_symbol("IBM", exchange="NYSE") == "NYSE:IBM"


def test_prepare_single_ticker_refresh_writes_input_and_copies_template(tmp_path: Path, monkeypatch) -> None:
    templates_dir = tmp_path / "templates"
    exports_dir = tmp_path / "exports"
    templates_dir.mkdir()
    exports_dir.mkdir()

    template_path = create_ibm_style_workbook(templates_dir / "ciq_cleandata.xlsx")
    input_path = templates_dir / "financials_input.json"
    input_path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(ciq_refresh, "CIQ_TEMPLATES_DIR", templates_dir)
    monkeypatch.setattr(ciq_refresh, "CIQ_DROP_FOLDER", exports_dir)

    workbook_path = ciq_refresh.prepare_single_ticker_refresh(
        ticker="CALM",
        ciq_symbol="NASDAQ:CALM",
        as_of_date=date(2026, 3, 29),
        template_path=template_path,
        input_json_path=input_path,
        output_folder=exports_dir,
    )

    assert workbook_path == exports_dir / "CALM_Standard.xlsx"
    assert workbook_path.exists()

    payload = json.loads(input_path.read_text(encoding="utf-8"))
    assert payload == {
        "ticker": "NASDAQ:CALM",
        "date_year": 2026,
        "date_month": 3,
        "date_day": 29,
        "currency": "USD",
    }


def test_refresh_and_ingest_single_ticker_orchestrates_refresh_and_ingest(tmp_path: Path, monkeypatch) -> None:
    template_path = create_ibm_style_workbook(tmp_path / "ciq_cleandata.xlsx")
    output_folder = tmp_path / "exports"
    output_folder.mkdir()
    input_json_path = tmp_path / "financials_input.json"
    input_json_path.write_text("{}", encoding="utf-8")

    refresh_calls: list[Path] = []
    ingest_calls: list[Path] = []
    archive_calls: list[tuple[Path, str, str | date | None, Path | None]] = []

    monkeypatch.setattr(ciq_refresh, "refresh_workbook", lambda path, timeout_sec=300: refresh_calls.append(path) or True)
    monkeypatch.setattr(
        ciq_refresh,
        "ingest_ciq_folder",
        lambda folder_path: ingest_calls.append(Path(folder_path)) or {"processed": 1, "failed": 0},
    )
    monkeypatch.setattr(
        ciq_refresh,
        "archive_refreshed_workbook",
        lambda workbook_path, *, ticker, as_of_date=None, archive_dir=None: archive_calls.append(
            (workbook_path, ticker, as_of_date, archive_dir)
        ) or (tmp_path / "archive" / "CALM_2026-03-29_20260329-010203.xlsx"),
    )

    result = ciq_refresh.refresh_and_ingest_single_ticker(
        ticker="CALM",
        ciq_symbol="NASDAQ:CALM",
        as_of_date=date(2026, 3, 29),
        template_path=template_path,
        input_json_path=input_json_path,
        output_folder=output_folder,
    )

    staged_workbook = output_folder / "CALM_Standard.xlsx"

    assert refresh_calls == [staged_workbook]
    assert ingest_calls == [output_folder]
    assert archive_calls == [(staged_workbook, "CALM", date(2026, 3, 29), None)]
    assert result["ticker"] == "CALM"
    assert result["ciq_symbol"] == "NASDAQ:CALM"
    assert result["refreshed"] is True
    assert result["workbook_path"] == str(staged_workbook)
    assert result["archive_path"] == str(tmp_path / "archive" / "CALM_2026-03-29_20260329-010203.xlsx")
    assert result["ingest_report"] == {"processed": 1, "failed": 0}


def test_refresh_and_ingest_single_ticker_skips_archive_when_ingest_fails(tmp_path: Path, monkeypatch) -> None:
    template_path = create_ibm_style_workbook(tmp_path / "ciq_cleandata.xlsx")
    output_folder = tmp_path / "exports"
    output_folder.mkdir()
    input_json_path = tmp_path / "financials_input.json"
    input_json_path.write_text("{}", encoding="utf-8")

    archive_called = False

    monkeypatch.setattr(ciq_refresh, "refresh_workbook", lambda path, timeout_sec=300: True)
    monkeypatch.setattr(ciq_refresh, "ingest_ciq_folder", lambda folder_path: {"processed": 0, "failed": 1})

    def _archive(*args, **kwargs):
        nonlocal archive_called
        archive_called = True
        return tmp_path / "archive" / "should-not-exist.xlsx"

    monkeypatch.setattr(ciq_refresh, "archive_refreshed_workbook", _archive)

    result = ciq_refresh.refresh_and_ingest_single_ticker(
        ticker="CALM",
        ciq_symbol="NASDAQ:CALM",
        as_of_date=date(2026, 3, 29),
        template_path=template_path,
        input_json_path=input_json_path,
        output_folder=output_folder,
    )

    assert archive_called is False
    assert result["archive_path"] is None


def test_refresh_and_ingest_single_ticker_archives_when_ingest_is_deduplicated(tmp_path: Path, monkeypatch) -> None:
    template_path = create_ibm_style_workbook(tmp_path / "ciq_cleandata.xlsx")
    output_folder = tmp_path / "exports"
    output_folder.mkdir()
    input_json_path = tmp_path / "financials_input.json"
    input_json_path.write_text("{}", encoding="utf-8")

    archive_calls: list[Path] = []

    monkeypatch.setattr(ciq_refresh, "refresh_workbook", lambda path, timeout_sec=300: True)
    monkeypatch.setattr(ciq_refresh, "ingest_ciq_folder", lambda folder_path: {"processed": 0, "skipped": 1, "failed": 0})
    monkeypatch.setattr(
        ciq_refresh,
        "archive_refreshed_workbook",
        lambda workbook_path, *, ticker, as_of_date=None, archive_dir=None: archive_calls.append(Path(workbook_path))
        or (tmp_path / "archive" / "CALM_2026-03-29_20260329-010204.xlsx"),
    )

    result = ciq_refresh.refresh_and_ingest_single_ticker(
        ticker="CALM",
        ciq_symbol="NASDAQ:CALM",
        as_of_date=date(2026, 3, 29),
        template_path=template_path,
        input_json_path=input_json_path,
        output_folder=output_folder,
    )

    assert archive_calls == [output_folder / "CALM_Standard.xlsx"]
    assert result["archive_path"] == str(tmp_path / "archive" / "CALM_2026-03-29_20260329-010204.xlsx")
