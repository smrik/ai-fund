from __future__ import annotations

import json
from datetime import datetime, timezone
import subprocess
from pathlib import Path

from types import SimpleNamespace
import pytest

from scripts.manual import recalculate_excel_isolated as isolated


def identity(pid: int, executable: str = r"C:\Office\EXCEL.EXE", created: float = 1.0):
    return isolated.ProcessIdentity(pid=pid, create_time=created, executable=executable)


def window(
    hwnd: int,
    pid: int,
    class_name: str,
    title: str = "",
):
    return isolated.WindowRecord(
        hwnd=hwnd,
        pid=pid,
        class_name=class_name,
        title=title,
    )


def test_excel_hresult_unwraps_nested_excel_busy_scode():
    error = Exception(
        -2147352567,
        "Exception occurred.",
        (0, None, None, None, 0, -2146777998),
        None,
    )

    assert isolated._excel_hresult(error) == 0x800AC472


def test_excel_command_is_exact_and_does_not_include_workbook():
    excel = Path(r"C:\Office\EXCEL.EXE")

    command = isolated.build_excel_command(excel)

    assert command == [str(excel), "/safe", "/x", "/automation"]
    assert "model.xlsx" not in command


def test_new_excel_identity_rejects_preexisting_pid():
    excel = Path(r"C:\Office\EXCEL.EXE")
    existing = identity(23828)

    with pytest.raises(isolated.ExcelSafetyError, match="pre-existing"):
        isolated.validate_new_excel_identity(
            existing,
            preexisting={23828: existing},
            expected_executable=excel,
        )


def test_new_excel_identity_requires_exact_executable():
    with pytest.raises(isolated.ExcelSafetyError, match="executable mismatch"):
        isolated.validate_new_excel_identity(
            identity(40000, executable=r"D:\Other\EXCEL.EXE"),
            preexisting={},
            expected_executable=Path(r"C:\Office\EXCEL.EXE"),
        )


def test_termination_guard_rejects_pid_reuse_and_preexisting_pid():
    owned = identity(40000, created=100.0)

    with pytest.raises(isolated.ExcelSafetyError, match="identity changed"):
        isolated.validate_termination_target(
            owned,
            identity(40000, created=101.0),
            preexisting_pids=(),
        )

    with pytest.raises(isolated.ExcelSafetyError, match="pre-existing"):
        isolated.validate_termination_target(
            owned,
            owned,
            preexisting_pids=(40000,),
        )


def test_preexisting_process_proof_detects_missing_or_reused_pid():
    before = {
        23828: identity(23828, created=10.0),
        25000: identity(25000, created=20.0),
    }
    after = {23828: identity(23828, created=11.0)}

    issues = isolated.preexisting_process_issues(before, after)

    assert issues == [
        "pre-existing Excel PID 23828 changed identity",
        "pre-existing Excel PID 25000 is no longer present",
    ]


def test_startup_workbook_classifier_allows_only_pathless_default_book():
    safe = isolated.StartupWorkbookRecord(
        name="Book1",
        full_name="Book1",
        path="",
        worksheet_count=1,
    )
    personal = isolated.StartupWorkbookRecord(
        name="PERSONAL.XLSB",
        full_name=r"C:\Users\me\XLSTART\PERSONAL.XLSB",
        path=r"C:\Users\me\XLSTART",
        worksheet_count=1,
    )
    recovered = isolated.StartupWorkbookRecord(
        name="Recovered.xlsx",
        full_name=r"C:\Temp\Recovered.xlsx",
        path=r"C:\Temp",
        worksheet_count=1,
    )

    assert isolated.is_disposable_startup_workbook(safe)
    assert not isolated.is_disposable_startup_workbook(personal)
    assert not isolated.is_disposable_startup_workbook(recovered)


def test_modal_match_requires_exact_owned_pid_and_exact_default_types_identity():
    exact = window(10, 40000, "#32770", "Microsoft Excel - Default File Types")
    body_heading = window(20, 40000, "Static", "Default File Types")
    caption_only = window(11, 40000, "#32770", "Microsoft Excel")
    wrong_pid = window(12, 23828, "#32770", "Default File Types")
    vague_title = window(13, 40000, "#32770", "Choose your default file types now")

    assert isolated.is_default_file_types_modal(exact, 40000)
    assert isolated.is_default_file_types_modal(caption_only, 40000, [body_heading])
    assert not isolated.is_default_file_types_modal(caption_only, 40000)
    assert not isolated.is_default_file_types_modal(wrong_pid, 40000)
    assert not isolated.is_default_file_types_modal(vague_title, 40000)


