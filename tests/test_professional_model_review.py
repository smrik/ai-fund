from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest

from db.loader import PROFESSIONAL_MODEL_REVIEW_FINGERPRINT_VERSION
from src.stage_04_pipeline import professional_model_review as review


SOURCE_HASH = "1" * 64
INPUT_HASH = "2" * 64
RESULT_HASH = "3" * 64
MANIFEST_HASH = "4" * 64
WORKBOOK_HASH = "5" * 64
OTHER_WORKBOOK_HASH = "6" * 64
QA_HASH = "7" * 64
EVIDENCE_FILE_HASH = "8" * 64
SCOPE = "scenario_driver:Base:revenue_growth"
APPROVAL_KEY = "pmq:Base:revenue_growth"
REVIEWED_VALUES = [0.10, 0.09, 0.08, 0.07, 0.06]
FORECAST_PERIODS = ("FY26E", "FY27E", "FY28E", "FY29E", "FY30E")
BLOCKER = f"pm_approval_required:Base:revenue_growth:{APPROVAL_KEY}"


def _artifact_hashes() -> dict[str, str]:
    return {
        "source_sha256": SOURCE_HASH,
        "model_input_sha256": INPUT_HASH,
        "result_sha256": RESULT_HASH,
        "manifest_sha256": MANIFEST_HASH,
        "workbook_sha256": WORKBOOK_HASH,
        "qa_report_sha256": QA_HASH,
        "review_evidence_sha256": EVIDENCE_FILE_HASH,
    }


def _requirement_contract() -> dict[str, Any]:
    return review.enrich_pm_driver_requirement(
        ticker="MSFT",
        model_run_id=3,
        artifact_hashes=_artifact_hashes(),
        forecast_periods=FORECAST_PERIODS,
        blocker_row={
            "row": 5,
            "sheet": "PM_Review_Queue",
            "code": BLOCKER,
        },
        scenario="Base",
        driver="revenue_growth",
        approval_key=APPROVAL_KEY,
        scope=SCOPE,
        canonical_hash_fn=review._canonical_hash,
    )


def _review_context() -> dict[str, Any]:
    requirement = _requirement_contract()
    return review.normalize_preview_review_context(
        {
            "source_ref": "https://example.test/evidence/17",
            "method": "PM selected exact five-year path",
            "as_of": "2026-07-12T10:00:00Z",
            "evidence_locator": requirement["evidence_locator"],
        }
    )


def _fingerprint(
    *,
    scope: str = SCOPE,
    approval_key: str = APPROVAL_KEY,
    reviewed_values: list[float] | None = None,
) -> str:
    requirement = _requirement_contract()
    context = _review_context()
    return review._canonical_hash(
        {
            "approval_key": approval_key,
            "fingerprint_version": PROFESSIONAL_MODEL_REVIEW_FINGERPRINT_VERSION,
            "reviewed_values": reviewed_values
            if reviewed_values is not None
            else REVIEWED_VALUES,
            "scope": scope,
            "requirement_hash": requirement["requirement_hash"],
            "review_context": context,
        }
    )


def _manifest(*, blockers: list[str] | None = None) -> dict[str, Any]:
    return {
        "source_hash": SOURCE_HASH,
        "model_input_hash": INPUT_HASH,
        "result_hash": RESULT_HASH,
        "manifest_hash": MANIFEST_HASH,
        "blockers": blockers
        if blockers is not None
        else [BLOCKER],
    }


def _artifacts(
    tmp_path: Path,
    *,
    manifest: dict[str, Any] | None = None,
    workbook_hash: str = WORKBOOK_HASH,
    evidence_file_hash: str | None = EVIDENCE_FILE_HASH,
) -> review.ProfessionalModelArtifacts:
    artifact_dir = tmp_path / "MSFT" / "3"
    return review.ProfessionalModelArtifacts(
        ticker="MSFT",
        model_run_id=3,
        artifact_dir=artifact_dir,
        workbook_path=artifact_dir / "MSFT_professional_model_v2.xlsx",
        manifest_path=artifact_dir / "manifest.json",
        qa_report_path=artifact_dir / "qa_report.json",
        manifest=manifest or _manifest(),
        review_evidence=None,
        qa_report={},
        workbook_hash=workbook_hash,
        qa_report_hash=QA_HASH,
        review_evidence_file_hash=evidence_file_hash,
        workbook_bytes=123,
        issues=(),
        forecast_periods=FORECAST_PERIODS,
    )


