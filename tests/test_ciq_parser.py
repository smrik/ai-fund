import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest

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
