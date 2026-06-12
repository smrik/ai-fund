"""Capital IQ refresh + direct workbook ingestion pipeline.

This script can either:
- refresh and ingest all workbook files from the CIQ drop folder, or
- stage, refresh, and ingest a single ticker from the template workbook.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, datetime
import json
import multiprocessing as mp
from pathlib import Path
import shutil
import subprocess
import sys
import time
from queue import Empty

from ciq.ingest import ingest_ciq_folder
from config.settings import CIQ_ARCHIVE_DIR, CIQ_DROP_FOLDER, CIQ_REFRESH_TIMEOUT, CIQ_TEMPLATES_DIR, CIQ_WORKBOOK_GLOB

DEFAULT_TEMPLATE_NAME = "ciq_cleandata.xlsx"
DEFAULT_INPUT_JSON_NAME = "financials_input.json"
_CIQ_PENDING_TOKENS = (
    "#req",
    "requesting data",
    "getting data",
    "retrieving data",
    "refreshing",
    "loading",
)
_CIQ_ERROR_TOKENS = (
    "#value!",
    "#name?",
    "#n/a",
    "#ref!",
    "#num!",
    "#div/0!",
    "#null!",
)
_EXCHANGE_MAP = {
    "NMS": "NASDAQ",
    "NGM": "NASDAQ",
    "NGS": "NASDAQ",
    "NYQ": "NYSE",
    "ASE": "AMEX",
    "NASDAQGS": "NASDAQ",
    "NASDAQGM": "NASDAQ",
    "NASDAQCM": "NASDAQ",
    "NASDAQ": "NASDAQ",
    "NYSE": "NYSE",
    "AMEX": "AMEX",
}


@dataclass(slots=True)
class RefreshValidationResult:
    ok: bool
    pending_count: int = 0
    error_count: int = 0
    findings: list[str] | None = None


class CIQRefreshValidationError(RuntimeError):
    """Raised when an Excel-refreshed workbook still contains CIQ error/pending values."""


def _normalize_ticker(ticker: str) -> str:
    ticker = ticker.strip().upper()
    if ":" in ticker:
        return ticker.split(":", 1)[1].strip().upper()
    return ticker


def _parse_as_of_date(as_of_date: str | date | None) -> date:
    if isinstance(as_of_date, date):
        return as_of_date
    if isinstance(as_of_date, str) and as_of_date.strip():
        return datetime.strptime(as_of_date.strip(), "%Y-%m-%d").date()
    return date.today()


def resolve_ciq_symbol(ticker: str, *, ciq_symbol: str | None = None, exchange: str | None = None) -> str:
    if ciq_symbol and ciq_symbol.strip():
        return ciq_symbol.strip().upper()

    raw_ticker = ticker.strip().upper()
    if ":" in raw_ticker:
        return raw_ticker
    normalized_ticker = _normalize_ticker(raw_ticker)

    if exchange and exchange.strip():
        return f"{exchange.strip().upper()}:{normalized_ticker}"

    try:
        import yfinance as yf
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise ValueError(
            f"Could not infer CIQ symbol for {normalized_ticker}. Pass --ciq-symbol like NASDAQ:{normalized_ticker}."
        ) from exc

    info = yf.Ticker(normalized_ticker).info or {}
    for candidate in (info.get("exchange"), info.get("fullExchangeName"), info.get("quoteType")):
        if not candidate:
            continue
        mapped = _EXCHANGE_MAP.get(str(candidate).strip().upper())
        if mapped:
            return f"{mapped}:{normalized_ticker}"

    raise ValueError(
        f"Could not infer CIQ symbol for {normalized_ticker}. Pass --ciq-symbol like NASDAQ:{normalized_ticker}."
    )


def write_financials_input(
    input_json_path: str | Path,
    *,
    ciq_symbol: str,
    as_of_date: str | date | None = None,
    currency: str = "USD",
) -> dict[str, str | int]:
    target_date = _parse_as_of_date(as_of_date)
    payload: dict[str, str | int] = {
        "ticker": ciq_symbol,
        "date_year": target_date.year,
        "date_month": target_date.month,
        "date_day": target_date.day,
        "currency": currency,
    }
    path = Path(input_json_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=4), encoding="utf-8")
    return payload


def prepare_single_ticker_refresh(
    *,
    ticker: str,
    ciq_symbol: str,
    as_of_date: str | date | None = None,
    currency: str = "USD",
    template_path: str | Path | None = None,
    input_json_path: str | Path | None = None,
    output_folder: str | Path | None = None,
) -> Path:
    normalized_ticker = _normalize_ticker(ticker)
    template = Path(template_path or (CIQ_TEMPLATES_DIR / DEFAULT_TEMPLATE_NAME))
    input_json = Path(input_json_path or (CIQ_TEMPLATES_DIR / DEFAULT_INPUT_JSON_NAME))
    folder = Path(output_folder or CIQ_DROP_FOLDER)

    if not template.exists():
        raise FileNotFoundError(f"CIQ template workbook not found: {template}")

    write_financials_input(input_json, ciq_symbol=ciq_symbol, as_of_date=as_of_date, currency=currency)

    folder.mkdir(parents=True, exist_ok=True)
    staged_workbook = folder / f"{normalized_ticker}_Standard.xlsx"
    shutil.copy2(template, staged_workbook)
    return staged_workbook


def _report_stat(report: object, key: str) -> int:
    if isinstance(report, dict):
        value = report.get(key, 0)
    else:
        value = getattr(report, key, 0)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _failed_refresh_report(folder: Path, workbook_path: Path, error: str) -> dict:
    return {
        "as_of_date": date.today().isoformat(),
        "folder": str(folder),
        "total_files": 1,
        "processed": 0,
        "skipped": 0,
        "failed": 1,
        "results": [
            {
                "file": workbook_path.name,
                "status": "failed",
                "ticker": None,
                "run_id": None,
                "rows_parsed": 0,
                "error": error,
            }
        ],
    }


def _resolve_archive_as_of_date(workbook_path: Path, fallback: str | date | None = None) -> str:
    if fallback:
        return _parse_as_of_date(fallback).isoformat()

    try:
        from ciq.workbook_parser import parse_ciq_workbook

        payload = parse_ciq_workbook(workbook_path)
        as_of_date = payload.valuation_snapshot.get("as_of_date")
        if as_of_date:
            return str(as_of_date)
    except Exception:
        pass

    return date.today().isoformat()


def archive_refreshed_workbook(
    workbook_path: str | Path,
    *,
    ticker: str,
    as_of_date: str | date | None = None,
    archive_dir: str | Path | None = None,
) -> Path:
    source_path = Path(workbook_path)
    archive_root = Path(archive_dir or CIQ_ARCHIVE_DIR)
    archive_root.mkdir(parents=True, exist_ok=True)

    normalized_ticker = _normalize_ticker(ticker)
    archive_as_of_date = _resolve_archive_as_of_date(source_path, fallback=as_of_date)
    run_stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    archived_path = archive_root / f"{normalized_ticker}_{archive_as_of_date}_{run_stamp}.xlsx"
    shutil.copy2(source_path, archived_path)
    return archived_path


def refresh_and_ingest_single_ticker(
    *,
    ticker: str,
    ciq_symbol: str | None = None,
    exchange: str | None = None,
    as_of_date: str | date | None = None,
    currency: str = "USD",
    template_path: str | Path | None = None,
    input_json_path: str | Path | None = None,
    output_folder: str | Path | None = None,
    archive_dir: str | Path | None = None,
    refresh: bool = True,
    timeout_sec: int = CIQ_REFRESH_TIMEOUT,
) -> dict:
    resolved_symbol = resolve_ciq_symbol(ticker, ciq_symbol=ciq_symbol, exchange=exchange)
    folder = Path(output_folder or CIQ_DROP_FOLDER)
    resolved_input_json = Path(input_json_path or (CIQ_TEMPLATES_DIR / DEFAULT_INPUT_JSON_NAME))
    staged_workbook = prepare_single_ticker_refresh(
        ticker=ticker,
        ciq_symbol=resolved_symbol,
        as_of_date=as_of_date,
        currency=currency,
        template_path=template_path,
        input_json_path=resolved_input_json,
        output_folder=folder,
    )
    try:
        financials_input = json.loads(resolved_input_json.read_text(encoding="utf-8"))
    except Exception:
        financials_input = {}

    refreshed = True
    refresh_error = None
    if refresh:
        refreshed = refresh_workbook(staged_workbook, timeout_sec=timeout_sec, expected_ticker=ticker)
        if not refreshed:
            refresh_error = f"CIQ Excel refresh failed validation for {staged_workbook.name}"

    if refresh and not refreshed:
        report = _failed_refresh_report(folder, staged_workbook, refresh_error or "CIQ Excel refresh failed")
    else:
        report = ingest_ciq_folder(folder)
    archived_path: Path | None = None
    if (_report_stat(report, "processed") > 0 or _report_stat(report, "skipped") > 0) and _report_stat(report, "failed") == 0:
        archived_path = archive_refreshed_workbook(
            staged_workbook,
            ticker=ticker,
            as_of_date=as_of_date,
            archive_dir=archive_dir,
        )
    return {
        "ticker": _normalize_ticker(ticker),
        "ciq_symbol": resolved_symbol,
        "input_json_path": str(resolved_input_json),
        "financials_input": financials_input,
        "workbook_path": str(staged_workbook),
        "archive_path": str(archived_path) if archived_path is not None else None,
        "refreshed": refreshed,
        "refresh_error": refresh_error,
        "ingest_report": report,
    }


def _as_matrix(value: object) -> list[list[object]]:
    if value is None:
        return []
    if not isinstance(value, list):
        return [[value]]
    if not value:
        return []
    if any(isinstance(item, list) for item in value):
        return [item if isinstance(item, list) else [item] for item in value]
    return [value]


def _cell_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _workbook_ticker(wb: object) -> str:
    for sheet_name, cell_ref in (("Input", "B2"), ("Financial Statements", "C2")):
        try:
            value = wb.sheets[sheet_name].range(cell_ref).value
        except Exception:
            continue
        ticker = _normalize_ticker(_cell_text(value))
        if ticker:
            return ticker
    return ""


def validate_refreshed_workbook(
    wb: object,
    *,
    expected_ticker: str | None = None,
    max_findings: int = 20,
) -> RefreshValidationResult:
    pending_count = 0
    error_count = 0
    findings: list[str] = []

    if expected_ticker:
        actual_ticker = _workbook_ticker(wb)
        expected = _normalize_ticker(expected_ticker)
        if not actual_ticker:
            findings.append(f"ticker missing: expected {expected}")
            error_count += 1
        elif actual_ticker != expected:
            findings.append(f"ticker mismatch: expected {expected}, workbook has {actual_ticker}")
            error_count += 1

    for sheet in wb.sheets:
        sheet_name = getattr(sheet, "name", "")
        try:
            values = _as_matrix(sheet.used_range.value)
        except Exception as exc:
            findings.append(f"{sheet_name}: could not inspect used range: {exc}")
            error_count += 1
            continue

        for row_index, row in enumerate(values, start=1):
            for col_index, value in enumerate(row, start=1):
                text = _cell_text(value)
                if not text:
                    continue
                lower = text.lower()
                matched_pending = any(token in lower for token in _CIQ_PENDING_TOKENS)
                matched_error = any(token in lower for token in _CIQ_ERROR_TOKENS)
                if matched_pending:
                    pending_count += 1
                if matched_error:
                    error_count += 1
                if (matched_pending or matched_error) and len(findings) < max_findings:
                    findings.append(f"{sheet_name}!R{row_index}C{col_index}: {text[:120]}")

    return RefreshValidationResult(
        ok=pending_count == 0 and error_count == 0,
        pending_count=pending_count,
        error_count=error_count,
        findings=findings,
    )


def _run_excel_power_query_refresh(app: object, wb: object) -> None:
    """Trigger workbook data connections/Power Query refresh, then wait for async queries."""
    try:
        for connection in wb.api.Connections:
            try:
                connection.Refresh()
            except Exception:
                pass
    except Exception:
        pass

    try:
        wb.api.RefreshAll()
    except Exception:
        pass

    try:
        app.api.CalculateUntilAsyncQueriesDone()
    except Exception:
        pass

    try:
        app.calculate()
    except Exception:
        pass


def _refresh_workbook_in_excel(
    path: Path,
    timeout_sec: int = CIQ_REFRESH_TIMEOUT,
    *,
    expected_ticker: str | None = None,
    event_queue: object | None = None,
) -> bool:
    """Open workbook in Excel, trigger recalc, and save."""
    try:
        import xlwings as xw
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError(
            "xlwings is not installed. Install the dashboard/CIQ environment dependencies "
            "or use --no-refresh to ingest already-saved workbooks."
        ) from exc

    app = xw.App(visible=True)
    if event_queue is not None:
        try:
            event_queue.put({"type": "excel_pid", "pid": int(app.pid)})
        except Exception:
            pass
    wb = None
    try:
        wb = app.books.open(path)
        _run_excel_power_query_refresh(app, wb)

        validation = RefreshValidationResult(ok=False)
        elapsed = 0
        while elapsed < timeout_sec:
            time.sleep(2)
            elapsed += 2
            _run_excel_power_query_refresh(app, wb)
            validation = validate_refreshed_workbook(wb, expected_ticker=expected_ticker)
            if validation.ok:
                break
        if not validation.ok:
            details = "; ".join(validation.findings or [])
            raise CIQRefreshValidationError(
                f"pending={validation.pending_count}, errors={validation.error_count}"
                + (f" | {details}" if details else "")
            )
        wb.save()
        return True
    except Exception as exc:
        print(f"✗ refresh failed for {path.name}: {exc}")
        return False
    finally:
        try:
            if wb:
                wb.close()
        finally:
            app.quit()


def _refresh_workbook_worker(
    path: str,
    timeout_sec: int,
    expected_ticker: str | None,
    event_queue: object,
) -> None:
    try:
        ok = _refresh_workbook_in_excel(
            Path(path),
            timeout_sec=timeout_sec,
            expected_ticker=expected_ticker,
            event_queue=event_queue,
        )
        event_queue.put({"type": "result", "ok": bool(ok)})
    except Exception as exc:  # pragma: no cover - defensive child-process path
        event_queue.put({"type": "result", "ok": False, "error": str(exc)})


def _terminate_child_process(process: mp.Process) -> None:
    if not process.is_alive():
        return
    process.terminate()
    process.join(timeout=5)
    if process.is_alive():
        process.kill()
        process.join(timeout=5)


def _kill_excel_pid(pid: int | None) -> None:
    if not pid or sys.platform != "win32":
        return
    try:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except Exception:
        pass


def refresh_workbook(
    path: Path,
    timeout_sec: int = CIQ_REFRESH_TIMEOUT,
    *,
    expected_ticker: str | None = None,
) -> bool:
    """Run Excel refresh in a child process so hung COM/add-in calls cannot trap the CLI."""
    outer_timeout = max(int(timeout_sec) + 15, 30)
    context = mp.get_context("spawn")
    event_queue = context.Queue()
    process = context.Process(
        target=_refresh_workbook_worker,
        args=(str(Path(path)), int(timeout_sec), expected_ticker, event_queue),
    )
    process.start()

    excel_pid: int | None = None
    deadline = time.monotonic() + outer_timeout
    while time.monotonic() < deadline:
        try:
            message = event_queue.get(timeout=0.5)
        except Empty:
            if not process.is_alive():
                process.join(timeout=1)
                return process.exitcode == 0
            continue

        message_type = message.get("type")
        if message_type == "excel_pid":
            try:
                excel_pid = int(message.get("pid"))
            except (TypeError, ValueError):
                excel_pid = None
            continue
        if message_type == "result":
            process.join(timeout=5)
            if process.is_alive():
                _terminate_child_process(process)
            return bool(message.get("ok"))

    _terminate_child_process(process)
    _kill_excel_pid(excel_pid)
    print(f"✗ refresh timed out for {Path(path).name} after {outer_timeout}s")
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh CIQ workbooks and ingest parsed output")
    parser.add_argument("--ticker", type=str, help="Single ticker to stage, refresh, and ingest")
    parser.add_argument("--ciq-symbol", type=str, help="Exact CIQ symbol, e.g. NASDAQ:CALM")
    parser.add_argument("--exchange", type=str, help="Exchange prefix used to form the CIQ symbol, e.g. NYSE")
    parser.add_argument("--date", type=str, help="As-of date for financials_input.json in YYYY-MM-DD format")
    parser.add_argument("--currency", type=str, default="USD", help="Currency for financials_input.json")
    parser.add_argument(
        "--template",
        type=str,
        default=str(CIQ_TEMPLATES_DIR / DEFAULT_TEMPLATE_NAME),
        help="Template workbook used for single-ticker staging",
    )
    parser.add_argument(
        "--input-json",
        type=str,
        default=str(CIQ_TEMPLATES_DIR / DEFAULT_INPUT_JSON_NAME),
        help="financials_input.json path used for single-ticker staging",
    )
    parser.add_argument("--no-refresh", action="store_true", help="Skip Excel refresh and ingest files directly")
    parser.add_argument("--folder", type=str, default=str(CIQ_DROP_FOLDER), help="CIQ workbook drop folder")
    parser.add_argument(
        "--timeout-sec",
        type=int,
        default=CIQ_REFRESH_TIMEOUT,
        help="Maximum seconds to wait for Excel/CIQ formulas to validate",
    )
    args = parser.parse_args()

    if args.ticker:
        result = refresh_and_ingest_single_ticker(
            ticker=args.ticker,
            ciq_symbol=args.ciq_symbol,
            exchange=args.exchange,
            as_of_date=args.date,
            currency=args.currency,
            template_path=args.template,
            input_json_path=args.input_json,
            output_folder=args.folder,
            refresh=not args.no_refresh,
            timeout_sec=args.timeout_sec,
        )
        report = result["ingest_report"]
        print(f"CIQ single-ticker run complete for {result['ticker']} ({result['ciq_symbol']})")
        print(f"Workbook: {result['workbook_path']}")
        print(f"Archive: {result['archive_path'] or 'n/a'}")
        print(f"Refreshed: {result['refreshed']}")
        print(
            f"Ingest: total={_report_stat(report, 'total_files')}, "
            f"processed={_report_stat(report, 'processed')}, "
            f"skipped={_report_stat(report, 'skipped')}, "
            f"failed={_report_stat(report, 'failed')}"
        )
        return

    folder = Path(args.folder)
    files = sorted(folder.glob(CIQ_WORKBOOK_GLOB)) if folder.exists() else []
    if not files:
        print(f"No CIQ workbooks found in {folder} ({CIQ_WORKBOOK_GLOB}).")
        return

    if not args.no_refresh:
        print(f"Refreshing {len(files)} workbook(s) in Excel...")
        for path in files:
            print(f"  -> {path.name}")
            refresh_workbook(path, timeout_sec=args.timeout_sec)

    print("Running deterministic CIQ ingestion...")
    report = ingest_ciq_folder(folder)
    print(
        f"CIQ ingest complete: total={report.total_files}, "
        f"processed={report.processed}, skipped={report.skipped}, failed={report.failed}"
    )
    for result in report.results:
        line = f"  {result.file}: {result.status}"
        if result.ticker:
            line += f" ({result.ticker})"
        if result.error:
            line += f" | {result.error}"
        print(line)


if __name__ == "__main__":
    main()
