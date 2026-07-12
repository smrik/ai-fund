from __future__ import annotations

from dataclasses import dataclass

from ciq.source_evidence import (
    build_model_evidence_records,
    build_source_evidence_records,
    summarize_evidence_layers,
)


def _fact(**overrides):
    row = {
        "ticker": "MSFT",
        "sheet_name": "Financial Statements",
        "row_index": 12,
        "column_index": 6,
        "source_row_id": "Financial Statements!12",
        "row_label": "Total Revenues",
        "period_date": "2025-06-30",
        "cell_locator": "Financial Statements!F12",
        "cached_value": 100.0,
        "value_num": 100.0,
        "unit": "USD",
        "scale_factor": 1_000_000.0,
        "formula_text": "=SUM(F8:F11)",
        "formula_status": "formula_cached",
        "formula_error": None,
        "cached_error": None,
        "has_formula": True,
        "has_cached_value": True,
    }
    row.update(overrides)
    return row


def test_source_projection_separates_raw_normalized_and_repair_layers() -> None:
    ledger = {
        "repairs": [
            {
                "cell_locator": "Financial Statements!F12",
                "original_formula": "=SUM(F8:#REF!)",
                "repaired_formula": "=SUM(F8:F11)",
                "refresh_verification_status": "unresolved_native_ciq_unavailable",
            }
        ]
    }
    records = build_source_evidence_records(
        [_fact()],
        source_hash="a" * 64,
        run_id=4,
        source_refresh_timestamp="2026-07-11T00:00:00Z",
        repair_ledger=ledger,
        downstream_consumers={"Financial Statements!F12": ["is.revenue", "dcf.revenue"]},
    )

    assert records == [
        {
            "schema_version": "ciq_source_evidence_v1",
            "evidence_layer": "source_cell",
            "ticker": "MSFT",
            "run_id": 4,
            "source_hash": "a" * 64,
            "raw_cached_value": 100.0,
            "normalized_model_value": 100.0,
            "derived_value": None,
            "transformation_rule": "numeric_cast;retain_source_display_scale:1e+06",
            "sign_rule": "source_sign_preserved",
            "source_formula": "=SUM(F8:#REF!)",
            "repaired_formula": "=SUM(F8:F11)",
            "formula_error_state": {
                "status": "formula_cached",
                "formula_error": None,
                "cached_error": None,
                "has_formula": True,
                "has_cached_value": True,
                "refresh_verification": "unresolved_native_ciq_unavailable",
            },
            "unit": "USD",
            "unit_provenance": "source_parser",
            "scale": 1_000_000.0,
            "scale_provenance": "source_parser",
            "source_period": "2025-06-30",
            "source_period_end": "2025-06-30",
            "source_refresh_timestamp": "2026-07-11T00:00:00Z",
            "exact_source_locator": "Financial Statements!F12",
            "source_row_id": "Financial Statements!12",
            "row_label": "Total Revenues",
            "downstream_consumers": ["dcf.revenue", "is.revenue"],
        }
    ]


def test_source_projection_marks_missing_unit_scale_contract_unverified() -> None:
    records = build_source_evidence_records(
        [_fact(unit=None, scale_factor=1.0)],
        source_hash="a" * 64,
        run_id=4,
        source_refresh_timestamp="2026-07-11T00:00:00Z",
    )
    summary = summarize_evidence_layers(records, [])

    assert records[0]["unit"] is None
    assert records[0]["unit_provenance"] == "source_unit_unavailable"
    assert records[0]["scale"] == 1.0
    assert (
        records[0]["scale_provenance"]
        == "parser_scale_without_unit_contract_unverified"
    )
    assert summary["source_unit_unavailable_count"] == 1
    assert summary["source_scale_unverified_count"] == 1


@dataclass(frozen=True)
class Ref:
    cell_locator: str


@dataclass(frozen=True)
class Lineage:
    canonical_key: str
    period_key: str
    method_id: str
    formula_id: str | None
    normalized_value: float | None
    normalization_rule: str
    source_refs: tuple[Ref, ...]


def test_model_projection_exposes_derived_and_sign_normalized_layers() -> None:
    source = build_source_evidence_records(
        [_fact(has_formula=False, formula_text=None, formula_status="literal")],
        source_hash="b" * 64,
        run_id=4,
        source_refresh_timestamp="2026-07-11T00:00:00Z",
    )
    lineage = [
        Lineage(
            "is.revenue",
            "FY2025",
            "historical:direct",
            None,
            100.0,
            "source_sign_preserved",
            (Ref("Financial Statements!F12"),),
        ),
        Lineage(
            "is.cost_of_revenue",
            "FY2025",
            "historical:direct",
            None,
            -40.0,
            "negative=-abs(source)",
            (Ref("Financial Statements!F12"),),
        ),
        Lineage(
            "is.gross_profit",
            "FY2025",
            "historical:derived",
            "gross_profit=revenue+cost_of_revenue",
            60.0,
            "derived_identity",
            (Ref("Financial Statements!F12"),),
        ),
    ]

    model = build_model_evidence_records(
        lineage,
        source_evidence=source,
        unit_by_canonical_key={"is.revenue": "USD mm"},
        source_refresh_timestamp="2026-07-11T00:00:00Z",
    )
    summary = summarize_evidence_layers(source, model)

    gross_profit = next(row for row in model if row["canonical_key"] == "is.gross_profit")
    assert gross_profit["derived_value"] == 60.0
    assert gross_profit["source_formula"] == ["gross_profit=revenue+cost_of_revenue"]
    assert summary["model_direct_value_count"] == 2
    assert summary["model_derived_value_count"] == 1
    assert summary["model_sign_normalized_count"] == 1