def _approval_event(
    *,
    event_id: int = 17,
    reviewed_values: list[float] | None = None,
) -> dict[str, Any]:
    values = list(reviewed_values or REVIEWED_VALUES)
    requirement = _requirement_contract()
    context = _review_context()
    return {
        "event_id": event_id,
        "created_at": "2026-07-12T10:00:00+00:00",
        "ticker": "MSFT",
        "model_run_id": 3,
        "approval_key": APPROVAL_KEY,
        "approval_scope": SCOPE,
        "event_type": "approve",
        "state": "approved",
        "reviewed_values": values,
        "reviewed_value_fingerprint": _fingerprint(reviewed_values=values),
        "input_hash": INPUT_HASH,
        "result_hash": RESULT_HASH,
        "source_hash": SOURCE_HASH,
        "manifest_hash": MANIFEST_HASH,
        "workbook_hash": WORKBOOK_HASH,
        "qa_hash": QA_HASH,
        "review_evidence_hash": None,
        "actor": "pm-user",
        "rationale": "Reviewed exact path",
        "parent_event_id": 16,
        "supersedes_event_id": 16,
        "metadata": {
            "fingerprint_version": PROFESSIONAL_MODEL_REVIEW_FINGERPRINT_VERSION,
            "requirement_hash": requirement["requirement_hash"],
            "review_context": context,
            "review_context_complete": True,
        },
    }


def _consumed_event(
    *,
    event_id: int = 17,
    reviewed_values: list[float] | None = None,
    reviewed_value_fingerprint: str | None = None,
) -> dict[str, Any]:
    values = list(reviewed_values or REVIEWED_VALUES)
    requirement = _requirement_contract()
    context = _review_context()
    return {
        "scope": SCOPE,
        "approval_key": APPROVAL_KEY,
        "event_id": event_id,
        "reviewed_value_fingerprint": reviewed_value_fingerprint
        or _fingerprint(reviewed_values=values),
        "reviewed_values": values,
        "approval_artifact_identity": {
            "model_run_id": 3,
            "source_sha256": SOURCE_HASH,
            "model_input_sha256": INPUT_HASH,
            "result_sha256": RESULT_HASH,
            "workbook_sha256": WORKBOOK_HASH,
        },
        "requirement_hash": requirement["requirement_hash"],
        "requirement_contract": requirement,
        "review_context": context,
    }


def _review_evidence_payload(*, workbook_hash: str = WORKBOOK_HASH) -> dict[str, Any]:
    events = [_consumed_event()]
    inventory = [
        {
            "scope": SCOPE,
            "approval_key": APPROVAL_KEY,
            "requirement_hash": events[0]["requirement_hash"],
        }
    ]
    payload: dict[str, Any] = {
        "schema_version": "1.0.0",
        "fingerprint_version": PROFESSIONAL_MODEL_REVIEW_FINGERPRINT_VERSION,
        "ticker": "MSFT",
        "model_run_id": 3,
        "artifact_identity": {
            "source_sha256": SOURCE_HASH,
            "model_input_sha256": INPUT_HASH,
            "result_sha256": RESULT_HASH,
            "workbook_sha256": workbook_hash,
        },
        "approval_event_count": len(events),
        "required_approval_identities": inventory,
        "required_approval_inventory_hash": review._canonical_hash(inventory),
        "approval_set_hash": review._canonical_hash(events),
        "consumed_approval_events": events,
    }
    payload["review_evidence_hash"] = review._canonical_hash(payload)
    return payload


