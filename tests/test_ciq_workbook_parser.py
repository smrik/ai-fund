from __future__ import annotations

import json
from pathlib import Path

import pytest

from ciq.workbook_parser import parse_ciq_workbook
from tests.ciq_test_utils import create_ibm_style_workbook


def test_valuation_snapshot_ignores_common_size_duplicate_metric_rows(tmp_path: Path) -> None:
    workbook_path = create_ibm_style_workbook(tmp_path / "TEST_Standard.xlsx")

    from openpyxl import load_workbook

    wb = load_workbook(workbook_path)
    cs = wb["Common Size"]
    cs["A13"] = "Total Revenues"
    cs["D13"] = 1.0
    cs["E13"] = 1.0
    cs["F13"] = 1.0
    wb.save(workbook_path)

    payload = parse_ciq_workbook(workbook_path)
    snapshot = payload.valuation_snapshot

    assert snapshot["revenue_mm"] == 1200
    assert snapshot["ebit_margin"] == pytest.approx(150 / 1200)
    assert snapshot["revenue_cagr_3yr"] == pytest.approx(0.10)


def test_valuation_snapshot_prefers_real_row_over_zero_placeholder_duplicate(tmp_path: Path) -> None:
    """Real CIQ exports repeat 'Depreciation & Amort.' as a zero-filled placeholder.

    The placeholder collides with the cash-flow row on (period, column), so the dedupe
    must keep the row that carries a value. Picking the zero silently drops D&A from
    the DCF add-back while capex is still subtracted.
    """
    workbook_path = create_ibm_style_workbook(tmp_path / "TEST_Standard.xlsx")

    from openpyxl import load_workbook

    wb = load_workbook(workbook_path)
    fs = wb["Financial Statements"]
    fs["A122"] = "Depreciation & Amort."
    fs["D122"] = 0
    fs["E122"] = 0
    fs["F122"] = 0
    wb.save(workbook_path)

    snapshot = parse_ciq_workbook(workbook_path).valuation_snapshot

    assert snapshot["da_mm"] == 22
    # FY-only average of the two reported periods: 20/1000 and 21/1100.
    assert snapshot["da_pct_avg_3yr"] == pytest.approx((20 / 1000 + 21 / 1100) / 2)


def test_committed_cleandata_workbook_has_plausible_ciq_growth_snapshot() -> None:
    payload = parse_ciq_workbook("ciq/templates/ciq_cleandata.xlsx")
    snapshot = payload.valuation_snapshot

    assert snapshot["ticker"] == payload.ticker
    assert snapshot["revenue_mm"] is not None
    assert snapshot["revenue_cagr_3yr"] is not None
    assert -1.0 < snapshot["revenue_cagr_3yr"] < 1.0


def test_committed_cleandata_classifies_all_three_statements_with_metadata() -> None:
    payload = parse_ciq_workbook("ciq/templates/ciq_cleandata.xlsx")
    records = [
        row
        for row in payload.long_form_records
        if row["sheet_name"] == "Financial Statements"
    ]
    assert all(row["section_name"] != "Uncategorized" for row in records)

    by_label = {
        (row["section_name"], row["row_label"]): row
        for row in records
        if row["period_date"] == "2025-05-31"
    }
    revenue = by_label[("Income Statement", "Total Revenues")]
    capex = by_label[("Cash Flow Statement", "Capital Expenditure")]
    assets = by_label[("Balance Sheet", "Total Assets")]

    for row in (revenue, capex, assets):
        assert row["unit"] == "USD"
        assert row["scale_factor"] == 1_000_000.0
        assert row["period_kind"] == "annual"
        assert row["currency"] == "USD"
    assert revenue["period_start"] == "2024-06-01"
    assert capex["period_start"] == "2024-06-01"
    assert assets["period_start"] is None


def test_committed_cleandata_emits_stable_completed_coverage_manifest() -> None:
    first = parse_ciq_workbook("ciq/templates/ciq_cleandata.xlsx")
    second = parse_ciq_workbook("ciq/templates/ciq_cleandata.xlsx")
    manifest = first.coverage_manifest

    assert json.loads(json.dumps(manifest)) == manifest
    assert manifest["contract_version"] == "ciq_statement_coverage_v1"
    assert manifest["manifest_id"].startswith("sha256:")
    assert manifest["manifest_id"] == second.coverage_manifest["manifest_id"]
    assert manifest["ticker"] == first.ticker
    assert manifest["source"] == "ciq_workbook_v1"
    assert manifest["source_run_id"] is None
    assert manifest["status"] == "completed"
    assert manifest["as_of_date"] == "2025-11-29"
    assert manifest["evidence_cutoff"] == "2026-03-29"
    assert manifest["errors"] == []

    da_entry = next(
        entry
        for entry in manifest["coverage"]["entries"].values()
        if entry["statement"] == "CashFlowStatement"
        and entry["canonical_role"] == "da"
        and entry["period_end"] == "2025-05-31"
    )
    assert da_entry == {
        "statement": "CashFlowStatement",
        "statement_role": "ciq:Financial Statements:CashFlowStatement",
        "canonical_role": "da",
        "canonical_roles": ["da"],
        "period_start": "2024-06-01",
        "period_end": "2025-05-31",
        "period_kind": "annual",
        "period_type": "duration",
        "fiscal_year": 2025,
        "fiscal_period": "FY",
        "unit": "USD",
        "currency": "USD",
        "scale_factor": 1_000_000.0,
        "presented_fact_count": 1,
        "completion_status": "completed",
        "source_locator": (
            "ciq_cleandata.xlsx#Financial Statements/"
            "CashFlowStatement/2025-05-31"
        ),
    }


def test_workbook_rejects_unknown_scale_conversion(
    tmp_path: Path,
) -> None:
    from openpyxl import load_workbook

    workbook_path = create_ibm_style_workbook(
        tmp_path / "UNKNOWN_SCALE.xlsx"
    )
    wb = load_workbook(workbook_path)
    input_sheet = wb.create_sheet("Input")
    input_sheet["B2"] = "NYSE:TEST"
    input_sheet["B7"] = "USD"
    wb["Input"]["B8"] = "UNKNOWN"
    wb.save(workbook_path)

    from ciq.workbook_parser import CIQTemplateContractError

    with pytest.raises(
        CIQTemplateContractError,
        match="Unsupported CIQ conversion code",
    ):
        parse_ciq_workbook(workbook_path)
