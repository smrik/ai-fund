from __future__ import annotations

from copy import deepcopy

import pytest

from src.stage_04_pipeline import professional_model_review_contract as contract


HASHES = {
    "source_sha256": "1" * 64,
    "model_input_sha256": "2" * 64,
    "result_sha256": "3" * 64,
    "manifest_sha256": "4" * 64,
    "workbook_sha256": "5" * 64,
    "qa_report_sha256": "6" * 64,
    "review_evidence_sha256": None,
}
PERIODS = ["FY26E", "FY27E", "FY28E", "FY29E", "FY30E"]


def _requirement(**overrides):
    values = {
        "ticker": "msft",
        "model_run_id": 3,
        "artifact_hashes": HASHES,
        "forecast_periods": PERIODS,
        "blocker_row": {
            "row": 7,
            "sheet": "PM_Review_Queue",
            "coordinate": "C7",
            "code": (
                "pm_approval_required:Base:revenue_growth:"
                "pmq:Base:revenue_growth"
            ),
        },
        "scenario": "Base",
        "driver": "revenue_growth",
        "approval_key": "pmq:Base:revenue_growth",
        "scope": "scenario_driver:Base:revenue_growth",
    }
    values.update(overrides)
    return contract.enrich_pm_driver_requirement(**values)


def _semantic_evidence(check_id: str) -> dict:
    content = {
        "schema": "professional_model_semantic_qa_v1",
        "source": f"qa:{check_id}",
        "method": "exact positive-list semantic verification",
        "as_of": "2026-06-30",
        "details": {"check_id": check_id, "conclusion": "supported"},
    }
    return {**content, "evidence_hash": contract.canonical_hash(content)}


def _passing_checks(core_ids: tuple[str, ...]) -> list[dict]:
    checks = [
        {"check_id": check_id, "status": "PASS"}
        for check_id in core_ids
    ]
    checks.extend(
        {
            "check_id": check_id,
            "status": "PASS",
            "semantic_evidence": _semantic_evidence(check_id),
        }
        for check_id in contract.SEMANTIC_QA_CHECK_IDS
    )
    return checks


def test_enriches_known_driver_with_exact_identity_and_stable_review_metadata() -> None:
    requirement = _requirement()

    assert requirement["ticker"] == "MSFT"
    assert requirement["model_run_id"] == 3
    assert requirement["artifact_identity"] == HASHES
    assert requirement["approval_key"] == "pmq:Base:revenue_growth"
    assert requirement["scope"] == "scenario_driver:Base:revenue_growth"
    assert requirement["unit"] == "percent"
    assert requirement["module"] == "revenue"
    assert requirement["forecast_periods"] == PERIODS
    assert requirement["required_value_shape"] == {
        "type": "number_array",
        "length": 5,
        "periods": PERIODS,
    }
    assert requirement["artifact_current_path"] is None
    assert requirement["artifact_current_path_status"] == "unavailable"
    assert requirement["proposed_path"] is None
    assert requirement["proposed_path_status"] == "not_provided"
    assert requirement["materiality"] is None
    assert requirement["impact"] == {"status": "not_provided"}
    assert requirement["downstream_dependencies"] == sorted(
        requirement["downstream_dependencies"]
    )
    assert "dcf.fcff" in requirement["downstream_dependencies"]
    assert requirement["evidence_locator"] == {
        "url": (
            "/api/tickers/MSFT/professional-model/sheets/PM_Review_Queue?"
            "start_row=7&start_column=3&row_limit=1&column_limit=1"
        ),
        "sheet": "PM_Review_Queue",
        "coordinate": "C7",
    }
    assert requirement["contract_issues"] == []
    assert requirement["approvable"] is True

    unsigned = {key: value for key, value in requirement.items() if key != "requirement_hash"}
    assert requirement["requirement_hash"] == contract.canonical_hash(unsigned)
    assert _requirement() == requirement


def test_enrichment_fails_closed_for_unknown_driver_or_invalid_period_axis() -> None:
    unknown = _requirement(
        driver="invented_margin",
        approval_key="pmq:Base:invented_margin",
        scope="scenario_driver:Base:invented_margin",
        blocker_row={
            "row": 12,
            "code": (
                "pm_approval_required:Base:invented_margin:"
                "pmq:Base:invented_margin"
            ),
        },
    )
    assert unknown["approvable"] is False
    assert unknown["unit"] is None
    assert unknown["module"] is None
    assert "unknown_runtime_driver" in unknown["contract_issues"]
    assert "driver_review_metadata_unavailable" in unknown["contract_issues"]

    bad_periods = _requirement(forecast_periods=["FY26E"] * 5)
    assert bad_periods["approvable"] is False
    assert bad_periods["contract_issues"] == ["forecast_period_axis_invalid"]
    assert bad_periods["artifact_current_path"] is None


def test_enrichment_rejects_non_pm_or_mismatched_blocker_identity() -> None:
    requirement = _requirement(
        blocker_row={
            "row": 5,
            "coordinate": "C5",
            "code": "historical:source_dependent_modules_unavailable",
        }
    )
    assert requirement["approvable"] is False
    assert "blocker_code_mismatch" in requirement["contract_issues"]


