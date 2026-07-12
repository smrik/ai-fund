from __future__ import annotations

from pathlib import Path

import pytest

from ciq.formula_repair import (
    FormulaRepairError,
    TARGET_CELLS,
    TARGET_SHEET,
    _write_repaired_package,
    build_dependency_map,
    inspect_workbook,
    load_repair_ledger,
    query_repair_ledger,
    repair_workbook,
    repaired_formula_for,
    sha256_file,
)
from ciq.workbook_parser import parse_ciq_workbook


MSFT_SOURCE = Path("data/exports/MSFT_Standard.xlsx")
MSFT_SOURCE_SHA256 = "413c51b4e976c6c4c61e7c616c6ff51f839a77ad8443bd0be8883b9d6c630411"


def _repair_paths(root: Path, suffix: str = "") -> tuple[Path, Path, Path]:
    return (
        root / f"MSFT_Standard_formula_repaired{suffix}.xlsx",
        root / f"MSFT_Standard_formula_repair_ledger{suffix}.json",
        root / f"MSFT_Standard_formula_dependency_map{suffix}.json",
    )


def test_msft_repair_is_deterministic_cache_preserving_and_parser_usable(tmp_path: Path) -> None:
    assert MSFT_SOURCE.exists()
    assert sha256_file(MSFT_SOURCE) == MSFT_SOURCE_SHA256
    source_hash_before = sha256_file(MSFT_SOURCE)
    derived, ledger_path, dependency_path = _repair_paths(tmp_path)
    second_derived, second_ledger, second_dependency = _repair_paths(tmp_path, "_second")

    ledger = repair_workbook(
        MSFT_SOURCE,
        derived,
        ledger_path=ledger_path,
        dependency_map_path=dependency_path,
        generated_at="2026-07-12T00:00:00Z",
    )
    second = repair_workbook(
        MSFT_SOURCE,
        second_derived,
        ledger_path=second_ledger,
        dependency_map_path=second_dependency,
        generated_at="2026-07-12T00:00:00Z",
    )

    assert sha256_file(MSFT_SOURCE) == source_hash_before == MSFT_SOURCE_SHA256
    assert ledger["source_workbook"]["sha256"] == MSFT_SOURCE_SHA256
    assert ledger["derived_workbook"]["sha256"] == second["derived_workbook"]["sha256"]
    assert ledger["repair_scope"]["repair_count"] == 24
    assert ledger["source_formula_state"]["formula_error_count"] == 24
    assert ledger["derived_formula_state"]["formula_error_count"] == 0
    assert ledger["structural_verification"]["target_formula_errors_remaining"] == []
    assert ledger["structural_verification"]["all_cached_values_byte_preserved"] is True
    assert ledger["structural_verification"]["all_untouched_formulas_logically_preserved"] is True
    assert ledger["structural_verification"]["changed_ooxml_parts"] == [
        inspect_workbook(MSFT_SOURCE)["sheet_parts"][TARGET_SHEET]
    ]
    assert ledger["refresh_verification"]["status"] == "unresolved"

    repairs = ledger["repairs"]
    assert {item["a1_locator"] for item in repairs} == set(TARGET_CELLS)
    assert sum(isinstance(item["cached_value"], (int, float)) for item in repairs) == 20
    assert sum(item["cached_value"] == "NM" for item in repairs) == 4
    assert all(item["original_formula_error"] == "#REF!" for item in repairs)
    assert all(item["original_cached_error"] is None for item in repairs)
    assert all(item["repaired_formula_error"] is None for item in repairs)
    assert all(item["pattern_evidence"]["candidate_matches_translated_anchor"] for item in repairs)

    source_payload = parse_ciq_workbook(MSFT_SOURCE)
    derived_payload = parse_ciq_workbook(derived)
    assert derived_payload.rows_parsed == source_payload.rows_parsed
    source_facts = {
        row["a1_locator"]: row
        for row in source_payload.long_form_records
        if row["sheet_name"] == TARGET_SHEET and row["a1_locator"] in TARGET_CELLS
    }
    derived_facts = {
        row["a1_locator"]: row
        for row in derived_payload.long_form_records
        if row["sheet_name"] == TARGET_SHEET and row["a1_locator"] in TARGET_CELLS
    }
    assert derived_facts.keys() == source_facts.keys()
    for coordinate in TARGET_CELLS:
        assert derived_facts[coordinate]["cached_value"] == source_facts[coordinate]["cached_value"]
        assert derived_facts[coordinate]["formula_error"] is None
        assert derived_facts[coordinate]["formula_status"] == "formula_cached"


