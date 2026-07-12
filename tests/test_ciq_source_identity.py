from __future__ import annotations

import pytest

from ciq.source_identity import (
    SourceIdentityError,
    _dependency_index,
    _verify_source_fact_integrity,
    attach_preflight_identity,
    validate_preflight_identity,
)


def _manifest(generated_at: str = "2026-07-12T00:00:00Z") -> dict:
    return {
        "schema_version": "professional_model_preflight_v1",
        "generated_at": generated_at,
        "ticker": "MSFT",
        "status": "ready",
        "blockers": [],
        "source": {
            "source_file": "MSFT_repaired.xlsx",
            "sha256": "a" * 64,
            "run_id": 4,
            "ingest_ts": "2026-07-12T00:00:00Z",
            "status": "completed",
            "workbook_as_of_date": "2026-03-31",
            "workbook_refresh_date": "2026-07-11",
        },
        "parser": {
            "parser_version": "ibm_standard_v4",
            "rows_parsed": 8601,
            "template_fingerprint": {"sheets": ["Financial Statements"]},
        },
        "workbook": {"formula_error_count": 0, "cached_error_count": 0},
    }


def test_preflight_hash_is_stable_across_generation_timestamps() -> None:
    first = attach_preflight_identity(_manifest("2026-07-12T00:00:00Z"))
    second = attach_preflight_identity(_manifest("2026-07-12T01:00:00Z"))

    assert first["identity"]["preflight_hash"] == second["identity"]["preflight_hash"]
    assert first["identity"]["preflight_generated_at"] != second["identity"]["preflight_generated_at"]
    validate_preflight_identity(first)
    validate_preflight_identity(second)


def test_stale_run_or_parser_identity_is_rejected() -> None:
    manifest = attach_preflight_identity(_manifest())
    manifest["identity"]["run_id"] = 3

    with pytest.raises(SourceIdentityError, match="inconsistent"):
        validate_preflight_identity(manifest)


def test_ready_identity_requires_zero_formula_errors() -> None:
    manifest = _manifest()
    manifest["workbook"]["formula_error_count"] = 1
    identified = attach_preflight_identity(manifest)

    with pytest.raises(SourceIdentityError, match="zero source formula"):
        validate_preflight_identity(identified)


def test_dependency_index_reads_formula_repair_cells_payload() -> None:
    payload = {
        "cells": [
            {
                "sheet": "Detailed Comps",
                "cell": "AC3",
                "direct_formula_dependents": [],
                "transitive_formula_dependents": [],
                "non_cell_consumers": [
                    {"kind": "defined_name", "name": "Print_Area"},
                ],
                "pipeline": {
                    "primary_module_scope": "comps",
                    "persisted_surface": "ciq_comps_snapshot",
                },
            }
        ]
    }

    assert _dependency_index(payload) == {
        "Detailed Comps!AC3": (
            "defined_name:Print_Area",
            "module:comps",
            "persisted:ciq_comps_snapshot",
        )
    }


def test_source_fact_integrity_rejects_partial_or_mutated_persistence() -> None:
    identity = {"rows_parsed": 1}
    expected = [
        {
            "ticker": "MSFT",
            "sheet_name": "Financial Statements",
            "row_index": 12,
            "column_index": 6,
            "source_row_id": "Financial Statements!12",
            "a1_locator": "F12",
            "cell_locator": "Financial Statements!F12",
            "cached_value": 100.0,
            "value_num": 100.0,
            "has_formula": 1,
            "has_cached_value": 1,
            "formula_status": "formula_cached",
            "source_file": "MSFT_repaired.xlsx",
        }
    ]

    verified = _verify_source_fact_integrity(
        identity=identity,
        expected_facts=expected,
        persisted_facts=[dict(expected[0])],
    )
    assert verified["status"] == "verified"
    assert verified["persisted_row_count"] == 1

    with pytest.raises(SourceIdentityError, match="persisted source fact count"):
        _verify_source_fact_integrity(
            identity=identity,
            expected_facts=expected,
            persisted_facts=[],
        )

    mutated = [dict(expected[0], cached_value=99.0)]
    with pytest.raises(SourceIdentityError, match="content does not match"):
        _verify_source_fact_integrity(
            identity=identity,
            expected_facts=expected,
            persisted_facts=mutated,
        )