class _TransactionConnection:
    def __init__(self) -> None:
        self.transaction_started = False
        self.committed = False
        self.rolled_back = False

    def __enter__(self) -> _TransactionConnection:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, statement: str) -> None:
        assert statement == "BEGIN IMMEDIATE"
        assert not self.transaction_started
        self.transaction_started = True

    def commit(self) -> None:
        assert self.transaction_started
        self.committed = True

    def rollback(self) -> None:
        assert self.transaction_started
        self.rolled_back = True


def test_review_evidence_canonical_hash_binds_exact_workbook_sha256() -> None:
    evidence = _review_evidence_payload()

    assert review._validate_review_evidence(
        evidence,
        ticker="MSFT",
        model_run_id=3,
        manifest=_manifest(),
        workbook_hash=WORKBOOK_HASH,
    ) == []

    stale_workbook_evidence = _review_evidence_payload(
        workbook_hash=OTHER_WORKBOOK_HASH
    )
    assert (
        stale_workbook_evidence["review_evidence_hash"]
        != evidence["review_evidence_hash"]
    )
    assert review._canonical_hash(
        {
            key: value
            for key, value in evidence.items()
            if key != "review_evidence_hash"
        }
    ) == evidence["review_evidence_hash"]


def test_review_evidence_rejects_stale_workbook_even_if_payload_is_resigned() -> None:
    stale_workbook_evidence = _review_evidence_payload(
        workbook_hash=OTHER_WORKBOOK_HASH
    )

    issues = review._validate_review_evidence(
        stale_workbook_evidence,
        ticker="MSFT",
        model_run_id=3,
        manifest=_manifest(),
        workbook_hash=WORKBOOK_HASH,
    )

    assert issues == ["review_evidence_workbook_sha256_mismatch"]


def test_review_evidence_detects_workbook_tamper_without_recomputed_hash() -> None:
    evidence = _review_evidence_payload()
    evidence["artifact_identity"]["workbook_sha256"] = OTHER_WORKBOOK_HASH

    issues = review._validate_review_evidence(
        evidence,
        ticker="MSFT",
        model_run_id=3,
        manifest=_manifest(),
        workbook_hash=WORKBOOK_HASH,
    )

    assert issues == [
        "review_evidence_hash_mismatch",
        "review_evidence_workbook_sha256_mismatch",
    ]


def test_final_signoff_becomes_stale_when_exact_workbook_changes(tmp_path: Path) -> None:
    artifacts = _artifacts(tmp_path)
    event = {
        **_approval_event(),
        "approval_scope": review.FINAL_SIGNOFF_SCOPE,
        "approval_key": review.FINAL_SIGNOFF_KEY,
        "event_type": "signoff",
        "state": "signed_off",
        "reviewed_values": {"workbook_sha256": OTHER_WORKBOOK_HASH},
        "workbook_hash": OTHER_WORKBOOK_HASH,
    }
    event["reviewed_value_fingerprint"] = review._canonical_hash(
        {
            "approval_key": review.FINAL_SIGNOFF_KEY,
            "fingerprint_version": PROFESSIONAL_MODEL_REVIEW_FINGERPRINT_VERSION,
            "reviewed_values": event["reviewed_values"],
            "scope": review.FINAL_SIGNOFF_SCOPE,
        }
    )
    event["review_evidence_hash"] = EVIDENCE_FILE_HASH

    assert review._event_stale_reasons(event, artifacts) == [
        "workbook_hash_changed"
    ]