def test_msft_dependencies_are_comps_only_and_not_dcf_or_wacc() -> None:
    dependency_map = build_dependency_map(MSFT_SOURCE)

    assert dependency_map["summary"]["target_cell_count"] == 24
    assert dependency_map["summary"]["classification"] == "comps_only"
    assert dependency_map["summary"]["affects_comps"] is True
    assert dependency_map["summary"]["affects_dcf"] is False
    assert dependency_map["summary"]["affects_wacc"] is False
    assert dependency_map["summary"]["cells_with_direct_formula_dependents"] == 0
    assert dependency_map["summary"]["cells_with_transitive_formula_dependents"] == 0
    assert dependency_map["summary"]["cells_with_layout_consumers"] == 24
    assert dependency_map["summary"]["cells_with_computational_non_cell_consumers"] == 0
    assert dependency_map["summary"]["active_computation_consumer_count"] == 0
    assert {
        cell["context"]["metric_key"] for cell in dependency_map["cells"]
    } == {"tev_total_revenue_fy", "tev_ebitda_fy", "pe_fy"}
    assert all(cell["workbook_scope"] == "comps_only" for cell in dependency_map["cells"])
    assert all(cell["pipeline"]["affects_dcf"] is False for cell in dependency_map["cells"])
    assert all(cell["pipeline"]["affects_wacc"] is False for cell in dependency_map["cells"])
    assert all(cell["pipeline"]["active_computation_consumer"] is False for cell in dependency_map["cells"])
    assert all(cell["pipeline"]["unmapped_by_current_ciq_adapter"] is True for cell in dependency_map["cells"])


def test_ledger_loader_and_query_hook_expose_repaired_formula(tmp_path: Path) -> None:
    derived, ledger_path, dependency_path = _repair_paths(tmp_path)
    repair_workbook(
        MSFT_SOURCE,
        derived,
        ledger_path=ledger_path,
        dependency_map_path=dependency_path,
        generated_at="2026-07-12T00:00:00Z",
    )

    ledger = load_repair_ledger(ledger_path)
    record = query_repair_ledger(ledger, sheet_name=TARGET_SHEET, a1_locator="ac3")

    assert record is not None
    assert record["original_formula"].endswith(",#REF!)")
    assert record["cached_value"] == pytest.approx(19.99757)
    assert repaired_formula_for(ledger, sheet_name=TARGET_SHEET, a1_locator="AC3") == record["repaired_formula"]
    assert record["repaired_formula"].endswith(",$C3)")


def test_repair_fails_closed_when_row_two_anchor_is_not_proven(tmp_path: Path) -> None:
    source_inspection = inspect_workbook(MSFT_SOURCE)
    anchor = source_inspection["snapshots"][TARGET_SHEET]["AC2"]
    assert anchor.formula is not None
    broken_anchor = anchor.formula.replace("$C2", "$D2")
    assert broken_anchor != anchor.formula
    invalid_source = tmp_path / "MSFT_invalid_anchor.xlsx"
    _write_repaired_package(
        MSFT_SOURCE,
        invalid_source,
        source_inspection["sheet_parts"][TARGET_SHEET],
        [
            {
                "a1_locator": "AC2",
                "cell_locator": f"{TARGET_SHEET}!AC2",
                "original_formula": anchor.formula,
                "repaired_formula": broken_anchor,
            }
        ],
        overwrite=False,
    )

    with pytest.raises(FormulaRepairError, match="Anchor final argument"):
        repair_workbook(
            invalid_source,
            tmp_path / "must_not_exist.xlsx",
            generated_at="2026-07-12T00:00:00Z",
        )
