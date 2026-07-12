"""Recalculate one workbook in a strictly isolated native Excel process.

This helper is intentionally conservative.  It never attaches through the
Running Object Table or ``GetActiveObject``.  Instead it:

1. snapshots all existing EXCEL.EXE processes;
2. starts ``EXCEL.EXE /safe /x /automation`` and records that exact PID;
3. delegates COM work to a watchdog-controlled child process;
4. binds through an ``EXCEL7`` window owned by that exact PID;
5. opens exactly one requested workbook, runs ``CalculateFull``, saves, and
   closes it; and
6. verifies that every Excel process present before the run still has the
   same PID and creation time.

On a timeout or any ambiguity the helper fails closed and terminates only the
new Excel PID, after re-validating its executable path and creation time.

Examples
--------
Dry-run (does not launch Excel)::

    python scripts/manual/recalculate_excel_isolated.py model.xlsx --dry-run

Native recalculation::

    python scripts/manual/recalculate_excel_isolated.py model.xlsx
"""

from __future__ import annotations

import argparse
import ctypes
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


EXCEL_WINDOW_CLASS = "XLMAIN"
EXCEL_NATIVE_OBJECT_CLASS = "EXCEL7"
EXCEL_PROCESS_NAME = "excel.exe"
SUPPORTED_WORKBOOK_SUFFIXES = frozenset({".xlsx", ".xlsm", ".xlsb", ".xls"})
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
XL_CELL_TYPE_FORMULAS = -4123
FORMULA_ERROR_TOKENS = frozenset(
    {
        "#BLOCKED!",
        "#CALC!",
        "#DIV/0!",
        "#FIELD!",
        "#GETTING_DATA",
        "#N/A",
        "#NAME?",
        "#NULL!",
        "#NUM!",
        "#REF!",
        "#SPILL!",
        "#UNKNOWN!",
        "#VALUE!",
    }
)


# These are exact values after punctuation/whitespace normalization.  A vague
# substring match would risk interacting with an unrelated Excel dialog.
DEFAULT_FILE_TYPES_TITLES = frozenset(
    {
        "default file types",
        "microsoft excel default file types",
        "default file types microsoft excel",
    }
)
SAFE_DISMISS_BUTTON_TEXT = (
    "ask me later",
    "do not make changes",
    "dont make changes",
    "cancel",
    "no",
)
RECOVERED_FILES_NOTICE_TEXT = (
    "excel has detected that you have recovered files these files will be opened "
    "the next time you start excel in normal mode"
)

WM_CLOSE = 0x0010
WM_GETOBJECT = 0x003D
BM_CLICK = 0x00F5
OBJID_NATIVEOM = -16
SMTO_BLOCK = 0x0001
SMTO_ABORTIFHUNG = 0x0002

XL_CALCULATION_MANUAL = -4135
XL_CALCULATION_DONE = 0
MSO_AUTOMATION_SECURITY_FORCE_DISABLE = 3


class ExcelIsolationError(RuntimeError):
    """Base error for a closed-safe isolated Excel run."""


class ExcelSafetyError(ExcelIsolationError):
    """Raised when process or window ownership is ambiguous."""


class ExcelTimeoutError(ExcelIsolationError):
    """Raised when startup or recalculation exceeds its deadline."""


@dataclass(frozen=True)
class ProcessIdentity:
    """The minimum process identity needed to defend against PID reuse."""

    pid: int
    create_time: float
    executable: str

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ProcessIdentity":
        return cls(
            pid=int(payload["pid"]),
            create_time=float(payload["create_time"]),
            executable=str(payload["executable"]),
        )


@dataclass(frozen=True)
class WindowRecord:
    hwnd: int
    pid: int
    class_name: str
    title: str
    visible: bool = False


@dataclass(frozen=True)
class ModalAction:
    kind: str
    hwnd: int


@dataclass(frozen=True)
class StartupWorkbookRecord:
    name: str
    full_name: str
    path: str
    worksheet_count: int


@dataclass(frozen=True)
class FormulaCellEvidence:
    sheet: str
    cell: str
    formula_text: str
    cache_populated: bool
    formula_error: str | None = None