def test_preview_review_context_is_canonical_bounded_and_path_safe() -> None:
    raw = {
        "impact": {"direction": "up", "affected_outputs": ["DCF", "EPS"]},
        "materiality": {"unit": "percent", "classification": "high"},
        "as_of": "2026-07-12T14:00:00+02:00",
        "method": "PM selected exact five-year path",
        "source_ref": "https://example.test/evidence/123",
        "evidence_locator": {
            "coordinate": "c7",
            "sheet": "PM_Review_Queue",
            "url": (
                "/api/tickers/MSFT/professional-model/sheets/PM_Review_Queue?"
                "start_row=7&start_column=3&row_limit=1&column_limit=1"
            ),
        },
        "downstream_dependencies": ["dcf.fcff", "shares_eps", "dcf.fcff"],
    }
    normalized = contract.normalize_preview_review_context(raw)

    assert normalized == {
        "source_ref": "https://example.test/evidence/123",
        "method": "PM selected exact five-year path",
        "as_of": "2026-07-12T12:00:00Z",
        "evidence_locator": {
            "url": raw["evidence_locator"]["url"],
            "sheet": "PM_Review_Queue",
            "coordinate": "C7",
        },
        "materiality": {"classification": "high", "unit": "percent"},
        "impact": {"affected_outputs": ["DCF", "EPS"], "direction": "up"},
        "downstream_dependencies": ["dcf.fcff", "shares_eps"],
    }
    assert contract.normalize_preview_review_context(None) == {
        "source_ref": None,
        "method": None,
        "as_of": None,
        "evidence_locator": None,
        "materiality": None,
        "impact": None,
        "downstream_dependencies": [],
    }


@pytest.mark.parametrize(
    "review_context",
    [
        {"source_ref": r"C:\Users\analyst\review.xlsx"},
        {"method": "loaded from /home/analyst/review.json"},
        {"impact": {"source": r"..\private\review.csv"}},
        {"evidence_locator": "file:///tmp/review.json"},
        {"source_ref": "data/review.json"},
    ],
)
def test_preview_review_context_rejects_local_filesystem_paths(
    review_context: dict,
) -> None:
    with pytest.raises(
        contract.ProfessionalModelReviewContractError,
        match=r"filesystem paths|HTTP\(S\)",
    ):
        contract.normalize_preview_review_context(review_context)


def test_preview_review_context_rejects_unknown_keys_and_oversize() -> None:
    with pytest.raises(
        contract.ProfessionalModelReviewContractError,
        match="unknown keys",
    ):
        contract.normalize_preview_review_context({"reviewer_override": True})

    with pytest.raises(
        contract.ProfessionalModelReviewContractError,
        match="oversized",
    ):
        contract.normalize_preview_review_context({"method": "x" * 2_001})


def test_decision_semantic_qa_verification_requires_exact_positive_list() -> None:
    core_ids = ("source_preflight", "formula_cache", "calculation_marker")
    checks = list(reversed(_passing_checks(core_ids)))

    verification = contract.build_decision_semantic_qa_verification(
        checks,
        required_core_ids=core_ids,
    )

    required = sorted((*core_ids, *contract.SEMANTIC_QA_CHECK_IDS))
    assert verification == {
        "verified": True,
        "reasons": [],
        "required": required,
        "observed": required,
        "failed": [],
    }


def test_decision_semantic_qa_verification_rejects_duplicates_unknowns_and_nonpass() -> None:
    core_ids = ("source_preflight", "formula_cache")
    checks = _passing_checks(core_ids)
    checks.append({"check_id": "source_preflight", "status": "PASS"})
    checks.append({"check_id": "model_readiness", "status": "PASS"})
    next(item for item in checks if item["check_id"] == "formula_cache")["status"] = "BLOCKED"

    verification = contract.build_decision_semantic_qa_verification(
        checks,
        required_core_ids=core_ids,
    )

    assert verification["verified"] is False
    assert "qa_check_id_duplicate:source_preflight" in verification["reasons"]
    assert "qa_check_set_unknown:model_readiness" in verification["reasons"]
    assert (
        "qa_check_status_not_pass:formula_cache:BLOCKED"
        in verification["reasons"]
    )
    assert verification["failed"] == ["formula_cache", "source_preflight"]


def test_decision_semantic_qa_verification_rejects_missing_or_tampered_evidence() -> None:
    core_ids = ("source_preflight",)
    checks = _passing_checks(core_ids)
    by_id = {item["check_id"]: item for item in checks}
    by_id["wacc_parity"]["semantic_evidence"]["details"]["conclusion"] = "tampered"
    del by_id["share_basis"]["semantic_evidence"]
    by_id["as_of_alignment"]["semantic_evidence"]["unexpected"] = True

    verification = contract.build_decision_semantic_qa_verification(
        checks,
        required_core_ids=core_ids,
    )

    assert verification["verified"] is False
    assert "semantic_evidence_hash_mismatch:wacc_parity" in verification["reasons"]
    assert "semantic_evidence_missing:share_basis" in verification["reasons"]
    assert "semantic_evidence_keys_invalid:as_of_alignment" in verification["reasons"]
    assert verification["failed"] == [
        "as_of_alignment",
        "share_basis",
        "wacc_parity",
    ]


def test_semantic_evidence_hash_uses_supplied_canonical_hash_callback() -> None:
    core_ids = ("source_preflight",)
    checks = _passing_checks(core_ids)
    calls: list[dict] = []

    def callback(value):
        calls.append(deepcopy(value))
        return contract.canonical_hash(value)

    verification = contract.build_decision_semantic_qa_verification(
        checks,
        required_core_ids=core_ids,
        canonical_hash_fn=callback,
    )

    assert verification["verified"] is True
    assert len(calls) == len(contract.SEMANTIC_QA_CHECK_IDS)
    assert all("evidence_hash" not in value for value in calls)
