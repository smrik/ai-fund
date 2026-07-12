from __future__ import annotations

from ciq.source_evidence import build_source_evidence_records
from ciq.source_identity import _dependency_index


def test_formula_repair_dependency_shape_projects_machine_consumers() -> None:
    payload = {
        "cells": [
            {
                "cell_locator": "Detailed Comps!AC3",
                "direct_formula_dependents": [],
                "transitive_formula_dependents": [],
                "non_cell_consumers": [
                    {"kind": "defined_name", "name": "_xlnm.Print_Area"}
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
            "defined_name:_xlnm.Print_Area",
            "module:comps",
            "persisted:ciq_comps_snapshot",
        )
    }


def test_repair_refresh_verification_status_is_preserved() -> None:
    fact = {
        "ticker": "MSFT",
        "sheet_name": "Detailed Comps",
        "row_index": 3,
        "column_index": 29,
        "source_row_id": "Detailed Comps!3",
        "row_label": "NasdaqGS:NVDA",
        "period_date": None,
        "cell_locator": "Detailed Comps!AC3",
        "cached_value": 19.99757,
        "value_num": 19.99757,
        "unit": None,
        "scale_factor": 1.0,
        "formula_text": "=CIQ(...,$C3)",
        "formula_status": "formula_cached",
        "formula_error": None,
        "cached_error": None,
        "has_formula": True,
        "has_cached_value": True,
    }
    records = build_source_evidence_records(
        [fact],
        source_hash="a" * 64,
        run_id=4,
        source_refresh_timestamp="2026-07-11",
        repair_ledger={
            "repairs": [
                {
                    "cell_locator": "Detailed Comps!AC3",
                    "original_formula": "=CIQ(...,#REF!)",
                    "repaired_formula": "=CIQ(...,$C3)",
                    "refresh_verification_status": "unresolved",
                }
            ]
        },
    )

    assert records[0]["formula_error_state"]["refresh_verification"] == "unresolved"
