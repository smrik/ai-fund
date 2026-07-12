from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


SCRIPT_PATH = Path("scripts/manual/review_react_route_matrix.py")
MODULE_NAME = "review_react_route_matrix_contract_test"


@pytest.fixture(scope="module")
def route_matrix():
    spec = importlib.util.spec_from_file_location(MODULE_NAME, SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


def test_normalizes_live_professional_model_summary_contract(route_matrix):
    payload = {
        "ticker": "MSFT",
        "model_run_id": 3,
        "normalized_state": "BLOCKED",
        "decision_readiness": False,
        "hashes": {
            "source_sha256": "a" * 64,
            "workbook_sha256": "b" * 64,
        },
        "calculation_verification": {
            "verified": False,
            "status": "UNVERIFIED",
        },
        "blockers": {
            "groups": {
                "source": ["source_formula_errors:2"],
                "pm_review": [
                    "pm_approval_required:Base:revenue_growth",
                    "pm_approval_required:Upside:revenue_growth",
                ],
            },
            "counts": {"source": 1, "pm_review": 2},
            "total": 3,
        },
        "sheets": [{"name": f"Sheet {index}"} for index in range(26)],
    }

    assert route_matrix.normalize_professional_model_summary(payload) == {
        "state": "BLOCKED",
        "decision_ready": False,
        "source_run_id": "3",
        "source_hash": "a" * 64,
        "workbook_hash": "b" * 64,
        "calculation_status": "UNVERIFIED",
        "blocker_count": 3,
        "sheet_count": 26,
    }


def test_structured_blocker_count_accepts_consistent_empty_contract(route_matrix):
    assert route_matrix.professional_model_blocker_count(
        {"blockers": {"groups": {}, "counts": {}, "total": 0}}
    ) == 0


@pytest.mark.parametrize(
    "blockers",
    [
        {
            "groups": {"source": ["source_formula_errors:2"]},
            "counts": {"source": 2},
            "total": 2,
        },
        {
            "groups": {"source": ["source_formula_errors:2"]},
            "counts": {"source": 1},
            "total": 2,
        },
        {
            "groups": {"source": ["source_formula_errors:2"]},
            "counts": {"pm_review": 1},
            "total": 1,
        },
    ],
)
def test_structured_blocker_count_rejects_internal_disagreement(
    route_matrix,
    blockers,
):
    with pytest.raises(RuntimeError, match="blocker"):
        route_matrix.professional_model_blocker_count({"blockers": blockers})


def test_normalizer_preserves_legacy_frontend_shaped_contract(route_matrix):
    payload = {
        "state": "PARTIAL",
        "decision_ready": False,
        "decision_readiness": "Not ready because package evidence is incomplete.",
        "artifact": {
            "source_run_id": 2,
            "source_hash": "c" * 64,
            "workbook_hash": "d" * 64,
        },
        "calculation_verification": {"verified": True},
        "blocker_groups": [
            {"category": "other", "blockers": [{"reason_code": "gap"}]}
        ],
        "sheets": [{"name": "Cover"}],
    }

    assert route_matrix.normalize_professional_model_summary(payload) == {
        "state": "PARTIAL",
        "decision_ready": False,
        "source_run_id": "2",
        "source_hash": "c" * 64,
        "workbook_hash": "d" * 64,
        "calculation_status": "VERIFIED",
        "blocker_count": 1,
        "sheet_count": 1,
    }
