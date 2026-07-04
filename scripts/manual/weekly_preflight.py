"""Read-only weekly session preflight for Alpha Pod operators."""
from __future__ import annotations

import argparse
import importlib.util
import os
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config import CIQ_DROP_FOLDER, CIQ_WORKBOOK_GLOB, DB_PATH, ROOT_DIR  # noqa: E402


# Engineering default: CIQ workbooks older than one week are stale enough to
# call out before a weekly PM session, but staleness alone should not block.
CIQ_STALE_WARN_DAYS = 7.0

# Engineering default: yfinance-backed market cache has a short runtime TTL, but
# the weekly preflight only warns when the newest cached row is over a day old.
MARKET_CACHE_STALE_WARN_DAYS = 1.0

# These git-committed CIQ template fixtures live under ciq/templates/ and must
# not count as evidence of a PM-refreshed workbook when default config falls
# back CIQ_DROP_FOLDER to the templates dir.
CIQ_COMMITTED_TEMPLATE_NAMES = frozenset({"IBM_Standard.xlsx", "ciq_cleandata.xlsx"})

# Documented local interpreter for real weekly-loop sessions on this machine.
EXPECTED_AI_FUND_PYTHON = Path(r"C:\Users\patri\miniconda3\envs\ai-fund\python.exe")

REQUIRED_PACKAGES = {
    "pytest": "pytest",
    "pandas": "pandas",
    "numpy": "numpy",
    "yfinance": "yfinance",
    "requests": "requests",
    "openpyxl": "openpyxl",
    "pyyaml": "yaml",
    "python-dotenv": "dotenv",
    "edgartools": "edgar",
}

OPTIONAL_PACKAGES = {
    "ruff": "ruff",
}


@dataclass(frozen=True)
class CheckResult:
    item: str
    status: str
    detail: str


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _age_days_from_timestamp(timestamp: float, *, now: datetime | None = None) -> float:
    current = now or _utc_now()
    modified = datetime.fromtimestamp(timestamp, tz=timezone.utc)
    return max(0.0, (current - modified).total_seconds() / 86400.0)


def _parse_datetime(value: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _sqlite_ro_uri(path: Path) -> str:
    return f"file:{path.resolve().as_posix()}?mode=ro"


def expected_schema_tables() -> tuple[str, ...]:
    """Return the current schema's expected user tables without touching disk."""
    from db.schema import create_tables

    with sqlite3.connect(":memory:") as conn:
        create_tables(conn)
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
    return tuple(row[0] for row in rows)


def _list_ciq_workbooks(folder: Path, pattern: str = CIQ_WORKBOOK_GLOB) -> list[Path]:
    if not folder.exists():
        return []
    return sorted(
        path
        for path in folder.glob(pattern)
        if path.is_file() and not path.name.startswith("~$") and path.name not in CIQ_COMMITTED_TEMPLATE_NAMES
    )


def check_interpreter(
    executable: str | Path = sys.executable,
    expected: Path = EXPECTED_AI_FUND_PYTHON,
) -> CheckResult:
    current = Path(executable)
    if os.name == "nt":
        current_text = str(current).lower()
        expected_text = str(expected).lower()
    else:
        current_text = str(current)
        expected_text = str(expected)
    if current_text == expected_text:
        return CheckResult("python", "PASS", f"using documented ai-fund interpreter: {current}")
    env_name = os.environ.get("CONDA_DEFAULT_ENV", "")
    suffix = f"; CONDA_DEFAULT_ENV={env_name}" if env_name else ""
    return CheckResult("python", "WARN", f"using {current}{suffix}; documented path is {expected}")


def check_packages(
    required: dict[str, str] = REQUIRED_PACKAGES,
    optional: dict[str, str] = OPTIONAL_PACKAGES,
) -> CheckResult:
    missing_required = [name for name, module in required.items() if importlib.util.find_spec(module) is None]
    missing_optional = [name for name, module in optional.items() if importlib.util.find_spec(module) is None]
    if missing_required:
        return CheckResult("packages", "FAIL", f"missing required imports: {', '.join(missing_required)}")
    if missing_optional:
        return CheckResult("packages", "WARN", f"required imports present; optional missing: {', '.join(missing_optional)}")
    optional_detail = f"; optional present: {', '.join(optional)}" if optional else ""
    return CheckResult("packages", "PASS", f"required imports present{optional_detail}")


def check_database(
    db_path: Path = DB_PATH,
    required_tables: Iterable[str] | None = None,
) -> CheckResult:
    path = Path(db_path)
    required_tables = tuple(required_tables) if required_tables is not None else expected_schema_tables()
    if not path.exists():
        return CheckResult("sqlite_db", "FAIL", f"missing database: {path}")
    try:
        with sqlite3.connect(_sqlite_ro_uri(path), uri=True) as conn:
            rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    except sqlite3.Error as exc:
        return CheckResult("sqlite_db", "FAIL", f"cannot read {path}: {exc}")

    existing = {row[0] for row in rows}
    missing = [table for table in required_tables if table not in existing]
    if missing:
        shown = ", ".join(missing[:8])
        suffix = f" (+{len(missing) - 8} more)" if len(missing) > 8 else ""
        return CheckResult("sqlite_db", "FAIL", f"missing schema tables: {shown}{suffix}")
    return CheckResult("sqlite_db", "PASS", f"{path} reachable; {len(existing)} tables present")


def check_ciq_workbook(
    folder: Path = CIQ_DROP_FOLDER,
    pattern: str = CIQ_WORKBOOK_GLOB,
    warn_days: float = CIQ_STALE_WARN_DAYS,
    *,
    now: datetime | None = None,
) -> CheckResult:
    folder = Path(folder)
    workbooks = _list_ciq_workbooks(folder, pattern)
    if not workbooks:
        return CheckResult("ciq_workbook", "FAIL", f"no CIQ workbook found in {folder} ({pattern})")

    newest = max(workbooks, key=lambda path: path.stat().st_mtime)
    age_days = _age_days_from_timestamp(newest.stat().st_mtime, now=now)
    detail = f"{newest.name} in {folder}; age {age_days:.1f} days"
    if age_days > warn_days:
        return CheckResult("ciq_workbook", "WARN", f"{detail}; warn threshold {warn_days:.0f} days")
    return CheckResult("ciq_workbook", "PASS", detail)


def check_market_cache(
    db_path: Path = DB_PATH,
    warn_days: float = MARKET_CACHE_STALE_WARN_DAYS,
    *,
    now: datetime | None = None,
) -> CheckResult:
    path = Path(db_path)
    if not path.exists():
        return CheckResult("market_cache", "WARN", f"database missing, cannot inspect market_data_cache: {path}")
    try:
        with sqlite3.connect(_sqlite_ro_uri(path), uri=True) as conn:
            row = conn.execute("SELECT MAX(fetched_at) FROM market_data_cache").fetchone()
    except sqlite3.Error as exc:
        return CheckResult("market_cache", "WARN", f"cannot inspect market_data_cache: {exc}")

    latest = row[0] if row else None
    if not latest:
        return CheckResult("market_cache", "WARN", "market_data_cache has no fetched_at rows")
    try:
        fetched_at = _parse_datetime(str(latest))
    except ValueError:
        return CheckResult("market_cache", "WARN", f"latest fetched_at is not parseable: {latest}")

    current = now or _utc_now()
    age_days = max(0.0, (current - fetched_at).total_seconds() / 86400.0)
    detail = f"latest fetched_at {fetched_at.isoformat()}; age {age_days:.1f} days"
    if age_days > warn_days:
        return CheckResult("market_cache", "WARN", f"{detail}; warn threshold {warn_days:.0f} day")
    return CheckResult("market_cache", "PASS", detail)


def check_fred_api_key(env: dict[str, str] | None = None) -> CheckResult:
    source = env if env is not None else os.environ
    if source.get("FRED_API_KEY"):
        return CheckResult("fred_api_key", "PASS", "FRED_API_KEY is set")
    return CheckResult("fred_api_key", "WARN", "FRED_API_KEY is not set; macro refresh may fall back or skip")


def _run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )


