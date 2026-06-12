from __future__ import annotations

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


def test_committed_cleandata_workbook_has_plausible_ciq_growth_snapshot() -> None:
    payload = parse_ciq_workbook("ciq/templates/ciq_cleandata.xlsx")
    snapshot = payload.valuation_snapshot

    assert snapshot["ticker"] == payload.ticker
    assert snapshot["revenue_mm"] is not None
    assert snapshot["revenue_cagr_3yr"] is not None
    assert -1.0 < snapshot["revenue_cagr_3yr"] < 1.0