def test_recovered_files_notice_requires_exact_owned_dialog_and_selects_only_ok():
    modal = window(10, 40000, "#32770", "Microsoft Excel")
    notice = window(
        20,
        40000,
        "Static",
        "Excel has detected that you have recovered files. These files will be "
        "opened the next time you start Excel in normal mode.",
    )
    children = [notice, window(21, 40000, "Button", "OK")]

    assert isolated.is_recovered_files_notice(modal, 40000, children)
    assert not isolated.is_recovered_files_notice(modal, 23828, children)
    assert isolated.select_recovered_files_ok_button(
        modal, children, owned_pid=40000
    ) == isolated.ModalAction(kind="button", hwnd=21)


def test_safe_modal_button_never_selects_committing_button():
    modal = window(10, 40000, "#32770", "Default File Types")
    children = [
        window(20, 40000, "Button", "OK"),
        window(21, 40000, "Button", "&Cancel"),
        window(22, 23828, "Button", "Ask me later"),
    ]

    action = isolated.select_safe_modal_button(modal, children, owned_pid=40000)

    assert action == isolated.ModalAction(kind="button", hwnd=21)


def test_owned_excel_window_selection_is_pid_and_class_exact():
    top = [
        window(100, 23828, "XLMAIN"),
        window(200, 40000, "XLMAIN"),
        window(300, 40000, "Other"),
    ]
    descendants = {
        100: [window(101, 23828, "EXCEL7")],
        200: [
            window(201, 23828, "EXCEL7"),
            window(202, 40000, "EXCEL7"),
            window(203, 40000, "Excel7"),
        ],
    }

    selected = isolated.select_owned_excel_windows(top, descendants, owned_pid=40000)

    assert selected is not None
    main, excel7 = selected
    assert main.hwnd == 200
    assert [item.hwnd for item in excel7] == [202]


def test_owned_excel_window_selection_ignores_xlmain_without_exact_excel7():
    top = [window(200, 40000, "XLMAIN"), window(201, 40000, "XLMAIN")]
    descendants = {
        200: [window(202, 40000, "Other")],
        201: [window(203, 40000, "EXCEL7")],
    }

    selected = isolated.select_owned_excel_windows(top, descendants, owned_pid=40000)

    assert selected is not None
    assert selected[0].hwnd == 201
    assert [item.hwnd for item in selected[1]] == [203]


def test_owned_excel_window_selection_fails_on_multiple_excel7_bearing_mains():
    top = [window(200, 40000, "XLMAIN"), window(201, 40000, "XLMAIN")]
    descendants = {
        200: [window(202, 40000, "EXCEL7")],
        201: [window(203, 40000, "EXCEL7")],
    }

    with pytest.raises(isolated.ExcelSafetyError, match="multiple EXCEL7-bearing"):
        isolated.select_owned_excel_windows(top, descendants, owned_pid=40000)