def check_git(repo_root: Path = ROOT_DIR) -> CheckResult:
    branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], repo_root)
    if branch.returncode != 0:
        return CheckResult("git", "FAIL", f"cannot determine branch: {branch.stderr.strip() or branch.stdout.strip()}")
    branch_name = branch.stdout.strip()

    status = _run_git(["status", "--porcelain"], repo_root)
    if status.returncode != 0:
        return CheckResult("git", "FAIL", f"cannot determine worktree status: {status.stderr.strip() or status.stdout.strip()}")
    dirty_count = len([line for line in status.stdout.splitlines() if line.strip()])

    upstream = _run_git(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"], repo_root)
    if upstream.returncode != 0:
        dirty_detail = f"{dirty_count} dirty path(s)" if dirty_count else "clean"
        return CheckResult("git", "WARN", f"branch {branch_name}; {dirty_detail}; no upstream configured")

    upstream_name = upstream.stdout.strip()
    counts = _run_git(["rev-list", "--left-right", "--count", f"HEAD...{upstream_name}"], repo_root)
    if counts.returncode != 0:
        return CheckResult("git", "WARN", f"branch {branch_name}; cannot compare with {upstream_name}")
    parts = counts.stdout.split()
    ahead, behind = (int(parts[0]), int(parts[1])) if len(parts) >= 2 else (0, 0)
    detail = f"branch {branch_name}; upstream {upstream_name}; dirty {dirty_count}; ahead {ahead}; behind {behind}"
    if dirty_count or ahead or behind:
        return CheckResult("git", "WARN", detail)
    return CheckResult("git", "PASS", detail)


def run_checks() -> list[CheckResult]:
    return [
        check_interpreter(),
        check_packages(),
        check_database(),
        check_ciq_workbook(),
        check_market_cache(),
        check_fred_api_key(),
        check_git(),
    ]


def render_table(results: list[CheckResult]) -> str:
    item_width = max([len("Item"), *(len(result.item) for result in results)])
    status_width = len("Status")
    lines = [
        f"{'Item':<{item_width}}  {'Status':<{status_width}}  Detail",
        f"{'-' * item_width}  {'-' * status_width}  {'-' * 6}",
    ]
    for result in results:
        lines.append(f"{result.item:<{item_width}}  {result.status:<{status_width}}  {result.detail}")
    return "\n".join(lines)


def exit_code(results: Iterable[CheckResult]) -> int:
    return 1 if any(result.status == "FAIL" for result in results) else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Alpha Pod weekly session preflight checks.")
    parser.parse_args(argv)
    results = run_checks()
    print(render_table(results))
    return exit_code(results)


if __name__ == "__main__":
    raise SystemExit(main())
