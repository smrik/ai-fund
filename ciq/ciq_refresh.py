"""Capital IQ refresh + direct workbook ingestion pipeline.

This script can either:
- refresh and ingest all workbook files from the CIQ drop folder, or
- stage, refresh, and ingest a single ticker from the template workbook.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime
import json
from pathlib import Path
import shutil
import time

from ciq.ingest import ingest_ciq_folder
from config.settings import CIQ_ARCHIVE_DIR, CIQ_DROP_FOLDER, CIQ_REFRESH_TIMEOUT, CIQ_TEMPLATES_DIR, CIQ_WORKBOOK_GLOB

DEFAULT_TEMPLATE_NAME = "ciq_cleandata.xlsx"
DEFAULT_INPUT_JSON_NAME = "financials_input.json"
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


def _normalize_ticker(ticker: str) -> str:
    return ticker.strip().upper()


def _parse_as_of_date(as_of_date: str | date | None) -> date:
    if isinstance(as_of_date, date):
        return as_of_date
    if isinstance(as_of_date, str) and as_of_date.strip():
        return datetime.strptime(as_of_date.strip(), "%Y-%m-%d").date()
    return date.today()


def resolve_ciq_symbol(ticker: str, *, ciq_symbol: str | None = None, exchange: str | None = None) -> str:
    if ciq_symbol and ciq_symbol.strip():
        return ciq_symbol.strip().upper()

    normalized_ticker = _normalize_ticker(ticker)
    if ":" in normalized_ticker:
        return normalized_ticker

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
    staged_workbook = prepare_single_ticker_refresh(
        ticker=ticker,
        ciq_symbol=resolved_symbol,
        as_of_date=as_of_date,
        currency=currency,
        template_path=template_path,
        input_json_path=input_json_path,
        output_folder=folder,
    )

    refreshed = True
    if refresh:
        refreshed = refresh_workbook(staged_workbook, timeout_sec=timeout_sec)

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
        "workbook_path": str(staged_workbook),
        "archive_path": str(archived_path) if archived_path is not None else None,
        "refreshed": refreshed,
        "ingest_report": report,
    }


def refresh_workbook(path: Path, timeout_sec: int = CIQ_REFRESH_TIMEOUT) -> bool:
    """Open workbook in Excel, trigger recalc, and save."""
    try:
        import xlwings as xw
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError(
            "xlwings is not installed. Install the dashboard/CIQ environment dependencies "
            "or use --no-refresh to ingest already-saved workbooks."
        ) from exc

    app = xw.App(visible=True)
    wb = None
    try:
        wb = app.books.open(path)
        try:
            wb.api.RefreshAll()
            app.api.CalculateUntilAsyncQueriesDone()
        except Exception:
            app.calculate()

        elapsed = 0
        while elapsed < timeout_sec:
            time.sleep(2)
            elapsed += 2
            try:
                val = str(wb.sheets[0].range("A1").value or "")
            except Exception:
                val = ""
            if "#req" not in val.lower() and "getting data" not in val.lower():
                break
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
        )
        report = result["ingest_report"]
        print(f"CIQ single-ticker run complete for {result['ticker']} ({result['ciq_symbol']})")
        print(f"Workbook: {result['workbook_path']}")
        print(f"Archive: {result['archive_path'] or 'n/a'}")
        print(f"Refreshed: {result['refreshed']}")
        print(
            f"Ingest: total={getattr(report, 'total_files', 'n/a')}, "
            f"processed={getattr(report, 'processed', 'n/a')}, "
            f"skipped={getattr(report, 'skipped', 'n/a')}, "
            f"failed={getattr(report, 'failed', 'n/a')}"
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
            refresh_workbook(path)

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
