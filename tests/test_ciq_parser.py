import sys
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest
from openpyxl import load_workbook

from ciq.workbook_parser import CIQTemplateContractError, parse_ciq_workbook
from ciq_test_utils import create_ibm_style_workbook


def test_parse_ciq_workbook_returns_payload(tmp_path):
    workbook = create_ibm_style_workbook(tmp_path / "TEST_Standard.xlsx")

    payload = parse_ciq_workbook(workbook)

    assert payload.ticker == "TEST"
    assert payload.rows_parsed > 0
    assert payload.valuation_snapshot["revenue_mm"] == 1200
    assert payload.valuation_snapshot["revenue_cagr_3yr"] is not None
    assert payload.valuation_snapshot["op_margin_avg_3yr"] is not None
    assert payload.comps_snapshot


def test_parse_ciq_workbook_enforces_template_lock(tmp_path):
    workbook = create_ibm_style_workbook(tmp_path / "BROKEN.xlsx", break_anchor=True)

    with pytest.raises(CIQTemplateContractError):
        parse_ciq_workbook(workbook)


def test_parse_ciq_workbook_keeps_unknown_metrics(tmp_path):
    workbook = create_ibm_style_workbook(tmp_path / "UNKNOWN.xlsx", include_unknown=True)

    payload = parse_ciq_workbook(workbook)

    unknown = [r for r in payload.long_form_records if r["row_label"] == "My Custom KPI"]
    assert unknown
    assert unknown[0]["metric_key"] == "my_custom_kpi"


def test_parse_cleandata_workbook_contract_and_snapshots():
    workbook = Path("ciq/templates/ciq_cleandata.xlsx")
    payload = parse_ciq_workbook(workbook)

    assert payload.ticker == "IBM"
    assert payload.rows_parsed > 0

    snap = payload.valuation_snapshot
    assert snap["revenue_mm"] is not None
    assert snap["op_margin_avg_3yr"] is not None
    assert snap["revenue_cagr_3yr"] is not None

    assert payload.comps_snapshot
    target_rows = [r for r in payload.comps_snapshot if r.get("is_target") == 1]
    assert target_rows


def test_parse_cleandata_ignores_trailing_formatted_columns():
    workbook = Path("ciq/templates/ciq_cleandata.xlsx")
    payload = parse_ciq_workbook(workbook)

    fs_cols = [
        r["column_index"] for r in payload.long_form_records if r["sheet_name"] == "Financial Statements"
    ]
    cs_cols = [
        r["column_index"] for r in payload.long_form_records if r["sheet_name"] == "Common Size"
    ]
    dc_cols = [
        r["column_index"] for r in payload.long_form_records if r["sheet_name"] == "Detailed Comps"
    ]

    assert fs_cols and max(fs_cols) <= 13
    assert cs_cols and max(cs_cols) <= 13
    assert dc_cols and max(dc_cols) <= 86


def test_parse_cleandata_disambiguates_duplicate_comps_metric_keys():
    workbook = Path("ciq/templates/ciq_cleandata.xlsx")
    payload = parse_ciq_workbook(workbook)

    ibm_rows = [r for r in payload.comps_snapshot if r.get("peer_ticker") == "IBM"]
    keys = {r.get("metric_key") for r in ibm_rows}

    assert "ebitda_ltm" in keys
    assert any(k and k.startswith("ebitda_ltm__") for k in keys)


def test_parse_ciq_workbook_excludes_1900_placeholder_period_columns(tmp_path):
    workbook = create_ibm_style_workbook(tmp_path / "PLACEHOLDER_1900.xlsx")
    wb = load_workbook(workbook)
    fs = wb["Financial Statements"]
    cs = wb["Common Size"]
    fs["D10"] = date(1900, 1, 1)
    cs["D10"] = date(1900, 1, 1)
    wb.save(workbook)

    payload = parse_ciq_workbook(workbook)

    fs_dates = {
        row["period_date"]
        for row in payload.long_form_records
        if row["sheet_name"] == "Financial Statements"
    }
    cs_dates = {
        row["period_date"]
        for row in payload.long_form_records
        if row["sheet_name"] == "Common Size"
    }

    assert "1900-01-01" not in fs_dates
    assert "1900-01-01" not in cs_dates