def test_final_signoff_becomes_stale_when_only_evidence_file_hash_changes(
    tmp_path: Path,
) -> None:
    original_artifacts = _artifacts(tmp_path)
    event = {
        **_approval_event(),
        "approval_scope": review.FINAL_SIGNOFF_SCOPE,
        "approval_key": review.FINAL_SIGNOFF_KEY,
        "event_type": "signoff",
        "state": "signed_off",
        "reviewed_values": {"workbook_sha256": WORKBOOK_HASH},
        "review_evidence_hash": EVIDENCE_FILE_HASH,
    }
    event["reviewed_value_fingerprint"] = review._canonical_hash(
        {
            "approval_key": review.FINAL_SIGNOFF_KEY,
            "fingerprint_version": PROFESSIONAL_MODEL_REVIEW_FINGERPRINT_VERSION,
            "reviewed_values": event["reviewed_values"],
            "scope": review.FINAL_SIGNOFF_SCOPE,
        }
    )
    assert review._event_stale_reasons(event, original_artifacts) == []

    changed_evidence_artifacts = _artifacts(
        tmp_path, evidence_file_hash="9" * 64
    )
    assert review._event_stale_reasons(event, changed_evidence_artifacts) == [
        "review_evidence_hash_changed"
    ]


def test_load_json_snapshot_parses_and_hashes_one_exact_byte_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot = tmp_path / "snapshot.json"
    raw = b'{  "ticker": "MSFT", "nested": {"count": 3}  }\r\n'
    snapshot.write_bytes(raw)
    original_read_bytes = Path.read_bytes
    reads: list[Path] = []

    def _counted_read_bytes(path: Path) -> bytes:
        reads.append(path)
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", _counted_read_bytes)

    payload, snapshot_hash = review._load_json_snapshot(
        snapshot, "test JSON snapshot"
    )

    assert reads == [snapshot]
    assert payload == {"ticker": "MSFT", "nested": {"count": 3}}
    assert snapshot_hash == sha256(raw).hexdigest()


def test_rebuild_persists_workbook_bound_evidence_after_locked_event_reload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = _artifacts(tmp_path)
    output_dir = tmp_path / "rebuild" / "MSFT" / "3"
    output_dir.mkdir(parents=True)
    conn = _TransactionConnection()
    observed: dict[str, Any] = {}
    current_event = _approval_event()

    def _list_events(
        supplied_connection: _TransactionConnection,
        *,
        ticker: str,
        model_run_id: int,
    ) -> list[dict[str, Any]]:
        assert supplied_connection is conn
        assert conn.transaction_started
        observed.update(ticker=ticker, model_run_id=model_run_id)
        return [current_event]

    monkeypatch.setattr(review, "get_connection", lambda: conn)
    monkeypatch.setattr(
        review,
        "_expected_driver_approval_identities",
        lambda: {(SCOPE, APPROVAL_KEY)},
    )
    monkeypatch.setattr(
        "db.loader.list_professional_model_review_events", _list_events
    )

    proof = review._persist_rebuild_review_evidence(
        artifacts,
        consumed_events=[_consumed_event()],
        built_manifest=_manifest(blockers=[]),
        built_workbook_hash=OTHER_WORKBOOK_HASH,
        built_output_dir=output_dir,
    )

    assert observed == {"ticker": "MSFT", "model_run_id": 3}
    assert conn.committed is True
    assert conn.rolled_back is False
    evidence_path = output_dir / review.REVIEW_EVIDENCE_NAME
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert evidence["artifact_identity"]["workbook_sha256"] == OTHER_WORKBOOK_HASH
    assert proof == {
        "review_evidence_sha256": review._sha256_file(evidence_path),
        "review_evidence_hash": evidence["review_evidence_hash"],
        "approval_set_hash": evidence["approval_set_hash"],
        "required_approval_inventory_hash": evidence[
            "required_approval_inventory_hash"
        ],
        "approval_event_count": 1,
    }
    assert review._validate_review_evidence(
        evidence,
        ticker="MSFT",
        model_run_id=3,
        manifest=_manifest(blockers=[]),
        workbook_hash=OTHER_WORKBOOK_HASH,
    ) == []