def _validate_sha256(value: str, field_name: str) -> str:
    cleaned = str(value).strip().lower()
    if not SHA256_RE.fullmatch(cleaned):
        raise ExcelSafetyError(f"{field_name} must be a lowercase SHA-256 digest")
    return cleaned


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_formula_rows(
    records: Iterable[FormulaCellEvidence],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    identities: set[tuple[str, str]] = set()
    for record in records:
        sheet = str(record.sheet).strip()
        cell = str(record.cell).replace("$", "").strip().upper()
        formula_text = str(record.formula_text)
        if not sheet or not cell or not formula_text:
            raise ExcelSafetyError("formula evidence requires sheet, cell, and formula text")
        identity = (sheet, cell)
        if identity in identities:
            raise ExcelSafetyError(f"duplicate formula evidence cell: {sheet}!{cell}")
        identities.add(identity)
        rows.append(
            {
                "sheet": sheet,
                "cell": cell,
                "formula_text": formula_text,
            }
        )
    return sorted(rows, key=lambda item: (item["sheet"], item["cell"]))


def formula_text_hash(records: Iterable[FormulaCellEvidence]) -> str:
    rows = _canonical_formula_rows(records)
    encoded = json.dumps(
        rows,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_calculation_verification_evidence(
    *,
    workbook_sha256: str,
    model_input_hash: str | None,
    workbook_model_input_hash: str | None,
    expected_formula_text_hash: str | None,
    before: Iterable[FormulaCellEvidence],
    after: Iterable[FormulaCellEvidence],
    engine: str,
    engine_version: str,
    verified_at: datetime | None = None,
) -> dict[str, Any]:
    """Build contract-shaped evidence without inferring verification from cells."""

    workbook_hash = _validate_sha256(workbook_sha256, "workbook_sha256")
    input_hash = (
        _validate_sha256(model_input_hash, "model_input_hash")
        if model_input_hash is not None
        else None
    )
    workbook_input_hash = (
        _validate_sha256(workbook_model_input_hash, "workbook_model_input_hash")
        if workbook_model_input_hash is not None
        else None
    )
    renderer_formula_hash = (
        _validate_sha256(expected_formula_text_hash, "expected_formula_text_hash")
        if expected_formula_text_hash is not None
        else None
    )
    before_records = tuple(before)
    after_records = tuple(after)
    precalculation_hash = formula_text_hash(before_records)
    observed_hash = formula_text_hash(after_records)
    formula_expectation_bound = renderer_formula_hash is not None
    expected_hash = renderer_formula_hash or precalculation_hash
    formula_count = len(after_records)
    cached_formula_count = sum(item.cache_populated for item in after_records)
    formula_errors = tuple(
        sorted(
            f"{item.sheet}!{item.cell}:{item.formula_error}"
            for item in after_records
            if item.formula_error is not None
        )
    )
    parity_status = (
        "pass"
        if len({expected_hash, precalculation_hash, observed_hash}) == 1
        else "fail"
    )
    model_input_parity = (
        "pass" if input_hash == workbook_input_hash else "fail"
    ) if input_hash is not None else None
    cache_status = (
        "pass"
        if formula_count > 0 and cached_formula_count == formula_count
        else "fail"
    )
    error_status = "pass" if not formula_errors else "fail"

    if "fail" in {
        parity_status,
        cache_status,
        error_status,
        model_input_parity,
    }:
        verification_state = "BLOCKED"
    elif (
        input_hash is None
        or workbook_input_hash is None
        or not formula_expectation_bound
    ):
        verification_state = "UNVERIFIED"
    else:
        verification_state = "FULL"

    timestamp = verified_at or datetime.now(timezone.utc)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ExcelSafetyError("verified_at must be timezone-aware")
    verified_at_text = (
        timestamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    )
    payload: dict[str, Any] = {
        "contract_version": "1.0.0",
        "workbook_sha256": workbook_hash,
        "model_input_hash": input_hash,
        "workbook_model_input_hash": workbook_input_hash,
        "model_input_hash_parity": model_input_parity,
        "formula_text_hash": observed_hash,
        "precalculation_formula_text_hash": precalculation_hash,
        "formula_text_expectation_bound": formula_expectation_bound,
        "expected_formula_text_hash": expected_hash,
        "formula_text_parity": parity_status,
        "formula_count": formula_count,
        "cached_formula_count": cached_formula_count,
        "cache_population": cache_status,
        "formula_error_count": len(formula_errors),
        "formula_error_scan": error_status,
        "formula_errors": list(formula_errors),
        "engine": str(engine).strip(),
        "engine_version": str(engine_version).strip(),
        "calculation_completed": True,
        "verified_at": verified_at_text,
        "verification_state": verification_state,
    }
    if not payload["engine"] or not payload["engine_version"]:
        raise ExcelSafetyError("calculation engine and version are required")
    payload["verification_hash"] = hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    return payload


def build_verification_sidecar(result: Mapping[str, Any]) -> dict[str, Any]:
    evidence = result.get("calculation_verification")
    isolation_pass = (
        result.get("status") == "ok"
        and result.get("saved") is True
        and result.get("preexisting_excel_pids_untouched") is True
        and not result.get("timeout")
        and not result.get("cleanup_issues")
        and not result.get("preexisting_process_issues")
    )
    reported_evidence_state = (
        str(evidence.get("verification_state")).strip().upper()
        if isinstance(evidence, Mapping)
        else "UNVERIFIED"
    )
    evidence_state = (
        reported_evidence_state
        if reported_evidence_state
        in {"UNVERIFIED", "BLOCKED", "NEEDS_PM_REVIEW", "PARTIAL", "FULL"}
        else "UNVERIFIED"
    )
    authoritative = isolation_pass and evidence_state == "FULL"
    release_state = evidence_state if isolation_pass else "BLOCKED"
    payload: dict[str, Any] = {
        "schema_version": "isolated_excel_verification_v1",
        "status": result.get("status"),
        "workbook": result.get("workbook"),
        "authoritative": authoritative,
        "release_state": release_state,
        "authoritative_scope": "calculation_verification_only",
        "calculation_verification_state": release_state,
        "package_release_state": "UNVERIFIED",
        "calculation_verification": evidence,
        "isolation": {
            "owned_excel_pid": result.get("owned_excel_pid"),
            "preexisting_excel_pids": result.get("preexisting_excel_pids", []),
            "preexisting_excel_pids_untouched": result.get(
                "preexisting_excel_pids_untouched",
                False,
            ),
            "timeout": result.get("timeout", False),
            "cleanup_terminated_owned_pid": result.get(
                "cleanup_terminated_owned_pid",
                False,
            ),
            "cleanup_issues": result.get("cleanup_issues", []),
            "preexisting_process_issues": result.get(
                "preexisting_process_issues",
                [],
            ),
        },
    }
    payload["sidecar_hash"] = hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    return payload


def is_disposable_startup_workbook(record: StartupWorkbookRecord) -> bool:
    """Allow only Excel's pathless, default-named startup workbook."""

    return (
        record.path == ""
        and record.full_name == record.name
        and re.fullmatch(r"Book[1-9][0-9]*", record.name) is not None
        and record.worksheet_count >= 1
    )


def _normal_path(path: str | os.PathLike[str]) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def _same_process_identity(left: ProcessIdentity, right: ProcessIdentity) -> bool:
    return (
        left.pid == right.pid
        and abs(left.create_time - right.create_time) < 0.01
        and _normal_path(left.executable) == _normal_path(right.executable)
    )


def normalize_window_text(value: str) -> str:
    """Normalize dialog text without broadening the accepted title set."""

    value = value.replace("&", "")
    value = value.replace("’", "'")
    value = value.replace("'", "")
    value = re.sub(r"[^a-z0-9]+", " ", value.casefold())
    return " ".join(value.split())


def build_excel_command(excel_path: Path) -> list[str]:
    """Return the only permitted command line for the isolated instance."""

    return [str(excel_path), "/safe", "/x", "/automation"]


def validate_excel_executable(path: str | os.PathLike[str]) -> Path:
    candidate = Path(path).expanduser().resolve(strict=True)
    if not candidate.is_file() or candidate.name.casefold() != EXCEL_PROCESS_NAME:
        raise ExcelSafetyError(f"Not an EXCEL.EXE executable: {candidate}")
    return candidate


def validate_workbook_path(path: str | os.PathLike[str]) -> Path:
    workbook = Path(path).expanduser().resolve(strict=True)
    if not workbook.is_file():
        raise ExcelSafetyError(f"Workbook is not a file: {workbook}")
    if workbook.suffix.casefold() not in SUPPORTED_WORKBOOK_SUFFIXES:
        raise ExcelSafetyError(
            f"Unsupported workbook extension {workbook.suffix!r}; expected one of "
            f"{sorted(SUPPORTED_WORKBOOK_SUFFIXES)}"
        )
    return workbook
def validate_verification_output_path(
    path: str | os.PathLike[str],
    *,
    workbook_path: Path,
) -> Path:
    candidate = Path(path).expanduser().resolve(strict=False)
    if _normal_path(candidate) == _normal_path(workbook_path):
        raise ExcelSafetyError("verification output cannot overwrite the workbook")
    if candidate.suffix.casefold() != ".json":
        raise ExcelSafetyError("verification output must use a .json extension")
    if not candidate.parent.is_dir():
        raise ExcelSafetyError(
            f"verification output directory does not exist: {candidate.parent}"
        )
    return candidate




def discover_excel_executable(explicit_path: str | None = None) -> Path:
    if explicit_path:
        return validate_excel_executable(explicit_path)

    candidates: list[Path] = []
    try:
        import winreg

        registry_locations = (
            (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_64KEY),
            (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_32KEY),
            (winreg.HKEY_CURRENT_USER, 0),
        )
        for hive, view_flag in registry_locations:
            try:
                with winreg.OpenKey(
                    hive,
                    r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\excel.exe",
                    0,
                    winreg.KEY_READ | view_flag,
                ) as key:
                    candidates.append(Path(winreg.QueryValueEx(key, None)[0]))
            except OSError:
                continue
    except ImportError:
        pass

    for environment_name in ("ProgramFiles", "ProgramFiles(x86)"):
        base = os.environ.get(environment_name)
        if base:
            candidates.extend(
                [
                    Path(base) / "Microsoft Office" / "root" / "Office16" / "EXCEL.EXE",
                    Path(base) / "Microsoft Office" / "Office16" / "EXCEL.EXE",
                ]
            )

    for candidate in candidates:
        try:
            return validate_excel_executable(candidate)
        except (FileNotFoundError, ExcelSafetyError):
            continue
    raise ExcelIsolationError(
        "Could not locate EXCEL.EXE. Pass --excel-path with the exact executable."
    )


def _psutil() -> Any:
    try:
        import psutil
    except ImportError as exc:  # pragma: no cover - environment error
        raise ExcelIsolationError("psutil is required for safe PID ownership checks") from exc
    return psutil


def snapshot_excel_processes(psutil_module: Any | None = None) -> dict[int, ProcessIdentity]:
    psutil_module = psutil_module or _psutil()
    snapshot: dict[int, ProcessIdentity] = {}
    for process in psutil_module.process_iter(["pid", "name", "exe", "create_time"]):
        try:
            info = process.info
            executable = str(info.get("exe") or "")
            name = str(info.get("name") or Path(executable).name)
            if name.casefold() != EXCEL_PROCESS_NAME:
                continue
            if not executable:
                executable = str(process.exe())
            identity = ProcessIdentity(
                pid=int(info["pid"]),
                create_time=float(info.get("create_time") or process.create_time()),
                executable=executable,
            )
            snapshot[identity.pid] = identity
        except (
            psutil_module.AccessDenied,
            psutil_module.NoSuchProcess,
            psutil_module.ZombieProcess,
        ):
            continue
    return snapshot


def read_process_identity(
    pid: int,
    *,
    psutil_module: Any | None = None,
    retry_seconds: float = 0.0,
) -> ProcessIdentity | None:
    psutil_module = psutil_module or _psutil()
    deadline = time.monotonic() + max(0.0, retry_seconds)
    while True:
        try:
            process = psutil_module.Process(pid)
            executable = str(process.exe())
            name = str(process.name())
            if name.casefold() != EXCEL_PROCESS_NAME:
                raise ExcelSafetyError(f"PID {pid} is {name!r}, not EXCEL.EXE")
            return ProcessIdentity(
                pid=pid,
                create_time=float(process.create_time()),
                executable=executable,
            )
        except psutil_module.NoSuchProcess:
            if time.monotonic() >= deadline:
                return None
        except psutil_module.AccessDenied as exc:
            raise ExcelSafetyError(f"Cannot validate ownership of Excel PID {pid}") from exc
        if time.monotonic() >= deadline:
            return None
        time.sleep(0.05)


def validate_new_excel_identity(
    identity: ProcessIdentity,
    *,
    preexisting: Mapping[int, ProcessIdentity],
    expected_executable: Path,
) -> None:
    if identity.pid in preexisting:
        raise ExcelSafetyError(f"Refusing to claim pre-existing Excel PID {identity.pid}")
    if Path(identity.executable).name.casefold() != EXCEL_PROCESS_NAME:
        raise ExcelSafetyError(f"Owned PID {identity.pid} is not EXCEL.EXE")
    if _normal_path(identity.executable) != _normal_path(expected_executable):
        raise ExcelSafetyError(
            f"Owned PID {identity.pid} executable mismatch: {identity.executable!r}"
        )


def validate_termination_target(
    expected: ProcessIdentity,
    current: ProcessIdentity,
    *,
    preexisting_pids: Iterable[int],
) -> None:
    """Pure safety guard shared by normal cleanup and timeout cleanup."""

    if expected.pid in set(preexisting_pids):
        raise ExcelSafetyError(f"Refusing to terminate pre-existing PID {expected.pid}")
    if not _same_process_identity(expected, current):
        raise ExcelSafetyError(
            f"Refusing to terminate PID {expected.pid}: process identity changed"
        )
    if Path(current.executable).name.casefold() != EXCEL_PROCESS_NAME:
        raise ExcelSafetyError(f"Refusing to terminate non-Excel PID {current.pid}")


def terminate_owned_excel(
    expected: ProcessIdentity,
    *,
    preexisting_pids: Iterable[int],
    grace_seconds: float = 3.0,
    psutil_module: Any | None = None,
) -> bool:
    """Terminate, then if necessary kill, only the re-validated owned PID."""

    psutil_module = psutil_module or _psutil()
    current = read_process_identity(expected.pid, psutil_module=psutil_module)
    if current is None:
        return False
    validate_termination_target(expected, current, preexisting_pids=preexisting_pids)
    process = psutil_module.Process(expected.pid)
    process.terminate()
    try:
        process.wait(timeout=grace_seconds)
        return True
    except psutil_module.TimeoutExpired:
        current = read_process_identity(expected.pid, psutil_module=psutil_module)
        if current is None:
            return True
        validate_termination_target(expected, current, preexisting_pids=preexisting_pids)
        process = psutil_module.Process(expected.pid)
        process.kill()
        process.wait(timeout=grace_seconds)
        return True
    except psutil_module.NoSuchProcess:
        return True


def preexisting_process_issues(
    before: Mapping[int, ProcessIdentity],
    after: Mapping[int, ProcessIdentity],
) -> list[str]:
    issues: list[str] = []
    for pid, expected in sorted(before.items()):
        current = after.get(pid)
        if current is None:
            issues.append(f"pre-existing Excel PID {pid} is no longer present")
        elif not _same_process_identity(expected, current):
            issues.append(f"pre-existing Excel PID {pid} changed identity")
    return issues


def is_default_file_types_modal(
    window: WindowRecord,
    owned_pid: int,
    children: Sequence[WindowRecord] = (),
) -> bool:
    if window.pid != owned_pid:
        return False
    normalized_title = normalize_window_text(window.title)
    if normalized_title in DEFAULT_FILE_TYPES_TITLES:
        return True
    if window.class_name != "#32770" or normalized_title != "microsoft excel":
        return False
    child_text = {normalize_window_text(item.title) for item in children}
    return bool(child_text & DEFAULT_FILE_TYPES_TITLES)


def is_recovered_files_notice(
    window: WindowRecord,
    owned_pid: int,
    children: Sequence[WindowRecord] = (),
) -> bool:
    if (
        window.pid != owned_pid
        or window.class_name != "#32770"
        or normalize_window_text(window.title) != "microsoft excel"
    ):
        return False
    return RECOVERED_FILES_NOTICE_TEXT in {
        normalize_window_text(item.title) for item in children
    }


def select_recovered_files_ok_button(
    modal: WindowRecord,
    children: Sequence[WindowRecord],
    *,
    owned_pid: int,
) -> ModalAction | None:
    if not is_recovered_files_notice(modal, owned_pid, children):
        return None
    for child in children:
        if (
            child.pid == owned_pid
            and child.class_name.casefold() == "button"
            and normalize_window_text(child.title) == "ok"
        ):
            return ModalAction(kind="button", hwnd=child.hwnd)
    return None


def select_safe_modal_button(
    modal: WindowRecord,
    children: Sequence[WindowRecord],
    *,
    owned_pid: int,
) -> ModalAction | None:
    """Choose only an explicitly non-committing button on the exact modal."""

    if not is_default_file_types_modal(modal, owned_pid, children):
        return None
    candidates: dict[str, WindowRecord] = {}
    for child in children:
        if child.pid != owned_pid or child.class_name.casefold() != "button":
            continue
        candidates.setdefault(normalize_window_text(child.title), child)
    for safe_text in SAFE_DISMISS_BUTTON_TEXT:
        candidate = candidates.get(safe_text)
        if candidate:
            return ModalAction(kind="button", hwnd=candidate.hwnd)
    return None


def select_owned_excel_windows(
    top_level: Sequence[WindowRecord],
    descendants: Mapping[int, Sequence[WindowRecord]],
    *,
    owned_pid: int,
) -> tuple[WindowRecord, tuple[WindowRecord, ...]] | None:
    """Return one unambiguous XLMAIN and its PID-matched EXCEL7 children."""

    mains = [
        item
        for item in top_level
        if item.pid == owned_pid and item.class_name == EXCEL_WINDOW_CLASS
    ]
    candidates: list[tuple[WindowRecord, tuple[WindowRecord, ...]]] = []
    for main in mains:
        excel7 = tuple(
            item
            for item in descendants.get(main.hwnd, ())
            if item.pid == owned_pid and item.class_name == EXCEL_NATIVE_OBJECT_CLASS
        )
        if excel7:
            candidates.append((main, excel7))
    if len(candidates) > 1:
        details = ", ".join(
            f"XLMAIN={main.hwnd} EXCEL7={[item.hwnd for item in excel7]}"
            for main, excel7 in candidates
        )
        raise ExcelSafetyError(
            f"Owned Excel PID {owned_pid} exposed multiple EXCEL7-bearing XLMAIN windows: "
            f"{details}"
        )
    if not candidates:
        return None
    return candidates[0]


def _window_record(hwnd: int) -> WindowRecord:
    import win32gui
    import win32process

    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    return WindowRecord(
        hwnd=int(hwnd),
        pid=int(pid),
        class_name=str(win32gui.GetClassName(hwnd)),
        title=str(win32gui.GetWindowText(hwnd)),
        visible=bool(win32gui.IsWindowVisible(hwnd)),
    )


def _enumerate_top_level_windows() -> list[WindowRecord]:
    import win32gui

    windows: list[WindowRecord] = []

    def collect(hwnd: int, _: Any) -> bool:
        try:
            windows.append(_window_record(hwnd))
        except Exception:
            pass
        return True

    win32gui.EnumWindows(collect, None)
    return windows


def _enumerate_descendant_windows(parent_hwnd: int) -> list[WindowRecord]:
    import win32gui

    windows: list[WindowRecord] = []

    def collect(hwnd: int, _: Any) -> bool:
        try:
            windows.append(_window_record(hwnd))
        except Exception:
            pass
        return True

    win32gui.EnumChildWindows(parent_hwnd, collect, None)
    return windows


def _dismiss_owned_safe_startup_modals(owned_pid: int) -> list[str]:
    """Dismiss only exact, allowlisted startup notices from ``owned_pid``."""

    import win32gui

    dismissed: list[str] = []
    for modal in _enumerate_top_level_windows():
        children = _enumerate_descendant_windows(modal.hwnd)
        is_default_types = is_default_file_types_modal(modal, owned_pid, children)
        is_recovery_notice = is_recovered_files_notice(modal, owned_pid, children)
        if not is_default_types and not is_recovery_notice:
            continue
        modal_kind = "default_file_types" if is_default_types else "recovered_files_notice"

        # WM_CLOSE is non-committing and is always attempted before a button.
        win32gui.PostMessage(modal.hwnd, WM_CLOSE, 0, 0)
        time.sleep(0.15)
        if not win32gui.IsWindow(modal.hwnd):
            dismissed.append(modal_kind)
            continue

        if is_default_types:
            action = select_safe_modal_button(modal, children, owned_pid=owned_pid)
        else:
            action = select_recovered_files_ok_button(
                modal,
                children,
                owned_pid=owned_pid,
            )
        if action is not None:
            win32gui.PostMessage(action.hwnd, BM_CLICK, 0, 0)
            time.sleep(0.15)
            if not win32gui.IsWindow(modal.hwnd):
                dismissed.append(modal_kind)
    return dismissed

def _wait_for_owned_excel_windows(
    owned: ProcessIdentity,
    *,
    startup_timeout_seconds: float,
) -> tuple[WindowRecord, tuple[WindowRecord, ...], tuple[str, ...]]:
    deadline = time.monotonic() + startup_timeout_seconds
    dismissed: list[str] = []
    while time.monotonic() < deadline:
        current = read_process_identity(owned.pid)
        if current is None:
            raise ExcelIsolationError(f"Owned Excel PID {owned.pid} exited during startup")
        if not _same_process_identity(owned, current):
            raise ExcelSafetyError(f"Owned Excel PID {owned.pid} changed identity")

        dismissed.extend(_dismiss_owned_safe_startup_modals(owned.pid))
        top_level = _enumerate_top_level_windows()
        descendants = {
            main.hwnd: _enumerate_descendant_windows(main.hwnd)
            for main in top_level
            if main.pid == owned.pid and main.class_name == EXCEL_WINDOW_CLASS
        }
        selected = select_owned_excel_windows(
            top_level,
            descendants,
            owned_pid=owned.pid,
        )
        if selected is not None:
            return selected[0], selected[1], tuple(dismissed)
        time.sleep(0.20)
    remaining_windows = [
        item for item in _enumerate_top_level_windows() if item.pid == owned.pid
    ]
    details = [
        {
            "hwnd": item.hwnd,
            "class": item.class_name,
            "title": item.title,
            "visible": item.visible,
            "titled_children": [
                {"class": child.class_name, "title": child.title}
                for child in _enumerate_descendant_windows(item.hwnd)
                if child.title
            ]
            if item.class_name == "#32770"
            else [],
        }
        for item in remaining_windows
    ]
    raise ExcelTimeoutError(
        f"Timed out waiting for an EXCEL7 window from owned PID {owned.pid}; "
        f"owned top-level windows={details}"
    )


def _pid_for_hwnd(hwnd: int) -> int:
    import win32process

    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    return int(pid)


def _native_object_from_excel7(hwnd: int) -> Any:
    """Get Excel's native object through WM_GETOBJECT for one EXCEL7 HWND."""

    import pythoncom
    import win32com.client

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    result = ctypes.c_size_t()
    send_message_timeout = user32.SendMessageTimeoutW
    send_message_timeout.argtypes = (
        ctypes.c_void_p,
        ctypes.c_uint,
        ctypes.c_size_t,
        ctypes.c_ssize_t,
        ctypes.c_uint,
        ctypes.c_uint,
        ctypes.POINTER(ctypes.c_size_t),
    )
    send_message_timeout.restype = ctypes.c_void_p
    ok = send_message_timeout(
        ctypes.c_void_p(hwnd),
        WM_GETOBJECT,
        0,
        OBJID_NATIVEOM,
        SMTO_BLOCK | SMTO_ABORTIFHUNG,
        2_000,
        ctypes.byref(result),
    )
    if not ok:
        raise ExcelTimeoutError(f"WM_GETOBJECT timed out for EXCEL7 HWND {hwnd}")
    dispatch = pythoncom.ObjectFromLresult(result.value, pythoncom.IID_IDispatch, 0)
    return win32com.client.Dispatch(dispatch)


def _bind_owned_application(
    owned: ProcessIdentity,
    *,
    startup_timeout_seconds: float,
) -> tuple[Any, int, int, tuple[str, ...]]:
    main, excel7_windows, dismissed = _wait_for_owned_excel_windows(
        owned,
        startup_timeout_seconds=startup_timeout_seconds,
    )
    errors: list[str] = []
    for excel7 in excel7_windows:
        try:
            if _pid_for_hwnd(excel7.hwnd) != owned.pid:
                raise ExcelSafetyError("EXCEL7 PID changed before COM binding")
            native_object = _native_object_from_excel7(excel7.hwnd)
            application = native_object.Application
            application_hwnd = int(application.Hwnd)
            if application_hwnd != main.hwnd:
                raise ExcelSafetyError(
                    f"COM application HWND {application_hwnd} did not match XLMAIN {main.hwnd}"
                )
            if _pid_for_hwnd(application_hwnd) != owned.pid:
                raise ExcelSafetyError("COM application belongs to a different PID")
            if _pid_for_hwnd(excel7.hwnd) != owned.pid:
                raise ExcelSafetyError("EXCEL7 window belongs to a different PID")
            return application, main.hwnd, excel7.hwnd, dismissed
        except Exception as exc:
            errors.append(f"HWND {excel7.hwnd}: {type(exc).__name__}: {exc}")
    raise ExcelSafetyError(
        "Could not bind the owned Excel application through its EXCEL7 window: "
        + "; ".join(errors)
    )


def _same_workbook_path(left: str | os.PathLike[str], right: str | os.PathLike[str]) -> bool:
    return _normal_path(left) == _normal_path(right)


def _excel_hresult(error: Exception) -> int | None:
    # pywin32 sometimes wraps Excel's SCODE in DISP_E_EXCEPTION; prefer the
    # nested EXCEPINFO code when it is present.
    if len(error.args) >= 3 and isinstance(error.args[2], tuple):
        for value in reversed(error.args[2]):
            if isinstance(value, int) and value != 0:
                return int(value) & 0xFFFFFFFF
    value = getattr(error, "hresult", None)
    if value is None and error.args and isinstance(error.args[0], int):
        value = error.args[0]
    return None if value is None else int(value) & 0xFFFFFFFF


def _retry_excel_busy(operation: Any, *, phase: str, timeout_seconds: float = 10.0) -> Any:
    """Retry only Excel's known transient busy/rejected-call HRESULTs."""

    transient_hresult = {0x800AC472, 0x80010001, 0x8001010A}
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            return operation()
        except Exception as exc:
            if _excel_hresult(exc) not in transient_hresult:
                raise
            if time.monotonic() >= deadline:
                raise ExcelTimeoutError(f"{phase}: Excel remained busy") from exc
            try:
                import pythoncom

                pythoncom.PumpWaitingMessages()
            except Exception:
                pass
            time.sleep(0.20)


def _wait_for_excel_responsive(
    application: Any,
    *,
    owned_pid: int,
    phase: str,
    timeout_seconds: float = 10.0,
) -> None:
    """Wait for an idempotent COM probe; Excel.Ready is false in safe mode."""

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        _dismiss_owned_safe_startup_modals(owned_pid)
        try:
            _retry_excel_busy(
                lambda: application.Workbooks.Count,
                phase=phase,
                timeout_seconds=1.0,
            )
            return
        except ExcelTimeoutError:
            time.sleep(0.20)
    raise ExcelTimeoutError(f"{phase}: Excel did not become COM-responsive")


def _collect_formula_evidence(workbook: Any) -> tuple[FormulaCellEvidence, ...]:
    """Inspect formulas only through the already PID-bound workbook object."""

    records: list[FormulaCellEvidence] = []
    worksheet_count = int(
        _retry_excel_busy(
            lambda: workbook.Worksheets.Count,
            phase="count formula-evidence worksheets",
        )
    )
    for worksheet_index in range(1, worksheet_count + 1):
        worksheet = _retry_excel_busy(
            lambda worksheet_index=worksheet_index: workbook.Worksheets.Item(
                worksheet_index
            ),
            phase="open formula-evidence worksheet",
        )
        sheet_name = str(
            _retry_excel_busy(
                lambda worksheet=worksheet: worksheet.Name,
                phase="read formula-evidence worksheet name",
            )
        )
        used_range = _retry_excel_busy(
            lambda worksheet=worksheet: worksheet.UsedRange,
            phase=f"read used range for {sheet_name}",
        )
        has_formula = _retry_excel_busy(
            lambda used_range=used_range: used_range.HasFormula,
            phase=f"check formulas for {sheet_name}",
        )
        if has_formula is False or has_formula == 0:
            continue
        formula_cells = _retry_excel_busy(
            lambda worksheet=worksheet: worksheet.Cells.SpecialCells(
                XL_CELL_TYPE_FORMULAS
            ),
            phase=f"select formula cells for {sheet_name}",
        )
        expected_count = int(
            _retry_excel_busy(
                lambda formula_cells=formula_cells: formula_cells.CountLarge,
                phase=f"count formula cells for {sheet_name}",
            )
        )
        observed_count = 0
        for cell in formula_cells.Cells:
            formula_text = str(
                _retry_excel_busy(
                    lambda cell=cell: cell.Formula,
                    phase=f"read formula text for {sheet_name}",
                )
            )
            address = str(
                _retry_excel_busy(
                    lambda cell=cell: cell.Address(False, False),
                    phase=f"read formula address for {sheet_name}",
                )
            )
            cached_value = _retry_excel_busy(
                lambda cell=cell: cell.Value2,
                phase=f"read formula cache for {sheet_name}!{address}",
            )
            displayed = str(
                _retry_excel_busy(
                    lambda cell=cell: cell.Text,
                    phase=f"read formula display for {sheet_name}!{address}",
                )
            ).strip().upper()
            formula_error = displayed if displayed in FORMULA_ERROR_TOKENS else None
            records.append(
                FormulaCellEvidence(
                    sheet=sheet_name,
                    cell=address,
                    formula_text=formula_text,
                    cache_populated=cached_value is not None,
                    formula_error=formula_error,
                )
            )
            observed_count += 1
        if observed_count != expected_count:
            raise ExcelSafetyError(
                f"formula evidence enumeration mismatch for {sheet_name}: "
                f"{observed_count} != {expected_count}"
            )
    _canonical_formula_rows(records)
    return tuple(records)


def _read_workbook_model_input_hash(workbook: Any) -> str:
    """Read the renderer-written immutable model-input binding from Cover!B14."""

    cover = _retry_excel_busy(
        lambda: workbook.Worksheets.Item("Cover"),
        phase="open Cover for model-input binding",
    )
    marker = _retry_excel_busy(
        lambda: cover.Range("B14"),
        phase="open Cover!B14 model-input binding",
    )
    formula = str(
        _retry_excel_busy(
            lambda: marker.Formula,
            phase="read Cover!B14 marker formula",
        )
    ).strip()
    value = str(
        _retry_excel_busy(
            lambda: marker.Value2,
            phase="read Cover!B14 model-input binding",
        )
    ).strip()
    if formula.startswith("="):
        raise ExcelSafetyError("Cover!B14 model-input binding must be a static value")
    return _validate_sha256(value, "Cover!B14 model_input_hash")


def _close_disposable_startup_workbook(
    application: Any,
    startup_workbook: Any,
    *,
    owned_pid: int,
    timeout_seconds: float = 10.0,
) -> None:
    """Idempotently close only a repeatedly re-validated default Book#."""

    transient_hresult = {0x800AC472, 0x80010001, 0x8001010A}
    deadline = time.monotonic() + timeout_seconds
    candidate = startup_workbook
    while True:
        try:
            candidate.Close(SaveChanges=False)
            return
        except Exception as exc:
            if _excel_hresult(exc) not in transient_hresult:
                raise
            if time.monotonic() >= deadline:
                raise ExcelTimeoutError(
                    "close default startup workbook: Excel remained busy"
                ) from exc

        _dismiss_owned_safe_startup_modals(owned_pid)
        count = int(
            _retry_excel_busy(
                lambda: application.Workbooks.Count,
                phase="recount startup workbooks after busy close",
                timeout_seconds=1.0,
            )
        )
        if count == 0:
            return
        if count != 1:
            raise ExcelSafetyError(
                f"Busy startup close left {count} workbooks; refusing to continue"
            )
        candidate = _retry_excel_busy(
            lambda: application.Workbooks.Item(1),
            phase="reacquire startup workbook after busy close",
            timeout_seconds=1.0,
        )
        record = _retry_excel_busy(
            lambda: StartupWorkbookRecord(
                name=str(candidate.Name),
                full_name=str(candidate.FullName),
                path=str(candidate.Path or ""),
                worksheet_count=int(candidate.Worksheets.Count),
            ),
            phase="revalidate startup workbook after busy close",
            timeout_seconds=1.0,
        )
        if not is_disposable_startup_workbook(record):
            raise ExcelSafetyError(
                "Busy startup close exposed a non-default workbook: "
                f"{asdict(record)}"
            )
        time.sleep(0.20)


def _worker_recalculate(
    workbook_path: Path,
    owned: ProcessIdentity,
    *,
    startup_timeout_seconds: float,
    calculation_timeout_seconds: float,
    model_input_hash: str | None = None,
    expected_formula_text_hash: str | None = None,
) -> dict[str, Any]:
    import pythoncom
    if model_input_hash is not None:
        model_input_hash = _validate_sha256(model_input_hash, "model_input_hash")
    if expected_formula_text_hash is not None:
        expected_formula_text_hash = _validate_sha256(
            expected_formula_text_hash,
            "expected_formula_text_hash",
        )
    workbook_sha256_before = sha256_file(workbook_path)


    pythoncom.CoInitialize()
    application: Any | None = None
    workbook: Any | None = None
    workbook_closed = False
    bound_to_owned_pid = False
    startup_blank_workbooks_closed = 0
    saved = False
    phase = "validate owned process"
    try:
        current = read_process_identity(owned.pid)
        if current is None or not _same_process_identity(owned, current):
            raise ExcelSafetyError("Owned Excel identity was not valid in COM worker")

        phase = "bind exact PID/EXCEL7 window"
        application, main_hwnd, excel7_hwnd, dismissed = _bind_owned_application(
            owned,
            startup_timeout_seconds=startup_timeout_seconds,
        )
        bound_to_owned_pid = True
        _wait_for_excel_responsive(
            application,
            owned_pid=owned.pid,
            phase="post-bind readiness",
            timeout_seconds=startup_timeout_seconds,
        )

        phase = "configure isolated Excel"
        settings = (
            # The process is already created hidden; toggling Visible while
            # Excel is completing safe-mode startup is itself a busy-call risk.
            ("DisplayAlerts", False),
            ("AskToUpdateLinks", False),
            ("EnableEvents", False),
            ("ScreenUpdating", False),
            ("AutomationSecurity", MSO_AUTOMATION_SECURITY_FORCE_DISABLE),
            ("Calculation", XL_CALCULATION_MANUAL),
            ("CalculateBeforeSave", False),
        )
        for property_name, value in settings:
            _retry_excel_busy(
                lambda property_name=property_name, value=value: setattr(
                    application, property_name, value
                ),
                phase=f"configure {property_name}",
                timeout_seconds=startup_timeout_seconds,
            )

        phase = "inspect startup workbooks"
        startup_count = int(
            _retry_excel_busy(
                lambda: application.Workbooks.Count,
                phase="count startup workbooks",
            )
        )
        if startup_count:
            if startup_count != 1:
                raise ExcelSafetyError(
                    f"Isolated Excel created {startup_count} startup workbooks"
                )
            startup_workbook = _retry_excel_busy(
                lambda: application.Workbooks.Item(1),
                phase="get startup workbook",
            )
            startup_record = _retry_excel_busy(
                lambda: StartupWorkbookRecord(
                    name=str(startup_workbook.Name),
                    full_name=str(startup_workbook.FullName),
                    path=str(startup_workbook.Path or ""),
                    worksheet_count=int(startup_workbook.Worksheets.Count),
                ),
                phase="inspect startup workbook",
            )
            if not is_disposable_startup_workbook(startup_record):
                raise ExcelSafetyError(
                    "Isolated Excel opened a non-default startup workbook: "
                    f"{asdict(startup_record)}"
                )
            phase = "close default startup workbook"
            _close_disposable_startup_workbook(
                application,
                startup_workbook,
                owned_pid=owned.pid,
            )
            startup_blank_workbooks_closed = 1
            _wait_for_excel_responsive(
                application,
                owned_pid=owned.pid,
                phase="post-startup-workbook readiness",
            )
            remaining = int(
                _retry_excel_busy(
                    lambda: application.Workbooks.Count,
                    phase="verify startup workbook closed",
                )
            )
            if remaining != 0:
                raise ExcelSafetyError("Default startup workbook did not close cleanly")

        phase = "open exact target workbook"
        workbook = application.Workbooks.Open(
            Filename=str(workbook_path),
            UpdateLinks=0,
            ReadOnly=False,
            IgnoreReadOnlyRecommended=True,
            Notify=False,
            AddToMru=False,
        )

        phase = "verify exact target workbook"
        opened_full_name = str(
            _retry_excel_busy(lambda: workbook.FullName, phase="read opened workbook path")
        )
        if not _same_workbook_path(opened_full_name, workbook_path):
            raise ExcelSafetyError(
                f"Excel opened {opened_full_name!r}, not requested {str(workbook_path)!r}"
            )
        if bool(_retry_excel_busy(lambda: workbook.ReadOnly, phase="check read-only state")):
            raise ExcelSafetyError("Excel opened the requested workbook read-only")
        if int(
            _retry_excel_busy(
                lambda: application.Workbooks.Count,
                phase="verify target workbook count",
            )
        ) != 1:
            raise ExcelSafetyError("Isolated Excel opened more than the requested workbook")
        phase = "verify workbook model-input binding"
        workbook_model_input_hash = (
            _read_workbook_model_input_hash(workbook)
            if model_input_hash is not None
            else None
        )
        phase = "capture pre-calculation formula evidence"
        engine = str(
            _retry_excel_busy(
                lambda: application.Name,
                phase="read calculation engine",
            )
        )
        engine_version = str(
            _retry_excel_busy(
                lambda: application.Version,
                phase="read calculation engine version",
            )
        )
        before_formula_evidence = _collect_formula_evidence(workbook)

        phase = "CalculateFull"
        _retry_excel_busy(
            application.CalculateFull,
            phase="CalculateFull",
            timeout_seconds=calculation_timeout_seconds,
        )
        deadline = time.monotonic() + calculation_timeout_seconds
        while int(
            _retry_excel_busy(
                lambda: application.CalculationState,
                phase="read calculation state",
                timeout_seconds=min(2.0, calculation_timeout_seconds),
            )
        ) != XL_CALCULATION_DONE:
            if time.monotonic() >= deadline:
                raise ExcelTimeoutError("Excel calculation did not reach xlDone")
            time.sleep(0.20)

        _wait_for_excel_responsive(
            application,
            owned_pid=owned.pid,
            phase="pre-save readiness",
            timeout_seconds=calculation_timeout_seconds,
        )
        phase = "save target workbook"
        workbook.Save()
        saved = True
        phase = "capture post-save calculation evidence"
        after_formula_evidence = _collect_formula_evidence(workbook)
        if model_input_hash is not None:
            post_save_model_input_hash = _read_workbook_model_input_hash(workbook)
            if post_save_model_input_hash != workbook_model_input_hash:
                raise ExcelSafetyError(
                    "Cover!B14 model-input binding changed during calculation/save"
                )
        phase = "close target workbook"
        workbook.Close(SaveChanges=True)
        workbook_closed = True
        workbook = None
        phase = "bind calculation verification evidence"
        workbook_sha256_after = sha256_file(workbook_path)
        calculation_verification = build_calculation_verification_evidence(
            workbook_sha256=workbook_sha256_after,
            model_input_hash=model_input_hash,
            workbook_model_input_hash=workbook_model_input_hash,
            expected_formula_text_hash=expected_formula_text_hash,
            before=before_formula_evidence,
            after=after_formula_evidence,
            engine=engine,
            engine_version=engine_version,
        )

        phase = "quit isolated Excel"
        _retry_excel_busy(application.Quit, phase="quit isolated Excel")

        return {
            "status": "ok",
            "saved": True,
            "workbook": str(workbook_path),
            "workbook_sha256_before": workbook_sha256_before,
            "workbook_sha256": workbook_sha256_after,
            "calculation_verification": calculation_verification,
            "owned_excel_pid": owned.pid,
            "xlmain_hwnd": main_hwnd,
            "excel7_hwnd": excel7_hwnd,
            "dismissed_startup_modal_kinds": list(dismissed),
            "default_file_types_modals_dismissed": dismissed.count("default_file_types"),
            "recovered_files_notices_dismissed": dismissed.count("recovered_files_notice"),
            "startup_blank_workbooks_closed": startup_blank_workbooks_closed,
            "calculation": "CalculateFull",
            "calculation_mode": "manual",
        }
    except ExcelIsolationError:
        raise
    except Exception as exc:
        raise ExcelIsolationError(
            f"{phase}: {type(exc).__name__}: {exc}"
        ) from exc
    finally:
        # These operations are allowed only after exact PID/HWND verification.
        if bound_to_owned_pid:
            if workbook is not None and not workbook_closed:
                try:
                    workbook.Close(SaveChanges=bool(saved))
                except Exception:
                    pass
            if application is not None:
                try:
                    application.Quit()
                except Exception:
                    pass
        pythoncom.CoUninitialize()

def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(temporary, path)


def _hidden_startup_info() -> Any | None:
    if os.name != "nt":
        return None
    startup_info = subprocess.STARTUPINFO()
    startup_info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup_info.wShowWindow = 0  # SW_HIDE
    return startup_info


def launch_excel_process(excel_path: Path) -> subprocess.Popen[bytes]:
    creation_flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    return subprocess.Popen(
        build_excel_command(excel_path),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        startupinfo=_hidden_startup_info(),
        creationflags=creation_flags,
    )


def _launch_worker(
    *,
    script_path: Path,
    workbook_path: Path,
    owned: ProcessIdentity,
    result_path: Path,
    startup_timeout_seconds: float,
    calculation_timeout_seconds: float,
    model_input_hash: str | None = None,
    expected_formula_text_hash: str | None = None,
) -> subprocess.Popen[bytes]:
    command = [
        sys.executable,
        str(script_path),
        str(workbook_path),
        "--_worker",
        "--_owned-pid",
        str(owned.pid),
        "--_owned-create-time",
        repr(owned.create_time),
        "--_owned-executable",
        owned.executable,
        "--_result-path",
        str(result_path),
        "--startup-timeout-seconds",
        str(startup_timeout_seconds),
        "--calculation-timeout-seconds",
        str(calculation_timeout_seconds),
    ]
    if model_input_hash is not None:
        command.extend(["--model-input-hash", model_input_hash])
    if expected_formula_text_hash is not None:
        command.extend(
            ["--expected-formula-text-hash", expected_formula_text_hash]
        )
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        startupinfo=_hidden_startup_info(),
        creationflags=creation_flags,
    )


def _stop_worker(worker: subprocess.Popen[bytes], grace_seconds: float = 2.0) -> None:
    if worker.poll() is not None:
        return
    worker.terminate()
    try:
        worker.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        worker.kill()
        worker.wait(timeout=grace_seconds)


def _wait_for_owned_exit(owned: ProcessIdentity, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        current = read_process_identity(owned.pid)
        if current is None:
            return True
        if not _same_process_identity(owned, current):
            raise ExcelSafetyError(f"Owned PID {owned.pid} changed identity during exit")
        time.sleep(0.10)
    return read_process_identity(owned.pid) is None


def run_isolated_recalculation(
    workbook_path: Path,
    excel_path: Path,
    *,
    timeout_seconds: float,
    startup_timeout_seconds: float,
    calculation_timeout_seconds: float,
    model_input_hash: str | None = None,
    expected_formula_text_hash: str | None = None,
) -> dict[str, Any]:
    if model_input_hash is not None:
        model_input_hash = _validate_sha256(model_input_hash, "model_input_hash")
    if expected_formula_text_hash is not None:
        expected_formula_text_hash = _validate_sha256(
            expected_formula_text_hash,
            "expected_formula_text_hash",
        )
    before = snapshot_excel_processes()
    excel_process: subprocess.Popen[bytes] | None = None
    worker: subprocess.Popen[bytes] | None = None
    owned: ProcessIdentity | None = None
    result: dict[str, Any] = {}
    timed_out = False
    cleanup_terminated_owned_pid = False
    cleanup_issues: list[str] = []

    try:
        excel_process = launch_excel_process(excel_path)
        identity = read_process_identity(excel_process.pid, retry_seconds=5.0)
        if identity is None:
            raise ExcelIsolationError(
                f"Launched EXCEL.EXE PID {excel_process.pid} exited before ownership capture"
            )
        # Keep the exact identity for guarded cleanup even if a subsequent
        # ownership assertion fails. A pre-existing PID is still protected by
        # terminate_owned_excel's independent preexisting-PID check.
        owned = identity
        validate_new_excel_identity(
            identity,
            preexisting=before,
            expected_executable=excel_path,
        )

        with tempfile.TemporaryDirectory(prefix="ai_fund_excel_recalc_") as temporary_dir:
            result_path = Path(temporary_dir) / "worker-result.json"
            worker = _launch_worker(
                script_path=Path(__file__).resolve(),
                workbook_path=workbook_path,
                owned=owned,
                result_path=result_path,
                startup_timeout_seconds=startup_timeout_seconds,
                model_input_hash=model_input_hash,
                expected_formula_text_hash=expected_formula_text_hash,
                calculation_timeout_seconds=calculation_timeout_seconds,
            )
            try:
                worker.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                timed_out = True
                _stop_worker(worker)

            if result_path.exists():
                result = json.loads(result_path.read_text(encoding="utf-8"))
            elif timed_out:
                result = {
                    "status": "error",
                    "error": f"overall timeout after {timeout_seconds:g} seconds",
                    "error_type": "ExcelTimeoutError",
                }
            else:
                result = {
                    "status": "error",
                    "error": f"COM worker exited with code {worker.returncode} without a result",
                    "error_type": "ExcelIsolationError",
                }
    except Exception as exc:
        result = {
            "status": "error",
            "saved": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
    finally:
        try:
            if worker is not None:
                _stop_worker(worker)
        except Exception as exc:
            cleanup_issues.append(f"worker cleanup failed: {type(exc).__name__}: {exc}")
        try:
            if owned is not None and not _wait_for_owned_exit(owned, 2.0):
                cleanup_terminated_owned_pid = terminate_owned_excel(
                    owned,
                    preexisting_pids=before,
                )
        except Exception as exc:
            cleanup_issues.append(f"Excel cleanup failed: {type(exc).__name__}: {exc}")
        if excel_process is not None:
            try:
                excel_process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                # Never call Popen.kill here; the guarded PID cleanup above is
                # the only permitted Excel termination path.
                pass

    after = snapshot_excel_processes()
    process_issues = preexisting_process_issues(before, after)
    result.update(
        {
            "owned_excel_pid": owned.pid if owned else None,
            "preexisting_excel_pids": sorted(before),
            "preexisting_excel_pids_untouched": not process_issues,
            "preexisting_process_issues": process_issues,
            "timeout": timed_out,
            "cleanup_terminated_owned_pid": cleanup_terminated_owned_pid,
            "cleanup_issues": cleanup_issues,
        }
    )
    if timed_out:
        result["status"] = "error"
        result["saved"] = False
        result["error_type"] = "ExcelTimeoutError"
        result["error"] = f"overall timeout after {timeout_seconds:g} seconds"
    if cleanup_issues:
        result["status"] = "error"
        result["error_type"] = "ExcelSafetyError"
        result["error"] = "; ".join(cleanup_issues)
    if process_issues:
        result["status"] = "error"
        result["error_type"] = "ExcelSafetyError"
        result["error"] = "; ".join(process_issues)
    return result


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Recalculate one workbook in a PID-isolated native Excel process."
    )
    parser.add_argument("workbook", help="Exact workbook path to recalculate and save")
    parser.add_argument("--excel-path", help="Exact path to EXCEL.EXE")
    parser.add_argument(
        "--model-input-hash",
        help="Lowercase SHA-256 of the exact model-input snapshot",
    )
    parser.add_argument(
        "--expected-formula-text-hash",
        help="Renderer-baseline SHA-256 of canonical workbook formula text",
    )
    parser.add_argument(
        "--verification-output",
        help="Optional authoritative isolated-calculation JSON sidecar path",
    )
    parser.add_argument("--dry-run", action="store_true", help="Validate and print the plan only")
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument("--startup-timeout-seconds", type=float, default=45.0)
    parser.add_argument("--calculation-timeout-seconds", type=float, default=120.0)

    # Internal watchdog worker arguments.  They are deliberately undocumented.
    parser.add_argument("--_worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--_owned-pid", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--_owned-create-time", type=float, help=argparse.SUPPRESS)
    parser.add_argument("--_owned-executable", help=argparse.SUPPRESS)
    parser.add_argument("--_result-path", help=argparse.SUPPRESS)
    return parser


def _validate_timeouts(args: argparse.Namespace) -> None:
    for name in (
        "timeout_seconds",
        "startup_timeout_seconds",
        "calculation_timeout_seconds",
    ):
        if float(getattr(args, name)) <= 0:
            raise ExcelSafetyError(f"--{name.replace('_', '-')} must be positive")


def _run_worker_cli(args: argparse.Namespace, workbook_path: Path) -> int:
    if (
        args._owned_pid is None
        or args._owned_create_time is None
        or not args._owned_executable
        or not args._result_path
    ):
        raise ExcelSafetyError("Internal worker ownership arguments are incomplete")
    result_path = Path(args._result_path).resolve()
    owned = ProcessIdentity(
        pid=args._owned_pid,
        create_time=args._owned_create_time,
        executable=args._owned_executable,
    )
    try:
        result = _worker_recalculate(
            workbook_path,
            owned,
            startup_timeout_seconds=args.startup_timeout_seconds,
            calculation_timeout_seconds=args.calculation_timeout_seconds,
            model_input_hash=args.model_input_hash,
            expected_formula_text_hash=args.expected_formula_text_hash,
        )
        _atomic_write_json(result_path, result)
        return 0
    except Exception as exc:
        _atomic_write_json(
            result_path,
            {
                "status": "error",
                "saved": False,
                "error_type": type(exc).__name__,
                "error": str(exc),
                "owned_excel_pid": owned.pid,
            },
        )
        return 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        _validate_timeouts(args)
        workbook_path = validate_workbook_path(args.workbook)
        model_input_hash = (
            _validate_sha256(args.model_input_hash, "model_input_hash")
            if args.model_input_hash is not None
            else None
        )
        expected_formula_text_hash = (
            _validate_sha256(
                args.expected_formula_text_hash,
                "expected_formula_text_hash",
            )
            if args.expected_formula_text_hash is not None
            else None
        )
        if args._worker:
            return _run_worker_cli(args, workbook_path)
        verification_output = (
            validate_verification_output_path(
                args.verification_output,
                workbook_path=workbook_path,
            )
            if args.verification_output
            else None
        )
        if verification_output is not None and (
            model_input_hash is None or expected_formula_text_hash is None
        ):
            raise ExcelSafetyError(
                "--verification-output requires --model-input-hash and "
                "--expected-formula-text-hash"
            )

        excel_path = discover_excel_executable(args.excel_path)
        if args.dry_run:
            payload = {
                "status": "dry-run",
                "launched": False,
                "workbook": str(workbook_path),
                "excel_path": str(excel_path),
                "excel_command": build_excel_command(excel_path),
                "preexisting_excel_pids": sorted(snapshot_excel_processes()),
                "binding": "exact PID -> XLMAIN -> EXCEL7 -> WM_GETOBJECT",
                "calculation": "manual mode + CalculateFull + save",
                "model_input_hash": model_input_hash,
                "expected_formula_text_hash": expected_formula_text_hash,
                "verification_output": (
                    str(verification_output) if verification_output else None
                ),
                "verification_state": "UNVERIFIED",
            }
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 0

        result = run_isolated_recalculation(
            workbook_path,
            excel_path,
            timeout_seconds=args.timeout_seconds,
            startup_timeout_seconds=args.startup_timeout_seconds,
            calculation_timeout_seconds=args.calculation_timeout_seconds,
            model_input_hash=model_input_hash,
            expected_formula_text_hash=expected_formula_text_hash,
        )
        if verification_output is not None:
            sidecar = build_verification_sidecar(result)
            _atomic_write_json(verification_output, sidecar)
            result["verification_output"] = str(verification_output)
            result["verification_sidecar_hash"] = sidecar["sidecar_hash"]
        stream = sys.stdout if result.get("status") == "ok" else sys.stderr
        print(json.dumps(result, indent=2, sort_keys=True), file=stream)
        return 0 if result.get("status") == "ok" else 1
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "error",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
                indent=2,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
