"""
Operator diagnostics — cheap, offline, deterministic health checks.

Returns a DiagnosticsPayload describing whether key runtime dependencies
are healthy, degraded, or unavailable. No LLM calls, no live market data,
no CIQ refresh.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from config import DB_PATH, DOSSIER_ROOT, OUTPUT_DIR, REPORTS_DIR, UNIVERSE_PATH
from db.schema import get_connection

Status = Literal["ok", "degraded", "unavailable"]


@dataclass
class CheckResult:
    name: str
    status: Status
    message: str


@dataclass
class DiagnosticsPayload:
    overall: Status
    checks: list[CheckResult] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "overall": self.overall,
            "checks": [
                {"name": c.name, "status": c.status, "message": c.message}
                for c in self.checks
            ],
        }


def _check_database() -> CheckResult:
    try:
        with get_connection() as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        required = {"pipeline_log", "market_data_cache"}
        missing = required - tables
        if missing:
            return CheckResult(
                "database",
                "degraded",
                f"DB reachable but missing tables: {', '.join(sorted(missing))}",
            )
        return CheckResult("database", "ok", f"Reachable at {DB_PATH}")
    except Exception as e:
        return CheckResult("database", "unavailable", str(e))


def _check_universe() -> CheckResult:
    try:
        if not UNIVERSE_PATH.exists():
            return CheckResult("universe", "unavailable", f"Not found: {UNIVERSE_PATH}")
        lines = [ln for ln in UNIVERSE_PATH.read_text().splitlines() if ln.strip()]
        ticker_count = max(0, len(lines) - 1)  # subtract header
        if ticker_count == 0:
            return CheckResult("universe", "degraded", "universe.csv exists but has no tickers")
        return CheckResult("universe", "ok", f"{ticker_count} tickers loaded")
    except Exception as e:
        return CheckResult("universe", "unavailable", str(e))


def _check_exports_writable() -> CheckResult:
    exports_dir = OUTPUT_DIR / "exports"
    try:
        exports_dir.mkdir(parents=True, exist_ok=True)
        probe = exports_dir / ".write_probe"
        probe.write_text("ok")
        probe.unlink()
        count = len(list(exports_dir.glob("*.xlsx")))
        return CheckResult("exports_dir", "ok", f"Writable; {count} workbook(s) present")
    except Exception as e:
        return CheckResult("exports_dir", "unavailable", str(e))


def _check_dossiers() -> CheckResult:
    try:
        dossier_path = Path(DOSSIER_ROOT) if not isinstance(DOSSIER_ROOT, Path) else DOSSIER_ROOT
        if not dossier_path.exists():
            return CheckResult("dossiers", "degraded", f"Dossier root not found: {dossier_path}")
        folders = [p for p in dossier_path.iterdir() if p.is_dir()]
        return CheckResult("dossiers", "ok", f"{len(folders)} dossier(s) available")
    except Exception as e:
        return CheckResult("dossiers", "unavailable", str(e))


def _check_latest_snapshot() -> CheckResult:
    valuations_dir = OUTPUT_DIR / "valuations"
    try:
        if not valuations_dir.exists():
            return CheckResult("latest_snapshot", "degraded", "Valuations dir not found — run batch_runner")
        latest = valuations_dir / "latest.csv"
        if not latest.exists():
            return CheckResult("latest_snapshot", "degraded", "latest.csv missing — run batch_runner")
        size_kb = latest.stat().st_size // 1024
        return CheckResult("latest_snapshot", "ok", f"latest.csv present ({size_kb} KB)")
    except Exception as e:
        return CheckResult("latest_snapshot", "unavailable", str(e))


def _check_reports_dir() -> CheckResult:
    try:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        probe = REPORTS_DIR / ".write_probe"
        probe.write_text("ok")
        probe.unlink()
        reports = sorted(REPORTS_DIR.glob("daily_*.md"), reverse=True)
        if reports:
            latest = reports[0].name
            return CheckResult("reports_dir", "ok", f"Writable; latest report: {latest}")
        return CheckResult("reports_dir", "ok", "Writable; no daily reports yet")
    except Exception as e:
        return CheckResult("reports_dir", "unavailable", str(e))


def run_diagnostics() -> DiagnosticsPayload:
    """Run all health checks and return a DiagnosticsPayload."""
    checks = [
        _check_database(),
        _check_universe(),
        _check_exports_writable(),
        _check_dossiers(),
        _check_latest_snapshot(),
        _check_reports_dir(),
    ]

    if any(c.status == "unavailable" for c in checks):
        overall: Status = "unavailable"
    elif any(c.status == "degraded" for c in checks):
        overall = "degraded"
    else:
        overall = "ok"

    return DiagnosticsPayload(overall=overall, checks=checks)
