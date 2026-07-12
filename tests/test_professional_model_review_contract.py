from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping, Sequence

import pytest

from db.loader import list_professional_model_review_events
from db.schema import get_connection
from src.stage_04_pipeline import professional_model_review as review


SOURCE_HASH = "1" * 64
INPUT_HASH = "2" * 64
RESULT_HASH = "3" * 64
MANIFEST_HASH = "4" * 64
WORKBOOK_HASH = "5" * 64
QA_HASH = "6" * 64
EVIDENCE_FILE_HASH = "7" * 64

EXPECTED_SHEETS = [
    "Cover",
    "Summary",
    "Sources",
    "Assumptions",
    "Historical_Data",
    "Segment_Build",
    "Income_Statement",
    "Balance_Sheet",
    "Cash_Flow",
    "Working_Capital",
    "PP&E_Intangibles",
    "Debt_Cash_Interest",
    "Capital_Allocation",
    "Taxes",
    "Shares_EPS",
    "Consensus_Bridge",
    "WACC",
    "DCF",
    "Comps",
    "SOTP",
    "Valuation",
    "Scenarios",
    "Sensitivities",
    "Accounting_QoE",
    "PM_Review_Queue",
    "Checks",
]


@pytest.fixture(scope="module")
def live_artifacts() -> review.ProfessionalModelArtifacts:
    return review.discover_professional_model_artifacts("MSFT")


