"""Fama-French factor data downloader and cache manager."""

from __future__ import annotations

import io
import logging
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd

logger = logging.getLogger(__name__)

# Ken French Data Library URLs
_FF5_DAILY_URL = (
    "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"
    "F-F_Research_Data_5_Factors_2x3_daily_CSV.zip"
)
_MOM_DAILY_URL = (
    "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"
    "F-F_Momentum_Factor_daily_CSV.zip"
)

_CACHE_MAX_AGE_DAYS = 30


def _cache_path() -> Path:
    """Return path to the Parquet cache file, creating parent dirs as needed."""
    from config import DATA_DIR

    cache_dir = DATA_DIR / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / "ff_factors.parquet"


def _cache_is_fresh(path: Path) -> bool:
    """Return True if cache file exists and is younger than _CACHE_MAX_AGE_DAYS."""
    if not path.exists():
        return False
    mtime = datetime.fromtimestamp(path.stat().st_mtime)
    return datetime.now() - mtime < timedelta(days=_CACHE_MAX_AGE_DAYS)


def _download_zip_content(url: str) -> bytes | None:
    """Download a ZIP from url and return raw bytes, or None on failure."""
    try:
        import urllib.request

        with urllib.request.urlopen(url, timeout=30) as resp:
            return resp.read()
    except Exception as exc:
        logger.warning("Failed to download %s: %s", url, exc)
        return None


def _extract_first_csv(zip_bytes: bytes) -> bytes | None:
    """Extract the first CSV file from a ZIP archive and return its bytes."""
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            csv_names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
            if not csv_names:
                return None
            return zf.read(csv_names[0])
    except Exception as exc:
        logger.warning("ZIP extraction failed: %s", exc)
        return None


def _parse_ff_csv(content: bytes, date_format: str = "%Y%m%d") -> pd.DataFrame:
    """
    Parse CSV content from a Ken French Data Library ZIP file.

    Skips header rows until the first line that starts with a digit (the data
    block).  Stops at a blank line or a line whose first token is not a valid
    date.  Returns a DataFrame with a datetime index and numeric columns
    divided by 100 to convert from percent to decimal.
    """
    import pandas as pd

    text = content.decode("utf-8", errors="replace")
    lines = text.splitlines()

    data_lines: list[str] = []
    header: list[str] | None = None
    in_data = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if in_data:
                # Blank line signals the end of the data block
                break
            continue

        first_token = stripped.split(",")[0].strip()

        if not in_data:
            # Look for the column-header row that precedes the first data row
            if stripped.startswith(",") or (
                first_token and not first_token[0].isdigit()
            ):
                # Candidate header row
                header = [t.strip() for t in stripped.split(",")]
            else:
                # First token is a digit — data starts here
                in_data = True
                data_lines.append(stripped)
        else:
            if not first_token[0].isdigit():
                break
            data_lines.append(stripped)

    if not data_lines:
        return pd.DataFrame()

    # Build a tidy CSV string
    csv_text = "\n".join(data_lines)
    try:
        df = pd.read_csv(
            io.StringIO(csv_text),
            header=None,
            names=header if header else None,
        )
    except Exception as exc:
        logger.warning("CSV parse failed: %s", exc)
        return pd.DataFrame()

    # First column is the date
    date_col = df.columns[0]
    try:
        df[date_col] = pd.to_datetime(df[date_col].astype(str).str.strip(), format=date_format)
    except Exception as exc:
        logger.warning("Date parse failed: %s", exc)
        return pd.DataFrame()

    df = df.set_index(date_col)
    df.index.name = "Date"

    # Convert all factor columns from pct to decimal
    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce") / 100.0

    return df


def get_fama_french_factors(
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame | None:
    """
    Return daily Fama-French 5-factor + Momentum factor returns as a DataFrame.

    Columns: Mkt_RF, SMB, HML, RMW, CMA, Mom, RF  (all as decimal, not pct).
    Index: datetime.

    Data is cached to data/cache/ff_factors.parquet and refreshed when older
    than 30 days.  start_date / end_date are YYYY-MM-DD strings for filtering.
    Returns None on failure.
    """
    try:
        import pandas as pd

        cache = _cache_path()

        if _cache_is_fresh(cache):
            try:
                df = pd.read_parquet(cache)
                logger.debug("Loaded FF factors from cache: %s", cache)
                return _filter_dates(df, start_date, end_date)
            except Exception as exc:
                logger.warning("Cache read failed, re-downloading: %s", exc)

        # ── Download FF5 ───────────────────────────────────────────────────────
        ff5_bytes = _download_zip_content(_FF5_DAILY_URL)
        if ff5_bytes is None:
            return None
        ff5_csv = _extract_first_csv(ff5_bytes)
        if ff5_csv is None:
            return None
        ff5 = _parse_ff_csv(ff5_csv)
        if ff5.empty:
            return None

        # Standardise column names: strip whitespace, replace spaces with _
        ff5.columns = [str(c).strip().replace("-", "_").replace(" ", "_") for c in ff5.columns]
        # Rename Mkt-RF → Mkt_RF if present
        ff5 = ff5.rename(columns={"Mkt_RF": "Mkt_RF"})  # no-op but explicit

        # ── Download Momentum ──────────────────────────────────────────────────
        mom_bytes = _download_zip_content(_MOM_DAILY_URL)
        mom: "pd.DataFrame | None" = None
        if mom_bytes is not None:
            mom_csv = _extract_first_csv(mom_bytes)
            if mom_csv is not None:
                mom = _parse_ff_csv(mom_csv)
                if not mom.empty:
                    mom.columns = [str(c).strip().replace(" ", "_") for c in mom.columns]
                    # Ken French momentum CSV typically has a single column "Mom   "
                    mom_col = [c for c in mom.columns if "Mom" in c or "mom" in c or "MOM" in c]
                    if mom_col:
                        mom = mom[[mom_col[0]]].rename(columns={mom_col[0]: "Mom"})
                    else:
                        mom = None

        # ── Merge ──────────────────────────────────────────────────────────────
        if mom is not None:
            df = ff5.join(mom, how="left")
        else:
            df = ff5.copy()
            df["Mom"] = float("nan")

        # Ensure expected column names exist; rename RF column if needed
        rf_candidates = [c for c in df.columns if c.upper() == "RF"]
        if rf_candidates and rf_candidates[0] != "RF":
            df = df.rename(columns={rf_candidates[0]: "RF"})

        # Drop duplicate index entries (rare but possible near file boundaries)
        df = df[~df.index.duplicated(keep="last")]
        df = df.sort_index()

        # ── Persist cache ──────────────────────────────────────────────────────
        try:
            df.to_parquet(cache, index=True)
            logger.debug("FF factors cached to %s", cache)
        except Exception as exc:
            logger.warning("Cache write failed: %s", exc)

        return _filter_dates(df, start_date, end_date)

    except Exception as exc:
        logger.warning("get_fama_french_factors failed: %s", exc)
        return None


def _filter_dates(
    df: pd.DataFrame,
    start_date: str | None,
    end_date: str | None,
) -> pd.DataFrame:
    """Slice DataFrame by optional YYYY-MM-DD start/end bounds."""
    import pandas as pd

    if start_date:
        df = df[df.index >= pd.Timestamp(start_date)]
    if end_date:
        df = df[df.index <= pd.Timestamp(end_date)]
    return df
