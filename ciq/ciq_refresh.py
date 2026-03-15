"""Capital IQ refresh + direct workbook ingestion pipeline.

This script optionally refreshes workbooks via Excel/CIQ add-in and then ingests
all workbook files from the CIQ drop folder using the deterministic parser.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from config.settings import CIQ_DROP_FOLDER, CIQ_REFRESH_TIMEOUT, CIQ_WORKBOOK_GLOB
from ciq.ingest import ingest_ciq_folder



def refresh_workbook(path: Path, timeout_sec: int = CIQ_REFRESH_TIMEOUT) -> bool:
    """Open workbook in Excel, trigger recalc, and save."""
    try:
        import xlwings as xw
    except ImportError as exc:
        raise RuntimeError(
            "xlwings is not installed. Install the dashboard/CIQ environment dependencies "
            "or use --no-refresh to ingest already-saved workbooks."
        ) from exc

    app = xw.App(visible=True)
    wb = None
    try:
        wb = app.books.open(path)
        app.calculate()
        elapsed = 0
        while elapsed < timeout_sec:
            time.sleep(2)
            elapsed += 2
            # Best-effort poll on active workbook status.
            # If formulas are still resolving, CIQ often surfaces #REQ.
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


def main():
    parser = argparse.ArgumentParser(description="Refresh CIQ workbooks and ingest parsed output")
    parser.add_argument("--no-refresh", action="store_true", help="Skip Excel refresh and ingest files directly")
    parser.add_argument("--folder", type=str, default=str(CIQ_DROP_FOLDER), help="CIQ workbook drop folder")
    args = parser.parse_args()

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
