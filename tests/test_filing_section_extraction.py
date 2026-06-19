from __future__ import annotations

from pathlib import Path

import src.stage_00_data.filing_retrieval as fr


FIXTURES_DIR = Path(__file__).parent / "fixtures" / "filings"


def test_msft_10k_multiline_item_headings_do_not_extract_toc():
    text = (FIXTURES_DIR / "msft_2025_10k_multiline_items.txt").read_text(encoding="utf-8")
    sections = {key: section_text for key, _, section_text in fr._extract_sections_for_filing("10-K", text)}

    assert "business" in sections
    assert "risk_factors" in sections
    assert "mda" in sections
    assert "financial_statements" in sections
    assert "Cloud provides integration" in sections["business"]
    assert "Competition in cloud services" in sections["risk_factors"]
    assert "Revenue increased due to cloud services growth" in sections["mda"]
    assert "INDEX" not in sections["business"]


def test_msft_10q_multiline_item_headings_extract_mda_and_risk():
    text = (FIXTURES_DIR / "msft_2026_10q_multiline_items.txt").read_text(encoding="utf-8")
    sections = {key: section_text for key, _, section_text in fr._extract_sections_for_filing("10-Q", text)}

    assert "financial_statements_q" in sections
    assert "notes_to_financials_q" in sections
    assert "mda_q" in sections
    assert "risk_factors_q" in sections
    assert "Cloud revenue increased" in sections["mda_q"]
    assert "no material changes to the risk factors" in sections["risk_factors_q"]


def test_iesc_10k_standard_item_headings_still_extract_notes():
    text = (FIXTURES_DIR / "iesc_2025_10k_standard_items.txt").read_text(encoding="utf-8")
    sections = {key: section_text for key, _, section_text in fr._extract_sections_for_filing("10-K", text)}

    assert "business" in sections
    assert "risk_factors" in sections
    assert "mda" in sections
    assert "notes_to_financials" in sections
    assert "electrical contracting" in sections["business"]
    assert "project execution" in sections["mda"]