@pytest.mark.parametrize(
    "consumed_event,current_event",
    [
        pytest.param(
            _consumed_event(event_id=17),
            _approval_event(event_id=18),
            id="later-approval-event",
        ),
        pytest.param(
            _consumed_event(reviewed_value_fingerprint="9" * 64),
            _approval_event(),
            id="fingerprint-changed",
        ),
        pytest.param(
            _consumed_event(reviewed_values=[0.11, 0.09, 0.08, 0.07, 0.06]),
            _approval_event(),
            id="reviewed-values-changed",
        ),
    ],
)
def test_rebuild_aborts_when_consumed_approval_no_longer_exactly_matches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    consumed_event: dict[str, Any],
    current_event: dict[str, Any],
) -> None:
    artifacts = _artifacts(tmp_path)
    output_dir = tmp_path / "rebuild" / "MSFT" / "3"
    output_dir.mkdir(parents=True)
    conn = _TransactionConnection()

    def _list_events(
        supplied_connection: _TransactionConnection,
        **_kwargs: Any,
    ) -> list[dict[str, Any]]:
        assert supplied_connection is conn
        assert conn.transaction_started
        return [current_event]

    monkeypatch.setattr(review, "get_connection", lambda: conn)
    monkeypatch.setattr(
        review,
        "_expected_driver_approval_identities",
        lambda: {(SCOPE, APPROVAL_KEY)},
    )
    monkeypatch.setattr(
        "db.loader.list_professional_model_review_events", _list_events
    )

    with pytest.raises(
        review.ProfessionalModelConflictError,
        match="consumed professional-model approval changed during rebuild",
    ):
        review._persist_rebuild_review_evidence(
            artifacts,
            consumed_events=[consumed_event],
            built_manifest=_manifest(blockers=[]),
            built_workbook_hash=OTHER_WORKBOOK_HASH,
            built_output_dir=output_dir,
        )

    assert conn.rolled_back is True
    assert conn.committed is False
    assert not (output_dir / review.REVIEW_EVIDENCE_NAME).exists()


def test_malformed_pm_blocker_cannot_vacuously_satisfy_approval_gate(
    tmp_path: Path,
) -> None:
    artifacts = _artifacts(
        tmp_path,
        manifest=_manifest(blockers=["pm_approval_required:Base:revenue_growth"]),
    )

    state = review._review_state_for_artifact(artifacts, events=[])

    assert state["requirements"] == []
    assert state["required_count"] == 0
    assert state["approved_count"] == 0
    assert state["all_approved"] is False
    assert state["evidence_issues"] == [
        "malformed_pm_approval_blocker",
        "pm_approval_requirement_count_mismatch",
    ]


@pytest.mark.parametrize(
    "kwargs",
    [
        pytest.param({"start_row": 0}, id="non-positive-row"),
        pytest.param({"start_column": 0}, id="non-positive-column"),
        pytest.param({"row_limit": review.MAX_SHEET_ROWS + 1}, id="row-cap"),
        pytest.param(
            {"column_limit": review.MAX_SHEET_COLUMNS + 1}, id="column-cap"
        ),
        pytest.param(
            {"row_limit": 101, "column_limit": 50}, id="cell-window-cap"
        ),
    ],
)
def test_sheet_bounds_fail_before_artifact_discovery(
    tmp_path: Path, kwargs: dict[str, int]
) -> None:
    with pytest.raises(review.ProfessionalModelValidationError):
        review.build_professional_model_sheet_payload(
            "MSFT",
            "Cover",
            artifact_root=tmp_path,
            **kwargs,
        )


def test_workbook_text_redaction_preserves_web_urls_and_hides_local_paths() -> None:
    assert review._redact_workbook_text(
        "https://example.test/source.xlsx", limit=200
    ) == "https://example.test/source.xlsx"
    assert review._redact_workbook_text(
        r"C:\Users\analyst\source.xlsx", limit=200
    ) == "[redacted filesystem path]"
    assert review._redact_workbook_text(
        r"\\server\share\source.xlsx", limit=200
    ) == "[redacted filesystem path]"
    assert review._redact_workbook_text(
        "/home/analyst/source.xlsx", limit=200
    ) == "[redacted filesystem path]"