@pytest.fixture
def isolated_review_db(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    db_path = tmp_path / "professional-model-review-contract.db"
    monkeypatch.setenv("ALPHA_POD_DB_PATH", str(db_path))
    return db_path


def _synthetic_artifacts(
    tmp_path: Path,
    *,
    blockers: Sequence[str] = (),
    warnings: Sequence[str] = (),
    reported_status: Any = "READY",
    decision_ready: Any = True,
    checks: Sequence[Mapping[str, Any]] | None = None,
    issues: Sequence[Mapping[str, str]] = (),
    review_evidence_file_hash: str | None = EVIDENCE_FILE_HASH,
) -> review.ProfessionalModelArtifacts:
    artifact_dir = tmp_path / "MSFT" / "3"
    return review.ProfessionalModelArtifacts(
        ticker="MSFT",
        model_run_id=3,
        artifact_dir=artifact_dir,
        workbook_path=artifact_dir / "MSFT_professional_model_v2.xlsx",
        manifest_path=artifact_dir / review.MANIFEST_NAME,
        qa_report_path=artifact_dir / review.QA_REPORT_NAME,
        manifest={
            "source_hash": SOURCE_HASH,
            "model_input_hash": INPUT_HASH,
            "result_hash": RESULT_HASH,
            "manifest_hash": MANIFEST_HASH,
            "blockers": list(blockers),
            "warnings": list(warnings),
        },
        review_evidence=None,
        qa_report={
            "model_status": reported_status,
            "decision_ready": decision_ready,
            "checks": list(
                checks
                if checks is not None
                else [{"check_id": "model_readiness", "status": "PASS"}]
            ),
        },
        workbook_hash=WORKBOOK_HASH,
        qa_report_hash=QA_HASH,
        review_evidence_file_hash=review_evidence_file_hash,
        workbook_bytes=17,
        issues=tuple(dict(item) for item in issues),
    )


def _review_state(
    *,
    all_approved: bool,
    signoff_current: bool = False,
) -> dict[str, Any]:
    requirement = {
        "approval_key": "pmq:Base:revenue_growth",
        "scope": "scenario_driver:Base:revenue_growth",
        "status": "approved" if all_approved else "pending",
    }
    return {
        "requirements": [requirement],
        "events": [],
        "counts": {requirement["status"]: 1},
        "required_count": 1,
        "approved_count": int(all_approved),
        "all_approved": all_approved,
        "evidence_issues": [],
        "signoff": {
            "status": "signed_off" if signoff_current else "pending",
            "current": signoff_current,
            "stale_reasons": [],
        },
    }


def test_live_msft_summary_matches_the_exact_review_contract(
    live_artifacts: review.ProfessionalModelArtifacts,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        review,
        "discover_professional_model_artifacts",
        lambda *_args, **_kwargs: live_artifacts,
    )
    monkeypatch.setattr(review, "_load_review_events", lambda _ticker: [])

    summary = review.build_professional_model_summary("MSFT")

    assert summary["ticker"] == "MSFT"
    assert summary["model_run_id"] == 3
    assert summary["normalized_state"] == "BLOCKED"
    assert summary["reported_workbook_status"] == "BLOCKED"
    assert summary["decision_readiness"] is False
    assert summary["reported_decision_ready"] is False
    assert summary["artifact_identity"]["verified"] is True
    assert summary["artifact_identity"]["issues"] == []
    assert summary["calculation_verification"]["verified"] is True
    assert summary["calculation_verification"]["status"] == "VERIFIED"
    assert summary["calculation_verification"]["reasons"] == []
    assert summary["calculation_verification"]["formula_count"] == 17_089
    assert summary["blockers"]["total"] == 133
    assert summary["blockers"]["counts"] == {
        "mechanical": 1,
        "source": 2,
        "market_data": 1,
        "pm_review": 123,
        "package": 6,
    }
    assert summary["review"] == {
        "required_count": 123,
        "approved_count": 0,
        "counts": {"pending": 123},
        "signoff": {
            "status": "pending",
            "current": False,
            "event_id": None,
            "actor": None,
            "signed_at": None,
            "workbook_hash": None,
            "stale_reasons": [],
        },
    }
    assert [sheet["name"] for sheet in summary["sheets"]] == EXPECTED_SHEETS
    assert len(summary["sheets"]) == 26
    assert summary["download_url"] == (
        "/api/tickers/MSFT/professional-model/download"
    )
    assert summary["permitted_actions"] == {
        "view_summary": True,
        "view_sheets": True,
        "download": True,
        "review_preview": True,
        "review_approve": False,
        "review_reject": True,
        "signoff": False,
        "rebuild": True,
    }
    assert summary["state_issues"] == []


def test_discovery_never_falls_back_when_the_newest_run_is_incomplete(
    tmp_path: Path,
) -> None:
    ticker_dir = tmp_path / "artifacts" / "MSFT"
    old_run = ticker_dir / "3"
    new_run = ticker_dir / "4"
    old_run.mkdir(parents=True)
    new_run.mkdir()
    for name in (
        "MSFT_professional_model_v2.xlsx",
        review.MANIFEST_NAME,
        review.QA_REPORT_NAME,
    ):
        (old_run / name).write_bytes(b"older-run-would-not-parse")
    (new_run / "MSFT_professional_model_v2.xlsx").write_bytes(b"newest")

    with pytest.raises(
        review.ProfessionalModelNotFoundError,
        match=r"newest professional model run is incomplete: .*manifest\.json.*qa_report\.json",
    ):
        review.discover_professional_model_artifacts(
            "MSFT",
            artifact_root=ticker_dir.parent,
        )


def test_discovery_flags_a_qa_hash_that_contradicts_the_exact_workbook(
    tmp_path: Path,
    live_artifacts: review.ProfessionalModelArtifacts,
) -> None:
    destination = tmp_path / "artifacts" / "MSFT" / "3"
    destination.mkdir(parents=True)
    workbook_path = destination / live_artifacts.workbook_path.name
    shutil.copy2(live_artifacts.workbook_path, workbook_path)
    shutil.copy2(live_artifacts.manifest_path, destination / review.MANIFEST_NAME)
    qa_report = json.loads(
        live_artifacts.qa_report_path.read_text(encoding="utf-8")
    )
    qa_report["workbook_sha256"] = "f" * 64
    qa_report["workbook"] = str(workbook_path)
    (destination / review.QA_REPORT_NAME).write_text(
        json.dumps(qa_report, sort_keys=True),
        encoding="utf-8",
    )

    discovered = review.discover_professional_model_artifacts(
        "MSFT",
        artifact_root=destination.parents[1],
    )

    assert discovered.workbook_hash == live_artifacts.workbook_hash
    assert [issue["code"] for issue in discovered.issues] == [
        "workbook_hash_mismatch"
    ]


@pytest.mark.parametrize(
    (
        "case",
        "blockers",
        "warnings",
        "reported_status",
        "decision_ready",
        "identity_issues",
        "all_approved",
        "signoff_current",
        "expected_state",
    ),
    [
        pytest.param(
            "identity",
            [],
            [],
            "READY",
            True,
            [{"code": "hash_mismatch", "detail": "synthetic"}],
            True,
            True,
            "UNVERIFIED",
            id="unverified",
        ),
        pytest.param(
            "source",
            ["source_preflight_blocked"],
            [],
            "BLOCKED",
            False,
            [],
            True,
            False,
            "BLOCKED",
            id="blocked",
        ),
        pytest.param(
            "pm",
            [],
            [],
            "READY",
            True,
            [],
            False,
            False,
            "NEEDS_PM_REVIEW",
            id="needs-pm-review",
        ),
        pytest.param(
            "package",
            [],
            ["segments_unavailable"],
            "READY",
            True,
            [],
            True,
            False,
            "PARTIAL",
            id="partial",
        ),
        pytest.param(
            "complete",
            [],
            [],
            "READY",
            True,
            [],
            True,
            True,
            "FULL",
            id="full",
        ),
    ],
)
def test_state_machine_truth_table_is_fail_closed(
    tmp_path: Path,
    case: str,
    blockers: list[str],
    warnings: list[str],
    reported_status: str,
    decision_ready: bool,
    identity_issues: list[dict[str, str]],
    all_approved: bool,
    signoff_current: bool,
    expected_state: str,
) -> None:
    del case
    artifacts = _synthetic_artifacts(
        tmp_path,
        blockers=blockers,
        warnings=warnings,
        reported_status=reported_status,
        decision_ready=decision_ready,
        issues=identity_issues,
    )

    result = review._evaluate_state(
        artifacts,
        {"verified": True, "reasons": []},
        _review_state(
            all_approved=all_approved,
            signoff_current=signoff_current,
        ),
    )

    assert result["normalized_state"] == expected_state
    assert result["decision_readiness"] is (expected_state == "FULL")
    if expected_state == "FULL":
        assert result["pre_signoff_ready"] is True
    if expected_state == "UNVERIFIED":
        assert "hash_mismatch" in result["state_issues"]


@pytest.mark.parametrize(
    ("reported_status", "expected_issue"),
    [
        pytest.param(None, "unknown_reported_status:blank", id="missing"),
        pytest.param("", "unknown_reported_status:blank", id="blank"),
        pytest.param(
            "not-a-real-state",
            "unknown_reported_status:NOT-A-REAL-STATE",
            id="unknown",
        ),
    ],
)
def test_blank_or_unknown_reported_status_is_unverified(
    tmp_path: Path,
    reported_status: Any,
    expected_issue: str,
) -> None:
    result = review._evaluate_state(
        _synthetic_artifacts(tmp_path, reported_status=reported_status),
        {"verified": True, "reasons": []},
        _review_state(all_approved=True, signoff_current=True),
    )

    assert result["normalized_state"] == "UNVERIFIED"
    assert result["decision_readiness"] is False
    assert expected_issue in result["state_issues"]


@pytest.mark.parametrize(
    ("check_status", "expected_suffix"),
    [
        pytest.param(None, "blank", id="missing"),
        pytest.param("", "blank", id="blank"),
        pytest.param("maybe", "MAYBE", id="unknown"),
    ],
)
def test_blank_or_unknown_check_status_is_unverified(
    tmp_path: Path,
    check_status: Any,
    expected_suffix: str,
) -> None:
    result = review._evaluate_state(
        _synthetic_artifacts(
            tmp_path,
            checks=[{"check_id": "source_preflight", "status": check_status}],
        ),
        {"verified": True, "reasons": []},
        _review_state(all_approved=True, signoff_current=True),
    )

    assert result["normalized_state"] == "UNVERIFIED"
    assert result["decision_readiness"] is False
    assert (
        f"unknown_check_status:source_preflight:{expected_suffix}"
        in result["state_issues"]
    )


def test_blockers_are_deduplicated_and_grouped_by_control_domain() -> None:
    grouped = review.group_professional_model_blockers(
        [
            "formula_reference_errors:1",
            "formula_reference_errors:1",
            "source_formula_errors:1",
            "source_formula_errors:1",
            "source_preflight_blocked",
            "source_preflight_blocked",
            "balance_sheet_delta:5",
            "wacc_degraded:fallback",
            "valuation_input_gate",
            "pm_approval_required:Base:revenue_growth:pmq:Base:revenue_growth",
            "source_or_pm_required:segment.revenue",
            "mystery_gate",
            "",
        ]
    )

    assert {key: grouped[key] for key in ("groups", "counts", "total")} == {
        "groups": {
            "mechanical": ["formula_reference_errors:1"],
            "source": ["source_formula_errors:1", "source_preflight_blocked"],
            "accounting": ["balance_sheet_delta:5"],
            "market_data": ["wacc_degraded:fallback"],
            "valuation": ["valuation_input_gate"],
            "pm_review": [
                "pm_approval_required:Base:revenue_growth:pmq:Base:revenue_growth"
            ],
            "package": ["source_or_pm_required:segment.revenue"],
            "unknown": ["blank_blocker", "mystery_gate"],
        },
        "counts": {
            "mechanical": 1,
            "source": 2,
            "accounting": 1,
            "market_data": 1,
            "valuation": 1,
            "pm_review": 1,
            "package": 1,
            "unknown": 2,
        },
        "total": 10,
    }
    assert grouped["raw_total"] == 13
    assert grouped["normalized_root_cause_count"] == 9
    root_causes = grouped["root_causes"]
    root_ids = [root["root_cause_id"] for root in root_causes]
    assert len(root_ids) == len(set(root_ids)) == grouped[
        "normalized_root_cause_count"
    ]
    formula_root = next(
        root
        for root in root_causes
        if root["root_cause_id"] == "source_formula_reference_errors"
    )
    assert formula_root == {
        "root_cause_id": "source_formula_reference_errors",
        "symptoms": [
            "formula_reference_errors:1",
            "source_formula_errors:1",
        ],
        "groups": ["mechanical", "source"],
        "occurrence_count": 4,
        "approvable": False,
    }
    source_preflight_root = next(
        root
        for root in root_causes
        if root["root_cause_id"] == "source_preflight"
    )
    assert source_preflight_root == {
        "root_cause_id": "source_preflight",
        "symptoms": ["source_preflight_blocked"],
        "groups": ["source"],
        "occurrence_count": 2,
        "approvable": False,
    }


def test_sheet_access_rejects_invalid_ticker_and_sheet_paths(
    live_artifacts: review.ProfessionalModelArtifacts,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(
        review.ProfessionalModelValidationError,
        match="invalid ticker",
    ):
        review.build_professional_model_sheet_payload("../MSFT", "Cover")

    monkeypatch.setattr(
        review,
        "discover_professional_model_artifacts",
        lambda *_args, **_kwargs: live_artifacts,
    )
    for sheet_name in ("../Cover", r"C:\\private\\model.xlsx", "Not_A_Sheet"):
        with pytest.raises(
            review.ProfessionalModelNotFoundError,
            match="professional model sheet not found",
        ):
            review.build_professional_model_sheet_payload("MSFT", sheet_name)
    with pytest.raises(
        review.ProfessionalModelValidationError,
        match="invalid sheet_name",
    ):
        review.build_professional_model_sheet_payload("MSFT", "")


def test_review_service_requires_preview_and_rejects_a_stale_fingerprint(
    live_artifacts: review.ProfessionalModelArtifacts,
    isolated_review_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        review,
        "discover_professional_model_artifacts",
        lambda *_args, **_kwargs: live_artifacts,
    )
    approval_key = "pmq:Base:revenue_growth"

    with pytest.raises(
        review.ProfessionalModelConflictError,
        match="approval requires a persisted preview",
    ):
        review.approve_professional_model_review(
            "MSFT",
            preview_id=999,
            reviewed_value_fingerprint="0" * 64,
            actor="pm-reviewer",
        )

    preview = review.preview_professional_model_review(
        "MSFT",
        approval_key=approval_key,
        reviewed_values=[0.11, 0.10, 0.09, 0.08, 0.07],
        actor="pm-reviewer",
        rationale="Exact five-year path reviewed",
    )
    with pytest.raises(
        review.ProfessionalModelConflictError,
        match="reviewed-value fingerprint changed after preview",
    ):
        review.approve_professional_model_review(
            "MSFT",
            preview_id=preview["preview_id"],
            reviewed_value_fingerprint="0" * 64,
            actor="pm-reviewer",
        )

    approved = review.approve_professional_model_review(
        "MSFT",
        preview_id=preview["preview_id"],
        reviewed_value_fingerprint=preview["reviewed_value_fingerprint"],
        actor="pm-reviewer",
        rationale="Approved after preview",
    )

    assert approved["state"] == "approved"
    assert approved["preview_id"] == preview["preview_id"]
    assert approved["reviewed_value_fingerprint"] == preview[
        "reviewed_value_fingerprint"
    ]
    with get_connection(isolated_review_db) as conn:
        events = list_professional_model_review_events(
            conn,
            ticker="MSFT",
            model_run_id=live_artifacts.model_run_id,
            approval_key=approval_key,
            approval_scope="scenario_driver:Base:revenue_growth",
        )
    assert [event["event_type"] for event in events] == ["preview", "approve"]
    assert events[1]["parent_event_id"] == events[0]["event_id"]
    assert events[1]["reviewed_value_fingerprint"] == preview[
        "reviewed_value_fingerprint"
    ]


def test_final_signoff_is_blocked_for_the_current_msft_artifact(
    live_artifacts: review.ProfessionalModelArtifacts,
    isolated_review_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del isolated_review_db
    monkeypatch.setattr(
        review,
        "discover_professional_model_artifacts",
        lambda *_args, **_kwargs: live_artifacts,
    )

    with pytest.raises(
        review.ProfessionalModelConflictError,
        match="final sign-off is blocked until every other FULL-state requirement passes",
    ):
        review.signoff_professional_model(
            "MSFT",
            workbook_sha256=live_artifacts.workbook_hash,
            actor="pm-reviewer",
            rationale="Attempting exact-workbook sign-off",
        )


class _ManifestStub:
    def __init__(self, payload: Mapping[str, Any]) -> None:
        self.payload = dict(payload)

    def model_dump(self, *, mode: str) -> dict[str, Any]:
        assert mode == "json"
        return dict(self.payload)


def test_full_rebuild_hashes_the_workbook_before_persisting_review_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts = _synthetic_artifacts(tmp_path)
    order: list[str] = []
    captured: dict[str, Any] = {}
    rebuilt_manifest = {
        "source_hash": SOURCE_HASH,
        "model_input_hash": INPUT_HASH,
        "result_hash": RESULT_HASH,
        "manifest_hash": MANIFEST_HASH,
        "blockers": [],
        "warnings": [],
    }

    monkeypatch.setattr(
        review,
        "discover_professional_model_artifacts",
        lambda *_args, **_kwargs: artifacts,
    )
    monkeypatch.setattr(review, "_current_db_path", lambda: tmp_path / "db.sqlite")
    monkeypatch.setattr(
        review,
        "_resolve_rebuild_source_workbook",
        lambda _artifacts: tmp_path / "source.xlsx",
    )
    monkeypatch.setattr(
        review,
        "_resolve_frozen_valuation_json",
        lambda _artifacts: (
            tmp_path / "valuation.json",
            {"sha256": "8" * 64, "timestamp": "2026-07-12T00:00:00Z"},
        ),
    )
    consumed_event = {
        "scope": "scenario_driver:Base:revenue_growth",
        "approval_key": "pmq:Base:revenue_growth",
        "event_id": 17,
        "reviewed_value_fingerprint": "9" * 64,
        "reviewed_values": [0.11, 0.10, 0.09, 0.08, 0.07],
    }
    monkeypatch.setattr(
        review,
        "_build_approved_forecast_bundle",
        lambda _artifacts, *, db_path: (
            {"approved": "bundle"},
            {
                "required": 1,
                "approved": 1,
                "consumed": 1,
                "consumed_approval_events": [consumed_event],
            },
        ),
    )

    def _fake_builder(**kwargs: Any) -> SimpleNamespace:
        order.append("build")
        output_dir = Path(kwargs["output_dir"]) / "MSFT" / "3"
        output_dir.mkdir(parents=True)
        workbook_path = output_dir / "MSFT_professional_model_v2.xlsx"
        workbook_path.write_bytes(b"exact rebuilt workbook bytes")
        manifest_path = output_dir / review.MANIFEST_NAME
        manifest_path.write_text("{}", encoding="utf-8")
        return SimpleNamespace(
            output_dir=output_dir,
            workbook_path=workbook_path,
            manifest_path=manifest_path,
            manifest=_ManifestStub(rebuilt_manifest),
        )

    monkeypatch.setitem(
        sys.modules,
        "src.stage_04_pipeline.professional_model_adapter",
        SimpleNamespace(build_professional_model_v2=_fake_builder),
    )

    def _hash_workbook(path: Path) -> str:
        order.append("hash")
        assert path.read_bytes() == b"exact rebuilt workbook bytes"
        return "a" * 64

    monkeypatch.setattr(review, "_sha256_file", _hash_workbook)

    def _persist(
        supplied_artifacts: review.ProfessionalModelArtifacts,
        **kwargs: Any,
    ) -> dict[str, Any]:
        order.append("persist")
        captured.update(kwargs)
        assert supplied_artifacts is artifacts
        assert order == ["build", "hash", "persist"]
        assert kwargs["built_workbook_hash"] == "a" * 64
        assert kwargs["built_output_dir"].joinpath(
            review.REVIEW_EVIDENCE_NAME
        ).exists() is False
        return {"review_evidence_sha256": EVIDENCE_FILE_HASH}

    monkeypatch.setattr(review, "_persist_rebuild_review_evidence", _persist)

    result = review.rebuild_professional_model(
        "MSFT",
        model_run_id=3,
        actor="pm-reviewer",
        rationale="Rebuild exact approved paths",
        tracker_run_id="order-proof",
        rebuild_root=tmp_path / "rebuilds",
    )

    assert order == ["build", "hash", "persist"]
    assert captured["consumed_events"] == [consumed_event]
    assert captured["built_manifest"] == rebuilt_manifest
    assert result["artifact_identity"]["workbook_sha256"] == "a" * 64
    assert result["review_inputs"]["evidence"] == {
        "review_evidence_sha256": EVIDENCE_FILE_HASH
    }
    assert result["status"] == "built_calculation_pending"
    assert result["promotion_ready"] is False


class _SignoffConnection:
    def __init__(self, order: list[str]) -> None:
        self.order = order
        self.committed = False
        self.rolled_back = False

    def __enter__(self) -> _SignoffConnection:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, statement: str) -> None:
        assert statement == "BEGIN IMMEDIATE"
        self.order.append("begin")

    def commit(self) -> None:
        self.order.append("commit")
        self.committed = True

    def rollback(self) -> None:
        self.order.append("rollback")
        self.rolled_back = True


def test_successful_signoff_refreshes_twice_and_binds_exact_evidence_file_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts = _synthetic_artifacts(
        tmp_path,
        review_evidence_file_hash=EVIDENCE_FILE_HASH,
    )
    order: list[str] = []
    connection = _SignoffConnection(order)
    inserted: dict[str, Any] = {}
    current_events = [{"event_id": 40, "state": "approved"}]

    monkeypatch.setattr(
        review,
        "discover_professional_model_artifacts",
        lambda *_args, **_kwargs: artifacts,
    )
    monkeypatch.setattr(review, "get_connection", lambda: connection)
    monkeypatch.setattr(
        review,
        "create_tables",
        lambda _conn: order.append("create_tables"),
    )

    refresh_count = 0

    def _refresh(
        expected: review.ProfessionalModelArtifacts,
        *,
        artifact_root: str | Path | None,
    ) -> review.ProfessionalModelArtifacts:
        nonlocal refresh_count
        assert expected is artifacts
        assert artifact_root is None
        refresh_count += 1
        order.append(f"refresh_{refresh_count}")
        return artifacts

    monkeypatch.setattr(review, "_refresh_actionable_artifact", _refresh)

    def _list_events(
        supplied_connection: _SignoffConnection,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        assert supplied_connection is connection
        assert kwargs == {"ticker": "MSFT", "model_run_id": 3}
        order.append("list_events")
        return current_events

    def _insert_event(
        supplied_connection: _SignoffConnection,
        row: dict[str, Any],
    ) -> int:
        assert supplied_connection is connection
        order.append("insert_event")
        inserted.update(row)
        return 41

    def _load_event(
        supplied_connection: _SignoffConnection,
        event_id: int,
    ) -> dict[str, Any]:
        assert supplied_connection is connection
        assert event_id == 41
        order.append("load_event")
        return {"event_id": 41, "created_at": "2026-07-12T12:00:00+00:00"}

    monkeypatch.setattr(
        "db.loader.list_professional_model_review_events",
        _list_events,
    )
    monkeypatch.setattr(
        "db.loader.insert_professional_model_review_event",
        _insert_event,
    )
    monkeypatch.setattr(
        "db.loader.load_professional_model_review_event",
        _load_event,
    )
    monkeypatch.setattr(
        review,
        "_calculation_verification",
        lambda _artifacts: order.append("calculation")
        or {"verified": True, "reasons": []},
    )
    monkeypatch.setattr(
        review,
        "_review_state_for_artifact",
        lambda _artifacts, *, events: order.append("review_state")
        or {
            "requirements": [{"status": "approved"}],
            "all_approved": True,
            "signoff": {"current": False},
        },
    )
    monkeypatch.setattr(
        review,
        "_evaluate_state",
        lambda _artifacts, _calculation, _review_state: order.append("evaluate")
        or {"pre_signoff_ready": True},
    )

    response = review.signoff_professional_model(
        "MSFT",
        workbook_sha256=WORKBOOK_HASH,
        actor="pm-reviewer",
        rationale="All gates reviewed for this exact evidence file",
    )

    expected_reviewed_values = {
        "workbook_sha256": WORKBOOK_HASH,
        "qa_report_sha256": QA_HASH,
        "review_evidence_sha256": EVIDENCE_FILE_HASH,
    }
    expected_fingerprint = review._canonical_hash(
        {
            "fingerprint_version": review.REVIEW_FINGERPRINT_VERSION,
            "approval_key": review.FINAL_SIGNOFF_KEY,
            "scope": review.FINAL_SIGNOFF_SCOPE,
            "reviewed_values": expected_reviewed_values,
        }
    )
    assert refresh_count == 2
    assert order == [
        "create_tables",
        "begin",
        "refresh_1",
        "list_events",
        "calculation",
        "review_state",
        "evaluate",
        "insert_event",
        "refresh_2",
        "commit",
        "load_event",
    ]
    assert connection.committed is True
    assert connection.rolled_back is False
    assert inserted["event_type"] == "signoff"
    assert inserted["state"] == "signed_off"
    assert inserted["approval_key"] == review.FINAL_SIGNOFF_KEY
    assert inserted["approval_scope"] == review.FINAL_SIGNOFF_SCOPE
    assert inserted["workbook_hash"] == WORKBOOK_HASH
    assert inserted["qa_hash"] == QA_HASH
    assert inserted["review_evidence_hash"] == EVIDENCE_FILE_HASH
    assert inserted["reviewed_values"] == expected_reviewed_values
    assert inserted["reviewed_value_fingerprint"] == expected_fingerprint
    assert inserted["parent_event_id"] == 40
    assert response["review_evidence_sha256"] == EVIDENCE_FILE_HASH
    assert response["signoff_fingerprint"] == expected_fingerprint
    assert response["normalized_state"] == "FULL"