def test_dry_run_validates_plan_without_launching_excel(tmp_path, monkeypatch, capsys):
    workbook = tmp_path / "tiny.xlsx"
    workbook.write_bytes(b"not opened in dry-run")
    excel = tmp_path / "EXCEL.EXE"
    excel.write_bytes(b"not launched in dry-run")

    def forbidden_launch(_excel_path):
        raise AssertionError("dry-run launched Excel")

    monkeypatch.setattr(isolated, "launch_excel_process", forbidden_launch)
    monkeypatch.setattr(isolated, "snapshot_excel_processes", lambda: {23828: identity(23828)})

    code = isolated.main(
        [str(workbook), "--excel-path", str(excel), "--dry-run"]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "dry-run"
    assert payload["launched"] is False
    assert payload["preexisting_excel_pids"] == [23828]
    assert payload["excel_command"][-3:] == ["/safe", "/x", "/automation"]


def test_watchdog_timeout_cleanup_targets_only_owned_excel_pid(monkeypatch):
    protected = identity(23828, created=10.0)
    owned = identity(40000, created=20.0)
    snapshots = iter([{23828: protected}, {23828: protected}])
    terminated = []

    class FakeExcelProcess:
        pid = 40000

        def wait(self, timeout):
            return 0

    class FakeWorker:
        returncode = None

        def wait(self, timeout):
            raise subprocess.TimeoutExpired("worker", timeout)

    monkeypatch.setattr(isolated, "snapshot_excel_processes", lambda: next(snapshots))
    monkeypatch.setattr(isolated, "launch_excel_process", lambda _path: FakeExcelProcess())
    monkeypatch.setattr(
        isolated,
        "read_process_identity",
        lambda _pid, **_kwargs: owned,
    )
    monkeypatch.setattr(isolated, "_launch_worker", lambda **_kwargs: FakeWorker())
    monkeypatch.setattr(isolated, "_stop_worker", lambda _worker: None)
    monkeypatch.setattr(isolated, "_wait_for_owned_exit", lambda _owned, _seconds: False)

    def record_termination(expected, *, preexisting_pids, **_kwargs):
        terminated.append((expected.pid, set(preexisting_pids)))
        return True

    monkeypatch.setattr(isolated, "terminate_owned_excel", record_termination)

    result = isolated.run_isolated_recalculation(
        Path("tiny.xlsx"),
        Path(r"C:\Office\EXCEL.EXE"),
        timeout_seconds=0.01,
        startup_timeout_seconds=1.0,
        calculation_timeout_seconds=1.0,
    )

    assert result["status"] == "error"
    assert result["timeout"] is True
    assert result["preexisting_excel_pids_untouched"] is True
    assert terminated == [(40000, {23828})]


@pytest.mark.parametrize("suffix", [".csv", ".txt", ".pdf"])
def test_workbook_validation_rejects_non_excel_files(tmp_path, suffix):
    path = tmp_path / f"input{suffix}"
    path.write_text("x", encoding="utf-8")

    with pytest.raises(isolated.ExcelSafetyError, match="Unsupported"):
        isolated.validate_workbook_path(path)
def formula_record(
    sheet: str,
    cell: str,
    formula_text: str,
    *,
    cache_populated: bool = True,
    formula_error: str | None = None,
) -> isolated.FormulaCellEvidence:
    return isolated.FormulaCellEvidence(
        sheet=sheet,
        cell=cell,
        formula_text=formula_text,
        cache_populated=cache_populated,
        formula_error=formula_error,
    )


def _full_calculation_evidence(**updates):
    before = (
        formula_record("Income_Statement", "B2", "=SUM(B3:B4)"),
        formula_record("Checks", "C5", '=IF(B5="PASS","PASS","BLOCKED")'),
    )
    payload = {
        "workbook_sha256": "a" * 64,
        "model_input_hash": "b" * 64,
        "workbook_model_input_hash": "b" * 64,
        "expected_formula_text_hash": isolated.formula_text_hash(before),
        "before": before,
        "after": tuple(reversed(before)),
        "engine": "Microsoft Excel",
        "engine_version": "16.0",
        "verified_at": datetime(2026, 7, 12, 10, 0, tzinfo=timezone.utc),
    }
    payload.update(updates)
    return isolated.build_calculation_verification_evidence(**payload)


def test_formula_text_hash_is_order_independent_but_text_sensitive():
    first = formula_record("Checks", "B5", "=1+1")
    second = formula_record("DCF", "C8", "=NPV(C2,C3:C7)")

    assert isolated.formula_text_hash((first, second)) == isolated.formula_text_hash(
        (second, first)
    )
    assert isolated.formula_text_hash((first,)) != isolated.formula_text_hash(
        (formula_record("Checks", "B5", "=1+2"),)
    )

    with pytest.raises(isolated.ExcelSafetyError, match="duplicate formula evidence"):
        isolated.formula_text_hash((first, first))


def test_calculation_evidence_is_contract_compatible_and_bound_to_final_hash():
    from src.contracts.professional_financial_model import (
        CalculationVerificationRecord,
        WorkflowState,
    )

    evidence = _full_calculation_evidence()

    assert evidence["workbook_sha256"] == "a" * 64
    assert evidence["model_input_hash"] == "b" * 64
    assert evidence["formula_text_parity"] == "pass"
    assert evidence["cache_population"] == "pass"
    assert evidence["formula_error_scan"] == "pass"
    assert evidence["verification_state"] == "FULL"

    record = CalculationVerificationRecord.model_validate(evidence)
    assert record.verification_state is WorkflowState.FULL
    assert record.verification_hash == evidence["verification_hash"]


@pytest.mark.parametrize(
    ("updates", "expected_state", "expected_gate"),
    (
        ({"model_input_hash": None}, "UNVERIFIED", None),
        (
            {"expected_formula_text_hash": None},
            "UNVERIFIED",
            None,
        ),
        (
            {"expected_formula_text_hash": "c" * 64},
            "BLOCKED",
            "formula_text_parity",
        ),
        (
            {"workbook_model_input_hash": "c" * 64},
            "BLOCKED",
            "model_input_hash_parity",
        ),
        (
            {
                "after": (
                    formula_record("Income_Statement", "B2", "=SUM(B3:B5)"),
                    formula_record(
                        "Checks",
                        "C5",
                        '=IF(B5="PASS","PASS","BLOCKED")',
                    ),
                )
            },
            "BLOCKED",
            "formula_text_parity",
        ),
        (
            {
                "after": (
                    formula_record(
                        "Income_Statement",
                        "B2",
                        "=SUM(B3:B4)",
                        cache_populated=False,
                    ),
                    formula_record(
                        "Checks",
                        "C5",
                        '=IF(B5="PASS","PASS","BLOCKED")',
                    ),
                )
            },
            "BLOCKED",
            "cache_population",
        ),
        (
            {
                "after": (
                    formula_record("Income_Statement", "B2", "=SUM(B3:B4)"),
                    formula_record(
                        "Checks",
                        "C5",
                        '=IF(B5="PASS","PASS","BLOCKED")',
                        formula_error="#REF!",
                    ),
                )
            },
            "BLOCKED",
            "formula_error_scan",
        ),
    ),
)
def test_calculation_evidence_fails_closed(
    updates,
    expected_state,
    expected_gate,
):
    evidence = _full_calculation_evidence(**updates)

    assert evidence["verification_state"] == expected_state
    if expected_gate is not None:
        assert evidence[expected_gate] == "fail"


def test_verification_sidecar_requires_both_full_evidence_and_clean_pid_isolation():
    evidence = _full_calculation_evidence()
    result = {
        "status": "ok",
        "saved": True,
        "workbook": r"C:\models\model.xlsx",
        "owned_excel_pid": 40000,
        "preexisting_excel_pids": [23828],
        "preexisting_excel_pids_untouched": True,
        "preexisting_process_issues": [],
        "timeout": False,
        "cleanup_terminated_owned_pid": False,
        "cleanup_issues": [],
        "calculation_verification": evidence,
    }

    sidecar = isolated.build_verification_sidecar(result)
    assert sidecar["authoritative"] is True
    assert sidecar["release_state"] == "FULL"
    assert sidecar["authoritative_scope"] == "calculation_verification_only"
    assert sidecar["calculation_verification_state"] == "FULL"
    assert sidecar["package_release_state"] == "UNVERIFIED"
    assert len(sidecar["sidecar_hash"]) == 64
    assert isolated.build_verification_sidecar(result) == sidecar

    failed_isolation = isolated.build_verification_sidecar(
        {**result, "preexisting_excel_pids_untouched": False}
    )
    assert failed_isolation["authoritative"] is False
    assert failed_isolation["release_state"] == "BLOCKED"

    unbound = isolated.build_verification_sidecar(
        {
            **result,
            "calculation_verification": _full_calculation_evidence(
                model_input_hash=None
            ),
        }
    )
    assert unbound["authoritative"] is False
    assert unbound["release_state"] == "UNVERIFIED"

    unknown = isolated.build_verification_sidecar(
        {
            **result,
            "calculation_verification": {
                **evidence,
                "verification_state": "READY",
            },
        }
    )
    assert unknown["authoritative"] is False
    assert unknown["release_state"] == "UNVERIFIED"


def test_verification_output_path_is_json_and_cannot_replace_workbook(tmp_path):
    workbook = tmp_path / "model.xlsx"
    workbook.write_bytes(b"x")

    output = isolated.validate_verification_output_path(
        tmp_path / "model.verification.json",
        workbook_path=workbook,
    )
    assert output.suffix == ".json"

    with pytest.raises(isolated.ExcelSafetyError, match=r"\.json"):
        isolated.validate_verification_output_path(
            tmp_path / "model.txt",
            workbook_path=workbook,
        )
    with pytest.raises(isolated.ExcelSafetyError, match="cannot overwrite"):
        isolated.validate_verification_output_path(
            workbook,
            workbook_path=workbook,
        )


def test_dry_run_reports_hash_binding_and_does_not_write_sidecar(
    tmp_path,
    monkeypatch,
    capsys,
):
    workbook = tmp_path / "tiny.xlsx"
    workbook.write_bytes(b"not opened in dry-run")
    excel = tmp_path / "EXCEL.EXE"
    excel.write_bytes(b"not launched in dry-run")
    sidecar = tmp_path / "verification.json"

    monkeypatch.setattr(
        isolated,
        "launch_excel_process",
        lambda _path: (_ for _ in ()).throw(
            AssertionError("dry-run launched Excel")
        ),
    )
    monkeypatch.setattr(isolated, "snapshot_excel_processes", lambda: {})

    code = isolated.main(
        [
            str(workbook),
            "--excel-path",
            str(excel),
            "--dry-run",
            "--model-input-hash",
            "b" * 64,
            "--expected-formula-text-hash",
            "c" * 64,
            "--verification-output",
            str(sidecar),
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["model_input_hash"] == "b" * 64
    assert payload["expected_formula_text_hash"] == "c" * 64
    assert payload["verification_output"] == str(sidecar.resolve())
    assert payload["verification_state"] == "UNVERIFIED"
    assert not sidecar.exists()


def test_main_writes_authoritative_verification_sidecar(
    tmp_path,
    monkeypatch,
    capsys,
):
    workbook = tmp_path / "tiny.xlsx"
    workbook.write_bytes(b"test workbook")
    excel = tmp_path / "EXCEL.EXE"
    excel.write_bytes(b"test executable")
    sidecar_path = tmp_path / "verification.json"
    evidence = _full_calculation_evidence()

    result = {
        "status": "ok",
        "saved": True,
        "workbook": str(workbook.resolve()),
        "owned_excel_pid": 40000,
        "preexisting_excel_pids": [],
        "preexisting_excel_pids_untouched": True,
        "preexisting_process_issues": [],
        "timeout": False,
        "cleanup_terminated_owned_pid": False,
        "cleanup_issues": [],
        "calculation_verification": evidence,
    }
    observed = {}

    def fake_run(workbook_path, excel_path, **kwargs):
        observed.update(
            {
                "workbook_path": workbook_path,
                "excel_path": excel_path,
                **kwargs,
            }
        )
        return dict(result)

    monkeypatch.setattr(isolated, "run_isolated_recalculation", fake_run)

    code = isolated.main(
        [
            str(workbook),
            "--excel-path",
            str(excel),
            "--model-input-hash",
            "b" * 64,
            "--expected-formula-text-hash",
            evidence["expected_formula_text_hash"],
            "--verification-output",
            str(sidecar_path),
        ]
    )

    assert code == 0
    assert observed["model_input_hash"] == "b" * 64
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    assert (
        observed["expected_formula_text_hash"] == evidence["expected_formula_text_hash"]
    )
    assert sidecar["authoritative"] is True
    assert sidecar["calculation_verification"]["workbook_sha256"] == "a" * 64
    stdout = json.loads(capsys.readouterr().out)
    assert stdout["verification_output"] == str(sidecar_path.resolve())
    assert stdout["verification_sidecar_hash"] == sidecar["sidecar_hash"]


def test_invalid_model_input_hash_fails_before_excel_snapshot(monkeypatch):
    monkeypatch.setattr(
        isolated,
        "snapshot_excel_processes",
        lambda: (_ for _ in ()).throw(AssertionError("snapshot should not run")),
    )

    with pytest.raises(isolated.ExcelSafetyError, match="model_input_hash"):
        isolated.run_isolated_recalculation(
            Path("tiny.xlsx"),
            Path(r"C:\Office\EXCEL.EXE"),
            timeout_seconds=1.0,
            startup_timeout_seconds=1.0,
            calculation_timeout_seconds=1.0,
            model_input_hash="unknown",
        )
def test_workbook_model_input_binding_requires_static_cover_hash():
    marker = SimpleNamespace(Formula="b" * 64, Value2="b" * 64)
    cover = SimpleNamespace(Range=lambda address: marker)
    workbook = SimpleNamespace(
        Worksheets=SimpleNamespace(Item=lambda sheet: cover)
    )

    assert isolated._read_workbook_model_input_hash(workbook) == "b" * 64

    marker.Formula = '="mutable"'
    with pytest.raises(isolated.ExcelSafetyError, match="static value"):
        isolated._read_workbook_model_input_hash(workbook)


def test_verification_sidecar_cli_requires_renderer_formula_baseline(
    tmp_path,
    capsys,
):
    workbook = tmp_path / "tiny.xlsx"
    workbook.write_bytes(b"test workbook")
    sidecar = tmp_path / "verification.json"

    code = isolated.main(
        [
            str(workbook),
            "--model-input-hash",
            "b" * 64,
            "--verification-output",
            str(sidecar),
        ]
    )

    assert code == 1
    error = json.loads(capsys.readouterr().err)
    assert error["error_type"] == "ExcelSafetyError"
    assert "--expected-formula-text-hash" in error["error"]
    assert not sidecar.exists()
