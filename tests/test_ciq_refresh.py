from __future__ import annotations

from datetime import date
import json
from pathlib import Path

from ciq import ciq_refresh
from tests.ciq_test_utils import create_ibm_style_workbook


class _FakeRange:
    def __init__(self, value):
        self.value = value


class _FakeSheet:
    def __init__(self, name: str, values, cells: dict[str, object] | None = None):
        self.name = name
        self.used_range = _FakeRange(values)
        self._cells = cells or {}

    def range(self, cell_ref: str) -> _FakeRange:
        return _FakeRange(self._cells.get(cell_ref))


class _FakeSheets:
    def __init__(self, sheets: list[_FakeSheet]):
        self._sheets = sheets
        self._by_name = {sheet.name: sheet for sheet in sheets}

    def __iter__(self):
        return iter(self._sheets)

    def __getitem__(self, name: str) -> _FakeSheet:
        return self._by_name[name]


class _FakeWorkbook:
    def __init__(self, sheets: list[_FakeSheet]):
        self.sheets = _FakeSheets(sheets)


class _FakeApi:
    def __init__(self, calls: list[str], connections: list[object] | None = None):
        self.calls = calls
        self.Connections = connections or []

    def RefreshAll(self):
        self.calls.append("RefreshAll")

    def CalculateUntilAsyncQueriesDone(self):
        self.calls.append("CalculateUntilAsyncQueriesDone")


class _FakeConnection:
    def __init__(self, calls: list[str], name: str):
        self.calls = calls
        self.name = name

    def Refresh(self):
        self.calls.append(f"Connection.Refresh:{self.name}")


class _FakeExcelApp:
    def __init__(self, calls: list[str]):
        self.api = _FakeApi(calls)
        self.calls = calls

    def calculate(self):
        self.calls.append("calculate")


class _FakeExcelBook:
    def __init__(self, calls: list[str], connections: list[object]):
        self.api = _FakeApi(calls, connections)


def test_default_template_name_matches_canonical_cleandata_workbook() -> None:
    assert ciq_refresh.DEFAULT_TEMPLATE_NAME == "ciq_cleandata.xlsx"


def test_resolve_ciq_symbol_prefers_explicit_symbol() -> None:
    assert ciq_refresh.resolve_ciq_symbol("CALM", ciq_symbol="NASDAQ:CALM") == "NASDAQ:CALM"


def test_resolve_ciq_symbol_accepts_explicit_exchange() -> None:
    assert ciq_refresh.resolve_ciq_symbol("IBM", exchange="NYSE") == "NYSE:IBM"


def test_resolve_ciq_symbol_accepts_prefixed_ticker() -> None:
    assert ciq_refresh.resolve_ciq_symbol("NASDAQ:CALM") == "NASDAQ:CALM"


def test_validate_refreshed_workbook_rejects_pending_and_error_values() -> None:
    workbook = _FakeWorkbook(
        [
            _FakeSheet("Input", [["ticker", "NASDAQ:CALM"]], {"B2": "NASDAQ:CALM"}),
            _FakeSheet(
                "Financial Statements",
                [["Period", "FY25"], ["Revenue", "Requesting Data"], ["Debt", "#VALUE!"]],
                {"C2": "NASDAQ:CALM"},
            ),
        ]
    )

    result = ciq_refresh.validate_refreshed_workbook(workbook, expected_ticker="CALM")

    assert result.ok is False
    assert result.pending_count == 1
    assert result.error_count == 1
    assert any("Requesting Data" in finding for finding in result.findings or [])


def test_validate_refreshed_workbook_rejects_ticker_mismatch() -> None:
    workbook = _FakeWorkbook(
        [
            _FakeSheet("Input", [["ticker", "NASDAQ:IBM"]], {"B2": "NASDAQ:IBM"}),
            _FakeSheet("Financial Statements", [["Revenue", 100]], {"C2": "NASDAQ:IBM"}),
        ]
    )

    result = ciq_refresh.validate_refreshed_workbook(workbook, expected_ticker="CALM")

    assert result.ok is False
    assert result.error_count == 1
    assert result.findings == ["ticker mismatch: expected CALM, workbook has IBM"]


def test_excel_refresh_triggers_power_query_connections_and_async_wait() -> None:
    calls: list[str] = []
    connections = [_FakeConnection(calls, "financials_input")]
    app = _FakeExcelApp(calls)
    wb = _FakeExcelBook(calls, connections)

    ciq_refresh._run_excel_power_query_refresh(app, wb)

    assert calls == [
        "Connection.Refresh:financials_input",
        "RefreshAll",
        "CalculateUntilAsyncQueriesDone",
        "calculate",
    ]


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

    monkeypatch.setattr(
        ciq_refresh,
        "refresh_workbook",
        lambda path, timeout_sec=300, **kwargs: refresh_calls.append(path) or True,
    )
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
    assert result["input_json_path"] == str(input_json_path)
    assert result["financials_input"] == {
        "ticker": "NASDAQ:CALM",
        "date_year": 2026,
        "date_month": 3,
        "date_day": 29,
        "currency": "USD",
    }
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

    monkeypatch.setattr(ciq_refresh, "refresh_workbook", lambda path, timeout_sec=300, **kwargs: True)
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

    monkeypatch.setattr(ciq_refresh, "refresh_workbook", lambda path, timeout_sec=300, **kwargs: True)
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


def test_refresh_and_ingest_single_ticker_does_not_ingest_failed_refresh(tmp_path: Path, monkeypatch) -> None:
    template_path = create_ibm_style_workbook(tmp_path / "ciq_cleandata.xlsx")
    output_folder = tmp_path / "exports"
    output_folder.mkdir()
    input_json_path = tmp_path / "financials_input.json"
    input_json_path.write_text("{}", encoding="utf-8")

    ingest_called = False
    archive_called = False

    monkeypatch.setattr(ciq_refresh, "refresh_workbook", lambda path, timeout_sec=300, **kwargs: False)

    def _ingest(*args, **kwargs):
        nonlocal ingest_called
        ingest_called = True
        return {"processed": 1, "failed": 0}

    def _archive(*args, **kwargs):
        nonlocal archive_called
        archive_called = True
        return tmp_path / "archive" / "should-not-exist.xlsx"

    monkeypatch.setattr(ciq_refresh, "ingest_ciq_folder", _ingest)
    monkeypatch.setattr(ciq_refresh, "archive_refreshed_workbook", _archive)

    result = ciq_refresh.refresh_and_ingest_single_ticker(
        ticker="CALM",
        ciq_symbol="NASDAQ:CALM",
        template_path=template_path,
        input_json_path=input_json_path,
        output_folder=output_folder,
    )

    assert ingest_called is False
    assert archive_called is False
    assert result["refreshed"] is False
    assert result["archive_path"] is None
    assert result["ingest_report"]["failed"] == 1
